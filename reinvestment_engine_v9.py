"""
services/copy_trading_service.py — Institutional Copy Trading Engine
When a master executes a trade → all active followers auto-mirror it.
Platform takes a cut of master's performance fee.
"""
from __future__ import annotations
from datetime import datetime, timezone
from core.database import db
from core.config import settings
import structlog, asyncio

log = structlog.get_logger("copy_trading")


class CopyTradingService:

    async def mirror_trade(self, master_user_id: str, master_trade_id: str,
                            signal: dict) -> list[dict]:
        """
        Mirror a master's trade to all active followers.
        Called immediately after master trade opens.
        Returns list of follower execution results.
        """
        # Get master profile
        master = (db.table("copy_masters")
                  .select("*").eq("user_id", master_user_id)
                  .eq("is_active", True).single().execute()).data
        if not master:
            return []

        # Get all active followers
        followers = (db.table("copy_followers")
                     .select("*, users!copy_followers_follower_id_fkey(id,trading_enabled)")
                     .eq("master_id", master["id"])
                     .eq("status", "active").execute()).data or []

        if not followers:
            return []

        results = []
        tasks = [self._execute_for_follower(f, master, master_trade_id, signal)
                 for f in followers]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Update master AUM and follower count
        total_aum = sum(
            float(f.get("allocated_usd", 0)) for f in followers
        )
        db.table("copy_masters").update({
            "total_followers": len(followers),
            "total_aum": total_aum,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", master["id"]).execute()

        return [r for r in results if isinstance(r, dict)]

    async def _execute_for_follower(self, follower: dict, master: dict,
                                     master_trade_id: str, signal: dict) -> dict:
        """Execute a single copy trade for a follower."""
        follower_id = follower["follower_id"]

        try:
            # Check follower is allowed to trade
            user = follower.get("users") or {}
            if not user.get("trading_enabled", True):
                return {"follower": follower_id, "skipped": "trading_disabled"}

            # Check stop-loss circuit breaker for follower
            total_pnl     = float(follower.get("total_pnl", 0))
            allocated     = float(follower.get("allocated_usd", 0))
            stop_loss_pct = float(follower.get("stop_loss_pct", 20))
            if allocated > 0 and (-total_pnl / allocated * 100) >= stop_loss_pct:
                # Auto-stop follower
                db.table("copy_followers").update({
                    "status": "stopped"
                }).eq("id", follower["id"]).execute()
                await self._notify_follower(follower_id, "copy_stopped",
                    "Copy trading auto-stopped", f"Max loss reached ({stop_loss_pct}%)")
                return {"follower": follower_id, "skipped": "stop_loss_hit"}

            # Scale position by copy ratio
            copy_ratio  = float(follower.get("copy_ratio", 1.0))
            master_size = float(signal.get("notional", 0)) or allocated * 0.02
            follower_size = min(
                master_size * copy_ratio,
                float(follower.get("max_trade_size") or master_size * copy_ratio),
                allocated * 0.25,   # Never more than 25% of allocated in one trade
            )

            if follower_size < 1.0:
                return {"follower": follower_id, "skipped": "size_too_small"}

            # Get follower wallet
            wallet = await db.get_wallet(follower_id, "real")
            if not wallet:
                wallet = await db.get_wallet(follower_id, "demo")
            if not wallet:
                return {"follower": follower_id, "skipped": "no_wallet"}

            available = float(wallet["balance"]) - float(wallet["locked_balance"])
            if available < follower_size:
                follower_size = min(available * 0.95, follower_size)
                if follower_size < 1.0:
                    return {"follower": follower_id, "skipped": "insufficient_balance"}

            # Create the copied trade
            entry_price = float(signal.get("entry_price", 0))
            qty = follower_size / entry_price if entry_price > 0 else 0

            follower_trade = db.table("trades").insert({
                "bot_id": None,
                "user_id": follower_id,
                "signal_id": signal.get("signal_id"),
                "symbol": signal.get("pair", signal.get("symbol", "")),
                "side": signal.get("direction", "long"),
                "mode": wallet.get("wallet_type", "demo"),
                "strategy": f"copy_trade:{master.get('display_name', 'master')}",
                "entry_price": entry_price,
                "quantity": round(qty, 8),
                "notional_value": round(follower_size, 4),
                "stop_loss": signal.get("stop_loss"),
                "take_profit": signal.get("take_profit"),
                "status": "open",
            }).execute()

            if not follower_trade.data:
                return {"follower": follower_id, "error": "trade_insert_failed"}

            follower_trade_id = follower_trade.data[0]["id"]

            # Record copied trade link
            db.table("copied_trades").insert({
                "follower_id": follower_id,
                "master_id": master["id"],
                "master_trade_id": master_trade_id,
                "follower_trade_id": follower_trade_id,
                "symbol": signal.get("pair", ""),
                "direction": signal.get("direction", "long"),
                "copy_ratio": copy_ratio,
                "master_entry": entry_price,
                "follower_entry": entry_price,
                "status": "open",
            }).execute()

            # Update follower stats
            db.table("copy_followers").update({
                "total_copied": follower.get("total_copied", 0) + 1,
            }).eq("id", follower["id"]).execute()

            # Notify follower
            await self._notify_follower(follower_id, "copy_trade",
                f"Copy trade opened: {signal.get('direction','').upper()} {signal.get('pair','')}",
                f"Following {master.get('display_name')} | Size: ${follower_size:.2f}")

            log.info("copy_trade_mirrored", follower=follower_id,
                     master=master_user_id, symbol=signal.get("pair"))

            return {
                "follower": follower_id,
                "follower_trade_id": follower_trade_id,
                "size": round(follower_size, 4),
                "success": True,
            }

        except Exception as e:
            log.error("copy_trade_error", follower=follower_id, error=str(e))
            return {"follower": follower_id, "error": str(e)}

    async def close_copied_trades(self, master_trade_id: str,
                                   exit_price: float, pnl_pct: float):
        """Close all copied trades when master closes."""
        copied = (db.table("copied_trades")
                  .select("*")
                  .eq("master_trade_id", master_trade_id)
                  .eq("status", "open").execute()).data or []

        for ct in copied:
            follower_trade_id = ct.get("follower_trade_id")
            if not follower_trade_id:
                continue

            # Close follower trade
            trade = (db.table("trades")
                     .select("*").eq("id", follower_trade_id)
                     .single().execute()).data
            if not trade or trade["status"] != "open":
                continue

            entry  = float(trade.get("entry_price", exit_price))
            qty    = float(trade.get("quantity", 0))
            side   = trade["side"]
            gross  = ((exit_price - entry) * qty if side == "long"
                      else (entry - exit_price) * qty)
            fee    = float(trade.get("notional_value", qty * exit_price)) * settings.TRADING_FEE_PCT
            net    = gross - fee

            db.table("trades").update({
                "exit_price": exit_price,
                "gross_pnl": round(gross, 8),
                "net_pnl": round(net, 8),
                "status": "closed",
                "closed_at": datetime.now(timezone.utc).isoformat(),
            }).eq("id", follower_trade_id).execute()

            # Performance fee: master takes % of follower's profit
            if net > 0:
                perf_fee_pct = float(ct.get("performance_fee_pct") or 10) / 100
                platform_cut = 0.05   # Platform takes 5% of master's cut
                master_fee   = net * perf_fee_pct * (1 - platform_cut)
                platform_fee = net * perf_fee_pct * platform_cut

                # Deduct from follower
                from services.wallet_service import wallet_service
                try:
                    await wallet_service.debit(
                        ct["follower_id"], trade["mode"],
                        master_fee + platform_fee,
                        f"Copy trade performance fee to {ct.get('master_id','')}",
                        ref_id=ct["id"], ref_type="copied_trade"
                    )
                    # Credit master
                    await wallet_service.credit(
                        (db.table("copy_masters").select("user_id")
                         .eq("id", ct["master_id"]).single().execute()).data["user_id"],
                        trade["mode"], master_fee, "trade_credit",
                        f"Performance fee from copy follower"
                    )
                except Exception:
                    pass

            # Update copied_trade record
            db.table("copied_trades").update({
                "follower_pnl": round(net, 8),
                "master_pnl": round(gross * pnl_pct, 8),
                "status": "closed",
                "closed_at": datetime.now(timezone.utc).isoformat(),
            }).eq("id", ct["id"]).execute()

            # Update follower totals
            db.table("copy_followers").update({
                "total_pnl": float(db.table("copy_followers")
                                   .select("total_pnl").eq("follower_id", ct["follower_id"])
                                   .single().execute().data.get("total_pnl", 0)) + net,
            }).eq("follower_id", ct["follower_id"]).eq("master_id", ct["master_id"]).execute()

    async def _notify_follower(self, user_id: str, notif_type: str,
                                title: str, body: str):
        try:
            db.table("notifications").insert({
                "user_id": user_id,
                "type": notif_type,
                "title": title,
                "body": body,
                "priority": "normal",
            }).execute()
        except Exception:
            pass

    async def get_leaderboard(self, period: str = "monthly") -> list:
        return (db.table("leaderboard")
                .select("*")
                .eq("period", period)
                .eq("is_public", True)
                .order("rank")
                .limit(50)
                .execute()).data or []

    async def refresh_leaderboard(self):
        """Recompute leaderboard from recent trade performance."""
        for period in ("weekly", "monthly", "all_time"):
            trades = (db.table("trades")
                      .select("user_id, net_pnl, status")
                      .eq("status", "closed")
                      .eq("mode", "live")
                      .execute()).data or []

            by_user: dict = {}
            for t in trades:
                uid = t["user_id"]
                if uid not in by_user:
                    by_user[uid] = {"pnl": 0, "trades": 0, "wins": 0}
                by_user[uid]["pnl"] += float(t.get("net_pnl") or 0)
                by_user[uid]["trades"] += 1
                if float(t.get("net_pnl") or 0) > 0:
                    by_user[uid]["wins"] += 1

            ranked = sorted(by_user.items(), key=lambda x: x[1]["pnl"], reverse=True)

            for rank, (uid, stats) in enumerate(ranked[:100], 1):
                user = await db.get_user(uid)
                if not user:
                    continue
                wr = stats["wins"] / max(stats["trades"], 1)
                db.table("leaderboard").upsert({
                    "user_id": uid,
                    "display_name": user.get("full_name") or user["email"][:12],
                    "period": period,
                    "rank": rank,
                    "total_pnl": round(stats["pnl"], 4),
                    "win_rate": round(wr, 4),
                    "total_trades": stats["trades"],
                    "roi_pct": round(stats["pnl"] / 1000, 6),   # normalize to initial capital
                    "computed_at": datetime.now(timezone.utc).isoformat(),
                }, on_conflict="user_id,period").execute()


copy_trading_service = CopyTradingService()
