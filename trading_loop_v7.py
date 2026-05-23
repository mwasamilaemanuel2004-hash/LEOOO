"""
ai/indicator_engine.py — ESTRADE v6 Layered Indicator Engine
══════════════════════════════════════════════════════════════════════════
Eliminates overlapping by organizing indicators into 5 non-redundant layers.
Each layer asks a DIFFERENT question. No two indicators answer the same thing.

LAYER 1 — TREND DIRECTION (What direction is price moving?)
  → EMA Stack (8/21/55/200) + SuperTrend + Ichimoku Cloud
  → Output: trend_score -1 to +1, trend_strength 0-100

LAYER 2 — MOMENTUM QUALITY (How strong is the move?)
  → RSI(14) + MACD Histogram + ADX + Rate-of-Change
  → Output: momentum_score -1 to +1, momentum_strength 0-100

LAYER 3 — MEAN REVERSION (Is price overextended?)
  → Bollinger %B + Stochastic + Williams%R + CCI
  → Output: reversion_score -1 to +1 (negative=buy, positive=sell)

LAYER 4 — VOLUME CONFIRMATION (Is the move backed by volume?)
  → OBV trend + VWAP position + CMF + Volume ratio
  → Output: volume_confirm 0-1 (0=no confirm, 1=strong confirm)

LAYER 5 — MARKET STRUCTURE (Where is price in the big picture?)
  → Pivot Points + Fibonacci + Keltner breakout + Parabolic SAR
  → Output: structure_bias -1 to +1

FINAL DECISION:
  → Weighted blend of all 5 layers
  → Conflict detector: penalizes contradicting layers
  → Minimum 3/5 layer agreement required for high-confidence signal
══════════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from dataclasses import dataclass, asdict
from typing import Optional


# ═══════════════════════════════════════════════════════════════
# SHARED MATH HELPERS (used across layers)
# ═══════════════════════════════════════════════════════════════

def _ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()

def _sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n).mean()

def _rsi(s: pd.Series, n: int = 14) -> pd.Series:
    d = s.diff()
    g = d.clip(lower=0).ewm(span=n, adjust=False).mean()
    l = (-d.clip(upper=0)).ewm(span=n, adjust=False).mean()
    return 100 - 100 / (1 + g / l.replace(0, 1e-9))

def _atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    h, lo, c = df["high"], df["low"], df["close"]
    tr = pd.concat([h-lo, (h-c.shift()).abs(), (lo-c.shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(span=n, adjust=False).mean()

def _safe(val, default=0.0):
    try:
        v = float(val)
        return default if np.isnan(v) or np.isinf(v) else v
    except Exception:
        return default


# ═══════════════════════════════════════════════════════════════
# LAYER RESULT
# ═══════════════════════════════════════════════════════════════

@dataclass
class LayerResult:
    layer_id: int
    name: str
    score: float          # -1 to +1  (positive=bullish)
    strength: float       # 0 to 100  (confidence in the signal)
    signals: dict         # individual indicator values
    bias: str             # BULL | BEAR | NEUTRAL

    @property
    def weighted_score(self) -> float:
        return self.score * (self.strength / 100)

    def to_dict(self) -> dict:
        return asdict(self)


# ═══════════════════════════════════════════════════════════════
# LAYER 1 — TREND DIRECTION
# ═══════════════════════════════════════════════════════════════

class TrendLayer:
    """
    Answers: WHAT DIRECTION is the market trending?
    Uses: EMA Stack · SuperTrend · Ichimoku Cloud
    Non-overlapping: measures structural trend, NOT momentum speed
    """
    ID, NAME = 1, "Trend Direction"

    def compute(self, df: pd.DataFrame) -> LayerResult:
        if len(df) < 60:
            return LayerResult(self.ID, self.NAME, 0, 0, {}, "NEUTRAL")
        c = df["close"]
        e8   = _safe(_ema(c, 8).iloc[-1])
        e21  = _safe(_ema(c, 21).iloc[-1])
        e55  = _safe(_ema(c, 55).iloc[-1])
        e200 = _safe(_ema(c, 200).iloc[-1]) if len(df) >= 200 else _safe(_ema(c, len(df)-1).iloc[-1])
        cl   = _safe(c.iloc[-1])

        # EMA Stack scoring (each alignment worth 0.25)
        stack = 0
        if e8 > e21:  stack += 0.25
        if e21 > e55: stack += 0.25
        if e55 > e200: stack += 0.25
        if cl > e8:   stack += 0.25
        ema_score = (stack - 0.5) * 2   # -1 to +1

        # SuperTrend (ATR-based)
        atr = _safe(_atr(df, 10).iloc[-1])
        hl2 = (df["high"] + df["low"]) / 2
        st_upper = _safe(hl2.iloc[-1]) + 3 * atr
        st_lower = _safe(hl2.iloc[-1]) - 3 * atr
        st_score = 1.0 if cl > st_lower else -1.0

        # Ichimoku (simplified)
        h9  = df["high"].rolling(9).max().iloc[-1]
        l9  = df["low"].rolling(9).min().iloc[-1]
        h26 = df["high"].rolling(26).max().iloc[-1]
        l26 = df["low"].rolling(26).min().iloc[-1]
        h52 = df["high"].rolling(min(52, len(df))).max().iloc[-1]
        l52 = df["low"].rolling(min(52, len(df))).min().iloc[-1]
        tenkan = _safe((h9 + l9) / 2)
        kijun  = _safe((h26 + l26) / 2)
        span_a = (tenkan + kijun) / 2
        span_b = _safe((h52 + l52) / 2)
        cloud_top = max(span_a, span_b)
        cloud_bot = min(span_a, span_b)
        if cl > cloud_top:    ichi_score = 1.0
        elif cl < cloud_bot:  ichi_score = -1.0
        elif tenkan > kijun:  ichi_score = 0.4
        else:                 ichi_score = -0.4

        # Weighted blend (EMA is most reliable for trend)
        score    = ema_score * 0.50 + st_score * 0.30 + ichi_score * 0.20
        score    = max(-1.0, min(1.0, score))
        strength = abs(score) * 100

        return LayerResult(self.ID, self.NAME, round(score, 4), round(strength, 2), {
            "ema_stack_score": round(ema_score, 4),
            "supertrend":      "BULL" if st_score > 0 else "BEAR",
            "ichimoku":        "ABOVE" if cl > cloud_top else ("BELOW" if cl < cloud_bot else "INSIDE"),
            "ema8": round(e8, 4), "ema21": round(e21, 4),
            "ema55": round(e55, 4), "ema200": round(e200, 4),
            "tenkan_vs_kijun": "BULL" if tenkan > kijun else "BEAR",
        }, "BULL" if score > 0.1 else "BEAR" if score < -0.1 else "NEUTRAL")


# ═══════════════════════════════════════════════════════════════
# LAYER 2 — MOMENTUM QUALITY
# ═══════════════════════════════════════════════════════════════

class MomentumLayer:
    """
    Answers: HOW STRONG and ACCELERATING is the move?
    Uses: RSI · MACD Histogram · ADX · Rate-of-Change
    Non-overlapping: measures speed/energy, NOT direction or position
    """
    ID, NAME = 2, "Momentum Quality"

    def compute(self, df: pd.DataFrame) -> LayerResult:
        if len(df) < 30:
            return LayerResult(self.ID, self.NAME, 0, 0, {}, "NEUTRAL")
        c = df["close"]
        l = df.iloc[-1]
        p = df.iloc[-2]

        # RSI — momentum direction
        rsi = _safe(_rsi(c, 14).iloc[-1], 50)
        p_rsi = _safe(_rsi(c, 14).iloc[-2], 50)
        if   rsi < 30: rsi_score = 0.8    # oversold = buy pressure
        elif rsi > 70: rsi_score = -0.8   # overbought = sell pressure
        elif rsi < 45 and rsi > p_rsi: rsi_score = 0.4  # rising from low
        elif rsi > 55 and rsi < p_rsi: rsi_score = -0.4 # falling from high
        else: rsi_score = (50 - rsi) / 50 * 0.3

        # MACD Histogram — acceleration
        ema12 = _ema(c, 12)
        ema26 = _ema(c, 26)
        macd  = ema12 - ema26
        sig   = _ema(macd, 9)
        hist  = macd - sig
        h_cur  = _safe(hist.iloc[-1])
        h_prev = _safe(hist.iloc[-2])
        if h_cur > 0 and h_cur > h_prev:   macd_score = 0.9   # bull + accelerating
        elif h_cur > 0:                     macd_score = 0.4   # bull, decelerating
        elif h_cur < 0 and h_cur < h_prev:  macd_score = -0.9  # bear + accelerating
        elif h_cur < 0:                     macd_score = -0.4  # bear, decelerating
        else:                               macd_score = 0.0

        # ADX — trend strength (0–100, not directional)
        atr14 = _atr(df, 14)
        dm_p  = (df["high"] - df["high"].shift()).clip(lower=0)
        dm_n  = (df["low"].shift() - df["low"]).clip(lower=0)
        dm_p  = dm_p.where(dm_p > dm_n, 0)
        dm_n  = dm_n.where(dm_n > dm_p, 0)
        di_p  = 100 * dm_p.ewm(span=14, adjust=False).mean() / (atr14 + 1e-9)
        di_n  = 100 * dm_n.ewm(span=14, adjust=False).mean() / (atr14 + 1e-9)
        dx    = 100 * (di_p - di_n).abs() / (di_p + di_n + 1e-9)
        adx   = _safe(dx.ewm(span=14, adjust=False).mean().iloc[-1])
        dip   = _safe(di_p.iloc[-1])
        din   = _safe(di_n.iloc[-1])
        adx_score = (dip - din) / (dip + din + 1e-9) if adx > 20 else 0.0
        adx_mult  = min(1.0, adx / 40)   # scale by ADX strength

        # Rate of Change (5-period)
        roc5 = _safe(c.pct_change(5).iloc[-1])
        roc_score = max(-1.0, min(1.0, roc5 * 20))

        score = (rsi_score * 0.30 + macd_score * 0.35 +
                 adx_score * adx_mult * 0.25 + roc_score * 0.10)
        score    = max(-1.0, min(1.0, score))
        strength = (abs(h_cur) / (c.iloc[-1] * 0.001 + 1e-9) + adx / 100) / 2 * 100
        strength = min(100, abs(score) * 80 + adx * 0.3)

        return LayerResult(self.ID, self.NAME, round(score, 4), round(min(100,strength), 2), {
            "rsi14":       round(rsi, 2),
            "rsi_trend":   "RISING" if rsi > p_rsi else "FALLING",
            "macd_hist":   round(h_cur, 6),
            "macd_accel":  "ACCELERATING" if abs(h_cur) > abs(h_prev) else "DECELERATING",
            "adx":         round(adx, 2),
            "di_plus":     round(dip, 2),
            "di_minus":    round(din, 2),
            "roc5_pct":    round(roc5 * 100, 3),
        }, "BULL" if score > 0.1 else "BEAR" if score < -0.1 else "NEUTRAL")


# ═══════════════════════════════════════════════════════════════
# LAYER 3 — MEAN REVERSION PRESSURE
# ═══════════════════════════════════════════════════════════════

class ReversionLayer:
    """
    Answers: Is price OVEREXTENDED and due for reversal?
    Uses: Bollinger %B · Stochastic · Williams%R · CCI
    Non-overlapping: measures price deviation from mean, NOT trend direction
    """
    ID, NAME = 3, "Mean Reversion Pressure"

    def compute(self, df: pd.DataFrame) -> LayerResult:
        if len(df) < 25:
            return LayerResult(self.ID, self.NAME, 0, 0, {}, "NEUTRAL")
        c = df["close"]
        cl = _safe(c.iloc[-1])

        # Bollinger %B
        mid    = _sma(c, 20)
        sigma  = c.rolling(20).std()
        bb_u   = mid + 2 * sigma
        bb_l   = mid - 2 * sigma
        bb_pct = _safe((cl - bb_l.iloc[-1]) / (bb_u.iloc[-1] - bb_l.iloc[-1] + 1e-9))
        if   bb_pct < 0.1:  bb_score = 0.8   # very near lower band → buy
        elif bb_pct > 0.9:  bb_score = -0.8  # very near upper band → sell
        elif bb_pct < 0.3:  bb_score = 0.3
        elif bb_pct > 0.7:  bb_score = -0.3
        else:               bb_score = (0.5 - bb_pct) * 0.6

        # Stochastic %K/%D
        lo_min  = df["low"].rolling(14).min()
        hi_max  = df["high"].rolling(14).max()
        stk_k   = _safe(100 * (cl - lo_min.iloc[-1]) / (hi_max.iloc[-1] - lo_min.iloc[-1] + 1e-9))
        stk_d   = _safe(pd.Series([stk_k]).rolling(3).mean().iloc[-1], stk_k)
        p_stk   = _safe(100 * (c.iloc[-2] - lo_min.iloc[-2]) / (hi_max.iloc[-2] - lo_min.iloc[-2] + 1e-9))
        if   stk_k < 20:  stoch_score = 0.8
        elif stk_k > 80:  stoch_score = -0.8
        elif stk_k < 40 and stk_k > p_stk: stoch_score = 0.4  # rising from low
        elif stk_k > 60 and stk_k < p_stk: stoch_score = -0.4
        else:             stoch_score = (50 - stk_k) / 50 * 0.4

        # Williams %R
        hi14  = df["high"].rolling(14).max()
        lo14  = df["low"].rolling(14).min()
        willr = _safe(-100 * (hi14.iloc[-1] - cl) / (hi14.iloc[-1] - lo14.iloc[-1] + 1e-9))
        if   willr > -20:  willr_score = -0.7  # overbought
        elif willr < -80:  willr_score = 0.7   # oversold
        else:              willr_score = (willr + 50) / 50 * 0.4

        # CCI
        tp  = (df["high"] + df["low"] + c) / 3
        cci_ma = tp.rolling(20).mean()
        cci_md = tp.rolling(20).apply(lambda x: np.mean(np.abs(x - x.mean())))
        cci  = _safe((tp.iloc[-1] - cci_ma.iloc[-1]) / (0.015 * cci_md.iloc[-1] + 1e-9))
        if   cci > 150:  cci_score = -0.6
        elif cci < -150: cci_score = 0.6
        elif cci > 100:  cci_score = -0.3
        elif cci < -100: cci_score = 0.3
        else:            cci_score = -cci / 200 * 0.3

        score = (bb_score * 0.35 + stoch_score * 0.30 +
                 willr_score * 0.20 + cci_score * 0.15)
        score    = max(-1.0, min(1.0, score))
        # Reversion strength: higher when indicators agree on extreme
        reversion_extreme = abs(bb_pct - 0.5) + abs(stk_k - 50) / 100
        strength = min(100, reversion_extreme * 80 + abs(score) * 40)

        return LayerResult(self.ID, self.NAME, round(score, 4), round(strength, 2), {
            "bb_pct":        round(bb_pct * 100, 2),
            "bb_width":      round(_safe((bb_u.iloc[-1] - bb_l.iloc[-1]) / mid.iloc[-1] * 100), 3),
            "stoch_k":       round(stk_k, 2),
            "stoch_d":       round(stk_d, 2),
            "williams_r":    round(willr, 2),
            "cci20":         round(cci, 2),
            "squeeze":       bool(_safe((bb_u.iloc[-1] - bb_l.iloc[-1]) / mid.iloc[-1]) < 0.04),
        }, "BULL" if score > 0.1 else "BEAR" if score < -0.1 else "NEUTRAL")


# ═══════════════════════════════════════════════════════════════
# LAYER 4 — VOLUME CONFIRMATION
# ═══════════════════════════════════════════════════════════════

class VolumeLayer:
    """
    Answers: Is VOLUME confirming the price move?
    Uses: OBV · VWAP · Chaikin MF · Volume ratio
    Non-overlapping: confirms or denies other layers (NOT directional on own)
    """
    ID, NAME = 4, "Volume Confirmation"

    def compute(self, df: pd.DataFrame) -> LayerResult:
        if len(df) < 20 or "volume" not in df.columns:
            return LayerResult(self.ID, self.NAME, 0.0, 50.0,
                               {"note": "No volume data"}, "NEUTRAL")
        c  = df["close"]
        v  = df["volume"]
        cl = _safe(c.iloc[-1])

        # OBV trend
        direction = c.diff().apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))
        obv = (direction * v).cumsum()
        obv_sma5 = obv.rolling(5).mean()
        obv_rising = _safe(obv.iloc[-1]) > _safe(obv_sma5.iloc[-1])
        obv_score  = 0.6 if obv_rising else -0.6

        # VWAP position
        tp  = (df["high"] + df["low"] + c) / 3
        vwap = _safe((tp * v).cumsum().iloc[-1] / v.cumsum().iloc[-1])
        vwap_score = 0.5 if cl > vwap else -0.5

        # Chaikin Money Flow
        mf_mult = _safe(((c - df["low"]) - (df["high"] - c)) / (df["high"] - df["low"] + 1e-9))
        mf_vol  = mf_mult * v
        cmf     = _safe(mf_vol.rolling(20).sum().iloc[-1] / v.rolling(20).sum().iloc[-1])
        cmf_score = max(-1.0, min(1.0, cmf * 2))

        # Volume ratio (current vs 20-bar avg)
        vol_sma   = _safe(v.rolling(20).mean().iloc[-1])
        vol_cur   = _safe(v.iloc[-1])
        vol_ratio = vol_cur / (vol_sma + 1e-9)
        # Volume confirms direction of price change
        px_change = _safe(c.pct_change().iloc[-1])
        vol_dir_confirm = np.sign(px_change) * min(1.0, (vol_ratio - 1) * 0.5) if vol_ratio > 1.2 else 0

        score = (obv_score * 0.30 + vwap_score * 0.25 +
                 cmf_score * 0.30 + vol_dir_confirm * 0.15)
        score    = max(-1.0, min(1.0, score))
        strength = min(100, vol_ratio * 30 + abs(cmf) * 40 + 30)

        return LayerResult(self.ID, self.NAME, round(score, 4), round(min(100,strength), 2), {
            "obv_trend":    "RISING" if obv_rising else "FALLING",
            "vwap":         round(vwap, 4),
            "price_vs_vwap": "ABOVE" if cl > vwap else "BELOW",
            "cmf20":        round(cmf, 4),
            "vol_ratio":    round(vol_ratio, 3),
            "vol_surge":    bool(vol_ratio > 2.0),
        }, "BULL" if score > 0.1 else "BEAR" if score < -0.1 else "NEUTRAL")


# ═══════════════════════════════════════════════════════════════
# LAYER 5 — MARKET STRUCTURE
# ═══════════════════════════════════════════════════════════════

class StructureLayer:
    """
    Answers: WHERE is price relative to key structural levels?
    Uses: Pivot Points · Fibonacci · Keltner Channel · Parabolic SAR
    Non-overlapping: absolute price levels, NOT relative to moving averages
    """
    ID, NAME = 5, "Market Structure"

    def compute(self, df: pd.DataFrame) -> LayerResult:
        if len(df) < 20:
            return LayerResult(self.ID, self.NAME, 0, 0, {}, "NEUTRAL")
        c  = df["close"]
        cl = _safe(c.iloc[-1])

        # Pivot Points (from prev session: df.iloc[-2])
        ph = _safe(df["high"].iloc[-2])
        pl = _safe(df["low"].iloc[-2])
        pc = _safe(c.iloc[-2])
        pivot = (ph + pl + pc) / 3
        r1 = 2*pivot - pl
        s1 = 2*pivot - ph
        r2 = pivot + (ph - pl)
        s2 = pivot - (ph - pl)
        atr14 = _safe(_atr(df, 14).iloc[-1])

        piv_score = 0
        if abs(cl - s1) < atr14 * 0.8:   piv_score = 0.7   # near support
        elif abs(cl - s2) < atr14 * 0.8: piv_score = 0.8   # near strong support
        elif abs(cl - r1) < atr14 * 0.8: piv_score = -0.6  # near resistance
        elif abs(cl - r2) < atr14 * 0.8: piv_score = -0.7  # near strong resistance
        elif cl > pivot:                  piv_score = 0.3
        else:                             piv_score = -0.3

        # Fibonacci retracement (50-bar swing)
        n = min(50, len(df))
        hi50 = _safe(df["high"].tail(n).max())
        lo50 = _safe(df["low"].tail(n).min())
        diff = hi50 - lo50
        fibs = {f: lo50 + diff * r for f, r in
                [("0",0),("236",.236),("382",.382),("500",.5),("618",.618),("786",.786),("100",1)]}
        fib_score = 0
        for level, price in fibs.items():
            if abs(cl - price) < atr14 * 0.6:
                # Fib support/resistance proximity
                fib_score = 0.5 if cl > price else -0.5
                break

        # Keltner Channel breakout
        ema20  = _safe(_ema(c, 20).iloc[-1])
        kc_u   = ema20 + 2.0 * atr14
        kc_l   = ema20 - 2.0 * atr14
        if cl > kc_u:    kc_score = 0.8    # bullish breakout
        elif cl < kc_l:  kc_score = -0.8   # bearish breakout
        else:            kc_score = (cl - ema20) / (kc_u - ema20 + 1e-9) * 0.3

        # Parabolic SAR
        af, af_max = 0.02, 0.2
        psar = np.zeros(len(df))
        ep   = _safe(df["low"].iloc[0])
        bull = True
        psar[0] = _safe(df["high"].iloc[0])
        for i in range(1, len(df)):
            if bull:
                psar[i] = psar[i-1] + af*(ep - psar[i-1])
                if _safe(df["low"].iloc[i]) < psar[i]:
                    bull=False; psar[i]=ep; ep=_safe(df["low"].iloc[i]); af=0.02
                else:
                    if _safe(df["high"].iloc[i]) > ep: ep=_safe(df["high"].iloc[i]); af=min(af+0.02,af_max)
            else:
                psar[i] = psar[i-1] + af*(ep - psar[i-1])
                if _safe(df["high"].iloc[i]) > psar[i]:
                    bull=True; psar[i]=ep; ep=_safe(df["high"].iloc[i]); af=0.02
                else:
                    if _safe(df["low"].iloc[i]) < ep: ep=_safe(df["low"].iloc[i]); af=min(af+0.02,af_max)
        sar_bull  = bool(cl > psar[-1])
        sar_score = 0.6 if sar_bull else -0.6

        score = (piv_score * 0.30 + fib_score * 0.25 +
                 kc_score  * 0.25 + sar_score * 0.20)
        score    = max(-1.0, min(1.0, score))
        strength = abs(score) * 100

        near_level = ""
        for name, price in [("R2",r2),("R1",r1),("Pivot",pivot),("S1",s1),("S2",s2)]:
            if abs(cl - price) < atr14:
                near_level = name; break

        return LayerResult(self.ID, self.NAME, round(score, 4), round(strength, 2), {
            "pivot": round(pivot,4), "r1": round(r1,4), "r2": round(r2,4),
            "s1": round(s1,4), "s2": round(s2,4),
            "near_level":   near_level or "None",
            "keltner":      "ABOVE" if cl > kc_u else "BELOW" if cl < kc_l else "INSIDE",
            "psar":         "BULL" if sar_bull else "BEAR",
            "fib_nearest":  min(fibs.items(), key=lambda x: abs(cl-x[1]))[0] + "%",
        }, "BULL" if score > 0.1 else "BEAR" if score < -0.1 else "NEUTRAL")


# ═══════════════════════════════════════════════════════════════
# MASTER AI DECISION ENGINE
# ═══════════════════════════════════════════════════════════════

@dataclass
class AIDecision:
    action: str           # BUY | SELL | WAIT
    confidence: float     # 0–100
    composite_score: float  # -1 to +1
    layer_results: list
    agreement: int        # 0–5 layers in agreement
    conflict_penalty: float
    market_phase: str
    key_levels: dict
    reasoning: str
    entry_quality: str    # EXCELLENT | GOOD | FAIR | POOR
    suggested_sl_pct: float
    suggested_tp_pct: float
    risk_reward: float

    def to_dict(self) -> dict:
        return {
            "action":          self.action,
            "confidence":      self.confidence,
            "composite_score": self.composite_score,
            "layers":          [l.to_dict() for l in self.layer_results],
            "agreement":       f"{self.agreement}/5",
            "conflict_penalty": self.conflict_penalty,
            "market_phase":    self.market_phase,
            "key_levels":      self.key_levels,
            "reasoning":       self.reasoning,
            "entry_quality":   self.entry_quality,
            "suggested_sl_pct": self.suggested_sl_pct,
            "suggested_tp_pct": self.suggested_tp_pct,
            "risk_reward":     self.risk_reward,
        }


class LayeredAIEngine:
    """
    Combines all 5 non-overlapping layers into a single unified decision.
    Each layer answers a DIFFERENT question — no information is double-counted.

    Final score = weighted sum of layers, penalized for conflicts.
    Minimum 3/5 layers must agree for BUY/SELL signal.
    """

    LAYER_WEIGHTS = {1: 0.30, 2: 0.25, 3: 0.20, 4: 0.15, 5: 0.10}
    BUY_THRESHOLD  = 0.35
    SELL_THRESHOLD = -0.35

    def __init__(self):
        self.layers = [
            TrendLayer(),
            MomentumLayer(),
            ReversionLayer(),
            VolumeLayer(),
            StructureLayer(),
        ]

    def analyze(self, df: pd.DataFrame, symbol: str = "") -> AIDecision:
        """
        Full 5-layer analysis. Returns complete AIDecision.
        """
        if df is None or len(df) < 30:
            return self._empty_decision("Insufficient data")

        layer_results = [layer.compute(df) for layer in self.layers]

        # Weighted composite score
        composite = sum(
            lr.weighted_score * self.LAYER_WEIGHTS[lr.layer_id]
            for lr in layer_results
        ) / sum(self.LAYER_WEIGHTS.values())

        # Agreement count — how many layers point same way as composite
        direction = "BULL" if composite > 0.05 else "BEAR" if composite < -0.05 else "NEUTRAL"
        agreement = sum(1 for lr in layer_results if lr.bias == direction)

        # Conflict penalty — reduces confidence when layers disagree
        bull_count = sum(1 for lr in layer_results if lr.bias == "BULL")
        bear_count = sum(1 for lr in layer_results if lr.bias == "BEAR")
        max_split   = min(bull_count, bear_count)
        conflict_penalty = max_split * 0.08   # each conflict layer reduces by 8%

        # Adjusted score
        adj_score  = composite * (1 - conflict_penalty)
        adj_score  = max(-1.0, min(1.0, adj_score))

        # Action
        avg_strength = sum(lr.strength for lr in layer_results) / len(layer_results)
        if adj_score >= self.BUY_THRESHOLD and agreement >= 3:
            action = "BUY"
            confidence = min(97, 50 + abs(adj_score) * 40 + agreement * 3 - conflict_penalty * 20)
        elif adj_score <= self.SELL_THRESHOLD and agreement >= 3:
            action = "SELL"
            confidence = min(97, 50 + abs(adj_score) * 40 + agreement * 3 - conflict_penalty * 20)
        else:
            action = "WAIT"
            confidence = min(70, 50 + abs(adj_score) * 15)

        # Market phase
        t_layer = layer_results[0]  # Trend
        m_layer = layer_results[1]  # Momentum
        r_layer = layer_results[2]  # Reversion
        adx = _safe(m_layer.signals.get("adx", 20))
        rsi = _safe(m_layer.signals.get("rsi14", 50))
        squeeze = r_layer.signals.get("squeeze", False)

        if   t_layer.score > 0.5 and adx > 30:  phase = "strong_uptrend"
        elif t_layer.score < -0.5 and adx > 30: phase = "strong_downtrend"
        elif squeeze:                             phase = "consolidating_pre_breakout"
        elif rsi > 72:                            phase = "overbought"
        elif rsi < 28:                            phase = "oversold"
        elif adx < 18:                            phase = "ranging_choppy"
        elif t_layer.score > 0.2:                phase = "mild_uptrend"
        elif t_layer.score < -0.2:               phase = "mild_downtrend"
        else:                                     phase = "neutral"

        # Entry quality
        if action != "WAIT":
            if agreement == 5:              quality = "EXCELLENT"
            elif agreement == 4:            quality = "GOOD"
            elif agreement == 3 and adx > 25: quality = "GOOD"
            else:                           quality = "FAIR"
        else:
            quality = "POOR" if agreement <= 1 else "WAIT"

        # Dynamic SL/TP based on volatility
        atr = _safe(_atr(df, 14).iloc[-1])
        cl  = _safe(df["close"].iloc[-1])
        if atr > 0 and cl > 0:
            atr_pct       = atr / cl * 100
            sl_pct        = round(atr_pct * 2.0, 2)   # 2 ATR SL
            tp_pct        = round(atr_pct * 4.0, 2)   # 4 ATR TP (1:2 RR)
        else:
            sl_pct, tp_pct = 2.0, 4.0

        # Key levels from structure layer
        key_levels = layer_results[4].signals if layer_results else {}

        # Reasoning string
        layer_summary = " | ".join(
            f"L{lr.layer_id}({lr.bias} {lr.strength:.0f}%)" for lr in layer_results
        )
        reasoning = (
            f"[{action} {confidence:.1f}%] Score:{adj_score:.3f} "
            f"Agreement:{agreement}/5 Conflict:{conflict_penalty:.2f} "
            f"Phase:{phase} — {layer_summary}"
        )

        return AIDecision(
            action=action,
            confidence=round(confidence, 2),
            composite_score=round(adj_score, 4),
            layer_results=layer_results,
            agreement=agreement,
            conflict_penalty=round(conflict_penalty, 3),
            market_phase=phase,
            key_levels=key_levels,
            reasoning=reasoning,
            entry_quality=quality,
            suggested_sl_pct=sl_pct,
            suggested_tp_pct=tp_pct,
            risk_reward=round(tp_pct / (sl_pct + 1e-9), 2),
        )

    def _empty_decision(self, reason: str) -> AIDecision:
        empty_layers = [
            LayerResult(i, n, 0, 0, {"reason": reason}, "NEUTRAL")
            for i, n in [(1,"Trend"),(2,"Momentum"),(3,"Reversion"),(4,"Volume"),(5,"Structure")]
        ]
        return AIDecision("WAIT", 0, 0, empty_layers, 0, 0, "unknown", {}, reason, "POOR", 2.0, 4.0, 2.0)

    def quick_score(self, df: pd.DataFrame) -> dict:
        """Fast scoring — just returns action/confidence without full breakdown."""
        d = self.analyze(df)
        return {"action": d.action, "confidence": d.confidence,
                "score": d.composite_score, "phase": d.market_phase,
                "quality": d.entry_quality}


# ── Singleton ────────────────────────────────────────────────
layered_ai = LayeredAIEngine()
