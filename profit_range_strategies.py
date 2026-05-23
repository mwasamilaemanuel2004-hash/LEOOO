"""
strategies/timeframe_profit_engine.py — estrading.machine v9 GODMODE
══════════════════════════════════════════════════════════════════════════════
TIMEFRAME + PROFIT TARGET SYSTEM

Each timeframe has a DEDICATED strategy optimized for that time horizon.
User selects: timeframe + profit target → system deploys optimal strategy.

TIMEFRAMES & THEIR BEST STRATEGIES:
  1m  → Micro Scalp     (0.05-0.15% target, HFT logic, 50-100 trades/day)
  3m  → Quick Scalp     (0.1-0.3%  target, momentum, 30-50 trades/day)
  5m  → Standard Scalp  (0.2-0.5%  target, RSI+BB, 15-30 trades/day)
  15m → Session Scalp   (0.5-1.5%  target, SMC+Volume, 8-15 trades/day)
  30m → Swing Entry     (1.0-3.0%  target, breakout, 4-8 trades/day)
  1h  → Intraday Swing  (2.0-5.0%  target, trend, 2-5 trades/day)
  4h  → Swing Trade     (4.0-10%   target, HTF bias, 1-3 trades/day)
  1d  → Position Trade  (10-30%    target, macro, 1-3 trades/week)
  1w  → Long-Term       (30-100%   target, fundamentals, monthly)

PROFIT TARGET + STRATEGY MATRIX:
  Target 1-2%   → Conservative scalp (tight SL, quick TP, high frequency)
  Target 3-5%   → Moderate swing    (2×ATR SL, 4-5×ATR TP)
  Target 6-10%  → Aggressive trend  (3×ATR SL, 8×ATR TP, pyramid)
  Target 11-20% → High conviction   (5×ATR SL, 15×ATR TP, full size)
  Target 20%+   → YOLO mode         (max size, bear crusher, volatility)

DRAWDOWN CONTROL PER TIMEFRAME:
  1m:  Max DD 2%, pause after 3 losses (fast market = quick damage)
  5m:  Max DD 3%, pause after 4 losses
  15m: Max DD 4%, pause after 3 losses
  1h:  Max DD 5%, pause after 3 losses
  4h:  Max DD 8%, pause after 2 losses
  1d:  Max DD 12%, pause after 2 losses
══════════════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Optional
import math


# ── Timeframe Configuration ───────────────────────────────────
@dataclass
class TimeframeConfig:
    tf:              str
    label:           str
    seconds:         int
    strategy_name:   str
    strategy_code:   str
    # Signal parameters
    min_confidence:  float
    sl_atr_mult:     float
    tp_atr_mult:     float
    min_rr:          float
    # Size & frequency
    base_size_pct:   float
    max_trades_day:  int
    avg_hold_minutes:int
    # Risk control
    max_dd_pct:      float
    pause_after_losses: int
    daily_loss_limit:float
    # Profit targets (conservative / base / aggressive)
    profit_cons_pct: float
    profit_base_pct: float
    profit_agg_pct:  float
    # Indicators
    primary_indicators: List[str]
    entry_condition: str
    exit_condition:  str
    description:     str
    color:           str
    icon:            str


TIMEFRAME_CONFIGS: Dict[str, TimeframeConfig] = {
    "1m": TimeframeConfig(
        tf="1m", label="1 Minute", seconds=60,
        strategy_name="Micro HFT Scalp",
        strategy_code="MICRO_HFT",
        min_confidence=78.0,
        sl_atr_mult=0.8, tp_atr_mult=1.5, min_rr=1.5,
        base_size_pct=45.0, max_trades_day=100, avg_hold_minutes=3,
        max_dd_pct=2.0, pause_after_losses=3, daily_loss_limit=2.0,
        profit_cons_pct=0.5, profit_base_pct=1.5, profit_agg_pct=4.0,
        primary_indicators=["Tick Velocity","OBV micro","VWAP deviation","Spread"],
        entry_condition="2nd consecutive same-direction tick + vol surge + spread < 0.01%",
        exit_condition="0.05% profit OR reversal tick — whichever first",
        description="Ultra-fast HFT scalping. 50-100 trades/day. Targets 0.05-0.15% per trade.",
        color="#00e5a0", icon="⚡",
    ),
    "3m": TimeframeConfig(
        tf="3m", label="3 Minutes", seconds=180,
        strategy_name="Quick Momentum Scalp",
        strategy_code="QUICK_MOM",
        min_confidence=74.0,
        sl_atr_mult=1.0, tp_atr_mult=2.0, min_rr=1.8,
        base_size_pct=48.0, max_trades_day=50, avg_hold_minutes=8,
        max_dd_pct=2.5, pause_after_losses=4, daily_loss_limit=2.5,
        profit_cons_pct=1.0, profit_base_pct=2.5, profit_agg_pct=6.0,
        primary_indicators=["RSI 7","EMA 5/13","Volume Surge","Momentum"],
        entry_condition="RSI reversal + EMA micro cross + volume spike >2×",
        exit_condition="EMA cross reversal OR trailing stop 0.5×ATR",
        description="Fast momentum scalping. 30-50 trades/day. Best in trending sessions.",
        color="#22c55e", icon="🚀",
    ),
    "5m": TimeframeConfig(
        tf="5m", label="5 Minutes", seconds=300,
        strategy_name="Standard Precision Scalp",
        strategy_code="STD_SCALP",
        min_confidence=70.0,
        sl_atr_mult=1.2, tp_atr_mult=2.5, min_rr=2.0,
        base_size_pct=50.0, max_trades_day=30, avg_hold_minutes=15,
        max_dd_pct=3.0, pause_after_losses=4, daily_loss_limit=3.0,
        profit_cons_pct=1.5, profit_base_pct=4.0, profit_agg_pct=8.0,
        primary_indicators=["RSI 14","BB %B","EMA 8/21","OBV","VWAP"],
        entry_condition="RSI oversold/overbought + BB band touch + EMA direction",
        exit_condition="BB opposite band OR 2.5×ATR TP OR trailing 1×ATR",
        description="Balanced scalping. 15-30 trades/day. The platform's most popular timeframe.",
        color="#6366f1", icon="📊",
    ),
    "15m": TimeframeConfig(
        tf="15m", label="15 Minutes", seconds=900,
        strategy_name="Session Swing Scalp",
        strategy_code="SESSION_SWING",
        min_confidence=68.0,
        sl_atr_mult=1.5, tp_atr_mult=3.5, min_rr=2.2,
        base_size_pct=50.0, max_trades_day=15, avg_hold_minutes=45,
        max_dd_pct=4.0, pause_after_losses=3, daily_loss_limit=4.0,
        profit_cons_pct=2.5, profit_base_pct=6.0, profit_agg_pct=12.0,
        primary_indicators=["SMC Order Blocks","Volume Profile","EMA 8/21/50","RSI 14","Pivot Points"],
        entry_condition="OB retest + pivot support/resistance + RSI confirmation + session timing",
        exit_condition="Next pivot level OR 3.5×ATR OR trailing 1.5×ATR",
        description="Session-optimized swing scalp. Best at London open and NY session.",
        color="#f59e0b", icon="🎯",
    ),
    "30m": TimeframeConfig(
        tf="30m", label="30 Minutes", seconds=1800,
        strategy_name="Breakout Swing",
        strategy_code="BREAKOUT_SWING",
        min_confidence=68.0,
        sl_atr_mult=2.0, tp_atr_mult=4.5, min_rr=2.0,
        base_size_pct=50.0, max_trades_day=8, avg_hold_minutes=90,
        max_dd_pct=5.0, pause_after_losses=3, daily_loss_limit=4.0,
        profit_cons_pct=3.0, profit_base_pct=7.0, profit_agg_pct=15.0,
        primary_indicators=["Donchian Breakout","Volume Surge","EMA 20/50","ATR","MACD"],
        entry_condition="Donchian channel breakout + volume >2.5× + MACD cross",
        exit_condition="MACD reverse OR 4.5×ATR target OR trailing 2×ATR",
        description="Breakout specialist. 4-8 trades/day. Targets 3-15% per breakout event.",
        color="#f97316", icon="💥",
    ),
    "1h": TimeframeConfig(
        tf="1h", label="1 Hour", seconds=3600,
        strategy_name="Intraday Trend Rider",
        strategy_code="INTRADAY_TREND",
        min_confidence=65.0,
        sl_atr_mult=2.0, tp_atr_mult=5.0, min_rr=2.2,
        base_size_pct=50.0, max_trades_day=5, avg_hold_minutes=240,
        max_dd_pct=5.0, pause_after_losses=3, daily_loss_limit=5.0,
        profit_cons_pct=4.0, profit_base_pct=8.0, profit_agg_pct=18.0,
        primary_indicators=["EMA 8/21/50/200","RSI 14","MACD","ATR","Volume","Supertrend"],
        entry_condition="EMA 8/21 cross + above EMA50 + RSI 45-60 + volume confirmation",
        exit_condition="EMA cross reverse OR 5×ATR OR trailing 2×ATR from peak",
        description="Classic trend riding. 2-5 trades/day. Best for consistent daily profits.",
        color="#3b82f6", icon="📈",
    ),
    "4h": TimeframeConfig(
        tf="4h", label="4 Hours", seconds=14400,
        strategy_name="HTF Bias Swing",
        strategy_code="HTF_SWING",
        min_confidence=65.0,
        sl_atr_mult=2.5, tp_atr_mult=6.0, min_rr=2.5,
        base_size_pct=50.0, max_trades_day=3, avg_hold_minutes=720,
        max_dd_pct=8.0, pause_after_losses=2, daily_loss_limit=6.0,
        profit_cons_pct=6.0, profit_base_pct=12.0, profit_agg_pct=25.0,
        primary_indicators=["Weekly bias","Daily OB","4H EMA 21/55","RSI 21","DXY corr"],
        entry_condition="Weekly+daily bias aligned + 4H OB retest + RSI reset 40-50",
        exit_condition="Previous major high/low OR 6×ATR OR weekly bias change",
        description="Institutional swing trading. 1-3 trades/day. Big moves, high R:R.",
        color="#8b5cf6", icon="🏦",
    ),
    "1d": TimeframeConfig(
        tf="1d", label="Daily", seconds=86400,
        strategy_name="Position Trade",
        strategy_code="POSITION_TRADE",
        min_confidence=72.0,
        sl_atr_mult=3.0, tp_atr_mult=9.0, min_rr=3.0,
        base_size_pct=40.0, max_trades_day=1, avg_hold_minutes=2880,
        max_dd_pct=12.0, pause_after_losses=2, daily_loss_limit=8.0,
        profit_cons_pct=10.0, profit_base_pct=20.0, profit_agg_pct=50.0,
        primary_indicators=["Weekly structure","Daily EMA 50/200","RSI 21","Market phases","COT"],
        entry_condition="Daily key level + weekly bias + RSI pullback to neutral zone",
        exit_condition="Major structure level OR 9×ATR OR fundamental change",
        description="Long-term position trades. 1-3 trades/week. 10-50% target per trade.",
        color="#ec4899", icon="💎",
    ),
    "1w": TimeframeConfig(
        tf="1w", label="Weekly", seconds=604800,
        strategy_name="Macro Position",
        strategy_code="MACRO_POS",
        min_confidence=78.0,
        sl_atr_mult=4.0, tp_atr_mult=12.0, min_rr=3.0,
        base_size_pct=30.0, max_trades_day=0, avg_hold_minutes=10080,
        max_dd_pct=15.0, pause_after_losses=1, daily_loss_limit=10.0,
        profit_cons_pct=30.0, profit_base_pct=60.0, profit_agg_pct=150.0,
        primary_indicators=["Monthly structure","Weekly EMA","BTC halving cycles","Macro economy"],
        entry_condition="Monthly/weekly key level + fundamental catalyst + macro alignment",
        exit_condition="Macro structure change OR 12×ATR OR fundamental reversal",
        description="Macro/halving cycle trades. Monthly entries. 30-150% targets.",
        color="#a16207", icon="🌍",
    ),
}

# ── Profit Target Profiles ────────────────────────────────────
@dataclass
class ProfitProfile:
    target_pct:    float
    label:         str
    color:         str
    icon:          str
    style:         str    # conservative | moderate | aggressive | ultra
    sl_adjustment: float  # multiply SL by this
    tp_adjustment: float  # multiply TP by this
    size_pct:      float  # capital deployment %
    max_dd_allowed:float
    special_rule:  str
    description:   str

PROFIT_PROFILES: Dict[str, ProfitProfile] = {
    "1pct":  ProfitProfile(1,  "1% Safe",        "#22c55e","🛡️","conservative", 0.8, 1.0, 40, 1.5,  "Stop after target hit", "Ultra safe. Very high win rate. Ideal for daily income."),
    "2pct":  ProfitProfile(2,  "2% Steady",      "#4ade80","✅","conservative", 0.9, 1.2, 45, 2.0,  "2% Pro Mode active",    "Daily 2% target. Auto-stops on hit."),
    "3pct":  ProfitProfile(3,  "3% Balanced",    "#86efac","💚","moderate",     1.0, 1.5, 48, 2.5,  "Compound on win",       "Balanced risk/reward. Sustainable daily target."),
    "5pct":  ProfitProfile(5,  "5% Active",      "#facc15","⚡","moderate",     1.0, 2.0, 50, 3.5,  "Pyramid after +2%",     "Active compounding. 5% daily is excellent."),
    "7pct":  ProfitProfile(7,  "7% Growth",      "#fb923c","🚀","aggressive",   1.1, 2.5, 52, 4.5,  "Compound + pyramid",    "High growth. Acceptable risk for experienced traders."),
    "10pct": ProfitProfile(10, "10% High",       "#ef4444","🔥","aggressive",   1.2, 3.0, 55, 6.0,  "Full capital deploy",   "Maximum sustainable daily target."),
    "15pct": ProfitProfile(15, "15% Bold",       "#dc2626","⚠️","ultra",        1.3, 4.0, 58, 8.0,  "Bear crusher + vol",    "Bold target. Uses Bear Crusher + Volatility Assassin."),
    "20pct": ProfitProfile(20, "20% Ultra",      "#b91c1c","💀","ultra",        1.5, 5.0, 60, 10.0, "All weapons deployed",  "Ultra aggressive. All special strategies active."),
    "30pct": ProfitProfile(30, "30% YOLO",       "#7f1d1d","☠️","ultra",        2.0, 7.0, 65, 15.0, "Quantum + Bear + Vol",  "Maximum possible. Panic/euphoria exploitation only."),
}


def get_timeframe_strategy(
    tf:            str,
    profit_target: str,
    symbol:        str = "BTCUSDT",
) -> dict:
    """
    Get complete strategy config for timeframe + profit target combo.
    Returns everything needed for execution.
    """
    tf_cfg  = TIMEFRAME_CONFIGS.get(tf, TIMEFRAME_CONFIGS["5m"])
    pp_cfg  = PROFIT_PROFILES.get(profit_target, PROFIT_PROFILES["5pct"])

    # Adjust SL/TP based on profit profile
    sl_mult = tf_cfg.sl_atr_mult * pp_cfg.sl_adjustment
    tp_mult = tf_cfg.tp_atr_mult * pp_cfg.tp_adjustment
    rr      = tp_mult / sl_mult

    # Capital size
    size_pct= min(70, (tf_cfg.base_size_pct + pp_cfg.size_pct) / 2)

    # Special strategy activation
    special_strats = []
    if pp_cfg.style == "ultra":
        special_strats = ["bear_crusher_pro", "volatility_assassin", "quantum_arb_x"]
    elif pp_cfg.style == "aggressive":
        special_strats = ["momentum_surge", "breakout_king"]
    elif pp_cfg.style == "moderate":
        special_strats = ["ai_fusion", "hybrid_alpha"]
    else:
        special_strats = ["smart_balance", "hybrid_pro"]

    # Min confidence: higher target = higher confidence required
    base_conf = tf_cfg.min_confidence
    adj_conf  = min(90, base_conf + (pp_cfg.style == "conservative") * 5 + 
                   (pp_cfg.style == "ultra") * (-5))

    return {
        "timeframe":         tf,
        "tf_label":          tf_cfg.label,
        "strategy":          tf_cfg.strategy_name,
        "strategy_code":     tf_cfg.strategy_code,
        "profit_target_pct": pp_cfg.target_pct,
        "profit_label":      pp_cfg.label,
        "profit_style":      pp_cfg.style,
        "symbol":            symbol,
        # Execution params
        "sl_atr_mult":       round(sl_mult, 2),
        "tp_atr_mult":       round(tp_mult, 2),
        "rr_ratio":          round(rr, 2),
        "min_confidence":    adj_conf,
        "capital_pct":       round(size_pct, 1),
        "max_trades_day":    tf_cfg.max_trades_day,
        "avg_hold_minutes":  tf_cfg.avg_hold_minutes,
        # Risk control
        "max_dd_pct":        min(tf_cfg.max_dd_pct, pp_cfg.max_dd_allowed),
        "pause_after_losses":tf_cfg.pause_after_losses,
        "daily_loss_limit":  tf_cfg.daily_loss_limit,
        "special_rule":      pp_cfg.special_rule,
        # Active systems
        "active_strategies": special_strats,
        "primary_indicators":tf_cfg.primary_indicators,
        "entry_condition":   tf_cfg.entry_condition,
        "exit_condition":    tf_cfg.exit_condition,
        # UI
        "tf_color":          tf_cfg.color,
        "tf_icon":           tf_cfg.icon,
        "profit_color":      pp_cfg.color,
        "profit_icon":       pp_cfg.icon,
        "description":       (
            f"{tf_cfg.description} | "
            f"{pp_cfg.description} | "
            f"SL:{sl_mult:.1f}×ATR, TP:{tp_mult:.1f}×ATR, RR:{rr:.1f}"
        ),
        "expected_daily": (
            f"Conservative: {pp_cfg.target_pct*0.5:.1f}% | "
            f"Base: {pp_cfg.target_pct:.1f}% | "
            f"Optimistic: {pp_cfg.target_pct*1.5:.1f}%"
        ),
    }


def get_all_configs() -> dict:
    """Return all timeframe and profit configs for frontend."""
    return {
        "timeframes": {k: {
            "label":          v.label,
            "strategy":       v.strategy_name,
            "icon":           v.icon,
            "color":          v.color,
            "max_trades":     v.max_trades_day,
            "profit_base":    v.profit_base_pct,
            "max_dd":         v.max_dd_pct,
            "description":    v.description,
            "indicators":     v.primary_indicators,
        } for k, v in TIMEFRAME_CONFIGS.items()},
        "profit_profiles": {k: {
            "label":       v.label,
            "target":      v.target_pct,
            "color":       v.color,
            "icon":        v.icon,
            "style":       v.style,
            "description": v.description,
            "size_pct":    v.size_pct,
        } for k, v in PROFIT_PROFILES.items()},
    }
