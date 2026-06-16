import ccxt.async_support as ccxt
import asyncio
from core.database import db
from core.security import security_manager
import structlog

log = structlog.get_logger("exchange_service")

EXCHANGE_CLASSES = {
    "binance": ccxt.binance,
    "bybit": ccxt.bybit,
    "okx": ccxt.okx,
    "kucoin": ccxt.kucoin,
    "gateio": ccxt.gateio,
    "kraken": ccxt.kraken,
    "bitget": ccxt.bitget,
    "coinbase": ccxt.coinbase,
    "hyperliquid": ccxt.hyperliquid,
    "mexc": ccxt.mexc,
}

class ExchangeService:
    def __init__(self):
        self.clients = {}

    async def get_client(self, user_id: str, exchange_id: str) -> ccxt.Exchange:
        cache_key = f"{user_id}:{exchange_id}"
        if cache_key in self.clients:
            return self.clients[cache_key]

        res = db.table("exchange_connections").select("*").eq("user_id", user_id).eq("exchange", exchange_id.lower()).single().execute()
        conn = res.data
        if not conn:
            raise ValueError(f"No connection found for {exchange_id}")

        exchange_cls = EXCHANGE_CLASSES.get(exchange_id.lower()) or getattr(ccxt, exchange_id.lower())

        api_key = security_manager.decrypt(conn["api_key"])
        api_secret = security_manager.decrypt(conn["secret_key"])
        passphrase = security_manager.decrypt(conn["passphrase"]) if conn.get("passphrase") else None

        client = exchange_cls({
            "apiKey": api_key,
            "secret": api_secret,
            "password": passphrase,
            "enableRateLimit": True,
        })

        self.clients[cache_key] = client
        return client

    async def test_connection(self, exchange_id: str, api_key: str, secret: str, passphrase: str = None) -> bool:
        try:
            exchange_cls = EXCHANGE_CLASSES.get(exchange_id.lower()) or getattr(ccxt, exchange_id.lower())
            client = exchange_cls({
                "apiKey": api_key,
                "secret": secret,
                "password": passphrase,
            })
            await client.fetch_balance()
            await client.close()
            return True
        except Exception as e:
            log.error("test_connection_failed", exchange=exchange_id, error=str(e))
            return False

exchange_service = ExchangeService()
