"""
services/broker_service.py — ESTRADE v6 Multi-Broker Integration
══════════════════════════════════════════════════════════════════════════
Supported Brokers (via CCXT + custom adapters):
  ① Binance     — Spot + Futures (crypto)
  ② Bybit       — Perpetual futures (crypto)
  ③ OKX         — Spot + Futures (crypto)
  ④ OANDA       — Forex CFDs (REST API)
  ⑤ MetaTrader5 — Forex via MT5 bridge (optional)
  ⑥ Interactive Brokers — Premium (optional)
  ⑦ IC Markets  — Forex/CFD (FIX API optional)

All brokers share the same interface:
  - get_ticker(symbol)
  - get_ohlcv(symbol, timeframe, limit)
  - place_order(symbol, side, qty, price, sl, tp)
  - cancel_order(order_id)
  - get_positions()
  - get_balance()
══════════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations
import asyncio
from datetime import datetime, timezone
from typing import Optional
import httpx
import structlog

from core.config import settings
from core.database import db

log = structlog.get_logger("broker")


# ── Base Broker Interface ─────────────────────────────────────

class BrokerBase:
    name        = "base"
    supports_fx = False
    supports_crypto = False

    async def get_ticker(self, symbol: str) -> dict:
        raise NotImplementedError

    async def get_ohlcv(self, symbol: str, tf: str, limit: int = 100) -> list:
        raise NotImplementedError

    async def place_order(self, symbol:str, side:str, qty:float,
                           order_type:str="market", price:float=None,
                           sl:float=None, tp:float=None) -> dict:
        raise NotImplementedError

    async def get_balance(self, currency: str = "USDT") -> float:
        raise NotImplementedError

    async def get_positions(self) -> list:
        raise NotImplementedError

    async def cancel_order(self, order_id: str, symbol: str) -> bool:
        raise NotImplementedError

    def normalize_symbol(self, symbol: str) -> str:
        return symbol


# ── CCXT Broker (Binance, Bybit, OKX) ────────────────────────

class CCXTBroker(BrokerBase):
    """Generic CCXT wrapper — works for Binance, Bybit, OKX."""
    supports_crypto = True

    def __init__(self, exchange_id: str, api_key: str = "", secret: str = "",
                  password: str = "", sandbox: bool = False):
        self.exchange_id = exchange_id
        self.api_key     = api_key
        self.secret      = secret
        self.password    = password
        self.sandbox     = sandbox
        self._exchange   = None

    def _get_exchange(self):
        if self._exchange: return self._exchange
        try:
            import ccxt
            ExClass = getattr(ccxt, self.exchange_id)
            self._exchange = ExClass({
                "apiKey":   self.api_key,
                "secret":   self.secret,
                "password": self.password,
                "enableRateLimit": True,
                "sandbox":  self.sandbox,
            })
        except Exception as e:
            log.error("ccxt_init_failed", exchange=self.exchange_id, error=str(e))
        return self._exchange

    async def get_ticker(self, symbol: str) -> dict:
        loop = asyncio.get_event_loop()
        try:
            ex = self._get_exchange()
            if not ex: return {"last":0,"bid":0,"ask":0}
            t = await loop.run_in_executor(None, ex.fetch_ticker, symbol)
            return {"last":t["last"],"bid":t["bid"],"ask":t["ask"],
                    "volume":t["quoteVolume"],"change":t.get("percentage",0)}
        except Exception as e:
            log.warning("ticker_error",symbol=symbol,error=str(e))
            return {"last":0,"bid":0,"ask":0}

    async def get_ohlcv(self, symbol: str, tf: str, limit: int = 100) -> list:
        loop = asyncio.get_event_loop()
        try:
            ex = self._get_exchange()
            if not ex: return []
            data = await loop.run_in_executor(None, lambda: ex.fetch_ohlcv(symbol, tf, limit=limit))
            return data or []
        except Exception as e:
            log.warning("ohlcv_error",symbol=symbol,tf=tf,error=str(e))
            return []

    async def place_order(self, symbol:str, side:str, qty:float,
                           order_type:str="market", price:float=None,
                           sl:float=None, tp:float=None) -> dict:
        loop = asyncio.get_event_loop()
        try:
            ex = self._get_exchange()
            if not ex: return {"error":"Exchange not initialized"}
            params = {}
            if sl:   params["stopLoss"]   = {"type":"market","stopPrice":sl}
            if tp:   params["takeProfit"] = {"type":"limit","price":tp}
            order = await loop.run_in_executor(None, lambda: ex.create_order(
                symbol, order_type, side.lower(), qty, price, params
            ))
            return {
                "order_id":   order["id"],
                "symbol":     symbol,
                "side":       side,
                "qty":        qty,
                "price":      order.get("price",price),
                "status":     order.get("status","submitted"),
                "broker":     self.exchange_id,
            }
        except Exception as e:
            log.error("place_order_error",symbol=symbol,side=side,error=str(e))
            return {"error":str(e)}

    async def get_balance(self, currency: str = "USDT") -> float:
        loop = asyncio.get_event_loop()
        try:
            ex = self._get_exchange()
            if not ex: return 0.0
            bal = await loop.run_in_executor(None, ex.fetch_balance)
            return float(bal.get(currency,{}).get("free",0))
        except Exception:
            return 0.0

    async def get_positions(self) -> list:
        loop = asyncio.get_event_loop()
        try:
            ex = self._get_exchange()
            if not ex: return []
            pos = await loop.run_in_executor(None, ex.fetch_positions)
            return [p for p in pos if float(p.get("contracts",0)) > 0]
        except Exception:
            return []

    async def cancel_order(self, order_id: str, symbol: str) -> bool:
        loop = asyncio.get_event_loop()
        try:
            ex = self._get_exchange()
            if not ex: return False
            await loop.run_in_executor(None, lambda: ex.cancel_order(order_id, symbol))
            return True
        except Exception:
            return False


# ── OANDA Broker (Forex) ──────────────────────────────────────

class OANDABroker(BrokerBase):
    """OANDA REST API v20 — Forex CFD trading."""
    name        = "oanda"
    supports_fx = True

    BASE_LIVE    = "https://api-fxtrade.oanda.com/v3"
    BASE_PRACTICE= "https://api-fxpractice.oanda.com/v3"

    def __init__(self, api_key: str = "", account_id: str = "", practice: bool = True):
        self.api_key    = api_key or getattr(settings,"OANDA_API_KEY","")
        self.account_id = account_id or getattr(settings,"OANDA_ACCOUNT_ID","")
        self.base       = self.BASE_PRACTICE if practice else self.BASE_LIVE

    def _h(self) -> dict:
        return {"Authorization":f"Bearer {self.api_key}","Content-Type":"application/json"}

    def normalize_symbol(self, symbol: str) -> str:
        return symbol.replace("/","_").replace("EURUSD","EUR_USD").replace("GBPUSD","GBP_USD").replace("USDJPY","USD_JPY")

    async def get_ticker(self, symbol: str) -> dict:
        sym = self.normalize_symbol(symbol)
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.get(f"{self.base}/accounts/{self.account_id}/pricing",
                    params={"instruments":sym}, headers=self._h())
            data = r.json()
            prices = data.get("prices",[{}])[0]
            bid = float(prices.get("bids",[{"price":0}])[0]["price"])
            ask = float(prices.get("asks",[{"price":0}])[0]["price"])
            return {"last":(bid+ask)/2,"bid":bid,"ask":ask,"spread":round(ask-bid,6)}
        except Exception as e:
            return {"last":0,"bid":0,"ask":0,"error":str(e)}

    async def get_ohlcv(self, symbol:str, tf:str, limit:int=100) -> list:
        sym = self.normalize_symbol(symbol)
        tf_map = {"M1":"M1","M5":"M5","M15":"M15","H1":"H1","H4":"H4","D1":"D"}
        gran = tf_map.get(tf,"H1")
        try:
            async with httpx.AsyncClient(timeout=15) as c:
                r = await c.get(f"{self.base}/instruments/{sym}/candles",
                    params={"count":limit,"granularity":gran,"price":"MBA"},
                    headers=self._h())
            candles = r.json().get("candles",[])
            return [[
                c["time"],
                float(c["mid"]["o"]),float(c["mid"]["h"]),
                float(c["mid"]["l"]),float(c["mid"]["c"]),
                int(c.get("volume",0))
            ] for c in candles if c.get("complete")]
        except Exception as e:
            log.warning("oanda_ohlcv_error",symbol=symbol,error=str(e))
            return []

    async def place_order(self, symbol:str, side:str, qty:float,
                           order_type:str="market", price:float=None,
                           sl:float=None, tp:float=None) -> dict:
        sym   = self.normalize_symbol(symbol)
        units = int(qty * 1000) * (1 if side.lower()=="buy" else -1)
        order = {"type":"MARKET","instrument":sym,"units":str(units)}
        if sl:
            order["stopLossOnFill"] = {"price":str(round(sl,5)),"timeInForce":"GTC"}
        if tp:
            order["takeProfitOnFill"] = {"price":str(round(tp,5)),"timeInForce":"GTC"}
        try:
            async with httpx.AsyncClient(timeout=15) as c:
                r = await c.post(f"{self.base}/accounts/{self.account_id}/orders",
                    json={"order":order}, headers=self._h())
            d = r.json()
            fill = d.get("orderFillTransaction",{})
            return {
                "order_id": fill.get("id",""),
                "symbol":   symbol,
                "side":     side,
                "qty":      qty,
                "price":    float(fill.get("price",0)),
                "status":   "filled" if fill else "submitted",
                "broker":   "oanda",
            }
        except Exception as e:
            return {"error":str(e)}

    async def get_balance(self, currency: str = "USD") -> float:
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.get(f"{self.base}/accounts/{self.account_id}/summary",
                    headers=self._h())
            data = r.json()
            return float(data.get("account",{}).get("balance",0))
        except Exception:
            return 0.0

    async def get_positions(self) -> list:
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.get(f"{self.base}/accounts/{self.account_id}/openPositions",
                    headers=self._h())
            return r.json().get("positions",[])
        except Exception:
            return []

    async def cancel_order(self, order_id: str, symbol: str = "") -> bool:
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.put(
                    f"{self.base}/accounts/{self.account_id}/orders/{order_id}/cancel",
                    headers=self._h())
            return r.status_code in (200,201)
        except Exception:
            return False


# ── Broker Manager ────────────────────────────────────────────

class BrokerManager:
    """
    Central broker registry. Maps exchange IDs to broker instances.
    User can connect their own broker API keys.
    """

    def __init__(self):
        # Default platform brokers (using platform keys)
        self._brokers: dict[str, BrokerBase] = {}
        self._init_defaults()

    def _init_defaults(self):
        """Initialize default brokers from platform API keys."""
        bk  = getattr(settings,"BINANCE_API_KEY","")
        bs  = getattr(settings,"BINANCE_SECRET","")
        if bk and bs:
            self._brokers["binance"] = CCXTBroker("binance",bk,bs)

        bybk = getattr(settings,"BYBIT_API_KEY","")
        bybs = getattr(settings,"BYBIT_SECRET","")
        if bybk and bybs:
            self._brokers["bybit"] = CCXTBroker("bybit",bybk,bybs)

        ok  = getattr(settings,"OKX_API_KEY","")
        os_ = getattr(settings,"OKX_SECRET","")
        if ok and os_:
            self._brokers["okx"] = CCXTBroker("okx",ok,os_,
                getattr(settings,"OKX_PASSPHRASE",""))

        oak = getattr(settings,"OANDA_API_KEY","")
        oai = getattr(settings,"OANDA_ACCOUNT_ID","")
        if oak and oai:
            self._brokers["oanda"] = OANDABroker(oak,oai)
        else:
            # Always create OANDA instance (practice mode for testing)
            self._brokers["oanda"] = OANDABroker(practice=True)

    async def get_broker_for_user(self, user_id: str,
                                    broker_id: str = "binance") -> BrokerBase:
        """Get user-configured broker (falls back to platform broker)."""
        try:
            conn = (db.table("exchange_connections").select("*")
                    .eq("user_id",user_id).eq("exchange_id",broker_id)
                    .eq("is_active",True).single().execute()).data
            if conn:
                from core.security import decrypt
                key    = decrypt(conn["api_key"])
                secret = decrypt(conn["api_secret"])
                pw     = decrypt(conn.get("api_passphrase","") or "")
                if broker_id == "oanda":
                    return OANDABroker(key, conn.get("account_id",""))
                return CCXTBroker(broker_id, key, secret, pw)
        except Exception:
            pass
        return self._brokers.get(broker_id, self._brokers.get("binance", CCXTBroker("binance")))

    def get_broker_for_symbol(self, symbol: str) -> str:
        """Auto-select best broker for a symbol."""
        s = symbol.upper()
        if "USD" in s and "/" in s and "USDT" not in s:
            return "oanda"   # Forex
        if "XAU" in s or "XAG" in s:
            return "oanda"   # Gold/Silver
        return "binance"     # Default crypto

    async def route_order(self, user_id:str, bot_config:dict,
                           symbol:str, side:str, qty:float,
                           sl:float=None, tp:float=None) -> dict:
        """
        Route a trade to the correct broker based on symbol and bot config.
        Applies slippage protection before executing.
        """
        broker_id = self.get_broker_for_symbol(symbol)
        if bot_config.get("broker_required"):
            # Check user has a connected broker
            broker_id = await self._get_user_broker_pref(user_id, symbol)

        broker = await self.get_broker_for_user(user_id, broker_id)

        # Slippage check: get current price first
        try:
            tick      = await broker.get_ticker(symbol)
            curr_price= float(tick.get("last",0))
            spread    = float(tick.get("spread",curr_price*0.001))
            # If spread > 0.5% — skip (too wide for reliable entry)
            if curr_price > 0 and spread/curr_price > 0.005:
                return {"error":f"Spread too wide: {spread/curr_price*100:.3f}%"}
        except Exception:
            pass

        result = await broker.place_order(symbol,side,qty,sl=sl,tp=tp)
        result["broker_id"] = broker_id
        return result

    async def _get_user_broker_pref(self, user_id:str, symbol:str) -> str:
        """Get user's preferred broker for a symbol type."""
        try:
            conn = (db.table("exchange_connections").select("exchange_id")
                    .eq("user_id",user_id).eq("is_active",True)
                    .order("created_at",desc=True).limit(1).execute()).data
            if conn: return conn[0]["exchange_id"]
        except Exception: pass
        return self.get_broker_for_symbol(symbol)


# ── Singleton ────────────────────────────────────────────────
broker_manager = BrokerManager()
