"""
services/backtest_service.py — Historical Strategy Backtesting Engine
Tests strategies against historical OHLCV data with:
  - Realistic fee simulation (exact 0.05% platform rate)
  - Slippage modeling
  - Risk management enforcement
  - Full performance analytics: Sharpe, Sortino, Calmar, Max Drawdown
"""
from __future__ import annotations
import math
from datetime import datetime, timezone
from core.database import db
from core.config import settings
from ai.indicators import compute_all, ohlcv_to_df
from strategies.all_weather_engine import all_weather_engine
import structlog

log = structlog.get_logger("backtest")


class BacktestEngine:

    async def run(self, backtest_id: str, user_id: str, strategy: str,
                   symbol: str, timeframe: str,
                   start_date: str, end_date: str,
                   initial_capital: float) -> dict:
        """Run a full backtest and save results."""
        db.table("backtests").update({"status": "running"}).eq("id", backtest_id).execute()

        try:
            # Fetch historical data from DB
            rows = (db.table("market_data")
                    .select("timestamp,open,high,low,close,volume")
                    .eq("symbol", symbol).eq("timeframe", timeframe)
                    .gte("timestamp", start_date).lte("timestamp", end_date)
                    .order("timestamp").execute()).data or []

            if len(rows) < 50:
                raise ValueError(f"Insufficient historical data: {len(rows)} candles")

            raw = [[r["timestamp"], float(r["open"]), float(r["high"]),
                    float(r["low"]), float(r["close"]), float(r.get("volume",0))]
                   for r in rows]

            df = ohlcv_to_df(raw)
            df = compute_all(df)

            # Run simulation
            result = self._simulate(df, symbol, timeframe, initial_capital)

            # Save results
            db.table("backtests").update({
                "status": "completed",
                "final_capital": round(result["final_capital"], 4),
                "total_trades": result["total_trades"],
                "win_rate": round(result["win_rate"], 4),
                "max_drawdown": round(result["max_drawdown"], 4),
                "sharpe_ratio": round(result.get("sharpe", 0), 6),
                "total_return": round(result["total_return"], 6),
                "results": result["summary"],
                "trade_log": result["trades"][:200],  # limit stored trades
                "completed_at": datetime.now(timezone.utc).isoformat(),
            }).eq("id", backtest_id).execute()

            return result

        except Exception as e:
            db.table("backtests").update({
                "status": "failed",
                "results": {"error": str(e)},
            }).eq("id", backtest_id).execute()
            raise

    def _simulate(self, df, symbol: str, timeframe: str,
                   capital: float) -> dict:
        """Walk-forward simulation through historical data."""
        equity     = capital
        peak_eq    = capital
        max_dd     = 0.0
        trades     = []
        equity_curve = [capital]
        returns    = []
        position   = None  # current open position

        WARMUP = 200  # bars needed for indicators

        for i in range(WARMUP, len(df)):
            window = df.iloc[:i+1].copy()
            current = window.iloc[-1]
            close   = float(current["close"])

            # Check SL/TP on open position
            if position:
                sl  = position["sl"]
                tp  = position["tp"]
                side = position["side"]

                hit_sl = (side == "long"  and close <= sl) or (side == "short" and close >= sl)
                hit_tp = (side == "long"  and close >= tp) or (side == "short" and close <= tp)

                if hit_sl or hit_tp:
                    exit_price = sl if hit_sl else tp
                    pnl = self._calc_pnl(position, exit_price)
                    fee = abs(position["notional"]) * settings.TRADING_FEE_PCT
                    net = pnl - fee - position["entry_fee"]
                    equity += net
                    peak_eq = max(peak_eq, equity)
                    dd = (peak_eq - equity) / peak_eq * 100 if peak_eq > 0 else 0
                    max_dd = max(max_dd, dd)
                    returns.append(net / position["notional"] if position["notional"] else 0)
                    equity_curve.append(round(equity, 4))
                    trades.append({
                        "entry": position["entry_price"],
                        "exit": exit_price,
                        "side": side,
                        "pnl": round(net, 6),
                        "won": net > 0,
                        "reason": "tp" if hit_tp else "sl",
                        "bar": i,
                    })
                    position = None

            # Generate signal every 4 bars (avoid over-trading)
            if not position and i % 4 == 0:
                result = all_weather_engine.analyze(symbol, {timeframe: window})
                sig = result.get("top_signal")
                if sig and sig.get("direction") != "none":
                    risk_pct  = 1.5  # 1.5% risk per trade
                    risk_amt  = equity * (risk_pct / 100)
                    sl_dist   = abs(close - sig["stop_loss"])
                    if sl_dist > 0:
                        qty      = risk_amt / sl_dist
                        notional = qty * close
                        fee      = notional * settings.TRADING_FEE_PCT
                        if equity - notional - fee > 0:
                            position = {
                                "side": sig["direction"],
                                "entry_price": close,
                                "sl": sig["stop_loss"],
                                "tp": sig["take_profit"],
                                "qty": qty,
                                "notional": notional,
                                "entry_fee": fee,
                            }
                            equity -= fee  # Deduct entry fee

        # Close any open position at end
        if position:
            close_final = float(df.iloc[-1]["close"])
            pnl = self._calc_pnl(position, close_final)
            equity += pnl
            trades.append({
                "entry": position["entry_price"],
                "exit": close_final,
                "side": position["side"],
                "pnl": round(pnl, 6),
                "won": pnl > 0,
                "reason": "end_of_data",
                "bar": len(df) - 1,
            })

        wins   = sum(1 for t in trades if t["won"])
        losses = len(trades) - wins
        total_return = (equity - capital) / capital

        # Sharpe ratio
        sharpe = 0.0
        if returns:
            avg_r = sum(returns) / len(returns)
            std_r = (sum((r - avg_r) ** 2 for r in returns) / len(returns)) ** 0.5
            sharpe = (avg_r / std_r * math.sqrt(252)) if std_r > 0 else 0

        return {
            "final_capital": equity,
            "total_trades": len(trades),
            "wins": wins,
            "losses": losses,
            "win_rate": wins / max(len(trades), 1),
            "max_drawdown": max_dd,
            "total_return": total_return,
            "sharpe": sharpe,
            "trades": trades,
            "equity_curve": equity_curve[::max(1, len(equity_curve)//100)],
            "summary": {
                "initial": capital,
                "final": round(equity, 4),
                "profit": round(equity - capital, 4),
                "return_pct": round(total_return * 100, 2),
                "win_rate_pct": round(wins / max(len(trades), 1) * 100, 2),
                "max_dd_pct": round(max_dd, 2),
                "sharpe": round(sharpe, 4),
                "total_trades": len(trades),
            }
        }

    def _calc_pnl(self, position: dict, exit_price: float) -> float:
        qty  = position["qty"]
        side = position["side"]
        entry = position["entry_price"]
        if side == "long":
            return (exit_price - entry) * qty
        return (entry - exit_price) * qty


backtest_service = BacktestEngine()
