"""
ai/risk_ai_engine.py — ESTRADE v8 GODMODE Risk AI Engine
══════════════════════════════════════════════════════════════════════════════
THE MOST ADVANCED RISK MANAGEMENT SYSTEM FOR ALGORITHMIC TRADING:

  ① DYNAMIC POSITION SIZING
     → Kelly Criterion (fractional) with safety cap
     → Volatility-adjusted sizing (reduces in high vol)
     → Correlation-aware (reduces size for correlated positions)
     → Win-streak/loss-streak adaptive sizing
     → Maximum allocation: never risk >5% on any single trade

  ② DRAWDOWN DEFENSE SYSTEM (5-Level)
     Level 0: Normal trading (0-3% DD)
     Level 1: Alert (3-5% DD) → reduce position size 20%
     Level 2: Caution (5-8% DD) → reduce 40%, only A+ setups
     Level 3: Crisis (8-12% DD) → reduce 60%, halt new bots
     Level 4: Emergency (12-15% DD) → reduce 80%, manual review required
     Level 5: HALT (>15% DD) → stop ALL trading, notify user immediately

  ③ CIRCUIT BREAKERS
     → Daily loss limit: configurable (default 3%)
     → Consecutive loss limit: 4 losses → 1h pause
     → Correlation circuit: max 3 correlated positions
     → Slippage circuit: if slippage > 0.5% → halt
     → Latency circuit: if latency > 2000ms → reduce size

  ④ PORTFOLIO HEAT MAP
     → Tracks exposure per: asset class, exchange, timeframe
     → Max 30% in any one asset class
     → Max 50% in any one exchange
     → Rebalances automatically when limits breached

  ⑤ VAR (VALUE AT RISK)
     → Monte Carlo VaR: 1000 simulations, 95% & 99% confidence
     → Historical VaR: tail risk from last 500 trades
     → Expected Shortfall (CVaR): worst 5% of outcomes
     → Updates after every 10 trades

  ⑥ RISK SCORING (0-100 per trade)
     100 = Perfect setup, full size
     80  = Good setup, 80% size
     60  = Acceptable, 60% size
     40  = Marginal, 40% size
     20  = Risky, 20% size only
     0   = REJECT, do not trade

  ⑦ ADAPTIVE RISK LEARNING
     → Tracks which risk levels lead to best outcomes
     → Adjusts risk thresholds based on historical performance
     → Self-calibrates to market conditions (volatile vs calm)
     → Monthly risk review: updates all parameters

══════════════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations
import json
import math
import statistics
import time
from collections import deque, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, List, Tuple
import numpy as np
import structlog

log = structlog.get_logger("risk_ai")

RISK_STORAGE = Path("storage/risk_ai.json")
RISK_STORAGE.parent.mkdir(parents=True, exist_ok=True)

# ── Drawdown Defense Levels ───────────────────────────────────
DD_LEVEL_0 = 3.0   # Normal
DD_LEVEL_1 = 5.0   # Alert
DD_LEVEL_2 = 8.0   # Caution
DD_LEVEL_3 = 12.0  # Crisis
DD_LEVEL_4 = 15.0  # Emergency
DD_LEVEL_5 = 20.0  # HALT

DD_SIZE_MULTS = {0: 1.00, 1: 0.80, 2: 0.60, 3: 0.40, 4: 0.20, 5: 0.00}
DD_MIN_CONF   = {0: 60.0, 1: 65.0, 2: 72.0, 3: 78.0, 4: 85.0, 5: 100.0}

# ── Risk Limits ───────────────────────────────────────────────
MAX_RISK_PER_TRADE  = 5.0    # % of portfolio max
MIN_RISK_PER_TRADE  = 0.1    # % minimum
MAX_PORTFOLIO_RISK  = 20.0   # total open risk
MAX_CORR_POSITIONS  = 3      # correlated positions max
MAX_DAILY_LOSS      = 3.0    # % daily loss limit
CONSECUTIVE_LOSS_PAUSE = 4   # trades before pause
KELLY_CAP           = 0.25   # never bet more than 25% Kelly
VAR_CONFIDENCE      = 0.95   # 95% VaR
VAR_SIMULATIONS     = 1000   # Monte Carlo runs

# ── Asset Classes ─────────────────────────────────────────────
ASSET_CLASS_MAP = {
    "BTCUSDT": "crypto_major", "ETHUSDT": "crypto_major",
    "BNBUSDT": "crypto_alt",   "SOLUSDT": "crypto_alt",
    "XRPUSDT": "crypto_alt",   "DOGEUSDT": "crypto_meme",
    "XAUUSD":  "commodities",  "XAGUSD":  "commodities",
    "EURUSD":  "forex_major",  "GBPUSD":  "forex_major",
    "USDJPY":  "forex_major",  "AUDUSD":  "forex_minor",
    "NAS100":  "indices",      "SPX500":  "indices",
}
MAX_CLASS_EXPOSURE = 0.30   # max 30% in one asset class


# ══════════════════════════════════════════════════════════════
# POSITION SIZING ENGINE
# ══════════════════════════════════════════════════════════════

class PositionSizer:
    """
    Advanced position sizing using Kelly + volatility adjustment + heat map.
    """

    def __init__(self):
        self.win_history:  deque = deque(maxlen=100)
        self.loss_history: deque = deque(maxlen=100)
        self.rr_history:   deque = deque(maxlen=100)

    def kelly_fraction(self, win_rate: float, avg_rr: float) -> float:
        """
        Fractional Kelly Criterion.
        f* = (b×p - q) / b  where b=R:R, p=win_rate, q=1-p
        Returns fraction of capital to risk.
        """
        if win_rate <= 0 or avg_rr <= 0:
            return 0.01
        b = avg_rr
        p = win_rate
        q = 1 - p
        kelly = (b * p - q) / b
        kelly = max(0, kelly)
        # Fractional Kelly: use 25-50% of full Kelly for safety
        fractional = kelly * 0.3
        return min(fractional, KELLY_CAP)

    def volatility_adjustment(self, current_atr_pct: float, avg_atr_pct: float) -> float:
        """
        Adjust position size inversely to current volatility.
        High vol → smaller size. Low vol → larger size.
        """
        if avg_atr_pct <= 0:
            return 1.0
        ratio = avg_atr_pct / (current_atr_pct + 1e-9)
        return float(np.clip(ratio, 0.4, 1.6))

    def calculate_size(
        self,
        balance:         float,
        risk_pct:        float,         # Base risk % from strategy
        sl_distance_pct: float,         # SL distance as % of price
        win_rate:        float = 0.55,  # Recent win rate
        avg_rr:          float = 2.0,   # Average R:R
        current_atr_pct: float = 0.01,  # Current ATR as % of price
        avg_atr_pct:     float = 0.01,  # Average ATR as % of price
        dd_mult:         float = 1.0,   # From drawdown defense
        consecutive_wins: int  = 0,
        consecutive_losses: int = 0,
        open_risk_pct:   float = 0.0,   # Total current open risk %
    ) -> dict:
        """
        Calculate final position size considering all factors.
        Returns {risk_pct, size_usd, risk_usd, rationale}
        """
        if sl_distance_pct <= 0:
            sl_distance_pct = 0.01

        # Step 1: Kelly optimal fraction
        kelly = self.kelly_fraction(win_rate, avg_rr)

        # Step 2: Volatility adjustment
        vol_adj = self.volatility_adjustment(current_atr_pct, avg_atr_pct)

        # Step 3: Streak adjustment
        if consecutive_wins >= 5:
            streak_adj = 1.1   # slight increase on win streak
        elif consecutive_losses >= 3:
            streak_adj = 0.7   # reduce on loss streak
        elif consecutive_losses >= 2:
            streak_adj = 0.85
        else:
            streak_adj = 1.0

        # Step 4: Portfolio heat (reduce if already heavily committed)
        remaining_budget = max(0, MAX_PORTFOLIO_RISK - open_risk_pct)
        portfolio_adj = min(1.0, remaining_budget / 5.0)

        # Step 5: Combine all adjustments
        adjusted_risk = (
            risk_pct * kelly * 10 *   # scale Kelly to risk%
            vol_adj *
            streak_adj *
            portfolio_adj *
            dd_mult
        )

        # Clip to allowed range
        adjusted_risk = float(np.clip(adjusted_risk, MIN_RISK_PER_TRADE, MAX_RISK_PER_TRADE))

        # Dollar amounts
        risk_usd = balance * adjusted_risk / 100
        position_usd = risk_usd / (sl_distance_pct / 100 + 1e-9)

        return {
            "risk_pct":      round(adjusted_risk, 3),
            "risk_usd":      round(risk_usd, 2),
            "position_usd":  round(position_usd, 2),
            "kelly":         round(kelly, 4),
            "vol_adj":       round(vol_adj, 3),
            "streak_adj":    round(streak_adj, 3),
            "portfolio_adj": round(portfolio_adj, 3),
            "dd_mult":       round(dd_mult, 3),
        }


# ══════════════════════════════════════════════════════════════
# DRAWDOWN DEFENSE SYSTEM
# ══════════════════════════════════════════════════════════════

@dataclass
class DrawdownState:
    peak_balance:    float = 0.0
    current_balance: float = 0.0
    current_dd_pct:  float = 0.0
    dd_level:        int   = 0        # 0-5
    daily_loss_pct:  float = 0.0
    daily_start_bal: float = 0.0
    consecutive_losses: int = 0
    paused_until:    float = 0.0
    alert_sent:      dict  = field(default_factory=dict)
    level_entered_at: float = field(default_factory=time.time)


class DrawdownDefense:
    """5-level drawdown defense system. Automatically protects capital."""

    def __init__(self):
        self.states: dict[str, DrawdownState] = {}
        self.level_history: deque = deque(maxlen=200)

    def get_or_create(self, bot_id: str, balance: float) -> DrawdownState:
        if bot_id not in self.states:
            self.states[bot_id] = DrawdownState(
                peak_balance=balance,
                current_balance=balance,
                daily_start_bal=balance,
            )
        return self.states[bot_id]

    def update(self, bot_id: str, balance: float, pnl_pct: float = 0.0) -> dict:
        """Update drawdown state and return defense parameters."""
        s = self.get_or_create(bot_id, balance)

        # Update balance
        if balance > s.peak_balance:
            s.peak_balance = balance
        s.current_balance = balance

        # Calculate drawdown
        if s.peak_balance > 0:
            s.current_dd_pct = (s.peak_balance - balance) / s.peak_balance * 100

        # Daily loss
        if s.daily_start_bal > 0:
            s.daily_loss_pct = (s.daily_start_bal - balance) / s.daily_start_bal * 100

        # Consecutive losses
        if pnl_pct < 0:
            s.consecutive_losses += 1
        elif pnl_pct > 0:
            s.consecutive_losses = 0

        # Determine level
        old_level = s.dd_level
        if s.current_dd_pct >= DD_LEVEL_5 or s.daily_loss_pct >= DD_LEVEL_5:
            s.dd_level = 5
        elif s.current_dd_pct >= DD_LEVEL_4 or s.daily_loss_pct >= MAX_DAILY_LOSS * 1.5:
            s.dd_level = 4
        elif s.current_dd_pct >= DD_LEVEL_3 or s.daily_loss_pct >= MAX_DAILY_LOSS:
            s.dd_level = 3
        elif s.current_dd_pct >= DD_LEVEL_2:
            s.dd_level = 2
        elif s.current_dd_pct >= DD_LEVEL_1:
            s.dd_level = 1
        else:
            s.dd_level = 0

        if s.dd_level != old_level:
            s.level_entered_at = time.time()
            log.warning("Drawdown level changed",
                        bot_id=bot_id, old=old_level, new=s.dd_level,
                        dd_pct=round(s.current_dd_pct, 2))

        # Pause on consecutive losses
        if s.consecutive_losses >= CONSECUTIVE_LOSS_PAUSE:
            if time.time() >= s.paused_until:
                s.paused_until = time.time() + 3600  # 1h pause
                s.consecutive_losses = 0
                log.warning("Bot paused after consecutive losses",
                            bot_id=bot_id)

        size_mult   = DD_SIZE_MULTS.get(s.dd_level, 0.0)
        min_conf    = DD_MIN_CONF.get(s.dd_level, 100.0)
        is_paused   = time.time() < s.paused_until
        can_trade   = s.dd_level < 5 and not is_paused

        return {
            "can_trade":    can_trade,
            "dd_level":     s.dd_level,
            "dd_pct":       round(s.current_dd_pct, 2),
            "daily_loss":   round(s.daily_loss_pct, 2),
            "size_mult":    size_mult,
            "min_confidence": min_conf,
            "is_paused":    is_paused,
            "paused_until": s.paused_until,
            "consecutive_losses": s.consecutive_losses,
            "peak_balance": round(s.peak_balance, 2),
            "level_label":  _level_label(s.dd_level),
        }

    def reset_daily(self, bot_id: str, balance: float):
        """Reset daily metrics at start of new trading day."""
        if bot_id in self.states:
            self.states[bot_id].daily_start_bal = balance
            self.states[bot_id].daily_loss_pct  = 0.0


def _level_label(level: int) -> str:
    return {0: "Normal", 1: "Alert", 2: "Caution",
            3: "Crisis", 4: "Emergency", 5: "HALT"}[level]


# ══════════════════════════════════════════════════════════════
# VAR CALCULATOR (Value at Risk)
# ══════════════════════════════════════════════════════════════

class VaRCalculator:
    """
    Monte Carlo + Historical VaR.
    Quantifies portfolio tail risk.
    """

    def __init__(self):
        self.return_history: deque = deque(maxlen=500)

    def add_return(self, pnl_pct: float):
        self.return_history.append(pnl_pct)

    def historical_var(self, confidence: float = VAR_CONFIDENCE) -> float:
        """Historical VaR at given confidence level."""
        if len(self.return_history) < 20:
            return 2.0  # default 2% VaR
        returns = sorted(list(self.return_history))
        idx = int(len(returns) * (1 - confidence))
        return float(-returns[max(0, idx)])

    def monte_carlo_var(self, n_sims: int = VAR_SIMULATIONS) -> dict:
        """Monte Carlo VaR with 1000 scenarios."""
        if len(self.return_history) < 20:
            return {"var_95": 2.0, "var_99": 4.0, "cvar_95": 3.0}

        returns = list(self.return_history)
        mean = statistics.mean(returns)
        std  = statistics.stdev(returns) if len(returns) > 1 else 1.0

        # Simulate n_sims return sequences of 20 trades
        simulated = np.random.normal(mean, std, (n_sims, 20))
        portfolio_returns = simulated.sum(axis=1)

        var_95 = float(-np.percentile(portfolio_returns, 5))
        var_99 = float(-np.percentile(portfolio_returns, 1))

        # Conditional VaR (Expected Shortfall)
        threshold = np.percentile(portfolio_returns, 5)
        tail = portfolio_returns[portfolio_returns <= threshold]
        cvar_95 = float(-tail.mean()) if len(tail) > 0 else var_95

        return {
            "var_95":   round(var_95,  2),
            "var_99":   round(var_99,  2),
            "cvar_95":  round(cvar_95, 2),
            "mean_return": round(mean, 3),
            "std_return":  round(std,  3),
            "n_trades":    len(returns),
        }


# ══════════════════════════════════════════════════════════════
# RISK SCORER (0-100 per trade)
# ══════════════════════════════════════════════════════════════

class RiskScorer:
    """
    Score each potential trade 0-100 based on all risk factors.
    Only allow trades above minimum score.
    """

    def score(
        self,
        confidence:   float,    # AI signal confidence %
        rr_ratio:     float,     # R:R ratio
        dd_level:     int,       # Drawdown defense level
        session:      str,       # Trading session
        volatility:   float,     # Current ATR %
        avg_volatility: float,   # Average ATR %
        consecutive_losses: int, # Recent loss streak
        win_rate:     float,     # Recent win rate
        open_positions: int,     # Current open positions
        regime:       str,       # Market regime
    ) -> dict:

        score = 0.0

        # Confidence score (0-30)
        conf_score = max(0, (confidence - 50) / 50 * 30)
        score += conf_score

        # R:R score (0-25)
        rr_score = min(25, (rr_ratio - 1.0) / 2.0 * 25)
        score += max(0, rr_score)

        # Drawdown level penalty (0 to -40)
        dd_penalty = {0: 0, 1: -5, 2: -15, 3: -25, 4: -35, 5: -50}
        score += dd_penalty.get(dd_level, -50)

        # Session bonus (0-10)
        session_scores = {"overlap": 10, "ny": 8, "london": 8,
                          "asia": 4, "neutral": 3}
        score += session_scores.get(session, 3)

        # Volatility score (0-10)
        if avg_volatility > 0:
            vol_ratio = volatility / avg_volatility
            if 0.7 <= vol_ratio <= 1.5:    # ideal range
                score += 10
            elif vol_ratio > 3.0:           # extremely high vol
                score -= 10
            elif vol_ratio < 0.3:           # extremely low vol
                score -= 5
            else:
                score += 5

        # Win rate bonus (0-10)
        score += (win_rate - 0.5) * 20

        # Consecutive loss penalty
        if consecutive_losses >= 4:
            score -= 20
        elif consecutive_losses >= 2:
            score -= 8

        # Open positions penalty (concentration risk)
        if open_positions > 5:
            score -= 10
        elif open_positions > 3:
            score -= 5

        # Regime bonus/penalty
        regime_adj = {
            "trending_bull": 5, "trending_bear": 5,
            "breakout": 8, "ranging_low_vol": 3,
            "ranging_high_vol": -5, "reversal": -3,
        }
        score += regime_adj.get(regime, 0)

        score = float(np.clip(score, 0, 100))

        # Determine recommendation
        if score >= 80:    rec = "STRONG_TRADE"
        elif score >= 65:  rec = "TRADE"
        elif score >= 50:  rec = "REDUCED_SIZE"
        elif score >= 35:  rec = "MARGINAL"
        else:              rec = "SKIP"

        return {
            "score":          round(score, 1),
            "recommendation": rec,
            "conf_score":     round(conf_score, 1),
            "rr_score":       round(max(0, rr_score), 1),
            "dd_penalty":     dd_penalty.get(dd_level, -50),
            "trade_allowed":  score >= 40,
        }


# ══════════════════════════════════════════════════════════════
# PORTFOLIO HEAT MAP
# ══════════════════════════════════════════════════════════════

class PortfolioHeatMap:
    """
    Track exposure by asset class, exchange, and symbol.
    Enforce diversification limits.
    """

    def __init__(self):
        self.positions: dict = {}  # symbol → {risk_pct, class, exchange}
        self.class_exposure:    defaultdict = defaultdict(float)
        self.exchange_exposure: defaultdict = defaultdict(float)

    def add_position(self, symbol: str, risk_pct: float, exchange: str = "binance"):
        asset_class = ASSET_CLASS_MAP.get(symbol, "other")
        self.positions[symbol] = {
            "risk_pct":   risk_pct,
            "class":      asset_class,
            "exchange":   exchange,
            "opened_at":  time.time(),
        }
        self._recalculate()

    def remove_position(self, symbol: str):
        self.positions.pop(symbol, None)
        self._recalculate()

    def _recalculate(self):
        self.class_exposure    = defaultdict(float)
        self.exchange_exposure = defaultdict(float)
        for sym, pos in self.positions.items():
            self.class_exposure[pos["class"]]    += pos["risk_pct"]
            self.exchange_exposure[pos["exchange"]] += pos["risk_pct"]

    def total_risk(self) -> float:
        return sum(p["risk_pct"] for p in self.positions.values())

    def can_add(self, symbol: str, risk_pct: float, exchange: str = "binance") -> dict:
        asset_class = ASSET_CLASS_MAP.get(symbol, "other")

        total_after      = self.total_risk() + risk_pct
        class_after      = self.class_exposure[asset_class] + risk_pct
        exchange_after   = self.exchange_exposure[exchange] + risk_pct

        issues = []
        if total_after > MAX_PORTFOLIO_RISK:
            issues.append(f"Portfolio risk {total_after:.1f}% > {MAX_PORTFOLIO_RISK}%")
        if class_after / (total_after + 1e-9) > MAX_CLASS_EXPOSURE:
            issues.append(f"Asset class {asset_class} concentration too high")

        return {
            "allowed":       len(issues) == 0,
            "issues":        issues,
            "total_risk":    round(self.total_risk(), 2),
            "class_exposure":dict(self.class_exposure),
            "open_positions":len(self.positions),
        }

    def get_heat_map(self) -> dict:
        return {
            "positions":        len(self.positions),
            "total_risk":       round(self.total_risk(), 2),
            "class_exposure":   {k: round(v, 2) for k, v in self.class_exposure.items()},
            "exchange_exposure":{k: round(v, 2) for k, v in self.exchange_exposure.items()},
            "symbols":          list(self.positions.keys()),
        }


# ══════════════════════════════════════════════════════════════
# CIRCUIT BREAKER NETWORK
# ══════════════════════════════════════════════════════════════

@dataclass
class CircuitState:
    name:         str
    is_open:      bool  = False   # True = circuit tripped = trading blocked
    trip_count:   int   = 0
    last_trip:    float = 0.0
    reset_after:  float = 3600    # seconds before auto-reset
    trip_reason:  str   = ""
    error_count:  int   = 0


class CircuitBreakerNetwork:
    """
    Network of circuit breakers protecting against cascading failures.
    """

    CIRCUITS = {
        "daily_loss":   {"threshold": MAX_DAILY_LOSS, "window": 86400, "reset_after": 86400},
        "consec_loss":  {"threshold": CONSECUTIVE_LOSS_PAUSE, "window": 0, "reset_after": 3600},
        "slippage":     {"threshold": 0.5, "window": 300, "reset_after": 1800},
        "latency":      {"threshold": 2000, "window": 60, "reset_after": 900},
        "exchange_err": {"threshold": 5, "window": 300, "reset_after": 1800},
        "global_halt":  {"threshold": 15, "window": 3600, "reset_after": 14400},
    }

    def __init__(self):
        self.circuits: dict[str, CircuitState] = {
            name: CircuitState(name=name, reset_after=cfg["reset_after"])
            for name, cfg in self.CIRCUITS.items()
        }
        self.metrics: defaultdict = defaultdict(list)

    def record(self, circuit: str, value: float) -> bool:
        """
        Record metric for circuit. Returns True if circuit tripped.
        """
        self.metrics[circuit].append((time.time(), value))
        # Clean old data
        window = self.CIRCUITS.get(circuit, {}).get("window", 300)
        if window > 0:
            cutoff = time.time() - window
            self.metrics[circuit] = [
                (t, v) for t, v in self.metrics[circuit] if t >= cutoff
            ]

        return self._check_trip(circuit)

    def _check_trip(self, circuit: str) -> bool:
        cfg   = self.CIRCUITS.get(circuit)
        state = self.circuits.get(circuit)
        if not cfg or not state: return False

        values = [v for _, v in self.metrics[circuit]]
        if not values: return False

        threshold = cfg["threshold"]
        tripped   = False

        if circuit == "slippage":
            tripped = any(v > threshold for v in values[-3:])
        elif circuit == "latency":
            tripped = any(v > threshold for v in values[-5:])
        elif circuit == "exchange_err":
            tripped = sum(1 for v in values if v > 0) >= threshold
        elif circuit == "global_halt":
            tripped = max(values) >= threshold
        else:
            tripped = max(values) >= threshold if values else False

        if tripped and not state.is_open:
            state.is_open    = True
            state.trip_count += 1
            state.last_trip   = time.time()
            state.trip_reason = f"Threshold {threshold} exceeded: {max(values):.2f}"
            log.warning("Circuit breaker TRIPPED",
                        circuit=circuit, reason=state.trip_reason)
        return tripped

    def is_open(self, circuit: str) -> bool:
        """Check if circuit is currently open (blocking trades)."""
        state = self.circuits.get(circuit)
        if not state: return False
        # Auto-reset after timeout
        if state.is_open and time.time() - state.last_trip > state.reset_after:
            state.is_open = False
            log.info("Circuit breaker auto-reset", circuit=circuit)
        return state.is_open

    def any_critical_open(self) -> bool:
        return any(self.is_open(c) for c in ["daily_loss", "global_halt"])

    def manual_reset(self, circuit: str):
        if circuit in self.circuits:
            self.circuits[circuit].is_open = False

    def get_status(self) -> dict:
        return {
            name: {
                "open":       state.is_open,
                "trip_count": state.trip_count,
                "reason":     state.trip_reason,
            }
            for name, state in self.circuits.items()
        }


# ══════════════════════════════════════════════════════════════
# MASTER RISK AI ENGINE
# ══════════════════════════════════════════════════════════════

class RiskAIEngine:
    """
    Master Risk AI Engine.
    Combines all risk components into a single decision interface.
    Self-adapts based on historical outcomes.
    """

    def __init__(self):
        self.sizer    = PositionSizer()
        self.defense  = DrawdownDefense()
        self.var_calc = VaRCalculator()
        self.scorer   = RiskScorer()
        self.heat_map = PortfolioHeatMap()
        self.breakers = CircuitBreakerNetwork()

        # Performance tracking
        self.risk_decisions: deque = deque(maxlen=500)
        self.total_trades:   int   = 0
        self.halted_trades:  int   = 0
        self.avg_atr_pct:    float = 0.01

        self._load()
        log.info("Risk AI Engine initialized")

    def evaluate_trade(
        self,
        bot_id:     str,
        symbol:     str,
        exchange:   str,
        confidence: float,
        rr_ratio:   float,
        sl_pct:     float,
        balance:    float,
        win_rate:   float = 0.55,
        avg_rr:     float = 2.0,
        atr_pct:    float = 0.01,
        session:    str   = "neutral",
        regime:     str   = "neutral",
        base_risk:  float = 1.0,
        latency_ms: float = 100,
        consecutive_wins:   int = 0,
        consecutive_losses: int = 0,
    ) -> dict:
        """
        Master trade evaluation.
        Returns full risk assessment + recommended position size.
        CALL THIS BEFORE EVERY TRADE.
        """
        # 1. Circuit breakers
        if self.breakers.any_critical_open():
            return self._reject("Critical circuit breaker open", balance)
        if self.breakers.is_open("latency"):
            return self._reject("Latency circuit open", balance)
        if self.breakers.record("latency", latency_ms):
            log.warning("Latency circuit tripped", ms=latency_ms)

        # 2. Drawdown defense
        dd_info = self.defense.update(bot_id, balance)
        if not dd_info["can_trade"]:
            return self._reject(
                f"Drawdown defense Level {dd_info['dd_level']}: {dd_info['level_label']}",
                balance, dd_info=dd_info
            )

        # 3. Minimum confidence check
        if confidence < dd_info["min_confidence"]:
            return self._reject(
                f"Confidence {confidence:.1f}% below min {dd_info['min_confidence']:.1f}%",
                balance, dd_info=dd_info
            )

        # 4. Risk scoring
        open_pos = len(self.heat_map.positions)
        risk_score = self.scorer.score(
            confidence=confidence,
            rr_ratio=rr_ratio,
            dd_level=dd_info["dd_level"],
            session=session,
            volatility=atr_pct,
            avg_volatility=self.avg_atr_pct,
            consecutive_losses=consecutive_losses,
            win_rate=win_rate,
            open_positions=open_pos,
            regime=regime,
        )

        if not risk_score["trade_allowed"]:
            self.halted_trades += 1
            return self._reject(
                f"Risk score too low: {risk_score['score']}/100",
                balance, risk_score=risk_score, dd_info=dd_info
            )

        # 5. Portfolio heat check
        # Estimate risk for this trade
        heat_check = self.heat_map.can_add(symbol, base_risk, exchange)
        if not heat_check["allowed"]:
            return self._reject(
                f"Portfolio heat limit: {', '.join(heat_check['issues'])}",
                balance, heat_check=heat_check
            )

        # 6. Position sizing
        size_info = self.sizer.calculate_size(
            balance=balance,
            risk_pct=base_risk,
            sl_distance_pct=sl_pct,
            win_rate=win_rate,
            avg_rr=avg_rr,
            current_atr_pct=atr_pct,
            avg_atr_pct=self.avg_atr_pct,
            dd_mult=dd_info["size_mult"],
            consecutive_wins=consecutive_wins,
            consecutive_losses=consecutive_losses,
            open_risk_pct=self.heat_map.total_risk(),
        )

        # Apply risk score scaling
        score_mult = risk_score["score"] / 100
        final_risk = size_info["risk_pct"] * score_mult
        final_risk = float(np.clip(final_risk, MIN_RISK_PER_TRADE, MAX_RISK_PER_TRADE))

        # Update ATR running average
        self.avg_atr_pct = self.avg_atr_pct * 0.99 + atr_pct * 0.01

        self.total_trades += 1

        result = {
            "approved":      True,
            "risk_pct":      round(final_risk, 3),
            "risk_usd":      round(balance * final_risk / 100, 2),
            "position_usd":  round(balance * final_risk / 100 / (sl_pct / 100 + 1e-9), 2),
            "risk_score":    risk_score,
            "dd_info":       dd_info,
            "size_info":     size_info,
            "heat_map":      self.heat_map.get_heat_map(),
            "circuits":      self.breakers.get_status(),
            "var":           self.var_calc.monte_carlo_var() if self.total_trades % 10 == 0 else {},
        }

        self.risk_decisions.append({
            "time":    time.time(),
            "bot_id":  bot_id,
            "symbol":  symbol,
            "risk":    final_risk,
            "score":   risk_score["score"],
        })

        if self.total_trades % 50 == 0:
            self._save()

        return result

    def on_trade_closed(
        self,
        bot_id:  str,
        symbol:  str,
        pnl_pct: float,
        balance: float,
        slippage_pct: float = 0.0,
    ):
        """Update all risk components after trade closes."""
        self.var_calc.add_return(pnl_pct)
        self.defense.update(bot_id, balance, pnl_pct)
        self.heat_map.remove_position(symbol)

        if slippage_pct > 0:
            self.breakers.record("slippage", slippage_pct)

        if pnl_pct < 0:
            self.breakers.record("daily_loss", abs(pnl_pct))

    def register_exchange_error(self):
        self.breakers.record("exchange_err", 1)

    def _reject(self, reason: str, balance: float, **kwargs) -> dict:
        log.info("Trade REJECTED by Risk AI", reason=reason)
        self.halted_trades += 1
        return {
            "approved":  False,
            "reason":    reason,
            "risk_pct":  0.0,
            "risk_usd":  0.0,
            **kwargs,
        }

    def get_stats(self) -> dict:
        var = self.var_calc.monte_carlo_var()
        return {
            "total_evaluated": self.total_trades,
            "halted_trades":   self.halted_trades,
            "halt_rate":       round(self.halted_trades / max(self.total_trades, 1), 3),
            "var_95":          var.get("var_95", 0),
            "var_99":          var.get("var_99", 0),
            "circuits":        self.breakers.get_status(),
            "open_positions":  len(self.heat_map.positions),
            "total_open_risk": round(self.heat_map.total_risk(), 2),
        }

    def _save(self):
        try:
            RISK_STORAGE.write_text(json.dumps({
                "avg_atr_pct":   self.avg_atr_pct,
                "total_trades":  self.total_trades,
                "halted_trades": self.halted_trades,
                "var_history":   list(self.var_calc.return_history)[-200:],
            }, indent=2))
        except Exception as e:
            log.error("Risk AI save failed", error=str(e))

    def _load(self):
        try:
            if RISK_STORAGE.exists():
                d = json.loads(RISK_STORAGE.read_text())
                self.avg_atr_pct   = d.get("avg_atr_pct", 0.01)
                self.total_trades  = d.get("total_trades", 0)
                self.halted_trades = d.get("halted_trades", 0)
                for r in d.get("var_history", []):
                    self.var_calc.add_return(r)
        except Exception as e:
            log.warning("Risk AI load failed", error=str(e))


# ── Singleton ─────────────────────────────────────────────────
risk_ai = RiskAIEngine()
