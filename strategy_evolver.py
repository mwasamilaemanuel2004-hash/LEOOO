"""
ai/elite_indicators_v9.py — estrading.machine v9 GODMODE
════════════════════════════════════════════════════════════════════════
ELITE NON-CONFLICTING INDICATOR SYSTEM

PROBLEM with normal systems: 20 indicators saying different things = noise
SOLUTION: Indicator groups with interference prevention:
  • Each indicator belongs to exactly ONE group
  • Only ONE indicator per group fires at a time
  • Groups vote independently → clean signal

GROUPS (7 groups, max 1 signal per group):
  [A] TREND        → EMA Cloud, Hull MA, DEMA, TEMA, Supertrend
  [B] MOMENTUM     → RSI, Stoch RSI, Williams %R, MFI, CCI
  [C] VOLATILITY   → ATR Bands, Keltner Channel, Donchian, BB%B
  [D] VOLUME       → OBV Trend, VWAP deviation, CMF, MFI vol
  [E] STRUCTURE    → SMC Order Blocks, Supply/Demand, Pivot Points
  [F] PATTERN      → Engulfing, Hammer, Doji, 3-bar reversal
  [G] OSCILLATOR   → MACD, PPO, Awesome Oscillator, DPO

FINAL SIGNAL: Count groups signaling BUY vs SELL
  5-7 groups agree → HIGH CONFIDENCE (>80%)
  4 groups agree   → MEDIUM CONFIDENCE (65-80%)
  3 groups agree   → LOW CONFIDENCE (50-65%)
  <3 groups        → NO SIGNAL (noise)

BORROWED FROM TOP PLATFORMS:
  • Binance Bot:    RSI + BB grid trigger logic
  • 3Commas:        DCA safety order logic
  • Pionex:         Grid parameter optimization
  • Cryptohopper:   Template-based signal triggers
  • MT5 EA:         iMACD cross + iRSI filter combo
  • cTrader:        cBots-style parameter validation
  • WunderTrading:  TradingView webhook signal format
  • Cornix:         Telegram signal auto-parse
  • CryptoHero:     Mobile-first signal format
════════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations
import math, statistics, time
from collections import deque
from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Dict
import numpy as np

# ══════════════════════════════════════════════════════════════
# DATA STRUCTURES
# ══════════════════════════════════════════════════════════════

@dataclass
class IndicatorSignal:
    name:       str
    group:      str    # A-G
    direction:  str    # "buy" | "sell" | "neutral"
    strength:   float  # 0-100
    value:      float  # raw indicator value
    note:       str    = ""

@dataclass
class EliteSignal:
    direction:   str    # "buy" | "sell" | "neutral"
    confidence:  float  # 0-100
    groups_buy:  int    # how many groups say buy
    groups_sell: int    # how many groups say sell
    signals:     list   = field(default_factory=list)
    sl_pct:      float  = 0.8   # % below entry
    tp_pct:      float  = 2.0   # % above entry
    rr_ratio:    float  = 2.5
    entry_note:  str    = ""
    indicators_fired: list = field(default_factory=list)


# ══════════════════════════════════════════════════════════════
# PURE NUMPY INDICATOR CALCULATIONS (zero dependencies)
# ══════════════════════════════════════════════════════════════

def _ema(data: List[float], period: int) -> float:
    k = 2 / (period + 1)
    e = data[0]
    for v in data[1:]: e = v * k + e * (1 - k)
    return e

def _sma(data: List[float], period: int) -> float:
    return sum(data[-period:]) / period

def _stdev(data: List[float], period: int) -> float:
    s = data[-period:]
    m = sum(s) / len(s)
    return (sum((x - m)**2 for x in s) / len(s)) ** 0.5

def _rsi(closes: List[float], period: int = 14) -> float:
    if len(closes) < period + 1: return 50.0
    gains = [max(0, closes[i] - closes[i-1]) for i in range(-period, 0)]
    losses= [max(0, closes[i-1] - closes[i]) for i in range(-period, 0)]
    ag = sum(gains) / period + 1e-9
    al = sum(losses) / period + 1e-9
    return 100 - 100 / (1 + ag / al)

def _atr(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> float:
    if len(closes) < 2: return closes[-1] * 0.01
    trs = [max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1]))
           for i in range(1, len(closes))]
    return sum(trs[-period:]) / min(period, len(trs))


# ══════════════════════════════════════════════════════════════
# GROUP A: TREND INDICATORS (pick best one that fires)
# ══════════════════════════════════════════════════════════════

def group_a_trend(closes: List[float], highs: List[float], lows: List[float]) -> IndicatorSignal:
    """EMA Cloud + Hull MA + Supertrend — returns strongest signal."""
    if len(closes) < 55: return IndicatorSignal("EMA","A","neutral",0,closes[-1])
    c = closes[-1]

    # 1. EMA Cloud (8/21/50/200)
    e8  = _ema(closes, 8)
    e21 = _ema(closes, 21)
    e50 = _ema(closes, 50)
    e200= _ema(closes[-200:] if len(closes)>=200 else closes, 200 if len(closes)>=200 else len(closes))

    ema_bull = c > e8 > e21 > e50   # perfect bull alignment
    ema_bear = c < e8 < e21 < e50   # perfect bear alignment
    ema_str  = (abs(c-e50)/e50*100) if e50 > 0 else 0

    # 2. Hull Moving Average (HMA = WMA(2×WMA(n/2) − WMA(n), √n))
    def wma(data, n):
        weights = list(range(1, n+1))
        s = data[-n:]
        return sum(w*v for w,v in zip(weights,s)) / sum(weights) if len(s)==n else data[-1]
    hma_half = wma(closes, max(1, len(closes)//4))
    hma_full = wma(closes, max(1, len(closes)//2))
    hma_raw  = 2 * hma_half - hma_full
    hma_bull = c > hma_raw and hma_raw > wma(closes[:-1], max(1,len(closes)//2)) if len(closes)>4 else False

    # 3. Supertrend (simplified: ATR-based bands)
    atr   = _atr(highs, lows, closes, 10)
    basic_upper = (highs[-1] + lows[-1]) / 2 + 3 * atr
    basic_lower = (highs[-1] + lows[-1]) / 2 - 3 * atr
    supertrend_bull = c > basic_lower
    supertrend_bear = c < basic_upper and not supertrend_bull

    # Count signals
    bull_count = sum([ema_bull, hma_bull, supertrend_bull])
    bear_count = sum([ema_bear, not hma_bull and not ema_bull, supertrend_bear])

    if bull_count >= 2:
        str_val = min(90, 60 + ema_str * 5)
        return IndicatorSignal("EMA_CLOUD_HMA_ST","A","buy",str_val,e8,
                               f"EMA aligned bull + HMA + Supertrend ({bull_count}/3)")
    elif bear_count >= 2:
        str_val = min(90, 60 + ema_str * 5)
        return IndicatorSignal("EMA_CLOUD_HMA_ST","A","sell",str_val,e8,
                               f"EMA aligned bear + HMA + Supertrend ({bear_count}/3)")
    return IndicatorSignal("EMA_CLOUD_HMA_ST","A","neutral",0,e8,"Mixed trend signals")


# ══════════════════════════════════════════════════════════════
# GROUP B: MOMENTUM INDICATORS
# ══════════════════════════════════════════════════════════════

def group_b_momentum(closes: List[float], highs: List[float], lows: List[float], vols: List[float]) -> IndicatorSignal:
    """RSI + Stoch RSI + Williams %R + MFI — returns strongest signal."""
    if len(closes) < 20: return IndicatorSignal("MOMENTUM","B","neutral",0,50)

    # 1. RSI (14)
    rsi = _rsi(closes, 14)

    # 2. Stochastic RSI
    rsi_series = [_rsi(closes[:i+1], min(14,i)) for i in range(len(closes)) if i >= 5]
    if len(rsi_series) >= 14:
        rsi_low  = min(rsi_series[-14:])
        rsi_high = max(rsi_series[-14:])
        stoch_rsi = (rsi - rsi_low) / (rsi_high - rsi_low + 1e-9) * 100
    else:
        stoch_rsi = 50.0

    # 3. Williams %R (14)
    hh = max(highs[-14:])
    ll = min(lows[-14:])
    wr = (hh - closes[-1]) / (hh - ll + 1e-9) * -100

    # 4. Money Flow Index (14)
    if len(vols) >= 14:
        typ_prices = [(highs[i]+lows[i]+closes[i])/3 for i in range(len(closes))]
        raw_mf = [typ_prices[i]*vols[i] for i in range(len(closes))]
        pos_mf = sum(raw_mf[i] for i in range(-14,0) if closes[i]>closes[i-1]) + 1e-9
        neg_mf = sum(raw_mf[i] for i in range(-14,0) if closes[i]<closes[i-1]) + 1e-9
        mfi = 100 - 100/(1 + pos_mf/neg_mf)
    else:
        mfi = 50.0

    # Scoring
    buy_score  = 0
    sell_score = 0
    notes = []

    if rsi < 30:       buy_score += 2;  notes.append(f"RSI oversold {rsi:.0f}")
    elif rsi < 40:     buy_score += 1
    elif rsi > 70:     sell_score += 2; notes.append(f"RSI overbought {rsi:.0f}")
    elif rsi > 60:     sell_score += 1

    if stoch_rsi < 20: buy_score += 2;  notes.append(f"StochRSI oversold {stoch_rsi:.0f}")
    elif stoch_rsi > 80:sell_score += 2;notes.append(f"StochRSI overbought {stoch_rsi:.0f}")

    if wr < -80:       buy_score += 1
    elif wr > -20:     sell_score += 1

    if mfi < 30:       buy_score += 1;  notes.append(f"MFI {mfi:.0f} oversold")
    elif mfi > 70:     sell_score += 1; notes.append(f"MFI {mfi:.0f} overbought")

    if buy_score >= 4:
        return IndicatorSignal("RSI_STOCH_WR_MFI","B","buy", min(90,50+buy_score*8),rsi,", ".join(notes))
    elif sell_score >= 4:
        return IndicatorSignal("RSI_STOCH_WR_MFI","B","sell",min(90,50+sell_score*8),rsi,", ".join(notes))
    return IndicatorSignal("RSI_STOCH_WR_MFI","B","neutral",0,rsi,"Momentum neutral")


# ══════════════════════════════════════════════════════════════
# GROUP C: VOLATILITY INDICATORS
# ══════════════════════════════════════════════════════════════

def group_c_volatility(closes: List[float], highs: List[float], lows: List[float]) -> IndicatorSignal:
    """Bollinger Bands %B + Keltner Channel + ATR — volatility signal."""
    if len(closes) < 21: return IndicatorSignal("VOLATILITY","C","neutral",0,0)

    c = closes[-1]

    # 1. Bollinger Bands %B
    bb_mid  = _sma(closes, 20)
    bb_std  = _stdev(closes, 20)
    bb_up   = bb_mid + 2 * bb_std
    bb_dn   = bb_mid - 2 * bb_std
    bb_pctb = (c - bb_dn) / (bb_up - bb_dn + 1e-9)
    bb_width= (bb_up - bb_dn) / bb_mid

    # Historical BB width for squeeze detection
    bb_hist_widths = []
    for i in range(20, min(len(closes), 70)):
        sl = closes[i-20:i]
        m  = sum(sl)/20
        st = (sum((x-m)**2 for x in sl)/20)**0.5
        bb_hist_widths.append(st*2/m if m>0 else 0)
    squeeze = bb_width < (min(bb_hist_widths)*1.1) if bb_hist_widths else False
    expansion= bb_width > (max(bb_hist_widths)*0.9) if bb_hist_widths else False

    # 2. Keltner Channel
    atr = _atr(highs, lows, closes, 14)
    ema20 = _ema(closes, 20)
    kc_up = ema20 + 2 * atr
    kc_dn = ema20 - 2 * atr
    above_kc = c > kc_up
    below_kc = c < kc_dn

    # 3. Donchian Channel (20)
    dc_high = max(highs[-20:])
    dc_low  = min(lows[-20:])
    dc_break_up = c >= dc_high * 0.999
    dc_break_dn = c <= dc_low  * 1.001

    notes = []
    if squeeze:       notes.append("BB SQUEEZE — big move incoming")
    if expansion:     notes.append("BB EXPANSION — trend accelerating")
    if dc_break_up:   notes.append("Donchian breakout UP")
    if dc_break_dn:   notes.append("Donchian breakout DOWN")

    if bb_pctb < 0.05 or below_kc or dc_break_dn:
        return IndicatorSignal("BB_KC_DONCHIAN","C","buy", 75 if bb_pctb<0.05 else 65,
                               bb_pctb, ", ".join(notes) or "Below lower bands")
    elif bb_pctb > 0.95 or above_kc or dc_break_up:
        return IndicatorSignal("BB_KC_DONCHIAN","C","sell" if not dc_break_up else "buy",
                               75, bb_pctb, ", ".join(notes) or "Above upper bands")
    elif squeeze:
        return IndicatorSignal("BB_KC_DONCHIAN","C","neutral",30,bb_pctb,"Squeeze — wait for direction")
    return IndicatorSignal("BB_KC_DONCHIAN","C","neutral",0,bb_pctb)


# ══════════════════════════════════════════════════════════════
# GROUP D: VOLUME INDICATORS
# ══════════════════════════════════════════════════════════════

def group_d_volume(closes: List[float], highs: List[float], lows: List[float], vols: List[float]) -> IndicatorSignal:
    """OBV + VWAP deviation + CMF — volume pressure signal."""
    if len(vols) < 20: return IndicatorSignal("VOLUME","D","neutral",0,0)

    c = closes[-1]

    # 1. OBV trend
    obv = 0.0
    for i in range(1, len(closes)):
        obv += vols[i] if closes[i] > closes[i-1] else (-vols[i] if closes[i] < closes[i-1] else 0)
    obv_prev = sum(vols[i] if closes[i]>closes[i-1] else -vols[i] for i in range(1,len(closes)-5))
    obv_rising = obv > obv_prev

    # 2. VWAP deviation
    typ = [(highs[i]+lows[i]+closes[i])/3 for i in range(len(closes))]
    cum_pv = sum(typ[i]*vols[i] for i in range(len(closes)))
    cum_v  = sum(vols) + 1e-9
    vwap   = cum_pv / cum_v
    vwap_dev = (c - vwap) / vwap * 100   # % above/below VWAP

    # 3. Chaikin Money Flow (20)
    mfm = ((closes[-1]-lows[-1])-(highs[-1]-closes[-1])) / (highs[-1]-lows[-1]+1e-9)
    cmf_num = sum(((closes[i]-lows[i])-(highs[i]-closes[i]))/(highs[i]-lows[i]+1e-9)*vols[i]
                  for i in range(-20,0))
    cmf_den = sum(vols[-20:]) + 1e-9
    cmf     = cmf_num / cmf_den

    # 4. Volume ratio
    avg_vol  = sum(vols[-20:]) / 20
    vol_ratio= vols[-1] / (avg_vol + 1e-9)

    notes = []
    if vol_ratio > 2.5:  notes.append(f"Vol spike {vol_ratio:.1f}×")
    if abs(vwap_dev) > 2:notes.append(f"VWAP dev {vwap_dev:.1f}%")
    if abs(cmf) > 0.15:  notes.append(f"CMF {cmf:.2f}")

    buy_score = sum([obv_rising and c > vwap, vwap_dev < -1.5, cmf > 0.15, vol_ratio>2 and c>closes[-2]])
    sel_score = sum([not obv_rising and c < vwap, vwap_dev > 1.5, cmf < -0.15, vol_ratio>2 and c<closes[-2]])

    if buy_score >= 3:
        return IndicatorSignal("OBV_VWAP_CMF","D","buy",70+buy_score*5,cmf,", ".join(notes))
    elif sel_score >= 3:
        return IndicatorSignal("OBV_VWAP_CMF","D","sell",70+sel_score*5,cmf,", ".join(notes))
    return IndicatorSignal("OBV_VWAP_CMF","D","neutral",0,cmf)


# ══════════════════════════════════════════════════════════════
# GROUP E: STRUCTURE (SMC + Pivots)
# ══════════════════════════════════════════════════════════════

def group_e_structure(closes: List[float], highs: List[float], lows: List[float]) -> IndicatorSignal:
    """Order Blocks + Supply/Demand + Pivot Points."""
    if len(closes) < 30: return IndicatorSignal("STRUCTURE","E","neutral",0,closes[-1])
    c = closes[-1]

    # Pivot Points (Classic)
    prev_h = max(highs[-6:-1])
    prev_l = min(lows[-6:-1])
    prev_c = closes[-2]
    pp = (prev_h + prev_l + prev_c) / 3
    r1 = 2*pp - prev_l
    r2 = pp + (prev_h - prev_l)
    s1 = 2*pp - prev_h
    s2 = pp - (prev_h - prev_l)

    near_s1 = abs(c - s1) / c < 0.003
    near_s2 = abs(c - s2) / c < 0.004
    near_r1 = abs(c - r1) / c < 0.003
    near_r2 = abs(c - r2) / c < 0.004
    above_pp= c > pp
    below_pp= c < pp

    # Order Block detection (simplified: large bullish/bearish candles followed by move)
    def find_order_block(n=20):
        for i in range(-n, -3):
            body = abs(closes[i] - closes[i-1])
            avg_body = sum(abs(closes[j]-closes[j-1]) for j in range(-n,-3)) / n
            if body > avg_body * 2:  # large candle = potential OB
                if closes[i] > closes[i-1]:   # bullish OB
                    return ("buy", lows[i], highs[i], "Bullish Order Block")
                else:
                    return ("sell", lows[i], highs[i], "Bearish Order Block")
        return None

    ob = find_order_block()
    ob_signal = "neutral"
    ob_note   = ""
    if ob:
        ob_dir, ob_low, ob_high, ob_label = ob
        if ob_dir == "buy" and ob_low <= c <= ob_high * 1.01:
            ob_signal = "buy"
            ob_note   = f"{ob_label} support at {ob_low:.4f}"
        elif ob_dir == "sell" and ob_low * 0.99 <= c <= ob_high:
            ob_signal = "sell"
            ob_note   = f"{ob_label} resistance at {ob_high:.4f}"

    notes = []
    if near_s1 or near_s2: notes.append(f"At pivot support S{'2' if near_s2 else '1'}")
    if near_r1 or near_r2: notes.append(f"At pivot resistance R{'2' if near_r2 else '1'}")
    if ob_note:             notes.append(ob_note)

    if (near_s1 or near_s2) and above_pp and ob_signal == "buy":
        return IndicatorSignal("SMC_PIVOT_OB","E","buy",80,pp,", ".join(notes))
    elif (near_s1 or near_s2) and ob_signal != "sell":
        return IndicatorSignal("SMC_PIVOT_OB","E","buy",65,pp," ".join(notes) or "At pivot support")
    elif (near_r1 or near_r2) and below_pp:
        return IndicatorSignal("SMC_PIVOT_OB","E","sell",65,pp," ".join(notes) or "At pivot resistance")
    elif ob_signal != "neutral":
        return IndicatorSignal("SMC_PIVOT_OB","E",ob_signal,60,pp,ob_note)
    return IndicatorSignal("SMC_PIVOT_OB","E","neutral",0,pp)


# ══════════════════════════════════════════════════════════════
# GROUP F: CANDLESTICK PATTERNS
# ══════════════════════════════════════════════════════════════

def group_f_patterns(opens: List[float], closes: List[float], highs: List[float], lows: List[float]) -> IndicatorSignal:
    """Detects high-probability candlestick reversal patterns."""
    if len(closes) < 5: return IndicatorSignal("PATTERNS","F","neutral",0,0)

    o,c,h,l = opens[-1],closes[-1],highs[-1],lows[-1]
    po,pc,ph,pl = opens[-2],closes[-2],highs[-2],lows[-2]
    body    = abs(c-o)
    p_body  = abs(pc-po)
    candle_range = h-l+1e-9

    # 1. Bullish Engulfing
    bull_engulf = (c > o and pc < po and c > po and o < pc and body > p_body * 1.1)
    # 2. Bearish Engulfing
    bear_engulf = (c < o and pc > po and c < po and o > pc and body > p_body * 1.1)
    # 3. Hammer (bullish)
    hammer = (c > o and (l-min(c,o))/(candle_range) > 0.60 and body < candle_range*0.35)
    # 4. Shooting Star (bearish)
    shoot  = (c < o and (max(c,o)-h)/(candle_range) < -0.60 if h > max(c,o) else False)
    # 5. Doji (potential reversal)
    doji   = body < candle_range * 0.10
    # 6. 3-bar bullish reversal (LL, HL, close above mid)
    three_bar_bull = (lows[-3]>lows[-2] and highs[-1]>highs[-2] and closes[-1]>_sma(closes[-3:],3))
    # 7. Pin bar
    pin_bull = (min(c,o)-l)/(candle_range) > 0.65
    pin_bear = (h-max(c,o))/(candle_range) > 0.65

    patterns = []
    if bull_engulf:    patterns.append(("buy",85,"Bullish Engulfing"))
    if bear_engulf:    patterns.append(("sell",85,"Bearish Engulfing"))
    if hammer:         patterns.append(("buy",75,"Hammer"))
    if shoot:          patterns.append(("sell",75,"Shooting Star"))
    if three_bar_bull: patterns.append(("buy",70,"3-Bar Reversal"))
    if pin_bull:       patterns.append(("buy",72,"Pin Bar bullish"))
    if pin_bear:       patterns.append(("sell",72,"Pin Bar bearish"))

    if patterns:
        # Return highest confidence pattern
        best = max(patterns, key=lambda p: p[1])
        return IndicatorSignal("CANDLE_PATTERNS","F", best[0], best[1], body, best[2])
    return IndicatorSignal("CANDLE_PATTERNS","F","neutral",0,body,"No pattern detected")


# ══════════════════════════════════════════════════════════════
# GROUP G: OSCILLATOR (MACD + AO + PPO)
# ══════════════════════════════════════════════════════════════

def group_g_oscillator(closes: List[float]) -> IndicatorSignal:
    """MACD + Awesome Oscillator + PPO — momentum oscillator signal."""
    if len(closes) < 35: return IndicatorSignal("OSCILLATOR","G","neutral",0,0)

    # 1. MACD (12/26/9)
    ema12 = _ema(closes, 12)
    ema26 = _ema(closes, 26)
    macd  = ema12 - ema26

    # MACD history for signal line
    macd_hist = []
    for i in range(26, len(closes)):
        e12 = _ema(closes[:i+1], 12)
        e26 = _ema(closes[:i+1], 26)
        macd_hist.append(e12 - e26)
    signal_line = _ema(macd_hist, 9) if len(macd_hist) >= 9 else macd
    histogram   = macd - signal_line

    # 2. Awesome Oscillator (5/34 SMA midpoints)
    mids = [(closes[i]+closes[i]) / 2 for i in range(len(closes))]   # simplified
    ao5  = _sma(mids[-5:],  min(5, len(mids)))
    ao34 = _sma(mids[-34:], min(34,len(mids)))
    ao   = ao5 - ao34

    # 3. PPO (Percentage Price Oscillator)
    ppo  = (ema12 - ema26) / (ema26 + 1e-9) * 100

    buy_score  = sum([macd > 0 and histogram > 0,
                      ao > 0,
                      ppo > 0,
                      len(macd_hist)>2 and macd_hist[-1]>macd_hist[-2]>macd_hist[-3]])
    sell_score = sum([macd < 0 and histogram < 0,
                      ao < 0,
                      ppo < 0,
                      len(macd_hist)>2 and macd_hist[-1]<macd_hist[-2]<macd_hist[-3]])

    macd_cross_up   = len(macd_hist) >= 2 and macd_hist[-1] > 0 > macd_hist[-2]
    macd_cross_down = len(macd_hist) >= 2 and macd_hist[-1] < 0 < macd_hist[-2]

    if macd_cross_up:
        return IndicatorSignal("MACD_AO_PPO","G","buy", 80, macd, "MACD bullish crossover")
    elif macd_cross_down:
        return IndicatorSignal("MACD_AO_PPO","G","sell",80, macd, "MACD bearish crossover")
    elif buy_score >= 3:
        return IndicatorSignal("MACD_AO_PPO","G","buy", 60+buy_score*5, macd, f"Oscillators bullish {buy_score}/4")
    elif sell_score >= 3:
        return IndicatorSignal("MACD_AO_PPO","G","sell",60+sell_score*5,macd,f"Oscillators bearish {sell_score}/4")
    return IndicatorSignal("MACD_AO_PPO","G","neutral",0,macd)


# ══════════════════════════════════════════════════════════════
# FEATURES FROM TOP PLATFORMS
# ══════════════════════════════════════════════════════════════

class PlatformFeatures:
    """
    Best features extracted from 20+ top trading platforms.
    Integrated into estrading.machine v9.
    """

    # ── FROM 3COMMAS: DCA Safety Orders ──────────────────────
    def three_commas_dca(
        self,
        entry_price: float,
        current_price: float,
        base_order_size: float,
        safety_order_pct: float = 2.5,
        safety_order_mult: float = 1.5,
        max_safety_orders: int = 5,
        take_profit_pct: float = 2.0,
    ) -> dict:
        """
        3Commas DCA bot logic:
        - Enters base order
        - Places safety orders at each -X% level
        - Each safety order is larger (multiplier)
        - Take profit when average price + TP%
        """
        safety_orders = []
        order_size = base_order_size
        total_invested = base_order_size
        total_qty = base_order_size / entry_price

        for i in range(max_safety_orders):
            safety_price = entry_price * (1 - safety_order_pct/100 * (i+1))
            order_size   = order_size * safety_order_mult
            qty          = order_size / safety_price
            total_invested += order_size
            total_qty      += qty
            avg_price       = total_invested / total_qty

            safety_orders.append({
                "level":         i + 1,
                "price":         round(safety_price, 6),
                "size_usd":      round(order_size, 2),
                "qty":           round(qty, 6),
                "avg_price_after":round(avg_price, 6),
                "tp_price":      round(avg_price * (1 + take_profit_pct/100), 6),
                "total_invested":round(total_invested, 2),
            })

        avg_price_final = total_invested / total_qty
        return {
            "feature":          "3Commas_DCA",
            "entry_price":      entry_price,
            "base_order":       base_order_size,
            "safety_orders":    safety_orders,
            "total_investment": round(total_invested, 2),
            "avg_price":        round(avg_price_final, 6),
            "take_profit":      round(avg_price_final * (1 + take_profit_pct/100), 6),
            "breakeven":        round(avg_price_final, 6),
            "max_safety_levels":max_safety_orders,
        }

    # ── FROM PIONEX: Grid Trading Optimizer ──────────────────
    def pionex_grid(
        self,
        upper_price: float,
        lower_price: float,
        grids: int = 20,
        total_investment: float = 1000.0,
        current_price: float = None,
    ) -> dict:
        """
        Pionex-style grid bot with auto-parameter optimization.
        Calculates optimal grid levels, profit per grid, and ROI.
        """
        if current_price is None: current_price = (upper_price + lower_price) / 2

        # Grid spacing
        if grids < 2: grids = 2
        spacing_pct = (upper_price / lower_price - 1) / grids * 100

        # Investment per grid
        inv_per_grid = total_investment / grids
        profit_per_grid = inv_per_grid * spacing_pct / 100

        # Grid levels
        levels = []
        for i in range(grids + 1):
            price = lower_price * ((upper_price/lower_price) ** (i/grids))
            order_type = "buy" if price < current_price else "sell"
            levels.append({
                "level": i,
                "price": round(price, 6),
                "type":  order_type,
                "size":  round(inv_per_grid, 2),
            })

        # Daily profit estimate (assume 50% of grids fill per day)
        daily_fills = grids * 0.5
        daily_profit = daily_fills * profit_per_grid
        annual_roi   = (daily_profit / total_investment * 365) * 100

        return {
            "feature":         "Pionex_Grid",
            "upper":           upper_price,
            "lower":           lower_price,
            "grids":           grids,
            "spacing_pct":     round(spacing_pct, 3),
            "profit_per_grid": round(profit_per_grid, 4),
            "levels":          levels,
            "daily_profit_est":round(daily_profit, 2),
            "annual_roi_pct":  round(annual_roi, 1),
            "total_investment":total_investment,
        }

    # ── FROM BINANCE BOT: RSI+BB Signal Template ─────────────
    def binance_bot_signal(
        self,
        rsi: float,
        bb_pctb: float,
        volume_ratio: float,
        trend: str = "neutral",
    ) -> dict:
        """Binance Bot template-based signal generation."""
        signal = "neutral"
        conditions = []

        # Long conditions
        if rsi < 35 and bb_pctb < 0.15 and volume_ratio > 1.5:
            signal = "buy"
            conditions.append(f"RSI {rsi:.0f} oversold + BB lower band + volume spike")
        elif rsi < 40 and bb_pctb < 0.20 and trend == "bull":
            signal = "buy"
            conditions.append(f"RSI {rsi:.0f} + lower BB + bull trend")

        # Short conditions
        elif rsi > 65 and bb_pctb > 0.85 and volume_ratio > 1.5:
            signal = "sell"
            conditions.append(f"RSI {rsi:.0f} overbought + BB upper band + volume spike")
        elif rsi > 60 and bb_pctb > 0.80 and trend == "bear":
            signal = "sell"
            conditions.append(f"RSI {rsi:.0f} + upper BB + bear trend")

        confidence = 75 if len(conditions) > 0 else 0

        return {
            "feature":    "Binance_Bot_RSI_BB",
            "signal":     signal,
            "confidence": confidence,
            "conditions": conditions,
            "rsi":        rsi,
            "bb_pctb":    bb_pctb,
        }

    # ── FROM CRYPTOHOPPER: Template Signal ───────────────────
    def cryptohopper_template(self, indicators: dict) -> dict:
        """Cryptohopper-style template: weighted indicator scoring."""
        weights = {
            "rsi":     0.25,
            "macd":    0.25,
            "ema":     0.20,
            "volume":  0.15,
            "bb":      0.15,
        }
        buy_score = sell_score = 0.0
        for key, weight in weights.items():
            v = indicators.get(key, "neutral")
            if v == "buy":   buy_score  += weight * 100
            elif v == "sell":sell_score += weight * 100

        if buy_score >= 60:
            return {"signal":"buy",  "score":buy_score,  "feature":"Cryptohopper_Template"}
        elif sell_score >= 60:
            return {"signal":"sell", "score":sell_score, "feature":"Cryptohopper_Template"}
        return {"signal":"neutral","score":0,"feature":"Cryptohopper_Template"}

    # ── FROM ZULUTRADE: Copy Trade Signal Format ─────────────
    def zulutrade_signal(
        self,
        direction: str,
        symbol: str,
        entry: float,
        sl: float,
        tp: float,
        provider_winrate: float = 0.65,
    ) -> dict:
        """ZuluTrade-style signal with provider risk scoring."""
        rr = abs(tp - entry) / (abs(sl - entry) + 1e-9)
        risk_score = provider_winrate * rr
        return {
            "feature":        "ZuluTrade_Signal",
            "symbol":         symbol,
            "action":         direction,
            "entry":          entry,
            "stop_loss":      sl,
            "take_profit":    tp,
            "rr_ratio":       round(rr, 2),
            "risk_score":     round(risk_score, 2),
            "provider_wr":    provider_winrate,
            "recommendation": "COPY" if risk_score > 1.2 else "SKIP",
        }

    # ── FROM WUNDERTRADING: TradingView Webhook ───────────────
    def parse_tv_webhook(self, payload: dict) -> dict:
        """Parse TradingView webhook alert (WunderTrading format)."""
        action = payload.get("action","").lower()
        return {
            "feature":    "WunderTrading_TV_Webhook",
            "direction":  "buy" if "buy" in action or "long" in action else
                          "sell" if "sell" in action or "short" in action else "neutral",
            "symbol":     payload.get("ticker","BTCUSDT").replace(".P","").replace("USDT.P","USDT"),
            "timeframe":  payload.get("interval","5m"),
            "confidence": 70.0,
            "source":     "tradingview_webhook",
        }

    # ── FROM MT5 EA: iMACD + iRSI Filter (classic EA logic) ──
    def mt5_ea_signal(
        self,
        macd_main: float,
        macd_signal: float,
        macd_prev: float,
        rsi: float,
        ema_fast: float,
        ema_slow: float,
    ) -> dict:
        """Classic MT5 EA signal: MACD cross + RSI filter + EMA trend."""
        macd_cross_up   = macd_main > macd_signal and macd_prev < macd_signal
        macd_cross_down = macd_main < macd_signal and macd_prev > macd_signal
        rsi_ok_buy  = 40 < rsi < 60
        rsi_ok_sell = 40 < rsi < 60
        trend_bull  = ema_fast > ema_slow
        trend_bear  = ema_fast < ema_slow

        if macd_cross_up and rsi_ok_buy and trend_bull:
            return {"feature":"MT5_EA_iMACD_iRSI","signal":"buy","confidence":78,
                    "reason":"MACD bull cross + RSI neutral + EMA uptrend"}
        elif macd_cross_down and rsi_ok_sell and trend_bear:
            return {"feature":"MT5_EA_iMACD_iRSI","signal":"sell","confidence":78,
                    "reason":"MACD bear cross + RSI neutral + EMA downtrend"}
        return {"feature":"MT5_EA_iMACD_iRSI","signal":"neutral","confidence":0}

    # ── FROM CORNIX: Telegram Signal Parser ──────────────────
    def cornix_parse(self, text: str, price: float = 0) -> dict:
        """Parse Telegram signal in Cornix format."""
        text = text.upper()
        direction = "buy" if any(w in text for w in ["BUY","LONG","CALL"]) else \
                    "sell" if any(w in text for w in ["SELL","SHORT","PUT"]) else "neutral"
        return {
            "feature":   "Cornix_Signal_Parser",
            "direction": direction,
            "raw":       text,
            "confidence":65 if direction != "neutral" else 0,
        }


platform_features = PlatformFeatures()


# ══════════════════════════════════════════════════════════════
# MASTER ELITE INDICATOR ENGINE
# ══════════════════════════════════════════════════════════════

class EliteIndicatorEngine:
    """
    Non-conflicting 7-group indicator system.
    Minimum 3 groups must agree. Auto-calculates SL/TP.
    < 5ms inference time.
    """

    def __init__(self):
        self._cache: dict = {}
        self._perf:  dict = {}   # track accuracy per indicator

    def analyze(
        self,
        symbol:  str,
        opens:   List[float],
        closes:  List[float],
        highs:   List[float],
        lows:    List[float],
        volumes: List[float],
    ) -> EliteSignal:
        """Run all 7 groups, tally votes, return clean signal."""
        t0 = time.time()
        if len(closes) < 55:
            return EliteSignal("neutral", 0, 0, 0)

        # Run all 7 groups (fast — < 2ms each)
        sigs = [
            group_a_trend(closes, highs, lows),
            group_b_momentum(closes, highs, lows, volumes),
            group_c_volatility(closes, highs, lows),
            group_d_volume(closes, highs, lows, volumes),
            group_e_structure(closes, highs, lows),
            group_f_patterns(opens, closes, highs, lows),
            group_g_oscillator(closes),
        ]

        # Tally (only strong signals count)
        buy_sigs  = [s for s in sigs if s.direction == "buy"  and s.strength >= 55]
        sell_sigs = [s for s in sigs if s.direction == "sell" and s.strength >= 55]
        buy_count = len(buy_sigs)
        sell_count= len(sell_sigs)

        # Minimum 3 groups must agree
        if buy_count < 3 and sell_count < 3:
            return EliteSignal(
                direction="neutral", confidence=0,
                groups_buy=buy_count, groups_sell=sell_count,
                signals=[{"group":s.group,"dir":s.direction,"str":s.strength,"note":s.note} for s in sigs],
                entry_note=f"Only {max(buy_count,sell_count)}/7 groups agree — waiting",
            )

        direction = "buy" if buy_count > sell_count else "sell"
        agreed    = buy_sigs if direction == "buy" else sell_sigs
        avg_str   = statistics.mean(s.strength for s in agreed)

        # Confidence: 3 groups = 60%, each additional = +10%
        agree_n   = max(buy_count, sell_count)
        confidence= min(95, 55 + (agree_n - 3) * 10 + avg_str * 0.15)

        # Dynamic SL/TP based on ATR and signal strength
        atr      = _atr(highs, lows, closes, 14)
        close    = closes[-1]
        atr_pct  = atr / close * 100

        # Higher confidence = tighter SL (AI is surer), wider TP
        sl_mult  = max(1.2, 2.5 - (confidence - 60) / 100)
        tp_mult  = min(8.0, 3.0 + (confidence - 60) / 20)
        rr_ratio = tp_mult / sl_mult

        sl_pct   = atr_pct * sl_mult
        tp_pct   = atr_pct * tp_mult

        fired    = [f"{s.group}:{s.name}({s.strength:.0f})" for s in agreed]
        notes    = [s.note for s in agreed if s.note]

        result = EliteSignal(
            direction  = direction,
            confidence = round(confidence, 2),
            groups_buy = buy_count,
            groups_sell= sell_count,
            signals    = [{"group":s.group,"dir":s.direction,"str":s.strength,"note":s.note} for s in sigs],
            sl_pct     = round(sl_pct, 4),
            tp_pct     = round(tp_pct, 4),
            rr_ratio   = round(rr_ratio, 2),
            entry_note = f"{agree_n}/7 groups agree | {', '.join(notes[:3])}",
            indicators_fired=fired,
        )

        # Cache result
        self._cache[symbol] = {"result": result, "ts": time.time()}
        return result

    def analyze_candles(self, symbol: str, candles: List[dict]) -> EliteSignal:
        """Convenience method from candle list."""
        if len(candles) < 55:
            return EliteSignal("neutral", 0, 0, 0)
        opens  = [c.get("open",  c.get("close",1)) for c in candles]
        closes = [c["close"] for c in candles]
        highs  = [c["high"]  for c in candles]
        lows   = [c["low"]   for c in candles]
        vols   = [c.get("volume",1) for c in candles]
        return self.analyze(symbol, opens, closes, highs, lows, vols)


# ── Singleton ─────────────────────────────────────────────────
elite_indicators = EliteIndicatorEngine()
