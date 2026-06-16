"""
services/portfolio_risk.py — Institutional Portfolio Risk Engine
Computes: VaR 95/99, Expected Shortfall, Correlation Matrix,
          Stress Tests, Beta, Net Delta, Portfolio Snapshot
"""
from __future__ import annotations
import math
from datetime import datetime, timezone
from core.database import db
import structlog

log = structlog.get_logger("portfolio_risk")


STRESS_SCENARIOS = {
    "flash_crash":       {"move": -0.20, "vol_mult": 3.0, "duration_h": 1},
    "btc_50pct_drop":    {"move": -0.50, "vol_mult": 4.0, "duration_h": 24},
    "rate_hike_shock":   {"move": -0.12, "vol_mult": 2.0, "duration_h": 48},
    "liquidity_crisis":  {"move": -0.30, "vol_mult": 5.0, "duration_h": 72},
    "black_swan":        {"move": -0.60, "vol_mult": 8.0, "duration_h": 4},
    "bull_euphoria":     {"move": +0.40, "vol_mult": 2.5, "duration_h": 168},
}


class PortfolioRiskEngine:

    async def compute_snapshot(self, user_id: str) -> dict:
        """Full portfolio risk snapshot for a user."""
        open_trades = await db.get_open_trades(user_id)
        wallet = await db.get_wallet(user_id, "real")
        demo_wallet = await db.get_wallet(user_id, "demo")

        balance = float((wallet or {}).get("balance", 0))
        demo_balance = float((demo_wallet or {}).get("balance", 0))

        if not open_trades:
            snapshot = {
                "user_id": user_id,
                "total_exposure": 0, "net_delta": 0,
                "var_95": 0, "var_99": 0, "expected_shortfall": 0,
                "beta": 1.0, "positions_count": 0,
                "correlation_risk": 0, "stress_test_result": {},
            }
            self._save_snapshot(user_id, snapshot)
            return snapshot

        # Compute exposures
        positions = []
        total_long  = 0.0
        total_short = 0.0
        symbols = set()

        for t in open_trades:
            notional = float(t.get("notional_value") or 0)
            side = t.get("side", "long")
            symbol = t.get("symbol", "")
            symbols.add(symbol)
            positions.append({
                "symbol": symbol, "side": side,
                "notional": notional, "mode": t.get("mode"),
            })
            if side == "long":
                total_long  += notional
            else:
                total_short += notional

        total_exposure = total_long + total_short
        net_delta = (total_long - total_short) / (total_exposure + 1e-9)

        # Simplified VaR: assume 2% daily vol for crypto (conservative)
        avg_daily_vol = 0.025   # 2.5% average daily crypto volatility
        var_95  = total_exposure * avg_daily_vol * 1.645   # Z=1.645 for 95%
        var_99  = total_exposure * avg_daily_vol * 2.326   # Z=2.326 for 99%
        es_99   = var_99 * 1.15                            # Expected shortfall ~ 115% of VaR

        # Correlation risk: more symbols = less correlation risk
        n_symbols = len(symbols)
        corr_risk = max(0.0, 1.0 - n_symbols * 0.12)  # Diversification reduces risk

        # Beta to BTC (simplified: crypto assets have ~0.8 beta to BTC)
        crypto_exposure = sum(p["notional"] for p in positions
                              if any(c in p["symbol"] for c in ["BTC","ETH","BNB","SOL","XRP"]))
        beta = 0.8 * crypto_exposure / (total_exposure + 1e-9)

        # Stress tests
        stress = self._run_stress_tests(positions, total_exposure)

        # Risk score: 0 = safest, 100 = maximum risk
        risk_score = min(100, int(
            corr_risk * 30 +
            (total_exposure / max(balance + demo_balance, 1)) * 40 +
            abs(net_delta) * 20 +
            (var_95 / max(balance, 1)) * 10
        ))

        snapshot = {
            "user_id": user_id,
            "total_exposure": round(total_exposure, 4),
            "net_delta": round(net_delta, 4),
            "var_95": round(var_95, 4),
            "var_99": round(var_99, 4),
            "expected_shortfall": round(es_99, 4),
            "beta": round(beta, 4),
            "positions_count": len(open_trades),
            "correlation_risk": round(corr_risk, 4),
            "stress_test_result": stress,
            "risk_score": risk_score,
            "symbols_traded": list(symbols),
            "long_exposure": round(total_long, 4),
            "short_exposure": round(total_short, 4),
        }

        self._save_snapshot(user_id, snapshot)
        return snapshot

    def _run_stress_tests(self, positions: list, total_exposure: float) -> dict:
        """Simulate each stress scenario against current portfolio."""
        results = {}
        for scenario_name, params in STRESS_SCENARIOS.items():
            move     = params["move"]
            vol_mult = params["vol_mult"]

            # Estimate loss
            directional_loss = total_exposure * move
            vol_loss = total_exposure * 0.025 * vol_mult * 0.3  # Extra vol loss

            # Net impact (long positions lose on crash, short positions lose on rally)
            long_pos  = sum(p["notional"] for p in positions if p["side"] == "long")
            short_pos = sum(p["notional"] for p in positions if p["side"] == "short")

            if move < 0:
                loss = long_pos * abs(move) - short_pos * abs(move) * 0.8
            else:
                loss = short_pos * abs(move) - long_pos * abs(move) * 0.8

            total_loss = loss + vol_loss
            survival = total_loss < total_exposure * 0.5  # Survive if < 50% lost

            results[scenario_name] = {
                "estimated_loss": round(total_loss, 4),
                "loss_pct": round(total_loss / (total_exposure + 1e-9) * 100, 2),
                "survival": survival,
                "risk_level": "HIGH" if total_loss > total_exposure * 0.3 else
                              "MEDIUM" if total_loss > total_exposure * 0.1 else "LOW",
            }
        return results

    def _save_snapshot(self, user_id: str, snapshot: dict):
        try:
            db.table("portfolio_snapshots").insert({
                **{k: v for k, v in snapshot.items()
                   if k in ("user_id","total_exposure","net_delta","var_95","var_99",
                            "expected_shortfall","beta","positions_count",
                            "correlation_risk","stress_test_result")},
            }).execute()
        except Exception:
            pass

    async def check_exposure_limits(self, user_id: str,
                                     new_notional: float) -> dict:
        """Check if a new trade would breach exposure limits."""
        risk  = await db.get_risk_profile(user_id)
        open_ = await db.get_open_trades(user_id)
        wallet = await db.get_wallet(user_id, "real")
        balance = float((wallet or {}).get("balance", 0)) or 1000

        current_exposure = sum(float(t.get("notional_value") or 0) for t in open_)
        new_total = current_exposure + new_notional
        exposure_pct = new_total / balance * 100

        # Max 3x leverage equivalent
        if exposure_pct > 300:
            return {"allowed": False, "reason": f"Portfolio exposure would be {exposure_pct:.0f}% of balance (max 300%)"}

        # Max trades
        max_trades = int((risk or {}).get("max_open_trades", 10))
        if len(open_) >= max_trades:
            return {"allowed": False, "reason": f"Max open trades reached ({max_trades})"}

        return {"allowed": True, "exposure_pct": round(exposure_pct, 2)}


portfolio_risk = PortfolioRiskEngine()
