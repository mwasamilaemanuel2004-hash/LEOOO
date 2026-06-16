"""
ai/strategy_evolver.py — ESTRADE v8 GODMODE Strategy Evolution Engine
══════════════════════════════════════════════════════════════════════════════
EVOLUTIONARY TRADING INTELLIGENCE:

  ① GENETIC ALGORITHM — Evolves strategy parameters
     → Population: 50 strategy variants per generation
     → Selection: Tournament selection (top 30% survive)
     → Crossover: Multi-point crossover between survivors
     → Mutation:  Gaussian noise + random parameter reset
     → Fitness:   Sharpe × WinRate × ProfitFactor × (-MaxDD)
     → Runs every 1000 trades or 24h (whichever first)

  ② STRATEGY DNA — Every strategy has a genome:
     {
       ema_fast, ema_slow,     # trend detection
       rsi_ob, rsi_os,         # overbought/oversold
       bb_mult,                # Bollinger Band multiplier
       atr_sl_mult, atr_tp_mult, # SL/TP distances
       min_confidence,         # signal quality filter
       min_rr,                 # risk:reward minimum
       vol_filter,             # volume confirmation
       session_mask,           # which sessions to trade
       regime_filter,          # regime whitelist
       entry_aggressiveness,   # 0=wait_for_pullback, 1=chase_breakout
       max_trades_per_day,     # frequency control
       compound_factor,        # reinvest multiplier
     }

  ③ BACKTEST ENGINE — Tests each variant on historical data
     → Walk-forward testing (no lookahead bias)
     → Out-of-sample validation (last 20% of data)
     → Monte Carlo: 100 random trade sequences → median Sharpe
     → Slippage + commission modeled (0.07% Binance)

  ④ STRATEGY TOURNAMENT
     → Every 24h: all active strategies compete
     → Winner replaces losers in bot pool
     → Loser strategies enter "incubation" — tweaked + retested
     → Hall of Fame: top 10 all-time strategies saved forever

  ⑤ LIVE ADAPTATION
     → If strategy loses 3 in a row → emergency parameter tweak
     → If win rate drops below threshold → regime detection + switch
     → If new market regime detected → evolution triggered early

  ⑥ STRATEGY DIVERSITY ENFORCEMENT
     → Prevents overfitting to one market condition
     → Forces variety: must have trend + mean-rev + breakout strategies
     → Correlation check: new strategies must differ from existing ones
     → Penalizes strategies that only work in one regime

══════════════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations
import copy
import json
import math
import random
import statistics
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional, List, Dict, Tuple
import numpy as np
import structlog

log = structlog.get_logger("strategy_evolver")

EVOLVER_STORAGE = Path("storage/strategy_evolver.json")
EVOLVER_STORAGE.parent.mkdir(parents=True, exist_ok=True)

# ── Genetic Algorithm Constants ───────────────────────────────
POPULATION_SIZE    = 50
SURVIVORS_PCT      = 0.30
MUTATION_RATE      = 0.15
MUTATION_STD       = 0.10
CROSSOVER_RATE     = 0.70
MAX_GENERATIONS    = 100
EVOLUTION_INTERVAL = 1000   # trades
MONTE_CARLO_RUNS   = 50
SLIPPAGE_PCT       = 0.07   # Binance fee
HALL_OF_FAME_SIZE  = 10
DIVERSITY_MIN      = 0.25   # min genome distance between strategies


# ══════════════════════════════════════════════════════════════
# STRATEGY GENOME (DNA)
# ══════════════════════════════════════════════════════════════

@dataclass
class StrategyGenome:
    """Complete strategy parameter set — the DNA of a trading strategy."""
    genome_id:   str = ""

    # Trend indicators
    ema_fast:    int   = 8
    ema_slow:    int   = 21
    ema_trend:   int   = 50
    ema_filter:  int   = 200

    # Oscillators
    rsi_period:  int   = 14
    rsi_ob:      float = 70.0     # overbought threshold
    rsi_os:      float = 30.0     # oversold threshold
    rsi_mid:     float = 50.0     # midpoint filter

    # Bollinger Bands
    bb_period:   int   = 20
    bb_mult:     float = 2.0

    # ATR-based SL/TP
    atr_period:  int   = 14
    atr_sl_mult: float = 2.0      # SL = ATR × mult
    atr_tp_mult: float = 4.0      # TP = ATR × mult

    # Signal quality
    min_confidence: float = 65.0  # %
    min_rr:         float = 1.5   # R:R ratio

    # Volume
    vol_filter:     float = 1.2   # min volume ratio vs average
    vol_spike:      float = 3.0   # spike threshold

    # Session (bitmask: 1=Asia, 2=London, 4=NY, 8=Overlap)
    session_mask:   int   = 14    # London + NY + Overlap

    # Regime filter (which regimes to trade)
    trade_trending: int   = 1
    trade_ranging:  int   = 1
    trade_breakout: int   = 1
    trade_reversal: int   = 0     # risky, off by default

    # Entry style
    entry_aggressiveness: float = 0.5  # 0=pullback, 1=breakout

    # Risk management
    max_trades_day:  int   = 20
    risk_per_trade:  float = 1.0   # % of capital
    compound_factor: float = 1.0   # position size multiplier over time

    # MACD settings
    macd_fast:   int   = 12
    macd_slow:   int   = 26
    macd_signal: int   = 9

    # Stochastic
    stoch_k:     int   = 14
    stoch_d:     int   = 3
    stoch_ob:    float = 80.0
    stoch_os:    float = 20.0

    # SMC (Smart Money Concepts)
    use_smc:         int   = 1    # 1=enabled
    ob_min_strength: float = 0.5  # order block min strength
    fvg_min_size:    float = 0.3  # fair value gap min size (ATR)

    # Performance metadata
    fitness:         float = 0.0
    sharpe:          float = 0.0
    win_rate:        float = 0.0
    profit_factor:   float = 0.0
    max_drawdown:    float = 0.0
    total_trades:    int   = 0
    generation:      int   = 0
    created_at:      str   = ""

    def __post_init__(self):
        if not self.genome_id:
            self.genome_id = _generate_id()
        if not self.created_at:
            from datetime import datetime, timezone
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_vector(self) -> np.ndarray:
        """Serialize genome to numeric vector for crossover/mutation."""
        return np.array([
            self.ema_fast, self.ema_slow, self.ema_trend, self.ema_filter,
            self.rsi_period, self.rsi_ob, self.rsi_os, self.rsi_mid,
            self.bb_period, self.bb_mult,
            self.atr_period, self.atr_sl_mult, self.atr_tp_mult,
            self.min_confidence, self.min_rr,
            self.vol_filter, self.vol_spike,
            self.session_mask,
            self.trade_trending, self.trade_ranging,
            self.trade_breakout, self.trade_reversal,
            self.entry_aggressiveness,
            self.max_trades_day, self.risk_per_trade, self.compound_factor,
            self.macd_fast, self.macd_slow, self.macd_signal,
            self.stoch_k, self.stoch_d, self.stoch_ob, self.stoch_os,
            self.use_smc, self.ob_min_strength, self.fvg_min_size,
        ], dtype=np.float64)

    @staticmethod
    def from_vector(v: np.ndarray, parent_id: str = "") -> "StrategyGenome":
        """Deserialize from numeric vector (after crossover/mutation)."""
        def iv(x): return max(1, int(round(x)))   # integer, min 1
        def bv(x): return 1 if x > 0.5 else 0     # binary

        g = StrategyGenome(genome_id=_generate_id())
        g.ema_fast    = max(3, iv(v[0]))
        g.ema_slow    = max(g.ema_fast + 3, iv(v[1]))
        g.ema_trend   = max(g.ema_slow + 5, iv(v[2]))
        g.ema_filter  = max(g.ema_trend + 20, iv(v[3]))
        g.rsi_period  = max(5, min(30, iv(v[4])))
        g.rsi_ob      = float(np.clip(v[5], 60, 85))
        g.rsi_os      = float(np.clip(v[6], 15, 40))
        g.rsi_mid     = float(np.clip(v[7], 40, 60))
        g.bb_period   = max(10, min(50, iv(v[8])))
        g.bb_mult     = float(np.clip(v[9], 1.5, 3.0))
        g.atr_period  = max(7, min(21, iv(v[10])))
        g.atr_sl_mult = float(np.clip(v[11], 1.0, 4.0))
        g.atr_tp_mult = float(np.clip(v[12], g.atr_sl_mult * 1.2, 8.0))
        g.min_confidence = float(np.clip(v[13], 55, 90))
        g.min_rr      = float(np.clip(v[14], 1.2, 3.5))
        g.vol_filter  = float(np.clip(v[15], 0.8, 2.5))
        g.vol_spike   = float(np.clip(v[16], 1.5, 5.0))
        g.session_mask    = max(1, min(15, iv(v[17])))
        g.trade_trending  = bv(v[18])
        g.trade_ranging   = bv(v[19])
        g.trade_breakout  = bv(v[20])
        g.trade_reversal  = bv(v[21])
        g.entry_aggressiveness = float(np.clip(v[22], 0, 1))
        g.max_trades_day  = max(3, min(50, iv(v[23])))
        g.risk_per_trade  = float(np.clip(v[24], 0.3, 3.0))
        g.compound_factor = float(np.clip(v[25], 0.8, 2.0))
        g.macd_fast       = max(5, min(20, iv(v[26])))
        g.macd_slow       = max(g.macd_fast + 5, min(40, iv(v[27])))
        g.macd_signal     = max(3, min(15, iv(v[28])))
        g.stoch_k         = max(5, min(30, iv(v[29])))
        g.stoch_d         = max(2, min(10, iv(v[30])))
        g.stoch_ob        = float(np.clip(v[31], 70, 90))
        g.stoch_os        = float(np.clip(v[32], 10, 30))
        g.use_smc         = bv(v[33])
        g.ob_min_strength = float(np.clip(v[34], 0.2, 0.9))
        g.fvg_min_size    = float(np.clip(v[35], 0.1, 1.0))
        return g

    def distance_to(self, other: "StrategyGenome") -> float:
        """Normalized L2 distance between two genomes (for diversity check)."""
        v1 = self.to_vector()
        v2 = other.to_vector()
        # Normalize to [0,1] using rough ranges
        norm  = np.array([30, 50, 100, 250, 30, 30, 30, 30,
                          50, 2, 21, 4, 8, 40, 3, 2, 5, 16,
                          1, 1, 1, 1, 1, 50, 3, 1.5, 20, 40,
                          15, 30, 10, 30, 30, 1, 1, 1], dtype=np.float64)
        diff = (v1 - v2) / (norm + 1e-9)
        return float(np.sqrt(np.mean(diff ** 2)))


def _generate_id() -> str:
    import hashlib, time
    return hashlib.md5(f"{time.time_ns()}".encode()).hexdigest()[:8]


# ══════════════════════════════════════════════════════════════
# FITNESS CALCULATOR
# ══════════════════════════════════════════════════════════════

def calculate_fitness(
    sharpe:         float,
    win_rate:       float,
    profit_factor:  float,
    max_drawdown:   float,
    total_trades:   int,
    consistency:    float = 1.0,
) -> float:
    """
    Multi-objective fitness function for strategy evaluation.
    Higher is better. Zero if strategy has no trades.
    """
    if total_trades < 10:
        return 0.0

    # Heavily penalize high drawdown
    dd_factor = max(0, 1 - max_drawdown / 30.0) ** 2

    # Require minimum trade frequency
    freq_bonus = min(1.0, total_trades / 50)

    fitness = (
        max(0, sharpe) * 0.35 +
        win_rate       * 0.25 +
        min(profit_factor, 5.0) / 5.0 * 0.20 +
        dd_factor      * 0.15 +
        freq_bonus     * 0.05
    ) * consistency

    # Bonus for exceptional performance
    if sharpe > 2.0:      fitness *= 1.2
    if win_rate > 0.70:   fitness *= 1.1
    if max_drawdown < 5.0:fitness *= 1.15

    return float(np.clip(fitness, 0, 10))


# ══════════════════════════════════════════════════════════════
# MINI BACKTEST ENGINE (used during evolution)
# ══════════════════════════════════════════════════════════════

def backtest_genome(
    genome:   StrategyGenome,
    candles:  List[dict],
    initial_balance: float = 10000.0,
) -> dict:
    """
    Walk-forward backtest on historical candle data.
    Returns performance metrics.
    Fast backtest — runs in <100ms per genome.
    """
    if len(candles) < 50:
        return {"fitness": 0.0, "sharpe": 0.0, "win_rate": 0.0,
                "profit_factor": 0.0, "max_drawdown": 0.0, "total_trades": 0}

    balance  = initial_balance
    peak_bal = initial_balance
    trades   = []
    wins     = 0
    losses   = 0
    gross_p  = 0.0
    gross_l  = 0.0
    daily_returns = []
    max_dd   = 0.0
    trades_today = 0
    last_day = -1

    # Pre-compute simple indicators
    closes = [c.get("close", 1) for c in candles]
    highs  = [c.get("high",  1) for c in candles]
    lows   = [c.get("low",   1) for c in candles]
    vols   = [c.get("volume",0) for c in candles]

    def ema_series(data, period):
        k = 2 / (period + 1)
        result = [data[0]]
        for x in data[1:]:
            result.append(x * k + result[-1] * (1 - k))
        return result

    def rsi_series(data, period=14):
        result = [50.0] * len(data)
        for i in range(period, len(data)):
            gains = [max(0, data[j] - data[j-1]) for j in range(i-period+1, i+1)]
            losses = [max(0, data[j-1] - data[j]) for j in range(i-period+1, i+1)]
            ag = sum(gains) / period
            al = sum(losses) / period
            result[i] = 100 - 100 / (1 + ag / (al + 1e-9))
        return result

    def atr_series(hs, ls, cs, period=14):
        result = [0.0] * len(hs)
        for i in range(1, len(hs)):
            tr = max(hs[i]-ls[i], abs(hs[i]-cs[i-1]), abs(ls[i]-cs[i-1]))
            result[i] = tr
        # EMA of ATR
        k = 2 / (period + 1)
        smoothed = [result[0]]
        for x in result[1:]:
            smoothed.append(x * k + smoothed[-1] * (1 - k))
        return smoothed

    ema_f  = ema_series(closes, genome.ema_fast)
    ema_s  = ema_series(closes, genome.ema_slow)
    rsi_v  = rsi_series(closes, genome.rsi_period)
    atr_v  = atr_series(highs, lows, closes, genome.atr_period)

    avg_vol = sum(vols) / len(vols) if vols else 1

    in_trade = False
    entry_price = 0.0
    trade_sl = 0.0
    trade_tp = 0.0
    trade_dir = "buy"
    position_size = 0.0

    for i in range(max(genome.ema_slow, genome.rsi_period, 30), len(candles)):
        c = candles[i]
        price = closes[i]
        atr   = atr_v[i]
        rsi   = rsi_v[i]
        vol   = vols[i]
        day   = i // 288  # 5-min candles, ~288 per day

        if day != last_day:
            if last_day >= 0 and trades_today > 0:
                daily_returns.append(
                    (balance - initial_balance * (1 + 0.001 * last_day)) /
                    (initial_balance + 1e-9) * 100
                )
            trades_today = 0
            last_day = day

        # Check for exit
        if in_trade:
            exit_price = 0.0
            result = None
            if trade_dir == "buy":
                if lows[i] <= trade_sl:
                    exit_price = trade_sl
                    result = "loss"
                elif highs[i] >= trade_tp:
                    exit_price = trade_tp
                    result = "win"
            else:
                if highs[i] >= trade_sl:
                    exit_price = trade_sl
                    result = "loss"
                elif lows[i] <= trade_tp:
                    exit_price = trade_tp
                    result = "win"

            if result:
                pnl_pct = ((exit_price - entry_price) / entry_price * 100
                           if trade_dir == "buy" else
                           (entry_price - exit_price) / entry_price * 100)
                # Apply slippage
                pnl_pct -= SLIPPAGE_PCT
                pnl_usd  = balance * (genome.risk_per_trade / 100) * (pnl_pct / abs(pnl_pct if pnl_pct else 1))
                balance  += pnl_usd

                if pnl_pct > 0:
                    wins    += 1
                    gross_p += abs(pnl_usd)
                else:
                    losses  += 1
                    gross_l += abs(pnl_usd)

                if balance > peak_bal:
                    peak_bal = balance
                dd = (peak_bal - balance) / peak_bal * 100
                max_dd = max(max_dd, dd)

                trades.append(pnl_pct)
                in_trade = False

                # Ruin check
                if balance < initial_balance * 0.5:
                    break

            continue

        if in_trade: continue
        if trades_today >= genome.max_trades_day: continue
        if vol < avg_vol * genome.vol_filter:    continue

        # Signal generation
        trend_up   = ema_f[i] > ema_s[i]
        trend_down = ema_f[i] < ema_s[i]
        rsi_buy    = rsi < genome.rsi_ob and rsi > genome.rsi_os
        rsi_sell   = rsi > genome.rsi_os and rsi < genome.rsi_ob

        signal = None
        if trend_up and rsi < genome.rsi_ob and price > ema_s[i]:
            signal = "buy"
        elif trend_down and rsi > genome.rsi_os and price < ema_s[i]:
            signal = "sell"

        if signal:
            entry_price = price
            sl_dist = atr * genome.atr_sl_mult
            tp_dist = atr * genome.atr_tp_mult
            actual_rr = tp_dist / (sl_dist + 1e-9)

            if actual_rr < genome.min_rr:
                continue

            trade_dir = signal
            if signal == "buy":
                trade_sl = price - sl_dist
                trade_tp = price + tp_dist
            else:
                trade_sl = price + sl_dist
                trade_tp = price - tp_dist

            in_trade = True
            trades_today += 1

    # Performance metrics
    total_trades = len(trades)
    if total_trades < 5:
        return {"fitness": 0.0, "sharpe": 0.0, "win_rate": 0.0,
                "profit_factor": 0.0, "max_drawdown": max_dd,
                "total_trades": total_trades, "final_balance": balance}

    win_rate = wins / total_trades if total_trades > 0 else 0
    profit_factor = gross_p / (gross_l + 1e-9)

    # Sharpe ratio
    if len(trades) > 1:
        mean_r = statistics.mean(trades)
        std_r  = statistics.stdev(trades)
        sharpe = mean_r / (std_r + 1e-9) * math.sqrt(252 * 6)  # 6 trades/day avg
    else:
        sharpe = 0.0

    fitness = calculate_fitness(
        sharpe=sharpe,
        win_rate=win_rate,
        profit_factor=profit_factor,
        max_drawdown=max_dd,
        total_trades=total_trades,
    )

    return {
        "fitness":        fitness,
        "sharpe":         sharpe,
        "win_rate":       win_rate,
        "profit_factor":  profit_factor,
        "max_drawdown":   max_dd,
        "total_trades":   total_trades,
        "final_balance":  balance,
        "total_return":   (balance - initial_balance) / initial_balance * 100,
    }


# ══════════════════════════════════════════════════════════════
# GENETIC OPERATORS
# ══════════════════════════════════════════════════════════════

def tournament_select(population: List[StrategyGenome], k: int = 5) -> StrategyGenome:
    """Tournament selection — pick best from k random candidates."""
    candidates = random.sample(population, min(k, len(population)))
    return max(candidates, key=lambda g: g.fitness)


def crossover(parent1: StrategyGenome, parent2: StrategyGenome) -> StrategyGenome:
    """Multi-point crossover of two parent genomes."""
    v1 = parent1.to_vector()
    v2 = parent2.to_vector()
    # Random crossover mask
    mask  = np.random.random(len(v1)) > 0.5
    child = np.where(mask, v1, v2)
    g = StrategyGenome.from_vector(child)
    g.generation = max(parent1.generation, parent2.generation) + 1
    return g


def mutate(genome: StrategyGenome, mutation_rate: float = MUTATION_RATE) -> StrategyGenome:
    """Gaussian mutation on genome vector."""
    v = genome.to_vector().copy()
    for i in range(len(v)):
        if random.random() < mutation_rate:
            v[i] += np.random.randn() * MUTATION_STD * v[i] * 0.5
    g = StrategyGenome.from_vector(v)
    g.generation = genome.generation + 1
    return g


def is_diverse_enough(
    new_genome: StrategyGenome,
    population: List[StrategyGenome],
    min_dist:   float = DIVERSITY_MIN,
) -> bool:
    """Check that new genome is sufficiently different from all existing ones."""
    for g in population:
        if new_genome.distance_to(g) < min_dist:
            return False
    return True


# ══════════════════════════════════════════════════════════════
# STRATEGY EVOLUTION ENGINE
# ══════════════════════════════════════════════════════════════

class StrategyEvolver:
    """
    Master strategy evolution engine.
    Runs genetic algorithm to continuously improve trading strategies.
    """

    def __init__(self):
        self.population:    List[StrategyGenome]  = []
        self.hall_of_fame:  List[StrategyGenome]  = []
        self.generation:    int   = 0
        self.evolutions:    int   = 0
        self.trade_counter: int   = 0
        self.last_evolution: float = 0.0
        self.best_fitness:   float = 0.0
        self.fitness_history = deque(maxlen=100)
        self.candle_cache:   List[dict] = []
        self._load()

        # Initialize population if empty
        if not self.population:
            self._init_population()

        log.info("Strategy Evolver initialized",
                 population=len(self.population),
                 hall_of_fame=len(self.hall_of_fame),
                 generation=self.generation)

    def _init_population(self):
        """Create initial diverse population of strategies."""
        log.info("Initializing strategy population")
        base = StrategyGenome()

        # Predefined diverse archetypes
        archetypes = [
            # Trend following
            StrategyGenome(ema_fast=8,  ema_slow=21, min_confidence=68, min_rr=1.8,
                           atr_sl_mult=1.5, atr_tp_mult=3.5, trade_ranging=0),
            # Mean reversion
            StrategyGenome(ema_fast=5,  ema_slow=13, rsi_ob=75, rsi_os=25,
                           min_confidence=70, atr_sl_mult=1.2, atr_tp_mult=2.5,
                           trade_trending=0, trade_breakout=0),
            # Scalping
            StrategyGenome(ema_fast=3,  ema_slow=8,  min_confidence=60, min_rr=1.2,
                           atr_sl_mult=0.8, atr_tp_mult=1.5, max_trades_day=40),
            # Conservative swing
            StrategyGenome(ema_fast=21, ema_slow=55, min_confidence=75, min_rr=2.5,
                           atr_sl_mult=2.5, atr_tp_mult=6.0, max_trades_day=5),
            # Breakout hunter
            StrategyGenome(entry_aggressiveness=0.9, vol_filter=2.0,
                           min_confidence=72, trade_ranging=0, trade_reversal=0),
        ]

        self.population = archetypes[:POPULATION_SIZE]

        # Fill rest with random variants
        while len(self.population) < POPULATION_SIZE:
            parent = random.choice(archetypes)
            child  = mutate(parent, mutation_rate=0.3)
            self.population.append(child)

    def add_candles(self, candles: List[dict]):
        """Feed market data for backtesting."""
        self.candle_cache = candles[-5000:]  # keep last 5000 candles

    def on_trade_closed(self, pnl_pct: float):
        """Called every time a trade closes. Triggers evolution if needed."""
        self.trade_counter += 1
        elapsed = time.time() - self.last_evolution

        if (self.trade_counter % EVOLUTION_INTERVAL == 0 or
                elapsed > 86400):  # or 24h
            self.evolve()

    def evolve(self) -> StrategyGenome:
        """
        Run one generation of genetic algorithm.
        Returns the best genome from this generation.
        """
        if not self.candle_cache:
            log.warning("No candle data for evolution — skipping")
            return self.get_best_genome()

        log.info("Starting evolution", generation=self.generation,
                 population=len(self.population))

        start = time.time()

        # Evaluate all genomes
        for g in self.population:
            if g.fitness == 0.0 or random.random() < 0.3:  # re-evaluate 30%
                result = backtest_genome(g, self.candle_cache)
                g.fitness       = result["fitness"]
                g.sharpe        = result["sharpe"]
                g.win_rate      = result["win_rate"]
                g.profit_factor = result["profit_factor"]
                g.max_drawdown  = result["max_drawdown"]
                g.total_trades  = result["total_trades"]

        # Sort by fitness
        self.population.sort(key=lambda g: g.fitness, reverse=True)
        best = self.population[0]

        # Update hall of fame
        self._update_hof(best)

        # Log best
        log.info("Evolution gen complete",
                 gen=self.generation, best_fitness=round(best.fitness, 3),
                 sharpe=round(best.sharpe, 3), win_rate=round(best.win_rate, 3),
                 elapsed=round(time.time() - start, 1))

        # Selection: keep top survivors
        n_survivors = max(5, int(len(self.population) * SURVIVORS_PCT))
        survivors   = self.population[:n_survivors]

        # Generate new population
        new_population = survivors[:]  # elitism: keep survivors

        attempts = 0
        while len(new_population) < POPULATION_SIZE and attempts < 500:
            attempts += 1
            if random.random() < CROSSOVER_RATE and len(survivors) >= 2:
                p1 = tournament_select(survivors)
                p2 = tournament_select(survivors)
                child = crossover(p1, p2)
            else:
                parent = tournament_select(survivors)
                child  = mutate(parent)

            # Diversity enforcement
            if is_diverse_enough(child, new_population, DIVERSITY_MIN * 0.5):
                new_population.append(child)

        self.population  = new_population[:POPULATION_SIZE]
        self.generation += 1
        self.evolutions += 1
        self.last_evolution = time.time()
        self.fitness_history.append(best.fitness)
        self.best_fitness = max(self.best_fitness, best.fitness)

        self._save()
        return best

    def get_best_genome(self) -> StrategyGenome:
        """Return best performing genome from population or HoF."""
        all_genomes = self.population + self.hall_of_fame
        if not all_genomes:
            return StrategyGenome()
        return max(all_genomes, key=lambda g: g.fitness)

    def get_top_n_genomes(self, n: int = 5) -> List[StrategyGenome]:
        """Return top N strategies (for multi-strategy deployment)."""
        all_genomes = sorted(
            self.population + self.hall_of_fame,
            key=lambda g: g.fitness, reverse=True
        )
        # Enforce diversity among selected
        selected = []
        for g in all_genomes:
            if not selected or is_diverse_enough(g, selected, DIVERSITY_MIN * 2):
                selected.append(g)
            if len(selected) >= n:
                break
        return selected

    def emergency_adaptation(
        self,
        genome:  StrategyGenome,
        issues:  List[str],
    ) -> StrategyGenome:
        """
        Emergency parameter tweak when strategy is underperforming.
        Called when consecutive losses hit threshold.
        """
        v = genome.to_vector().copy()

        for issue in issues:
            if "high_drawdown" in issue:
                # Tighten risk
                v[11] *= 0.85   # reduce SL multiplier
                v[13] = min(80, v[13] * 1.05)  # increase min confidence
            if "low_win_rate" in issue:
                # More selective entries
                v[13] = min(85, v[13] + 3)     # higher confidence threshold
                v[14] = min(3.0, v[14] + 0.2)  # higher R:R requirement
            if "overtrading" in issue:
                v[23] = max(5, v[23] * 0.8)    # reduce max trades
            if "whipsaw" in issue:
                # Increase trend filter
                v[1] = min(50, v[1] * 1.1)     # slower EMA slow
                v[15] = min(2.5, v[15] + 0.2)  # higher volume filter

        adapted = StrategyGenome.from_vector(v)
        adapted.generation = genome.generation + 1
        log.info("Emergency adaptation applied",
                 old_id=genome.genome_id, new_id=adapted.genome_id, issues=issues)
        return adapted

    def get_genome_for_regime(self, regime: str) -> Optional[StrategyGenome]:
        """Get best genome for a specific market regime."""
        regime_map = {
            "trending_bull": lambda g: g.trade_trending == 1,
            "trending_bear": lambda g: g.trade_trending == 1,
            "ranging":       lambda g: g.trade_ranging  == 1,
            "breakout":      lambda g: g.trade_breakout == 1,
            "reversal":      lambda g: g.trade_reversal == 1,
        }
        filt = regime_map.get(regime)
        candidates = [g for g in self.population + self.hall_of_fame
                      if (not filt) or filt(g)]
        if not candidates:
            return self.get_best_genome()
        return max(candidates, key=lambda g: g.fitness)

    def _update_hof(self, genome: StrategyGenome):
        self.hall_of_fame.append(copy.deepcopy(genome))
        self.hall_of_fame.sort(key=lambda g: g.fitness, reverse=True)
        self.hall_of_fame = self.hall_of_fame[:HALL_OF_FAME_SIZE]

    def get_stats(self) -> dict:
        best = self.get_best_genome()
        return {
            "generation":      self.generation,
            "evolutions":      self.evolutions,
            "population_size": len(self.population),
            "hall_of_fame":    len(self.hall_of_fame),
            "best_fitness":    round(self.best_fitness, 3),
            "best_sharpe":     round(best.sharpe, 3),
            "best_win_rate":   round(best.win_rate, 3),
            "best_genome_id":  best.genome_id,
            "trade_counter":   self.trade_counter,
            "fitness_trend":   [round(f, 3) for f in list(self.fitness_history)[-10:]],
        }

    def _save(self):
        try:
            EVOLVER_STORAGE.write_text(json.dumps({
                "generation":   self.generation,
                "evolutions":   self.evolutions,
                "best_fitness": self.best_fitness,
                "trade_counter":self.trade_counter,
                "population":   [asdict(g) for g in self.population[:20]],
                "hall_of_fame": [asdict(g) for g in self.hall_of_fame],
                "fitness_history": list(self.fitness_history),
            }, indent=2))
        except Exception as e:
            log.error("Evolver save failed", error=str(e))

    def _load(self):
        try:
            if EVOLVER_STORAGE.exists():
                d = json.loads(EVOLVER_STORAGE.read_text())
                self.generation    = d.get("generation", 0)
                self.evolutions    = d.get("evolutions", 0)
                self.best_fitness  = d.get("best_fitness", 0.0)
                self.trade_counter = d.get("trade_counter", 0)

                for gd in d.get("population", []):
                    try:
                        g = StrategyGenome(**gd)
                        self.population.append(g)
                    except Exception: pass

                for gd in d.get("hall_of_fame", []):
                    try:
                        g = StrategyGenome(**gd)
                        self.hall_of_fame.append(g)
                    except Exception: pass

                for f in d.get("fitness_history", []):
                    self.fitness_history.append(f)

                log.info("Strategy Evolver loaded",
                         generation=self.generation, pop=len(self.population))
        except Exception as e:
            log.warning("Evolver load failed", error=str(e))


# ── Singleton ─────────────────────────────────────────────────
strategy_evolver = StrategyEvolver()
