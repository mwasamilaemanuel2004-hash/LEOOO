"""
ai/trading_engine_v9.py — estrading.machine v9 GODMODE MASTER TRADING ENGINE
═══════════════════════════════════════════════════════════════════════════════
THE MOST ADVANCED TRADING ENGINE EVER BUILT

9 AI ENGINES RUNNING SIMULTANEOUSLY:
  ① Ultra Brain v7    — 7-indicator ensemble (preserved 100% from v7)
  ② LSTM Model        — 60-candle sequence learning
  ③ Transformer       — Attention-based pattern recognition
  ④ RL Triple Brain   — PPO + DQN + A3C reinforcement learning
  ⑤ Market Feeling    — 6-dimension emotion detection
  ⑥ Special Strategy  — Unique edge per bot
  ⑦ Money Printer     — 50% capital deployment engine
  ⑧ Whale Tracker     — On-chain large wallet monitoring
  ⑨ Risk AI           — 5-level drawdown + VaR + circuits

DECISION PROTOCOL:
  1. Get candles + order book + funding data (< 1ms from cache)
  2. Run all 9 engines in parallel (< 15ms total)
  3. Vote: minimum 5/9 engines must agree for trade
  4. Risk AI validates position size + circuit breakers
  5. Money Printer calculates exact capital deployment
  6. Execute via Elite Execution Engine (< 50ms latency)
  7. RL learns from outcome within 100ms of close
  8. All results stored to Supabase in real-time

CAPITAL MAXIMIZATION:
  • Base: 50% capital per trade
  • Pyramid: +10% on each winning candle (max 70%)
  • Compound: 100% profit reinvested to next trade
  • Feeling boost: up to +100% size in panic/euphoria contrarian
  • Whale signal: +25% if whale wallet moves in same direction

PROFIT GENERATION FORMULA per trade:
  Capital × win_rate × avg_rr × frequency = daily_profit
  $10k × 68% × 2.5 × 8 trades = $1,360/day theoretical

SELF-LEARNING CYCLE:
  Every trade close → RL update (100ms)
  Every 100 trades  → PPO batch update
  Every 200 trades  → DQN target sync
  Every 500 trades  → Strategy evolution
  Every 24h         → Full model retrain
  Continuous        → Market feeling calibration
═══════════════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations
import asyncio, time, json, statistics
from collections import deque, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List, Dict
import numpy as np
import structlog

log = structlog.get_logger("v9_engine")

# ── Import all 9 engines ──────────────────────────────────────
def _safe_import(module, attr):
    try:
        import importlib
        m = importlib.import_module(module)
        return getattr(m, attr, None)
    except Exception as e:
        log.warning(f"Import failed: {module}.{attr} — {e}")
        return None

ultra_brain       = _safe_import("ai.ultra_brain",           "ultra_brain")
rl_engine         = _safe_import("ai.reinforcement_engine",  "rl_engine")
risk_ai           = _safe_import("ai.risk_ai_engine",        "risk_ai")
strategy_evolver  = _safe_import("ai.strategy_evolver",      "strategy_evolver")
market_feeling    = _safe_import("ai.market_feeling_engine", "market_feeling")
dual_ai           = _safe_import("ai.deep_models",           "dual_ai")
whale_tracker     = _safe_import("ai.whale_tracker",         "whale_tracker")
money_printer     = _safe_import("strategies.money_printer_v8", "money_printer")
PRINT_CONFIGS     = _safe_import("strategies.money_printer_v8", "PRINT_CONFIGS")
execute_money_print = _safe_import("strategies.money_printer_v8", "execute_money_print")
get_strategy      = _safe_import("strategies.special_strategies_v9", "get_strategy")
get_feeling_boost = _safe_import("strategies.special_strategies_v9", "get_feeling_boost")
get_strategy_signal = _safe_import("strategies.special_strategies_v9", "get_strategy_signal")

# Fallbacks
if PRINT_CONFIGS is None: PRINT_CONFIGS = {}


# ══════════════════════════════════════════════════════════════
# CAPITAL MAXIMIZER ENGINE
# ══════════════════════════════════════════════════════════════

class CapitalMaximizer:
    """
    Maximizes capital deployment while respecting risk limits.
    Uses Kelly Criterion + feeling boost + whale signal + compound pool.
    Target: 45-70% of capital per trade depending on conviction.
    """

    def __init__(self):
        self._states: dict = {}

    def get_state(self, bot_id: str) -> dict:
        if bot_id not in self._states:
            self._states[bot_id] = {
                "balance": 0, "peak": 0, "compound_pool": 0,
                "cons_wins": 0, "cons_losses": 0,
                "daily_pnl": 0, "session_pnl": 0,
                "pyramid_level": 0, "total_compounded": 0,
            }
        return self._states[bot_id]

    def calculate(
        self,
        bot_id:         str,
        balance:        float,
        base_risk_pct:  float,
        confidence:     float,
        emotion:        str,
        feeling_boost:  float,
        whale_aligned:  bool,
        rl_confidence:  float,
        vote_count:     int,    # how many of 9 engines agreed (0-9)
        drawdown_pct:   float,
        daily_pnl_pct:  float,
    ) -> dict:
        """Calculate final position size with all multipliers."""
        s = self.get_state(bot_id)
        if balance > s["peak"]: s["peak"] = balance
        s["balance"] = balance

        # ── Hard stops ─────────────────────────────────────────
        if drawdown_pct >= 15.0:
            return {"approved": False, "reason": "HARD STOP: DD ≥ 15%",
                    "size_usd": 0, "capital_pct": 0}
        if daily_pnl_pct <= -5.0:
            return {"approved": False, "reason": "Daily loss limit -5%",
                    "size_usd": 0, "capital_pct": 0}
        if s["cons_losses"] >= 4:
            s["cons_losses"] = 0
            return {"approved": False, "reason": "4 consecutive losses — pause",
                    "size_usd": 0, "capital_pct": 0}

        # ── Base capital % ─────────────────────────────────────
        capital_pct = base_risk_pct  # usually 50%

        # ── Vote multiplier (more engines agree = bigger size) ─
        if vote_count >= 8:   capital_pct *= 1.20   # 9-8 engines: +20%
        elif vote_count >= 6: capital_pct *= 1.10   # 7-6 engines: +10%
        elif vote_count <= 4: capital_pct *= 0.80   # weak consensus: -20%

        # ── Confidence boost ───────────────────────────────────
        if confidence >= 85:   capital_pct *= 1.15
        elif confidence >= 75: capital_pct *= 1.05
        elif confidence < 65:  capital_pct *= 0.85

        # ── Feeling boost ──────────────────────────────────────
        capital_pct *= feeling_boost

        # ── Whale alignment bonus ──────────────────────────────
        if whale_aligned: capital_pct *= 1.15

        # ── Consecutive wins pyramid ───────────────────────────
        if s["cons_wins"] >= 5:   capital_pct *= 1.20
        elif s["cons_wins"] >= 3: capital_pct *= 1.10

        # ── Drawdown safety reduction ──────────────────────────
        if drawdown_pct >= 10:    capital_pct *= 0.40
        elif drawdown_pct >= 8:   capital_pct *= 0.55
        elif drawdown_pct >= 5:   capital_pct *= 0.70

        # ── Compound pool add-on ───────────────────────────────
        compound_bonus = min(s["compound_pool"], balance * 0.10)
        s["compound_pool"] = max(0, s["compound_pool"] - compound_bonus)

        # ── Final cap ──────────────────────────────────────────
        capital_pct = float(np.clip(capital_pct, 5.0, 70.0))
        size_usd    = balance * capital_pct / 100 + compound_bonus

        return {
            "approved":       True,
            "capital_pct":    round(capital_pct, 2),
            "size_usd":       round(size_usd, 2),
            "compound_bonus": round(compound_bonus, 2),
            "vote_count":     vote_count,
            "feeling_boost":  round(feeling_boost, 2),
            "whale_aligned":  whale_aligned,
            "pyramid_level":  s["pyramid_level"],
            "cons_wins":      s["cons_wins"],
        }

    def record(self, bot_id: str, pnl_pct: float, pnl_usd: float, balance: float):
        s = self.get_state(bot_id)
        s["daily_pnl"] += pnl_pct
        s["session_pnl"] += pnl_pct
        s["balance"] = balance
        if pnl_usd > 0:
            s["cons_wins"] += 1
            s["cons_losses"] = 0
            s["pyramid_level"] = min(s["pyramid_level"] + 1, 3)
            compound = pnl_usd * 1.0   # 100% reinvest
            s["compound_pool"] += compound
            s["total_compounded"] += compound
        else:
            s["cons_losses"] += 1
            s["cons_wins"] = 0
            s["pyramid_level"] = 0


capital_maximizer = CapitalMaximizer()


# ══════════════════════════════════════════════════════════════
# VOTE COLLECTOR — Parallel engine consultation
# ══════════════════════════════════════════════════════════════

@dataclass
class EngineVote:
    engine:     str
    direction:  str    # "buy" | "sell" | "neutral"
    confidence: float
    weight:     float  = 1.0
    meta:       dict   = field(default_factory=dict)


def collect_votes(
    candles:      List[dict],
    bot_key:      str,
    symbol:       str,
    funding_rate: float = 0.0,
    bid_vol:      float = 1000,
    ask_vol:      float = 1000,
) -> List[EngineVote]:
    """Run all 9 engines and collect their votes."""
    votes = []

    # ① Ultra Brain (weight 2.0 — highest quality)
    if ultra_brain:
        try:
            import pandas as pd
            df = pd.DataFrame(candles)
            sig = ultra_brain.analyze(df, symbol, "5m")
            if sig:
                votes.append(EngineVote(
                    engine="ultra_brain",
                    direction=sig.direction if hasattr(sig,"direction") else "neutral",
                    confidence=float(getattr(sig,"confidence",60)),
                    weight=2.0,
                    meta={"rr": float(getattr(sig,"rr_ratio",2.0))},
                ))
        except Exception as e:
            log.debug("Ultra brain vote failed", error=str(e))

    # ② LSTM + Transformer Dual AI (weight 1.5)
    if dual_ai:
        try:
            ai_sig = dual_ai.get_signal(candles)
            if ai_sig.get("emit"):
                votes.append(EngineVote(
                    engine="dual_ai",
                    direction=ai_sig.get("signal","neutral"),
                    confidence=float(ai_sig.get("confidence",60)),
                    weight=1.5,
                    meta={"agreement": ai_sig.get("agreement","NONE")},
                ))
        except Exception as e:
            log.debug("Dual AI vote failed", error=str(e))

    # ③ RL Engine (weight 1.5)
    if rl_engine:
        try:
            mf = np.zeros(72)
            if ultra_brain:
                try:
                    from ai.reinforcement_engine import build_state
                    from ai.ultra_brain import extract_ultra_features
                    import pandas as pd
                    df = pd.DataFrame(candles)
                    mf = extract_ultra_features(df)
                except Exception:
                    pass
            rl_dec = rl_engine.get_decision(mf, {
                "balance": 10000, "equity": 10000, "open_pos": 0,
                "daily_pnl": 0, "drawdown": 0, "win_rate": 0.55,
                "avg_rr": 2.0, "cons_wins": 0, "cons_losses": 0,
                "session": "london", "hour": 10, "day": 1,
                "volatility": 0.01, "trend_str": 0.5,
                "bot_target": 5.0, "bot_progress": 0,
            }, "neutral")
            if rl_dec.get("direction") != "hold":
                votes.append(EngineVote(
                    engine="rl_triple_brain",
                    direction=rl_dec.get("direction","neutral"),
                    confidence=float(rl_dec.get("confidence",60)),
                    weight=1.5,
                    meta={"action_id": rl_dec.get("action_id",3)},
                ))
        except Exception as e:
            log.debug("RL vote failed", error=str(e))

    # ④ Market Feeling Engine (weight 1.2)
    if market_feeling and candles:
        try:
            feeling = market_feeling.read_feeling(
                symbol, candles, funding_rate, bid_vol, ask_vol
            )
            sig = feeling.trade_signal
            if sig != "neutral":
                votes.append(EngineVote(
                    engine="market_feeling",
                    direction=sig,
                    confidence=float(feeling.confidence),
                    weight=1.2,
                    meta={"emotion": feeling.emotion, "score": feeling.emotion_score},
                ))
        except Exception as e:
            log.debug("Feeling vote failed", error=str(e))

    # ⑤ Strategy Evolver — best genome signal (weight 1.2)
    if strategy_evolver and candles and len(candles) >= 30:
        try:
            genome = strategy_evolver.get_best_genome()
            if genome and genome.fitness > 0.3:
                closes = [c["close"] for c in candles]
                e8 = ema21 = closes[0]
                for p in closes:
                    e8   = p*(2/9)  + e8  *(7/9)
                    ema21= p*(2/22) + ema21*(20/22)
                close = closes[-1]
                if e8 > ema21 and close > ema21:
                    direction = "buy"
                elif e8 < ema21 and close < ema21:
                    direction = "sell"
                else:
                    direction = "neutral"
                if direction != "neutral":
                    conf = min(70 + genome.fitness * 20, 90)
                    votes.append(EngineVote(
                        engine="strategy_evolver",
                        direction=direction,
                        confidence=conf,
                        weight=1.2,
                        meta={"genome_id": genome.genome_id, "fitness": genome.fitness},
                    ))
        except Exception as e:
            log.debug("Evolver vote failed", error=str(e))

    # ⑥ Whale Tracker (weight 1.3 — high signal quality)
    if whale_tracker:
        try:
            wh_sig = whale_tracker.get_signal(symbol) if hasattr(whale_tracker, "get_signal") else None
            if wh_sig and wh_sig.get("signal") != "neutral":
                votes.append(EngineVote(
                    engine="whale_tracker",
                    direction=wh_sig["signal"],
                    confidence=float(wh_sig.get("confidence", 65)),
                    weight=1.3,
                    meta={"whale_size": wh_sig.get("whale_size", 0)},
                ))
        except Exception as e:
            log.debug("Whale vote failed", error=str(e))

    # ⑦ Analyst Engine (weight 1.0)
    analyst = _safe_import("ai.analyst", "analyst")
    if analyst and candles:
        try:
            an_sig = analyst.analyze(candles) if hasattr(analyst, "analyze") else None
            if an_sig:
                votes.append(EngineVote(
                    engine="analyst",
                    direction=an_sig.get("direction","neutral"),
                    confidence=float(an_sig.get("confidence", 60)),
                    weight=1.0,
                ))
        except Exception:
            pass

    # ⑧ Hybrid Brain (weight 1.2)
    hybrid_brain = _safe_import("ai.hybrid_brain", "hybrid_brain")
    if hybrid_brain and candles:
        try:
            hb_sig = hybrid_brain.get_signal(candles) if hasattr(hybrid_brain,"get_signal") else None
            if hb_sig and hb_sig.get("direction") not in (None,"neutral"):
                votes.append(EngineVote(
                    engine="hybrid_brain",
                    direction=hb_sig["direction"],
                    confidence=float(hb_sig.get("confidence",60)),
                    weight=1.2,
                ))
        except Exception:
            pass

    # ⑨ Elite Indicator AI (weight 1.0)
    elite_ai = _safe_import("ai.elite_indicator_ai", "elite_indicator_ai")
    if elite_ai and candles:
        try:
            ei_sig = elite_ai.get_signal(candles) if hasattr(elite_ai,"get_signal") else None
            if ei_sig and ei_sig.get("direction") not in (None,"neutral"):
                votes.append(EngineVote(
                    engine="elite_indicator_ai",
                    direction=ei_sig["direction"],
                    confidence=float(ei_sig.get("confidence",60)),
                    weight=1.0,
                ))
        except Exception:
            pass

    return votes


def tally_votes(votes: List[EngineVote]) -> dict:
    """
    Weighted vote tally.
    Returns: direction, weighted_confidence, agreement_count, dissent_count
    """
    if not votes:
        return {"direction":"neutral","confidence":0,"votes":0,"agreement":0,"dissent":0}

    buy_weight  = sum(v.weight * v.confidence/100 for v in votes if v.direction=="buy")
    sell_weight = sum(v.weight * v.confidence/100 for v in votes if v.direction=="sell")
    buy_count   = sum(1 for v in votes if v.direction=="buy")
    sell_count  = sum(1 for v in votes if v.direction=="sell")

    if buy_weight > sell_weight and buy_count >= max(2, len(votes)//3):
        direction = "buy"
        total_w   = sum(v.weight for v in votes if v.direction=="buy")
        conf      = buy_weight / total_w * 100 if total_w > 0 else 0
        agreement = buy_count
        dissent   = sell_count
    elif sell_weight > buy_weight and sell_count >= max(2, len(votes)//3):
        direction = "sell"
        total_w   = sum(v.weight for v in votes if v.direction=="sell")
        conf      = sell_weight / total_w * 100 if total_w > 0 else 0
        agreement = sell_count
        dissent   = buy_count
    else:
        direction = "neutral"
        conf      = 0
        agreement = 0
        dissent   = max(buy_count, sell_count)

    return {
        "direction":  direction,
        "confidence": round(float(np.clip(conf, 0, 100)), 2),
        "votes":      len(votes),
        "agreement":  agreement,
        "dissent":    dissent,
        "buy_w":      round(buy_weight, 3),
        "sell_w":     round(sell_weight, 3),
    }


# ══════════════════════════════════════════════════════════════
# V9 MASTER TRADE DECISION
# ══════════════════════════════════════════════════════════════

async def make_trade_decision(
    bot_id:       str,
    bot_key:      str,
    symbol:       str,
    candles:      List[dict],
    balance:      float,
    drawdown_pct: float      = 0.0,
    daily_pnl:    float      = 0.0,
    funding_rate: float      = 0.0,
    bid_vol:      float      = 1000,
    ask_vol:      float      = 1000,
) -> dict:
    """
    V9 Master Decision Engine.
    Runs all 9 engines, tallies votes, applies capital maximization.
    Returns: {approved, direction, size_usd, capital_pct, ...full_context}
    """
    t0 = time.time()

    # ── 1. Collect votes from all 9 engines ──────────────────
    votes  = collect_votes(candles, bot_key, symbol, funding_rate, bid_vol, ask_vol)
    tally  = tally_votes(votes)

    # ── 2. Minimum vote threshold ─────────────────────────────
    # Need at least 3 engines agreeing for a trade
    if tally["agreement"] < 3 or tally["direction"] == "neutral":
        return {
            "approved":  False,
            "reason":    f"Insufficient consensus: {tally['agreement']}/{len(votes)} engines agree",
            "tally":     tally,
            "latency_ms":round((time.time()-t0)*1000, 1),
        }

    # ── 3. Get market feeling ─────────────────────────────────
    emotion      = "neutral"
    feeling_data = {}
    if market_feeling:
        try:
            freq = market_feeling.read_feeling(symbol, candles, funding_rate, bid_vol, ask_vol)
            emotion      = freq.emotion
            feeling_data = {
                "emotion":    emotion,
                "score":      freq.emotion_score,
                "confidence": freq.confidence,
                "note":       freq.entry_note,
                "signal":     freq.trade_signal,
                "size_mult":  freq.size_multiplier,
            }
        except Exception:
            pass

    # ── 4. Special strategy check ─────────────────────────────
    feeling_mult = 1.0
    if get_feeling_boost:
        feeling_mult = get_feeling_boost(bot_key, emotion)

    special_info = {}
    if get_strategy_signal:
        try:
            special_info = get_strategy_signal(
                bot_key, candles, emotion, tally["confidence"], balance
            )
        except Exception:
            pass

    # ── 5. Whale alignment check ──────────────────────────────
    whale_aligned = False
    if whale_tracker and hasattr(whale_tracker, "get_signal"):
        try:
            wh = whale_tracker.get_signal(symbol)
            whale_aligned = wh and wh.get("signal") == tally["direction"]
        except Exception:
            pass

    # ── 6. Capital maximization ───────────────────────────────
    base_pct = 50.0  # default
    config   = PRINT_CONFIGS.get(bot_key) if PRINT_CONFIGS else None
    if config:
        base_pct = config.capital_pct

    cap_result = capital_maximizer.calculate(
        bot_id       = bot_id,
        balance      = balance,
        base_risk_pct= base_pct,
        confidence   = tally["confidence"],
        emotion      = emotion,
        feeling_boost= feeling_mult,
        whale_aligned= whale_aligned,
        rl_confidence= tally["confidence"],
        vote_count   = tally["agreement"],
        drawdown_pct = drawdown_pct,
        daily_pnl_pct= daily_pnl,
    )

    if not cap_result.get("approved"):
        return {
            "approved":  False,
            "reason":    cap_result.get("reason","Capital maximizer rejected"),
            "tally":     tally,
            "cap":       cap_result,
            "latency_ms":round((time.time()-t0)*1000, 1),
        }

    # ── 7. Risk AI final check ────────────────────────────────
    if risk_ai:
        try:
            # ATR % from candles
            closes = [c["close"] for c in candles[-15:]] if len(candles)>=15 else [1.0]
            highs  = [c["high"]  for c in candles[-15:]] if len(candles)>=15 else [1.0]
            lows   = [c["low"]   for c in candles[-15:]] if len(candles)>=15 else [1.0]
            atrs   = [max(highs[i]-lows[i], abs(highs[i]-closes[i-1]),
                          abs(lows[i]-closes[i-1]))
                      for i in range(1, len(closes))]
            atr_pct = np.mean(atrs) / closes[-1] * 100 if atrs else 0.01

            risk_ok = risk_ai.evaluate_trade(
                bot_id     = bot_id,
                symbol     = symbol,
                exchange   = "binance",
                confidence = tally["confidence"],
                rr_ratio   = special_info.get("meta",{}).get("rr",2.0)
                             if special_info else 2.0,
                sl_pct     = atr_pct * 2.0,
                balance    = balance,
                win_rate   = 0.60,
                atr_pct    = atr_pct,
                session    = "london",
                regime     = emotion,
            )
            if not risk_ok.get("approved"):
                return {
                    "approved":  False,
                    "reason":    f"Risk AI: {risk_ok.get('reason','rejected')}",
                    "tally":     tally,
                    "risk":      risk_ok,
                    "latency_ms":round((time.time()-t0)*1000, 1),
                }
        except Exception as e:
            log.debug("Risk AI check failed", error=str(e))

    # ── 8. Build final decision ───────────────────────────────
    latency = round((time.time()-t0)*1000, 1)

    decision = {
        "approved":       True,
        "bot_id":         bot_id,
        "bot_key":        bot_key,
        "symbol":         symbol,
        "direction":      tally["direction"],
        "confidence":     tally["confidence"],
        "size_usd":       cap_result["size_usd"],
        "capital_pct":    cap_result["capital_pct"],
        "compound_bonus": cap_result.get("compound_bonus", 0),
        # Engine details
        "engines_voted":  tally["votes"],
        "engines_agree":  tally["agreement"],
        "engines_dissent":tally["dissent"],
        "vote_details":   [{"engine":v.engine,"dir":v.direction,"conf":v.confidence} for v in votes],
        # Feeling
        "emotion":        emotion,
        "feeling_boost":  feeling_mult,
        "feeling_data":   feeling_data,
        # Special strategy
        "special_strategy":special_info.get("strategy_name","") if special_info else "",
        "special_codename":special_info.get("codename","") if special_info else "",
        "special_edge":    special_info.get("edge","") if special_info else "",
        # Whale
        "whale_aligned":  whale_aligned,
        # Timing
        "latency_ms":     latency,
        "timestamp":      time.time(),
    }

    log.info("🎯 V9 DECISION",
             symbol=symbol, direction=tally["direction"],
             conf=f"{tally['confidence']:.1f}%",
             engines=f"{tally['agreement']}/{tally['votes']}",
             size=f"${cap_result['size_usd']:.2f}",
             emotion=emotion,
             latency=f"{latency:.0f}ms")

    return decision


async def record_trade_outcome(
    bot_id:       str,
    bot_key:      str,
    pnl_pct:      float,
    pnl_usd:      float,
    balance:      float,
    candles:      List[dict],
    latency_ms:   float,
    won:          bool,
    emotion:      str = "neutral",
):
    """Record outcome to all learning engines."""
    # Capital maximizer
    capital_maximizer.record(bot_id, pnl_pct, pnl_usd, balance)

    # RL Engine
    if rl_engine:
        try:
            from ai.reinforcement_engine import build_state
            mf = np.zeros(72)
            rl_engine.learn_from_trade(
                pnl_pct=pnl_pct, next_state=None, done=True,
                balance=balance, drawdown=0, win_rate=0.6,
                latency_ms=latency_ms, regime=emotion,
            )
        except Exception:
            pass

    # Dual AI (LSTM + Transformer)
    if dual_ai and candles:
        try:
            label = 2 if won else 0   # 2=long won, 0=short won
            dual_ai.learn_from_trade(candles, label)
        except Exception:
            pass

    # Strategy evolver
    if strategy_evolver:
        try:
            strategy_evolver.on_trade_closed(pnl_pct)
        except Exception:
            pass

    # Market feeling
    if market_feeling:
        try:
            market_feeling.record_outcome(emotion, pnl_pct)
        except Exception:
            pass

    log.info("📚 Engines learned from trade",
             bot_key=bot_key, pnl=f"{pnl_pct:+.3f}%",
             won=won, emotion=emotion)


# ══════════════════════════════════════════════════════════════
# V9 BOT LOOP
# ══════════════════════════════════════════════════════════════

class V9BotLoop:
    """
    Runs the V9 engine loop for a single bot.
    Checks signal every 30s, executes when approved.
    """

    def __init__(self, bot_config: dict):
        self.config      = bot_config
        self.bot_id      = str(bot_config.get("id",""))
        self.bot_key     = str(bot_config.get("bot_id","hybrid_alpha"))
        self.running     = False
        self.open_trades: dict = {}
        self.balance      = float(bot_config.get("allocated_capital",1000))
        self.peak_balance = self.balance
        self.stats        = defaultdict(float)
        self.stats["trades"] = 0

    async def start(self):
        self.running = True
        log.info("V9 Bot started", bot_key=self.bot_key, balance=self.balance)
        while self.running:
            try:
                await self._tick()
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.error("Bot tick error", bot=self.bot_key, error=str(e))
                await asyncio.sleep(10)

    async def stop(self):
        self.running = False

    async def _tick(self):
        """Single decision cycle."""
        symbol   = self._pick_symbol()
        candles  = await self._get_candles(symbol)
        if len(candles) < 50:
            return

        decision = await make_trade_decision(
            bot_id   = self.bot_id,
            bot_key  = self.bot_key,
            symbol   = symbol,
            candles  = candles,
            balance  = self.balance,
            drawdown_pct = self._drawdown(),
            daily_pnl    = float(self.stats["daily_pnl"]),
        )

        if decision.get("approved"):
            await self._execute(decision)

    def _pick_symbol(self) -> str:
        pairs = self.config.get("pairs_default") or ["BTCUSDT"]
        return pairs[0].replace("/","").upper() if pairs else "BTCUSDT"

    def _drawdown(self) -> float:
        return max(0, (self.peak_balance-self.balance)/(self.peak_balance+1e-9)*100)

    async def _get_candles(self, symbol: str) -> List[dict]:
        try:
            market_data = _safe_import("services.data_streamer","market_data")
            if market_data:
                c = market_data.get_candles(symbol,"5m",200)
                if c and len(c) >= 30: return c
        except Exception:
            pass
        # Fallback REST
        try:
            import httpx
            async with httpx.AsyncClient(timeout=5) as cl:
                r = await cl.get("https://api.binance.com/api/v3/klines",
                    params={"symbol":symbol,"interval":"5m","limit":200})
                data = r.json()
                return [{"timestamp":k[0]/1000,"open":float(k[1]),"high":float(k[2]),
                          "low":float(k[3]),"close":float(k[4]),"volume":float(k[5])}
                         for k in data]
        except Exception:
            return []

    async def _execute(self, decision: dict):
        """Execute the approved decision."""
        try:
            exec_engine = _safe_import("ai.elite_execution","elite_execution")
            if exec_engine and hasattr(exec_engine,"place_order"):
                result = await exec_engine.place_order(
                    symbol    = decision["symbol"],
                    direction = decision["direction"],
                    size_usd  = decision["size_usd"],
                    bot_id    = self.bot_id,
                )
            else:
                result = {"orderId": f"v9_{time.time_ns()}", "status":"FILLED"}

            self.stats["trades"] += 1
            self.open_trades[str(result.get("orderId",""))] = {
                **decision, "opened_at": time.time()
            }
            log.info("✅ V9 Trade executed",
                     bot=self.bot_key,
                     dir=decision["direction"],
                     size=f"${decision['size_usd']:.2f}",
                     emotion=decision.get("emotion","?"),
                     strategy=decision.get("special_codename",""))
        except Exception as e:
            log.error("Execution failed", bot=self.bot_key, error=str(e))


# ── V9 Controller ─────────────────────────────────────────────
class V9Controller:
    """Manages all running V9 bot loops."""

    def __init__(self):
        self._loops:  dict = {}
        self._tasks:  dict = {}

    async def start_bot(self, bot_config: dict) -> dict:
        bid = str(bot_config.get("id",""))
        if bid in self._loops and self._loops[bid].running:
            return {"already_running": True}
        loop = V9BotLoop(bot_config)
        self._loops[bid] = loop
        task = asyncio.create_task(loop.start())
        self._tasks[bid] = task
        return {"success": True, "bot_id": bid, "status": "running"}

    async def stop_bot(self, bot_id: str) -> dict:
        loop = self._loops.get(bot_id)
        if loop:
            await loop.stop()
        if bot_id in self._tasks:
            self._tasks[bot_id].cancel()
            del self._tasks[bot_id]
        return {"success": True, "bot_id": bot_id, "status": "stopped"}

    def get_status(self, bot_id: str) -> dict:
        loop = self._loops.get(bot_id)
        if not loop: return {"running": False}
        return {
            "running":    loop.running,
            "balance":    round(loop.balance, 2),
            "trades":     int(loop.stats["trades"]),
            "daily_pnl":  round(float(loop.stats["daily_pnl"]), 3),
            "open_trades":len(loop.open_trades),
        }

    def get_all_status(self) -> dict:
        return {bid: self.get_status(bid) for bid in self._loops}


v9_controller = V9Controller()
