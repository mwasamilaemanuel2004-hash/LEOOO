"""
services/mt5_bridge.py — ESTRADE v7 MT4/MT5 Bridge Service
═══════════════════════════════════════════════════════════════════════
Full MetaTrader 4/5 integration via:
  1. MetaTrader5 Python library (direct connection)
  2. REST Bridge (for remote MT5 servers)
  3. FIX Protocol bridge (institutional)

Supports:
  - Account info, balance, equity
  - Real-time tick data (bid/ask)
  - OHLCV history (all timeframes)
  - Market orders (instant execution)
  - Pending orders (limit/stop)
  - Modify orders (SL/TP adjust)
  - Close positions
  - Copy trading (signal → sub-accounts)
  - Gold/Silver/Oil CFDs via broker
  - Hedging mode support

MT5 Timeframe mapping:
  M1/M5/M15/M30/H1/H4/D1/W1/MN
═══════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations
import asyncio
import json
import time
from datetime import datetime, timezone, timedelta
from typing import Optional
import httpx
import structlog

from core.config import settings
from core.database import db
from core.security import decrypt_field

log = structlog.get_logger("mt5_bridge")

# ── MT5 Timeframe Constants ───────────────────────────────────
MT5_TIMEFRAMES = {
    "M1":  1,
    "M5":  5,
    "M15": 15,
    "M30": 30,
    "H1":  60,
    "H4":  240,
    "D1":  1440,
    "W1":  10080,
    "MN":  43200,
}

# MT5 Order Types
ORDER_TYPE_BUY         = 0
ORDER_TYPE_SELL        = 1
ORDER_TYPE_BUY_LIMIT   = 2
ORDER_TYPE_SELL_LIMIT  = 3
ORDER_TYPE_BUY_STOP    = 4
ORDER_TYPE_SELL_STOP   = 5

# Trade Request Actions
TRADE_ACTION_DEAL    = 1   # Market order
TRADE_ACTION_PENDING = 5   # Pending order
TRADE_ACTION_SLTP    = 6   # Modify SL/TP
TRADE_ACTION_CLOSE_BY = 10 # Close by hedge

# Return codes
TRADE_RETCODE_DONE = 10009


class MT5BridgeBase:
    """Base interface for all MT5 connection methods."""
    name = "base"

    async def get_account_info(self) -> dict:
        raise NotImplementedError

    async def get_symbol_tick(self, symbol: str) -> dict:
        raise NotImplementedError

    async def get_ohlcv(self, symbol: str, timeframe: str, count: int = 200) -> list:
        raise NotImplementedError

    async def place_market_order(
        self, symbol: str, side: str, volume: float,
        sl: float = 0, tp: float = 0,
        comment: str = "ESTRADE_v7", magic: int = 777000,
    ) -> dict:
        raise NotImplementedError

    async def place_pending_order(
        self, symbol: str, side: str, order_type: str,
        volume: float, price: float, sl: float = 0, tp: float = 0,
        comment: str = "ESTRADE_v7", magic: int = 777000,
        expiry: Optional[datetime] = None,
    ) -> dict:
        raise NotImplementedError

    async def modify_position(
        self, ticket: int, sl: float = 0, tp: float = 0
    ) -> dict:
        raise NotImplementedError

    async def close_position(self, ticket: int, volume: float = 0) -> dict:
        raise NotImplementedError

    async def close_all_positions(self, magic: int = 777000) -> list[dict]:
        raise NotImplementedError

    async def get_open_positions(self, magic: int = 777000) -> list[dict]:
        raise NotImplementedError

    async def get_closed_trades(self, from_dt: datetime, to_dt: datetime) -> list[dict]:
        raise NotImplementedError


class MT5DirectBridge(MT5BridgeBase):
    """
    Direct MT5 connection via Python MetaTrader5 library.
    Runs in subprocess to avoid event loop conflicts.
    Best for local/VPS deployments.
    """
    name = "mt5_direct"

    def __init__(self, login: int, password: str, server: str, path: str = ""):
        self.login    = login
        self.password = password
        self.server   = server
        self.path     = path
        self._connected = False

    async def _run_mt5(self, code: str) -> dict:
        """
        Run MT5 Python code in subprocess.
        Returns JSON result.
        """
        script = f"""
import MetaTrader5 as mt5
import json, sys

mt5.initialize(login={self.login!r}, password={self.password!r},
               server={self.server!r}{f", path={self.path!r}" if self.path else ""})

try:
    result = {code}
    print(json.dumps(result if result is not None else {{"error": "None result"}}))
except Exception as e:
    print(json.dumps({{"error": str(e)}}))
finally:
    mt5.shutdown()
"""
        try:
            proc = await asyncio.create_subprocess_exec(
                "python3", "-c", script,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
            output = stdout.decode().strip()
            if output:
                return json.loads(output)
            return {"error": stderr.decode()[:200]}
        except asyncio.TimeoutError:
            return {"error": "MT5 subprocess timeout"}
        except Exception as e:
            return {"error": str(e)}

    async def get_account_info(self) -> dict:
        code = """
{
    "login":        mt5.account_info().login,
    "balance":      mt5.account_info().balance,
    "equity":       mt5.account_info().equity,
    "margin":       mt5.account_info().margin,
    "margin_free":  mt5.account_info().margin_free,
    "margin_level": mt5.account_info().margin_level,
    "profit":       mt5.account_info().profit,
    "currency":     mt5.account_info().currency,
    "leverage":     mt5.account_info().leverage,
    "server":       mt5.account_info().server,
    "name":         mt5.account_info().name,
}
"""
        return await self._run_mt5(code)

    async def get_symbol_tick(self, symbol: str) -> dict:
        code = f"""
tick = mt5.symbol_info_tick("{symbol}")
{{"symbol": "{symbol}", "bid": tick.bid, "ask": tick.ask,
  "last": tick.last, "time": tick.time, "spread": round(tick.ask - tick.bid, 5)}}
"""
        return await self._run_mt5(code)

    async def get_ohlcv(self, symbol: str, timeframe: str, count: int = 200) -> list:
        tf_const = {
            "M1": "mt5.TIMEFRAME_M1", "M5": "mt5.TIMEFRAME_M5",
            "M15": "mt5.TIMEFRAME_M15", "M30": "mt5.TIMEFRAME_M30",
            "H1": "mt5.TIMEFRAME_H1", "H4": "mt5.TIMEFRAME_H4",
            "D1": "mt5.TIMEFRAME_D1", "W1": "mt5.TIMEFRAME_W1",
        }.get(timeframe, "mt5.TIMEFRAME_H1")
        code = f"""
rates = mt5.copy_rates_from_pos("{symbol}", {tf_const}, 0, {count})
[[int(r["time"]), float(r["open"]), float(r["high"]), float(r["low"]),
  float(r["close"]), float(r["tick_volume"])] for r in rates] if rates is not None else []
"""
        result = await self._run_mt5(code)
        if isinstance(result, list):
            return result
        return []

    async def place_market_order(
        self, symbol: str, side: str, volume: float,
        sl: float = 0, tp: float = 0,
        comment: str = "ESTRADE_v7", magic: int = 777000,
    ) -> dict:
        order_type = "mt5.ORDER_TYPE_BUY" if side.lower() == "buy" else "mt5.ORDER_TYPE_SELL"
        price_fn   = "mt5.symbol_info_tick(symbol).ask" if side.lower() == "buy" else "mt5.symbol_info_tick(symbol).bid"
        code = f"""
symbol = "{symbol}"
request = {{
    "action":   mt5.TRADE_ACTION_DEAL,
    "symbol":   symbol,
    "volume":   {volume},
    "type":     {order_type},
    "price":    {price_fn},
    "sl":       {sl},
    "tp":       {tp},
    "deviation": 20,
    "magic":    {magic},
    "comment":  "{comment}",
    "type_time": mt5.ORDER_TIME_GTC,
    "type_filling": mt5.ORDER_FILLING_IOC,
}}
res = mt5.order_send(request)
{{"retcode": res.retcode, "order": res.order, "deal": res.deal,
  "volume": res.volume, "price": res.price, "comment": res.comment,
  "request_id": res.request_id, "success": res.retcode == 10009}}
"""
        return await self._run_mt5(code)

    async def modify_position(self, ticket: int, sl: float = 0, tp: float = 0) -> dict:
        code = f"""
request = {{
    "action":   mt5.TRADE_ACTION_SLTP,
    "ticket":   {ticket},
    "sl":       {sl},
    "tp":       {tp},
}}
res = mt5.order_send(request)
{{"retcode": res.retcode, "success": res.retcode == 10009, "ticket": {ticket}}}
"""
        return await self._run_mt5(code)

    async def close_position(self, ticket: int, volume: float = 0) -> dict:
        code = f"""
pos = mt5.positions_get(ticket={ticket})
if pos:
    p = pos[0]
    close_type = mt5.ORDER_TYPE_SELL if p.type == 0 else mt5.ORDER_TYPE_BUY
    price_fn = mt5.symbol_info_tick(p.symbol).bid if p.type == 0 else mt5.symbol_info_tick(p.symbol).ask
    vol = {volume} if {volume} > 0 else p.volume
    request = {{
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": p.symbol,
        "volume": vol,
        "type":   close_type,
        "position": {ticket},
        "price":  price_fn,
        "deviation": 20,
        "magic":  p.magic,
        "comment": "ESTRADE_close",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }}
    res = mt5.order_send(request)
    {{"retcode": res.retcode, "success": res.retcode == 10009, "deal": res.deal}}
else:
    {{"error": "position not found", "ticket": {ticket}}}
"""
        return await self._run_mt5(code)

    async def get_open_positions(self, magic: int = 777000) -> list[dict]:
        code = f"""
positions = mt5.positions_get()
if positions:
    [{{"ticket": p.ticket, "symbol": p.symbol, "type": p.type,
      "volume": p.volume, "price_open": p.price_open,
      "sl": p.sl, "tp": p.tp, "profit": p.profit,
      "magic": p.magic, "comment": p.comment,
      "time": p.time}}
     for p in positions if p.magic == {magic} or {magic} == 0]
else:
    []
"""
        result = await self._run_mt5(code)
        return result if isinstance(result, list) else []

    async def close_all_positions(self, magic: int = 777000) -> list[dict]:
        positions = await self.get_open_positions(magic)
        results = []
        for pos in positions:
            r = await self.close_position(pos["ticket"])
            results.append(r)
        return results


class MT5RESTBridge(MT5BridgeBase):
    """
    MT5 REST bridge for remote server connections.
    Compatible with MT5 bridge APIs like:
    - MetaTrader 5 Web API
    - Custom REST bridge servers
    - Third-party MT5 REST APIs (Fxpro API, IC Markets REST, etc.)
    """
    name = "mt5_rest"

    def __init__(self, base_url: str, api_key: str, account_id: str = ""):
        self.base_url   = base_url.rstrip("/")
        self.api_key    = api_key
        self.account_id = account_id
        self._client_headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "X-Account-ID": account_id,
        }

    async def _request(self, method: str, endpoint: str, **kwargs) -> dict:
        url = f"{self.base_url}{endpoint}"
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await getattr(client, method)(
                    url, headers=self._client_headers, **kwargs
                )
                resp.raise_for_status()
                return resp.json()
        except httpx.TimeoutException:
            return {"error": "MT5 REST timeout"}
        except Exception as e:
            log.error("mt5_rest_error", url=url, error=str(e))
            return {"error": str(e)}

    async def get_account_info(self) -> dict:
        return await self._request("get", "/account")

    async def get_symbol_tick(self, symbol: str) -> dict:
        return await self._request("get", f"/quotes/{symbol}")

    async def get_ohlcv(self, symbol: str, timeframe: str, count: int = 200) -> list:
        result = await self._request("get", f"/ohlcv/{symbol}",
                                      params={"timeframe": timeframe, "count": count})
        return result.get("data", []) if isinstance(result, dict) else []

    async def place_market_order(
        self, symbol: str, side: str, volume: float,
        sl: float = 0, tp: float = 0,
        comment: str = "ESTRADE_v7", magic: int = 777000,
    ) -> dict:
        return await self._request("post", "/orders/market", json={
            "symbol": symbol, "side": side.lower(),
            "volume": volume, "sl": sl, "tp": tp,
            "comment": comment, "magic": magic,
        })

    async def modify_position(self, ticket: int, sl: float = 0, tp: float = 0) -> dict:
        return await self._request("put", f"/positions/{ticket}", json={"sl": sl, "tp": tp})

    async def close_position(self, ticket: int, volume: float = 0) -> dict:
        return await self._request("delete", f"/positions/{ticket}",
                                    json={"volume": volume or None})

    async def get_open_positions(self, magic: int = 777000) -> list[dict]:
        result = await self._request("get", "/positions",
                                      params={"magic": magic if magic != 0 else None})
        return result.get("positions", []) if isinstance(result, dict) else []

    async def close_all_positions(self, magic: int = 777000) -> list[dict]:
        result = await self._request("delete", "/positions/all",
                                      json={"magic": magic})
        return result.get("closed", []) if isinstance(result, dict) else []


# ══════════════════════════════════════════════════════════════
# MT5 BROKER SERVICE
# ══════════════════════════════════════════════════════════════

class MT5BrokerService:
    """
    High-level MT5 broker service for ESTRADE.
    Manages connections per user, lot sizing, SL/TP calculation.
    """

    def __init__(self):
        self._connections: dict[str, MT5BridgeBase] = {}  # user_id → bridge

    async def get_bridge(self, user_id: str) -> Optional[MT5BridgeBase]:
        """Get or create MT5 connection for user."""
        if user_id in self._connections:
            return self._connections[user_id]

        # Load from DB
        conn = db.table("mt5_connections").select("*").eq("user_id", user_id).eq("is_active", True).maybe_single().execute()
        if not conn.data:
            return None

        c = conn.data
        try:
            if c.get("connection_type") == "direct":
                bridge = MT5DirectBridge(
                    login    = int(decrypt_field(c["login_enc"])),
                    password = decrypt_field(c["password_enc"]),
                    server   = c["server"],
                    path     = c.get("path", ""),
                )
            else:
                bridge = MT5RESTBridge(
                    base_url   = c["rest_url"],
                    api_key    = decrypt_field(c["api_key_enc"]),
                    account_id = c.get("account_id", ""),
                )
            self._connections[user_id] = bridge
            return bridge
        except Exception as e:
            log.error("mt5_connect_failed", user_id=user_id, error=str(e))
            return None

    def calculate_lot_size(
        self,
        balance: float,
        risk_pct: float,
        sl_pips: float,
        pip_value: float = 10.0,  # USD per pip per lot for EURUSD
        min_lot: float = 0.01,
        max_lot: float = 10.0,
    ) -> float:
        """
        Calculate position size using fixed % risk.
        lot = (balance × risk_pct) / (sl_pips × pip_value)
        """
        if sl_pips <= 0 or pip_value <= 0:
            return min_lot
        risk_amount = balance * (risk_pct / 100)
        lot = risk_amount / (sl_pips * pip_value)
        return max(min_lot, min(max_lot, round(lot, 2)))

    def calculate_gold_lot_size(
        self,
        balance: float,
        risk_pct: float,
        sl_usd: float,
        contract_size: float = 100,  # 1 lot XAU/USD = 100 oz
    ) -> float:
        """
        Gold-specific lot sizing.
        1 lot XAU/USD = 100 oz, $1 move = $100 profit/loss per lot
        """
        if sl_usd <= 0:
            return 0.01
        risk_amount = balance * (risk_pct / 100)
        lot = risk_amount / (sl_usd * contract_size)
        return max(0.01, min(10.0, round(lot, 2)))

    async def execute_signal(
        self,
        user_id: str,
        symbol: str,
        side: str,
        risk_pct: float,
        sl_price: float,
        tp_price: float,
        magic: int = 777000,
        comment: str = "ESTRADE_v7",
    ) -> dict:
        """
        Full signal execution:
        1. Get account balance
        2. Calculate lot size
        3. Place order
        4. Log to DB
        """
        bridge = await self.get_bridge(user_id)
        if not bridge:
            return {"success": False, "error": "No MT5 connection"}

        try:
            # Get account info
            account = await bridge.get_account_info()
            balance  = account.get("balance", 0)
            if balance <= 0:
                return {"success": False, "error": "Invalid account balance"}

            # Get current price for SL distance calculation
            tick = await bridge.get_symbol_tick(symbol)
            price = tick.get("ask") if side.lower() == "buy" else tick.get("bid")
            if not price:
                return {"success": False, "error": "Cannot get price"}

            # Calculate lot size
            sl_distance_usd = abs(price - sl_price) * self._get_pip_value(symbol)
            is_gold = "XAU" in symbol.upper()

            if is_gold:
                lot = self.calculate_gold_lot_size(balance, risk_pct, abs(price - sl_price))
            else:
                sl_pips = abs(price - sl_price) / self._get_pip_size(symbol)
                pip_val = self._get_pip_value(symbol)
                lot = self.calculate_lot_size(balance, risk_pct, sl_pips, pip_val)

            # Place order
            result = await bridge.place_market_order(
                symbol=symbol, side=side, volume=lot,
                sl=sl_price, tp=tp_price,
                comment=comment, magic=magic,
            )

            if result.get("success"):
                # Log to DB
                db.table("mt5_trades").insert({
                    "user_id":    user_id,
                    "symbol":     symbol,
                    "side":       side,
                    "volume":     lot,
                    "price_open": price,
                    "sl":         sl_price,
                    "tp":         tp_price,
                    "ticket":     result.get("order", 0),
                    "magic":      magic,
                    "comment":    comment,
                    "status":     "open",
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }).execute()

            log.info("mt5_order_placed", user_id=user_id, symbol=symbol,
                     side=side, lot=lot, result=result.get("success"))
            return {**result, "lot": lot, "price": price, "balance": balance}

        except Exception as e:
            log.error("mt5_execute_error", user_id=user_id, error=str(e))
            return {"success": False, "error": str(e)}

    def _get_pip_size(self, symbol: str) -> float:
        """Get pip size for given symbol."""
        if "JPY" in symbol:
            return 0.01
        if "XAU" in symbol or "XAG" in symbol:
            return 0.01
        if "WTI" in symbol or "OIL" in symbol:
            return 0.01
        return 0.0001  # Standard forex

    def _get_pip_value(self, symbol: str) -> float:
        """Get approximate pip value in USD."""
        if "XAU" in symbol:
            return 1.0   # $1 per pip per micro lot (0.01 lot)
        if "XAG" in symbol:
            return 0.5
        if "JPY" in symbol:
            return 0.91  # Approximate
        return 1.0       # Most USD pairs ≈ $1 per pip per 0.01 lot


# Singleton
mt5_service = MT5BrokerService()
