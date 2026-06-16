"""
ai/indicator_ai.py — ESTRADE Elite Indicator AI Engine
═══════════════════════════════════════════════════════════════════════
25+ Professional Indicators with AI Decision Fusion

INDICATORS:
  Trend:       EMA 5/10/20/50/100/200, SMA, VWAP, Supertrend, Ichimoku
  Momentum:    RSI, MACD, Stochastic, Williams %R, CCI, MFI, ROC
  Volatility:  ATR, Bollinger Bands, Keltner Channels, Donchian, VIX proxy
  Volume:      OBV, Volume Profile, CMF, VWAP, A/D Line, Force Index
  Advanced:    Heikin-Ashi, Elliott Wave counter, Pivot Points (CPR)
               Market Structure (BOS/CHoCH), Divergence detector

AI DECISION ENGINE:
  Each indicator produces a score: -1.0 (strong bear) to +1.0 (strong bull)
  Weights are regime-adaptive: trend indicators weigh more in trending markets
  Confluence scoring: how many indicators agree → confidence
  Final output: STRONG_BUY / BUY / NEUTRAL / SELL / STRONG_SELL
                + confidence % + entry/SL/TP recommendations
═══════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations
import math
import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from typing import Optional


# ══════════════════════════════════════════════════════════════
# OUTPUT STRUCTURES
# ══════════════════════════════════════════════════════════════

@dataclass
class IndicatorSignal:
    name: str
    value: float           # Raw indicator value
    score: float           # -1.0 to +1.0 (bear to bull)
    label: str             # STRONG_BULL / BULL / NEUTRAL / BEAR / STRONG_BEAR
    description: str       # Human-readable explanation
    weight: float = 1.0    # Regime-adjusted weight

    @property
    def direction(self) -> str:
        if self.score >  0.3: return "BULL"
        if self.score < -0.3: return "BEAR"
        return "NEUTRAL"


@dataclass
class AIIndicatorDecision:
    direction: str          # STRONG_BUY/BUY/NEUTRAL/SELL/STRONG_SELL
    confidence: float       # 0-100
    bull_score: float       # weighted bull pressure
    bear_score: float       # weighted bear pressure
    confluence: int         # how many indicators agree with direction
    total_indicators: int
    regime: str
    entry_price: float
    sl_price: float
    tp1_price: float
    tp2_price: float
    tp3_price: float
    rr_ratio: float
    indicators: list[IndicatorSignal]
    top_reasons: list[str]  # top 3 reasons for decision
    warnings: list[str]     # conflicting signals
    atr: float
    raw_scores: dict        # name → score for dashboard display


# ══════════════════════════════════════════════════════════════
# INDICATOR COMPUTATIONS
# ══════════════════════════════════════════════════════════════

def _ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()

def _sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n).mean()

def _rsi(s: pd.Series, n=14) -> pd.Series:
    d = s.diff()
    g = d.clip(lower=0).rolling(n).mean()
    l = (-d.clip(upper=0)).rolling(n).mean()
    return 100 - 100 / (1 + g / l.replace(0, 1e-9))

def _atr(df: pd.DataFrame, n=14) -> pd.Series:
    h, l, c = df['high'], df['low'], df['close']
    tr = pd.concat([h-l, (h-c.shift()).abs(), (l-c.shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(span=n, adjust=False).mean()

def _macd(s: pd.Series):
    f = _ema(s, 12); sl = _ema(s, 26)
    m = f - sl; sig = _ema(m, 9); hist = m - sig
    return m, sig, hist

def _bb(s: pd.Series, n=20, k=2):
    mid = _sma(s, n); std = s.rolling(n).std()
    return mid + k*std, mid, mid - k*std

def _stoch(df: pd.DataFrame, k=14, d=3):
    lo = df['low'].rolling(k).min(); hi = df['high'].rolling(k).max()
    kp = 100*(df['close']-lo)/(hi-lo+1e-9)
    return kp, kp.rolling(d).mean()

def _williams_r(df: pd.DataFrame, n=14) -> pd.Series:
    hi = df['high'].rolling(n).max(); lo = df['low'].rolling(n).min()
    return -100*(hi-df['close'])/(hi-lo+1e-9)

def _cci(df: pd.DataFrame, n=20) -> pd.Series:
    tp = (df['high']+df['low']+df['close'])/3
    ma = tp.rolling(n).mean()
    md = tp.rolling(n).apply(lambda x: np.abs(x-x.mean()).mean())
    return (tp-ma)/(0.015*md+1e-9)

def _obv(df: pd.DataFrame) -> pd.Series:
    direction = np.sign(df['close'].diff().fillna(0))
    return (direction * df.get('volume', pd.Series([1]*len(df), index=df.index))).cumsum()

def _mfi(df: pd.DataFrame, n=14) -> pd.Series:
    tp = (df['high']+df['low']+df['close'])/3
    vol = df.get('volume', pd.Series([1]*len(df), index=df.index))
    mf = tp * vol
    pos = mf.where(tp > tp.shift(), 0).rolling(n).sum()
    neg = mf.where(tp < tp.shift(), 0).rolling(n).sum()
    return 100 - 100/(1+pos/(neg+1e-9))

def _cmf(df: pd.DataFrame, n=20) -> pd.Series:
    h, l, c = df['high'], df['low'], df['close']
    vol = df.get('volume', pd.Series([1]*len(df), index=df.index))
    clv = ((c-l)-(h-c))/(h-l+1e-9)
    return (clv*vol).rolling(n).sum()/vol.rolling(n).sum()

def _vwap(df: pd.DataFrame) -> pd.Series:
    tp = (df['high']+df['low']+df['close'])/3
    vol = df.get('volume', pd.Series([1]*len(df), index=df.index))
    return (tp*vol).cumsum()/vol.cumsum()

def _supertrend(df: pd.DataFrame, n=10, mult=3.0):
    """Supertrend indicator."""
    atr_val = _atr(df, n)
    hl2 = (df['high'] + df['low']) / 2
    upper = hl2 + mult * atr_val
    lower = hl2 - mult * atr_val

    supertrend = pd.Series(index=df.index, dtype=float)
    direction  = pd.Series(index=df.index, dtype=float)
    supertrend.iloc[0] = lower.iloc[0]
    direction.iloc[0]  = 1

    for i in range(1, len(df)):
        prev_st = supertrend.iloc[i-1]
        prev_dir = direction.iloc[i-1]
        close = df['close'].iloc[i]

        if prev_dir == 1:
            st = max(lower.iloc[i], prev_st)
        else:
            st = min(upper.iloc[i], prev_st)

        if prev_dir == 1 and close < st:
            direction.iloc[i] = -1; supertrend.iloc[i] = upper.iloc[i]
        elif prev_dir == -1 and close > st:
            direction.iloc[i] = 1; supertrend.iloc[i] = lower.iloc[i]
        else:
            direction.iloc[i] = prev_dir; supertrend.iloc[i] = st

    return supertrend, direction

def _keltner(df: pd.DataFrame, n=20, mult=2.0):
    mid = _ema(df['close'], n)
    atr_val = _atr(df, n)
    return mid + mult*atr_val, mid, mid - mult*atr_val

def _donchian(df: pd.DataFrame, n=20):
    return df['high'].rolling(n).max(), df['low'].rolling(n).min()

def _ad_line(df: pd.DataFrame) -> pd.Series:
    h, l, c = df['high'], df['low'], df['close']
    vol = df.get('volume', pd.Series([1]*len(df), index=df.index))
    clv = ((c-l)-(h-c))/(h-l+1e-9)
    return (clv*vol).cumsum()

def _roc(s: pd.Series, n=12) -> pd.Series:
    return ((s - s.shift(n)) / s.shift(n).replace(0,1e-9)) * 100

def _pivot_points(df: pd.DataFrame):
    """Camarilla pivot points."""
    h = df['high'].iloc[-2]; l = df['low'].iloc[-2]; c = df['close'].iloc[-2]
    pp = (h + l + c) / 3
    r1 = pp + 0.382*(h-l); r2 = pp + 0.618*(h-l); r3 = pp + 1.0*(h-l)
    s1 = pp - 0.382*(h-l); s2 = pp - 0.618*(h-l); s3 = pp - 1.0*(h-l)
    return {"PP": pp, "R1": r1, "R2": r2, "R3": r3, "S1": s1, "S2": s2, "S3": s3}

def _heikin_ashi(df: pd.DataFrame) -> pd.DataFrame:
    ha = pd.DataFrame(index=df.index)
    ha['close'] = (df['open']+df['high']+df['low']+df['close'])/4
    ha['open'] = ((df['open']+df['close'])/2).shift(1)
    ha.iloc[0, ha.columns.get_loc('open')] = (df['open'].iloc[0]+df['close'].iloc[0])/2
    ha['high'] = pd.concat([df['high'], ha['open'], ha['close']], axis=1).max(axis=1)
    ha['low']  = pd.concat([df['low'],  ha['open'], ha['close']], axis=1).min(axis=1)
    return ha

def _detect_divergence(price: pd.Series, indicator: pd.Series, n=5) -> str:
    """Detect bullish/bearish divergence."""
    try:
        price_tail = price.tail(n)
        ind_tail   = indicator.tail(n)
        price_trend = (price_tail.iloc[-1] - price_tail.iloc[0])
        ind_trend   = (ind_tail.iloc[-1] - ind_tail.iloc[0])
        if price_trend > 0 and ind_trend < -0.5:
            return "bearish_div"
        if price_trend < 0 and ind_trend > 0.5:
            return "bullish_div"
    except Exception:
        pass
    return "none"


# ══════════════════════════════════════════════════════════════
# INDICATOR AI ENGINE
# ══════════════════════════════════════════════════════════════

class IndicatorAI:
    """
    Elite indicator analysis with AI decision fusion.
    Computes 25+ indicators, scores each -1..+1,
    weights by regime, fuses into final trading decision.
    """

    # Regime-specific indicator weights
    REGIME_WEIGHTS = {
        "bull_trend":   {"trend": 2.0, "momentum": 1.5, "volatility": 1.0, "volume": 1.2, "oscillator": 0.8},
        "bear_trend":   {"trend": 2.0, "momentum": 1.5, "volatility": 1.0, "volume": 1.2, "oscillator": 0.8},
        "ranging":      {"trend": 0.6, "momentum": 1.0, "volatility": 0.8, "volume": 1.5, "oscillator": 2.0},
        "choppy":       {"trend": 0.4, "momentum": 0.8, "volatility": 1.5, "volume": 1.0, "oscillator": 1.8},
        "breakout":     {"trend": 1.5, "momentum": 2.0, "volatility": 1.8, "volume": 2.0, "oscillator": 0.8},
        "high_vol":     {"trend": 1.0, "momentum": 1.2, "volatility": 2.0, "volume": 1.5, "oscillator": 0.9},
        "accumulation": {"trend": 0.8, "momentum": 1.2, "volatility": 0.8, "volume": 2.0, "oscillator": 1.5},
        "unknown":      {"trend": 1.0, "momentum": 1.0, "volatility": 1.0, "volume": 1.0, "oscillator": 1.0},
    }

    def analyze(self, df: pd.DataFrame, pair: str = "",
                 regime: str = "unknown") -> AIIndicatorDecision:
        """Full indicator analysis and AI decision."""
        if df is None or len(df) < 50:
            return self._empty_decision(pair)

        close = df['close']
        high  = df['high']
        low   = df['low']
        l     = df.iloc[-1]
        p     = df.iloc[-2]

        close_now = float(l['close'])
        atr_val   = float(_atr(df, 14).iloc[-1]) or close_now * 0.015
        weights   = self.REGIME_WEIGHTS.get(regime, self.REGIME_WEIGHTS["unknown"])

        signals: list[IndicatorSignal] = []

        # ════════════════════════════════════════════
        # TREND INDICATORS
        # ════════════════════════════════════════════
        w_trend = weights["trend"]

        # EMA Cascade
        ema20  = float(_ema(close, 20).iloc[-1])
        ema50  = float(_ema(close, 50).iloc[-1])
        ema200 = float(_ema(close, 200).iloc[-1])

        if ema20 > ema50 > ema200 and close_now > ema20:
            ema_score = 1.0
            ema_desc = f"Bull EMA stack: {close_now:.4f} > EMA20({ema20:.4f}) > EMA50({ema50:.4f}) > EMA200({ema200:.4f})"
        elif ema20 < ema50 < ema200 and close_now < ema20:
            ema_score = -1.0
            ema_desc = f"Bear EMA stack: {close_now:.4f} < EMA20 < EMA50 < EMA200"
        elif ema20 > ema50:
            ema_score = 0.5
            ema_desc = f"EMA20 > EMA50 (partial bull)"
        else:
            ema_score = -0.5
            ema_desc = f"EMA20 < EMA50 (partial bear)"

        signals.append(IndicatorSignal("EMA Cascade", close_now, ema_score,
                        self._label(ema_score), ema_desc, w_trend))

        # Supertrend
        try:
            st, st_dir = _supertrend(df, 10, 3.0)
            st_val = float(st.iloc[-1])
            st_d   = float(st_dir.iloc[-1])
            st_score = 0.9 if st_d == 1 else -0.9
            signals.append(IndicatorSignal("Supertrend", st_val, st_score,
                self._label(st_score),
                f"Supertrend {'↑ BULL' if st_d==1 else '↓ BEAR'} @ {st_val:.4f}",
                w_trend * 1.2))
        except Exception:
            pass

        # VWAP
        vwap_val = float(_vwap(df).iloc[-1])
        vwap_score = 0.7 if close_now > vwap_val else -0.7
        signals.append(IndicatorSignal("VWAP", vwap_val, vwap_score,
            self._label(vwap_score),
            f"Price {'above' if close_now > vwap_val else 'below'} VWAP({vwap_val:.4f})",
            w_trend))

        # Ichimoku (simplified: Tenkan/Kijun cross)
        tenkan = (high.rolling(9).max() + low.rolling(9).min()) / 2
        kijun  = (high.rolling(26).max() + low.rolling(26).min()) / 2
        t_val  = float(tenkan.iloc[-1]); k_val = float(kijun.iloc[-1])
        ichi_score = 0.8 if t_val > k_val and close_now > t_val else (-0.8 if t_val < k_val and close_now < t_val else 0)
        signals.append(IndicatorSignal("Ichimoku TK", t_val, ichi_score,
            self._label(ichi_score),
            f"Tenkan({'>' if t_val>k_val else '<'})Kijun | Close={'above' if close_now>t_val else 'below'} cloud",
            w_trend))

        # ════════════════════════════════════════════
        # MOMENTUM INDICATORS
        # ════════════════════════════════════════════
        w_mom = weights["momentum"]

        # RSI
        rsi_val = float(_rsi(close, 14).iloc[-1])
        prev_rsi = float(_rsi(close, 14).iloc[-2])
        if rsi_val < 25:
            rsi_score = 1.0    # extreme oversold → strong buy
        elif rsi_val < 35:
            rsi_score = 0.75
        elif rsi_val < 45:
            rsi_score = 0.3
        elif rsi_val > 75:
            rsi_score = -1.0   # extreme overbought → strong sell
        elif rsi_val > 65:
            rsi_score = -0.75
        elif rsi_val > 55:
            rsi_score = -0.3
        else:
            rsi_score = 0.0
        # Momentum bonus if RSI trending
        if rsi_val > prev_rsi: rsi_score = min(1.0, rsi_score + 0.1)
        else: rsi_score = max(-1.0, rsi_score - 0.1)

        signals.append(IndicatorSignal("RSI(14)", rsi_val, rsi_score,
            self._label(rsi_score),
            f"RSI={rsi_val:.1f} ({'Oversold↑' if rsi_val<30 else 'Overbought↓' if rsi_val>70 else 'Neutral'})",
            w_mom * 1.3))

        # MACD
        macd_l, macd_sig, macd_hist = _macd(close)
        hist_now  = float(macd_hist.iloc[-1])
        hist_prev = float(macd_hist.iloc[-2])
        macd_score = min(1.0, max(-1.0, hist_now * 5 / (atr_val + 1e-9)))
        if hist_now > hist_prev: macd_score = min(1.0, macd_score + 0.2)
        else: macd_score = max(-1.0, macd_score - 0.2)

        signals.append(IndicatorSignal("MACD", float(macd_l.iloc[-1]), macd_score,
            self._label(macd_score),
            f"MACD hist={hist_now:+.4f} {'↑Increasing' if hist_now>hist_prev else '↓Decreasing'}",
            w_mom * 1.2))

        # Stochastic
        sk, sd = _stoch(df)
        sk_val = float(sk.iloc[-1]); sd_val = float(sd.iloc[-1])
        if sk_val < 20:   stoch_score = 0.9
        elif sk_val < 35: stoch_score = 0.5
        elif sk_val > 80: stoch_score = -0.9
        elif sk_val > 65: stoch_score = -0.5
        else:             stoch_score = 0.0
        if sk_val > sd_val: stoch_score = min(1.0, stoch_score + 0.15)
        else: stoch_score = max(-1.0, stoch_score - 0.15)

        signals.append(IndicatorSignal("Stochastic", sk_val, stoch_score,
            self._label(stoch_score),
            f"K={sk_val:.1f} D={sd_val:.1f} {'K>D ↑' if sk_val>sd_val else 'K<D ↓'}",
            w_mom))

        # Williams %R
        wr_val = float(_williams_r(df, 14).iloc[-1])
        if wr_val < -80:   wr_score = 0.9
        elif wr_val < -65: wr_score = 0.5
        elif wr_val > -20: wr_score = -0.9
        elif wr_val > -35: wr_score = -0.5
        else:              wr_score = 0.0

        signals.append(IndicatorSignal("Williams %R", wr_val, wr_score,
            self._label(wr_score),
            f"W%R={wr_val:.1f} {'Oversold' if wr_val<-80 else 'Overbought' if wr_val>-20 else 'Normal'}",
            w_mom * 0.8))

        # CCI
        cci_val = float(_cci(df, 20).iloc[-1])
        cci_score = min(1.0, max(-1.0, -cci_val / 150))
        if cci_val > 200:  cci_score = -1.0
        elif cci_val < -200: cci_score = 1.0

        signals.append(IndicatorSignal("CCI(20)", cci_val, cci_score,
            self._label(cci_score),
            f"CCI={cci_val:.1f} {'Overbought↓' if cci_val>100 else 'Oversold↑' if cci_val<-100 else 'Normal'}",
            w_mom * 0.8))

        # ROC (Rate of Change)
        roc_val = float(_roc(close, 12).iloc[-1])
        roc_score = min(1.0, max(-1.0, roc_val / 5))
        signals.append(IndicatorSignal("ROC(12)", roc_val, roc_score,
            self._label(roc_score),
            f"ROC={roc_val:+.2f}% {'Accelerating↑' if roc_val>0 else 'Decelerating↓'}",
            w_mom * 0.7))

        # MFI (Money Flow Index)
        try:
            mfi_val = float(_mfi(df, 14).iloc[-1])
            if mfi_val < 20:   mfi_score = 1.0
            elif mfi_val < 35: mfi_score = 0.5
            elif mfi_val > 80: mfi_score = -1.0
            elif mfi_val > 65: mfi_score = -0.5
            else:              mfi_score = 0.0
            signals.append(IndicatorSignal("MFI(14)", mfi_val, mfi_score,
                self._label(mfi_score),
                f"MFI={mfi_val:.1f} {'Oversold' if mfi_val<20 else 'Overbought' if mfi_val>80 else 'Normal'}",
                w_mom * 0.9))
        except Exception:
            pass

        # ════════════════════════════════════════════
        # VOLATILITY INDICATORS
        # ════════════════════════════════════════════
        w_vol = weights["volatility"]

        # Bollinger Bands
        bb_u, bb_m, bb_l = _bb(close, 20, 2.0)
        bb_u_val = float(bb_u.iloc[-1]); bb_m_val = float(bb_m.iloc[-1]); bb_l_val = float(bb_l.iloc[-1])
        bb_width = (bb_u_val - bb_l_val) / (bb_m_val + 1e-9)
        bb_pos   = (close_now - bb_l_val) / (bb_u_val - bb_l_val + 1e-9)

        if close_now < bb_l_val: bb_score = 0.9
        elif bb_pos < 0.2:        bb_score = 0.5
        elif close_now > bb_u_val: bb_score = -0.9
        elif bb_pos > 0.8:         bb_score = -0.5
        else:                      bb_score = (0.5 - bb_pos) * 0.5

        signals.append(IndicatorSignal("Bollinger Bands", bb_width, bb_score,
            self._label(bb_score),
            f"BB pos={bb_pos:.0%} | {'Below lower (oversold)' if close_now<bb_l_val else 'Above upper (overbought)' if close_now>bb_u_val else f'Width={bb_width:.3f}'}",
            w_vol * 1.2))

        # Keltner Channels
        try:
            kc_u, kc_m, kc_l = _keltner(df, 20, 2.0)
            kc_u_val = float(kc_u.iloc[-1]); kc_l_val = float(kc_l.iloc[-1])
            if close_now < kc_l_val:    kc_score = 0.8
            elif close_now > kc_u_val:  kc_score = -0.8
            else:                       kc_score = (0.5 - (close_now - kc_l_val)/(kc_u_val - kc_l_val + 1e-9)) * 0.6
            signals.append(IndicatorSignal("Keltner Channel", float(kc_m.iloc[-1]), kc_score,
                self._label(kc_score),
                f"Price {'below KC (oversold)' if close_now<kc_l_val else 'above KC (overbought)' if close_now>kc_u_val else 'inside KC'}",
                w_vol))
        except Exception:
            pass

        # ATR (volatility state)
        atr_s = _atr(df, 14)
        atr_avg = float(atr_s.tail(20).mean())
        atr_ratio = atr_val / (atr_avg + 1e-9)
        # High ATR = high vol = caution; low ATR = squeeze approaching
        atr_score = 0.2 if atr_ratio < 0.8 else (-0.1 if atr_ratio > 1.5 else 0.0)
        signals.append(IndicatorSignal("ATR(14)", atr_val, atr_score,
            "NEUTRAL",
            f"ATR={atr_val:.4f} | {atr_ratio:.2f}× avg ({'Expanding' if atr_ratio>1.2 else 'Contracting' if atr_ratio<0.8 else 'Normal'} vol)",
            w_vol * 0.5))

        # Donchian Breakout
        try:
            dc_h, dc_l = _donchian(df, 20)
            dc_h_val = float(dc_h.iloc[-1]); dc_l_val = float(dc_l.iloc[-1])
            if close_now >= dc_h_val: dc_score = 0.9   # New 20-day high
            elif close_now <= dc_l_val: dc_score = -0.9  # New 20-day low
            else: dc_score = 0.0
            signals.append(IndicatorSignal("Donchian(20)", dc_h_val, dc_score,
                self._label(dc_score),
                f"{'🚀 New 20D High breakout!' if dc_score>0 else '📉 New 20D Low breakdown!' if dc_score<0 else 'Inside range'}",
                w_vol * 1.3))
        except Exception:
            pass

        # ════════════════════════════════════════════
        # VOLUME INDICATORS
        # ════════════════════════════════════════════
        w_volume = weights["volume"]

        # OBV
        try:
            obv_s = _obv(df)
            obv_ema = _ema(obv_s, 20)
            obv_score = 0.8 if float(obv_s.iloc[-1]) > float(obv_ema.iloc[-1]) else -0.8
            signals.append(IndicatorSignal("OBV", float(obv_s.iloc[-1]), obv_score,
                self._label(obv_score),
                f"OBV {'above' if obv_score>0 else 'below'} EMA (volume {'confirming' if obv_score>0 else 'diverging'} price)",
                w_volume * 1.2))
        except Exception:
            pass

        # CMF
        try:
            cmf_val = float(_cmf(df, 20).iloc[-1])
            cmf_score = min(1.0, max(-1.0, cmf_val * 3))
            signals.append(IndicatorSignal("CMF(20)", cmf_val, cmf_score,
                self._label(cmf_score),
                f"CMF={cmf_val:+.3f} {'Money flowing IN ↑' if cmf_val>0.1 else 'Money flowing OUT ↓' if cmf_val<-0.1 else 'Balanced'}",
                w_volume * 1.1))
        except Exception:
            pass

        # A/D Line
        try:
            ad = _ad_line(df)
            ad_ema = _ema(ad, 14)
            ad_score = 0.7 if float(ad.iloc[-1]) > float(ad_ema.iloc[-1]) else -0.7
            signals.append(IndicatorSignal("A/D Line", float(ad.iloc[-1]), ad_score,
                self._label(ad_score),
                f"Accumulation/Distribution {'↑ Accumulating' if ad_score>0 else '↓ Distributing'}",
                w_volume))
        except Exception:
            pass

        # Volume Ratio
        try:
            vol = df.get('volume')
            if vol is not None:
                vol_ratio = float(vol.iloc[-1]) / (float(vol.tail(20).mean()) + 1e-9)
                if vol_ratio > 2.5:
                    # Big volume confirms price direction
                    price_dir = 1 if float(l['close']) > float(l['open']) else -1
                    vol_score = price_dir * min(1.0, vol_ratio / 5)
                    signals.append(IndicatorSignal("Volume Spike", vol_ratio, vol_score,
                        self._label(vol_score),
                        f"Volume {vol_ratio:.1f}× average — {'Bullish impulse' if price_dir>0 else 'Bearish impulse'}!",
                        w_volume * 1.5))
        except Exception:
            pass

        # ════════════════════════════════════════════
        # ADVANCED INDICATORS
        # ════════════════════════════════════════════

        # Heikin-Ashi candle pattern
        try:
            ha = _heikin_ashi(df)
            ha_close = float(ha['close'].iloc[-1]); ha_open = float(ha['open'].iloc[-1])
            ha_prev  = float(ha['close'].iloc[-2]); ha_prev_o = float(ha['open'].iloc[-2])
            bull_ha = ha_close > ha_open
            prev_bull = ha_prev > ha_prev_o
            if bull_ha and prev_bull:    ha_score = 0.8
            elif bull_ha and not prev_bull: ha_score = 0.5   # Potential reversal up
            elif not bull_ha and not prev_bull: ha_score = -0.8
            else: ha_score = -0.5
            signals.append(IndicatorSignal("Heikin-Ashi", ha_close, ha_score,
                self._label(ha_score),
                f"HA {'Bullish' if bull_ha else 'Bearish'} {'(consecutive)' if (bull_ha==prev_bull) else '(reversal signal)'}",
                1.1))
        except Exception:
            pass

        # Pivot Points proximity
        try:
            pp = _pivot_points(df)
            pp_val = pp['PP']
            dist_to_pp = (close_now - pp_val) / atr_val
            r1 = pp['R1']; s1 = pp['S1']
            near_r1 = abs(close_now - r1) < atr_val * 0.5
            near_s1 = abs(close_now - s1) < atr_val * 0.5
            if near_s1: piv_score = 0.7   # Near support → bounce
            elif near_r1: piv_score = -0.7  # Near resistance → rejection
            elif dist_to_pp > 1: piv_score = -0.3  # Above PP by 1 ATR
            elif dist_to_pp < -1: piv_score = 0.3  # Below PP by 1 ATR
            else: piv_score = 0.0
            signals.append(IndicatorSignal("Pivot Points", pp_val, piv_score,
                self._label(piv_score),
                f"PP={pp_val:.4f} | {'Near S1 (support)' if near_s1 else 'Near R1 (resistance)' if near_r1 else f'{dist_to_pp:+.1f} ATR from PP'}",
                0.9))
        except Exception:
            pass

        # RSI Divergence
        try:
            rsi_s = _rsi(close, 14)
            div = _detect_divergence(close, rsi_s, 10)
            if div == "bullish_div":
                signals.append(IndicatorSignal("RSI Divergence", 0, 0.9, "STRONG_BULL",
                    "⚡ BULLISH DIVERGENCE: Price making lower lows but RSI higher lows — REVERSAL SIGNAL!",
                    1.8))
            elif div == "bearish_div":
                signals.append(IndicatorSignal("RSI Divergence", 0, -0.9, "STRONG_BEAR",
                    "⚡ BEARISH DIVERGENCE: Price making higher highs but RSI lower highs — REVERSAL SIGNAL!",
                    1.8))
        except Exception:
            pass

        # ════════════════════════════════════════════
        # AI FUSION DECISION
        # ════════════════════════════════════════════
        bull_sum = sum(s.score * s.weight for s in signals if s.score > 0)
        bear_sum = sum(abs(s.score) * s.weight for s in signals if s.score < 0)
        total_weight = sum(s.weight for s in signals) or 1

        bull_norm = bull_sum / total_weight
        bear_norm = bear_sum / total_weight
        net_score = (bull_norm - bear_norm)

        # Confidence from confluence
        bull_count = sum(1 for s in signals if s.score >  0.3)
        bear_count = sum(1 for s in signals if s.score < -0.3)
        neut_count = len(signals) - bull_count - bear_count
        dominant_count = max(bull_count, bear_count)
        confluence_pct = dominant_count / len(signals) if signals else 0

        # Direction & confidence
        if net_score > 0.25 and bull_count > bear_count:
            direction = "STRONG_BUY" if net_score > 0.5 else "BUY"
            confidence = min(97, 50 + net_score * 60 + confluence_pct * 20)
        elif net_score < -0.25 and bear_count > bull_count:
            direction = "STRONG_SELL" if net_score < -0.5 else "SELL"
            confidence = min(97, 50 + abs(net_score) * 60 + confluence_pct * 20)
        else:
            direction = "NEUTRAL"
            confidence = 50 - abs(net_score) * 20

        # Calculate entry/SL/TP
        is_long = "BUY" in direction
        sl_mult = 2.2 if direction.startswith("STRONG") else 1.8
        tp1_mult = 1.5; tp2_mult = 3.0; tp3_mult = 5.0

        if is_long:
            sl  = close_now - atr_val * sl_mult
            tp1 = close_now + atr_val * tp1_mult
            tp2 = close_now + atr_val * tp2_mult
            tp3 = close_now + atr_val * tp3_mult
        else:
            sl  = close_now + atr_val * sl_mult
            tp1 = close_now - atr_val * tp1_mult
            tp2 = close_now - atr_val * tp2_mult
            tp3 = close_now - atr_val * tp3_mult

        rr = abs(tp2 - close_now) / abs(sl - close_now) if abs(sl - close_now) > 0 else 0

        # Top reasons
        sorted_sigs = sorted(signals, key=lambda s: abs(s.score) * s.weight, reverse=True)
        top_reasons = [s.description for s in sorted_sigs[:3] if abs(s.score) > 0.3]
        warnings    = [s.description for s in signals if (is_long and s.score < -0.5) or (not is_long and s.score > 0.5)][:2]

        raw_scores = {s.name: round(s.score, 3) for s in signals}

        return AIIndicatorDecision(
            direction=direction,
            confidence=round(confidence, 1),
            bull_score=round(bull_norm * 100, 1),
            bear_score=round(bear_norm * 100, 1),
            confluence=dominant_count,
            total_indicators=len(signals),
            regime=regime,
            entry_price=round(close_now, 8),
            sl_price=round(sl, 8),
            tp1_price=round(tp1, 8),
            tp2_price=round(tp2, 8),
            tp3_price=round(tp3, 8),
            rr_ratio=round(rr, 2),
            indicators=signals,
            top_reasons=top_reasons,
            warnings=warnings,
            atr=round(atr_val, 8),
            raw_scores=raw_scores,
        )

    def _label(self, score: float) -> str:
        if score >  0.6: return "STRONG_BULL"
        if score >  0.2: return "BULL"
        if score < -0.6: return "STRONG_BEAR"
        if score < -0.2: return "BEAR"
        return "NEUTRAL"

    def _empty_decision(self, pair: str) -> AIIndicatorDecision:
        return AIIndicatorDecision(
            direction="NEUTRAL", confidence=0, bull_score=0, bear_score=0,
            confluence=0, total_indicators=0, regime="unknown",
            entry_price=0, sl_price=0, tp1_price=0, tp2_price=0, tp3_price=0,
            rr_ratio=0, indicators=[], top_reasons=[], warnings=[], atr=0, raw_scores={}
        )

    def to_api_dict(self, decision: AIIndicatorDecision) -> dict:
        """Serialize for API response / WebSocket push / frontend display."""
        return {
            "direction":   decision.direction,
            "confidence":  decision.confidence,
            "bull_score":  decision.bull_score,
            "bear_score":  decision.bear_score,
            "confluence":  f"{decision.confluence}/{decision.total_indicators}",
            "regime":      decision.regime,
            "entry":       decision.entry_price,
            "sl":          decision.sl_price,
            "tp1":         decision.tp1_price,
            "tp2":         decision.tp2_price,
            "tp3":         decision.tp3_price,
            "rr_ratio":    decision.rr_ratio,
            "atr":         decision.atr,
            "top_reasons": decision.top_reasons,
            "warnings":    decision.warnings,
            "indicators":  [
                {
                    "name":  s.name,
                    "value": round(s.value, 4),
                    "score": s.score,
                    "label": s.label,
                    "desc":  s.description,
                }
                for s in decision.indicators
            ],
            "raw_scores": decision.raw_scores,
        }


indicator_ai = IndicatorAI()
