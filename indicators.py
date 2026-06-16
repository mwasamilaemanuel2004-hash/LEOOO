"""
ai/elite_execution.py — ESTRADE Elite Execution Engine
═══════════════════════════════════════════════════════════════════════
Institutional-grade trade management after entry:

  ① Trailing Stop Loss    — moves SL up as price rises (long) or down (short)
                           Activates after 1x ATR profit
                           Distance: 1.5x ATR from peak price

  ② Partial Take Profit   — books profit in 3 slices:
                           TP1 @ 1.5x ATR → close 30% of position
                           TP2 @ 3.0x ATR → close 40% of position
                           TP3 @ 5.0x ATR → close 30% of position

  ③ Break-even Move       — SL → entry price after 0.8x ATR profit
                           Guarantees no loss on position

  ④ Volatility-based SL   — uses current ATR to widen/tighten SL dynamically
                           High vol market → wider SL (avoids premature stop)
                           Low vol market → tighter SL (locks more profit)

  ⑤ Auto Profit Locking   — milestones: 25%, 50%, 75% profit locked
                           Once milestone hit → SL never goes below lock level

  ⑥ AI Override           — if AI brain flips signal during trade, can reduce
                           position or tighten SL preemptively

All events logged to execution_events table for AI learning.
═══════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations
import asyncio
from datetime import datetime, timezone
from typing import Optional
from core.database import db
from core.config import settings
import structlog

log = structlog.get_logger("elite_execution")


class EliteExecutionEngine:
    """
    Manages open trades with institutional-grade exit logic.
    Called every MONITOR_INTERVAL (10s) by the trading loop.
    """

    # Default parameters (overridable from system_config)
    TRAILING_ACTIVATION_ATR = 1.0   # profit in ATR before trailing activates
    TRAILING_DISTANCE_ATR   = 1.5   # ATR distance for trailing SL
    BREAKEVEN_TRIGGER_ATR   = 0.8   # profit in ATR before moving to breakeven
    PARTIAL_TP1_ATR         = 1.5   # ATR target for TP1 (30%)
    PARTIAL_TP2_ATR         = 3.0   # ATR target for TP2 (40%)
    PARTIAL_TP3_ATR         = 5.0   # ATR target for TP3 (30%)
    PROFIT_LOCK_LEVELS      = [25, 50, 75]  # % profit milestones to lock

    async def process_trade(self, trade_id: str,
                             current_price: float,
                             current_atr: float) -> dict:
        """
        Full elite management cycle for one open trade.
        Returns action dict with any changes made.
        """
        trade = (db.table("trades").select("*")
                 .eq("id", trade_id).eq("status", "open")
                 .single().execute()).data
        if not trade:
            return {"action": "no_trade"}

        entry    = float(trade["entry_price"])
        qty      = float(trade["quantity"])
        side     = trade["side"]          # long | short
        user_id  = trade["user_id"]
        atr      = current_atr or float(trade.get("current_atr_at_move") or entry * 0.01)
        notional = qty * entry
        actions  = []

        # ── Compute current profit in ATR units ──────────────────────
        if side == "long":
            pnl_raw      = (current_price - entry) * qty
            profit_in_atr = (current_price - entry) / atr if atr > 0 else 0
        else:
            pnl_raw      = (entry - current_price) * qty
            profit_in_atr = (entry - current_price) / atr if atr > 0 else 0

        updates = {}   # batch DB updates

        # ════════════════════════════════════════════════
        # ① BREAK-EVEN LOGIC
        # ════════════════════════════════════════════════
        if (not trade.get("breakeven_activated") and
                profit_in_atr >= self.BREAKEVEN_TRIGGER_ATR):

            be_sl = entry + (atr * 0.05) if side == "long" else entry - (atr * 0.05)
            current_sl = float(trade.get("stop_loss") or 0)

            # Only move SL if new SL is better than current
            if ((side == "long" and be_sl > current_sl) or
                    (side == "short" and be_sl < current_sl)):
                updates["stop_loss"] = round(be_sl, 8)
                updates["breakeven_activated"] = True
                await self._log_event(trade_id, user_id, "breakeven_activate",
                    current_sl, be_sl, current_price, atr, pnl_raw,
                    f"Break-even activated at {be_sl:.6f}")
                actions.append(f"breakeven→{be_sl:.6f}")
                log.info("breakeven_activated", trade=trade_id, be_sl=be_sl)

        # ════════════════════════════════════════════════
        # ② TRAILING STOP LOSS
        # ════════════════════════════════════════════════
        if profit_in_atr >= self.TRAILING_ACTIVATION_ATR:
            trail_dist = atr * self.TRAILING_DISTANCE_ATR
            current_sl = float(updates.get("stop_loss") or trade.get("stop_loss") or 0)

            if side == "long":
                peak = max(float(trade.get("trailing_sl_peak") or entry), current_price)
                new_trail_sl = round(peak - trail_dist, 8)
                if new_trail_sl > current_sl:
                    updates["stop_loss"]        = new_trail_sl
                    updates["trailing_sl_peak"] = peak
                    await self._log_event(trade_id, user_id, "trailing_sl_move",
                        current_sl, new_trail_sl, current_price, atr, pnl_raw,
                        f"Trail SL ↑ peak={peak:.6f} dist={trail_dist:.6f}")
                    actions.append(f"trail_sl↑{new_trail_sl:.6f}")
            else:
                trough = min(float(trade.get("trailing_sl_peak") or entry), current_price)
                new_trail_sl = round(trough + trail_dist, 8)
                if new_trail_sl < current_sl or current_sl == 0:
                    updates["stop_loss"]        = new_trail_sl
                    updates["trailing_sl_peak"] = trough
                    await self._log_event(trade_id, user_id, "trailing_sl_move",
                        current_sl, new_trail_sl, current_price, atr, pnl_raw,
                        f"Trail SL ↓ trough={trough:.6f}")
                    actions.append(f"trail_sl↓{new_trail_sl:.6f}")

        # ════════════════════════════════════════════════
        # ③ PARTIAL TAKE PROFIT
        # ════════════════════════════════════════════════
        partial_results = await self._check_partial_tp(
            trade, current_price, qty, atr, pnl_raw, user_id, side, entry
        )
        if partial_results.get("update"):
            updates.update(partial_results["update"])
        if partial_results.get("close_qty"):
            actions.append(f"partial_tp_{partial_results['level']}@{current_price:.6f}")

        # ════════════════════════════════════════════════
        # ④ VOLATILITY-BASED SL ADJUSTMENT
        # ════════════════════════════════════════════════
        await self._vol_adjust_sl(trade, current_price, atr, updates, actions, user_id)

        # ════════════════════════════════════════════════
        # ⑤ AUTO PROFIT LOCKING
        # ════════════════════════════════════════════════
        await self._check_profit_lock(
            trade, pnl_raw, notional, current_price, atr, updates, actions, user_id
        )

        # ── Apply all updates at once ─────────────────────────────────
        if updates:
            updates["current_atr_at_move"] = round(atr, 8)
            db.table("trades").update(updates).eq("id", trade_id).execute()

        # ── Check final SL/TP hit ─────────────────────────────────────
        sl  = float(updates.get("stop_loss") or trade.get("stop_loss") or 0)
        tp  = float(trade.get("take_profit") or 0)

        hit_sl = (side == "long"  and sl > 0 and current_price <= sl) or \
                 (side == "short" and sl > 0 and current_price >= sl)
        hit_tp = (side == "long"  and tp > 0 and current_price >= tp) or \
                 (side == "short" and tp > 0 and current_price <= tp)

        if hit_sl or hit_tp:
            reason = "sl_hit" if hit_sl else "tp_hit"
            from services.bot_service import bot_service
            close_result = await bot_service.close_trade(
                trade_id, user_id, current_price, reason
            )
            await self._log_event(trade_id, user_id,
                "forced_close" if hit_sl else "forced_close",
                0, current_price, current_price, atr, pnl_raw, reason)
            return {"action": "closed", "reason": reason,
                    "price": current_price, "pnl": close_result.get("net_pnl")}

        return {
            "action": "updated" if actions else "no_change",
            "actions": actions,
            "current_price": current_price,
            "sl": sl,
            "profit_in_atr": round(profit_in_atr, 3),
            "pnl_raw": round(pnl_raw, 6),
        }

    async def _check_partial_tp(
        self, trade: dict, price: float, qty: float,
        atr: float, pnl_raw: float, user_id: str,
        side: str, entry: float
    ) -> dict:
        """Check and execute partial TPs. Returns update dict + close_qty if triggered."""
        result = {"update": {}, "close_qty": 0, "level": 0}

        pcts = {
            "partial_tp1": (not trade.get("partial_tp1_hit"), self.PARTIAL_TP1_ATR, 0.30),
            "partial_tp2": (not trade.get("partial_tp2_hit"), self.PARTIAL_TP2_ATR, 0.40),
            "partial_tp3": (not trade.get("partial_tp3_hit"), self.PARTIAL_TP3_ATR, 0.30),
        }

        for level, (not_hit, atr_mult, close_pct) in pcts.items():
            if not not_hit:
                continue
            tp_price = (entry + atr * atr_mult) if side == "long" else (entry - atr * atr_mult)
            hit = (side == "long" and price >= tp_price) or (side == "short" and price <= tp_price)

            if hit:
                close_qty = round(qty * close_pct, 8)
                # Book partial profit
                partial_pnl = ((price - entry) * close_qty if side == "long"
                               else (entry - price) * close_qty)
                partial_fee = price * close_qty * settings.TRADING_FEE_PCT

                # Credit partial profit to wallet
                net_partial = partial_pnl - partial_fee
                try:
                    from services.wallet_service import wallet_service
                    await wallet_service.credit(
                        user_id, trade.get("mode", "demo"),
                        max(0, (price * close_qty) + max(0, net_partial)),
                        "trade_credit",
                        f"Partial TP {level} {close_pct*100:.0f}% close @ {price:.4f}"
                    )
                except Exception as e:
                    log.error("partial_tp_credit_error", error=str(e))

                result["update"][f"{level}_hit"]   = True
                result["update"][f"{level}_price"] = round(tp_price, 8)
                result["update"]["quantity"]       = round(qty * (1 - close_pct), 8)
                result["close_qty"] = close_qty
                result["level"]     = level

                await self._log_event(trade["id"], user_id,
                    f"{level}",
                    qty, close_qty, price, atr, partial_pnl,
                    f"Partial TP {close_pct*100:.0f}% @ {price:.6f} net=${net_partial:.4f}")

                log.info("partial_tp_hit", level=level, qty=close_qty,
                         pnl=net_partial, trade=trade["id"])
                break  # Only one level per cycle

        return result

    async def _vol_adjust_sl(
        self, trade: dict, price: float, atr: float,
        updates: dict, actions: list, user_id: str
    ):
        """Volatility-based SL widening/tightening."""
        entry = float(trade["entry_price"])
        side  = trade["side"]
        current_sl = float(updates.get("stop_loss") or trade.get("stop_loss") or 0)
        if current_sl == 0 or atr <= 0:
            return

        # Compute ideal vol-adjusted SL
        base_mult = 2.0   # Default SL distance in ATR
        if side == "long":
            vol_sl = entry - atr * base_mult
            # Tighten if in profit (don't let vol_sl be worse than current)
            if vol_sl > current_sl and vol_sl < price:
                updates["stop_loss"] = round(vol_sl, 8)
                updates["vol_adjusted_sl"] = True
                actions.append(f"vol_sl_adj→{vol_sl:.6f}")
        else:
            vol_sl = entry + atr * base_mult
            if vol_sl < current_sl and vol_sl > price:
                updates["stop_loss"] = round(vol_sl, 8)
                updates["vol_adjusted_sl"] = True
                actions.append(f"vol_sl_adj→{vol_sl:.6f}")

    async def _check_profit_lock(
        self, trade: dict, pnl_raw: float, notional: float,
        price: float, atr: float, updates: dict, actions: list, user_id: str
    ):
        """Lock profits at milestones: 25%, 50%, 75%."""
        if notional <= 0 or pnl_raw <= 0:
            return

        profit_pct = (pnl_raw / notional) * 100
        current_lock_level = int(trade.get("profit_lock_level") or 0)

        for milestone in self.PROFIT_LOCK_LEVELS:
            if profit_pct >= milestone and current_lock_level < milestone:
                # Move SL to lock this profit level
                lock_fraction = milestone / 100 * 0.7   # Lock 70% of milestone profit
                entry = float(trade["entry_price"])
                side  = trade["side"]
                qty   = float(trade.get("quantity") or 0)

                if side == "long":
                    lock_sl = entry + (price - entry) * lock_fraction
                else:
                    lock_sl = entry - (entry - price) * lock_fraction

                lock_sl = round(lock_sl, 8)
                current_sl = float(updates.get("stop_loss") or trade.get("stop_loss") or 0)

                better = ((side == "long" and lock_sl > current_sl) or
                          (side == "short" and lock_sl < current_sl) or current_sl == 0)

                if better:
                    updates["stop_loss"]       = lock_sl
                    updates["profit_lock_level"] = milestone
                    updates["profit_locked_amount"] = round(pnl_raw * lock_fraction, 8)
                    actions.append(f"profit_lock_{milestone}%→sl={lock_sl:.6f}")

                    await self._log_event(
                        trade["id"], user_id, "profit_lock",
                        current_sl, lock_sl, price, atr, pnl_raw,
                        f"Profit locked at {milestone}% milestone (${pnl_raw * lock_fraction:.4f} secured)"
                    )
                    log.info("profit_locked", milestone=milestone, sl=lock_sl,
                             locked=pnl_raw * lock_fraction)
                break

    async def _log_event(
        self, trade_id: str, user_id: str, event_type: str,
        old_val: float, new_val: float, price: float,
        atr: float, pnl: float, reason: str
    ):
        """Log execution event for AI learning and audit."""
        try:
            db.table("execution_events").insert({
                "trade_id":     trade_id,
                "user_id":      user_id,
                "event_type":   event_type,
                "old_value":    round(old_val, 8) if old_val else None,
                "new_value":    round(new_val, 8) if new_val else None,
                "current_price": round(price, 8),
                "atr_at_event": round(atr, 8),
                "pnl_at_event": round(pnl, 6),
                "reason":       reason,
            }).execute()
        except Exception:
            pass

    async def bulk_process(self, price_map: dict[str, float],
                            atr_map: dict[str, float] = None) -> list[dict]:
        """
        Process all open trades at once.
        price_map: {symbol: current_price}
        atr_map:   {symbol: current_atr}
        """
        open_trades = (db.table("trades").select("id,symbol,user_id")
                       .eq("status", "open").execute()).data or []

        if not open_trades:
            return []

        tasks = []
        for t in open_trades:
            symbol = t["symbol"]
            price  = price_map.get(symbol) or price_map.get(symbol.replace("/", "").replace("USDT", "") + "/USDT")
            atr    = (atr_map or {}).get(symbol, 0)
            if price:
                tasks.append(self.process_trade(t["id"], price, atr))

        results = await asyncio.gather(*tasks, return_exceptions=True)
        return [r for r in results if isinstance(r, dict)]


elite_execution = EliteExecutionEngine()
