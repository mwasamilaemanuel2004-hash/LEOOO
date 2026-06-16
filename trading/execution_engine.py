import asyncio
import time
import redis.asyncio as redis
from core.config import settings
from services.exchange_service import exchange_service
import structlog

log = structlog.get_logger("execution_engine")

class ExecutionEngine:
    """
    Ultra-low latency execution engine using Redis for caching and
    parallel order processing.
    """

    def __init__(self):
        self.redis = redis.from_url(settings.redis_url) if settings.redis_url else None
        self.order_queue = asyncio.Queue()

    async def execute_parallel_order(self, orders: list[dict], user_id: str):
        """
        Execute multiple orders across different exchanges simultaneously.
        Ideal for Spatial Arbitrage.
        """
        start_time = time.perf_counter()

        async def place_single(order):
            client = await exchange_service.get_client(user_id, order["exchange"])
            return await client.create_order(
                symbol=order["symbol"],
                type=order["type"],
                side=order["side"],
                amount=order["amount"],
                price=order.get("price")
            )

        results = await asyncio.gather(*[place_single(o) for o in orders], return_exceptions=True)

        latency = (time.perf_counter() - start_time) * 1000
        log.info("parallel_execution_complete", latency_ms=latency, orders_count=len(orders))

        return results

    async def cache_price(self, exchange: str, symbol: str, price: float):
        if self.redis:
            await self.redis.set(f"price:{exchange}:{symbol}", price, ex=10) # 10s cache

    async def get_cached_price(self, exchange: str, symbol: str):
        if self.redis:
            val = await self.redis.get(f"price:{exchange}:{symbol}")
            return float(val) if val else None
        return None

execution_engine = ExecutionEngine()
