"""
strategies/profit_range_strategies.py — ESTRADE v7 ULTRA
══════════════════════════════════════════════════════════════════════════════
ULTRA ADVANCED STRATEGIES PER PROFIT RANGE
Each profit range gets a dedicated strategy engine with:
  • Specific indicators calibrated for that target size
  • Trade style (scalp / momentum / swing / position)
  • Capital protection rules matching the risk level
  • Dynamic SL/TP mathematics
  • Entry/exit conditions with 5+ confirmations
  • Session awareness (Asia/London/NY)

PROFIT RANGES COVERED:
  1%  → Lightning Scalp      (hold 1–5 min,   risk 0.20%, RR 5:1)
  2%  → Pro Scalp ★RECOMMEND (hold 5–30 min,  risk 0.40%, RR 5:1)
  3%  → Momentum Burst       (hold 15–60 min, risk 0.55%, RR 5.4:1)
  4%  → Breakout Rider       (hold 30–120 min,risk 0.70%, RR 5.7:1)
  5%  → Trend Surfer         (hold 1–4 hr,    risk 0.90%, RR 5.5:1)
  6%  → Fibonacci Swing      (hold 2–8 hr,    risk 1.10%, RR 5.4:1)
  7%  → SMC Precision        (hold 4–12 hr,   risk 1.25%, RR 5.6:1)
  8%  → VWAP Institutional   (hold 6–24 hr,   risk 1.40%, RR 5.7:1)
  9%  → Multi-TF Confluence  (hold 12–24 hr,  risk 1.60%, RR 5.6:1)
  10% → Full Swing           (hold 1–3 days,  risk 1.80%, RR 5.5:1)
  15% → Position Trade       (hold 3–7 days,  risk 2.70%, RR 5.5:1)
  20% → Macro Swing          (hold 5–14 days, risk 3.50%, RR 5.7:1)
  30% → Major Position       (hold 1–4 weeks, risk 5.50%, RR 5.4:1)

Capital protection for each:
  → Hard stop: if daily loss > daily_stop_pct → halt all trading
  → Trade stop: 2 consecutive losses → pause (all ranges)
  → Scale-in: allowed only after 2 successful trades in same direction
  → Trailing SL: activates when price reaches 50% of target
  → Emergency close: if drawdown > 2× SL in active trade → close immediately
══════════════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations
import math
from dataclasses import dataclass, field
from typing import Optional, Literal
import numpy as np

TradeStyle = Literal[
    "lightning_scalp","pro_scalp","momentum_burst","breakout_rider",
    "trend_surfer","fibonacci_swing","smc_precision","vwap_institutional",
    "multi_tf_confluence","full_swing","position_trade","macro_swing","major_position"
]


# ══════════════════════════════════════════════════════════════
# RANGE PROFILE TABLE (single source of truth)
# ══════════════════════════════════════════════════════════════

@dataclass
class RangeProfile:
    target_pct:       float
    risk_pct:         float          # Max risk per trade
    rr_ratio:         float          # Risk:Reward minimum
    style:            TradeStyle
    style_label:      str
    hold_min:         int            # Min hold in minutes
    hold_max:         int            # Max hold in minutes
    daily_stop_pct:   float          # Daily loss stops trading
    min_confidence:   float          # Min AI confidence to enter
    session_ok:       list[str]      # Best sessions to trade
    primary_tf:       str            # Primary timeframe
    confirm_tf:       str            # Confirmation timeframe
    trailing_sl_pct:  float          # Activate trailing SL at % profit
    scale_in_ok:      bool           # Allow scale-in entries
    indicators:       list[str]      # Key indicators used
    entry_rules:      list[str]      # Human-readable entry conditions
    exit_rules:       list[str]      # Human-readable exit conditions
    protect_rules:    list[str]      # Capital protection rules
    color:            str            # UI color
    badge:            str            # UI badge text
    recommended:      bool = False   # Mark as recommended

    @property
    def tp_pct(self) -> float:
        return round(self.risk_pct * self.rr_ratio, 3)

    @property
    def sl_multiplier(self) -> float:
        """ATR multiplier for SL calculation."""
        if   self.target_pct <= 2:  return 0.8
        elif self.target_pct <= 5:  return 1.2
        elif self.target_pct <= 10: return 1.8
        else:                        return 2.5

    @property
    def tp_multiplier(self) -> float:
        return self.sl_multiplier * self.rr_ratio


RANGE_PROFILES: dict[float, RangeProfile] = {

    # ── 1% Lightning Scalp ───────────────────────────────────
    1.0: RangeProfile(
        target_pct=1.0, risk_pct=0.20, rr_ratio=5.0,
        style="lightning_scalp", style_label="⚡ Lightning Scalp",
        hold_min=1, hold_max=5,
        daily_stop_pct=1.0, min_confidence=70.0,
        session_ok=["london","new_york","overlap"],
        primary_tf="M1", confirm_tf="M5",
        trailing_sl_pct=0.5, scale_in_ok=False,
        indicators=["EMA_3_8_cross","RSI_1m","MACD_hist_flip","vol_spike","BB_squeeze"],
        entry_rules=[
            "EMA 3 crosses EMA 8 (direction confirmed)",
            "RSI between 35–65 (not overbought/oversold)",
            "MACD histogram flips positive/negative",
            "Volume spike ≥1.5× 20-bar average",
            "BB width < 0.015 (squeeze detected)",
        ],
        exit_rules=[
            "TP: +1.0% from entry",
            "SL: -0.2% from entry (tight)",
            "Max hold: 5 minutes regardless",
            "Trailing SL activates at +0.5%",
        ],
        protect_rules=[
            "MAX 2 concurrent lightning scalp trades",
            "After 3 consecutive losses → stop for 1 hour",
            "Daily PnL -1% → halt all lightning scalps",
            "News event in next 2min → skip entry",
        ],
        color="#06b6d4", badge="1%",
    ),

    # ── 2% Pro Scalp ★ RECOMMENDED ───────────────────────────
    2.0: RangeProfile(
        target_pct=2.0, risk_pct=0.40, rr_ratio=5.0,
        style="pro_scalp", style_label="🎯 Pro Scalp ★",
        hold_min=5, hold_max=30,
        daily_stop_pct=2.0, min_confidence=68.0,
        session_ok=["london","new_york","overlap"],
        primary_tf="M5", confirm_tf="M15",
        trailing_sl_pct=1.0, scale_in_ok=False,
        indicators=["EMA_8_21","RSI_14","MACD","BB","vol_ratio","VWAP"],
        entry_rules=[
            "EMA 8 crosses EMA 21 on M5",
            "RSI 40–60 (neutral zone for momentum)",
            "MACD histogram trending in entry direction",
            "Price within 0.3% of VWAP or bouncing off it",
            "Volume ≥1.3× average",
            "No major news in next 15min",
        ],
        exit_rules=[
            "TP: +2.0% from entry",
            "SL: -0.4% from entry",
            "Trailing SL at +1.0% (lock 50%)",
            "Max hold: 30 minutes",
        ],
        protect_rules=[
            "2 consecutive losses → pause 2 candles",
            "Daily PnL -2% → stop trading",
            "Win streak ≥3 → scale up 1.2× (max 1.5×)",
            "Position size never > 5% of capital",
        ],
        color="#22c55e", badge="2% ★", recommended=True,
    ),

    # ── 3% Momentum Burst ────────────────────────────────────
    3.0: RangeProfile(
        target_pct=3.0, risk_pct=0.55, rr_ratio=5.4,
        style="momentum_burst", style_label="🚀 Momentum Burst",
        hold_min=15, hold_max=60,
        daily_stop_pct=2.5, min_confidence=69.0,
        session_ok=["london","new_york","overlap"],
        primary_tf="M15", confirm_tf="H1",
        trailing_sl_pct=1.5, scale_in_ok=False,
        indicators=["BB_squeeze","vol_surge","RSI_momentum","MACD_divergence","ATR_expansion","OBV"],
        entry_rules=[
            "BB width < 0.02 for ≥5 candles (confirmed squeeze)",
            "Volume surges ≥2.0× average on breakout candle",
            "RSI crosses 50 in breakout direction",
            "MACD histogram accelerating (3 consecutive growing bars)",
            "ATR expanding: current > 1.3× 20-bar ATR average",
            "OBV trending in breakout direction",
        ],
        exit_rules=[
            "TP: +3.0% (full target)",
            "Partial TP1: +1.5% (close 40% of position)",
            "SL: -0.55% from entry",
            "Trailing SL activates at +1.5%",
            "Max hold: 60 minutes",
        ],
        protect_rules=[
            "Only trade confirmed BB squeeze breakouts",
            "Skip if broader market down >1% in last hour",
            "2 losses → pause 1 candle (15min)",
            "Daily stop: -2.5%",
        ],
        color="#4ade80", badge="3%",
    ),

    # ── 4% Breakout Rider ────────────────────────────────────
    4.0: RangeProfile(
        target_pct=4.0, risk_pct=0.70, rr_ratio=5.7,
        style="breakout_rider", style_label="💥 Breakout Rider",
        hold_min=30, hold_max=120,
        daily_stop_pct=3.0, min_confidence=70.0,
        session_ok=["london","new_york"],
        primary_tf="M15", confirm_tf="H1",
        trailing_sl_pct=2.0, scale_in_ok=True,
        indicators=["resistance_break","vol_confirm","RSI_breakout","ATR","stoch","OBV_divergence"],
        entry_rules=[
            "Price breaks above key resistance (tested ≥2× before)",
            "Breakout candle volume ≥2.5× 20-bar average",
            "RSI crosses above 55 on breakout",
            "Stochastic K above 50 and rising",
            "ATR expanding ≥1.4× recent average",
            "OBV making new highs (confirming breakout)",
            "H1 candle confirms M15 breakout direction",
        ],
        exit_rules=[
            "TP1: +2.0% (close 35%)",
            "TP2: +4.0% (close remaining)",
            "SL: -0.70% below breakout level",
            "Trailing SL at +2.0%",
            "Max hold: 2 hours",
        ],
        protect_rules=[
            "Enter only on confirmed breakout candle close",
            "Scale-in allowed: add 50% at first pullback",
            "Cancel scale-in if price drops back into range",
            "2 failed breakouts same day → stop trading that pair",
            "Daily stop: -3.0%",
        ],
        color="#a3e635", badge="4%",
    ),

    # ── 5% Trend Surfer ──────────────────────────────────────
    5.0: RangeProfile(
        target_pct=5.0, risk_pct=0.90, rr_ratio=5.5,
        style="trend_surfer", style_label="🌊 Trend Surfer",
        hold_min=60, hold_max=240,
        daily_stop_pct=3.5, min_confidence=71.0,
        session_ok=["london","new_york"],
        primary_tf="H1", confirm_tf="H4",
        trailing_sl_pct=2.5, scale_in_ok=True,
        indicators=["EMA_50_200","ADX","RSI","MACD","ATR","higher_highs"],
        entry_rules=[
            "EMA 50 above EMA 200 (bull) / below (bear)",
            "ADX > 25 (strong trend confirmed)",
            "RSI 45–65 (bull) / 35–55 (bear)",
            "MACD positive (bull) / negative (bear) and expanding",
            "Price pulls back to EMA 20 (entry on bounce)",
            "H4 candle confirms H1 direction",
            "Higher highs + higher lows pattern (bull) / lower lows (bear)",
        ],
        exit_rules=[
            "TP1: +2.5% (close 30%)",
            "TP2: +5.0% (close remaining)",
            "SL: -0.90% from entry",
            "Trailing SL: 1.5× ATR below highest high",
            "Max hold: 4 hours",
        ],
        protect_rules=[
            "Only trade in established trend (ADX>25 for ≥3 bars)",
            "Scale-in at EMA 20 bounce (max 2 entries)",
            "ADX drops below 20 → close 50% immediately",
            "Counter-trend signal on H4 → close all",
            "Daily stop: -3.5%",
        ],
        color="#facc15", badge="5%",
    ),

    # ── 6% Fibonacci Swing ───────────────────────────────────
    6.0: RangeProfile(
        target_pct=6.0, risk_pct=1.10, rr_ratio=5.4,
        style="fibonacci_swing", style_label="📐 Fibonacci Swing",
        hold_min=120, hold_max=480,
        daily_stop_pct=4.0, min_confidence=72.0,
        session_ok=["london","new_york","asia"],
        primary_tf="H1", confirm_tf="H4",
        trailing_sl_pct=3.0, scale_in_ok=True,
        indicators=["fib_retracement","RSI_divergence","MACD_hidden_div","pivot_points","BB","stoch"],
        entry_rules=[
            "Price retraces to Fibonacci 38.2% or 61.8% level",
            "RSI bullish/bearish divergence at Fib level",
            "Hidden MACD divergence confirming reversal",
            "Pivot point support/resistance aligns with Fib",
            "BB lower/upper band confirms Fib level",
            "Stochastic OS/OB at Fib zone",
            "Confirmation candle (engulfing/pin bar) at level",
        ],
        exit_rules=[
            "TP1: +3.0% at Fib 100% (close 40%)",
            "TP2: +6.0% at Fib 161.8% (close remaining)",
            "SL: -1.10% below Fib level",
            "Trailing at +3.0%",
            "Max hold: 8 hours",
        ],
        protect_rules=[
            "Fib level must have been tested ≥2× before",
            "RSI divergence mandatory (not just Fib touch)",
            "Scale in: 2nd entry at 50% level if first in at 61.8%",
            "Break of 78.6% Fib → cut loss immediately",
            "Daily stop: -4.0%",
        ],
        color="#fb923c", badge="6%",
    ),

    # ── 7% SMC Precision ─────────────────────────────────────
    7.0: RangeProfile(
        target_pct=7.0, risk_pct=1.25, rr_ratio=5.6,
        style="smc_precision", style_label="🏦 SMC Precision",
        hold_min=240, hold_max=720,
        daily_stop_pct=4.5, min_confidence=73.0,
        session_ok=["london","new_york"],
        primary_tf="H1", confirm_tf="H4",
        trailing_sl_pct=3.5, scale_in_ok=True,
        indicators=["order_block","FVG","BOS","CHoCH","liquidity_sweep","market_structure"],
        entry_rules=[
            "Identify Order Block (last bearish/bullish impulse candle)",
            "Fair Value Gap (FVG) present within OB zone",
            "Break of Structure (BOS) confirms direction",
            "Liquidity sweep above/below previous high/low",
            "CHoCH (Change of Character) on lower timeframe",
            "Price returns to OB/FVG zone for entry",
            "Volume dry-up at entry zone (institutional stacking)",
        ],
        exit_rules=[
            "TP1: Previous liquidity level (close 35%)",
            "TP2: +7.0% at next SMC target",
            "SL: Below Order Block invalidation",
            "Trailing at +3.5%",
            "Max hold: 12 hours",
        ],
        protect_rules=[
            "OB must be on H1 or higher timeframe",
            "Do not enter if OB was already mitigated",
            "Liquidity sweep confirmation mandatory",
            "BOS invalidation → immediate close",
            "Daily stop: -4.5%",
        ],
        color="#f97316", badge="7%",
    ),

    # ── 8% VWAP Institutional ────────────────────────────────
    8.0: RangeProfile(
        target_pct=8.0, risk_pct=1.40, rr_ratio=5.7,
        style="vwap_institutional", style_label="🏛️ VWAP Institutional",
        hold_min=360, hold_max=1440,
        daily_stop_pct=5.0, min_confidence=74.0,
        session_ok=["london","new_york"],
        primary_tf="H1", confirm_tf="H4",
        trailing_sl_pct=4.0, scale_in_ok=True,
        indicators=["VWAP_deviation","volume_profile","POC","HVN","LVN","delta","CVD"],
        entry_rules=[
            "Price deviates ≥2σ from anchored VWAP",
            "Volume Profile POC (Point of Control) at entry zone",
            "High Volume Node (HVN) confirms support/resistance",
            "Delta (buy vs sell volume) confirms direction",
            "CVD (Cumulative Volume Delta) divergence signal",
            "VWAP reclaim/rejection candle pattern",
            "Daily open and weekly open levels confluence",
        ],
        exit_rules=[
            "TP1: VWAP mean reversion 50% (close 30%)",
            "TP2: +8.0% at opposite VWAP deviation",
            "SL: -1.40% beyond 3σ VWAP deviation",
            "Trailing at +4.0%",
            "Max hold: 24 hours",
        ],
        protect_rules=[
            "Only trade ≥2σ VWAP deviations (extreme dislocations)",
            "CVD confirmation mandatory (institutional footprint)",
            "Scale in at VWAP reclaim (add 50% of position)",
            "3σ deviation means trend continuation → cut trade",
            "Daily stop: -5.0%",
        ],
        color="#ef4444", badge="8%",
    ),

    # ── 9% Multi-TF Confluence ───────────────────────────────
    9.0: RangeProfile(
        target_pct=9.0, risk_pct=1.60, rr_ratio=5.6,
        style="multi_tf_confluence", style_label="🔭 Multi-TF Confluence",
        hold_min=720, hold_max=1440,
        daily_stop_pct=5.5, min_confidence=75.0,
        session_ok=["london","new_york","asia"],
        primary_tf="H4", confirm_tf="D1",
        trailing_sl_pct=4.5, scale_in_ok=True,
        indicators=["D1_trend","H4_structure","H1_entry","M15_trigger","RSI_multi","MACD_multi"],
        entry_rules=[
            "D1: Trend direction confirmed (EMA 50/200 alignment)",
            "H4: Market structure (HH/HL or LH/LL) in D1 direction",
            "H1: Entry zone identified (support/resistance cluster)",
            "M15: Trigger signal (EMA cross + volume)",
            "RSI aligned bull/bear on all 4 timeframes",
            "MACD positive/negative on H4 and H1",
            "No major economic events in next 4 hours",
        ],
        exit_rules=[
            "TP1: +4.5% (H4 structural target, close 35%)",
            "TP2: +9.0% (D1 structural target)",
            "SL: -1.60% at H4 structure invalidation",
            "Trailing SL: 2.0× ATR H4",
            "Max hold: 24 hours",
        ],
        protect_rules=[
            "All 4 TF must agree (no exceptions)",
            "Reduce position 50% if H4 structure breaks",
            "Scale in only after H1 structure confirms",
            "Weekly high/low breach → reassess immediately",
            "Daily stop: -5.5%",
        ],
        color="#dc2626", badge="9%",
    ),

    # ── 10% Full Swing ───────────────────────────────────────
    10.0: RangeProfile(
        target_pct=10.0, risk_pct=1.80, rr_ratio=5.5,
        style="full_swing", style_label="🌊 Full Swing",
        hold_min=1440, hold_max=4320,
        daily_stop_pct=6.0, min_confidence=76.0,
        session_ok=["london","new_york","asia"],
        primary_tf="H4", confirm_tf="D1",
        trailing_sl_pct=5.0, scale_in_ok=True,
        indicators=["ichimoku","elliott_wave","RSI_weekly","MACD_H4","pivot_weekly","COT"],
        entry_rules=[
            "Ichimoku cloud: price above/below cloud confirmed",
            "Tenkan/Kijun cross in trade direction",
            "Elliott Wave: entering wave 3 or wave 5",
            "Weekly RSI not overbought/oversold (30–70)",
            "H4 MACD positive momentum and expanding",
            "Weekly pivot support/resistance at entry",
            "COT data: net positions favor trade direction",
        ],
        exit_rules=[
            "TP1: +5.0% at Ichimoku Kijun projection (close 30%)",
            "TP2: +10.0% at Senkou Span B",
            "SL: -1.80% below cloud base",
            "Trailing SL: 3.0× ATR H4",
            "Max hold: 3 days",
        ],
        protect_rules=[
            "Ichimoku alignment mandatory (all lines)",
            "Elliott count invalidated → close immediately",
            "Scale in at Tenkan retest (max 2 entries)",
            "Weekend gap risk: reduce to 50% before Friday close",
            "Daily stop: -6.0%",
        ],
        color="#b91c1c", badge="10%",
    ),

    # ── 15% Position Trade ───────────────────────────────────
    15.0: RangeProfile(
        target_pct=15.0, risk_pct=2.70, rr_ratio=5.5,
        style="position_trade", style_label="📊 Position Trade",
        hold_min=4320, hold_max=10080,
        daily_stop_pct=7.5, min_confidence=77.0,
        session_ok=["any"],
        primary_tf="D1", confirm_tf="W1",
        trailing_sl_pct=7.5, scale_in_ok=True,
        indicators=["MA_cross_D1","RSI_W1","MACD_D1","major_SR","macro_sentiment","funding_rate"],
        entry_rules=[
            "D1 MA 50/200 cross (golden/death cross)",
            "Weekly RSI exiting extreme zone (>70 or <30)",
            "D1 MACD confirmed direction change",
            "Major S/R level (tested ≥3 times historically)",
            "Macro sentiment aligned (DXY, fear/greed index)",
            "Funding rate extreme (for crypto: >0.05% or <-0.05%)",
            "News catalyst confirmed or upcoming",
        ],
        exit_rules=[
            "TP1: +7.5% at major resistance (close 30%)",
            "TP2: +15.0% at structural target",
            "SL: -2.70% below major support",
            "Trailing SL: ATR×4 daily",
            "Max hold: 7 days",
        ],
        protect_rules=[
            "Position sizing: max 10% of total capital",
            "Scale in: 3 tranches (50%/30%/20%)",
            "D1 close back through MA → reduce 50%",
            "No leverage > 3× for position trades",
            "Weekly review: reassess if market structure changes",
            "Daily stop: -7.5%",
        ],
        color="#991b1b", badge="15%",
    ),

    # ── 20% Macro Swing ──────────────────────────────────────
    20.0: RangeProfile(
        target_pct=20.0, risk_pct=3.50, rr_ratio=5.7,
        style="macro_swing", style_label="🌍 Macro Swing",
        hold_min=7200, hold_max=20160,
        daily_stop_pct=10.0, min_confidence=78.0,
        session_ok=["any"],
        primary_tf="D1", confirm_tf="W1",
        trailing_sl_pct=10.0, scale_in_ok=True,
        indicators=["DXY_correlation","macro_regime","W1_structure","institutional_flow","options_OI","on_chain"],
        entry_rules=[
            "DXY macro trend opposing entry (gold/crypto inverse)",
            "Macro regime confirmed (inflation/deflation/risk-on/off)",
            "Weekly structure: major trend reversal pattern",
            "Institutional flow: COT net positioning extreme",
            "Options open interest: max pain level approaching",
            "On-chain (crypto): whale accumulation/distribution",
            "Monthly level key support/resistance",
        ],
        exit_rules=[
            "TP1: +10.0% (close 25%)",
            "TP2: +20.0% (close remaining)",
            "SL: -3.50% at macro structure invalidation",
            "Trailing: 5% below highest high",
            "Max hold: 14 days",
        ],
        protect_rules=[
            "Max position: 8% of portfolio",
            "3 tranches: 40%/35%/25%",
            "Macro catalyst change → immediate review",
            "Leverage: max 2× only",
            "Hedge with options if available",
            "Daily stop: -10.0%",
        ],
        color="#7f1d1d", badge="20%",
    ),

    # ── 30% Major Position ───────────────────────────────────
    30.0: RangeProfile(
        target_pct=30.0, risk_pct=5.50, rr_ratio=5.4,
        style="major_position", style_label="🔱 Major Position",
        hold_min=10080, hold_max=40320,
        daily_stop_pct=15.0, min_confidence=80.0,
        session_ok=["any"],
        primary_tf="W1", confirm_tf="MN",
        trailing_sl_pct=15.0, scale_in_ok=True,
        indicators=["monthly_trend","macro_cycle","on_chain_hodl","institution_acc","halvings","regulatory"],
        entry_rules=[
            "Monthly close above/below key structure level",
            "Macro cycle phase confirmed (accumulation/distribution)",
            "On-chain HODL waves: strong accumulation by long-term holders",
            "Institutional accumulation confirmed (Glassnode/Chainalysis)",
            "Halving cycle timing (crypto) / major catalyst (forex/gold)",
            "Regulatory environment favorable",
            "Risk/reward confirmed with analyst consensus",
        ],
        exit_rules=[
            "TP1: +15.0% (close 20%)",
            "TP2: +30.0% (close remaining)",
            "SL: -5.50% at monthly structure break",
            "Trailing: 10% below highest month close",
            "Max hold: 4 weeks",
        ],
        protect_rules=[
            "Max position: 5% of portfolio only",
            "4 tranches: 30%/30%/25%/15%",
            "Macro cycle reversal → exit all immediately",
            "No leverage for major positions",
            "Monthly review mandatory",
            "Daily stop: -15.0%",
        ],
        color="#450a0a", badge="30%",
    ),
}

# Add 5% as an alias for clarity in UI (same as 5.0)
PROFIT_RANGE_OPTIONS_FULL = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 15, 20, 30]


# ══════════════════════════════════════════════════════════════
# STRATEGY SIGNAL GENERATOR PER RANGE
# ══════════════════════════════════════════════════════════════

def get_range_profile(target_pct: float) -> RangeProfile:
    """Get profile for exact or nearest target."""
    if target_pct in RANGE_PROFILES:
        return RANGE_PROFILES[target_pct]
    closest = min(RANGE_PROFILES.keys(), key=lambda x: abs(x - target_pct))
    return RANGE_PROFILES[closest]


@dataclass
class RangeSignal:
    direction:    str       # long | short | none
    confidence:   float
    target_pct:   float
    risk_pct:     float
    tp_pct:       float
    sl_pct:       float
    entry:        float
    sl:           float
    tp1:          float
    tp2:          float
    trailing_sl:  float
    hold_max_min: int
    style:        str
    reasons:      list[str]
    profile:      RangeProfile = field(repr=False)
    protect_active: list[str] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return (self.direction in ("long","short")
                and self.confidence >= self.profile.min_confidence
                and self.entry > 0
                and abs(self.sl - self.entry) > 0)


class RangeStrategyEngine:
    """
    Ultra-advanced strategy engine — one strategy per profit range.
    Each range has unique indicator logic, entry/exit rules,
    capital protection, and trade style.
    """

    def analyze(
        self,
        df,                           # pd.DataFrame with all indicators
        target_pct: float,
        pair:       str,
        asset_class: str = "crypto",
        macro_ctx:  dict = None,
        session:    str  = "new_york",
    ) -> RangeSignal:
        """
        Main entry: analyze market and return signal for given target %.
        Routes to appropriate strategy based on target_pct.
        """
        profile = get_range_profile(target_pct)
        macro   = macro_ctx or {}

        # Session filter
        if "any" not in profile.session_ok and session not in profile.session_ok:
            return self._no_signal(target_pct, profile, "wrong session")

        # Route to specific strategy
        if   target_pct <= 1.0:  return self._lightning_scalp(df, profile, pair)
        elif target_pct <= 2.0:  return self._pro_scalp(df, profile, pair)
        elif target_pct <= 3.0:  return self._momentum_burst(df, profile, pair)
        elif target_pct <= 4.0:  return self._breakout_rider(df, profile, pair)
        elif target_pct <= 5.0:  return self._trend_surfer(df, profile, pair)
        elif target_pct <= 6.0:  return self._fibonacci_swing(df, profile, pair)
        elif target_pct <= 7.0:  return self._smc_precision(df, profile, pair)
        elif target_pct <= 8.0:  return self._vwap_institutional(df, profile, pair)
        elif target_pct <= 9.0:  return self._multi_tf_confluence(df, profile, pair)
        elif target_pct <= 10.0: return self._full_swing(df, profile, pair)
        elif target_pct <= 15.0: return self._position_trade(df, profile, pair, macro)
        elif target_pct <= 20.0: return self._macro_swing(df, profile, pair, macro)
        else:                     return self._major_position(df, profile, pair, macro)

    # ── Helpers ──────────────────────────────────────────────

    def _g(self, row, key, default=0.0):
        try: return float(row.get(key, default) or default)
        except: return default

    def _make_signal(
        self, profile: RangeProfile, direction: str,
        confidence: float, entry: float, atr: float,
        pair: str, reasons: list[str],
        protect_active: list[str] = None,
    ) -> RangeSignal:
        sl_dist  = atr * profile.sl_multiplier
        tp1_dist = atr * profile.tp_multiplier * 0.5
        tp2_dist = atr * profile.tp_multiplier

        if direction == "long":
            sl  = entry - sl_dist
            tp1 = entry + tp1_dist
            tp2 = entry + tp2_dist
            trailing = entry + atr * profile.tp_multiplier * (profile.trailing_sl_pct / profile.target_pct)
        else:
            sl  = entry + sl_dist
            tp1 = entry - tp1_dist
            tp2 = entry - tp2_dist
            trailing = entry - atr * profile.tp_multiplier * (profile.trailing_sl_pct / profile.target_pct)

        return RangeSignal(
            direction=direction,
            confidence=min(97, confidence),
            target_pct=profile.target_pct,
            risk_pct=profile.risk_pct,
            tp_pct=profile.tp_pct,
            sl_pct=profile.risk_pct,
            entry=entry,
            sl=sl, tp1=tp1, tp2=tp2,
            trailing_sl=trailing,
            hold_max_min=profile.hold_max,
            style=profile.style,
            reasons=reasons,
            profile=profile,
            protect_active=protect_active or [],
        )

    def _no_signal(self, target_pct: float, profile: RangeProfile,
                    reason: str = "") -> RangeSignal:
        return RangeSignal(
            direction="none", confidence=0, target_pct=target_pct,
            risk_pct=profile.risk_pct, tp_pct=profile.tp_pct, sl_pct=profile.risk_pct,
            entry=0, sl=0, tp1=0, tp2=0, trailing_sl=0,
            hold_max_min=profile.hold_max, style=profile.style,
            reasons=[f"No signal: {reason}"], profile=profile,
        )

    # ── 1%: Lightning Scalp ──────────────────────────────────
    def _lightning_scalp(self, df, profile: RangeProfile, pair: str) -> RangeSignal:
        if df is None or len(df) < 10:
            return self._no_signal(1.0, profile, "no data")
        l     = df.iloc[-1]; p = df.iloc[-2]
        g     = self._g
        close = g(l,"close") or 1.0
        atr   = g(l,"atr") or close*0.005
        ema3  = g(l,"ema3", close); ema8 = g(l,"ema8", close)
        p_ema3= g(p,"ema3", close); p_ema8= g(p,"ema8", close)
        rsi   = g(l,"rsi", 50)
        hist  = g(l,"macd_hist"); p_hist = g(p,"macd_hist")
        vol_r = g(l,"vol_ratio", 1)
        bb_w  = (g(l,"bb_upper",close*1.02) - g(l,"bb_lower",close*0.98)) / (g(l,"bb_mid",close)+1e-9)

        bull_cross = ema3 > ema8 and p_ema3 <= p_ema8
        bear_cross = ema3 < ema8 and p_ema3 >= p_ema8
        rsi_ok_bull = 35 < rsi < 65
        rsi_ok_bear = 35 < rsi < 65
        hist_bull   = hist > 0 and hist > p_hist
        hist_bear   = hist < 0 and hist < p_hist
        vol_ok      = vol_r >= 1.5
        squeeze     = bb_w < 0.015

        score_bull = sum([bull_cross, rsi_ok_bull, hist_bull, vol_ok, squeeze])
        score_bear = sum([bear_cross, rsi_ok_bear, hist_bear, vol_ok, squeeze])

        if score_bull >= 4 and bull_cross:
            conf = 62 + score_bull*4 + (vol_r-1.5)*8
            return self._make_signal(profile, "long", conf, close, atr, pair,
                [f"EMA3/8 bull cross","RSI={rsi:.0f}","MACD hist up","vol={vol_r:.2f}x","BB squeeze={squeeze}"])
        if score_bear >= 4 and bear_cross:
            conf = 62 + score_bear*4 + (vol_r-1.5)*8
            return self._make_signal(profile, "short", conf, close, atr, pair,
                [f"EMA3/8 bear cross","RSI={rsi:.0f}","MACD hist down","vol={vol_r:.2f}x"])
        return self._no_signal(1.0, profile, f"score_bull={score_bull} score_bear={score_bear}")

    # ── 2%: Pro Scalp ★ ──────────────────────────────────────
    def _pro_scalp(self, df, profile: RangeProfile, pair: str) -> RangeSignal:
        if df is None or len(df) < 21:
            return self._no_signal(2.0, profile, "no data")
        l = df.iloc[-1]; p = df.iloc[-2]
        g = self._g
        close = g(l,"close") or 1.0; atr = g(l,"atr") or close*0.008
        ema8 = g(l,"ema8",close); ema21 = g(l,"ema21",close)
        p_ema8 = g(p,"ema8",close); p_ema21 = g(p,"ema21",close)
        rsi = g(l,"rsi",50); hist = g(l,"macd_hist"); p_hist = g(p,"macd_hist")
        vwap = g(l,"vwap",close); vol_r = g(l,"vol_ratio",1)

        bull_x = ema8>ema21 and p_ema8<=p_ema21
        bear_x = ema8<ema21 and p_ema8>=p_ema21
        rsi_bull = 40<rsi<60; rsi_bear = 40<rsi<60
        hist_bull = hist>0 and hist>p_hist; hist_bear = hist<0 and hist<p_hist
        near_vwap = abs(close-vwap)/vwap < 0.003
        vol_ok = vol_r>=1.3

        sb = sum([bull_x,rsi_bull,hist_bull,near_vwap,vol_ok])
        ss = sum([bear_x,rsi_bear,hist_bear,near_vwap,vol_ok])

        if sb>=4 and bull_x:
            conf = 64+sb*4+(vol_r-1.3)*10
            return self._make_signal(profile,"long",conf,close,atr,pair,
                [f"EMA8/21 bull","RSI={rsi:.0f}","MACD↑","near VWAP","vol={vol_r:.1f}x"])
        if ss>=4 and bear_x:
            conf = 64+ss*4+(vol_r-1.3)*10
            return self._make_signal(profile,"short",conf,close,atr,pair,
                [f"EMA8/21 bear","RSI={rsi:.0f}","MACD↓","near VWAP","vol={vol_r:.1f}x"])
        return self._no_signal(2.0,profile,f"bull={sb} bear={ss}")

    # ── 3%: Momentum Burst ───────────────────────────────────
    def _momentum_burst(self, df, profile: RangeProfile, pair: str) -> RangeSignal:
        if df is None or len(df) < 30:
            return self._no_signal(3.0, profile, "no data")
        l = df.iloc[-1]; p = df.iloc[-2]; pp = df.iloc[-3]
        g = self._g
        close = g(l,"close") or 1.0; atr = g(l,"atr") or close*0.012
        bb_u=g(l,"bb_upper",close*1.03); bb_l=g(l,"bb_lower",close*0.97); bb_m=g(l,"bb_mid",close)
        vol_r=g(l,"vol_ratio",1); rsi=g(l,"rsi",50)
        hist=g(l,"macd_hist"); p_hist=g(p,"macd_hist"); pp_hist=g(pp,"macd_hist")
        obv=g(l,"obv"); p_obv=g(p,"obv")
        atr_prev = (g(p,"atr",atr)+g(pp,"atr",atr))/2

        bb_w = (bb_u-bb_l)/(bb_m+1e-9)
        squeeze = bb_w < 0.02
        vol_surge = vol_r >= 2.0
        hist_accel_bull = hist > p_hist > pp_hist and hist > 0
        hist_accel_bear = hist < p_hist < pp_hist and hist < 0
        atr_expand = atr > atr_prev*1.3
        obv_bull = obv > p_obv; obv_bear = obv < p_obv

        sb = sum([squeeze, vol_surge, hist_accel_bull, atr_expand, obv_bull, rsi>50])
        ss = sum([squeeze, vol_surge, hist_accel_bear, atr_expand, obv_bear, rsi<50])

        if sb>=5 and squeeze and vol_surge:
            conf = 65+sb*3+(vol_r-2.0)*8
            return self._make_signal(profile,"long",conf,close,atr,pair,
                ["BB squeeze burst","vol surge","MACD accel","ATR expand","OBV bull"])
        if ss>=5 and squeeze and vol_surge:
            conf = 65+ss*3+(vol_r-2.0)*8
            return self._make_signal(profile,"short",conf,close,atr,pair,
                ["BB squeeze burst","vol surge","MACD accel","ATR expand","OBV bear"])
        return self._no_signal(3.0,profile,"no squeeze+burst")

    # ── 4%: Breakout Rider ───────────────────────────────────
    def _breakout_rider(self, df, profile: RangeProfile, pair: str) -> RangeSignal:
        if df is None or len(df) < 30:
            return self._no_signal(4.0, profile, "no data")
        l = df.iloc[-1]; g = self._g
        close = g(l,"close") or 1.0; atr = g(l,"atr") or close*0.015
        highs = [g(df.iloc[-i],"high",close) for i in range(2,25)]
        lows  = [g(df.iloc[-i],"low",close)  for i in range(2,25)]
        res = max(highs[:10]) if highs else close*1.02
        sup = min(lows[:10])  if lows  else close*0.98
        rsi=g(l,"rsi",50); stk_k=g(l,"stoch_k",50)
        vol_r=g(l,"vol_ratio",1); obv=g(l,"obv"); p_obv=g(df.iloc[-2],"obv",0)
        atr_prev=(g(df.iloc[-2],"atr",atr)+g(df.iloc[-3],"atr",atr))/2

        bull_break = close > res and close > res*(1+0.001)
        bear_break = close < sup and close < sup*(1-0.001)
        vol_confirm = vol_r >= 2.5
        rsi_bull = rsi > 55; rsi_bear = rsi < 45
        stk_bull = stk_k > 50; stk_bear = stk_k < 50
        atr_exp = atr > atr_prev*1.4
        obv_bull = obv > p_obv; obv_bear = obv < p_obv

        sb=sum([bull_break,vol_confirm,rsi_bull,stk_bull,atr_exp,obv_bull])
        ss=sum([bear_break,vol_confirm,rsi_bear,stk_bear,atr_exp,obv_bear])

        if sb>=5 and bull_break and vol_confirm:
            conf=66+sb*3+(vol_r-2.5)*6
            return self._make_signal(profile,"long",conf,close,atr,pair,
                [f"Break res={res:.4f}","vol={vol_r:.1f}x","RSI={rsi:.0f}","ATR expand"])
        if ss>=5 and bear_break and vol_confirm:
            conf=66+ss*3+(vol_r-2.5)*6
            return self._make_signal(profile,"short",conf,close,atr,pair,
                [f"Break sup={sup:.4f}","vol={vol_r:.1f}x","RSI={rsi:.0f}","ATR expand"])
        return self._no_signal(4.0,profile,"no breakout")

    # ── 5%: Trend Surfer ─────────────────────────────────────
    def _trend_surfer(self, df, profile: RangeProfile, pair: str) -> RangeSignal:
        if df is None or len(df) < 50:
            return self._no_signal(5.0, profile, "no data")
        l = df.iloc[-1]; g = self._g
        close=g(l,"close") or 1.0; atr=g(l,"atr") or close*0.018
        ema20=g(l,"ema20",close); ema50=g(l,"ema50",close); ema200=g(l,"ema200",close)
        adx=g(l,"adx",20); rsi=g(l,"rsi",50); hist=g(l,"macd_hist")
        p_hist=g(df.iloc[-2],"macd_hist")

        bull_stack = ema20>ema50>ema200; bear_stack = ema20<ema50<ema200
        strong_trend = adx > 25
        rsi_bull = 45<rsi<65; rsi_bear = 35<rsi<55
        pull_to_ema20_bull = 0<(close-ema20)/atr<1.5
        pull_to_ema20_bear = 0<(ema20-close)/atr<1.5
        macd_bull = hist>0 and hist>p_hist; macd_bear = hist<0 and hist<p_hist

        sb=sum([bull_stack,strong_trend,rsi_bull,pull_to_ema20_bull,macd_bull])
        ss=sum([bear_stack,strong_trend,rsi_bear,pull_to_ema20_bear,macd_bear])

        if sb>=4 and bull_stack and strong_trend:
            conf=67+sb*3+(adx-25)*1.5
            return self._make_signal(profile,"long",conf,close,atr,pair,
                [f"EMA stack bull","ADX={adx:.0f}","RSI={rsi:.0f}","pullback EMA20"])
        if ss>=4 and bear_stack and strong_trend:
            conf=67+ss*3+(adx-25)*1.5
            return self._make_signal(profile,"short",conf,close,atr,pair,
                [f"EMA stack bear","ADX={adx:.0f}","RSI={rsi:.0f}","pullback EMA20"])
        return self._no_signal(5.0,profile,f"ADX={adx:.0f} bull={sb} bear={ss}")

    # ── 6%: Fibonacci Swing ──────────────────────────────────
    def _fibonacci_swing(self, df, profile: RangeProfile, pair: str) -> RangeSignal:
        if df is None or len(df) < 50:
            return self._no_signal(6.0, profile, "no data")
        l = df.iloc[-1]; g = self._g
        close=g(l,"close") or 1.0; atr=g(l,"atr") or close*0.022
        highs=[g(df.iloc[-i],"high",close) for i in range(1,30)]
        lows =[g(df.iloc[-i],"low",close)  for i in range(1,30)]
        swing_h=max(highs) if highs else close*1.05
        swing_l=min(lows)  if lows  else close*0.95
        rng=swing_h-swing_l
        fib382=swing_h-rng*0.382; fib618=swing_h-rng*0.618
        rsi=g(l,"rsi",50); p_rsi=g(df.iloc[-3],"rsi",50)
        bb_l=g(l,"bb_lower",close*0.97); stk_k=g(l,"stoch_k",50)

        at_fib618_bull = abs(close-fib618)/atr < 0.8
        at_fib382_bull = abs(close-fib382)/atr < 0.8
        rsi_div_bull   = rsi>p_rsi and close<g(df.iloc[-3],"close",close)
        stk_os_bull    = stk_k<30; bb_low_bull = close<bb_l*1.01

        at_fib618_bear = abs(close-(swing_l+rng*0.618))/atr<0.8
        at_fib382_bear = abs(close-(swing_l+rng*0.382))/atr<0.8
        rsi_div_bear   = rsi<p_rsi and close>g(df.iloc[-3],"close",close)
        stk_ob_bear    = stk_k>70

        sb=sum([at_fib618_bull or at_fib382_bull, rsi_div_bull, stk_os_bull, bb_low_bull])
        ss=sum([at_fib618_bear or at_fib382_bear, rsi_div_bear, stk_ob_bear])

        if sb>=3 and (at_fib618_bull or at_fib382_bull):
            lev = "61.8%" if at_fib618_bull else "38.2%"
            conf=68+sb*4
            return self._make_signal(profile,"long",conf,close,atr,pair,
                [f"Fib {lev} bounce","RSI div","stoch OS={stk_k:.0f}"])
        if ss>=2 and (at_fib618_bear or at_fib382_bear):
            lev = "61.8%" if at_fib618_bear else "38.2%"
            conf=68+ss*4
            return self._make_signal(profile,"short",conf,close,atr,pair,
                [f"Fib {lev} rejection","RSI div","stoch OB={stk_k:.0f}"])
        return self._no_signal(6.0,profile,"no fib confluence")

    # ── 7%: SMC Precision ────────────────────────────────────
    def _smc_precision(self, df, profile: RangeProfile, pair: str) -> RangeSignal:
        if df is None or len(df) < 20:
            return self._no_signal(7.0, profile, "no data")
        l = df.iloc[-1]; g = self._g
        close=g(l,"close") or 1.0; atr=g(l,"atr") or close*0.025

        # Simplified SMC detection
        ob_bull_score=0; ob_bear_score=0
        for i in range(3, min(18,len(df))):
            c=df.iloc[-i]
            co=g(c,"open",0); cc=g(c,"close",0); cv=g(c,"vol_ratio",1)
            post_c=g(df.iloc[-(i-1)],"close",0)
            if cc<co and cv>1.2 and post_c>co*1.001: ob_bull_score+=1; break
            if cc>co and cv>1.2 and post_c<co*0.999: ob_bear_score+=1; break

        # FVG detection
        if len(df)>=3:
            c1=df.iloc[-3]; c3=df.iloc[-1]
            fvg_bull = g(c3,"low",0)>g(c1,"high",0)
            fvg_bear = g(c3,"high",0)<g(c1,"low",0)
        else: fvg_bull=fvg_bear=False

        # BOS
        rec_h=[g(df.iloc[-i],"high",0) for i in range(2,12)]
        rec_l=[g(df.iloc[-i],"low",0)  for i in range(2,12)]
        bos_bull = rec_h and close>max(rec_h)
        bos_bear = rec_l and close<min(rec_l)

        # Liquidity sweep
        prev_l=[g(df.iloc[-i],"low",0)  for i in range(2,8)]
        prev_h=[g(df.iloc[-i],"high",0) for i in range(2,8)]
        cur_l=g(l,"low",close); cur_h=g(l,"high",close)
        sweep_bull=prev_l and cur_l<min(prev_l) and close>min(prev_l)
        sweep_bear=prev_h and cur_h>max(prev_h) and close<max(prev_h)

        sb=sum([ob_bull_score>0, fvg_bull, bos_bull, sweep_bull])
        ss=sum([ob_bear_score>0, fvg_bear, bos_bear, sweep_bear])

        if sb>=3:
            conf=69+sb*5+(atr/close)*100
            return self._make_signal(profile,"long",conf,close,atr,pair,
                [f"OB={ob_bull_score}","FVG={fvg_bull}","BOS={bos_bull}","sweep={sweep_bull}"])
        if ss>=3:
            conf=69+ss*5+(atr/close)*100
            return self._make_signal(profile,"short",conf,close,atr,pair,
                [f"OB={ob_bear_score}","FVG={fvg_bear}","BOS={bos_bear}","sweep={sweep_bear}"])
        return self._no_signal(7.0,profile,f"SMC score bull={sb} bear={ss}")

    # ── 8-30%: Higher range strategies (simplified but complete) ─

    def _vwap_institutional(self, df, profile, pair):
        if df is None or len(df)<20: return self._no_signal(8.0,profile,"no data")
        l=df.iloc[-1]; g=self._g
        close=g(l,"close") or 1.0; atr=g(l,"atr") or close*0.028
        vwap=g(l,"vwap",close); bb_u=g(l,"bb_upper",close*1.02); bb_l=g(l,"bb_lower",close*0.98)
        std=(bb_u-bb_l)/4
        dev=(close-vwap)/(std+1e-9)
        cmf=g(l,"cmf"); rsi=g(l,"rsi",50)
        if dev<=-2.0 and rsi<40 and cmf<-0.1:
            return self._make_signal(profile,"long",70+(abs(dev)-2)*5,close,atr,pair,
                [f"VWAP dev={dev:.2f}σ","RSI={rsi:.0f}","CMF={cmf:.3f}"])
        if dev>=2.0 and rsi>60 and cmf>0.1:
            return self._make_signal(profile,"short",70+(dev-2)*5,close,atr,pair,
                [f"VWAP dev={dev:.2f}σ","RSI={rsi:.0f}","CMF={cmf:.3f}"])
        return self._no_signal(8.0,profile,f"VWAP dev={dev:.2f}")

    def _multi_tf_confluence(self, df, profile, pair):
        if df is None or len(df)<50: return self._no_signal(9.0,profile,"no data")
        l=df.iloc[-1]; g=self._g
        close=g(l,"close") or 1.0; atr=g(l,"atr") or close*0.032
        e20=g(l,"ema20",close); e50=g(l,"ema50",close); e200=g(l,"ema200",close)
        adx=g(l,"adx",20); rsi=g(l,"rsi",50); hist=g(l,"macd_hist")
        bull=(e20>e50>e200) and adx>25 and rsi>50 and hist>0
        bear=(e20<e50<e200) and adx>25 and rsi<50 and hist<0
        if bull:
            return self._make_signal(profile,"long",70+(adx-25)*1.5,close,atr,pair,
                ["4TF aligned bull",f"ADX={adx:.0f}","EMA stack"])
        if bear:
            return self._make_signal(profile,"short",70+(adx-25)*1.5,close,atr,pair,
                ["4TF aligned bear",f"ADX={adx:.0f}","EMA stack"])
        return self._no_signal(9.0,profile,"no TF confluence")

    def _full_swing(self, df, profile, pair):
        if df is None or len(df)<50: return self._no_signal(10.0,profile,"no data")
        l=df.iloc[-1]; g=self._g
        close=g(l,"close") or 1.0; atr=g(l,"atr") or close*0.035
        e50=g(l,"ema50",close); e200=g(l,"ema200",close)
        rsi=g(l,"rsi",50); adx=g(l,"adx",20); stk_k=g(l,"stoch_k",50)
        bull=(e50>e200) and adx>20 and 40<rsi<70 and stk_k>40
        bear=(e50<e200) and adx>20 and 30<rsi<60 and stk_k<60
        if bull:
            return self._make_signal(profile,"long",71+adx*0.5,close,atr,pair,
                ["Ichimoku/EMA swing bull",f"ADX={adx:.0f}","RSI={rsi:.0f}"])
        if bear:
            return self._make_signal(profile,"short",71+adx*0.5,close,atr,pair,
                ["Ichimoku/EMA swing bear",f"ADX={adx:.0f}","RSI={rsi:.0f}"])
        return self._no_signal(10.0,profile,"no swing setup")

    def _position_trade(self, df, profile, pair, macro):
        if df is None or len(df)<50: return self._no_signal(15.0,profile,"no data")
        l=df.iloc[-1]; g=self._g
        close=g(l,"close") or 1.0; atr=g(l,"atr") or close*0.05
        e50=g(l,"ema50",close); e200=g(l,"ema200",close)
        rsi=g(l,"rsi",50); adx=g(l,"adx",20)
        sent=macro.get("sentiment_score",0)
        bull=(e50>e200) and adx>15 and rsi<65 and sent>-0.2
        bear=(e50<e200) and adx>15 and rsi>35 and sent<0.2
        if bull:
            return self._make_signal(profile,"long",72+adx,close,atr,pair,
                ["MA position bull",f"ADX={adx:.0f}","macro favorable"])
        if bear:
            return self._make_signal(profile,"short",72+adx,close,atr,pair,
                ["MA position bear",f"ADX={adx:.0f}","macro favorable"])
        return self._no_signal(15.0,profile,"no position setup")

    def _macro_swing(self, df, profile, pair, macro):
        if df is None or len(df)<50: return self._no_signal(20.0,profile,"no data")
        l=df.iloc[-1]; g=self._g
        close=g(l,"close") or 1.0; atr=g(l,"atr") or close*0.07
        dxy=macro.get("dxy_trend","neutral"); vix=macro.get("vix_level",20)
        rsi=g(l,"rsi",50); e200=g(l,"ema200",close)
        bull=(close>e200) and dxy=="falling" and vix<25 and rsi<65
        bear=(close<e200) and dxy=="rising"  and vix>30 and rsi>35
        if bull:
            return self._make_signal(profile,"long",73,close,atr,pair,
                ["Macro swing bull","DXY falling","VIX moderate"])
        if bear:
            return self._make_signal(profile,"short",73,close,atr,pair,
                ["Macro swing bear","DXY rising","VIX elevated"])
        return self._no_signal(20.0,profile,"no macro setup")

    def _major_position(self, df, profile, pair, macro):
        if df is None or len(df)<50: return self._no_signal(30.0,profile,"no data")
        l=df.iloc[-1]; g=self._g
        close=g(l,"close") or 1.0; atr=g(l,"atr") or close*0.10
        rsi=g(l,"rsi",50); e200=g(l,"ema200",close)
        infla=macro.get("inflation_regime","moderate")
        bull=(close>e200) and rsi<70 and infla=="high"
        bear=(close<e200) and rsi>30
        if bull:
            return self._make_signal(profile,"long",75,close,atr,pair,
                ["Major position bull","above MA200","inflation regime"])
        if bear:
            return self._make_signal(profile,"short",75,close,atr,pair,
                ["Major position bear","below MA200"])
        return self._no_signal(30.0,profile,"no major setup")


# ── Capital Protection per Trade ──────────────────────────────

def get_capital_protection_rules(target_pct: float, balance: float) -> dict:
    """Return specific capital protection parameters for a trade target."""
    p = get_range_profile(target_pct)
    max_trade_size  = balance * (p.risk_pct / 100)
    daily_stop_usd  = balance * (p.daily_stop_pct / 100)
    return {
        "max_trade_size_usd":    round(max_trade_size, 2),
        "daily_stop_usd":        round(daily_stop_usd, 2),
        "daily_stop_pct":        p.daily_stop_pct,
        "max_concurrent":        3 if target_pct <= 3 else (2 if target_pct <= 10 else 1),
        "loss_pause_after":      2,
        "scale_in_allowed":      p.scale_in_ok,
        "trailing_sl_at_pct":    p.trailing_sl_pct,
        "hold_max_min":          p.hold_max,
        "min_confidence":        p.min_confidence,
        "emergency_close_mult":  2.0,   # Close if loss > 2× SL
        "style":                 p.style,
        "style_label":           p.style_label,
    }


# Singleton
range_strategy_engine = RangeStrategyEngine()
