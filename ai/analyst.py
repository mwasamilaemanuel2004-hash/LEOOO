import numpy as np
import pandas as pd
from typing import Dict, List
import structlog

log = structlog.get_logger("ai_analyst")

class AIAnalyst:
    """
    Combines technical indicators, market structure, and liquidity analysis
    to generate institutional-grade trade signals.
    """

    def analyze_market(self, ohlcv: pd.DataFrame) -> Dict:
        # Technical Indicators
        df = self._compute_indicators(ohlcv)

        # Market Structure Analysis
        ms = self._analyze_structure(df)

        # Confluence Score
        score = self._calculate_confluence(df, ms)

        return {
            "trend": ms["trend"],
            "support": ms["support"],
            "resistance": ms["resistance"],
            "confluence_score": score,
            "action": "buy" if score > 75 else "sell" if score < 25 else "hold",
            "reasoning": f"Trend: {ms['trend']}, RSI: {df['rsi'].iloc[-1]:.1f}, VWAP Confluence: {ms['vwap_aligned']}"
        }

    def _compute_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        # Simple implementations for demonstration
        df['sma_20'] = df['close'].rolling(20).mean()
        df['sma_50'] = df['close'].rolling(50).mean()

        # RSI
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        df['rsi'] = 100 - (100 / (1 + rs))

        # VWAP
        df['vwap'] = (df['volume'] * (df['high'] + df['low'] + df['close']) / 3).cumsum() / df['volume'].cumsum()

        return df

    def _analyze_structure(self, df: pd.DataFrame) -> Dict:
        last = df.iloc[-1]
        prev = df.iloc[-2]

        trend = "bullish" if last['sma_20'] > last['sma_50'] else "bearish"
        vwap_aligned = (last['close'] > last['vwap'] and trend == "bullish") or                        (last['close'] < last['vwap'] and trend == "bearish")

        return {
            "trend": trend,
            "vwap_aligned": vwap_aligned,
            "support": df['low'].rolling(50).min().iloc[-1],
            "resistance": df['high'].rolling(50).max().iloc[-1]
        }

    def _calculate_confluence(self, df: pd.DataFrame, ms: Dict) -> float:
        score = 50.0
        last = df.iloc[-1]

        # Trend alignment
        if ms["trend"] == "bullish": score += 10
        else: score -= 10

        # RSI
        if last['rsi'] < 30: score += 15 # Oversold
        elif last['rsi'] > 70: score -= 15 # Overbought

        # VWAP alignment
        if ms["vwap_aligned"]: score += 10

        return max(0, min(100, score))

ai_analyst = AIAnalyst()
