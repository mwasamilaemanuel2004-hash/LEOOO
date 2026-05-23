"""
ai/market_feeling_engine.py — estrading.machine v9 GODMODE
══════════════════════════════════════════════════════════════════════════════
MARKET FEELING ENGINE — "Soko lina hisia"

The market is driven by human emotions. This engine reads those emotions
and trades accordingly. 7 emotional states detected simultaneously:

  EMOTION STATES:
  ① EUPHORIA    → Peak greed, everyone is buying. SHORT signal.
                  RSI>80, vol spike 5×, social mentions 10×, fear index <10
  ② GREED       → Strong bull run. BUY continuation or wait for pullback.
                  RSI 65-80, funding rate >0.03%, long/short ratio >2
  ③ OPTIMISM    → Healthy uptrend. BUY dips.
                  RSI 55-65, EMA8>EMA21>EMA50, funding neutral
  ④ NEUTRAL     → No clear emotion. Wait for signal.
                  RSI 40-55, low vol, balanced funding
  ⑤ ANXIETY     → Early fear. Positions size down, tighten stops.
                  RSI 35-45, vol rising, funding rate dropping
  ⑥ FEAR        → Strong sell pressure. SHORT confirmed.
                  RSI <35, vol spike, long liquidations rising
  ⑦ PANIC       → Maximum fear. BEST entry for longs (contrarian).
                  RSI <20, extreme vol spike, fear index >80

  FEELING INDICATORS (6 simultaneous sources):
  1. Technical Feeling   → RSI, BB position, EMA alignment
  2. Volume Feeling      → Volume vs average, buy/sell volume ratio
  3. Funding Feeling     → Perp funding rate (crowd positioning)
  4. Order Book Feeling  → Bid/ask imbalance, wall detection
  5. Momentum Feeling    → Rate of change, acceleration
  6. Volatility Feeling  → ATR vs historical, BB squeeze/expand

  SPECIAL STRATEGY: EMOTION EXPLOITATION
  Each emotional state has specific profit strategies:
  - Euphoria  → Short with 2× size (peak greed reversal)
  - Panic     → Long with 1.5× size (max fear bottom fishing)
  - Fear      → Short trend continuation
  - Greed     → Long pullbacks, tighten TP at euphoria threshold
  - Neutral   → Grid or arb only (no directional)
══════════════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations
import json, math, time, statistics
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Dict, Tuple
import numpy as np
import structlog

log = structlog.get_logger("market_feeling")

FEELING_STORAGE = Path("storage/market_feeling.json")
FEELING_STORAGE.parent.mkdir(parents=True, exist_ok=True)


# ── Emotion States ────────────────────────────────────────────
EMOTIONS = {
    "euphoria":  {"color":"#7f1d1d","icon":"🚀","score_range":(85,100),"trade":"contrarian_short","size_mult":2.0},
    "greed":     {"color":"#dc2626","icon":"😈","score_range":(70,85), "trade":"long_pullback",   "size_mult":1.2},
    "optimism":  {"color":"#22c55e","icon":"😊","score_range":(55,70), "trade":"buy_dips",        "size_mult":1.0},
    "neutral":   {"color":"#475569","icon":"😐","score_range":(45,55), "trade":"arb_grid",        "size_mult":0.5},
    "anxiety":   {"color":"#f97316","icon":"😰","score_range":(35,45), "trade":"reduce_size",     "size_mult":0.6},
    "fear":      {"color":"#ef4444","icon":"😱","score_range":(20,35), "trade":"short_trend",     "size_mult":1.3},
    "panic":     {"color":"#1e3a5f","icon":"💀","score_range":(0,20),  "trade":"contrarian_long", "size_mult":1.5},
}


@dataclass
class FeelingReading:
    """Complete market feeling snapshot."""
    symbol:           str
    timestamp:        float
    # Core emotion
    emotion:          str    = "neutral"
    emotion_score:    float  = 50.0   # 0=panic, 100=euphoria
    confidence:       float  = 50.0
    # Sub-scores
    technical_score:  float  = 50.0
    volume_score:     float  = 50.0
    funding_score:    float  = 50.0
    orderbook_score:  float  = 50.0
    momentum_score:   float  = 50.0
    volatility_score: float  = 50.0
    # Trading signal
    trade_signal:     str    = "neutral"  # buy/sell/neutral
    size_multiplier:  float  = 1.0
    entry_note:       str    = ""
    # Market context
    rsi:              float  = 50.0
    funding_rate:     float  = 0.0
    vol_ratio:        float  = 1.0
    bid_ask_imbalance:float  = 0.0
    atr_pct:          float  = 0.01
    trend_strength:   float  = 0.5


class MarketFeelingEngine:
    """
    Reads market emotions across 6 dimensions.
    Maps emotion state to optimal trading strategy.
    Learns which emotions predict best outcomes.
    """

    def __init__(self):
        self.history:     dict[str, deque] = {}   # symbol → deque of readings
        self.emotion_pnl: dict[str, list]  = {}   # emotion → [pnl outcomes]
        self.total_reads: int              = 0
        self._load()
        log.info("Market Feeling Engine initialized")

    # ── 1. TECHNICAL FEELING ─────────────────────────────────

    def _technical_score(self, candles: List[dict]) -> Tuple[float, dict]:
        """RSI + BB position + EMA alignment → 0-100 score."""
        if len(candles) < 50:
            return 50.0, {}

        closes = [c["close"] for c in candles]
        highs  = [c["high"]  for c in candles]
        lows   = [c["low"]   for c in candles]

        # RSI 14
        gains  = [max(0, closes[i]-closes[i-1]) for i in range(1,15)]
        losses = [max(0, closes[i-1]-closes[i]) for i in range(1,15)]
        ag, al = sum(gains)/14+1e-9, sum(losses)/14+1e-9
        rsi    = 100 - 100/(1 + ag/al)

        # EMA alignment
        e8=e21=e50=closes[0]
        for p in closes:
            e8  = p*(2/9)  + e8  *(7/9)
            e21 = p*(2/22) + e21 *(20/22)
            e50 = p*(2/51) + e50 *(49/51)
        close = closes[-1]
        ema_bull = close > e8 > e21 > e50
        ema_bear = close < e8 < e21 < e50

        # BB position
        bm  = np.mean(closes[-20:])
        bstd= np.std(closes[-20:]) + 1e-9
        bb_pos = (close - bm) / (2*bstd)   # -1=bottom band, +1=top band

        # Score: RSI heavily weighted + EMA + BB
        score = (
            rsi * 0.50 +
            (bb_pos * 25 + 50) * 0.25 +
            (80 if ema_bull else 20 if ema_bear else 50) * 0.25
        )
        return float(np.clip(score, 0, 100)), {"rsi": round(rsi,1), "bb_pos": round(bb_pos,3)}

    # ── 2. VOLUME FEELING ────────────────────────────────────

    def _volume_score(self, candles: List[dict]) -> float:
        """Volume surge and direction → 0-100."""
        vols   = [c.get("volume", 1) for c in candles]
        closes = [c["close"] for c in candles]
        if len(vols) < 20:
            return 50.0

        avg_vol   = np.mean(vols[-20:-1]) + 1e-9
        cur_vol   = vols[-1]
        vol_ratio = cur_vol / avg_vol

        # Direction: is vol on up or down candles?
        last3_bullish = sum(1 for i in [-3,-2,-1] if closes[i] > closes[i-1])
        dir_score     = last3_bullish / 3 * 100   # 0=all bear vol, 100=all bull vol

        # High volume in uptrend = greed; high vol in downtrend = fear
        if vol_ratio > 2:
            score = dir_score * 0.7 + 50 * 0.3   # vol spike
        else:
            score = 50.0   # neutral volume

        return float(np.clip(score, 0, 100))

    # ── 3. FUNDING FEELING ───────────────────────────────────

    def _funding_score(self, funding_rate: float) -> float:
        """Funding rate → crowd sentiment 0-100."""
        # Positive funding = longs paying = greed (score > 50)
        # Negative funding = shorts paying = fear (score < 50)
        # Scale: ±0.1% funding → full range
        score = 50 + funding_rate * 500   # 0.1% rate → +50 points
        return float(np.clip(score, 0, 100))

    # ── 4. ORDER BOOK FEELING ────────────────────────────────

    def _orderbook_score(self, bid_vol: float, ask_vol: float) -> float:
        """Bid/Ask imbalance → buying or selling pressure."""
        total = bid_vol + ask_vol + 1e-9
        imbalance = (bid_vol - ask_vol) / total   # -1=all selling, +1=all buying
        score = (imbalance + 1) / 2 * 100
        return float(np.clip(score, 0, 100))

    # ── 5. MOMENTUM FEELING ──────────────────────────────────

    def _momentum_score(self, candles: List[dict]) -> float:
        """Rate of change acceleration → 0-100."""
        if len(candles) < 20:
            return 50.0
        closes = [c["close"] for c in candles]
        # ROC 10
        roc10 = (closes[-1] - closes[-11]) / (closes[-11] + 1e-9) * 100
        # ROC 5
        roc5  = (closes[-1] - closes[-6])  / (closes[-6]  + 1e-9) * 100
        # Acceleration = ROC5 vs ROC10 (is momentum speeding up?)
        accel = roc5 - roc10/2
        score = np.tanh(accel * 5) * 25 + 50
        return float(np.clip(score, 0, 100))

    # ── 6. VOLATILITY FEELING ────────────────────────────────

    def _volatility_score(self, candles: List[dict]) -> float:
        """ATR expansion/contraction → 0-100 (high=volatile=extreme emotion)."""
        if len(candles) < 20:
            return 50.0
        closes = [c["close"] for c in candles]
        highs  = [c["high"]  for c in candles]
        lows   = [c["low"]   for c in candles]

        atrs = []
        for i in range(1, len(candles)):
            tr = max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1]))
            atrs.append(tr / (closes[i] + 1e-9) * 100)

        if len(atrs) < 14:
            return 50.0

        cur_atr = np.mean(atrs[-3:])
        avg_atr = np.mean(atrs[-20:])
        ratio   = cur_atr / (avg_atr + 1e-9)

        # High vol in uptrend = euphoria; high vol in downtrend = panic
        closes_trend = closes[-1] > closes[-10]
        if ratio > 2 and closes_trend:
            return 85.0   # euphoria-like spike
        if ratio > 2 and not closes_trend:
            return 15.0   # panic-like spike
        if ratio < 0.5:
            return 50.0   # squeeze = neutral
        return float(np.clip(50 + (ratio-1) * 20, 0, 100))

    # ── MASTER READING ───────────────────────────────────────

    def read_feeling(
        self,
        symbol:       str,
        candles:      List[dict],
        funding_rate: float = 0.0,
        bid_vol:      float = 1000,
        ask_vol:      float = 1000,
    ) -> FeelingReading:
        """
        Complete market feeling analysis.
        Returns FeelingReading with emotion, trade signal, and strategy.
        """
        t0 = time.time()

        tech_score, tech_meta  = self._technical_score(candles)
        vol_score              = self._volume_score(candles)
        fund_score             = self._funding_score(funding_rate)
        ob_score               = self._orderbook_score(bid_vol, ask_vol)
        mom_score              = self._momentum_score(candles)
        vola_score             = self._volatility_score(candles)

        # Weighted composite feeling score
        emotion_score = (
            tech_score  * 0.30 +
            vol_score   * 0.15 +
            fund_score  * 0.20 +
            ob_score    * 0.15 +
            mom_score   * 0.10 +
            vola_score  * 0.10
        )

        # Map score to emotion
        emotion = "neutral"
        for emo, cfg in EMOTIONS.items():
            lo, hi = cfg["score_range"]
            if lo <= emotion_score <= hi:
                emotion = emo
                break

        emo_cfg = EMOTIONS[emotion]

        # Confidence: how extreme is the emotion?
        # Near center (50) = low confidence. At extremes = high confidence.
        confidence = abs(emotion_score - 50) * 2   # 0-100

        # Generate trade signal and note
        trade_sig, entry_note = self._get_trade_signal(
            emotion, emotion_score, candles, funding_rate
        )

        # ATR for context
        closes = [c["close"] for c in candles[-20:]] if len(candles) >= 20 else [1.0]
        highs  = [c["high"]  for c in candles[-20:]] if len(candles) >= 20 else [1.0]
        lows   = [c["low"]   for c in candles[-20:]] if len(candles) >= 20 else [1.0]
        atrs   = []
        for i in range(1, len(closes)):
            tr = max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1]))
            atrs.append(tr)
        atr_pct = (np.mean(atrs[-5:]) / closes[-1] * 100) if atrs else 0.01

        reading = FeelingReading(
            symbol           = symbol,
            timestamp        = time.time(),
            emotion          = emotion,
            emotion_score    = round(emotion_score, 2),
            confidence       = round(confidence, 2),
            technical_score  = round(tech_score, 2),
            volume_score     = round(vol_score, 2),
            funding_score    = round(fund_score, 2),
            orderbook_score  = round(ob_score, 2),
            momentum_score   = round(mom_score, 2),
            volatility_score = round(vola_score, 2),
            trade_signal     = trade_sig,
            size_multiplier  = emo_cfg["size_mult"],
            entry_note       = entry_note,
            rsi              = tech_meta.get("rsi", 50.0),
            funding_rate     = funding_rate,
            vol_ratio        = vol_score / 50,
            bid_ask_imbalance= (bid_vol - ask_vol) / (bid_vol + ask_vol + 1e-9),
            atr_pct          = round(atr_pct, 4),
        )

        # Store history
        if symbol not in self.history:
            self.history[symbol] = deque(maxlen=200)
        self.history[symbol].append(reading)
        self.total_reads += 1

        return reading

    def _get_trade_signal(
        self,
        emotion: str,
        score:   float,
        candles: List[dict],
        funding: float,
    ) -> Tuple[str, str]:
        """Map emotion to specific trade signal and explanation."""

        if emotion == "euphoria":
            return ("sell",
                "🚀→📉 EUPHORIA DETECTED: Peak greed. Contrarian short. "
                "Everyone's in. Smart money selling to retail. "
                "Enter SHORT with 2× size. Target: -5 to -15%.")

        elif emotion == "greed":
            return ("buy",
                "😈 GREED: Strong bull trend. Buy pullbacks only. "
                "Don't chase breakouts — wait for dip to EMA8. "
                "Trail stop at 1.5×ATR. Watch for euphoria trigger.")

        elif emotion == "optimism":
            return ("buy",
                "😊 OPTIMISM: Healthy trend. Standard BUY setup. "
                "Full size entry on signal confirmation. "
                "2.0×ATR stop, 4.5×ATR target.")

        elif emotion == "neutral":
            return ("neutral",
                "😐 NEUTRAL: No emotional edge. "
                "Use arbitrage or grid only. "
                "No directional trades. Wait for emotion to develop.")

        elif emotion == "anxiety":
            return ("neutral",
                "😰 ANXIETY: Early fear detected. Reduce size 40%. "
                "Only A+ setups. Tighten stops to 1.5×ATR. "
                "Watch volume for escalation to fear/panic.")

        elif emotion == "fear":
            return ("sell",
                "😱 FEAR: Confirmed sell pressure. SHORT trend continuation. "
                f"Funding: {funding:.4f}% (negative = crowd is short = careful). "
                "1.3× size. Target cascade to next support.")

        elif emotion == "panic":
            return ("buy",
                "💀→🚀 PANIC BOTTOM: Maximum fear = maximum opportunity. "
                "RSI extreme, vol spike. Contrarian LONG. "
                "1.5× size. This is where 10-30% moves start. "
                "Tight stop 1.5×ATR. Big TP 8-20×ATR.")

        return ("neutral", "Waiting for clear emotional signal.")

    # ── EMOTION-SPECIFIC STRATEGIES ──────────────────────────

    def get_emotion_strategy(self, emotion: str) -> dict:
        """Return complete strategy parameters for given emotion."""
        strategies = {
            "euphoria": {
                "name":        "Euphoria Reversal Short",
                "direction":   "sell",
                "size_mult":   2.0,
                "sl_atr":      1.5,    # tight SL (may spike higher first)
                "tp_atr":      6.0,    # big TP (reversal = big move)
                "min_conf":    75.0,
                "entry_style": "at_market",
                "add_rule":    "add 10% every -1% move in our favor",
                "exit_rule":   "exit 50% at -5%, hold rest to -15%",
                "risk_note":   "Maximum conviction reversal play",
            },
            "greed": {
                "name":        "Greed Pullback Buy",
                "direction":   "buy",
                "size_mult":   1.2,
                "sl_atr":      2.0,
                "tp_atr":      4.0,
                "min_conf":    68.0,
                "entry_style": "limit_at_ema8_pullback",
                "exit_rule":   "exit at euphoria threshold (RSI>80)",
            },
            "optimism": {
                "name":        "Optimism Trend Follow",
                "direction":   "buy",
                "size_mult":   1.0,
                "sl_atr":      2.0,
                "tp_atr":      4.5,
                "min_conf":    65.0,
                "entry_style": "at_market_or_limit",
            },
            "neutral": {
                "name":        "Neutral Grid/Arb",
                "direction":   "both",
                "size_mult":   0.5,
                "sl_atr":      1.0,
                "tp_atr":      1.5,
                "min_conf":    90.0,   # very selective
                "entry_style": "grid_only",
            },
            "anxiety": {
                "name":        "Anxiety Defense Mode",
                "direction":   "neutral",
                "size_mult":   0.6,
                "sl_atr":      1.5,    # tighter stops
                "tp_atr":      3.0,
                "min_conf":    78.0,   # more selective
                "entry_style": "only_highest_quality",
            },
            "fear": {
                "name":        "Fear Short Continuation",
                "direction":   "sell",
                "size_mult":   1.3,
                "sl_atr":      2.0,
                "tp_atr":      5.0,
                "min_conf":    70.0,
                "entry_style": "cascade_short",
                "add_rule":    "add on each breakdown of support",
            },
            "panic": {
                "name":        "Panic Bottom Fisher",
                "direction":   "buy",
                "size_mult":   1.5,
                "sl_atr":      1.5,    # tight SL at panic low
                "tp_atr":      8.0,    # massive TP (reversals are huge)
                "min_conf":    65.0,
                "entry_style": "at_vol_spike_peak",
                "entry_note":  "Enter when volume STARTS to decrease from spike peak",
                "exit_rule":   "exit 30% at +5%, 30% at +10%, hold 40% to neutral",
            },
        }
        return strategies.get(emotion, strategies["neutral"])

    # ── LEARNING ─────────────────────────────────────────────

    def record_outcome(self, emotion: str, pnl_pct: float):
        """Learn which emotions lead to best outcomes."""
        if emotion not in self.emotion_pnl:
            self.emotion_pnl[emotion] = []
        self.emotion_pnl[emotion].append(pnl_pct)
        # Keep last 100 per emotion
        if len(self.emotion_pnl[emotion]) > 100:
            self.emotion_pnl[emotion] = self.emotion_pnl[emotion][-100:]

    def get_emotion_stats(self) -> dict:
        """Performance per emotion — shows which feelings are most profitable."""
        result = {}
        for emotion, pnls in self.emotion_pnl.items():
            if pnls:
                result[emotion] = {
                    "trades":    len(pnls),
                    "avg_pnl":   round(statistics.mean(pnls), 3),
                    "win_rate":  round(sum(1 for p in pnls if p>0)/len(pnls)*100, 1),
                    "best":      round(max(pnls), 2),
                    "worst":     round(min(pnls), 2),
                    "icon":      EMOTIONS[emotion]["icon"],
                    "color":     EMOTIONS[emotion]["color"],
                }
        return result

    def get_current_feelings(self) -> dict:
        """Get latest reading per symbol."""
        result = {}
        for symbol, hist in self.history.items():
            if hist:
                last = hist[-1]
                result[symbol] = {
                    "emotion":       last.emotion,
                    "score":         last.emotion_score,
                    "confidence":    last.confidence,
                    "signal":        last.trade_signal,
                    "icon":          EMOTIONS[last.emotion]["icon"],
                    "color":         EMOTIONS[last.emotion]["color"],
                    "rsi":           last.rsi,
                    "size_mult":     last.size_multiplier,
                    "entry_note":    last.entry_note,
                    "ts":            last.timestamp,
                }
        return result

    def _save(self):
        try:
            FEELING_STORAGE.write_text(json.dumps({
                "emotion_pnl":  self.emotion_pnl,
                "total_reads":  self.total_reads,
            }))
        except Exception as e:
            log.error("Feeling save failed", error=str(e))

    def _load(self):
        try:
            if FEELING_STORAGE.exists():
                d = json.loads(FEELING_STORAGE.read_text())
                self.emotion_pnl  = d.get("emotion_pnl", {})
                self.total_reads  = d.get("total_reads", 0)
        except Exception:
            pass


# ── Singleton ─────────────────────────────────────────────────
market_feeling = MarketFeelingEngine()
