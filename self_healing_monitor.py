"""
ai/indicators.py — Technical Indicator Computation
All indicators computed from raw OHLCV data.
Returns enriched DataFrame ready for strategy analysis.
"""
from __future__ import annotations
import pandas as pd
import numpy as np
from typing import Optional


def _ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def _sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(period).mean()


def _rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain  = delta.clip(lower=0).rolling(period).mean()
    loss  = (-delta.clip(upper=0)).rolling(period).mean()
    rs    = gain / loss.replace(0, 1e-9)
    return 100 - (100 / (1 + rs))


def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low  - close.shift()).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def _macd(series: pd.Series,
          fast: int = 12, slow: int = 26, signal: int = 9):
    fast_ema = _ema(series, fast)
    slow_ema = _ema(series, slow)
    macd_line   = fast_ema - slow_ema
    signal_line = _ema(macd_line, signal)
    histogram   = macd_line - signal_line
    return macd_line, signal_line, histogram


def _bollinger_bands(series: pd.Series, period: int = 20, std: float = 2.0):
    mid   = _sma(series, period)
    sigma = series.rolling(period).std()
    return mid + std * sigma, mid, mid - std * sigma


def _volume_ratio(vol: pd.Series, period: int = 20) -> pd.Series:
    avg = vol.rolling(period).mean()
    return vol / avg.replace(0, 1)


def _stochastic(df: pd.DataFrame, k: int = 14, d: int = 3):
    low_min  = df["low"].rolling(k).min()
    high_max = df["high"].rolling(k).max()
    k_pct    = 100 * (df["close"] - low_min) / (high_max - low_min + 1e-9)
    d_pct    = k_pct.rolling(d).mean()
    return k_pct, d_pct


def _williams_r(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high_max = df["high"].rolling(period).max()
    low_min  = df["low"].rolling(period).min()
    return -100 * (high_max - df["close"]) / (high_max - low_min + 1e-9)


def _cci(df: pd.DataFrame, period: int = 20) -> pd.Series:
    tp  = (df["high"] + df["low"] + df["close"]) / 3
    ma  = tp.rolling(period).mean()
    md  = tp.rolling(period).apply(lambda x: np.mean(np.abs(x - x.mean())))
    return (tp - ma) / (0.015 * md + 1e-9)


def _vwap(df: pd.DataFrame) -> pd.Series:
    tp  = (df["high"] + df["low"] + df["close"]) / 3
    if "volume" not in df.columns:
        return tp
    cum_vol   = df["volume"].cumsum()
    cum_tp_v  = (tp * df["volume"]).cumsum()
    return cum_tp_v / cum_vol.replace(0, 1)


def _market_phase(df: pd.DataFrame) -> str:
    """Classify market phase from last candle indicators."""
    l = df.iloc[-1]
    ema20  = float(l.get("ema20", 0))
    ema50  = float(l.get("ema50", 0))
    ema200 = float(l.get("ema200", 0))
    rsi    = float(l.get("rsi", 50))
    atr    = float(l.get("atr", 0))
    close  = float(l.get("close", 0))

    if ema20 > ema50 > ema200 and close > ema20:
        return "bull_trend"
    if ema20 < ema50 < ema200 and close < ema20:
        return "bear_trend"
    if rsi > 70:
        return "overbought"
    if rsi < 30:
        return "oversold"
    if atr > 0 and (close - ema20) / atr < 0.5:
        return "ranging"
    return "neutral"


def compute_all(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute all technical indicators on a OHLCV DataFrame.
    Adds columns in-place and returns enriched DataFrame.

    Required columns: open, high, low, close, volume (optional)
    """
    if df is None or len(df) < 20:
        return df

    close = df["close"]

    # Trend
    df["ema5"]   = _ema(close, 5)
    df["ema10"]  = _ema(close, 10)
    df["ema20"]  = _ema(close, 20)
    df["ema50"]  = _ema(close, 50)
    df["ema100"] = _ema(close, 100)
    df["ema200"] = _ema(close, 200)
    df["sma20"]  = _sma(close, 20)
    df["sma50"]  = _sma(close, 50)

    # Momentum
    df["rsi"]    = _rsi(close, 14)
    df["rsi_7"]  = _rsi(close, 7)

    macd, macd_sig, macd_hist = _macd(close)
    df["macd"]       = macd
    df["macd_signal"] = macd_sig
    df["macd_hist"]  = macd_hist

    k, d = _stochastic(df)
    df["stoch_k"] = k
    df["stoch_d"] = d
    df["williams_r"] = _williams_r(df)
    df["cci"]        = _cci(df)

    # Volatility
    df["atr"]    = _atr(df, 14)
    df["atr_7"]  = _atr(df, 7)
    df["atr_21"] = _atr(df, 21)

    bb_u, bb_m, bb_l = _bollinger_bands(close)
    df["bb_upper"] = bb_u
    df["bb_mid"]   = bb_m
    df["bb_lower"] = bb_l
    df["bb_width"] = (bb_u - bb_l) / bb_m.replace(0, 1)

    # Volume
    if "volume" in df.columns:
        df["vol_ratio"] = _volume_ratio(df["volume"])
        df["vwap"]      = _vwap(df)
    else:
        df["vol_ratio"] = 1.0
        df["vwap"]      = bb_m

    # Candle anatomy
    df["candle_body"]   = (df["close"] - df["open"]).abs()
    df["upper_wick"]    = df["high"] - df[["close","open"]].max(axis=1)
    df["lower_wick"]    = df[["close","open"]].min(axis=1) - df["low"]
    df["body_pct"]      = df["candle_body"] / df["atr"].replace(0, 1)

    # Price change
    df["pct_change"] = close.pct_change()
    df["pct_change_5"]  = close.pct_change(5)
    df["pct_change_20"] = close.pct_change(20)

    # Market phase (last row label)
    df["market_phase"] = _market_phase(df)

    return df


def ohlcv_to_df(raw: list, columns=None) -> pd.DataFrame:
    """Convert raw OHLCV list [[ts, o, h, l, c, v], ...] to DataFrame."""
    cols = columns or ["timestamp", "open", "high", "low", "close", "volume"]
    df = pd.DataFrame(raw, columns=cols[:len(raw[0])])
    for col in ["open", "high", "low", "close", "volume"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        df.set_index("timestamp", inplace=True)
    df.dropna(subset=["open","high","low","close"], inplace=True)
    return df
