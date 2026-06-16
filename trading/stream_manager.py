import asyncio
import json
import websockets
from services.exchange_service import exchange_service
from trading.execution_engine import execution_engine
import structlog

log = structlog.get_logger("stream_manager")

class StreamManager:
    """
    Manages WebSocket market streams for ultra-low latency price updates.
    """

    def __init__(self):
        self.active_streams = {}

    async def subscribe_binance(self, symbol: str):
        url = f"wss://stream.binance.com:9443/ws/{symbol.lower()}@ticker"
        async with websockets.connect(url) as ws:
            log.info("binance_ws_connected", symbol=symbol)
            while True:
                msg = await ws.recv()
                data = json.loads(msg)
                price = float(data['c'])
                await execution_engine.cache_price("binance", symbol, price)

    async def start_streams(self, pairs: list[tuple[str, str]]):
        tasks = []
        for exchange, symbol in pairs:
            if exchange == "binance":
                tasks.append(self.subscribe_binance(symbol))

        await asyncio.gather(*tasks)

stream_manager = StreamManager()
