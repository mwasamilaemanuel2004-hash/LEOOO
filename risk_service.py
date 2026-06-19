"""
services/smart_router.py — Smart Order Routing + Arbitrage Detection
Queries multiple exchanges simultaneously, routes to best price,
detects and logs arbitrage opportunities.
"""
from __future__ import annotations
import asyncio, time
from core.database import db
import structlog

log = structlog.get_logger("smart_router")


class SmartOrderRouter:
    """
    Queries Binance, Bybit, KuCoin simultaneously for best price.
    Routes order to exchange with best execution price.
    Also logs arbitrage opportunities when spread > threshold.
    """

    EXCHANGES = ["binance", "bybit", "kucoin"]

    async def get_best_price(self, symbol: str, side: str,
                              user_id: str) -> dict:
        """
        Fetch current price from all user-connected exchanges.
        Returns best exchange + prices from all.
        """
        connections = (db.table("exchange_connections")
                       .select("id,exchange,status")
                       .eq("user_id", user_id)
                       .eq("status", "active")
                       .execute()).data or []

        if len(connections) < 2:
            # Only one exchange — no routing possible
            if connections:
                return {"exchange": connections[0]["exchange"],
                        "conn_id": connections[0]["id"],
                        "prices": {}, "price_saved": 0}
            return {}

        # Fetch prices in parallel
        prices: dict = {}
        tasks = []
        for conn in connections:
            tasks.append(self._fetch_price(conn["id"], conn["exchange"], symbol))

        results = await asyncio.gather(*tasks, return_exceptions=True)
        for conn, result in zip(connections, results):
            if isinstance(result, dict) and "price" in result:
                prices[conn["exchange"]] = {
                    "price": result["price"],
                    "conn_id": conn["id"],
                }

        if not prices:
            return {}

        # Best price: lowest ask for buys, highest bid for sells
        if side == "buy":
            best_exch = min(prices, key=lambda x: prices[x]["price"])
        else:
            best_exch = max(prices, key=lambda x: prices[x]["price"])

        best_price  = prices[best_exch]["price"]
        other_prices = {k: v["price"] for k, v in prices.items() if k != best_exch}
        avg_other    = sum(other_prices.values()) / len(other_prices) if other_prices else best_price

        if side == "buy":
            price_saved_pct = (avg_other - best_price) / avg_other if avg_other else 0
        else:
            price_saved_pct = (best_price - avg_other) / avg_other if avg_other else 0

        # Log routing decision
        db.table("order_routing_log").insert({
            "symbol": symbol,
            "exchange_prices": {k: v["price"] for k, v in prices.items()},
            "best_exchange": best_exch,
            "price_saved": round(price_saved_pct * 100, 6),
            "routing_ms": 0,
        }).execute()

        # Check for arbitrage opportunity
        if len(prices) >= 2:
            await self._check_arbitrage(symbol, prices)

        return {
            "exchange": best_exch,
            "conn_id": prices[best_exch]["conn_id"],
            "best_price": best_price,
            "all_prices": {k: v["price"] for k, v in prices.items()},
            "price_saved_pct": round(price_saved_pct * 100, 4),
        }

    async def _fetch_price(self, conn_id: str, exchange: str, symbol: str) -> dict:
        try:
            from exchanges.exchange_service import exchange_service
            ticker = await exchange_service.get_ticker(conn_id, symbol)
            return {"price": float(ticker.get("last", 0)), "exchange": exchange}
        except Exception as e:
            return {"error": str(e)}

    async def _check_arbitrage(self, symbol: str, prices: dict):
        """Flag arbitrage opportunities with spread > threshold."""
        min_spread = 0.002  # 0.2%
        price_list = [(exch, data["price"]) for exch, data in prices.items()]
        price_list.sort(key=lambda x: x[1])

        buy_exch, buy_price   = price_list[0]
        sell_exch, sell_price = price_list[-1]

        spread_pct = (sell_price - buy_price) / buy_price
        if spread_pct > min_spread:
            log.info("arb_detected", symbol=symbol, spread=spread_pct,
                     buy=buy_exch, sell=sell_exch)
            db.table("arb_opportunities").insert({
                "symbol": symbol,
                "buy_exchange": buy_exch,
                "sell_exchange": sell_exch,
                "buy_price": buy_price,
                "sell_price": sell_price,
                "spread_pct": round(spread_pct, 8),
                "est_profit_usd": round((sell_price - buy_price) * 0.01, 4),  # per unit
            }).execute()


smart_router = SmartOrderRouter()
