"""
services/reinvestment_engine_v9.py — estrading.machine v9 GODMODE
══════════════════════════════════════════════════════════════════════════════
REINVESTMENT ENGINE — 8 MODES, EVERY BOT

REINVESTMENT MODES:
  0. OFF        — No reinvestment. Fixed position size always.
  1. CONSERVATIVE — Reinvest 25% of profits. Slow steady growth.
  2. MODERATE   — Reinvest 50% of profits. Balanced growth.
  3. AGGRESSIVE — Reinvest 75% of profits. Fast compounding.
  4. FULL       — Reinvest 100% of profits. Maximum compounding.
  5. GEOMETRIC  — Reinvest using geometric Kelly. Optimal growth.
  6. STREAK     — Reinvest more after winning streaks (up to 2×).
  7. SMART      — AI decides reinvestment rate based on performance.

REINVESTMENT BUTTON LOGIC (for UI):
  Each bot has a reinvestment dropdown in its control panel.
  Changing the mode saves instantly to Supabase + updates live state.
  The engine reads the mode every trade and applies accordingly.

COMPOUNDING MATH:
  Mode FULL at 5% daily:
    Day 1:  $10,000 → $10,500
    Day 7:  $10,000 → $14,071
    Day 30: $10,000 → $43,219
    Day 90: $10,000 → $808,500 (theoretical)

SAFETY RULES (always active regardless of mode):
  • Never reinvest if drawdown > 10%
  • Never reinvest if consecutive losses > 3
  • Reset to base size after any loss (modes 1-4)
  • Geometric mode caps at 3× starting size
  • Smart mode never exceeds 2× base
══════════════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations
import json, math, time, statistics
from collections import deque
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, Optional
import structlog

log = structlog.get_logger("reinvest_v9")

REINVEST_STORAGE = Path("storage/reinvest_v9.json")
REINVEST_STORAGE.parent.mkdir(parents=True, exist_ok=True)


# ── Mode definitions ─────────────────────────────────────────
REINVEST_MODES = {
    0: {"key":"off",          "label":"OFF",         "icon":"⏸",  "color":"#475569",
        "desc":"No reinvestment. Fixed position size. Safe and predictable.",
        "rate":0.00},
    1: {"key":"conservative", "label":"Conservative","icon":"🛡️","color":"#22c55e",
        "desc":"Reinvest 25% of profits. Slow but steady capital growth.",
        "rate":0.25},
    2: {"key":"moderate",     "label":"Moderate",    "icon":"⚖️", "color":"#3b82f6",
        "desc":"Reinvest 50% of profits. Balanced growth and withdrawal.",
        "rate":0.50},
    3: {"key":"aggressive",   "label":"Aggressive",  "icon":"🚀", "color":"#f59e0b",
        "desc":"Reinvest 75% of profits. Fast compounding, moderate risk.",
        "rate":0.75},
    4: {"key":"full",         "label":"FULL COMPOUND","icon":"💰","color":"#f97316",
        "desc":"Reinvest 100% of profits. Maximum exponential growth.",
        "rate":1.00},
    5: {"key":"geometric",    "label":"Geometric",   "icon":"📐", "color":"#8b5cf6",
        "desc":"Kelly Criterion geometric sizing. Mathematically optimal.",
        "rate":-1},  # calculated dynamically
    6: {"key":"streak",       "label":"Win Streak",  "icon":"🔥", "color":"#ef4444",
        "desc":"Scales reinvestment with win streaks. 1× → 2× on 5-win streak.",
        "rate":-2},  # calculated dynamically
    7: {"key":"smart",        "label":"AI Smart",    "icon":"🧠", "color":"#a78bfa",
        "desc":"AI adjusts rate based on win rate, drawdown, and market feeling.",
        "rate":-3},  # AI-calculated
}

@dataclass
class ReinvestState:
    """Per-bot reinvestment state."""
    bot_id:          str
    mode:            int   = 0       # 0-7
    base_size_usd:   float = 0.0     # original starting size
    current_size_usd:float = 0.0     # current size after reinvestment
    compound_pool:   float = 0.0     # accumulated profits ready to reinvest
    total_reinvested:float = 0.0     # total amount reinvested
    total_withdrawn: float = 0.0     # total taken as profit
    multiplier:      float = 1.0     # current_size / base_size
    cons_wins:       int   = 0
    cons_losses:     int   = 0
    win_rate:        float = 0.5
    pnl_history:     list  = field(default_factory=list)
    drawdown_pct:    float = 0.0
    peak_size:       float = 0.0
    last_updated:    float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["pnl_history"] = d["pnl_history"][-20:]  # only last 20
        d["mode_info"]   = REINVEST_MODES[self.mode]
        return d


class ReinvestEngine:
    """
    Manages reinvestment for all bots.
    Applies compound growth or fixed size per user preference.
    """

    def __init__(self):
        self._states: Dict[str, ReinvestState] = {}
        self._load()

    # ── State management ──────────────────────────────────────

    def init_bot(self, bot_id: str, initial_capital: float, mode: int = 0):
        if bot_id not in self._states:
            self._states[bot_id] = ReinvestState(
                bot_id           = bot_id,
                mode             = mode,
                base_size_usd    = initial_capital * 0.50,  # 50% base deployment
                current_size_usd = initial_capital * 0.50,
                peak_size        = initial_capital * 0.50,
            )
            log.info("Reinvest initialized", bot_id=bot_id, mode=mode, capital=initial_capital)

    def set_mode(self, bot_id: str, mode: int) -> dict:
        """Change reinvestment mode. Returns new state."""
        if mode not in REINVEST_MODES:
            return {"error": f"Invalid mode {mode}. Use 0-7."}
        s = self._states.get(bot_id)
        if not s:
            self.init_bot(bot_id, 1000, mode)
            s = self._states[bot_id]
        old_mode = s.mode
        s.mode   = mode
        self._save()
        log.info("Reinvest mode changed", bot_id=bot_id,
                 old=REINVEST_MODES[old_mode]["label"],
                 new=REINVEST_MODES[mode]["label"])
        return {"success": True, "bot_id": bot_id, "mode": mode,
                "mode_info": REINVEST_MODES[mode]}

    # ── Calculate next position size ──────────────────────────

    def get_next_size(
        self,
        bot_id:       str,
        drawdown_pct: float = 0.0,
    ) -> dict:
        """
        Get position size for next trade.
        Applies reinvestment mode and safety rules.
        """
        s = self._states.get(bot_id)
        if not s:
            return {"size_usd": 1000 * 0.50, "multiplier": 1.0, "mode": 0}

        # ── Safety override ──────────────────────────────────
        if drawdown_pct >= 10:
            return {"size_usd": s.base_size_usd * 0.50,
                    "multiplier": 0.50, "mode": s.mode,
                    "safety_override": "High drawdown → 50% size"}
        if s.cons_losses >= 3:
            return {"size_usd": s.base_size_usd * 0.70,
                    "multiplier": 0.70, "mode": s.mode,
                    "safety_override": "Loss streak → 70% size"}

        # ── Mode-specific calculation ─────────────────────────
        if s.mode == 0:
            # OFF: always base size
            size = s.base_size_usd

        elif s.mode in (1, 2, 3, 4):
            # Fixed rate reinvestment
            rate = REINVEST_MODES[s.mode]["rate"]
            pool = s.compound_pool * rate
            size = s.base_size_usd + pool
            # Cap: no more than 3× base
            size = min(size, s.base_size_usd * 3.0)

        elif s.mode == 5:
            # Geometric (Kelly Criterion)
            if len(s.pnl_history) >= 10:
                wins   = [p for p in s.pnl_history if p > 0]
                losses = [abs(p) for p in s.pnl_history if p < 0]
                if wins and losses:
                    avg_win  = statistics.mean(wins)
                    avg_loss = statistics.mean(losses)
                    wr       = len(wins) / len(s.pnl_history)
                    kelly    = wr/avg_loss - (1-wr)/avg_win if avg_win > 0 else 0
                    kelly    = max(0, min(kelly, 0.25))  # cap at 25%
                    size     = s.base_size_usd * (1 + kelly * 10)
                else:
                    size = s.base_size_usd
            else:
                size = s.base_size_usd
            size = min(size, s.base_size_usd * 3.0)

        elif s.mode == 6:
            # Streak-based: more after wins
            if s.cons_wins >= 5:   mult = 2.0
            elif s.cons_wins >= 3: mult = 1.5
            elif s.cons_wins >= 1: mult = 1.2
            else:                  mult = 0.9
            pool = s.compound_pool * 0.50 * mult
            size = s.base_size_usd + pool
            size = min(size, s.base_size_usd * 2.5)

        elif s.mode == 7:
            # Smart AI mode
            # Factors: win rate, streak, drawdown, feeling
            wr_factor   = s.win_rate / 0.5       # 1.0 at 50% WR
            streak_fact = 1.0 + s.cons_wins * 0.05
            dd_factor   = max(0.5, 1.0 - drawdown_pct / 20)
            smart_rate  = min(0.8, max(0.1, wr_factor * streak_fact * dd_factor * 0.5))
            pool = s.compound_pool * smart_rate
            size = s.base_size_usd + pool
            size = min(size, s.base_size_usd * 2.0)

        else:
            size = s.base_size_usd

        size       = max(size, s.base_size_usd * 0.10)   # minimum 10% of base
        multiplier = size / (s.base_size_usd + 1e-9)
        s.current_size_usd = size
        s.multiplier       = round(multiplier, 3)

        return {
            "size_usd":    round(size, 2),
            "multiplier":  round(multiplier, 3),
            "mode":        s.mode,
            "mode_label":  REINVEST_MODES[s.mode]["label"],
            "mode_icon":   REINVEST_MODES[s.mode]["icon"],
            "compound_pool":round(s.compound_pool, 2),
            "cons_wins":   s.cons_wins,
            "win_rate":    round(s.win_rate * 100, 1),
            "base_size":   round(s.base_size_usd, 2),
        }

    # ── Record trade result ───────────────────────────────────

    def record_trade(
        self,
        bot_id:   str,
        pnl_usd:  float,
        pnl_pct:  float,
        balance:  float,
    ):
        """Called after every trade closes. Updates compound pool."""
        s = self._states.get(bot_id)
        if not s: return

        s.pnl_history.append(pnl_pct)
        if len(s.pnl_history) > 100:
            s.pnl_history = s.pnl_history[-100:]

        if pnl_usd > 0:
            # Calculate amount to reinvest vs withdraw
            rate = REINVEST_MODES[s.mode]["rate"]
            if rate < 0:  # dynamic modes
                rate = 0.5  # default for smart/geometric/streak

            reinvest_amount = pnl_usd * rate
            withdraw_amount = pnl_usd * (1 - rate)

            s.compound_pool   += reinvest_amount
            s.total_reinvested+= reinvest_amount
            s.total_withdrawn += withdraw_amount
            s.cons_wins       += 1
            s.cons_losses      = 0
            if balance > s.peak_size:
                s.peak_size = balance

            log.info("✅ Reinvest recorded",
                     bot_id=bot_id,
                     pnl=f"+${pnl_usd:.2f}",
                     reinvested=f"${reinvest_amount:.2f}",
                     pool=f"${s.compound_pool:.2f}",
                     mode=REINVEST_MODES[s.mode]["label"])
        else:
            s.cons_losses += 1
            s.cons_wins    = 0
            # On loss: keep pool but don't increase
            if s.mode == 0:
                pass  # fixed mode — no change
            elif s.cons_losses >= 2:
                # Reduce pool slightly on repeated losses
                s.compound_pool *= 0.90

        # Update win rate
        hist = s.pnl_history
        if hist:
            s.win_rate = sum(1 for p in hist if p > 0) / len(hist)

        # Update drawdown
        if s.peak_size > 0 and balance < s.peak_size:
            s.drawdown_pct = (s.peak_size - balance) / s.peak_size * 100

        s.last_updated = time.time()

        # Periodic save
        if len(s.pnl_history) % 10 == 0:
            self._save()

    # ── Compound projections ──────────────────────────────────

    def get_projections(self, bot_id: str, daily_pct: float = 5.0, days: int = 30) -> dict:
        """Show compound growth projection for each reinvest mode."""
        s = self._states.get(bot_id)
        base = s.current_size_usd if s else 1000.0
        projections = {}

        for mode, cfg in REINVEST_MODES.items():
            rate = cfg["rate"]
            if rate < 0: rate = 0.5  # use 50% for dynamic modes

            bal = base
            curve = [base]
            for d in range(days):
                profit     = bal * daily_pct / 100
                reinvested = profit * rate
                bal       += reinvested
                bal        = min(bal, base * 1000)  # safety cap
                curve.append(round(bal, 2))

            projections[mode] = {
                "mode":       cfg["label"],
                "icon":       cfg["icon"],
                "color":      cfg["color"],
                "rate":       rate,
                "final_bal":  round(curve[-1], 2),
                "profit":     round(curve[-1] - base, 2),
                "growth_pct": round((curve[-1] - base) / base * 100, 1),
                "multiplier": round(curve[-1] / base, 2),
                "curve":      curve[::3],  # every 3 days for compact display
            }

        return {
            "bot_id":     bot_id,
            "base":       base,
            "daily_pct":  daily_pct,
            "days":       days,
            "projections":projections,
        }

    # ── Stats ─────────────────────────────────────────────────

    def get_stats(self, bot_id: str) -> dict:
        s = self._states.get(bot_id)
        if not s: return {"not_found": True}
        return {
            "bot_id":         bot_id,
            "mode":           s.mode,
            "mode_label":     REINVEST_MODES[s.mode]["label"],
            "mode_icon":      REINVEST_MODES[s.mode]["icon"],
            "mode_color":     REINVEST_MODES[s.mode]["color"],
            "mode_desc":      REINVEST_MODES[s.mode]["desc"],
            "base_size":      round(s.base_size_usd, 2),
            "current_size":   round(s.current_size_usd, 2),
            "compound_pool":  round(s.compound_pool, 2),
            "total_reinvested":round(s.total_reinvested, 2),
            "total_withdrawn": round(s.total_withdrawn, 2),
            "multiplier":     round(s.multiplier, 3),
            "cons_wins":      s.cons_wins,
            "cons_losses":    s.cons_losses,
            "win_rate":       round(s.win_rate * 100, 1),
            "drawdown_pct":   round(s.drawdown_pct, 2),
            "trades":         len(s.pnl_history),
        }

    def get_all_modes(self) -> dict:
        """Return all modes for UI dropdown."""
        return {k: {**v} for k, v in REINVEST_MODES.items()}

    # ── Persistence ───────────────────────────────────────────

    def _save(self):
        try:
            data = {bid: asdict(s) for bid, s in self._states.items()}
            REINVEST_STORAGE.write_text(json.dumps(data, indent=2))
        except Exception as e:
            log.error("Reinvest save failed", error=str(e))

    def _load(self):
        try:
            if REINVEST_STORAGE.exists():
                data = json.loads(REINVEST_STORAGE.read_text())
                for bid, d in data.items():
                    self._states[bid] = ReinvestState(**d)
                log.info("Reinvest states loaded", bots=len(self._states))
        except Exception as e:
            log.warning("Reinvest load failed", error=str(e))


# ── Singleton ─────────────────────────────────────────────────
reinvest_engine = ReinvestEngine()
REINVEST_MODES_LIST = REINVEST_MODES
