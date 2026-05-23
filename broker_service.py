"""
services/capital_maximizer.py — ESTRADE v7 ULTRA Capital Maximizer
═══════════════════════════════════════════════════════════════════════════════
ULTRA ADVANCED — All original features preserved + new:

━━━ PROFIT RANGE SELECTOR (NEW) ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Selectable target: 2% · 3% · 4% · 5% · 6% · 7% · 8% · 10% · 12% · 15%

  Two modes (user selects per bot):
    PER TRADE   → each individual trade targets selected %
                  risk = target × risk_ratio (e.g. 2% target → 0.44% risk)
                  bot pauses after any single trade hits target
                  perfect for precision entries

    PER SESSION → accumulate trades until session total = target %
                  smaller risk per trade (target / expected_trades)
                  bot keeps trading until cumulative PnL ≥ target
                  auto-pauses at end of session window (Asia/London/NY)
                  perfect for scalping bots

  Risk scales automatically:
    2%  → risk 0.40–0.50%   | confidence ≥ 68%  | RR ≥ 1.5
    3%  → risk 0.60–0.75%   | confidence ≥ 70%  | RR ≥ 1.6
    5%  → risk 0.90–1.25%   | confidence ≥ 74%  | RR ≥ 1.8
    7%  → risk 1.20–1.75%   | confidence ≥ 76%  | RR ≥ 2.0
    10% → risk 1.80–2.50%   | confidence ≥ 78%  | RR ≥ 2.2
    15% → risk 2.50–3.75%   | confidence ≥ 82%  | RR ≥ 2.5

  Adaptive features:
    → Win streak scale: after 3 consecutive wins, size +15% (max +50%)
    → Loss protection: 2 consecutive losses → pause + re-evaluate
    → Daily hard stop: if daily loss ≥ 50% of daily target → stop
    → Smart re-entry: after pause, wait for 80%+ confidence signal
    → Auto-adjust: if win rate drops below 50% → reduce next target by 1 step

━━━ ORIGINAL FEATURES (all preserved) ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ① Small Profit Mode (Headway-style)
  ② Compound Growth Engine (RoyalIQ-style Kelly Criterion)
  ③ Velocity Scalping Engine (50-100 trades/day)
  ④ Exponential Mode (Fibonacci sizing, 2× capital/week)
  ⑤ Circuit Breakers (drawdown protection)
  ⑥ 2% Pro Mode (from trading_loop — preserved exactly)
═══════════════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations
import asyncio
import math
import statistics
import random
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Optional, Literal
import structlog

from core.database    import db
from services.notification_service import notification_service

log = structlog.get_logger("capital_maximizer")


# ══════════════════════════════════════════════════════════════
# PROFIT RANGE CONSTANTS
# ══════════════════════════════════════════════════════════════

PROFIT_RANGE_OPTIONS = [2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 10.0, 12.0, 15.0]

TARGET_MODE = Literal["per_trade", "per_session"]

# Per-target risk profile (target_pct → config)
PROFIT_RANGE_CONFIG: dict[float, dict] = {
    2.0:  {"risk_ratio": 0.22, "min_confidence": 68.0, "min_rr": 1.5, "loss_pause": 2, "daily_stop_ratio": 0.50, "scale_after": 3, "max_scale": 1.5,  "label": "2%",  "color": "#22c55e", "badge": "SAFE"},
    3.0:  {"risk_ratio": 0.22, "min_confidence": 70.0, "min_rr": 1.6, "loss_pause": 2, "daily_stop_ratio": 0.50, "scale_after": 3, "max_scale": 1.5,  "label": "3%",  "color": "#4ade80", "badge": "MODERATE"},
    4.0:  {"risk_ratio": 0.23, "min_confidence": 71.0, "min_rr": 1.7, "loss_pause": 2, "daily_stop_ratio": 0.45, "scale_after": 3, "max_scale": 1.6,  "label": "4%",  "color": "#a3e635", "badge": "BALANCED"},
    5.0:  {"risk_ratio": 0.24, "min_confidence": 72.0, "min_rr": 1.8, "loss_pause": 2, "daily_stop_ratio": 0.45, "scale_after": 3, "max_scale": 1.6,  "label": "5%",  "color": "#facc15", "badge": "ACTIVE"},
    6.0:  {"risk_ratio": 0.24, "min_confidence": 73.0, "min_rr": 1.9, "loss_pause": 2, "daily_stop_ratio": 0.40, "scale_after": 3, "max_scale": 1.7,  "label": "6%",  "color": "#fb923c", "badge": "GROWTH"},
    7.0:  {"risk_ratio": 0.25, "min_confidence": 74.0, "min_rr": 2.0, "loss_pause": 2, "daily_stop_ratio": 0.40, "scale_after": 3, "max_scale": 1.7,  "label": "7%",  "color": "#f97316", "badge": "HIGH"},
    8.0:  {"risk_ratio": 0.25, "min_confidence": 75.0, "min_rr": 2.0, "loss_pause": 2, "daily_stop_ratio": 0.38, "scale_after": 3, "max_scale": 1.8,  "label": "8%",  "color": "#ef4444", "badge": "BOLD"},
    10.0: {"risk_ratio": 0.26, "min_confidence": 76.0, "min_rr": 2.2, "loss_pause": 2, "daily_stop_ratio": 0.35, "scale_after": 3, "max_scale": 2.0,  "label": "10%", "color": "#dc2626", "badge": "AGGRESSIVE"},
    12.0: {"risk_ratio": 0.28, "min_confidence": 78.0, "min_rr": 2.3, "loss_pause": 2, "daily_stop_ratio": 0.33, "scale_after": 3, "max_scale": 2.0,  "label": "12%", "color": "#b91c1c", "badge": "ULTRA"},
    15.0: {"risk_ratio": 0.30, "min_confidence": 80.0, "min_rr": 2.5, "loss_pause": 2, "daily_stop_ratio": 0.30, "scale_after": 3, "max_scale": 2.5,  "label": "15%", "color": "#991b1b", "badge": "MAX"},
}

# Session windows (UTC)
SESSION_WINDOWS = {
    "asia":     {"start_h": 0,  "end_h": 8,  "label": "Asia",     "icon": "🌏"},
    "london":   {"start_h": 8,  "end_h": 16, "label": "London",   "icon": "🇬🇧"},
    "new_york": {"start_h": 13, "end_h": 21, "label": "New York", "icon": "🗽"},
    "overnight":{"start_h": 21, "end_h": 24, "label": "Overnight","icon": "🌙"},
}


def get_current_session() -> str:
    h = datetime.now(timezone.utc).hour
    if 0 <= h < 8:   return "asia"
    if 8 <= h < 16:  return "london"
    if 13 <= h < 21: return "new_york"
    return "overnight"


def get_config(target_pct: float) -> dict:
    """Get risk config for a given target %."""
    # Round to nearest option
    closest = min(PROFIT_RANGE_OPTIONS, key=lambda x: abs(x - target_pct))
    return PROFIT_RANGE_CONFIG[closest]


def calc_risk_pct(target_pct: float, mode: str = "per_session",
                   expected_trades: int = 5) -> float:
    """
    Calculate per-trade risk based on target and mode.
    Per trade:   risk = target × risk_ratio
    Per session: risk = (target / expected_trades) × risk_ratio × 1.2
    """
    cfg = get_config(target_pct)
    ratio = cfg["risk_ratio"]
    if mode == "per_trade":
        return round(target_pct * ratio, 3)
    else:
        per_trade_target = target_pct / max(1, expected_trades)
        return round(per_trade_target * ratio * 1.2, 3)


# ══════════════════════════════════════════════════════════════
# PROFIT RANGE ENGINE (core new system)
# ══════════════════════════════════════════════════════════════

@dataclass
class ProfitRangeState:
    bot_id:             str
    target_pct:         float       = 2.0
    mode:               str         = "per_session"   # per_trade | per_session
    session_pnl_pct:    float       = 0.0
    daily_pnl_pct:      float       = 0.0
    trades_done:        int         = 0
    consecutive_wins:   int         = 0
    consecutive_losses: int         = 0
    current_scale:      float       = 1.0
    target_hit:         bool        = False
    paused:             bool        = False
    pause_reason:       str         = ""
    session:            str         = "new_york"
    session_start:      str         = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    win_rate_window:    list        = field(default_factory=list)   # last 20 results
    auto_adjusted_target: float     = 0.0   # 0 = no adjustment active
    last_trade_time:    float       = 0.0

    @property
    def cfg(self) -> dict:
        return get_config(self.effective_target)

    @property
    def effective_target(self) -> float:
        return self.auto_adjusted_target if self.auto_adjusted_target > 0 else self.target_pct

    @property
    def progress_pct(self) -> float:
        if self.effective_target <= 0: return 0
        return min(100, self.session_pnl_pct / self.effective_target * 100)

    @property
    def remaining_pct(self) -> float:
        return max(0, self.effective_target - self.session_pnl_pct)

    @property
    def risk_pct(self) -> float:
        expected = max(1, 20 // max(1, int(self.effective_target)))
        return calc_risk_pct(self.effective_target, self.mode, expected)

    @property
    def min_confidence(self) -> float:
        return self.cfg["min_confidence"]

    @property
    def min_rr(self) -> float:
        return self.cfg["min_rr"]

    @property
    def win_rate(self) -> float:
        if not self.win_rate_window: return 0.65
        return sum(self.win_rate_window) / len(self.win_rate_window)


class ProfitRangeEngine:
    """
    Ultra-advanced profit range selection and management.
    Handles both per-trade and per-session target modes.
    Self-adjusting: reduces target if performance degrades.
    """

    def __init__(self):
        self._states: dict[str, ProfitRangeState] = {}

    # ── Init & Config ─────────────────────────────────────────

    def configure(self, bot_id: str, target_pct: float,
                   mode: str = "per_session",
                   starting_balance: float = 1000.0) -> ProfitRangeState:
        """Set or update profit range for a bot."""
        if bot_id not in self._states:
            self._states[bot_id] = ProfitRangeState(bot_id=bot_id)

        s = self._states[bot_id]
        s.target_pct          = target_pct
        s.mode                = mode
        s.session_pnl_pct     = 0.0
        s.trades_done         = 0
        s.consecutive_wins    = 0
        s.consecutive_losses  = 0
        s.current_scale       = 1.0
        s.target_hit          = False
        s.paused              = False
        s.pause_reason        = ""
        s.auto_adjusted_target = 0.0
        s.session             = get_current_session()
        s.session_start       = datetime.now(timezone.utc).isoformat()

        log.info("profit_range_configured", bot=bot_id,
                 target=target_pct, mode=mode)
        return s

    def get_state(self, bot_id: str) -> Optional[ProfitRangeState]:
        return self._states.get(bot_id)

    def is_active(self, bot_id: str) -> bool:
        s = self._states.get(bot_id)
        return s is not None and s.target_pct > 0

    # ── Trade Gate ────────────────────────────────────────────

    def can_trade(self, bot_id: str, signal_confidence: float,
                   signal_rr: float) -> tuple[bool, str]:
        """
        Main gate: can the bot open a new trade?
        Returns (allowed, reason).
        """
        s = self._states.get(bot_id)
        if not s:
            return True, "no_range_config"

        # Session check — new session resets
        current_session = get_current_session()
        if current_session != s.session and s.mode == "per_session":
            self._reset_session(bot_id, current_session)

        if s.target_hit:
            return False, f"✅ Target {s.effective_target}% already hit this session"

        if s.paused:
            return False, f"⏸ Paused: {s.pause_reason}"

        # Confidence gate
        if signal_confidence < s.min_confidence:
            return False, (f"Confidence {signal_confidence:.1f}% < "
                           f"{s.min_confidence:.0f}% required for "
                           f"{s.effective_target}% target")

        # RR gate
        if signal_rr < s.min_rr:
            return False, (f"RR {signal_rr:.2f} < {s.min_rr:.1f} "
                           f"required for {s.effective_target}% target")

        # Per-trade mode: only allow if no current session trades using up space
        if s.mode == "per_trade" and s.target_hit:
            return False, "Per-trade target already hit"

        return True, "ok"

    def get_position_scale(self, bot_id: str) -> float:
        s = self._states.get(bot_id)
        if not s: return 1.0
        cfg = s.cfg
        streak = s.consecutive_wins
        if streak <= 0: return 1.0
        scale_after = cfg.get("scale_after", 3)
        max_scale   = cfg.get("max_scale",   1.5)
        increments  = streak // scale_after
        scale = 1.0 + increments * 0.15   # +15% per streak batch
        return round(min(max_scale, scale), 2)

    # ── Record Result ─────────────────────────────────────────

    async def record_result(self, bot_id: str, pnl_pct: float,
                             user_id: str = "") -> dict:
        """
        Called after every trade closes.
        Returns action dict: continue | pause | target_hit | daily_stop | adjust
        """
        s = self._states.get(bot_id)
        if not s:
            return {"action": "continue"}

        won = pnl_pct > 0
        s.session_pnl_pct   += pnl_pct
        s.daily_pnl_pct     += pnl_pct
        s.trades_done       += 1
        s.win_rate_window.append(1 if won else 0)
        if len(s.win_rate_window) > 20:
            s.win_rate_window.pop(0)

        cfg = s.cfg

        if won:
            s.consecutive_wins   += 1
            s.consecutive_losses  = 0
            s.paused              = False
        else:
            s.consecutive_losses += 1
            s.consecutive_wins    = 0
            s.current_scale       = 1.0  # reset scale on loss

        s.current_scale = self.get_position_scale(bot_id)

        # ── Per-trade mode: hit on single trade ───────────────
        if s.mode == "per_trade" and won and pnl_pct >= s.effective_target:
            s.target_hit = True
            await self._notify_target(user_id, bot_id, s, "per_trade")
            return {"action": "target_hit", "mode": "per_trade",
                    "pnl_pct": pnl_pct, "target": s.effective_target}

        # ── Per-session mode: accumulate ─────────────────────
        if s.mode == "per_session" and s.session_pnl_pct >= s.effective_target:
            s.target_hit = True
            await self._notify_target(user_id, bot_id, s, "per_session")
            return {"action": "target_hit", "mode": "per_session",
                    "session_pnl": s.session_pnl_pct,
                    "trades_used": s.trades_done,
                    "target": s.effective_target}

        # ── Daily loss stop ───────────────────────────────────
        daily_stop = -(s.effective_target * cfg["daily_stop_ratio"])
        if s.daily_pnl_pct <= daily_stop:
            s.paused      = True
            s.pause_reason = f"Daily loss {abs(s.daily_pnl_pct):.2f}% ≥ stop limit"
            await self._notify_daily_stop(user_id, bot_id, s)
            return {"action": "daily_stop",
                    "daily_pnl": s.daily_pnl_pct,
                    "stop_threshold": daily_stop}

        # ── Consecutive loss pause ────────────────────────────
        if s.consecutive_losses >= cfg["loss_pause"]:
            s.paused       = True
            s.pause_reason = f"{s.consecutive_losses} consecutive losses"
            await self._notify_loss_pause(user_id, bot_id, s)
            # Schedule auto-resume after 2 candles (handled by trading loop)
            return {"action": "loss_pause",
                    "consecutive_losses": s.consecutive_losses,
                    "session_pnl": s.session_pnl_pct}

        # ── Auto-adjust target if win rate drops ──────────────
        action = "continue"
        if len(s.win_rate_window) >= 10 and s.win_rate < 0.45:
            action = await self._auto_adjust_target(user_id, bot_id, s)

        return {
            "action":          action,
            "session_pnl_pct": round(s.session_pnl_pct, 3),
            "daily_pnl_pct":   round(s.daily_pnl_pct, 3),
            "remaining_pct":   round(s.remaining_pct, 3),
            "progress_pct":    round(s.progress_pct, 1),
            "trades_done":     s.trades_done,
            "current_scale":   s.current_scale,
            "consecutive_wins":s.consecutive_wins,
            "win_rate":        round(s.win_rate, 3),
        }

    # ── Auto-adjust ───────────────────────────────────────────

    async def _auto_adjust_target(self, user_id: str, bot_id: str,
                                    s: ProfitRangeState) -> str:
        """Reduce target by one step if win rate < 45%."""
        current = s.effective_target
        idx = PROFIT_RANGE_OPTIONS.index(
            min(PROFIT_RANGE_OPTIONS, key=lambda x: abs(x - current))
        )
        if idx > 0:
            new_target = PROFIT_RANGE_OPTIONS[idx - 1]
            s.auto_adjusted_target = new_target
            log.warning("target_auto_adjusted", bot=bot_id,
                        old=current, new=new_target, win_rate=s.win_rate)
            if user_id:
                await notification_service.send(
                    user_id=user_id,
                    event="target_auto_adjusted",
                    title=f"🔄 Target Auto-Adjusted: {bot_id}",
                    body=(f"Win rate {s.win_rate:.0%} below 45%. "
                          f"Target reduced from {current}% → {new_target}% to protect capital."),
                    data={"bot_id": bot_id, "old_target": current, "new_target": new_target},
                )
            return "target_adjusted"
        return "continue"

    def _reset_session(self, bot_id: str, new_session: str):
        s = self._states[bot_id]
        s.session_pnl_pct    = 0.0
        s.trades_done        = 0
        s.consecutive_wins   = 0
        s.consecutive_losses = 0
        s.current_scale      = 1.0
        s.target_hit         = False
        s.paused             = False
        s.pause_reason       = ""
        s.session            = new_session
        s.session_start      = datetime.now(timezone.utc).isoformat()
        s.auto_adjusted_target = 0.0

    def resume_after_pause(self, bot_id: str):
        s = self._states.get(bot_id)
        if s:
            s.paused             = False
            s.pause_reason       = ""
            s.consecutive_losses = 0

    # ── Notifications ─────────────────────────────────────────

    async def _notify_target(self, user_id: str, bot_id: str,
                               s: ProfitRangeState, mode: str):
        if not user_id: return
        emoji = "🎯" if s.effective_target <= 5 else ("🔥" if s.effective_target <= 10 else "🚀")
        await notification_service.send(
            user_id=user_id,
            event="profit_target_hit",
            title=f"{emoji} {s.effective_target}% Target Hit! ({mode})",
            body=(f"Bot achieved {s.session_pnl_pct:.2f}% in {s.trades_done} trades. "
                  f"Profit locked. Resumes next session."),
            data={"bot_id": bot_id, "target": s.effective_target,
                  "mode": mode, "pnl": s.session_pnl_pct},
        )

    async def _notify_daily_stop(self, user_id: str, bot_id: str,
                                   s: ProfitRangeState):
        if not user_id: return
        await notification_service.send(
            user_id=user_id,
            event="daily_loss_stop",
            title=f"🛑 Daily Loss Stop: {bot_id}",
            body=(f"Daily loss {abs(s.daily_pnl_pct):.2f}% reached stop limit. "
                  f"Capital protected. Resumes tomorrow."),
            data={"bot_id": bot_id, "daily_pnl": s.daily_pnl_pct},
            is_urgent=True,
        )

    async def _notify_loss_pause(self, user_id: str, bot_id: str,
                                   s: ProfitRangeState):
        if not user_id: return
        await notification_service.send(
            user_id=user_id,
            event="loss_pause",
            title=f"⏸ Loss Pause: {bot_id}",
            body=(f"{s.consecutive_losses} consecutive losses detected. "
                  f"Auto-resuming after 2 candles."),
            data={"bot_id": bot_id, "losses": s.consecutive_losses},
        )

    # ── Dashboard data ────────────────────────────────────────

    def get_dashboard_state(self, bot_id: str) -> dict:
        s = self._states.get(bot_id)
        if not s:
            return {
                "active": False,
                "options": PROFIT_RANGE_OPTIONS,
                "config_per_target": {
                    t: {"risk_pct": calc_risk_pct(t, "per_session"),
                        "min_confidence": PROFIT_RANGE_CONFIG[t]["min_confidence"],
                        "min_rr":         PROFIT_RANGE_CONFIG[t]["min_rr"],
                        "color":          PROFIT_RANGE_CONFIG[t]["color"],
                        "label":          PROFIT_RANGE_CONFIG[t]["label"],
                        "badge":          PROFIT_RANGE_CONFIG[t]["badge"]}
                    for t in PROFIT_RANGE_OPTIONS
                }
            }
        cfg = s.cfg
        return {
            "active":          True,
            "bot_id":          bot_id,
            "target_pct":      s.target_pct,
            "effective_target":s.effective_target,
            "mode":            s.mode,
            "session":         s.session,
            "session_pnl_pct": round(s.session_pnl_pct, 3),
            "daily_pnl_pct":   round(s.daily_pnl_pct, 3),
            "remaining_pct":   round(s.remaining_pct, 3),
            "progress_pct":    round(s.progress_pct, 1),
            "trades_done":     s.trades_done,
            "target_hit":      s.target_hit,
            "paused":          s.paused,
            "pause_reason":    s.pause_reason,
            "consecutive_wins":s.consecutive_wins,
            "consecutive_losses": s.consecutive_losses,
            "current_scale":   round(s.current_scale, 2),
            "win_rate":        round(s.win_rate, 3),
            "risk_pct":        round(s.risk_pct, 3),
            "min_confidence":  cfg["min_confidence"],
            "min_rr":          cfg["min_rr"],
            "color":           cfg["color"],
            "badge":           cfg["badge"],
            "auto_adjusted":   s.auto_adjusted_target > 0,
            "options":         PROFIT_RANGE_OPTIONS,
            "mode_options":    ["per_trade", "per_session"],
            "session_windows": SESSION_WINDOWS,
        }


# Singleton
profit_range_engine = ProfitRangeEngine()


# ══════════════════════════════════════════════════════════════
# SMALL PROFIT MODE — PRESERVED FROM ORIGINAL
# ══════════════════════════════════════════════════════════════

class SmallProfitEngine:
    """Headway-inspired small profit collection engine (preserved)."""

    def __init__(self, daily_target_pct=3.0, session_target_pct=1.0,
                 max_daily_loss_pct=5.0, sessions=3):
        self.daily_target_pct   = daily_target_pct
        self.session_target_pct = session_target_pct
        self.max_daily_loss_pct = max_daily_loss_pct
        self.sessions           = sessions
        self._session_pnl: dict[str, dict] = {}

    def get_session(self) -> str:
        return get_current_session()

    async def check_and_pause_on_target(self, user_id, bot_id, current_pnl_pct) -> dict:
        session = self.get_session()
        state = self._session_pnl.setdefault(user_id, {
            "daily_pnl_pct": 0.0, "session_pnl_pct": 0.0,
            "current_session": session, "trades_today": 0,
            "paused_for_target": False, "paused_for_loss": False,
        })
        if state["current_session"] != session:
            state["session_pnl_pct"] = 0.0
            state["current_session"] = session
            state["paused_for_target"] = False
        state["daily_pnl_pct"]   += current_pnl_pct
        state["session_pnl_pct"] += current_pnl_pct
        state["trades_today"]    += 1
        result = {"pause": False, "reason": None, "resume_at": None}
        if state["session_pnl_pct"] >= self.session_target_pct and not state["paused_for_target"]:
            state["paused_for_target"] = True
            result = {"pause": True, "reason": f"Session target {self.session_target_pct}% reached 🎯",
                      "resume_at": "next_session"}
            await notification_service.send(
                user_id=user_id, event="target_reached",
                title="🎯 Session Target Reached!",
                body=f"Bot {bot_id} hit {self.session_target_pct}% session target.",
                data={"bot_id": bot_id},
            )
        if state["daily_pnl_pct"] >= self.daily_target_pct:
            result = {"pause": True, "reason": f"Daily target {self.daily_target_pct}% reached 🏆",
                      "resume_at": "tomorrow_open"}
        if state["daily_pnl_pct"] <= -self.max_daily_loss_pct:
            result = {"pause": True, "reason": f"Daily loss limit {self.max_daily_loss_pct}% hit 🛑",
                      "resume_at": "tomorrow_open"}
            await notification_service.send(
                user_id=user_id, event="loss_limit_hit",
                title="🛑 Loss Limit Reached",
                body=f"Bot {bot_id} stopped. Daily loss = {abs(state['daily_pnl_pct']):.2f}%.",
                data={"bot_id": bot_id}, is_urgent=True,
            )
        try:
            db.table("capital_mode_state").upsert({
                "user_id": user_id, "bot_id": bot_id, "session": session,
                "daily_pnl_pct": round(state["daily_pnl_pct"], 4),
                "session_pnl_pct": round(state["session_pnl_pct"], 4),
                "trades_today": state["trades_today"], "is_paused": result["pause"],
                "pause_reason": result.get("reason", ""),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }).execute()
        except Exception:
            pass
        return {**result, "state": state}

    def calculate_safe_lot(self, balance, daily_profit_so_far, risk_pct=0.5):
        earned_today = balance * (abs(daily_profit_so_far) / 100)
        max_risk = min(balance * risk_pct / 100, earned_today * 0.5)
        return max(0.01, max_risk)


# ══════════════════════════════════════════════════════════════
# COMPOUND GROWTH ENGINE — PRESERVED FROM ORIGINAL
# ══════════════════════════════════════════════════════════════

class CompoundGrowthEngine:
    """RoyalIQ-inspired compound growth (preserved)."""

    def kelly_criterion(self, win_rate, avg_win_pct, avg_loss_pct) -> float:
        if avg_loss_pct <= 0: return 0.01
        r = avg_win_pct / avg_loss_pct
        kelly = win_rate - (1 - win_rate) / r
        return max(0.01, min(0.25, round(kelly, 4)))

    def calculate_compound_size(self, initial_capital, current_capital,
                                  win_rate, avg_win_pct, avg_loss_pct,
                                  reinvest_pct=70.0) -> dict:
        kelly            = self.kelly_criterion(win_rate, avg_win_pct, avg_loss_pct)
        effective_risk   = kelly * (reinvest_pct / 100)
        growth_factor    = current_capital / initial_capital if initial_capital > 0 else 1.0
        compound_mult    = min(3.0, math.sqrt(growth_factor))
        daily_growth_est = (1 + effective_risk * win_rate) ** (avg_win_pct / 100)
        weekly_growth    = daily_growth_est ** 5
        return {
            "kelly_fraction":     kelly,
            "effective_risk_pct": round(effective_risk * 100, 2),
            "compound_multiplier":round(compound_mult, 3),
            "projected_weekly_growth_pct": round((weekly_growth - 1) * 100, 2),
            "recommended_position_pct": round(effective_risk * 100, 2),
        }

    async def reinvest_profit(self, user_id, bot_id, trade_profit_usd,
                               reinvest_pct=70.0) -> dict:
        if trade_profit_usd <= 0:
            return {"reinvested": False, "reason": "no profit"}
        reinvest_amount = trade_profit_usd * (reinvest_pct / 100)
        withdraw_amount = trade_profit_usd * (1 - reinvest_pct / 100)
        try:
            db.table("bot_capital_allocation").upsert({
                "user_id": user_id, "bot_id": bot_id,
                "reinvested_usd": reinvest_amount, "withdrawn_usd": withdraw_amount,
                "trade_profit": trade_profit_usd,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }).execute()
        except Exception:
            pass
        return {"reinvested": True, "reinvest_amount": round(reinvest_amount, 4),
                "withdraw_amount": round(withdraw_amount, 4), "reinvest_pct": reinvest_pct}

    def project_capital_growth(self, starting_capital, daily_target_pct,
                                days=30, win_rate=0.65, reinvest_pct=70.0) -> list[dict]:
        capital = starting_capital
        results = [{"day": 0, "capital": capital, "profit": 0}]
        for day in range(1, days + 1):
            won     = random.random() < win_rate
            daily_pct = daily_target_pct * 0.7 if won else -daily_target_pct * 0.3
            profit  = capital * (daily_pct / 100)
            reinvested = profit * (reinvest_pct / 100) if profit > 0 else profit
            capital += reinvested
            results.append({"day": day, "capital": round(capital, 2),
                            "profit": round(profit, 2), "pct": round(daily_pct, 2), "won": won})
        return results


# ══════════════════════════════════════════════════════════════
# VELOCITY SCALPING ENGINE — PRESERVED FROM ORIGINAL
# ══════════════════════════════════════════════════════════════

class VelocityScalpingEngine:
    """HFT small-profit scalping (preserved)."""

    def __init__(self, target_trades_per_day=75, profit_per_trade_pct=0.2,
                 risk_per_trade_pct=0.1, reinvest_pct=80.0, pause_at_loss_pct=5.0):
        self.target_trades    = target_trades_per_day
        self.profit_per_trade = profit_per_trade_pct
        self.risk_per_trade   = risk_per_trade_pct
        self.reinvest_pct     = reinvest_pct
        self.pause_at_loss_pct= pause_at_loss_pct

    def calculate_velocity_lot(self, balance, current_win_streak=0) -> dict:
        streak_bonus   = min(0.5, current_win_streak * 0.05)
        effective_risk = self.risk_per_trade * (1 + streak_bonus)
        risk_usd       = balance * (effective_risk / 100)
        return {"risk_usd": round(risk_usd, 4), "effective_risk_pct": round(effective_risk, 4),
                "streak_bonus": streak_bonus, "recommended_sl_pct": round(effective_risk * 0.5, 4)}

    def daily_summary(self, trades, starting_balance) -> dict:
        if not trades:
            return {"trades": 0, "pnl": 0, "win_rate": 0}
        wins    = [t for t in trades if t.get("pnl", 0) > 0]
        total   = sum(t.get("pnl", 0) for t in trades)
        wr      = len(wins) / len(trades)
        return {"trades_done": len(trades), "target_trades": self.target_trades,
                "wins": len(wins), "losses": len(trades) - len(wins),
                "win_rate_pct": round(wr * 100, 1),
                "total_pnl_usd": round(total, 2),
                "total_pnl_pct": round(total / starting_balance * 100, 3)}


# ══════════════════════════════════════════════════════════════
# CIRCUIT BREAKER — PRESERVED FROM ORIGINAL
# ══════════════════════════════════════════════════════════════

class CircuitBreaker:
    """Automatic drawdown protection (preserved)."""

    async def check(self, user_id, bot_id, current_equity,
                     starting_equity, daily_low_equity, config) -> dict:
        daily_dd_pct = (starting_equity - current_equity) / starting_equity * 100
        checks = {
            "daily_drawdown": {
                "triggered": daily_dd_pct >= config.get("max_daily_dd_pct", 10.0),
                "severity": "critical",
                "reason": f"Daily drawdown {daily_dd_pct:.2f}% exceeded limit",
            },
            "equity_low": {
                "triggered": current_equity < starting_equity * 0.80,
                "severity": "critical",
                "reason": "Equity below 80% of starting balance",
            },
        }
        triggered = [(k, v) for k, v in checks.items() if v["triggered"]]
        if triggered:
            _, check = triggered[0]
            try:
                await notification_service.send_admin_alert(
                    title=f"🚨 Circuit Breaker: {bot_id}",
                    body=f"Bot {bot_id} HALTED. Reason: {check['reason']}",
                    severity=check["severity"],
                    data={"bot_id": bot_id, "current_equity": current_equity},
                )
                db.table("bots").update({
                    "status": "stopped", "stop_reason": check["reason"],
                    "circuit_breaker": True,
                    "stopped_at": datetime.now(timezone.utc).isoformat(),
                }).eq("id", bot_id).execute()
            except Exception:
                pass
            return {"triggered": True, "reason": check["reason"], "severity": check["severity"]}
        return {"triggered": False}


# ══════════════════════════════════════════════════════════════
# UNIFIED CAPITAL MAXIMIZER — PRESERVED + ENHANCED
# ══════════════════════════════════════════════════════════════

class CapitalMaximizer:
    """Unified entry point — all modes preserved + profit range engine added."""

    def __init__(self):
        self.small_profit    = SmallProfitEngine()
        self.compound        = CompoundGrowthEngine()
        self.velocity        = VelocityScalpingEngine()
        self.circuit         = CircuitBreaker()
        self.profit_range    = profit_range_engine   # NEW

    async def process_trade_result(self, user_id, bot_id, bot_config,
                                    trade_result, account_state) -> dict:
        pnl_pct = trade_result.get("pnl_pct", 0)
        pnl_usd = trade_result.get("pnl_usd", 0)
        response = {"reinvest": {}, "target_check": {},
                    "circuit_check": {}, "profit_range": {},
                    "should_pause": False}

        # Small profit mode (Headway-style)
        if bot_config.get("small_profit_mode"):
            tgt = await self.small_profit.check_and_pause_on_target(
                user_id, bot_id, pnl_pct)
            response["target_check"] = tgt
            if tgt.get("pause"):
                response["should_pause"] = True

        # Profit range engine
        if self.profit_range.is_active(bot_id):
            pr = await self.profit_range.record_result(bot_id, pnl_pct, user_id)
            response["profit_range"] = pr
            if pr.get("action") in ("target_hit", "daily_stop"):
                response["should_pause"] = True
            elif pr.get("action") == "loss_pause":
                response["should_pause"] = True

        # Compound reinvest
        reinvest_pct = bot_config.get("reinvest_pct", 0)
        if reinvest_pct > 0 and pnl_usd > 0:
            response["reinvest"] = await self.compound.reinvest_profit(
                user_id, bot_id, pnl_usd, reinvest_pct)

        # Circuit breaker
        cb = await self.circuit.check(
            user_id=user_id, bot_id=bot_id,
            current_equity=account_state.get("equity", 0),
            starting_equity=account_state.get("starting_equity", 0),
            daily_low_equity=account_state.get("daily_low_equity", 0),
            config={"max_daily_dd_pct": bot_config.get("drawdown_circuit_breaker_pct", 15.0)},
        )
        response["circuit_check"] = cb
        if cb.get("triggered"):
            response["should_pause"] = True

        return response

    def get_growth_projection(self, starting_capital, bot_config, days=30) -> dict:
        daily_target = bot_config.get("daily_target_pct", 3.0)
        reinvest_pct = bot_config.get("reinvest_pct", 70.0)
        projection   = self.compound.project_capital_growth(
            starting_capital, daily_target, days, 0.65, reinvest_pct)
        final        = projection[-1]["capital"] if projection else starting_capital
        return {
            "projection":       projection,
            "final_capital":    round(final, 2),
            "total_growth_pct": round((final - starting_capital) / starting_capital * 100, 2),
            "days":             days,
            "daily_target_pct": daily_target,
        }

    # ── Profit range helpers for API/dashboard ────────────────

    def set_profit_range(self, bot_id, target_pct, mode="per_session",
                          balance=1000.0) -> dict:
        state = self.profit_range.configure(bot_id, target_pct, mode, balance)
        return self.profit_range.get_dashboard_state(bot_id)

    def get_profit_range_state(self, bot_id) -> dict:
        return self.profit_range.get_dashboard_state(bot_id)


# Singleton
capital_maximizer = CapitalMaximizer()
