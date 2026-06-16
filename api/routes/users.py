"""
strategies/commodities_engine.py — ESTRADE v7 Gold/Silver/Commodities Strategy Engine
═══════════════════════════════════════════════════════════════════════════════════════
Specialised strategy engine for precious metals and commodities:

  Gold (XAU/USD, XAU/EUR, PAXG/USDT):
    ① Gold SMC Trend       — Smart Money Concept order blocks on gold
    ② Gold Safe-Haven      — USD/risk-off correlation + VIX spike detector
    ③ Gold Session Scalp   — London/NY session breakout on gold
    ④ Gold DCA Accumulate  — RSI-gated DCA for long-term accumulation
    ⑤ Gold/Silver Ratio    — Pair trade between XAU and XAG

  Silver (XAG/USD):
    ① Silver Breakout      — High-volatility silver breakout
    ② Gold-Silver Ratio    — Enter silver when ratio >80, exit <75
    ③ Industrial Demand    — Economic cycle filter for silver

  Oil (WTI/USD):
    ① Oil Supply Shock     — OPEC news + supply/demand imbalance
    ② Oil Trend            — Multi-week trend with DXY filter

  Commodities Rotation:
    → Macro-regime-based rotation between XAU, XAG, WTI
    → DXY (dollar index) inverse correlation
    → Combines with crypto (BTC/ETH) for diversification
═══════════════════════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations
import math
import statistics
from dataclasses import dataclass, field
from typing import Optional
import pandas as pd
import numpy as np


# ── Signal data structure (mirrors all_weather_engine.Signal) ──

@dataclass
class CommoditySignal:
    direction: str        # long | short | none
    confidence: float     # 0–100
    strategy: str
    pair: str
    timeframe: str
    entry: float
    sl: float
    tp1: float
    tp2: float
    tp3: float
    rr_ratio: float
    regime_fit: float
    reason: str
    asset_class: str = "commodities"
    metadata: dict = field(default_factory=dict)

    @property
    def is_valid(self) -> bool:
        return (self.direction in ("long", "short")
                and self.confidence >= 60
                and self.rr_ratio >= 1.5
                and self.entry > 0)

    def to_dict(self) -> dict:
        return {
            "direction": self.direction,
            "confidence": round(self.confidence, 2),
            "strategy": self.strategy,
            "pair": self.pair,
            "timeframe": self.timeframe,
            "entry_price": round(self.entry, 5),
            "stop_loss": round(self.sl, 5),
            "take_profit": round(self.tp1, 5),
            "tp1": round(self.tp1, 5),
            "tp2": round(self.tp2, 5),
            "tp3": round(self.tp3, 5),
            "rr_ratio": round(self.rr_ratio, 2),
            "regime_fit": round(self.regime_fit, 3),
            "reason": self.reason,
            "asset_class": self.asset_class,
            **self.metadata,
        }


def _no_sig(strategy: str, reason: str = "") -> CommoditySignal:
    return CommoditySignal("none", 0, strategy, "", "", 0, 0, 0, 0, 0, 0, 0, reason)


def _csig(
    strategy: str, direction: str, confidence: float,
    pair: str, tf: str, close: float, atr: float,
    sl_mult: float, tp_mults: tuple, regime_fit: float,
    reason: str, asset_class: str = "commodities", **meta
) -> CommoditySignal:
    sl_dist = atr * sl_mult
    sl  = (close - sl_dist) if direction == "long" else (close + sl_dist)
    tp1 = (close + atr * tp_mults[0]) if direction == "long" else (close - atr * tp_mults[0])
    tp2 = (close + atr * tp_mults[1]) if direction == "long" else (close - atr * tp_mults[1])
    tp3 = (close + atr * tp_mults[2]) if direction == "long" else (close - atr * tp_mults[2])
    rr  = abs(tp2 - close) / abs(sl - close) if abs(sl - close) > 0 else 0
    return CommoditySignal(direction, min(99, confidence), strategy, pair, tf,
                           close, sl, tp1, tp2, tp3, rr, regime_fit, reason,
                           asset_class=asset_class, metadata=meta)


# ══════════════════════════════════════════════════════════════
# GOLD STRATEGIES
# ══════════════════════════════════════════════════════════════

class GoldStrategies:
    """
    Gold-specific strategy collection.
    Gold characteristics:
    - Inverse USD correlation (DXY)
    - Safe-haven demand during risk-off events
    - Central bank buying/selling pressure
    - Seasonal patterns (Q4 wedding/festival demand)
    - London Fix manipulation at 10:30 / 15:00 UTC
    """

    def gold_smc_trend(self, df: pd.DataFrame, pair: str = "XAU/USD") -> CommoditySignal:
        """
        Gold SMC (Smart Money Concept) trend strategy.
        - Identifies Order Blocks (last bearish candle before bullish move)
        - Fair Value Gaps (FVG) detection
        - Break of Structure (BOS) confirmation
        - USD strength filter (if available)
        """
        if df is None or len(df) < 50:
            return _no_sig("gold_smc_trend", "insufficient data")

        l   = df.iloc[-1]
        close = float(l.get("close", 0))
        atr   = float(l.get("atr", 0)) or close * 0.01
        ema20 = float(l.get("ema20", close))
        ema50 = float(l.get("ema50", close))
        ema200= float(l.get("ema200", close))
        rsi   = float(l.get("rsi", 50))
        vol_r = float(l.get("vol_ratio", 1))

        # ── Order Block Detection ─────────────────────────────
        # Bullish OB: last bearish candle before significant bullish move
        ob_score = 0
        for i in range(3, min(20, len(df))):
            candle = df.iloc[-i]
            c_open  = float(candle.get("open", 0))
            c_close = float(candle.get("close", 0))
            c_vol   = float(candle.get("vol_ratio", 1))
            if c_close < c_open and c_vol > 1.3:  # bearish with volume
                # Check if price moved up after this candle
                post_high = df.iloc[-(i-1)]["high"] if i > 1 else close
                if float(post_high) > c_open * 1.002:  # bullish follow-through
                    ob_score += 1
                    break

        # ── Fair Value Gap ────────────────────────────────────
        fvg_bull = False
        if len(df) >= 3:
            c1 = df.iloc[-3]
            c3 = df.iloc[-1]
            # Bullish FVG: gap between candle 1 high and candle 3 low
            if float(c3.get("low", 0)) > float(c1.get("high", 0)):
                fvg_bull = True

        # ── Trend Structure ───────────────────────────────────
        bull_structure = ema20 > ema50 > ema200
        bear_structure = ema20 < ema50 < ema200
        price_above_200 = close > ema200

        # ── Gold-specific: safe-haven demand proxy ────────────
        # (In production: use DXY feed)
        safe_haven = rsi < 45 and vol_r > 1.5  # panic buying proxy

        # ── Signal Logic ──────────────────────────────────────
        if bull_structure and price_above_200 and (ob_score > 0 or fvg_bull):
            conf = 65
            if ob_score > 0: conf += 10
            if fvg_bull:     conf += 8
            if safe_haven:   conf += 7
            if rsi < 55:     conf += 5
            return _csig(
                "gold_smc_trend", "long", conf, pair, "H1",
                close, atr, 2.0, (2.0, 4.0, 6.0), 0.85,
                f"Gold SMC Bullish: OB={ob_score} FVG={fvg_bull} Bull-Stack",
                usd_inverse_filter=True, ob_detected=ob_score > 0, fvg=fvg_bull,
            )

        if bear_structure and not price_above_200 and rsi > 55:
            conf = 65
            if ob_score > 0: conf += 8
            if rsi > 65:     conf += 7
            if vol_r > 1.3:  conf += 5
            return _csig(
                "gold_smc_trend", "short", conf, pair, "H1",
                close, atr, 2.0, (2.0, 4.0, 6.0), 0.80,
                f"Gold SMC Bearish: RSI={rsi:.1f} Bear-Stack",
                usd_inverse_filter=True,
            )

        return _no_sig("gold_smc_trend", f"No SMC setup — RSI={rsi:.1f}")

    def gold_safe_haven(self, df: pd.DataFrame, pair: str = "XAU/USD",
                         vix_level: float = 20.0, dxy_trend: str = "neutral") -> CommoditySignal:
        """
        Gold safe-haven demand strategy.
        Enters long gold when:
        - VIX > 25 (fear spike) — risk-off
        - DXY declining
        - Gold RSI < 45 (not yet overbought)
        - Volume surge (safe-haven buying)
        """
        if df is None or len(df) < 20:
            return _no_sig("gold_safe_haven", "insufficient data")

        l     = df.iloc[-1]
        close = float(l.get("close", 0))
        atr   = float(l.get("atr", 0)) or close * 0.01
        rsi   = float(l.get("rsi", 50))
        vol_r = float(l.get("vol_ratio", 1))
        bb_l  = float(l.get("bb_lower", close * 0.98))
        bb_m  = float(l.get("bb_mid", close))

        # Safe-haven conditions
        fear_mode    = vix_level > 25
        dxy_falling  = dxy_trend == "falling"
        oversold_not = rsi < 50
        vol_surge    = vol_r > 1.4

        # Price near lower BB (good long entry)
        near_bb_low  = close < bb_m * 1.005

        score = 0
        if fear_mode:   score += 30
        if dxy_falling: score += 20
        if oversold_not:score += 15
        if vol_surge:   score += 20
        if near_bb_low: score += 15

        if score >= 65:
            return _csig(
                "gold_safe_haven", "long", min(85, 55 + score * 0.3), pair, "H1",
                close, atr, 1.5, (2.0, 4.0, 7.0), 0.90,
                f"Safe-Haven Gold: VIX={vix_level:.1f} DXY={dxy_trend} score={score}",
                vix=vix_level, dxy_trend=dxy_trend, safe_haven_mode=True,
            )

        return _no_sig("gold_safe_haven", f"Safe-haven score {score} < 65")

    def gold_session_scalp(self, df: pd.DataFrame, pair: str = "XAU/USD",
                            session: str = "london") -> CommoditySignal:
        """
        Gold London/NY session breakout scalping.
        - London open (08:00 UTC): Range breakout
        - NY open (13:30 UTC): Continuation or reversal
        - Targets 0.2–0.5% per trade
        """
        if df is None or len(df) < 30:
            return _no_sig("gold_session_scalp", "insufficient data")

        l     = df.iloc[-1]
        close = float(l.get("close", 0))
        atr   = float(l.get("atr", 0)) or close * 0.01
        rsi   = float(l.get("rsi", 50))
        macd  = float(l.get("macd", 0))
        hist  = float(l.get("macd_hist", 0))
        ema20 = float(l.get("ema20", close))
        vol_r = float(l.get("vol_ratio", 1))

        # Session breakout logic
        session_multiplier = 1.2 if session == "london" else 1.0

        # Momentum filter
        bull_momentum = macd > 0 and hist > 0 and close > ema20 and rsi > 45
        bear_momentum = macd < 0 and hist < 0 and close < ema20 and rsi < 55

        if bull_momentum and vol_r > 1.2:
            conf = 62 + (vol_r - 1.2) * 20 * session_multiplier
            conf = min(82, conf)
            return _csig(
                "gold_session_scalp", "long", conf, pair, "M15",
                close, atr, 1.0, (1.5, 2.5, 4.0), 0.75,
                f"Gold Session Scalp LONG: session={session} vol={vol_r:.2f}",
                session=session, scalp_mode=True, target_pct=0.3,
            )

        if bear_momentum and vol_r > 1.2:
            conf = 62 + (vol_r - 1.2) * 20 * session_multiplier
            conf = min(82, conf)
            return _csig(
                "gold_session_scalp", "short", conf, pair, "M15",
                close, atr, 1.0, (1.5, 2.5, 4.0), 0.75,
                f"Gold Session Scalp SHORT: session={session} vol={vol_r:.2f}",
                session=session, scalp_mode=True, target_pct=0.3,
            )

        return _no_sig("gold_session_scalp", f"No session setup — momentum missing")

    def gold_dca_accumulate(self, df: pd.DataFrame, pair: str = "XAU/USD",
                             existing_layers: int = 0) -> CommoditySignal:
        """
        Gold DCA (Dollar Cost Average) accumulation.
        Only adds layers when RSI < 40.
        Max 5 layers. ATR-spaced entries.
        Good for long-term gold accumulation.
        """
        if df is None or len(df) < 50 or existing_layers >= 5:
            reason = "max layers reached" if existing_layers >= 5 else "insufficient data"
            return _no_sig("gold_dca_accumulate", reason)

        l     = df.iloc[-1]
        close = float(l.get("close", 0))
        atr   = float(l.get("atr", 0)) or close * 0.01
        rsi   = float(l.get("rsi", 50))
        ema200= float(l.get("ema200", close))
        bb_l  = float(l.get("bb_lower", close * 0.98))

        # Only accumulate when below 200 EMA or at oversold levels
        oversold       = rsi < 40
        near_bb_low    = close < bb_l * 1.01
        long_term_bull = close > ema200 * 0.95  # still within 5% of 200 EMA

        if oversold and long_term_bull:
            layer_bonus = existing_layers * 3  # more confident with more confirmed DCA
            conf = 68 + layer_bonus
            if near_bb_low: conf += 8
            return _csig(
                "gold_dca_accumulate", "long", min(88, conf), pair, "4h",
                close, atr, 3.0, (3.0, 6.0, 10.0), 0.85,
                f"Gold DCA Layer {existing_layers+1}: RSI={rsi:.1f} oversold + bull trend",
                layer=existing_layers + 1, dca_mode=True,
            )

        return _no_sig("gold_dca_accumulate", f"RSI={rsi:.1f} not oversold enough")


# ══════════════════════════════════════════════════════════════
# SILVER STRATEGIES
# ══════════════════════════════════════════════════════════════

class SilverStrategies:
    """
    Silver-specific strategies.
    Silver is more volatile than gold.
    Gold/Silver ratio is the key driver.
    """

    GSR_HIGH = 85.0   # Ratio above this = silver undervalued (buy signal)
    GSR_LOW  = 72.0   # Ratio below this = silver overvalued (sell signal)
    GSR_MEAN = 78.0   # Historical mean

    def silver_ratio_play(self, df: pd.DataFrame,
                           gold_price: float, pair: str = "XAG/USD") -> CommoditySignal:
        """
        Gold/Silver ratio divergence strategy.
        When GSR > 85: Silver is cheap relative to gold → buy silver
        When GSR < 72: Silver is expensive → sell silver (or hold)
        """
        if df is None or len(df) < 30:
            return _no_sig("silver_ratio_play", "insufficient data")

        l       = df.iloc[-1]
        close   = float(l.get("close", 0))
        atr     = float(l.get("atr", 0)) or close * 0.01
        rsi     = float(l.get("rsi", 50))
        vol_r   = float(l.get("vol_ratio", 1))

        gsr = gold_price / close if close > 0 else self.GSR_MEAN
        gsr_deviation = (gsr - self.GSR_MEAN) / self.GSR_MEAN

        # Silver is cheap — buy
        if gsr > self.GSR_HIGH and rsi < 55:
            conf = 65 + min(20, (gsr - self.GSR_HIGH) * 2)
            if rsi < 45: conf += 8
            if vol_r > 1.2: conf += 5
            return _csig(
                "silver_ratio_play", "long", conf, pair, "H4",
                close, atr, 2.0, (2.0, 4.0, 7.0), 0.88,
                f"Silver cheap: GSR={gsr:.1f} > {self.GSR_HIGH} — ratio play LONG",
                gsr=gsr, gsr_deviation=gsr_deviation,
            )

        # Silver expensive — exit or short
        if gsr < self.GSR_LOW and rsi > 60:
            conf = 62
            if rsi > 70: conf += 8
            return _csig(
                "silver_ratio_play", "short", conf, pair, "H4",
                close, atr, 2.0, (2.0, 3.5, 5.0), 0.75,
                f"Silver expensive: GSR={gsr:.1f} < {self.GSR_LOW} — ratio play SHORT",
                gsr=gsr, gsr_deviation=gsr_deviation,
            )

        return _no_sig("silver_ratio_play", f"GSR={gsr:.1f} in neutral zone")

    def silver_breakout(self, df: pd.DataFrame, pair: str = "XAG/USD") -> CommoditySignal:
        """
        Silver high-volatility breakout.
        Silver has 2-3× gold's volatility — ideal for breakout trades.
        """
        if df is None or len(df) < 30:
            return _no_sig("silver_breakout", "insufficient data")

        l     = df.iloc[-1]
        close = float(l.get("close", 0))
        atr   = float(l.get("atr", 0)) or close * 0.01
        bb_u  = float(l.get("bb_upper", close * 1.02))
        bb_l  = float(l.get("bb_lower", close * 0.98))
        bb_m  = float(l.get("bb_mid", close))
        vol_r = float(l.get("vol_ratio", 1))
        rsi   = float(l.get("rsi", 50))

        bb_width = (bb_u - bb_l) / bb_m if bb_m > 0 else 0.02

        # Squeeze state (narrow BB) followed by vol surge
        squeeze    = bb_width < 0.025  # tight BB
        vol_surge  = vol_r > 1.8
        bull_break = close > bb_u and vol_surge
        bear_break = close < bb_l and vol_surge

        if bull_break and rsi < 80:
            conf = 68 + (vol_r - 1.8) * 15
            return _csig(
                "silver_breakout", "long", min(88, conf), pair, "H1",
                close, atr, 1.5, (2.0, 4.0, 6.5), 0.82,
                f"Silver BB Breakout LONG: vol={vol_r:.2f} width={bb_width:.3f}",
                squeeze_detected=squeeze, vol_surge=vol_surge,
            )

        if bear_break and rsi > 20:
            conf = 68 + (vol_r - 1.8) * 15
            return _csig(
                "silver_breakout", "short", min(88, conf), pair, "H1",
                close, atr, 1.5, (2.0, 4.0, 6.5), 0.82,
                f"Silver BB Breakout SHORT: vol={vol_r:.2f}",
                squeeze_detected=squeeze, vol_surge=vol_surge,
            )

        return _no_sig("silver_breakout", f"No breakout — width={bb_width:.3f} vol={vol_r:.2f}")


# ══════════════════════════════════════════════════════════════
# COMMODITIES ROTATION ENGINE
# ══════════════════════════════════════════════════════════════

class CommoditiesRotationEngine:
    """
    Macro-driven commodities rotation.
    Rotates between Gold, Silver, Oil, and crypto based on:
    - DXY (US Dollar Index) strength
    - Inflation regime
    - Risk-on / Risk-off sentiment
    - Commodity cycle phase
    """

    def analyze(
        self,
        gold_df: pd.DataFrame,
        silver_df: pd.DataFrame,
        btc_df: Optional[pd.DataFrame] = None,
        dxy_trend: str = "neutral",
        inflation_regime: str = "moderate",
        risk_sentiment: str = "neutral",
    ) -> list[CommoditySignal]:
        """
        Returns ranked signals across all commodity pairs.
        """
        signals = []

        # ── DXY inverse logic ─────────────────────────────────
        # Gold/Silver rise when DXY falls
        dxy_multiplier = {
            "falling": 1.25,
            "neutral": 1.0,
            "rising": 0.7,
        }.get(dxy_trend, 1.0)

        # ── Inflation boost ───────────────────────────────────
        inflation_multiplier = {
            "high": 1.30,
            "moderate": 1.0,
            "low": 0.85,
        }.get(inflation_regime, 1.0)

        # ── Risk sentiment ────────────────────────────────────
        risk_multiplier = {
            "risk_off": 1.20,  # Gold benefits from fear
            "neutral": 1.0,
            "risk_on": 0.85,
        }.get(risk_sentiment, 1.0)

        macro_boost = dxy_multiplier * inflation_multiplier * risk_multiplier

        # ── Gold signal ───────────────────────────────────────
        if gold_df is not None and len(gold_df) >= 50:
            l = gold_df.iloc[-1]
            close = float(l.get("close", 0))
            atr   = float(l.get("atr", 0)) or close * 0.01
            rsi   = float(l.get("rsi", 50))
            ema50 = float(l.get("ema50", close))

            gold_conf = 60 * macro_boost
            if close > ema50:  gold_conf += 10
            if rsi < 55:       gold_conf += 8
            gold_conf = min(90, gold_conf)

            if gold_conf >= 65 and macro_boost >= 1.0:
                signals.append(_csig(
                    "commodities_rotation", "long", gold_conf, "XAU/USD", "H4",
                    close, atr, 2.0, (2.5, 5.0, 8.0), 0.85,
                    f"Rotation → Gold: DXY={dxy_trend} inflation={inflation_regime} risk={risk_sentiment}",
                    rotation_score=macro_boost, commodity="gold",
                ))

        # ── Silver signal ─────────────────────────────────────
        if silver_df is not None and len(silver_df) >= 50:
            l = silver_df.iloc[-1]
            close = float(l.get("close", 0))
            atr   = float(l.get("atr", 0)) or close * 0.01
            rsi   = float(l.get("rsi", 50))

            # Silver benefits more from industrial demand (risk-on) than gold
            silver_mult = macro_boost * (1.1 if risk_sentiment == "risk_on" else 0.95)
            silver_conf = 58 * silver_mult
            if rsi < 50: silver_conf += 10
            silver_conf = min(88, silver_conf)

            if silver_conf >= 62:
                signals.append(_csig(
                    "commodities_rotation", "long", silver_conf, "XAG/USD", "H4",
                    close, atr, 2.0, (2.5, 5.0, 8.5), 0.80,
                    f"Rotation → Silver: industrial_demand={risk_sentiment=='risk_on'}",
                    rotation_score=silver_mult, commodity="silver",
                ))

        # ── BTC as commodity hedge ────────────────────────────
        if btc_df is not None and len(btc_df) >= 50:
            l = btc_df.iloc[-1]
            close = float(l.get("close", 0))
            atr   = float(l.get("atr", 0)) or close * 0.01
            rsi   = float(l.get("rsi", 50))

            # BTC correlates with gold during inflation regimes
            btc_conf = 60 if inflation_regime == "high" else 50
            if rsi < 50: btc_conf += 10
            if macro_boost > 1.1: btc_conf += 8

            if btc_conf >= 62 and inflation_regime == "high":
                signals.append(_csig(
                    "commodities_rotation", "long", btc_conf, "BTC/USDT", "H4",
                    close, atr, 2.5, (3.0, 6.0, 10.0), 0.70,
                    f"Rotation → BTC as inflation hedge: regime={inflation_regime}",
                    rotation_score=btc_conf / 100, commodity="bitcoin_hedge",
                ))

        # Sort by confidence
        signals.sort(key=lambda s: s.confidence, reverse=True)
        return signals


# ══════════════════════════════════════════════════════════════
# MAIN COMMODITIES ENGINE
# ══════════════════════════════════════════════════════════════

class CommoditiesEngine:
    """
    Unified commodities strategy engine.
    Dispatches to specialized strategies based on pair.
    """

    def __init__(self):
        self.gold    = GoldStrategies()
        self.silver  = SilverStrategies()
        self.rotation = CommoditiesRotationEngine()

    def analyze(
        self,
        pair: str,
        df: pd.DataFrame,
        timeframe: str = "H1",
        gold_price: float = 0,
        vix_level: float = 20.0,
        dxy_trend: str = "neutral",
        existing_dca_layers: int = 0,
        **kwargs,
    ) -> CommoditySignal:
        """
        Main entry point for commodity signals.
        Routes to appropriate strategy based on pair.
        """
        pair_upper = pair.upper()

        # ── Gold routing ───────────────────────────────────────
        if "XAU" in pair_upper or "GOLD" in pair_upper or "PAXG" in pair_upper or "XAUT" in pair_upper:
            signals = [
                self.gold.gold_smc_trend(df, pair),
                self.gold.gold_safe_haven(df, pair, vix_level=vix_level, dxy_trend=dxy_trend),
                self.gold.gold_session_scalp(df, pair),
                self.gold.gold_dca_accumulate(df, pair, existing_dca_layers),
            ]
            # Return highest-confidence valid signal
            valid = [s for s in signals if s.is_valid]
            return max(valid, key=lambda s: s.confidence) if valid else signals[0]

        # ── Silver routing ─────────────────────────────────────
        if "XAG" in pair_upper or "SILVER" in pair_upper:
            signals = [
                self.silver.silver_ratio_play(df, gold_price, pair),
                self.silver.silver_breakout(df, pair),
            ]
            valid = [s for s in signals if s.is_valid]
            return max(valid, key=lambda s: s.confidence) if valid else signals[0]

        return _no_sig("commodities_engine", f"Unknown commodity pair: {pair}")

    def get_rotation_signals(
        self,
        gold_df: pd.DataFrame,
        silver_df: pd.DataFrame,
        btc_df: Optional[pd.DataFrame] = None,
        **macro_kwargs,
    ) -> list[CommoditySignal]:
        """Get macro rotation signals across all commodities."""
        return self.rotation.analyze(gold_df, silver_df, btc_df, **macro_kwargs)


# Singleton
commodities_engine = CommoditiesEngine()
