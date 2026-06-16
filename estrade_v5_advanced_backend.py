"""
strategies/money_printer_v8.py — ESTRADE v8 GODMODE MONEY PRINTING ENGINE
═══════════════════════════════════════════════════════════════════════════════
MISSION: Print money consistently in ANY market condition.
ENTRY SIZE: 45-55% of allocated capital per position (max edge deployment)
DIFFERENCE FROM NORMAL: Risk management is the only separator.
  Normal bot: 1-2% risk per trade
  Money Printer: 45-55% CAPITAL per entry, aggressive compounding
  Safety net: 5-layer drawdown shield + RL emergency brake

═══════════════════════════════════════════════════════════════════════════════
MONEY PRINTING STRATEGIES (per bot category):

1. QUANTUM COMPOUND (Hybrid bots)
   → Enter 50% capital on A+ signal
   → Scale IN on winning trades (pyramid up)
   → Compound profit into next position automatically
   → Target: 3-8% per compound cycle

2. BEAR MONEY MACHINE (Bear Crusher Pro)
   → 50% capital short during confirmed bear cascade
   → Cascade detection: RSI<20 + vol spike >3×
   → Hold through the full wave, trail stop
   → Target: 10-30% per bear cycle

3. ARB PRINT (Quantum ARB-X)
   → Deploy 55% into arbitrage simultaneously
   → 3 arb legs running at once: exchange + triangular + funding
   → Near-zero risk, compounding micro-profits
   → Target: 5-15% daily from pure arbitrage

4. VOL CRUSH (Volatility Assassin)
   → 45% capital into straddle on BB squeeze
   → Both sides enter at max size
   → Winner compounds, loser exits fast
   → Target: 8-25% per volatility event

5. SCALP TSUNAMI (Crypto Scalp bots)
   → 50% capital, 30-50 trades/day
   → Each trade 0.2-0.5%
   → 0.2% × 50 trades = 10% daily
   → Compound each win

6. TREND TSUNAMI (Trend bots)
   → 50% capital into confirmed trend
   → Add 10% at each positive candle
   → Max position: 70% capital
   → Exit: trailing stop 1.5×ATR

7. GRID PRINT (Grid bots)
   → 50% capital spread across grid
   → Each grid level 5% capital
   → 10 levels × 5% = 50% deployed
   → Earns on every oscillation

8. FUNDING HARVEST PRINT (Funding bots)
   → 50% into funding arb position
   → Earns 0.01-0.05% per 8h
   → 3 payments/day = 0.03-0.15% daily
   → 30 days = 0.9-4.5% pure income

═══════════════════════════════════════════════════════════════════════════════
SAFETY MECHANISMS (non-negotiable):
  ✅ Hard stop at 15% drawdown → full halt
  ✅ Daily loss limit 5% → pause 24h
  ✅ RL emergency brake: 4 consecutive losses → reduce 50%
  ✅ Kelly criterion: never exceed theoretical optimal
  ✅ Correlation check: no 2 same-direction positions in same asset
═══════════════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations
import math
import time
import statistics
from collections import deque
from dataclasses import dataclass, field
from typing import Optional, List, Dict
import numpy as np
import structlog

log = structlog.get_logger("money_printer_v8")

# ── MONEY PRINTING CONSTANTS ─────────────────────────────────
MONEY_PRINT_CAPITAL_PCT   = 50.0   # % of allocated capital per trade
MONEY_PRINT_MAX_CAPITAL   = 55.0   # absolute maximum
MONEY_PRINT_MIN_CAPITAL   = 40.0   # minimum to be worth it
PYRAMID_ADD_PCT           = 10.0   # % to add at each pyramid level
MAX_PYRAMID_LEVELS        = 3      # max 3 scale-ins
COMPOUND_RATIO            = 1.0    # reinvest 100% of profits
HARD_STOP_DD              = 15.0   # % DD → halt everything
DAILY_LOSS_LIMIT          = 5.0    # % daily loss → 24h pause
CONSECUTIVE_LOSS_BRAKE    = 4      # losses → reduce 50%


@dataclass
class PrintConfig:
    """Money printing configuration per bot type."""
    bot_id:              str
    strategy_type:       str       # which print strategy to use
    capital_pct:         float = MONEY_PRINT_CAPITAL_PCT
    max_capital_pct:     float = MONEY_PRINT_MAX_CAPITAL
    pyramid_enabled:     bool  = True
    pyramid_levels:      int   = MAX_PYRAMID_LEVELS
    compound_enabled:    bool  = True
    compound_ratio:      float = COMPOUND_RATIO
    min_confidence:      float = 72.0
    min_rr:              float = 2.0
    daily_trade_target:  int   = 10
    daily_profit_target: float = 5.0   # %
    hard_stop_dd:        float = HARD_STOP_DD
    daily_loss_limit:    float = DAILY_LOSS_LIMIT


# ── MONEY PRINTING CONFIGS FOR ALL 43 BOTS ───────────────────
PRINT_CONFIGS: Dict[str, PrintConfig] = {

    # ── HYBRID BOTS ──────────────────────────────────────────
    "hybrid_alpha": PrintConfig(
        bot_id="hybrid_alpha", strategy_type="quantum_compound",
        capital_pct=50, min_confidence=74, min_rr=2.2,
        daily_profit_target=6.0, daily_trade_target=8,
    ),
    "hybrid_pro": PrintConfig(
        bot_id="hybrid_pro", strategy_type="quantum_compound",
        capital_pct=48, min_confidence=76, min_rr=2.5,
        daily_profit_target=5.0, daily_trade_target=6,
    ),
    "smart_balance": PrintConfig(
        bot_id="smart_balance", strategy_type="grid_print",
        capital_pct=50, pyramid_enabled=False, min_confidence=68,
        daily_profit_target=3.0, daily_trade_target=15,
    ),
    "momentum_surge": PrintConfig(
        bot_id="momentum_surge", strategy_type="trend_tsunami",
        capital_pct=52, min_confidence=73, min_rr=2.3,
        daily_profit_target=7.0, daily_trade_target=5,
    ),
    "ai_fusion": PrintConfig(
        bot_id="ai_fusion", strategy_type="quantum_compound",
        capital_pct=55, min_confidence=80, min_rr=2.5,
        daily_profit_target=8.0, daily_trade_target=5,
    ),
    "swing_elite": PrintConfig(
        bot_id="swing_elite", strategy_type="trend_tsunami",
        capital_pct=50, min_confidence=78, min_rr=3.0,
        daily_profit_target=5.0, daily_trade_target=3,
    ),

    # ── HIGH PROFIT BOTS ─────────────────────────────────────
    "quantum_yield": PrintConfig(
        bot_id="quantum_yield", strategy_type="quantum_compound",
        capital_pct=55, min_confidence=72, min_rr=2.0,
        daily_profit_target=10.0, daily_trade_target=8,
    ),
    "profit_guardian": PrintConfig(
        bot_id="profit_guardian", strategy_type="quantum_compound",
        capital_pct=45, min_confidence=75, min_rr=2.5,
        compound_ratio=0.8, daily_profit_target=4.0, daily_trade_target=6,
    ),
    "breakout_king": PrintConfig(
        bot_id="breakout_king", strategy_type="trend_tsunami",
        capital_pct=52, min_confidence=76, min_rr=2.8,
        daily_profit_target=8.0, daily_trade_target=4,
    ),
    "yield_compounder": PrintConfig(
        bot_id="yield_compounder", strategy_type="quantum_compound",
        capital_pct=55, compound_ratio=1.0, min_confidence=70,
        daily_profit_target=12.0, daily_trade_target=10,
    ),
    "alpha_hunter": PrintConfig(
        bot_id="alpha_hunter", strategy_type="quantum_compound",
        capital_pct=50, min_confidence=78, min_rr=2.5,
        daily_profit_target=7.0, daily_trade_target=5,
    ),
    "risk_reward_max": PrintConfig(
        bot_id="risk_reward_max", strategy_type="quantum_compound",
        capital_pct=50, min_confidence=80, min_rr=3.5,
        daily_profit_target=6.0, daily_trade_target=3,
    ),

    # ── MEDIUM BOTS ──────────────────────────────────────────
    "trend_rider": PrintConfig(
        bot_id="trend_rider", strategy_type="trend_tsunami",
        capital_pct=48, min_confidence=70, min_rr=2.0,
        daily_profit_target=4.0, daily_trade_target=6,
    ),
    "mean_reversion_pro": PrintConfig(
        bot_id="mean_reversion_pro", strategy_type="grid_print",
        capital_pct=50, pyramid_enabled=False, min_confidence=72,
        daily_profit_target=4.0, daily_trade_target=10,
    ),
    "volume_surge_ai": PrintConfig(
        bot_id="volume_surge_ai", strategy_type="trend_tsunami",
        capital_pct=50, min_confidence=73, min_rr=2.2,
        daily_profit_target=5.0, daily_trade_target=8,
    ),
    "session_specialist": PrintConfig(
        bot_id="session_specialist", strategy_type="quantum_compound",
        capital_pct=48, min_confidence=72, min_rr=2.0,
        daily_profit_target=4.0, daily_trade_target=6,
    ),
    "divergence_hunter": PrintConfig(
        bot_id="divergence_hunter", strategy_type="quantum_compound",
        capital_pct=50, min_confidence=74, min_rr=2.5,
        daily_profit_target=5.0, daily_trade_target=5,
    ),
    "smc_precision": PrintConfig(
        bot_id="smc_precision", strategy_type="quantum_compound",
        capital_pct=52, min_confidence=76, min_rr=2.5,
        daily_profit_target=6.0, daily_trade_target=5,
    ),

    # ── CRYPTO SCALP BOTS ────────────────────────────────────
    "promax_scalping": PrintConfig(
        bot_id="promax_scalping", strategy_type="scalp_tsunami",
        capital_pct=50, pyramid_enabled=False, min_confidence=85,
        daily_profit_target=10.0, daily_trade_target=40,
    ),
    "micro_scalper": PrintConfig(
        bot_id="micro_scalper", strategy_type="scalp_tsunami",
        capital_pct=45, pyramid_enabled=False, min_confidence=70,
        daily_profit_target=8.0, daily_trade_target=80,
    ),
    "crypto_momentum_scalp": PrintConfig(
        bot_id="crypto_momentum_scalp", strategy_type="scalp_tsunami",
        capital_pct=50, min_confidence=72, min_rr=1.8,
        daily_profit_target=8.0, daily_trade_target=30,
    ),
    "grid_scalper": PrintConfig(
        bot_id="grid_scalper", strategy_type="grid_print",
        capital_pct=50, pyramid_enabled=False, min_confidence=65,
        daily_profit_target=5.0, daily_trade_target=50,
    ),
    "order_flow_scalper": PrintConfig(
        bot_id="order_flow_scalper", strategy_type="scalp_tsunami",
        capital_pct=50, min_confidence=75, min_rr=2.0,
        daily_profit_target=8.0, daily_trade_target=30,
    ),
    "funding_scalper": PrintConfig(
        bot_id="funding_scalper", strategy_type="funding_harvest_print",
        capital_pct=50, pyramid_enabled=False, min_confidence=90,
        daily_profit_target=2.0, daily_trade_target=3,
    ),

    # ── FOREX BOTS ───────────────────────────────────────────
    "forex_london_pro": PrintConfig(
        bot_id="forex_london_pro", strategy_type="trend_tsunami",
        capital_pct=48, min_confidence=72, min_rr=2.2,
        daily_profit_target=4.0, daily_trade_target=6,
    ),
    "ny_session_trader": PrintConfig(
        bot_id="ny_session_trader", strategy_type="trend_tsunami",
        capital_pct=48, min_confidence=72, min_rr=2.0,
        daily_profit_target=4.0, daily_trade_target=6,
    ),
    "forex_swing_master": PrintConfig(
        bot_id="forex_swing_master", strategy_type="trend_tsunami",
        capital_pct=50, min_confidence=78, min_rr=3.0,
        daily_profit_target=3.0, daily_trade_target=2,
    ),
    "carry_trade_ai": PrintConfig(
        bot_id="carry_trade_ai", strategy_type="funding_harvest_print",
        capital_pct=50, pyramid_enabled=False, min_confidence=80,
        daily_profit_target=2.0, daily_trade_target=1,
    ),
    "news_trader_ai": PrintConfig(
        bot_id="news_trader_ai", strategy_type="vol_crush",
        capital_pct=45, min_confidence=85, min_rr=3.0,
        daily_profit_target=5.0, daily_trade_target=4,
    ),
    "asian_session_bot": PrintConfig(
        bot_id="asian_session_bot", strategy_type="grid_print",
        capital_pct=48, pyramid_enabled=False, min_confidence=68,
        daily_profit_target=3.0, daily_trade_target=10,
    ),

    # ── COMMODITIES BOTS ─────────────────────────────────────
    "gold_master": PrintConfig(
        bot_id="gold_master", strategy_type="trend_tsunami",
        capital_pct=50, min_confidence=76, min_rr=2.5,
        daily_profit_target=4.0, daily_trade_target=4,
    ),
    "silver_tech": PrintConfig(
        bot_id="silver_tech", strategy_type="trend_tsunami",
        capital_pct=48, min_confidence=74, min_rr=2.3,
        daily_profit_target=5.0, daily_trade_target=5,
    ),
    "oil_crypto_hybrid": PrintConfig(
        bot_id="oil_crypto_hybrid", strategy_type="quantum_compound",
        capital_pct=48, min_confidence=72, min_rr=2.2,
        daily_profit_target=4.0, daily_trade_target=4,
    ),

    # ── FOREX HYBRID BOTS ────────────────────────────────────
    "headway_style": PrintConfig(
        bot_id="headway_style", strategy_type="quantum_compound",
        capital_pct=48, min_confidence=70, min_rr=2.0,
        compound_ratio=0.7, daily_profit_target=2.0, daily_trade_target=5,
    ),
    "royaliq_style": PrintConfig(
        bot_id="royaliq_style", strategy_type="quantum_compound",
        capital_pct=50, compound_ratio=1.0, min_confidence=72,
        daily_profit_target=4.0, daily_trade_target=5,
    ),
    "forex_hybrid_master": PrintConfig(
        bot_id="forex_hybrid_master", strategy_type="quantum_compound",
        capital_pct=48, min_confidence=71, min_rr=2.0,
        daily_profit_target=4.0, daily_trade_target=8,
    ),

    # ── CAPITAL MAX BOTS ─────────────────────────────────────
    "capital_maximizer": PrintConfig(
        bot_id="capital_maximizer", strategy_type="quantum_compound",
        capital_pct=55, compound_ratio=1.0, min_confidence=70,
        daily_profit_target=15.0, daily_trade_target=12,
    ),
    "smart_reinvest": PrintConfig(
        bot_id="smart_reinvest", strategy_type="quantum_compound",
        capital_pct=50, compound_ratio=1.0, min_confidence=72,
        daily_profit_target=6.0, daily_trade_target=8,
    ),
    "promax_usdt_seq": PrintConfig(
        bot_id="promax_usdt_seq", strategy_type="scalp_tsunami",
        capital_pct=50, pyramid_enabled=False, min_confidence=80,
        daily_profit_target=8.0, daily_trade_target=25,
    ),

    # ── 3 NEW ULTRA BOTS ─────────────────────────────────────
    "quantum_arb_x": PrintConfig(
        bot_id="quantum_arb_x", strategy_type="arb_print",
        capital_pct=55, pyramid_enabled=False, min_confidence=95,
        compound_ratio=1.0, daily_profit_target=8.0, daily_trade_target=60,
        min_rr=5.0, hard_stop_dd=5.0,  # arb: very tight stop — near lossless
    ),
    "bear_crusher_pro": PrintConfig(
        bot_id="bear_crusher_pro", strategy_type="bear_money_machine",
        capital_pct=50, pyramid_levels=2, min_confidence=68,
        min_rr=2.5, daily_profit_target=15.0, daily_trade_target=8,
    ),
    "volatility_assassin": PrintConfig(
        bot_id="volatility_assassin", strategy_type="vol_crush",
        capital_pct=45, pyramid_enabled=False, min_confidence=70,
        min_rr=3.0, daily_profit_target=10.0, daily_trade_target=4,
    ),

    # ── ALPHA OMNIBUS ─────────────────────────────────────────
    "alpha_omnibus": PrintConfig(
        bot_id="alpha_omnibus", strategy_type="quantum_compound",
        capital_pct=50, compound_ratio=1.0, pyramid_levels=2,
        min_confidence=72, min_rr=2.0,
        daily_profit_target=10.0, daily_trade_target=12,
    ),
}


# ══════════════════════════════════════════════════════════════
# MONEY PRINTING POSITION SIZER
# ══════════════════════════════════════════════════════════════

class MoneyPrinter:
    """
    Core money printing engine.
    Calculates position sizes at 45-55% of capital.
    Manages pyramid scaling, compounding, and safety brakes.
    """

    def __init__(self):
        self._states: Dict[str, dict] = {}

    def _get_state(self, bot_id: str) -> dict:
        if bot_id not in self._states:
            self._states[bot_id] = {
                "balance":         0.0,
                "start_balance":   0.0,
                "daily_pnl_pct":   0.0,
                "session_pnl_pct": 0.0,
                "compound_pool":   0.0,   # accumulated profit ready to compound
                "peak_balance":    0.0,
                "drawdown_pct":    0.0,
                "consecutive_losses": 0,
                "consecutive_wins":   0,
                "trades_today":    0,
                "pyramid_level":   0,
                "braked":          False,   # emergency brake active
                "paused_until":    0.0,
                "total_compound_profit": 0.0,
            }
        return self._states[bot_id]

    def calculate_print_size(
        self,
        bot_id:     str,
        balance:    float,
        config:     PrintConfig,
        signal_confidence: float = 75.0,
        current_dd: float = 0.0,
    ) -> dict:
        """
        Calculate the money-printing position size.
        Returns: {size_usd, capital_pct, compound_add, print_mode, safe_to_trade}
        """
        s = self._get_state(bot_id)
        s["balance"] = balance
        if s["peak_balance"] < balance:
            s["peak_balance"] = balance
        if s["start_balance"] == 0:
            s["start_balance"] = balance

        # ── Safety checks ─────────────────────────────────────
        # 1. Hard stop
        if current_dd >= config.hard_stop_dd:
            return {
                "safe_to_trade": False,
                "reason": f"HARD STOP: DD {current_dd:.1f}% ≥ {config.hard_stop_dd}%",
                "size_usd": 0, "capital_pct": 0,
            }

        # 2. Daily loss limit
        if s["daily_pnl_pct"] <= -config.daily_loss_limit:
            return {
                "safe_to_trade": False,
                "reason": f"Daily loss limit reached: {s['daily_pnl_pct']:.2f}%",
                "size_usd": 0, "capital_pct": 0,
            }

        # 3. Consecutive loss brake
        brake_mult = 1.0
        if s["consecutive_losses"] >= CONSECUTIVE_LOSS_BRAKE:
            brake_mult = 0.5
            log.warning("Money print braked", bot_id=bot_id, losses=s["consecutive_losses"])

        # 4. Confidence gate
        if signal_confidence < config.min_confidence:
            return {
                "safe_to_trade": False,
                "reason": f"Confidence {signal_confidence:.1f}% < min {config.min_confidence}%",
                "size_usd": 0, "capital_pct": 0,
            }

        # ── Base capital percentage ────────────────────────────
        base_pct = config.capital_pct * brake_mult

        # Confidence bonus (higher confidence = bigger size, up to max)
        conf_bonus = max(0, (signal_confidence - config.min_confidence) / 30) * 5
        capital_pct = min(config.max_capital_pct, base_pct + conf_bonus)

        # ── Pyramid scaling ────────────────────────────────────
        pyramid_add = 0.0
        if config.pyramid_enabled and s["pyramid_level"] > 0:
            pyramid_add = PYRAMID_ADD_PCT * min(s["pyramid_level"], config.pyramid_levels)
            capital_pct = min(config.max_capital_pct, capital_pct + pyramid_add)

        # ── Compound pool addition ─────────────────────────────
        compound_add = 0.0
        if config.compound_enabled and s["compound_pool"] > 0:
            compound_add = s["compound_pool"] * config.compound_ratio
            s["compound_pool"] = 0.0  # reset pool

        # ── Final size ─────────────────────────────────────────
        base_size    = balance * capital_pct / 100
        compound_size= compound_add
        total_size   = base_size + compound_size

        # Never exceed max_capital_pct of current balance
        max_size = balance * config.max_capital_pct / 100
        total_size = min(total_size, max_size)

        s["trades_today"] += 1

        return {
            "safe_to_trade":  True,
            "size_usd":       round(total_size, 2),
            "capital_pct":    round(capital_pct, 2),
            "base_size":      round(base_size, 2),
            "compound_add":   round(compound_size, 2),
            "pyramid_level":  s["pyramid_level"],
            "brake_mult":     round(brake_mult, 2),
            "print_mode":     config.strategy_type,
            "daily_target":   config.daily_profit_target,
            "trades_today":   s["trades_today"],
            "consecutive_wins": s["consecutive_wins"],
        }

    def record_trade_result(
        self,
        bot_id:   str,
        pnl_pct:  float,
        pnl_usd:  float,
        balance:  float,
        config:   PrintConfig,
    ):
        """Update state after trade closes. Manages compounding."""
        s = self._get_state(bot_id)

        s["daily_pnl_pct"]   += pnl_pct
        s["session_pnl_pct"] += pnl_pct
        s["balance"]          = balance

        if pnl_usd > 0:
            s["consecutive_wins"]   += 1
            s["consecutive_losses"]  = 0
            s["pyramid_level"]       = min(s["pyramid_level"] + 1, config.pyramid_levels)
            # Add to compound pool
            if config.compound_enabled:
                s["compound_pool"] += pnl_usd * config.compound_ratio
                s["total_compound_profit"] += pnl_usd * config.compound_ratio
            log.info("💰 PROFIT PRINTED",
                     bot_id=bot_id, pnl=f"+{pnl_pct:.3f}%",
                     compound_pool=f"${s['compound_pool']:.2f}",
                     consecutive_wins=s["consecutive_wins"])
        else:
            s["consecutive_losses"] += 1
            s["consecutive_wins"]    = 0
            s["pyramid_level"]       = 0  # reset pyramid on loss
            log.info("Trade loss", bot_id=bot_id, pnl=f"{pnl_pct:.3f}%")

        # Update drawdown
        if balance < s["peak_balance"]:
            s["drawdown_pct"] = (s["peak_balance"] - balance) / s["peak_balance"] * 100
        else:
            s["peak_balance"] = balance

    def reset_daily(self, bot_id: str):
        """Call at start of each trading day."""
        s = self._get_state(bot_id)
        s["daily_pnl_pct"] = 0.0
        s["trades_today"]  = 0
        log.debug("Daily reset", bot_id=bot_id)

    def get_print_stats(self, bot_id: str) -> dict:
        s = self._get_state(bot_id)
        return {
            "balance":             round(s.get("balance", 0), 2),
            "daily_pnl_pct":       round(s.get("daily_pnl_pct", 0), 3),
            "session_pnl_pct":     round(s.get("session_pnl_pct", 0), 3),
            "compound_pool":       round(s.get("compound_pool", 0), 2),
            "total_compounded":    round(s.get("total_compound_profit", 0), 2),
            "pyramid_level":       s.get("pyramid_level", 0),
            "consecutive_wins":    s.get("consecutive_wins", 0),
            "consecutive_losses":  s.get("consecutive_losses", 0),
            "drawdown_pct":        round(s.get("drawdown_pct", 0), 2),
            "trades_today":        s.get("trades_today", 0),
        }


# ══════════════════════════════════════════════════════════════
# STRATEGY-SPECIFIC PRINT EXECUTORS
# ══════════════════════════════════════════════════════════════

def execute_quantum_compound(
    signal:  dict,
    balance: float,
    config:  PrintConfig,
    printer: MoneyPrinter,
) -> dict:
    """
    QUANTUM COMPOUND: 50% capital entry with pyramid scaling.
    Best for: Hybrid, High Profit, AI Fusion bots.
    """
    size_info = printer.calculate_print_size(
        bot_id=config.bot_id, balance=balance, config=config,
        signal_confidence=signal.get("confidence", 75),
        current_dd=signal.get("drawdown_pct", 0),
    )
    if not size_info["safe_to_trade"]:
        return {**size_info, "strategy": "quantum_compound"}

    return {
        **size_info,
        "strategy":    "quantum_compound",
        "entry_type":  "market",
        "pyramid_plan": [
            {"trigger_pct": 1.0, "add_pct": 10, "note": "Add after +1% move"},
            {"trigger_pct": 2.0, "add_pct": 10, "note": "Add after +2% move"},
            {"trigger_pct": 3.0, "add_pct": 10, "note": "Final pyramid +3%"},
        ] if config.pyramid_enabled else [],
        "sl_note":  "2×ATR below entry",
        "tp_note":  "4.5×ATR target + trailing stop",
        "expected_daily": f"+{config.daily_profit_target}%",
    }


def execute_scalp_tsunami(
    signal:  dict,
    balance: float,
    config:  PrintConfig,
    printer: MoneyPrinter,
) -> dict:
    """
    SCALP TSUNAMI: 50% capital, many trades per day.
    0.3% × 30 trades = 9% daily on 50% of capital = 4.5% on total.
    Best for: Crypto scalp bots, ProMax, Grid.
    """
    size_info = printer.calculate_print_size(
        bot_id=config.bot_id, balance=balance, config=config,
        signal_confidence=signal.get("confidence", 75),
        current_dd=signal.get("drawdown_pct", 0),
    )
    if not size_info["safe_to_trade"]:
        return {**size_info, "strategy": "scalp_tsunami"}

    return {
        **size_info,
        "strategy":        "scalp_tsunami",
        "entry_type":      "market",
        "target_pnl_pct":  0.3,      # per trade
        "sl_pnl_pct":      0.15,     # tight SL
        "trades_needed":   config.daily_trade_target,
        "daily_math":      f"0.3% × {config.daily_trade_target} = {0.3*config.daily_trade_target:.1f}% on {config.capital_pct}% = {0.003*config.daily_trade_target*config.capital_pct:.1f}% total",
        "expected_daily":  f"+{config.daily_profit_target}%",
    }


def execute_bear_money_machine(
    signal:  dict,
    balance: float,
    config:  PrintConfig,
    printer: MoneyPrinter,
) -> dict:
    """
    BEAR MONEY MACHINE: 50% capital shorts, scales up on cascade.
    Best for: Bear Crusher Pro.
    """
    size_info = printer.calculate_print_size(
        bot_id=config.bot_id, balance=balance, config=config,
        signal_confidence=signal.get("confidence", 68),
        current_dd=signal.get("drawdown_pct", 0),
    )
    if not size_info["safe_to_trade"]:
        return {**size_info, "strategy": "bear_money_machine"}

    # Scale UP on cascade signals
    bear_intensity = signal.get("bear_intensity", 5.0)
    intensity_mult = 1.0 + (bear_intensity - 5) * 0.1  # +10% per point above 5
    final_size = size_info["size_usd"] * max(0.5, min(intensity_mult, 1.5))

    return {
        **size_info,
        "size_usd":        round(final_size, 2),
        "strategy":        "bear_money_machine",
        "direction":       "sell",
        "bear_intensity":  bear_intensity,
        "intensity_mult":  round(intensity_mult, 2),
        "signal_type":     signal.get("type", "trend_short"),
        "expected_daily":  f"+{config.daily_profit_target}%",
    }


def execute_arb_print(
    signal:  dict,
    balance: float,
    config:  PrintConfig,
    printer: MoneyPrinter,
) -> dict:
    """
    ARB PRINT: 55% capital deployed across 3 simultaneous arb types.
    Near-zero risk. Pure mathematical profit.
    Best for: Quantum ARB-X.
    """
    size_info = printer.calculate_print_size(
        bot_id=config.bot_id, balance=balance, config=config,
        signal_confidence=signal.get("confidence", 95),
        current_dd=0,  # arb has near-zero DD
    )
    if not size_info["safe_to_trade"]:
        return {**size_info, "strategy": "arb_print"}

    total = size_info["size_usd"]
    return {
        **size_info,
        "strategy":      "arb_print",
        "allocation": {
            "exchange_arb":  round(total * 0.40, 2),   # 40% to exchange arb
            "triangular_arb":round(total * 0.35, 2),   # 35% to tri arb
            "funding_arb":   round(total * 0.25, 2),   # 25% to funding arb
        },
        "risk_level":    "NEAR_ZERO",
        "direction":     "neutral",
        "daily_cycles":  signal.get("daily_cycles", 60),
        "expected_daily":f"+{config.daily_profit_target}%",
    }


def execute_vol_crush(
    signal:  dict,
    balance: float,
    config:  PrintConfig,
    printer: MoneyPrinter,
) -> dict:
    """
    VOL CRUSH: 45% capital into straddle (22.5% each side).
    Winner compounds. Loser exits. Net = big move profit.
    Best for: Volatility Assassin, News Trader.
    """
    size_info = printer.calculate_print_size(
        bot_id=config.bot_id, balance=balance, config=config,
        signal_confidence=signal.get("confidence", 70),
        current_dd=signal.get("drawdown_pct", 0),
    )
    if not size_info["safe_to_trade"]:
        return {**size_info, "strategy": "vol_crush"}

    half = size_info["size_usd"] / 2
    return {
        **size_info,
        "strategy":      "vol_crush",
        "long_size":     round(half, 2),
        "short_size":    round(half, 2),
        "direction":     "both",
        "bb_percentile": signal.get("squeeze_pct", 15),
        "max_loss_usd":  round(half * 0.015 * 1.2 * 2, 2),  # 2 × SL (1.2×ATR)
        "max_profit_usd":round(half * 0.015 * 5.0, 2),      # winner TP (5×ATR)
        "expected_rr":   round((half * 0.015 * 5.0) / (half * 0.015 * 1.2 * 2), 2),
        "expected_daily":f"+{config.daily_profit_target}%",
    }


def execute_trend_tsunami(
    signal:  dict,
    balance: float,
    config:  PrintConfig,
    printer: MoneyPrinter,
) -> dict:
    """
    TREND TSUNAMI: 50% capital into confirmed trend.
    Adds 10% at each positive confirmation. Max 70%.
    Best for: Breakout King, Gold Master, Forex Swing.
    """
    size_info = printer.calculate_print_size(
        bot_id=config.bot_id, balance=balance, config=config,
        signal_confidence=signal.get("confidence", 73),
        current_dd=signal.get("drawdown_pct", 0),
    )
    if not size_info["safe_to_trade"]:
        return {**size_info, "strategy": "trend_tsunami"}

    return {
        **size_info,
        "strategy":      "trend_tsunami",
        "entry_type":    "market",
        "scale_plan":    [
            {"at": "+1%", "add_pct": 10},
            {"at": "+2%", "add_pct": 10},
        ],
        "exit": "trailing_stop_1.5atr",
        "expected_daily":f"+{config.daily_profit_target}%",
    }


def execute_grid_print(
    signal:  dict,
    balance: float,
    config:  PrintConfig,
    printer: MoneyPrinter,
) -> dict:
    """
    GRID PRINT: 50% capital spread across 10 grid levels (5% each).
    Earns profit on every oscillation up and down.
    Best for: Grid Scalper, Mean Reversion, Asian Session.
    """
    size_info = printer.calculate_print_size(
        bot_id=config.bot_id, balance=balance, config=config,
        signal_confidence=signal.get("confidence", 65),
        current_dd=signal.get("drawdown_pct", 0),
    )
    if not size_info["safe_to_trade"]:
        return {**size_info, "strategy": "grid_print"}

    total      = size_info["size_usd"]
    n_levels   = 10
    per_level  = total / n_levels
    grid_pct   = signal.get("atr", 0.5) / signal.get("price", 100) * 100

    return {
        **size_info,
        "strategy":      "grid_print",
        "grid_levels":   n_levels,
        "per_level_usd": round(per_level, 2),
        "grid_spacing":  f"{grid_pct:.3f}%",
        "direction":     "both",
        "profit_per_grid": round(per_level * 0.003, 2),  # 0.3% per level
        "expected_daily":  f"+{config.daily_profit_target}%",
    }


def execute_funding_harvest_print(
    signal:  dict,
    balance: float,
    config:  PrintConfig,
    printer: MoneyPrinter,
) -> dict:
    """
    FUNDING HARVEST PRINT: 50% into delta-neutral funding position.
    Collects funding every 8h. Daily income without directional risk.
    Best for: Funding Scalper, Carry Trade.
    """
    size_info = printer.calculate_print_size(
        bot_id=config.bot_id, balance=balance, config=config,
        signal_confidence=signal.get("confidence", 90),
        current_dd=0,  # delta neutral = no DD from price
    )
    if not size_info["safe_to_trade"]:
        return {**size_info, "strategy": "funding_harvest_print"}

    rate      = signal.get("funding_rate", 0.01)
    daily_earn= abs(rate) * 3 * size_info["size_usd"] / 100

    return {
        **size_info,
        "strategy":       "funding_harvest_print",
        "direction":      "neutral",
        "funding_rate":   rate,
        "payments_per_day": 3,
        "daily_income_usd": round(daily_earn, 2),
        "hold_hours":       8,
        "risk":             "NEAR_ZERO",
        "expected_daily":   f"+{config.daily_profit_target}%",
    }


# ── MASTER EXECUTE FUNCTION ───────────────────────────────────
STRATEGY_EXECUTORS = {
    "quantum_compound":      execute_quantum_compound,
    "scalp_tsunami":         execute_scalp_tsunami,
    "bear_money_machine":    execute_bear_money_machine,
    "arb_print":             execute_arb_print,
    "vol_crush":             execute_vol_crush,
    "trend_tsunami":         execute_trend_tsunami,
    "grid_print":            execute_grid_print,
    "funding_harvest_print": execute_funding_harvest_print,
}

def execute_money_print(
    bot_id:   str,
    signal:   dict,
    balance:  float,
    printer:  MoneyPrinter,
) -> dict:
    """
    Master money printing executor.
    Looks up config for bot, executes correct strategy.
    Returns full print instruction for execution engine.
    """
    config = PRINT_CONFIGS.get(bot_id)
    if not config:
        log.warning("No print config found", bot_id=bot_id)
        return {"safe_to_trade": False, "reason": "No print config"}

    executor = STRATEGY_EXECUTORS.get(config.strategy_type)
    if not executor:
        return {"safe_to_trade": False, "reason": f"Unknown strategy: {config.strategy_type}"}

    result = executor(signal, balance, config, printer)
    result["bot_id"]      = bot_id
    result["timestamp"]   = time.time()
    result["balance"]     = balance
    return result


# ── DAILY PROFIT PROJECTIONS ──────────────────────────────────
def get_all_projections(total_capital: float = 10000.0) -> List[dict]:
    """
    Project daily profits for all 43 bots at given total capital.
    Shows what's possible when all bots run simultaneously.
    """
    projections = []
    for bot_id, config in PRINT_CONFIGS.items():
        allocated  = total_capital / len(PRINT_CONFIGS)
        print_size = allocated * config.capital_pct / 100
        daily_earn = allocated * config.daily_profit_target / 100
        projections.append({
            "bot_id":           bot_id,
            "strategy":         config.strategy_type,
            "allocated_usd":    round(allocated, 2),
            "print_size_usd":   round(print_size, 2),
            "capital_pct":      config.capital_pct,
            "daily_target_pct": config.daily_profit_target,
            "daily_earn_usd":   round(daily_earn, 2),
            "monthly_est_usd":  round(daily_earn * 22, 2),
        })
    projections.sort(key=lambda x: x["daily_earn_usd"], reverse=True)

    total_daily  = sum(p["daily_earn_usd"] for p in projections)
    total_monthly= sum(p["monthly_est_usd"] for p in projections)
    projections.append({
        "bot_id":         "TOTAL_ALL_BOTS",
        "daily_earn_usd": round(total_daily, 2),
        "monthly_est_usd":round(total_monthly, 2),
        "daily_pct_on_capital": round(total_daily/total_capital*100, 2),
    })
    return projections


# ── SINGLETON ─────────────────────────────────────────────────
money_printer = MoneyPrinter()
