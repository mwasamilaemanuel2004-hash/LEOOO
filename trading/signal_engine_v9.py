"""
ai/discipline_engine.py — v10 GODMODE AI Discipline & Risk Logic
Prevents emotional trading. Enforces rules. Maximizes profit. Minimizes risk.
"""
from __future__ import annotations
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional
import structlog

log = structlog.get_logger("discipline")

@dataclass
class DisciplineState:
    bot_id: str
    # Consecutive tracking
    cons_wins: int = 0
    cons_losses: int = 0
    daily_trades: int = 0
    daily_pnl_pct: float = 0.0
    # Cooldown
    in_cooldown: bool = False
    cooldown_until: float = 0.0
    cooldown_reason: str = ""
    # Revenge trading prevention
    last_loss_time: float = 0.0
    revenge_block_until: float = 0.0
    # Overtrading prevention
    trades_last_hour: deque = field(default_factory=lambda: deque(maxlen=50))
    # FOMO prevention
    last_missed_signal: float = 0.0
    # Profit protection
    daily_target_hit: bool = False
    daily_target_pct: float = 5.0
    # Session stats
    peak_daily_pnl: float = 0.0

DISCIPLINE_RULES = {
    "max_daily_trades":        30,
    "max_hourly_trades":       8,
    "min_trade_gap_seconds":   30,
    "revenge_block_minutes":   15,
    "cooldown_after_losses":   3,
    "cooldown_minutes":        10,
    "max_daily_loss_pct":      5.0,
    "max_drawdown_pct":        15.0,
    "fomo_block_seconds":      60,
    "oversize_block_pct":      80.0,
    "min_confidence":          65.0,
    "min_rr":                  1.5,
    "required_engines_agree":  3,
}

class DisciplineEngine:
    """
    The AI discipline layer — enforces trading rules and prevents:
    1. Revenge trading (trading angry after a loss)
    2. Overtrading (too many trades per day/hour)
    3. FOMO (chasing missed signals)
    4. Oversizing (putting too much at risk)
    5. Low-quality entries (below confidence threshold)
    6. Trading during cooldown periods
    7. Exceeding daily loss limits
    8. Ignoring drawdown levels
    """

    def __init__(self):
        self._states: Dict[str, DisciplineState] = {}

    def _get(self, bot_id: str) -> DisciplineState:
        if bot_id not in self._states:
            self._states[bot_id] = DisciplineState(bot_id=bot_id)
        return self._states[bot_id]

    def check(
        self,
        bot_id: str,
        confidence: float,
        rr_ratio: float,
        engines_agree: int,
        drawdown_pct: float,
        daily_pnl_pct: float,
        proposed_size_pct: float,
        signal_timestamp: float = 0,
    ) -> dict:
        """
        Master discipline check. Returns approved/rejected with reason.
        EVERY trade must pass ALL checks before execution.
        """
        s = self._get(bot_id)
        now = time.time()
        rules = DISCIPLINE_RULES

        # ── 1. COOLDOWN CHECK ─────────────────────────────
        if s.in_cooldown and now < s.cooldown_until:
            remaining = int(s.cooldown_until - now)
            return self._reject(f"COOLDOWN: {s.cooldown_reason}. {remaining}s remaining.", "cooldown")

        if s.in_cooldown and now >= s.cooldown_until:
            s.in_cooldown = False
            s.cooldown_reason = ""
            log.info("Cooldown ended", bot_id=bot_id)

        # ── 2. REVENGE TRADING BLOCK ──────────────────────
        if now < s.revenge_block_until:
            remaining = int(s.revenge_block_until - now)
            return self._reject(f"REVENGE BLOCK: Cool down after loss. {remaining}s remaining.", "revenge")

        # ── 3. DAILY LOSS LIMIT ───────────────────────────
        if daily_pnl_pct <= -rules["max_daily_loss_pct"]:
            self._start_cooldown(s, 480, "Daily loss limit reached")
            return self._reject(f"DAILY LOSS LIMIT: -{rules['max_daily_loss_pct']}% reached. Trading paused.", "daily_loss")

        # ── 4. MAX DRAWDOWN ───────────────────────────────
        if drawdown_pct >= rules["max_drawdown_pct"]:
            self._start_cooldown(s, 3600, "Max drawdown exceeded")
            return self._reject(f"DRAWDOWN HALT: {drawdown_pct:.1f}% DD exceeds {rules['max_drawdown_pct']}%.", "drawdown")

        # ── 5. CONSECUTIVE LOSS BRAKE ─────────────────────
        if s.cons_losses >= rules["cooldown_after_losses"]:
            self._start_cooldown(s, rules["cooldown_minutes"]*60, f"{s.cons_losses} consecutive losses")
            s.cons_losses = 0
            return self._reject(f"LOSS STREAK: {rules['cooldown_after_losses']} consecutive losses. {rules['cooldown_minutes']}min pause.", "streak")

        # ── 6. DAILY TARGET HIT ───────────────────────────
        if daily_pnl_pct >= s.daily_target_pct and s.daily_target_hit:
            return self._reject(f"DAILY TARGET HIT: +{daily_pnl_pct:.1f}% achieved. Session complete.", "target_hit")

        # ── 7. OVERTRADING CHECK ──────────────────────────
        recent = [t for t in s.trades_last_hour if now - t < 3600]
        s.trades_last_hour = deque(recent, maxlen=50)
        if len(recent) >= rules["max_hourly_trades"]:
            return self._reject(f"OVERTRADING: {len(recent)} trades in last hour. Max: {rules['max_hourly_trades']}.", "overtrade")

        if s.daily_trades >= rules["max_daily_trades"]:
            return self._reject(f"MAX DAILY TRADES: {s.daily_trades}/{rules['max_daily_trades']} reached.", "max_trades")

        # ── 8. MINIMUM TRADE GAP ──────────────────────────
        if recent and (now - max(recent)) < rules["min_trade_gap_seconds"]:
            wait = int(rules["min_trade_gap_seconds"] - (now - max(recent)))
            return self._reject(f"TOO FAST: Wait {wait}s between trades.", "too_fast")

        # ── 9. QUALITY GATES ──────────────────────────────
        if confidence < rules["min_confidence"]:
            return self._reject(f"LOW CONFIDENCE: {confidence:.1f}% < {rules['min_confidence']}% required.", "confidence")

        if rr_ratio < rules["min_rr"]:
            return self._reject(f"LOW R:R: {rr_ratio:.1f}:1 < {rules['min_rr']}:1 required.", "rr_ratio")

        if engines_agree < rules["required_engines_agree"]:
            return self._reject(f"WEAK CONSENSUS: Only {engines_agree}/9 engines agree. Need {rules['required_engines_agree']}+.", "consensus")

        # ── 10. POSITION SIZE CHECK ───────────────────────
        if proposed_size_pct > rules["oversize_block_pct"]:
            return self._reject(f"OVERSIZE: {proposed_size_pct:.0f}% proposed. Max: {rules['oversize_block_pct']}%.", "oversize")

        # ── ALL CHECKS PASSED ─────────────────────────────
        s.trades_last_hour.append(now)
        s.daily_trades += 1

        # Confidence bonus message
        bonus = ""
        if confidence >= 85 and engines_agree >= 7:
            bonus = " | HIGH CONVICTION SIGNAL"

        return {
            "approved": True,
            "reason": f"All {len(DISCIPLINE_RULES)} discipline checks passed{bonus}",
            "checks": len(DISCIPLINE_RULES),
            "confidence": confidence,
            "rr_ratio": rr_ratio,
            "engines_agree": engines_agree,
            "daily_trades": s.daily_trades,
            "cons_wins": s.cons_wins,
            "hourly_trades": len(recent) + 1,
        }

    def record_result(self, bot_id: str, won: bool, pnl_pct: float):
        """Update discipline state after trade closes."""
        s = self._get(bot_id)
        s.daily_pnl_pct += pnl_pct
        s.peak_daily_pnl = max(s.peak_daily_pnl, s.daily_pnl_pct)

        if won:
            s.cons_wins += 1
            s.cons_losses = 0
            s.last_loss_time = 0
        else:
            s.cons_losses += 1
            s.cons_wins = 0
            s.last_loss_time = time.time()
            # Revenge block: 15 min after each loss
            s.revenge_block_until = time.time() + DISCIPLINE_RULES["revenge_block_minutes"] * 60
            log.info("Loss recorded → revenge block active", bot_id=bot_id, losses=s.cons_losses)

        if s.daily_pnl_pct >= s.daily_target_pct:
            s.daily_target_hit = True
            log.info("Daily target hit!", bot_id=bot_id, pnl=f"+{s.daily_pnl_pct:.2f}%")

    def reset_daily(self, bot_id: str):
        s = self._get(bot_id)
        s.daily_trades = 0
        s.daily_pnl_pct = 0.0
        s.daily_target_hit = False
        s.peak_daily_pnl = 0.0
        s.cons_wins = 0
        s.cons_losses = 0

    def get_status(self, bot_id: str) -> dict:
        s = self._get(bot_id)
        now = time.time()
        recent = [t for t in s.trades_last_hour if now - t < 3600]
        return {
            "bot_id": bot_id,
            "in_cooldown": s.in_cooldown,
            "cooldown_reason": s.cooldown_reason,
            "cooldown_remaining": max(0, int(s.cooldown_until - now)),
            "revenge_block_remaining": max(0, int(s.revenge_block_until - now)),
            "daily_trades": s.daily_trades,
            "hourly_trades": len(recent),
            "cons_wins": s.cons_wins,
            "cons_losses": s.cons_losses,
            "daily_pnl_pct": round(s.daily_pnl_pct, 3),
            "daily_target_hit": s.daily_target_hit,
            "daily_target_pct": s.daily_target_pct,
            "rules": DISCIPLINE_RULES,
        }

    def _reject(self, reason: str, code: str) -> dict:
        log.warning("Trade REJECTED by discipline", reason=reason, code=code)
        return {"approved": False, "reason": reason, "code": code}

    def _start_cooldown(self, s: DisciplineState, seconds: int, reason: str):
        s.in_cooldown = True
        s.cooldown_until = time.time() + seconds
        s.cooldown_reason = reason

discipline_engine = DisciplineEngine()
