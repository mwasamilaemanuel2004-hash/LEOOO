"""
services/demo_engine.py — Full Demo Trading Simulation Engine
Simulates real market execution with:
  - Realistic slippage (market impact model)
  - Variable execution delay (5-500ms)
  - Fee simulation at exact platform rate
  - Partial fills for large orders
  - Price feed from live exchange data
"""
from __future__ import annotations
import asyncio, random, time
from datetime import datetime, timezone
from core.database import db
from core.config import settings
import structlog

log = structlog.get_logger("demo_engine")


class DemoEngine:
    """
    Simulates trade execution against live market data.
    Used for demo mode — never touches real funds or exchange APIs.
    """

    # Slippage model: basis points by order size tier
    SLIPPAGE_TABLE = [
        (100,    0.0001),  # < $100   → 0.01 bps
        (1000,   0.0003),  # < $1k    → 0.03 bps
        (10000,  0.0008),  # < $10k   → 0.08 bps
        (100000, 0.0020),  # < $100k  → 0.20 bps
        (float("inf"), 0.0050),  # larger → 0.50 bps
    ]

    def _compute_slippage(self, notional: float, side: str) -> float:
        """Market impact slippage — larger orders slip more."""
        base_slip = next(
            slip for threshold, slip in self.SLIPPAGE_TABLE if notional < threshold
        )
        # Add random noise: ±30%
        noise = random.uniform(0.7, 1.3)
        slippage = base_slip * noise
        # Buy orders slip up, sell orders slip down
        return slippage if side == "buy" else -slippage

    def _compute_delay(self) -> float:
        """Simulate network + matching engine latency (ms)."""
        # Bimodal: fast execution (80%) or slow (20%)
        if random.random() < 0.8:
            return random.uniform(15, 120)   # Normal: 15-120ms
        return random.uniform(200, 500)       # Slow: 200-500ms

    async def simulate_fill(
        self,
        order_id: str,
        symbol: str,
        side: str,          # buy | sell
        quantity: float,
        market_price: float,
        notional: float,
    ) -> dict:
        """
        Simulate order fill with realistic market dynamics.
        Returns fill details including actual fill price, slippage, fee.
        """
        # Simulate execution delay
        delay_ms = self._compute_delay()
        await asyncio.sleep(delay_ms / 1000)

        # Compute fill price with slippage
        slippage_pct = self._compute_slippage(notional, side)
        fill_price = market_price * (1 + slippage_pct)

        # Simulate partial fill (5% chance for large orders)
        fill_ratio = 1.0
        if notional > 5000 and random.random() < 0.05:
            fill_ratio = random.uniform(0.7, 0.95)
            log.info("partial_fill", order_id=order_id, ratio=fill_ratio)

        filled_qty   = round(quantity * fill_ratio, 8)
        filled_value = filled_qty * fill_price

        # Fee calculation (always server-side)
        fee = filled_value * settings.TRADING_FEE_PCT

        # Record simulation details
        sim = db.table("demo_simulations").insert({
            "user_id": None,  # set by caller
            "bot_id": None,   # set by caller
            "symbol": symbol,
            "simulated_entry": fill_price,
            "slippage_pct": round(slippage_pct, 8),
            "execution_delay_ms": int(delay_ms),
            "simulated_fee": round(fee, 8),
        }).execute()

        return {
            "order_id": order_id,
            "fill_price": round(fill_price, 8),
            "filled_qty": filled_qty,
            "filled_value": round(filled_value, 8),
            "slippage_pct": round(slippage_pct * 100, 6),
            "fee": round(fee, 8),
            "execution_delay_ms": int(delay_ms),
            "partial_fill": fill_ratio < 1.0,
            "fill_ratio": round(fill_ratio, 4),
            "simulation_id": sim.data[0]["id"] if sim.data else None,
        }

    async def get_demo_price(self, symbol: str) -> float:
        """
        Fetch current price from market_data table or use fallback.
        Demo bots use same live price feed as live bots.
        """
        row = (db.table("market_data")
               .select("close")
               .eq("symbol", symbol.replace("/", ""))
               .order("timestamp", desc=True)
               .limit(1)
               .single()
               .execute()).data
        if row:
            return float(row["close"])
        # Fallback: reasonable demo prices
        FALLBACK = {
            "BTC/USDT": 68000.0, "ETH/USDT": 3600.0,
            "BNB/USDT": 580.0,   "SOL/USDT": 185.0,
            "XRP/USDT": 0.62,    "ADA/USDT": 0.48,
        }
        return FALLBACK.get(symbol, 100.0)

    async def check_sl_tp_demo(self, trade_id: str) -> dict | None:
        """
        For demo trades: check SL/TP against current market price.
        Called by the trading loop monitor.
        """
        trade = (db.table("trades")
                 .select("*")
                 .eq("id", trade_id)
                 .eq("status", "open")
                 .eq("mode", "demo")
                 .single()
                 .execute()).data
        if not trade:
            return None

        current_price = await self.get_demo_price(trade["symbol"])

        sl  = float(trade.get("stop_loss") or 0)
        tp  = float(trade.get("take_profit") or 0)
        side = trade["side"]

        hit_sl = (side == "long"  and sl  > 0 and current_price <= sl) or \
                 (side == "short" and sl  > 0 and current_price >= sl)
        hit_tp = (side == "long"  and tp  > 0 and current_price >= tp) or \
                 (side == "short" and tp  > 0 and current_price <= tp)

        if hit_sl or hit_tp:
            reason = "sl_hit" if hit_sl else "tp_hit"
            return {"trade_id": trade_id, "reason": reason,
                    "exit_price": current_price, "user_id": trade["user_id"]}
        return None


demo_engine = DemoEngine()
