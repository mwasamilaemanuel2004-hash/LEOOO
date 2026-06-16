"""
exchanges/exchange_service.py — Multi-Exchange Integration
Supports: Binance, Bybit, Pionex via ccxt
All API keys decrypted on-demand, never cached in memory long.
"""
from __future__ import annotations
import ccxt.async_support as ccxt
import asyncio
from core.database import db
from core.security import decrypt_field
from core.config import settings
import structlog

log = structlog.get_logger("exchange_service")

EXCHANGE_CLASSES = {
    "binance": ccxt.binance,
    "bybit":   ccxt.bybit,
    "pionex":  ccxt.pionex,
    "kucoin":  ccxt.kucoin,
    "okx":     ccxt.okx,
}


class ExchangeService:

    async def _get_client(self, exchange_conn_id: str) -> ccxt.Exchange:
        conn = db.table("exchange_connections").select("*").eq("id", exchange_conn_id).single().execute().data
        if not conn:
            raise ValueError("Exchange connection not found")

        exchange_cls = EXCHANGE_CLASSES.get(conn["exchange"])
        if not exchange_cls:
            raise ValueError(f"Unsupported exchange: {conn['exchange']}")

        api_key    = decrypt_field(conn["api_key_enc"])
        api_secret = decrypt_field(conn["api_secret_enc"])
        passphrase = decrypt_field(conn["passphrase_enc"]) if conn.get("passphrase_enc") else None

        config = {
            "apiKey": api_key,
            "secret": api_secret,
            "enableRateLimit": True,
            "sandbox": conn.get("is_testnet", False),
        }
        if passphrase:
            config["password"] = passphrase

        client = exchange_cls(config)
        if conn.get("is_testnet") and hasattr(client, "set_sandbox_mode"):
            client.set_sandbox_mode(True)
        return client

    async def get_balance(self, exchange_conn_id: str) -> dict:
        client = await self._get_client(exchange_conn_id)
        try:
            bal = await client.fetch_balance()
            total = bal.get("total", {})
            result = {k: v for k, v in total.items() if v and v > 0}

            # Cache in exchange_connections
            db.table("exchange_connections").update({
                "balance_cache": result,
                "last_sync": "now()",
                "status": "active",
            }).eq("id", exchange_conn_id).execute()

            return result
        finally:
            await client.close()

    async def fetch_ohlcv(self, exchange_conn_id: str,
                           symbol: str, timeframe: str = "1h",
                           limit: int = 200) -> list:
        client = await self._get_client(exchange_conn_id)
        try:
            ohlcv = await client.fetch_ohlcv(symbol, timeframe, limit=limit)
            return ohlcv
        finally:
            await client.close()

    async def get_ticker(self, exchange_conn_id: str, symbol: str) -> dict:
        client = await self._get_client(exchange_conn_id)
        try:
            ticker = await client.fetch_ticker(symbol)
            return {
                "symbol": symbol,
                "last": ticker.get("last"),
                "bid": ticker.get("bid"),
                "ask": ticker.get("ask"),
                "volume": ticker.get("baseVolume"),
                "change_pct": ticker.get("percentage"),
            }
        finally:
            await client.close()

    async def place_market_order(self, exchange_conn_id: str,
                                  symbol: str, side: str,
                                  amount: float) -> dict:
        client = await self._get_client(exchange_conn_id)
        try:
            order = await client.create_market_order(symbol, side, amount)
            log.info("exchange_order_placed", symbol=symbol, side=side, amount=amount,
                     order_id=order.get("id"))
            return {
                "exchange_order_id": str(order.get("id")),
                "status": order.get("status", "open"),
                "avg_price": order.get("average") or order.get("price"),
                "filled": order.get("filled", amount),
                "fee": (order.get("fee") or {}).get("cost", 0),
                "raw": order,
            }
        except ccxt.InsufficientFunds:
            raise ValueError("Insufficient funds on exchange")
        except ccxt.InvalidOrder as e:
            raise ValueError(f"Invalid order: {e}")
        except Exception as e:
            log.error("exchange_order_error", error=str(e))
            raise ValueError(f"Exchange error: {e}")
        finally:
            await client.close()

    async def place_limit_order(self, exchange_conn_id: str,
                                 symbol: str, side: str,
                                 amount: float, price: float) -> dict:
        client = await self._get_client(exchange_conn_id)
        try:
            order = await client.create_limit_order(symbol, side, amount, price)
            return {
                "exchange_order_id": str(order.get("id")),
                "status": order.get("status"),
                "price": price,
                "amount": amount,
                "raw": order,
            }
        finally:
            await client.close()

    async def cancel_order(self, exchange_conn_id: str,
                            order_id: str, symbol: str) -> dict:
        client = await self._get_client(exchange_conn_id)
        try:
            result = await client.cancel_order(order_id, symbol)
            return {"cancelled": True, "raw": result}
        finally:
            await client.close()

    async def get_order_status(self, exchange_conn_id: str,
                                order_id: str, symbol: str) -> dict:
        client = await self._get_client(exchange_conn_id)
        try:
            order = await client.fetch_order(order_id, symbol)
            return {
                "status": order.get("status"),
                "filled": order.get("filled", 0),
                "remaining": order.get("remaining"),
                "avg_price": order.get("average"),
                "fee": (order.get("fee") or {}).get("cost", 0),
            }
        finally:
            await client.close()

    async def get_open_positions(self, exchange_conn_id: str) -> list:
        client = await self._get_client(exchange_conn_id)
        try:
            if hasattr(client, "fetch_positions"):
                positions = await client.fetch_positions()
                return [p for p in positions if float(p.get("contracts", 0) or 0) > 0]
            return []
        finally:
            await client.close()

    async def validate_connection(self, exchange_conn_id: str) -> dict:
        """Test connection and return account info."""
        try:
            balance = await self.get_balance(exchange_conn_id)
            db.table("exchange_connections").update({
                "status": "active"
            }).eq("id", exchange_conn_id).execute()
            return {"valid": True, "balance_snapshot": balance}
        except Exception as e:
            db.table("exchange_connections").update({
                "status": "error"
            }).eq("id", exchange_conn_id).execute()
            return {"valid": False, "error": str(e)}

    async def add_connection(self, user_id: str, exchange: str,
                              api_key: str, api_secret: str,
                              passphrase: str = None,
                              label: str = None,
                              is_testnet: bool = False,
                              market_type: str = "spot") -> dict:
        from core.security import encrypt_field
        encrypted_key = encrypt_field(api_key)
        encrypted_secret = encrypt_field(api_secret)
        encrypted_pass = encrypt_field(passphrase) if passphrase else None

        conn = db.table("exchange_connections").insert({
            "user_id": user_id,
            "exchange": exchange,
            "api_key_enc": encrypted_key,
            "api_secret_enc": encrypted_secret,
            "passphrase_enc": encrypted_pass,
            "label": label or exchange.upper(),
            "is_testnet": is_testnet,
            "market_type": market_type,
            "status": "active",
        }).execute()

        if not conn.data:
            raise ValueError("Failed to save exchange connection")

        conn_id = conn.data[0]["id"]

        # Validate immediately
        validation = await self.validate_connection(conn_id)
        if not validation["valid"]:
            db.table("exchange_connections").delete().eq("id", conn_id).execute()
            raise ValueError(f"Connection test failed: {validation['error']}")

        return {"connection_id": conn_id, "validation": validation}


exchange_service = ExchangeService()
