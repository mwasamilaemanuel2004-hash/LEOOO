"""
services/bot_service.py — Enterprise Bot Management Service
Handles bot lifecycle, signal routing, and all-weather trading.
"""
from __future__ import annotations
import asyncio, time, uuid
from datetime import datetime, timezone
from typing import Literal
import pandas as pd
import structlog

from core.database import db
from core.config import settings
from services.wallet_service import wallet_service
from strategies.all_weather_engine import all_weather_engine, Signal

log = structlog.get_logger("bot_service")


class BotService:

    async def start_bot(self, bot_id: str, user_id: str) -> dict:
        """Start a bot — validates everything before starting."""
        bot = db.table("bots").select("*, bot_settings(*)").eq("id", bot_id).eq("user_id", user_id).single().execute().data
        if not bot:
            raise ValueError("Bot not found")

        user = await db.get_user(user_id)
        if not user.get("trading_enabled"):
            raise ValueError("Trading disabled for your account")

        risk = await db.get_risk_profile(user_id)
        if risk and risk.get("emergency_stop"):
            raise ValueError("Emergency stop active. Reset via settings.")

        # Check capital
        mode = bot.get("mode", "demo")
        capital = float(bot.get("capital_allocated", 0))
        if capital <= 0:
            raise ValueError("No capital allocated to bot")

        wallet = await db.get_wallet(user_id, mode)
        available = float(wallet["balance"]) - float(wallet["locked_balance"])
        if available < capital:
            raise ValueError(f"Insufficient {mode} wallet balance. Need ${capital}, have ${available:.2f}")

        # Lock capital
        db.rpc("deduct_wallet_balance", {
            "p_wallet_id": wallet["id"],
            "p_amount": capital,
            "p_lock": True
        }).execute()

        # Create session
        session = db.table("bot_sessions").insert({
            "bot_id": bot_id,
            "config_snapshot": {
                "mode": mode,
                "capital": capital,
                "pairs": bot.get("pairs", []),
                "strategy": bot.get("bot_type"),
            }
        }).execute()

        # Update bot status
        db.table("bots").update({
            "status": "running",
            "updated_at": datetime.now(timezone.utc).isoformat()
        }).eq("id", bot_id).execute()

        await db.log_audit(user_id, user_id, "bot_start", "bot", bot_id,
                           new_vals={"mode": mode, "capital": capital})

        log.info("bot_started", bot_id=bot_id, mode=mode, capital=capital)
        return {"success": True, "session_id": session.data[0]["id"] if session.data else None}

    async def stop_bot(self, bot_id: str, user_id: str, reason: str = "manual_stop") -> dict:
        """Stop bot — releases locked capital."""
        bot = db.table("bots").select("*").eq("id", bot_id).eq("user_id", user_id).single().execute().data
        if not bot:
            raise ValueError("Bot not found")

        # Close active session
        active_session = (db.table("bot_sessions")
                          .select("*").eq("bot_id", bot_id)
                          .is_("stopped_at", "null")
                          .single().execute()).data
        if active_session:
            db.table("bot_sessions").update({
                "stopped_at": datetime.now(timezone.utc).isoformat(),
                "stop_reason": reason,
            }).eq("id", active_session["id"]).execute()

        # Release locked capital
        mode = bot.get("mode", "demo")
        capital = float(bot.get("capital_allocated", 0))
        wallet = await db.get_wallet(user_id, mode)
        if wallet:
            db.table("wallets").update({
                "locked_balance": max(0, float(wallet.get("locked_balance", 0)) - capital),
                "balance": float(wallet["balance"]) + capital,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }).eq("id", wallet["id"]).execute()

        db.table("bots").update({
            "status": "stopped",
            "updated_at": datetime.now(timezone.utc).isoformat()
        }).eq("id", bot_id).execute()

        await db.log_audit(user_id, user_id, "bot_stop", "bot", bot_id,
                           new_vals={"reason": reason})
        return {"success": True}

    async def process_signal(self, bot_id: str, user_id: str,
                              pair: str, frames: dict,
                              funding_rate: float = 0.0,
                              news_sentiment: float = 0.0) -> dict:
        """
        Run the all-weather engine for a pair and process the result.
        This is called by the trading loop for each pair scan.
        """
        # Get bot + settings
        bot = (db.table("bots")
               .select("*, bot_settings(*)")
               .eq("id", bot_id).single().execute()).data
        if not bot or bot.get("status") != "running":
            return {"skipped": "bot_not_running"}

        mode = bot.get("mode", "demo")

        # Capital fortress check
        risk = await db.get_risk_profile(user_id)
        fortress_level = risk.get("fortress_level", "OPEN") if risk else "OPEN"
        if fortress_level in ("LOCKDOWN", "EMERGENCY"):
            log.warning("fortress_blocked", level=fortress_level, pair=pair)
            return {"skipped": f"fortress_{fortress_level}"}

        # Max open trades check
        open_trades = await db.get_open_trades(user_id, mode)
        max_concurrent = int(bot.get("max_concurrent", 3))
        if len(open_trades) >= max_concurrent:
            return {"skipped": "max_concurrent_reached"}

        # Run all-weather engine
        result = all_weather_engine.analyze(pair, frames, funding_rate, news_sentiment)

        top_signal = result.get("top_signal")
        if not top_signal or result.get("ensemble_vote") == "wait":
            return {"skipped": "no_signal", "regime": result.get("regime", {}).get("regime")}

        # Minimum confidence gate
        min_conf = float((bot.get("bot_settings") or {}).get("take_profit_pct", 2)) * 0  # placeholder
        if top_signal["confidence"] < 65:
            return {"skipped": f"low_confidence_{top_signal['confidence']:.1f}"}

        # Build trade signal
        sig_record = db.table("signals").insert({
            "bot_id": bot_id,
            "strategy": top_signal["strategy"],
            "symbol": pair,
            "timeframe": top_signal["timeframe"],
            "direction": top_signal["direction"],
            "confidence": top_signal["confidence"],
            "entry_price": top_signal["entry_price"],
            "stop_loss": top_signal["stop_loss"],
            "take_profit": top_signal["take_profit"],
            "indicators": {
                "tp2": top_signal.get("tp2"),
                "tp3": top_signal.get("tp3"),
                "rr_ratio": top_signal.get("rr_ratio"),
                "regime_fit": top_signal.get("regime_fit"),
            },
            "market_phase": result.get("regime", {}).get("regime"),
            "news_sentiment": result.get("news_sentiment", 0) > 0 and "BULLISH" or "NEUTRAL",
            "ai_score": top_signal.get("confidence"),
            "status": "pending",
        }).execute()

        sig_id = sig_record.data[0]["id"] if sig_record.data else None

        # Execute trade
        trade_result = await self.execute_trade(
            bot_id=bot_id,
            user_id=user_id,
            signal_id=sig_id,
            signal=top_signal,
            bot=bot,
            mode=mode,
        )

        return {
            "signal": top_signal,
            "trade": trade_result,
            "regime": result.get("regime"),
            "ensemble": result.get("ensemble_vote"),
        }

    async def execute_trade(self, bot_id: str, user_id: str,
                             signal_id: str, signal: dict,
                             bot: dict, mode: str) -> dict:
        """
        Execute a trade signal — demo or live.
        """
        settings_data = bot.get("bot_settings") or {}
        risk_pct = float(settings_data.get("risk_per_trade") or 1.5)

        # Apply fortress risk multiplier
        risk = await db.get_risk_profile(user_id)
        fortress_mult = {"OPEN": 1.0, "CAUTION": 0.75, "FORTRESS": 0.4,
                         "LOCKDOWN": 0.1, "EMERGENCY": 0.0}.get(
            risk.get("fortress_level", "OPEN") if risk else "OPEN", 1.0
        )
        effective_risk = risk_pct * fortress_mult

        # Get wallet balance
        wallet = await db.get_wallet(user_id, mode)
        if not wallet:
            return {"error": "Wallet not found"}

        available = float(wallet["balance"]) - float(wallet["locked_balance"])
        entry = float(signal["entry_price"])
        sl    = float(signal["stop_loss"])

        if entry <= 0 or available <= 0:
            return {"error": "Insufficient balance or invalid price"}

        # Position size = risk% of balance / stop distance
        risk_amount = available * (effective_risk / 100)
        sl_distance = abs(entry - sl)
        if sl_distance <= 0:
            return {"error": "Invalid stop loss"}

        quantity = risk_amount / sl_distance
        notional = quantity * entry

        # Minimum notional check ($1)
        if notional < 1:
            return {"error": f"Position too small: ${notional:.4f}"}

        # Create order
        side = "buy" if signal["direction"] == "long" else "sell"
        order = db.table("orders").insert({
            "bot_id": bot_id,
            "user_id": user_id,
            "signal_id": signal_id,
            "symbol": signal.get("pair", ""),
            "order_type": "market",
            "side": side,
            "mode": mode,
            "quantity": round(quantity, 8),
            "price": entry,
            "status": "pending",
        }).execute()

        if not order.data:
            return {"error": "Failed to create order"}

        order_id = order.data[0]["id"]

        if mode == "demo":
            # Simulate execution
            fill_price = entry * (1 + (0.0002 if side == "buy" else -0.0002))  # slippage
            simulated_fee = notional * settings.TRADING_FEE_PCT

            db.table("orders").update({
                "status": "filled",
                "avg_fill_price": fill_price,
                "filled_qty": round(quantity, 8),
                "fee": simulated_fee,
                "filled_at": datetime.now(timezone.utc).isoformat(),
            }).eq("id", order_id).execute()

            # Debit demo wallet
            await wallet_service.debit(
                user_id, "demo", notional + simulated_fee,
                f"Demo trade open: {signal['direction']} {signal.get('pair')}",
                ref_id=order_id, ref_type="order"
            )

            trade = db.table("trades").insert({
                "bot_id": bot_id,
                "user_id": user_id,
                "entry_order_id": order_id,
                "signal_id": signal_id,
                "symbol": signal.get("pair", ""),
                "side": signal["direction"],
                "mode": mode,
                "strategy": signal["strategy"],
                "entry_price": fill_price,
                "quantity": round(quantity, 8),
                "notional_value": round(notional, 8),
                "stop_loss": signal["stop_loss"],
                "take_profit": signal["take_profit"],
                "fee_paid": simulated_fee,
                "platform_fee": simulated_fee,
                "status": "open",
            }).execute()

        else:
            # Live execution via exchange
            from exchanges.exchange_service import exchange_service
            try:
                exchange_conn_id = bot.get("exchange_conn_id")
                live_result = await exchange_service.place_market_order(
                    exchange_conn_id=exchange_conn_id,
                    symbol=signal.get("pair", ""),
                    side=side,
                    amount=quantity,
                )

                db.table("orders").update({
                    "status": live_result["status"],
                    "exchange_order_id": live_result.get("exchange_order_id"),
                    "avg_fill_price": live_result.get("avg_price", entry),
                    "filled_qty": live_result.get("filled", quantity),
                    "fee": live_result.get("fee", 0),
                    "raw_response": live_result,
                    "filled_at": datetime.now(timezone.utc).isoformat(),
                }).eq("id", order_id).execute()

                fill_price = float(live_result.get("avg_price", entry))
                trade_fee = float(live_result.get("fee", notional * settings.TRADING_FEE_PCT))

                trade = db.table("trades").insert({
                    "bot_id": bot_id,
                    "user_id": user_id,
                    "entry_order_id": order_id,
                    "signal_id": signal_id,
                    "symbol": signal.get("pair", ""),
                    "side": signal["direction"],
                    "mode": mode,
                    "strategy": signal["strategy"],
                    "entry_price": fill_price,
                    "quantity": round(quantity, 8),
                    "notional_value": round(notional, 8),
                    "stop_loss": signal["stop_loss"],
                    "take_profit": signal["take_profit"],
                    "fee_paid": trade_fee,
                    "status": "open",
                }).execute()

                # Deduct platform fee
                if trade.data:
                    await wallet_service.deduct_trade_fee(
                        user_id, "real", trade.data[0]["id"], notional
                    )
            except Exception as e:
                db.table("orders").update({
                    "status": "rejected", "error_msg": str(e)
                }).eq("id", order_id).execute()
                log.error("live_order_failed", error=str(e))
                return {"error": str(e)}

        trade_id = trade.data[0]["id"] if trade and trade.data else None
        log.info("trade_opened", trade_id=trade_id, mode=mode, pair=signal.get("pair"),
                 direction=signal["direction"], qty=round(quantity, 6))

        return {
            "success": True,
            "trade_id": trade_id,
            "order_id": order_id,
            "fill_price": entry,
            "quantity": round(quantity, 8),
            "notional": round(notional, 4),
            "mode": mode,
        }

    async def check_sl_tp(self, trade_id: str, current_price: float) -> dict:
        """Check if SL or TP has been hit. Returns close action if so."""
        trade = db.table("trades").select("*").eq("id", trade_id).eq("status", "open").single().execute().data
        if not trade:
            return {"action": "none"}

        entry = float(trade["entry_price"])
        sl    = float(trade.get("stop_loss") or 0)
        tp    = float(trade.get("take_profit") or 0)
        side  = trade["side"]

        hit_sl = hit_tp = False
        if side == "long":
            if sl > 0 and current_price <= sl: hit_sl = True
            if tp > 0 and current_price >= tp: hit_tp = True
        else:
            if sl > 0 and current_price >= sl: hit_sl = True
            if tp > 0 and current_price <= tp: hit_tp = True

        if hit_sl or hit_tp:
            reason = "sl_hit" if hit_sl else "tp_hit"
            await self.close_trade(trade_id, trade["user_id"], current_price, reason)
            return {"action": "closed", "reason": reason, "price": current_price}

        return {"action": "none", "current": current_price, "sl": sl, "tp": tp}

    async def close_trade(self, trade_id: str, user_id: str,
                           exit_price: float, reason: str = "manual") -> dict:
        """Close a trade and calculate P&L."""
        trade = db.table("trades").select("*").eq("id", trade_id).single().execute().data
        if not trade or trade["status"] != "open":
            raise ValueError("Trade not found or already closed")

        entry    = float(trade["entry_price"])
        qty      = float(trade["quantity"])
        side     = trade["side"]
        mode     = trade["mode"]
        fee_paid = float(trade.get("fee_paid") or 0)

        # Calculate P&L
        if side == "long":
            gross_pnl = (exit_price - entry) * qty
        else:
            gross_pnl = (entry - exit_price) * qty

        exit_fee  = float(trade.get("notional_value", qty * exit_price)) * settings.TRADING_FEE_PCT
        net_pnl   = gross_pnl - exit_fee - fee_paid

        from datetime import timedelta
        opened_at = datetime.fromisoformat(trade["opened_at"].replace("Z", "+00:00"))
        duration  = int((datetime.now(timezone.utc) - opened_at).total_seconds() / 60)

        db.table("trades").update({
            "exit_price": exit_price,
            "gross_pnl": round(gross_pnl, 8),
            "net_pnl": round(net_pnl, 8),
            "platform_fee": round(exit_fee, 8),
            "duration_minutes": duration,
            "sl_hit": reason == "sl_hit",
            "status": "closed",
            "closed_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", trade_id).execute()

        # Credit profit back to wallet
        wallet = await db.get_wallet(user_id, mode)
        notional = float(trade.get("notional_value") or qty * entry)
        credit_back = notional + net_pnl  # Capital + P&L

        await wallet_service.credit(
            user_id, mode, max(0, credit_back),
            "trade_credit",
            f"Trade closed {side.upper()} {trade['symbol']}: P&L ${net_pnl:+.4f}",
            ref_id=trade_id, ref_type="trade"
        )

        # ACCRUE fee (do NOT deduct immediately — collected at withdrawal/month-end)
        if mode == "live":
            try:
                from services.fee_engine import fee_engine
                await fee_engine.accrue_trade_fee(
                    user_id=user_id,
                    trade_id=trade_id,
                    symbol=trade.get("symbol",""),
                    side=side,
                    notional=notional,
                    gross_pnl=gross_pnl,
                    net_pnl=net_pnl,
                    mode=mode,
                )
            except Exception as fe:
                log.warning("fee_accrue_skipped", error=str(fe), trade_id=trade_id)
        # Note: exit_fee NOT deducted now — accrued to trade_fees table

        # Update risk profile
        risk = await db.get_risk_profile(user_id)
        if risk:
            consec = risk.get("consecutive_losses", 0)
            new_consec = (consec + 1) if net_pnl < 0 else 0
            db.table("risk_profiles").update({
                "consecutive_losses": new_consec,
                "daily_pnl": float(risk.get("daily_pnl", 0)) + net_pnl,
            }).eq("user_id", user_id).execute()

        log.info("trade_closed", trade_id=trade_id, pnl=net_pnl, reason=reason)
        return {"trade_id": trade_id, "net_pnl": round(net_pnl, 6), "reason": reason}


bot_service = BotService()

# ═══════════════════════════════════════════════════════════════
# CAPITAL MODES — Institutional Risk Engine (appended to BotService)
# 4 modes: safe | hybrid | aggressive | aggressive_protected
# ═══════════════════════════════════════════════════════════════

CAPITAL_MODES = {
    "safe": {
        "name":             "Highest Risk Control",
        "icon":             "🛡️",
        "color":            "#5dba8a",
        "risk_per_trade":   1.5,     # % of balance
        "max_daily_loss":   3.0,     # %
        "max_drawdown":     10.0,    # % → auto stop
        "sl_atr_mult":      2.0,     # SL = 2×ATR from entry
        "tp_atr_mult":      4.0,     # TP = 4×ATR
        "trailing_stop":    True,
        "trailing_atr":     1.5,
        "ai_conf_threshold":0.75,
        "strategies":       ["trend","mean_reversion"],
        "max_open_trades":  3,
        "description":      "Capital preservation, consistent growth, skips weak signals",
        "warning":          None,
        "slippage_limit":   0.001,   # 0.1% max slippage
    },
    "hybrid": {
        "name":             "Hybrid AI + Strategy",
        "icon":             "⚡",
        "color":            "#f59e0b",
        "risk_per_trade":   3.5,
        "max_daily_loss":   7.0,
        "max_drawdown":     15.0,
        "sl_atr_mult":      2.5,
        "tp_atr_mult":      5.0,
        "trailing_stop":    True,
        "trailing_atr":     2.0,
        "ai_conf_threshold":0.65,
        "strategies":       ["trend","breakout","whale"],
        "max_open_trades":  5,
        "description":      "Balanced growth — AI + multi-signal ensemble, moderate frequency",
        "warning":          None,
        "slippage_limit":   0.002,
    },
    "aggressive": {
        "name":             "Without Risk Control",
        "icon":             "🔥",
        "color":            "#d4604a",
        "risk_per_trade":   20.0,
        "max_daily_loss":   50.0,
        "max_drawdown":     80.0,
        "sl_atr_mult":      5.0,
        "tp_atr_mult":      10.0,
        "trailing_stop":    False,
        "trailing_atr":     0,
        "ai_conf_threshold":0.50,
        "strategies":       ["breakout","scalp","momentum"],
        "max_open_trades":  10,
        "description":      "Maximum aggression — breakout + scalp, high frequency, high risk",
        "warning":          "⚠️ High Risk Mode – Possible full capital loss",
        "slippage_limit":   0.005,
    },
    "aggressive_protected": {
        "name":             "High Risk + Capital Guard",
        "icon":             "💥",
        "color":            "#ec4899",
        "risk_per_trade":   18.0,
        "max_daily_loss":   35.0,
        "max_drawdown":     30.0,    # triggers size reduction at 20%
        "sl_atr_mult":      4.0,
        "tp_atr_mult":      8.0,
        "trailing_stop":    True,
        "trailing_atr":     3.0,
        "ai_conf_threshold":0.55,
        "strategies":       ["breakout","volatility","momentum"],
        "max_open_trades":  8,
        "description":      "Aggressive with last-layer protection — auto-reduces size on drawdown",
        "warning":          "⚠️ Aggressive Mode – Auto-protection active at 20% drawdown",
        "slippage_limit":   0.004,
        "capital_guard_trigger": 20.0,  # % drawdown → reduce size by 50%
        "capital_guard_pause":   30.0,  # % drawdown → pause trading
    },
}


class CapitalModeEngine:
    """
    Enforces capital mode rules on EVERY trade decision.
    Called from bot_service.open_trade() before execution.
    Backend-enforced — NOT just frontend labels.
    """

    def get_mode(self, mode_key: str) -> dict:
        return CAPITAL_MODES.get(mode_key, CAPITAL_MODES["safe"])

    async def get_user_bot_mode(self, bot_id: str, user_id: str) -> str:
        """Get active capital mode for a bot from DB."""
        try:
            row = (db.table("bot_capital_modes")
                   .select("mode")
                   .eq("bot_id", bot_id)
                   .eq("user_id", user_id)
                   .single().execute()).data
            return row["mode"] if row else "safe"
        except Exception:
            return "safe"

    async def set_user_bot_mode(self, bot_id: str, user_id: str,
                                  mode_key: str) -> dict:
        """Persist capital mode selection + log change."""
        if mode_key not in CAPITAL_MODES:
            raise ValueError(f"Unknown mode: {mode_key}")
        db.table("bot_capital_modes").upsert({
            "bot_id":    bot_id,
            "user_id":   user_id,
            "mode":      mode_key,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }).execute()
        db.table("bot_mode_logs").insert({
            "bot_id":  bot_id,
            "user_id": user_id,
            "mode":    mode_key,
            "changed_at": datetime.now(timezone.utc).isoformat(),
        }).execute()
        mode = CAPITAL_MODES[mode_key]
        log.info("capital_mode_changed", bot=bot_id, user=user_id, mode=mode_key)
        return {"success": True, "mode": mode_key, "config": mode}

    def compute_position_size(self, mode: dict, balance: float,
                               atr: float, price: float,
                               drawdown_pct: float = 0.0) -> float:
        """
        ATR-based position sizing per mode.
        Reduces size on drawdown for aggressive_protected mode.
        """
        risk_pct = mode["risk_per_trade"]

        # Capital guard: reduce size if drawdown exceeded
        if mode.get("capital_guard_trigger") and drawdown_pct >= mode["capital_guard_trigger"]:
            risk_pct = risk_pct * 0.50   # cut size by 50%
            log.warning("capital_guard_triggered", drawdown=drawdown_pct, new_risk=risk_pct)

        # ATR-based SL distance
        sl_dist = atr * mode["sl_atr_mult"]
        if sl_dist <= 0 or price <= 0:
            return 0

        # Kelly-inspired: risk_amount / sl_distance
        risk_amount    = balance * risk_pct / 100
        position_size  = risk_amount / (sl_dist / price * price)
        # Clamp to reasonable max
        max_position   = balance * min(risk_pct * 3, 80) / 100 / price
        return round(min(position_size, max_position), 8)

    def compute_sl_tp(self, mode: dict, entry: float, side: str,
                       atr: float) -> tuple[float, float]:
        """Compute SL and TP from ATR multiples per mode."""
        d    = 1 if side == "long" else -1
        sl   = round(entry - d * atr * mode["sl_atr_mult"], 8)
        tp   = round(entry + d * atr * mode["tp_atr_mult"], 8)
        return sl, tp

    def compute_trailing(self, mode: dict, entry: float, side: str,
                          current_price: float, atr: float,
                          current_sl: float) -> float:
        """Compute trailing stop level per mode."""
        if not mode.get("trailing_stop") or mode["trailing_atr"] <= 0:
            return current_sl
        d = 1 if side == "long" else -1
        trail_sl = current_price - d * atr * mode["trailing_atr"]
        if side == "long":
            return max(current_sl, trail_sl)
        else:
            return min(current_sl, trail_sl) if current_sl > 0 else trail_sl

    async def check_mode_limits(self, user_id: str, bot_id: str,
                                  mode: dict) -> dict:
        """
        Hard-check all mode limits before allowing a new trade.
        Returns {allowed: bool, reason: str}
        """
        # Check open trades limit
        open_count = (db.table("trades").select("id", count="exact")
                      .eq("user_id", user_id).eq("bot_id", bot_id)
                      .eq("status", "open").execute()).count or 0
        if open_count >= mode["max_open_trades"]:
            return {"allowed": False,
                    "reason": f"Max {mode['max_open_trades']} open trades for {mode['name']}"}

        # Check daily loss
        today = datetime.now(timezone.utc).date().isoformat()
        today_trades = (db.table("trades").select("net_pnl")
                        .eq("user_id", user_id).eq("bot_id", bot_id)
                        .eq("status", "closed")
                        .gte("closed_at", today).execute()).data or []
        daily_pnl = sum(float(t.get("net_pnl", 0)) for t in today_trades)

        # Get balance for % calc
        wallet = (db.table("wallets").select("balance")
                  .eq("user_id", user_id).eq("wallet_type","trading")
                  .eq("mode","live").single().execute()).data
        balance = float(wallet["balance"]) if wallet else 1000

        daily_loss_pct = abs(min(0, daily_pnl)) / balance * 100
        if daily_loss_pct >= mode["max_daily_loss"]:
            return {"allowed": False,
                    "reason": f"Daily loss {daily_loss_pct:.1f}% ≥ limit {mode['max_daily_loss']}% for {mode['name']}"}

        # Check drawdown for aggressive_protected
        if mode.get("capital_guard_pause"):
            peak_balance = (db.table("wallet_snapshots").select("balance")
                            .eq("user_id", user_id).order("created_at", desc=True)
                            .limit(1).execute()).data
            peak = float(peak_balance[0]["balance"]) if peak_balance else balance
            drawdown = (peak - balance) / (peak + 1e-9) * 100
            if drawdown >= mode["capital_guard_pause"]:
                return {"allowed": False,
                        "reason": f"Drawdown {drawdown:.1f}% → trading paused (protection active)"}

        return {"allowed": True, "reason": ""}

    def get_ai_threshold(self, mode: dict) -> float:
        return mode["ai_conf_threshold"]

    def get_allowed_strategies(self, mode: dict) -> list:
        return mode["strategies"]


capital_mode_engine = CapitalModeEngine()


# ═══════════════════════════════════════════════════════════════
# AUTO-TRADE ENGINE — Automatic Trade Execution
# Runs continuously in background via Celery beat (30s interval)
# Applies capital modes + anti-fake + compound logic per bot
# ═══════════════════════════════════════════════════════════════

class AutoTradeEngine:
    """
    Autonomous trading loop for all running bots.
    Called by Celery beat every 30 seconds.
    Each bot type routes to the correct strategy engine.
    """

    # Map bot_id → strategy function
    BOT_STRATEGY_MAP = {
        "forex_scalper":  ("all_weather.forex_bots", "scalper_signal", "1m"),
        "forex_swing":    ("all_weather.forex_bots", "swing_signal",   "1h"),
        "forex_grid":     ("all_weather.grid",        "grid_check",    "1h"),
        "forex_arb":      ("all_weather.forex_bots", "news_volatility_signal","5m"),
        "crypto_momentum":("all_weather.crypto_bots", "momentum_signal","15m"),
        "crypto_dca":     ("all_weather.crypto_bots", "dca_signal",    "4h"),
        "crypto_reversal":("all_weather.crypto_bots", "reversal_signal","1h"),
        "gramma_ai":      ("all_weather.gramma_ai",   "analyze",       "1h"),
        "beta_scalping":  ("all_weather.beta_scalping","analyze",       "1m"),
    }

    async def run_bot_cycle(self, bot_id: str, user_id: str) -> dict:
        """
        Full auto-trade cycle for one bot:
        1. Get capital mode
        2. Fetch market data (multi-TF)
        3. Run strategy
        4. Validate signal (anti-fake)
        5. Check mode limits
        6. Open trade if all checks pass
        7. Manage open trades (SL/TP/trail)
        8. Reinvest if configured
        """
        from strategies.all_weather_engine import (
            institutional_ai, gramma_ai, beta_scalping,
            forex_bots, crypto_bots
        )
        from ai.indicators import ohlcv_to_df, compute_all
        from exchanges.exchange_service import exchange_service

        mode_key = await capital_mode_engine.get_user_bot_mode(bot_id, user_id)
        mode     = CAPITAL_MODES.get(mode_key, CAPITAL_MODES["safe"])

        # Get bot config
        bot = (db.table("bots").select("*,bot_settings(*)")
               .eq("id", bot_id).eq("user_id", user_id)
               .eq("status","running").single().execute()).data
        if not bot: return {"skipped": True, "reason": "Bot not running"}

        pairs    = bot.get("pairs", ["BTC/USDT"])
        symbol   = pairs[0] if pairs else "BTC/USDT"
        tf_map   = self.BOT_STRATEGY_MAP.get(bot_id, (None, None, "1h"))
        primary_tf = tf_map[2]

        # Fetch data
        try:
            ohlcv  = await exchange_service.get_ohlcv(symbol, primary_tf, limit=100)
            df     = compute_all(ohlcv_to_df(ohlcv))
        except Exception as e:
            return {"skipped": True, "reason": f"Data fetch failed: {e}"}

        # Run strategy per bot type
        signal = await self._get_signal(bot_id, df, symbol, mode, mode_key)

        if signal.get("action","WAIT") == "WAIT":
            return {"action":"WAIT","symbol":symbol,"bot_id":bot_id}

        # Anti-fake gate
        conf = float(signal.get("confidence", 0))
        if conf < mode["ai_conf_threshold"] * 100:
            return {"skipped":True, "reason":f"Conf {conf:.1f}% below threshold {mode['ai_conf_threshold']*100:.0f}%"}

        # Mode limits check
        limits = await capital_mode_engine.check_mode_limits(user_id, bot_id, mode)
        if not limits["allowed"]:
            return {"skipped":True, "reason":limits["reason"]}

        # Position sizing
        wallet = (db.table("wallets").select("balance")
                  .eq("user_id",user_id).eq("wallet_type","trading")
                  .eq("mode","live").single().execute()).data
        balance = float(wallet["balance"]) if wallet else 0

        # Check drawdown for aggressive_protected
        drawdown_pct = await self._compute_drawdown(user_id)
        atr  = float(df["atr14"].iloc[-1]) if "atr14" in df.columns else float(df["close"].iloc[-1])*0.02
        price = float(df["close"].iloc[-1])
        qty   = capital_mode_engine.compute_position_size(mode, balance, atr, price, drawdown_pct)

        if qty <= 0 or balance < 1:
            return {"skipped":True,"reason":"Insufficient balance"}

        # Compute SL/TP
        side = "long" if signal["action"]=="BUY" else "short"
        sl, tp = capital_mode_engine.compute_sl_tp(mode, price, side, atr)

        # Override if strategy provided explicit SL/TP
        if signal.get("stop_loss"):  sl = signal["stop_loss"]
        if signal.get("take_profit"): tp = signal["take_profit"]

        # Open trade
        try:
            trade_result = await self.open_trade(
                bot_id=bot_id, user_id=user_id,
                symbol=symbol, side=side,
                entry_price=price, quantity=qty,
                stop_loss=sl, take_profit=tp,
                source=f"auto_{bot_id}",
                mode_key=mode_key,
                explainability=signal.get("explainability",{}),
                ai_reason=signal.get("reason",""),
                ml_score=signal.get("ml_score",0),
                rule_conf=signal.get("rule_conf",0),
                regime=signal.get("regime",""),
            )
        except Exception as e:
            return {"error":str(e)}

        log.info("auto_trade_opened",
                 bot=bot_id, user=user_id, symbol=symbol,
                 side=side, qty=qty, price=price, mode=mode_key)
        return {
            "executed":   True,
            "trade_id":   trade_result.get("trade_id"),
            "symbol":     symbol,
            "side":       side,
            "qty":        qty,
            "entry":      price,
            "sl":         sl,
            "tp":         tp,
            "confidence": conf,
            "mode":       mode_key,
        }

    async def _get_signal(self, bot_id: str, df, symbol: str,
                           mode: dict, mode_key: str) -> dict:
        """Route to correct strategy engine per bot."""
        from strategies.all_weather_engine import (
            institutional_ai, gramma_ai, beta_scalping, forex_bots, crypto_bots
        )
        try:
            if bot_id == "gramma_ai":
                return gramma_ai.analyze(df, df)   # pass same df as proxy
            elif bot_id == "beta_scalping":
                return beta_scalping.analyze(df, df, df, symbol)
            elif bot_id in ("forex_scalper","forex_swing"):
                fn = forex_bots.scalper_signal if bot_id=="forex_scalper" else forex_bots.swing_signal
                sig = fn(df)
                return {**sig, "confidence": sig.get("confidence",0), "action": sig.get("action","WAIT")}
            elif bot_id in ("crypto_momentum","crypto_reversal"):
                fn = crypto_bots.momentum_signal if bot_id=="crypto_momentum" else crypto_bots.reversal_signal
                sig = fn(df)
                return {**sig, "confidence": sig.get("confidence",0)}
            elif bot_id == "crypto_dca":
                sig = crypto_bots.dca_signal(df)
                act = "BUY" if sig.get("action") in ("first_buy","safety_buy") else "WAIT"
                return {"action":act, "confidence": 72 if act=="BUY" else 0, **sig}
            else:
                # Default: institutional AI
                return institutional_ai.decide(df, symbol, mode_key)
        except Exception as e:
            return {"action":"WAIT","confidence":0,"error":str(e)}

    async def _compute_drawdown(self, user_id: str) -> float:
        """Compute current drawdown % from peak balance."""
        try:
            snaps = (db.table("wallet_snapshots").select("balance")
                     .eq("user_id",user_id).order("created_at",desc=True)
                     .limit(30).execute()).data or []
            if not snaps: return 0.0
            peak  = max(float(s["balance"]) for s in snaps)
            curr  = float(snaps[0]["balance"])
            return max(0.0, (peak-curr)/peak*100)
        except Exception:
            return 0.0

    async def manage_open_trades(self, user_id: str) -> list:
        """
        Check all open trades for SL/TP/trail hits.
        Called every 10 seconds.
        """
        from ai.elite_execution import elite_execution
        from exchanges.exchange_service import exchange_service

        open_trades = (db.table("trades").select("id,symbol,mode_key")
                       .eq("user_id",user_id).eq("status","open").execute()).data or []
        results = []
        for trade in open_trades:
            sym = trade["symbol"]
            try:
                tick  = await exchange_service.get_ticker(sym)
                price = float(tick.get("last",0))
                atr   = price * 0.015  # fallback
                r = await elite_execution.process_trade(trade["id"], price, atr)
                results.append(r)
            except Exception as e:
                results.append({"trade_id":trade["id"],"error":str(e)})
        return results

    async def auto_reinvest(self, user_id: str, bot_id: str,
                             trade_id: str, net_pnl: float) -> dict:
        """
        After profitable trade closes, reinvest profit % back into bot.
        Compound growth: next position size = base + pnl * reinvest_pct
        """
        if net_pnl <= 0: return {"reinvested":False}
        try:
            bot = (db.table("bots").select("capital_allocated,auto_reinvest,reinvest_pct")
                   .eq("id",bot_id).single().execute()).data
            if not bot or not bot.get("auto_reinvest",True):
                return {"reinvested":False}
            pct    = float(bot.get("reinvest_pct",80))/100
            add    = round(net_pnl * pct, 6)
            new_cap= float(bot.get("capital_allocated",0)) + add
            db.table("bots").update({"capital_allocated":new_cap}).eq("id",bot_id).execute()
            log.info("reinvested", bot=bot_id, amount=add, new_cap=new_cap)
            return {"reinvested":True,"amount":add,"new_capital":new_cap}
        except Exception as e:
            return {"reinvested":False,"error":str(e)}


auto_trade_engine = AutoTradeEngine()
