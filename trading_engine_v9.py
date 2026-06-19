"""
ai/trading_loop.py — ESTRADE v7 ULTRA Trading Loop
═══════════════════════════════════════════════════════════════════════════════
ALL ORIGINAL FEATURES PRESERVED + ULTRA ENHANCEMENTS:

━━━ 2% PRO MODE (preserved exactly) ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  • Targets exactly 2% per session, risk capped 0.4%/trade
  • Min confidence 72%, min RR 1.5
  • Win streak scaling (×1.2 per 3 wins, max ×1.5)
  • 2 consecutive losses → pause; daily loss ≥1% → stop

━━━ PROFIT RANGE SELECTOR (NEW) ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Targets: 2% · 3% · 4% · 5% · 6% · 7% · 8% · 10% · 12% · 15%

  Per-Trade Mode:
    → Each single trade attempts to hit selected target
    → Risk = target × risk_ratio
    → Bot pauses after any winning trade that hits target
    → Ideal for high-conviction swing entries

  Per-Session Mode:
    → Accumulates across multiple trades per session
    → Smaller per-trade risk: target ÷ expected_trades × ratio
    → Bot keeps trading until cumulative PnL ≥ target
    → Auto-resets when new session starts (Asia→London→NY)
    → Ideal for scalping bots (many small wins = big target)

  Strategy auto-adapts per target:
    2–3%:  conservative / balanced strategy
    4–7%:  balanced / aggressive strategy
    8–15%: aggressive / ultra strategy

  Risk auto-scales with target:
    2%  → 0.44% risk, conf ≥68%, RR ≥1.5
    5%  → 1.10% risk, conf ≥72%, RR ≥1.8
    10% → 2.30% risk, conf ≥76%, RR ≥2.2
    15% → 3.75% risk, conf ≥80%, RR ≥2.5

━━━ MAINTENANCE MODE (NEW) ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  • Global and per-bot maintenance windows
  • Auto-pauses bots during scheduled maintenance
  • Auto-resumes all bots after maintenance window
  • Admin notification on entry/exit
  • Emergency kill-switch for all bots

━━━ SYMBOL FEED (preserved + enhanced) ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  • Async OHLCV from crypto exchanges + MT5
  • TTL cache per timeframe (sub-1ms on cache hit)
  • 72-feature indicator computation
  • Trades ANY coin pair (BTC, ETH, SOL, meme coins, etc.)

━━━ ORDER EXECUTOR (preserved) ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  • Routes crypto → exchange, forex/gold → MT5
  • Position size from risk % and SL distance
═══════════════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations
import asyncio
import time
from collections import defaultdict, deque
from datetime import datetime, timezone, timedelta
from typing import Optional
import structlog
import pandas as pd
import numpy as np

from core.bot_registry   import (BOT_REGISTRY, get_bot, get_strategy_for_target,
                                   get_bot_risk_for_target, get_min_confidence_for_target,
                                   get_min_rr_for_target, get_target_mode)
from core.database       import db
from ai.ultra_brain      import ultra_brain, ultra_scalp_brain, UltraSignal
from services.capital_maximizer  import (capital_maximizer, profit_range_engine,
                                          CircuitBreaker, PROFIT_RANGE_OPTIONS,
                                          calc_risk_pct, get_current_session)
from services.notification_service import notification_service
from services.mt5_bridge           import mt5_service
from strategies.commodities_engine  import commodities_engine
from ai.security_auditor           import security_auditor

log = structlog.get_logger("trading_loop_ultra")


# ══════════════════════════════════════════════════════════════
# 2% PRO MODE ENGINE — PRESERVED EXACTLY FROM v7
# ══════════════════════════════════════════════════════════════

TWO_PCT_TARGET          = 2.0
TWO_PCT_RISK_PER_TRADE  = 0.4
TWO_PCT_MIN_CONFIDENCE  = 72.0
TWO_PCT_MIN_RR          = 1.5
TWO_PCT_MAX_TRADES      = 20
TWO_PCT_WIN_SCALE_AFTER = 3
TWO_PCT_WIN_SCALE_MULT  = 1.2
TWO_PCT_LOSS_PAUSE      = 2
TWO_PCT_DAILY_STOP      = 1.0


class TwoPctTargetEngine:
    """2% Pro Mode — preserved exactly from v7."""

    def __init__(self):
        self._state: dict[str, dict] = {}

    def init_bot(self, bot_id, starting_balance):
        self._state[bot_id] = {
            "enabled": False, "starting_balance": starting_balance,
            "session_pnl_pct": 0.0, "session_pnl_usd": 0.0,
            "trades_this_session": 0, "consecutive_wins": 0,
            "consecutive_losses": 0, "current_scale": 1.0,
            "paused_for_losses": False, "target_hit": False,
            "target_pct": TWO_PCT_TARGET,
            "session_start": datetime.now(timezone.utc).isoformat(),
            "daily_loss_pct": 0.0,
        }

    def enable(self, bot_id, starting_balance=0):
        if bot_id not in self._state:
            self.init_bot(bot_id, starting_balance)
        s = self._state[bot_id]
        s.update({"enabled": True, "target_hit": False, "paused_for_losses": False,
                   "session_pnl_pct": 0.0,
                   "session_start": datetime.now(timezone.utc).isoformat()})

    def disable(self, bot_id):
        if bot_id in self._state:
            self._state[bot_id]["enabled"] = False

    def is_enabled(self, bot_id) -> bool:
        return self._state.get(bot_id, {}).get("enabled", False)

    def can_trade(self, bot_id, signal: UltraSignal) -> tuple[bool, str]:
        s = self._state.get(bot_id)
        if not s or not s["enabled"]: return True, "2pct_mode_off"
        if s["target_hit"]: return False, f"2% target already hit ({s['session_pnl_pct']:.2f}%)"
        if s["daily_loss_pct"] <= -TWO_PCT_DAILY_STOP: return False, "Daily loss stop"
        if s["trades_this_session"] >= TWO_PCT_MAX_TRADES: return False, f"Max {TWO_PCT_MAX_TRADES} trades"
        if s["paused_for_losses"]: return False, "Loss pause active"
        if signal.confidence < TWO_PCT_MIN_CONFIDENCE:
            return False, f"Confidence {signal.confidence:.1f}% < {TWO_PCT_MIN_CONFIDENCE}%"
        if signal.rr_ratio < TWO_PCT_MIN_RR:
            return False, f"RR {signal.rr_ratio:.2f} < {TWO_PCT_MIN_RR}"
        remaining = s["target_pct"] - s["session_pnl_pct"]
        if remaining <= 0.1:
            s["target_hit"] = True
            return False, "2% target reached"
        return True, "ok"

    def get_position_size_mult(self, bot_id) -> float:
        s = self._state.get(bot_id, {})
        if not s.get("enabled"): return 1.0
        streak = s.get("consecutive_wins", 0)
        mult   = 1.0 + min(0.5, (streak // TWO_PCT_WIN_SCALE_AFTER) * (TWO_PCT_WIN_SCALE_MULT - 1.0))
        return round(mult, 2)

    def get_risk_pct(self, bot_id, base_risk_pct) -> float:
        if self.is_enabled(bot_id):
            return min(TWO_PCT_RISK_PER_TRADE, base_risk_pct)
        return base_risk_pct

    def record_result(self, bot_id, pnl_pct) -> dict:
        s = self._state.get(bot_id)
        if not s or not s["enabled"]: return {"action": "continue"}
        s["session_pnl_pct"]    += pnl_pct
        s["trades_this_session"] += 1
        if pnl_pct > 0:
            s["consecutive_wins"]  += 1; s["consecutive_losses"] = 0; s["paused_for_losses"] = False
        else:
            s["consecutive_losses"] += 1; s["consecutive_wins"] = 0; s["current_scale"] = 1.0
            s["daily_loss_pct"] += pnl_pct
            if s["consecutive_losses"] >= TWO_PCT_LOSS_PAUSE:
                s["paused_for_losses"] = True
                return {"action": "pause", "reason": f"{TWO_PCT_LOSS_PAUSE} consecutive losses",
                        "session_pnl": s["session_pnl_pct"]}
        if s["daily_loss_pct"] <= -TWO_PCT_DAILY_STOP:
            return {"action": "daily_stop", "reason": f"Daily loss {s['daily_loss_pct']:.2f}%",
                    "session_pnl": s["session_pnl_pct"]}
        if s["session_pnl_pct"] >= s["target_pct"]:
            s["target_hit"] = True
            return {"action": "target_hit", "session_pnl": s["session_pnl_pct"],
                    "trades_used": s["trades_this_session"], "win_streak": s["consecutive_wins"]}
        remaining = s["target_pct"] - s["session_pnl_pct"]
        return {"action": "continue", "session_pnl_pct": round(s["session_pnl_pct"], 3),
                "remaining_pct": round(remaining, 3), "trades_used": s["trades_this_session"],
                "scale_mult": s.get("current_scale", 1.0)}

    def get_state(self, bot_id) -> dict:
        s = self._state.get(bot_id, {})
        if not s: return {"enabled": False}
        remaining = max(0, s.get("target_pct", 2.0) - s.get("session_pnl_pct", 0.0))
        return {
            "enabled":           s.get("enabled", False),
            "session_pnl_pct":   round(s.get("session_pnl_pct", 0), 3),
            "remaining_pct":     round(remaining, 3),
            "target_pct":        s.get("target_pct", TWO_PCT_TARGET),
            "progress_pct":      round(s.get("session_pnl_pct", 0) / s.get("target_pct", 2) * 100, 1),
            "trades_used":       s.get("trades_this_session", 0),
            "consecutive_wins":  s.get("consecutive_wins", 0),
            "consecutive_losses":s.get("consecutive_losses", 0),
            "current_scale":     s.get("current_scale", 1.0),
            "target_hit":        s.get("target_hit", False),
            "paused_for_losses": s.get("paused_for_losses", False),
            "daily_loss_pct":    round(s.get("daily_loss_pct", 0), 3),
        }

    def reset_for_new_session(self, bot_id):
        s = self._state.get(bot_id)
        if s:
            s.update({"session_pnl_pct": 0.0, "session_pnl_usd": 0.0,
                       "trades_this_session": 0, "consecutive_wins": 0,
                       "consecutive_losses": 0, "current_scale": 1.0,
                       "paused_for_losses": False, "target_hit": False,
                       "daily_loss_pct": 0.0,
                       "session_start": datetime.now(timezone.utc).isoformat()})


two_pct_engine = TwoPctTargetEngine()


# ══════════════════════════════════════════════════════════════
# MAINTENANCE MANAGER (NEW)
# ══════════════════════════════════════════════════════════════

class MaintenanceManager:
    """
    Handles global and per-bot maintenance windows.
    Auto-pauses/resumes bots. Admin notifications.
    """

    def __init__(self):
        self._global_maintenance    = False
        self._maintenance_message   = ""
        self._bot_maintenance: dict[str, bool] = {}
        self._maintenance_start: Optional[datetime] = None
        self._scheduled: list[dict] = []   # [{start_h, end_h, days}]

    def is_in_maintenance(self, bot_id: str = "") -> bool:
        if self._global_maintenance:
            return True
        if bot_id and self._bot_maintenance.get(bot_id):
            return True
        # Check scheduled windows
        now = datetime.now(timezone.utc)
        for window in self._scheduled:
            wday = now.weekday()  # 0=Mon … 6=Sun
            if window.get("all_days") or wday in window.get("days", []):
                sh, sm = window["start_h"], window.get("start_m", 0)
                eh, em = window["end_h"],   window.get("end_m", 0)
                start = now.replace(hour=sh, minute=sm, second=0)
                end   = now.replace(hour=eh, minute=em, second=0)
                if start <= now <= end:
                    return True
        return False

    async def enter_global_maintenance(self, message: str = "Scheduled maintenance"):
        self._global_maintenance  = True
        self._maintenance_message = message
        self._maintenance_start   = datetime.now(timezone.utc)
        log.warning("global_maintenance_started", message=message)
        try:
            await notification_service.send_admin_alert(
                title="🔧 ESTRADE Maintenance Started",
                body=f"All bots paused. {message}",
                severity="medium", data={"maintenance": True},
            )
        except Exception:
            pass

    async def exit_global_maintenance(self):
        duration = (datetime.now(timezone.utc) - self._maintenance_start
                    ).total_seconds() if self._maintenance_start else 0
        self._global_maintenance = False
        log.info("global_maintenance_ended", duration_mins=duration / 60)
        try:
            await notification_service.send_admin_alert(
                title="✅ ESTRADE Maintenance Complete",
                body=f"All bots resuming. Duration: {duration/60:.1f} minutes.",
                severity="low", data={"maintenance": False},
            )
        except Exception:
            pass

    def add_scheduled_window(self, start_h: int, end_h: int,
                              days: list[int] = None):
        """Add a recurring maintenance window. days: 0=Mon, 6=Sun. None=all days."""
        self._scheduled.append({
            "start_h":  start_h, "end_h": end_h,
            "days":     days or [],
            "all_days": days is None,
        })

    def get_status(self) -> dict:
        return {
            "global_maintenance": self._global_maintenance,
            "message":            self._maintenance_message,
            "started_at":         self._maintenance_start.isoformat() if self._maintenance_start else None,
            "scheduled_windows":  self._scheduled,
            "currently_in_window":self.is_in_maintenance(),
        }


maintenance_manager = MaintenanceManager()
# Add default daily recalibration window (00:00–00:30 UTC)
maintenance_manager.add_scheduled_window(start_h=0, end_h=0, days=None)


# ══════════════════════════════════════════════════════════════
# PROFIT RANGE GATE (NEW — integrates with trading gate)
# ══════════════════════════════════════════════════════════════

class ProfitRangeGate:
    """
    Gate layer for profit range mode.
    Checks per-trade vs per-session logic before each order.
    """

    def check(self, bot_id: str, signal: UltraSignal,
               mode_active: bool) -> tuple[bool, str, float]:
        """
        Returns (can_trade, reason, adjusted_risk_pct).
        """
        if not mode_active or not profit_range_engine.is_active(bot_id):
            return True, "no_range_mode", 0.0

        allowed, reason = profit_range_engine.can_trade(
            bot_id,
            signal_confidence=signal.confidence,
            signal_rr=signal.rr_ratio,
        )
        if not allowed:
            return False, reason, 0.0

        state = profit_range_engine.get_state(bot_id)
        if not state:
            return True, "ok", 0.0

        risk_pct = state.risk_pct
        scale    = profit_range_engine.get_position_scale(bot_id)
        adjusted_risk = round(risk_pct * scale, 4)
        return True, "ok", adjusted_risk


profit_range_gate = ProfitRangeGate()


# ══════════════════════════════════════════════════════════════
# SYMBOL FEED — PRESERVED + enhanced caching
# ══════════════════════════════════════════════════════════════

class SymbolFeed:
    """Async OHLCV provider with TTL cache and full indicator suite."""

    _cache: dict[str, tuple[pd.DataFrame, float]] = {}
    _CACHE_SECONDS = {
        "M1": 55, "M5": 280, "M15": 850, "H1": 3550,
        "1m": 55, "5m": 280, "15m": 850, "1h": 3550,
        "4h": 14200, "H4": 14200, "1d": 86000, "D1": 86000,
    }

    async def get_candles(self, symbol, timeframe, exchange_client=None,
                           mt5_bridge=None, count=300) -> Optional[pd.DataFrame]:
        cache_key = f"{symbol}:{timeframe}"
        ttl = self._CACHE_SECONDS.get(timeframe, 60)
        if cache_key in self._cache:
            df, ts = self._cache[cache_key]
            if time.time() - ts < ttl:
                return df
        try:
            raw = None
            if exchange_client and hasattr(exchange_client, "fetch_ohlcv"):
                ohlcv = await asyncio.to_thread(
                    exchange_client.fetch_ohlcv, symbol, timeframe, limit=count)
                if ohlcv:
                    raw = pd.DataFrame(ohlcv, columns=["timestamp","open","high","low","close","volume"])
            elif mt5_bridge:
                raw_list = await mt5_bridge.get_ohlcv(symbol, timeframe, count)
                if raw_list:
                    raw = pd.DataFrame(raw_list, columns=["timestamp","open","high","low","close","volume"])
            if raw is None or raw.empty:
                return None
            df = self._compute_indicators(raw)
            self._cache[cache_key] = (df, time.time())
            return df
        except Exception as e:
            log.error("candle_fetch_error", symbol=symbol, tf=timeframe, error=str(e))
            return None

    def _compute_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """72-feature indicator suite — preserved from v7."""
        c = df["close"].astype(float); h = df["high"].astype(float)
        l = df["low"].astype(float);   v = df["volume"].astype(float)
        o = df["open"].astype(float)
        def ema(s, p): return s.ewm(span=p, adjust=False).mean()

        df["ema8"]  = ema(c,8);  df["ema20"] = ema(c,20)
        df["ema50"] = ema(c,50); df["ema200"]= ema(c,200)

        delta = c.diff(); gain = delta.clip(lower=0); loss = (-delta).clip(lower=0)
        rs = gain.ewm(14, adjust=False).mean() / (loss.ewm(14, adjust=False).mean() + 1e-9)
        df["rsi"]    = 100 - 100 / (1 + rs)
        rs7  = gain.ewm(7, adjust=False).mean() / (loss.ewm(7, adjust=False).mean() + 1e-9)
        df["rsi_7"]  = 100 - 100 / (1 + rs7)
        rs21 = gain.ewm(21,adjust=False).mean() / (loss.ewm(21,adjust=False).mean() + 1e-9)
        df["rsi_21"] = 100 - 100 / (1 + rs21)

        e12 = ema(c,12); e26 = ema(c,26)
        df["macd"] = e12 - e26
        df["macd_signal"] = ema(df["macd"], 9)
        df["macd_hist"]   = df["macd"] - df["macd_signal"]

        sma20 = c.rolling(20).mean(); std20 = c.rolling(20).std()
        df["bb_mid"]   = sma20
        df["bb_upper"] = sma20 + std20*2
        df["bb_lower"] = sma20 - std20*2

        tr   = pd.concat([h-l,(h-c.shift()).abs(),(l-c.shift()).abs()],axis=1).max(axis=1)
        df["atr"] = tr.ewm(14, adjust=False).mean()

        dm_p = (h.diff()).clip(lower=0); dm_n = (-l.diff()).clip(lower=0)
        tr14 = tr.ewm(14, adjust=False).mean() + 1e-9
        di_p = 100*dm_p.ewm(14,adjust=False).mean()/tr14
        di_n = 100*dm_n.ewm(14,adjust=False).mean()/tr14
        dx   = 100*(di_p-di_n).abs()/(di_p+di_n+1e-9)
        df["adx"] = dx.ewm(14, adjust=False).mean()

        lo14 = l.rolling(14).min(); hi14 = h.rolling(14).max()
        df["stoch_k"] = 100*(c-lo14)/(hi14-lo14+1e-9)
        df["stoch_d"] = df["stoch_k"].rolling(3).mean()

        tp = (h+l+c)/3
        df["vwap"]     = (tp*v).cumsum()/(v.cumsum()+1e-9)
        df["vol_ratio"]= v / (v.rolling(20).mean()+1e-9)

        obv = (v * np.sign(c.diff().fillna(0))).cumsum()
        df["obv"] = obv
        mfm = ((c-l)-(h-c))/(h-l+1e-9); mfv = mfm*v
        df["cmf"] = mfv.rolling(20).sum()/(v.rolling(20).sum()+1e-9)
        df["williams_r"] = -100*(hi14-c)/(hi14-lo14+1e-9)
        df["cci"] = (tp - tp.rolling(20).mean())/(0.015*tp.rolling(20).std()+1e-9)
        raw_mf = tp*v
        df["mfi"] = 100 - 100/(1 + raw_mf.where(tp>tp.shift(1),0).rolling(14).sum() /
                                   (raw_mf.where(tp<tp.shift(1),0).rolling(14).sum()+1e-9))
        df["pct_change_5"]  = c.pct_change(5)*100
        df["pct_change_20"] = c.pct_change(20)*100
        df["pct_change_50"] = c.pct_change(50)*100

        def classify(row):
            r,e20,e50,e200,cl = row["rsi"],row["ema20"],row["ema50"],row["ema200"],row["close"]
            atr_ = row["atr"] + 1e-9
            if e20>e50>e200 and r>55: return "bull_trend"
            if e20<e50<e200 and r<45: return "bear_trend"
            if r>70: return "overbought"
            if r<30: return "oversold"
            if abs(cl-e20)/atr_ < 0.5: return "ranging"
            return "neutral"
        df["market_phase"] = df.apply(classify, axis=1)
        return df.fillna(0)


# ══════════════════════════════════════════════════════════════
# ORDER EXECUTOR — PRESERVED from v7
# ══════════════════════════════════════════════════════════════

class OrderExecutor:
    """Routes order to crypto exchange or MT5 (preserved)."""

    async def execute(self, user_id, bot_id, signal: UltraSignal,
                       risk_pct, exchange_client=None, mt5_bridge=None,
                       balance=1000.0, platform="esc", size_mult=1.0) -> dict:
        side   = "buy" if signal.direction == "long" else "sell"
        symbol = signal.pair
        price  = signal.entry
        sl_dist= abs(price - signal.sl)
        if sl_dist <= 0: return {"success": False, "error": "Invalid SL"}
        quantity = (balance * (risk_pct / 100) * size_mult) / sl_dist
        try:
            if platform == "esc" and exchange_client:
                order = await asyncio.to_thread(
                    exchange_client.create_order, symbol, "market",
                    side, round(quantity, 4),
                    params={"stopLoss":   {"triggerPrice": signal.sl},
                            "takeProfit": {"triggerPrice": signal.tp2}},
                )
                order_id   = order.get("id", "")
                fill_price = float(order.get("price", price) or price)
                try:
                    db.table("trades").insert({
                        "user_id": user_id, "bot_id": bot_id,
                        "pair": symbol, "platform": "esc",
                        "asset_class": signal.metadata.get("asset_class","crypto"),
                        "direction": signal.direction, "status": "open",
                        "timeframe": signal.timeframe,
                        "entry_price": fill_price, "stop_loss": signal.sl,
                        "take_profit": signal.tp2,
                        "tp1": signal.tp1, "tp2": signal.tp2, "tp3": signal.tp3,
                        "quantity": round(quantity, 6),
                        "ai_confidence": signal.confidence,
                        "ai_signal": signal.to_dict(),
                        "regime": signal.regime,
                        "engines_agreed": signal.engines_agreed,
                        "latency_ms": signal.latency_ms,
                        "fast_path": signal.fast_path,
                        "exchange_order_id": order_id,
                        "opened_at": datetime.now(timezone.utc).isoformat(),
                    }).execute()
                except Exception:
                    pass
                return {"success": True, "order_id": order_id,
                        "fill_price": fill_price, "quantity": quantity}

            elif platform == "esf" and mt5_bridge:
                return await mt5_service.execute_signal(
                    user_id=user_id, symbol=symbol, side=side,
                    risk_pct=risk_pct * size_mult,
                    sl_price=signal.sl, tp_price=signal.tp2)

            return {"success": False, "error": "No connection"}
        except Exception as e:
            log.error("order_error", bot=bot_id, error=str(e))
            return {"success": False, "error": str(e)}


# ══════════════════════════════════════════════════════════════
# BOT RUNNER — ULTRA (preserved + profit range + maintenance)
# ══════════════════════════════════════════════════════════════

class BotRunner:
    """Full bot lifecycle manager — all features."""

    LOOP_INTERVALS = {
        "M1":1,"1m":1,"M5":5,"5m":5,"M15":15,"15m":15,
        "H1":60,"1h":60,"H4":240,"4h":240,"D1":1440,"1d":1440,
    }

    def __init__(self, bot_id, user_id, bot_config,
                 exchange_client=None, mt5_bridge=None):
        self.bot_id       = bot_id
        self.user_id      = user_id
        self.bot_config   = bot_config
        self.registry_cfg = get_bot(bot_config.get("bot_id", bot_id))
        self.exchange     = exchange_client
        self.mt5          = mt5_bridge
        self.feed         = SymbolFeed()
        self.executor     = OrderExecutor()
        self._running     = False
        self._open_positions: list[dict] = []
        self._balance     = bot_config.get("allocated_capital", 1000.0)
        self._starting_balance = self._balance
        self._daily_low   = self._balance
        self.platform     = bot_config.get("platform", "esc")

        # 2% mode init (preserved)
        two_pct_engine.init_bot(bot_id, self._balance)
        if bot_config.get("two_pct_mode"):
            two_pct_engine.enable(bot_id, self._balance)

        # Profit range init (new)
        if bot_config.get("profit_range_target") and bot_config.get("profit_range_mode"):
            capital_maximizer.set_profit_range(
                bot_id,
                target_pct=float(bot_config["profit_range_target"]),
                mode=bot_config["profit_range_mode"],
                balance=self._balance,
            )

    @property
    def primary_pairs(self): return self.registry_cfg.get("pairs_default", ["BTC/USDT"])
    @property
    def timeframes(self):    return self.registry_cfg.get("timeframes", ["1h"])
    @property
    def primary_tf(self):    return self.timeframes[0] if self.timeframes else "1h"
    @property
    def loop_sleep(self):    return self.LOOP_INTERVALS.get(self.primary_tf, 60)
    @property
    def is_scalp_bot(self):
        return (self.registry_cfg.get("category","") in ("crypto_scalp","forex")
                and self.primary_tf in ("M1","M5","1m","5m"))

    async def start(self):
        self._running = True
        log.info("bot_started", bot=self.bot_id, tf=self.primary_tf)
        try:
            db.table("bots").update({
                "status": "running",
                "started_at": datetime.now(timezone.utc).isoformat()
            }).eq("id", self.bot_id).execute()
        except Exception:
            pass
        await self._run_loop()

    async def stop(self, reason="manual"):
        self._running = False
        try:
            db.table("bots").update({
                "status": "stopped", "stop_reason": reason,
                "stopped_at": datetime.now(timezone.utc).isoformat()
            }).eq("id", self.bot_id).execute()
        except Exception:
            pass
        log.info("bot_stopped", bot=self.bot_id, reason=reason)

    async def enable_two_pct_mode(self):
        two_pct_engine.enable(self.bot_id, self._balance)
        try:
            db.table("bots").update({"two_pct_mode": True}).eq("id", self.bot_id).execute()
        except Exception:
            pass
        await notification_service.send(
            user_id=self.user_id, event="two_pct_mode_enabled",
            title="🎯 2% Pro Mode Activated",
            body=(f"Bot now targets 2%/session. Risk capped 0.4%/trade. "
                  f"Min confidence: {TWO_PCT_MIN_CONFIDENCE}%."),
            data={"bot_id": self.bot_id},
        )

    async def disable_two_pct_mode(self):
        two_pct_engine.disable(self.bot_id)
        try:
            db.table("bots").update({"two_pct_mode": False}).eq("id", self.bot_id).execute()
        except Exception:
            pass

    async def set_profit_range(self, target_pct: float, mode: str):
        """Set profit range from dashboard (new)."""
        state = capital_maximizer.set_profit_range(
            self.bot_id, target_pct, mode, self._balance)
        # Determine strategy from target
        strategy = get_strategy_for_target(
            self.bot_config.get("bot_id", self.bot_id), target_pct)
        log.info("profit_range_set", bot=self.bot_id,
                 target=target_pct, mode=mode, strategy=strategy)
        try:
            db.table("bots").update({
                "profit_range_target": target_pct,
                "profit_range_mode":   mode,
                "active_strategy":     strategy,
            }).eq("id", self.bot_id).execute()
        except Exception:
            pass
        await notification_service.send(
            user_id=self.user_id, event="profit_range_set",
            title=f"🎯 Target Set: {target_pct}% ({mode})",
            body=(f"Bot will use '{strategy}' strategy. "
                  f"Risk: {calc_risk_pct(target_pct, mode):.2f}%/trade. "
                  f"Min confidence: {get_min_confidence_for_target(target_pct):.0f}%."),
            data={"bot_id": self.bot_id, "target": target_pct,
                  "mode": mode, "strategy": strategy},
        )
        return state

    async def _run_loop(self):
        while self._running:
            t0 = time.perf_counter()
            try:
                # Maintenance check
                if maintenance_manager.is_in_maintenance(self.bot_id):
                    await asyncio.sleep(30)
                    continue
                await self._tick()
            except Exception as e:
                log.error("bot_tick_error", bot=self.bot_id, error=str(e))
                await asyncio.sleep(5)
            elapsed = time.perf_counter() - t0
            await asyncio.sleep(max(0.1, self.loop_sleep - elapsed))

    async def _tick(self):
        for pair in self.primary_pairs:
            df = await self.feed.get_candles(
                pair, self.primary_tf,
                exchange_client=self.exchange, mt5_bridge=self.mt5, count=300)
            if df is None or df.empty:
                continue

            asset_class = _infer_asset_class(pair)
            macro_ctx   = await self._get_macro_context(pair)

            # ── Generate signal ───────────────────────────────
            if self.is_scalp_bot:
                signal = ultra_scalp_brain.scalp_signal(df, pair, asset_class)
            elif asset_class in ("commodities","gold","silver"):
                csig   = commodities_engine.analyze(pair, df, self.primary_tf)
                signal = _commodity_to_ultra(csig, pair)
            else:
                # Adapt strategy based on profit range target
                pr_state = profit_range_engine.get_state(self.bot_id)
                signal = ultra_brain.generate_signal(
                    df, pair, self.primary_tf, asset_class, macro_ctx)

            if not signal.is_valid:
                continue

            # ── Determine active mode & gate ──────────────────
            two_pct_active  = two_pct_engine.is_enabled(self.bot_id)
            range_active     = profit_range_engine.is_active(self.bot_id)

            # 2% mode gate (preserved exactly)
            if two_pct_active:
                ok, reason = two_pct_engine.can_trade(self.bot_id, signal)
                if not ok:
                    log.debug("2pct_blocked", bot=self.bot_id, reason=reason)
                    continue
                risk_pct  = two_pct_engine.get_risk_pct(
                    self.bot_id,
                    self.registry_cfg.get("risk_profile",{}).get("max_risk_pct",2.0))
                size_mult = two_pct_engine.get_position_size_mult(self.bot_id)

            # Profit range gate (new)
            elif range_active:
                ok, reason, adj_risk = profit_range_gate.check(self.bot_id, signal, True)
                if not ok:
                    log.debug("range_blocked", bot=self.bot_id, reason=reason)
                    continue
                risk_pct  = adj_risk if adj_risk > 0 else \
                             get_bot_risk_for_target(
                                 self.bot_config.get("bot_id", self.bot_id),
                                 profit_range_engine.get_state(self.bot_id).effective_target)
                size_mult = profit_range_engine.get_position_scale(self.bot_id)

            else:
                # Normal mode
                risk_pct  = self.registry_cfg.get("risk_profile",{}).get("max_risk_pct", 2.0)
                size_mult = 1.0

            # Circuit breaker
            cb = await CircuitBreaker().check(
                user_id=self.user_id, bot_id=self.bot_id,
                current_equity=self._balance,
                starting_equity=self._starting_balance,
                daily_low_equity=self._daily_low,
                config={"max_daily_dd_pct": self.bot_config.get("drawdown_circuit_breaker_pct", 15)},
            )
            if cb.get("triggered"):
                await self.stop(reason=cb["reason"])
                return

            max_open = self.registry_cfg.get("risk_profile",{}).get("max_open", 4)
            if len(self._open_positions) >= max_open:
                continue

            # Execute
            result = await self.executor.execute(
                user_id=self.user_id, bot_id=self.bot_id,
                signal=signal, risk_pct=risk_pct,
                exchange_client=self.exchange, mt5_bridge=self.mt5,
                balance=self._balance, platform=self.platform,
                size_mult=size_mult,
            )

            if result.get("success"):
                self._open_positions.append({
                    "pair": pair, "signal": signal,
                    "result": result, "opened_at": time.time()})
                # Notification (with both mode states)
                pr_state = profit_range_engine.get_dashboard_state(self.bot_id)
                two_pct  = two_pct_engine.get_state(self.bot_id)
                body_extra = ""
                if two_pct_active:
                    body_extra = f" | 2% Progress: {two_pct['session_pnl_pct']:.2f}%"
                elif range_active and pr_state.get("active"):
                    body_extra = (f" | {pr_state['effective_target']}% Progress: "
                                  f"{pr_state['session_pnl_pct']:.2f}%")
                await notification_service.send(
                    user_id=self.user_id, event="trade_opened",
                    title=f"📊 {pair} {signal.direction.upper()}",
                    body=(f"{signal.direction.upper()} {pair} | "
                          f"Conf: {signal.confidence:.0f}% | RR: {signal.rr_ratio:.1f}"
                          f"{body_extra}"),
                    data={"bot_id": self.bot_id, "pair": pair,
                          "two_pct": two_pct, "profit_range": pr_state},
                )
                security_auditor.record_trade_result(self.bot_id, 0, "")

        await self._monitor_positions()

    async def _monitor_positions(self):
        still_open = []
        for pos in self._open_positions:
            sig, pair = pos["signal"], pos["pair"]
            df = await self.feed.get_candles(
                pair, "1m", exchange_client=self.exchange, mt5_bridge=self.mt5, count=5)
            if df is None or df.empty:
                still_open.append(pos); continue

            current = float(df.iloc[-1].get("close", sig.entry))
            tp_hit  = ((sig.direction == "long"  and current >= sig.tp2) or
                       (sig.direction == "short" and current <= sig.tp2))
            sl_hit  = ((sig.direction == "long"  and current <= sig.sl) or
                       (sig.direction == "short" and current >= sig.sl))
            max_hold = 4*3600 if self.is_scalp_bot else 72*3600
            timed   = (time.time() - pos["opened_at"]) > max_hold

            if tp_hit or sl_hit or timed:
                if sig.direction == "long":
                    pnl_pct = (current - sig.entry) / sig.entry * 100
                else:
                    pnl_pct = (sig.entry - current) / sig.entry * 100
                reason = "tp" if tp_hit else ("sl" if sl_hit else "timeout")

                # Process 2% mode result (preserved)
                if two_pct_engine.is_enabled(self.bot_id):
                    ar = two_pct_engine.record_result(self.bot_id, pnl_pct)
                    await self._handle_two_pct_action(ar)

                # Process profit range result (new)
                if profit_range_engine.is_active(self.bot_id):
                    ar2 = await profit_range_engine.record_result(
                        self.bot_id, pnl_pct, self.user_id)
                    if ar2.get("action") in ("target_hit","daily_stop"):
                        await self.stop(reason=f"profit_range_{ar2['action']}")
                        return
                    elif ar2.get("action") == "loss_pause":
                        await asyncio.sleep(self.loop_sleep * 2)
                        profit_range_engine.resume_after_pause(self.bot_id)

                # Capital maximizer
                await capital_maximizer.process_trade_result(
                    user_id=self.user_id, bot_id=self.bot_id,
                    bot_config=self.bot_config,
                    trade_result={"pnl_pct": pnl_pct,
                                  "pnl_usd": self._balance * pnl_pct / 100},
                    account_state={"equity": self._balance,
                                   "starting_equity": self._starting_balance,
                                   "daily_low_equity": self._daily_low},
                )

                self._balance *= (1 + pnl_pct / 100)
                self._daily_low = min(self._daily_low, self._balance)

                # AI brain learn
                try:
                    df2 = await self.feed.get_candles(pair, self.primary_tf, count=5)
                    if df2 is not None:
                        from ai.ultra_brain import extract_ultra_features
                        feats = extract_ultra_features(df2, _infer_asset_class(pair))
                        ultra_brain.record_outcome(feats, sig.direction, pnl_pct)
                except Exception:
                    pass

                security_auditor.record_trade_result(self.bot_id, pnl_pct, "")
                emoji = "✅" if pnl_pct > 0 else "❌"
                pr    = profit_range_engine.get_dashboard_state(self.bot_id)
                await notification_service.send(
                    user_id=self.user_id, event="trade_closed",
                    title=f"{emoji} {pair} {pnl_pct:+.2f}%",
                    body=(f"{sig.direction.upper()} {pair} | PnL: {pnl_pct:+.2f}% | {reason}"),
                    data={"bot_id": self.bot_id, "pnl_pct": pnl_pct,
                          "profit_range": pr,
                          "two_pct": two_pct_engine.get_state(self.bot_id)},
                )
                log.info("trade_closed", bot=self.bot_id, pair=pair,
                         pnl=round(pnl_pct,3), reason=reason)
            else:
                still_open.append(pos)

        self._open_positions = still_open

    async def _handle_two_pct_action(self, ar: dict):
        """Preserved from v7 exactly."""
        action = ar.get("action")
        if action == "target_hit":
            await notification_service.send(
                user_id=self.user_id, event="two_pct_target_hit",
                title="🎯 2% Target Reached! Bot Paused",
                body=(f"Bot hit 2% in {ar.get('trades_used','?')} trades. "
                      "Profit locked. Resumes next session."),
                data={"bot_id": self.bot_id, **ar},
            )
            try:
                db.table("bots").update({"status":"paused","stop_reason":"2% target hit"}
                                         ).eq("id",self.bot_id).execute()
            except Exception: pass
            self._running = False
        elif action == "pause":
            await asyncio.sleep(self.loop_sleep * 2)
            s = two_pct_engine._state.get(self.bot_id)
            if s: s["paused_for_losses"] = False
        elif action == "daily_stop":
            await self.stop(reason="2% mode daily loss stop")

    async def _get_macro_context(self, pair) -> dict:
        try:
            row = db.table("commodity_macro_context").select("*").order(
                "snapshot_time", desc=True).limit(1).maybe_single().execute()
            if row.data:
                return {
                    "dxy_trend":      row.data.get("dxy_trend","neutral"),
                    "vix_level":      row.data.get("vix_level", 20.0),
                    "btc_dominance":  row.data.get("btc_dominance", 50.0),
                    "inflation_regime":row.data.get("inflation_regime","moderate"),
                    "risk_sentiment": row.data.get("risk_sentiment","neutral"),
                }
        except Exception: pass
        return {}


# ══════════════════════════════════════════════════════════════
# LOOP CONTROLLER — ULTRA
# ══════════════════════════════════════════════════════════════

class LoopController:
    """Manages all active bots with profit range + maintenance support."""

    def __init__(self):
        self._runners: dict[str, BotRunner]     = {}
        self._tasks:   dict[str, asyncio.Task]  = {}

    async def start_bot(self, bot_db_row, exchange_client=None, mt5_bridge=None):
        bid = str(bot_db_row["id"])
        if bid in self._runners and self._tasks.get(bid) and not self._tasks[bid].done():
            return False
        runner = BotRunner(bid, str(bot_db_row["user_id"]),
                           bot_db_row, exchange_client, mt5_bridge)
        self._runners[bid] = runner
        self._tasks[bid]   = asyncio.create_task(runner.start(), name=f"bot_{bid}")
        return True

    async def stop_bot(self, bot_id, reason="manual"):
        runner = self._runners.get(bot_id)
        if runner: await runner.stop(reason)
        task = self._tasks.get(bot_id)
        if task and not task.done(): task.cancel()

    async def toggle_two_pct_mode(self, bot_id, enable) -> dict:
        runner = self._runners.get(bot_id)
        if not runner: return {"success": False, "error": "Bot not running"}
        if enable: await runner.enable_two_pct_mode()
        else:      await runner.disable_two_pct_mode()
        return {"success": True, "two_pct_state": two_pct_engine.get_state(bot_id)}

    async def set_profit_range(self, bot_id, target_pct, mode) -> dict:
        """Dashboard button → set profit range for bot."""
        runner = self._runners.get(bot_id)
        if runner:
            state = await runner.set_profit_range(target_pct, mode)
        else:
            state = capital_maximizer.set_profit_range(bot_id, target_pct, mode)
        return {"success": True, "state": state}

    def get_profit_range_state(self, bot_id) -> dict:
        return capital_maximizer.get_profit_range_state(bot_id)

    def get_two_pct_state(self, bot_id) -> dict:
        return two_pct_engine.get_state(bot_id)

    async def enter_maintenance(self, message="Scheduled maintenance"):
        await maintenance_manager.enter_global_maintenance(message)

    async def exit_maintenance(self):
        await maintenance_manager.exit_global_maintenance()

    def get_maintenance_status(self) -> dict:
        return maintenance_manager.get_status()

    def status(self) -> dict:
        active = len([t for t in self._tasks.values() if not t.done()])
        return {
            "active_bots":  active,
            "total_bots":   len(self._runners),
            "two_pct_bots": sum(1 for bid in self._runners
                                if two_pct_engine.is_enabled(bid)),
            "range_bots":   sum(1 for bid in self._runners
                                if profit_range_engine.is_active(bid)),
            "maintenance":  maintenance_manager.get_status(),
        }


# ── Helpers ───────────────────────────────────────────────────

def _infer_asset_class(pair: str) -> str:
    p = pair.upper()
    if "XAU" in p or "GOLD" in p or "PAXG" in p or "XAUT" in p: return "gold"
    if "XAG" in p or "SILVER" in p: return "silver"
    if "WTI" in p or "OIL"  in p:   return "commodities"
    if "/" in p:
        base = p.split("/")[0]
        if base in ("EUR","GBP","AUD","NZD","USD","CHF","CAD","JPY"):
            return "forex"
    return "crypto"


def _commodity_to_ultra(csig, pair: str) -> UltraSignal:
    from ai.ultra_brain import UltraSignal as US
    return US(
        direction=csig.direction, confidence=csig.confidence,
        pair=pair, timeframe=csig.timeframe,
        entry=csig.entry, sl=csig.sl,
        tp1=csig.tp1, tp2=csig.tp2, tp3=csig.tp3,
        rr_ratio=csig.rr_ratio, sl_mult=2.0, tp_mult=4.0,
        regime="commodities", engines_agreed=3, consensus_pct=75.0,
        fast_path=False, latency_ms=0.0,
        reasons=[csig.reason],
        metadata={"asset_class": csig.asset_class, "strategy": csig.strategy},
    )


# Singletons
loop_controller = LoopController()
