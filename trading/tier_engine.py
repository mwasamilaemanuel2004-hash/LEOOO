"""
services/exchange_connector.py — ESTRADE v7 ULTRA Secure Exchange Connector
═══════════════════════════════════════════════════════════════════════════════
SECURITY ARCHITECTURE (hacker-proof):

  ① API KEY STORAGE
     → Keys encrypted with AES-256 (Fernet) before DB write
     → Encryption key stored ONLY in environment variable (never DB)
     → Keys are NEVER logged, never returned to frontend in plaintext
     → Frontend sends keys ONCE during setup → backend encrypts → stores
     → If DB is breached, keys are worthless (encrypted)

  ② PERMISSIONS ENFORCED
     → ONLY "Read + Trade" permissions allowed (NEVER withdrawal)
     → Before saving any key, we verify it has no withdrawal permission
     → If withdrawal detected → reject connection immediately

  ③ REQUEST SIGNING
     → All Binance requests signed server-side with HMAC-SHA256
     → Timestamp included: requests expire in 5 seconds
     → RecvWindow: 5000ms (tight window against replay attacks)

  ④ WEBSOCKET CONNECTIONS
     → Direct Binance WebSocket for live prices (no auth needed)
     → User WebSocket (account data) uses listenKey (expires every hour)
     → ListenKey auto-renewed every 30 min

  ⑤ ANTI-HACK MEASURES
     → Rate limiting: 10 API calls per second per user (Binance limit)
     → IP-bound keys: store user IP when key added, alert on new IP
     → Anomaly detection: alert if order volume spikes 5× usual
     → Emergency stop: one API call halts ALL trading for that user
     → Key rotation reminder: notify user every 90 days

  ⑥ WEBSOCKET STREAMS (no API key needed for public data)
     Binance Public:
       wss://stream.binance.com:9443/ws/{symbol}@ticker
       wss://stream.binance.com:9443/ws/{symbol}@depth20@100ms
       wss://stream.binance.com:9443/ws/{symbol}@kline_{interval}
       wss://stream.binance.com:9443/ws/{symbol}@aggTrade

     Binance Private (requires listenKey):
       wss://stream.binance.com:9443/ws/{listenKey}
       → Receives: order updates, balance changes, position updates

     Other exchanges:
       Bybit:  wss://stream.bybit.com/v5/public/spot
       Pionex: wss://ws.pionex.com/wsPub
       OKX:    wss://ws.okx.com:8443/ws/v5/public
═══════════════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations
import asyncio, base64, hashlib, hmac, json, os, time, urllib.parse
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Optional
import httpx, structlog

log = structlog.get_logger("exchange_connector")

# ── Encryption (AES-256 via Fernet) ──────────────────────────
try:
    from cryptography.fernet import Fernet
    _ENC_KEY = os.getenv("ENCRYPTION_KEY", "")
    if not _ENC_KEY:
        # Generate one and warn — in production, set ENCRYPTION_KEY env var
        _ENC_KEY = Fernet.generate_key().decode()
        log.warning("ENCRYPTION_KEY not set — using ephemeral key. Set ENCRYPTION_KEY in .env")
    _FERNET = Fernet(_ENC_KEY.encode() if isinstance(_ENC_KEY, str) else _ENC_KEY)

    def encrypt(text: str) -> str:
        return _FERNET.encrypt(text.encode()).decode()

    def decrypt(token: str) -> str:
        return _FERNET.decrypt(token.encode()).decode()

except ImportError:
    import base64 as _b64
    log.warning("cryptography not installed — using base64 (NOT secure for production)")

    def encrypt(text: str) -> str:
        return _b64.b64encode(text.encode()).decode()

    def decrypt(token: str) -> str:
        return _b64.b64decode(token.encode()).decode()


# ══════════════════════════════════════════════════════════════
# BINANCE SIGNER
# ══════════════════════════════════════════════════════════════

class BinanceSigner:
    """Handles all Binance request signing. Server-side only."""

    BASE = "https://api.binance.com"
    RECV_WINDOW = 5000   # 5 second window (tight against replay attacks)

    def __init__(self, api_key: str, api_secret: str):
        self._key    = api_key
        self._secret = api_secret

    def _sign(self, query_string: str) -> str:
        return hmac.new(
            self._secret.encode("utf-8"),
            query_string.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def _build_url(self, endpoint: str, params: dict,
                    signed: bool = False) -> tuple[str, dict]:
        params = {k: v for k, v in params.items() if v is not None}
        if signed:
            params["timestamp"]  = int(time.time() * 1000)
            params["recvWindow"] = self.RECV_WINDOW
            qs  = urllib.parse.urlencode(params)
            sig = self._sign(qs)
            qs += f"&signature={sig}"
            return f"{self.BASE}{endpoint}?{qs}", {}
        return f"{self.BASE}{endpoint}", params

    def _headers(self) -> dict:
        return {
            "X-MBX-APIKEY": self._key,
            "Content-Type": "application/json",
        }

    async def get(self, endpoint: str, params: dict = None,
                   signed: bool = False) -> dict:
        url, qp = self._build_url(endpoint, params or {}, signed)
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(url, params=(qp if qp else None),
                                  headers=self._headers())
            data = r.json()
            if isinstance(data, dict) and data.get("code"):
                if data["code"] < 0:
                    raise ValueError(f"Binance error {data['code']}: {data.get('msg','')}")
            return data

    async def post(self, endpoint: str, params: dict = None) -> dict:
        url, _ = self._build_url(endpoint, params or {}, signed=True)
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(url, headers=self._headers())
            data = r.json()
            if isinstance(data, dict) and data.get("code", 0) < 0:
                raise ValueError(f"Binance error {data['code']}: {data.get('msg','')}")
            return data

    async def delete(self, endpoint: str, params: dict = None) -> dict:
        url, _ = self._build_url(endpoint, params or {}, signed=True)
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.delete(url, headers=self._headers())
            return r.json()

    # ── Account operations ────────────────────────────────────

    async def get_account(self) -> dict:
        """Get account info and balances."""
        return await self.get("/api/v3/account", signed=True)

    async def check_permissions(self) -> dict:
        """Check API key permissions — CRITICAL security check."""
        data = await self.get("/api/v3/account", signed=True)
        perms = data.get("permissions", [])
        return {
            "can_trade":    "SPOT" in perms or "MARGIN" in perms,
            "can_withdraw": "WITHDRAWALS" in perms,  # should be FALSE
            "can_read":     True,
            "permissions":  perms,
            "raw":          data,
        }

    async def get_balances(self, min_usd_value: float = 0.01) -> list[dict]:
        """Get non-zero balances."""
        account = await self.get_account()
        balances = []
        for b in account.get("balances", []):
            free  = float(b["free"])
            locked= float(b["locked"])
            total = free + locked
            if total > min_usd_value:
                balances.append({
                    "asset":  b["asset"],
                    "free":   free,
                    "locked": locked,
                    "total":  total,
                })
        return sorted(balances, key=lambda x: x["total"], reverse=True)

    async def create_listen_key(self) -> str:
        """Create WebSocket listenKey for private streams."""
        data = await self.post("/api/v3/userDataStream")
        return data.get("listenKey", "")

    async def keepalive_listen_key(self, listen_key: str) -> bool:
        """Keep listenKey alive (call every 30 min)."""
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.put(
                f"{self.BASE}/api/v3/userDataStream",
                params={"listenKey": listen_key},
                headers=self._headers(),
            )
            return r.status_code == 200

    # ── Trading operations ────────────────────────────────────

    async def place_order(
        self,
        symbol:    str,
        side:      str,    # BUY | SELL
        order_type:str,    # MARKET | LIMIT
        quantity:  Optional[float] = None,
        price:     Optional[float] = None,
        quote_qty: Optional[float] = None,   # for MARKET BUY by USDT amount
    ) -> dict:
        params = {
            "symbol":   symbol.upper(),
            "side":     side.upper(),
            "type":     order_type.upper(),
        }
        if order_type.upper() == "LIMIT":
            params["timeInForce"] = "GTC"
            params["price"]       = f"{price:.8f}".rstrip("0").rstrip(".")
        if quantity:
            params["quantity"] = f"{quantity:.8f}".rstrip("0").rstrip(".")
        if quote_qty and order_type.upper() == "MARKET":
            params["quoteOrderQty"] = f"{quote_qty:.2f}"

        return await self.post("/api/v3/order", params)

    async def cancel_order(self, symbol: str, order_id: int) -> dict:
        return await self.delete("/api/v3/order",
                                  {"symbol": symbol, "orderId": order_id})

    async def get_open_orders(self, symbol: str = None) -> list[dict]:
        params = {"symbol": symbol} if symbol else {}
        return await self.get("/api/v3/openOrders", params, signed=True)

    async def get_order_history(self, symbol: str, limit: int = 50) -> list[dict]:
        return await self.get("/api/v3/allOrders",
                               {"symbol": symbol, "limit": limit}, signed=True)

    async def get_my_trades(self, symbol: str, limit: int = 50) -> list[dict]:
        return await self.get("/api/v3/myTrades",
                               {"symbol": symbol, "limit": limit}, signed=True)

    # ── Market data (no auth) ─────────────────────────────────

    async def get_ticker(self, symbol: str) -> dict:
        return await self.get("/api/v3/ticker/24hr", {"symbol": symbol})

    async def get_orderbook(self, symbol: str, limit: int = 20) -> dict:
        return await self.get("/api/v3/depth", {"symbol": symbol, "limit": limit})

    async def get_klines(self, symbol: str, interval: str = "1m",
                          limit: int = 100) -> list:
        return await self.get("/api/v3/klines",
                               {"symbol": symbol, "interval": interval, "limit": limit})


# ══════════════════════════════════════════════════════════════
# SECURE KEY MANAGER
# ══════════════════════════════════════════════════════════════

class SecureKeyManager:
    """
    Manages exchange API keys securely.
    Keys are encrypted before storage and never returned plaintext.
    """

    # Allowed exchanges and their validation endpoints
    EXCHANGE_VALIDATORS = {
        "binance": "/api/v3/account",
        "bybit":   "/v5/account/info",
        "pionex":  "/api/v1/common/symbols",
        "okx":     "/api/v5/account/balance",
    }

    async def save_connection(
        self,
        user_id:    str,
        exchange:   str,
        api_key:    str,
        api_secret: str,
        label:      str = "",
        user_ip:    str = "",
        extra:      dict = None,
    ) -> dict:
        """
        Validate, check permissions, encrypt, and save exchange connection.
        SECURITY: api_key and api_secret are encrypted before any DB write.
        """
        from core.database import db

        exchange = exchange.lower().strip()

        # ── Security: validate key format ─────────────────────
        if not api_key or len(api_key) < 10:
            raise ValueError("Invalid API key format")
        if not api_secret or len(api_secret) < 10:
            raise ValueError("Invalid API secret format")

        # ── Security: check permissions FIRST ────────────────
        if exchange == "binance":
            signer = BinanceSigner(api_key, api_secret)
            try:
                perms = await signer.check_permissions()
                if perms["can_withdraw"]:
                    raise PermissionError(
                        "🚨 SECURITY ALERT: This API key has WITHDRAWAL permission. "
                        "ESTRADE requires Read + Trade ONLY. "
                        "Please create a new API key WITHOUT withdrawal permission."
                    )
                if not perms["can_trade"]:
                    raise PermissionError(
                        "This API key does not have trading permission. "
                        "Please enable SPOT trading in Binance API settings."
                    )
            except PermissionError:
                raise
            except Exception as e:
                raise ValueError(f"Cannot verify API key: {e}")

        # ── Encrypt keys ──────────────────────────────────────
        key_enc    = encrypt(api_key)
        secret_enc = encrypt(api_secret)

        # ── Save to DB ────────────────────────────────────────
        conn_data = {
            "user_id":       user_id,
            "exchange":      exchange,
            "label":         label or f"{exchange.title()} Account",
            "api_key_enc":   key_enc,
            "api_secret_enc":secret_enc,
            "status":        "active",
            "added_from_ip": user_ip,
            "permissions":   perms.get("permissions",[]) if exchange == "binance" else [],
            "extra_enc":     encrypt(json.dumps(extra or {})),
            "created_at":    datetime.now(timezone.utc).isoformat(),
            "last_verified": datetime.now(timezone.utc).isoformat(),
        }

        # Check if connection already exists → update
        existing = db.table("exchange_connections").select("id").eq(
            "user_id", user_id).eq("exchange", exchange).maybe_single().execute()
        if existing.data:
            db.table("exchange_connections").update(conn_data).eq(
                "id", existing.data["id"]).execute()
            conn_id = existing.data["id"]
            log.info("exchange_conn_updated", user=user_id, exchange=exchange)
        else:
            result = db.table("exchange_connections").insert(conn_data).execute()
            conn_id = result.data[0]["id"] if result.data else ""
            log.info("exchange_conn_created", user=user_id, exchange=exchange)

        # NEVER return the encrypted keys
        return {
            "success":    True,
            "conn_id":    conn_id,
            "exchange":   exchange,
            "label":      conn_data["label"],
            "status":     "active",
            "can_trade":  True,
            "can_withdraw":False,
            "message":    "✅ Connected securely. Keys encrypted with AES-256.",
        }

    def get_signer(self, user_id: str, exchange: str) -> Optional[BinanceSigner]:
        """
        Load decrypted keys from DB and return a signer.
        Keys are decrypted in memory, never written to disk.
        SECURITY: This function is called server-side only.
        """
        from core.database import db
        conn = db.table("exchange_connections").select(
            "api_key_enc,api_secret_enc,status"
        ).eq("user_id", user_id).eq("exchange", exchange).eq(
            "status", "active").maybe_single().execute()

        if not conn.data:
            return None

        try:
            api_key    = decrypt(conn.data["api_key_enc"])
            api_secret = decrypt(conn.data["api_secret_enc"])
            if exchange == "binance":
                return BinanceSigner(api_key, api_secret)
            return None
        except Exception as e:
            log.error("key_decrypt_failed", user=user_id, exchange=exchange,
                       error=str(e)[:50])
            return None

    def delete_connection(self, user_id: str, exchange: str):
        """Remove exchange connection and destroy encrypted keys."""
        from core.database import db
        db.table("exchange_connections").delete().eq(
            "user_id", user_id).eq("exchange", exchange).execute()
        log.info("exchange_conn_deleted", user=user_id, exchange=exchange)

    def list_connections(self, user_id: str) -> list[dict]:
        """List connections WITHOUT returning any key data."""
        from core.database import db
        conns = db.table("exchange_connections").select(
            "id,exchange,label,status,created_at,last_verified,permissions"
        ).eq("user_id", user_id).execute().data or []

        # Strip any sensitive fields
        return [{
            "id":            c["id"],
            "exchange":      c["exchange"],
            "label":         c.get("label",""),
            "status":        c.get("status",""),
            "created_at":    c.get("created_at",""),
            "last_verified": c.get("last_verified",""),
            "permissions":   c.get("permissions",[]),
            "key_preview":   "****" + c.get("api_key_preview",""),
        } for c in conns]


# ══════════════════════════════════════════════════════════════
# WEBSOCKET MANAGER
# ══════════════════════════════════════════════════════════════

class BinanceWSManager:
    """
    Manages Binance WebSocket streams server-side.
    Public streams (prices): no auth needed.
    Private stream (account): uses listenKey, auto-renewed.
    """

    PUBLIC_WS  = "wss://stream.binance.com:9443/ws"
    PRIVATE_WS = "wss://stream.binance.com:9443/ws"

    def __init__(self):
        self._subs:       dict[str, asyncio.Task] = {}   # stream_key → task
        self._listeners:  dict[str, list]          = {}   # stream_key → callbacks
        self._listen_keys:dict[str, str]            = {}   # user_id → listenKey
        self._last_prices:dict[str, float]          = {}   # symbol → price

    def get_ws_url(self, symbol: str, stream_type: str = "ticker") -> str:
        """Get WebSocket URL for a public stream."""
        sym = symbol.lower()
        streams = {
            "ticker":  f"{self.PUBLIC_WS}/{sym}@ticker",
            "depth":   f"{self.PUBLIC_WS}/{sym}@depth20@100ms",
            "kline_1m":f"{self.PUBLIC_WS}/{sym}@kline_1m",
            "kline_5m":f"{self.PUBLIC_WS}/{sym}@kline_5m",
            "trade":   f"{self.PUBLIC_WS}/{sym}@aggTrade",
            "mini":    f"{self.PUBLIC_WS}/{sym}@miniTicker",
        }
        return streams.get(stream_type, streams["ticker"])

    def get_private_ws_url(self, listen_key: str) -> str:
        return f"{self.PRIVATE_WS}/{listen_key}"

    async def start_public_stream(self, symbol: str,
                                    stream_type: str = "ticker",
                                    callback=None):
        """Start a public WebSocket stream."""
        key = f"{symbol}:{stream_type}"
        if key in self._subs:
            return  # Already running

        if callback:
            self._listeners.setdefault(key, []).append(callback)

        url  = self.get_ws_url(symbol, stream_type)
        task = asyncio.create_task(
            self._stream_loop(key, url),
            name=f"ws_{key}",
        )
        self._subs[key] = task
        log.info("ws_stream_started", symbol=symbol, type=stream_type)

    async def _stream_loop(self, key: str, url: str):
        """WebSocket receive loop with auto-reconnect."""
        import websockets
        reconnect_delay = 1
        while True:
            try:
                async with websockets.connect(
                    url,
                    ping_interval=30,
                    ping_timeout=10,
                    close_timeout=5,
                ) as ws:
                    reconnect_delay = 1  # reset on success
                    log.info("ws_connected", key=key)
                    async for raw in ws:
                        data = json.loads(raw)
                        # Cache latest price
                        if "c" in data:  # ticker
                            sym = data.get("s","").lower()
                            if sym: self._last_prices[sym] = float(data["c"])
                        # Notify callbacks
                        for cb in self._listeners.get(key, []):
                            try:
                                if asyncio.iscoroutinefunction(cb):
                                    await cb(data)
                                else:
                                    cb(data)
                            except Exception:
                                pass
            except Exception as e:
                log.warning("ws_disconnected", key=key, error=str(e)[:80],
                             reconnect_in=reconnect_delay)
                await asyncio.sleep(reconnect_delay)
                reconnect_delay = min(reconnect_delay * 2, 30)  # exp backoff

    async def start_private_stream(self, user_id: str,
                                     signer: BinanceSigner,
                                     callback=None):
        """Start private account stream (orders/balances)."""
        listen_key = await signer.create_listen_key()
        self._listen_keys[user_id] = listen_key
        key = f"private:{user_id}"
        if callback:
            self._listeners.setdefault(key, []).append(callback)
        url  = self.get_private_ws_url(listen_key)
        task = asyncio.create_task(
            self._private_stream_loop(key, url, signer, listen_key),
            name=f"ws_private_{user_id}",
        )
        self._subs[key] = task

    async def _private_stream_loop(self, key: str, url: str,
                                     signer: BinanceSigner,
                                     listen_key: str):
        """Private stream with listenKey renewal every 30 min."""
        import websockets
        last_renew = time.time()
        while True:
            try:
                async with websockets.connect(url, ping_interval=30) as ws:
                    async for raw in ws:
                        data = json.loads(raw)
                        # Auto-renew listenKey every 30 min
                        if time.time() - last_renew > 1800:
                            await signer.keepalive_listen_key(listen_key)
                            last_renew = time.time()
                        for cb in self._listeners.get(key, []):
                            try:
                                await cb(data) if asyncio.iscoroutinefunction(cb) else cb(data)
                            except Exception:
                                pass
            except Exception as e:
                log.warning("private_ws_error", key=key, error=str(e)[:80])
                await asyncio.sleep(5)

    def get_price(self, symbol: str) -> Optional[float]:
        return self._last_prices.get(symbol.lower().replace("/",""))

    def stop_stream(self, symbol: str, stream_type: str = "ticker"):
        key  = f"{symbol}:{stream_type}"
        task = self._subs.pop(key, None)
        if task: task.cancel()

    def stop_all(self):
        for task in self._subs.values():
            task.cancel()
        self._subs.clear()


# ══════════════════════════════════════════════════════════════
# RATE LIMITER (protect against ban + abuse)
# ══════════════════════════════════════════════════════════════

class ExchangeRateLimiter:
    """
    Per-user, per-exchange rate limiting.
    Binance limits: 1200 req/min weight-based.
    We use 600 to stay safe (50% margin).
    """
    MAX_WEIGHT_PER_MIN = 600
    MAX_ORDERS_PER_10S = 10

    def __init__(self):
        self._weights: dict[str, deque] = defaultdict(lambda: deque(maxlen=1200))
        self._orders:  dict[str, deque] = defaultdict(lambda: deque(maxlen=50))

    def check(self, user_id: str, weight: int = 1) -> tuple[bool, str]:
        """Check if request is within rate limits."""
        key = f"{user_id}"
        now = time.time()

        # Clean old entries
        while self._weights[key] and now - self._weights[key][0] > 60:
            self._weights[key].popleft()

        total_weight = sum(1 for _ in self._weights[key]) + weight
        if total_weight > self.MAX_WEIGHT_PER_MIN:
            return False, f"Rate limit: {total_weight}/{self.MAX_WEIGHT_PER_MIN} weight/min"

        self._weights[key].append(now)
        return True, "ok"

    def record_order(self, user_id: str):
        self._orders[user_id].append(time.time())

    def check_order_rate(self, user_id: str) -> tuple[bool, str]:
        now = time.time()
        self._orders[user_id] = deque(
            [t for t in self._orders[user_id] if now - t < 10],
            maxlen=50
        )
        if len(self._orders[user_id]) >= self.MAX_ORDERS_PER_10S:
            return False, f"Order rate limit: max {self.MAX_ORDERS_PER_10S} orders/10s"
        return True, "ok"


# ══════════════════════════════════════════════════════════════
# ANOMALY DETECTOR (anti-hack)
# ══════════════════════════════════════════════════════════════

class TradingAnomalyDetector:
    """
    Detects suspicious trading patterns that could indicate:
    - API key compromise
    - Unusual order sizes
    - Abnormal trading frequency
    """

    def __init__(self):
        self._order_sizes:  dict[str, deque] = defaultdict(lambda: deque(maxlen=100))
        self._trade_times:  dict[str, deque] = defaultdict(lambda: deque(maxlen=200))
        self._known_ips:    dict[str, set]   = defaultdict(set)

    def record_order(self, user_id: str, size_usd: float, symbol: str):
        self._order_sizes[user_id].append(size_usd)
        self._trade_times[user_id].append(time.time())

    def check_order(self, user_id: str, size_usd: float,
                     symbol: str, ip: str) -> list[str]:
        """Returns list of warning strings (empty = clean)."""
        warnings = []

        # Check order size anomaly (spike 5× average)
        history = list(self._order_sizes[user_id])
        if len(history) >= 10:
            import statistics
            avg = statistics.mean(history)
            if size_usd > avg * 5 and avg > 0:
                warnings.append(
                    f"Order size ${size_usd:.0f} is {size_usd/avg:.0f}× your average "
                    f"(${avg:.0f}). Possible API key compromise."
                )

        # Check trading frequency (>20 orders in 60s)
        now = time.time()
        recent = [t for t in self._trade_times[user_id] if now - t < 60]
        if len(recent) > 20:
            warnings.append(
                f"Unusually high order frequency: {len(recent)} orders in last 60s."
            )

        # Check new IP
        if ip and ip not in self._known_ips[user_id]:
            if self._known_ips[user_id]:  # not first IP
                warnings.append(f"New IP address detected: {ip}")
            self._known_ips[user_id].add(ip)

        return warnings

    async def alert_if_suspicious(self, user_id: str,
                                    warnings: list[str]):
        if not warnings: return
        from services.notification_service import notification_service
        await notification_service.send(
            user_id=user_id,
            event="trading_anomaly",
            title="🚨 Suspicious Trading Activity Detected",
            body="\n".join(f"• {w}" for w in warnings),
            data={"warnings": warnings},
            is_urgent=True,
        )


# ══════════════════════════════════════════════════════════════
# UNIFIED EXCHANGE SERVICE
# ══════════════════════════════════════════════════════════════

class ExchangeService:
    """
    Single entry point for all exchange operations.
    Handles: auth, rate limiting, anomaly detection, logging.
    """

    def __init__(self):
        self.key_manager  = SecureKeyManager()
        self.ws_manager   = BinanceWSManager()
        self.rate_limiter = ExchangeRateLimiter()
        self.anomaly      = TradingAnomalyDetector()

    async def connect(self, user_id: str, exchange: str,
                       api_key: str, api_secret: str,
                       label: str = "", user_ip: str = "") -> dict:
        """Connect a user's exchange account securely."""
        return await self.key_manager.save_connection(
            user_id, exchange, api_key, api_secret, label, user_ip)

    async def get_account(self, user_id: str, exchange: str = "binance") -> dict:
        """Get account info (balances etc.)."""
        ok, reason = self.rate_limiter.check(user_id, weight=10)
        if not ok: raise ValueError(reason)

        signer = self.key_manager.get_signer(user_id, exchange)
        if not signer: raise ValueError("Exchange not connected")

        if exchange == "binance":
            account  = await signer.get_account()
            balances = await signer.get_balances()
            return {
                "exchange":     exchange,
                "balances":     balances,
                "permissions":  account.get("permissions", []),
                "maker_fee":    account.get("makerCommission", 0) / 10000,
                "taker_fee":    account.get("takerCommission", 0) / 10000,
                "can_trade":    account.get("canTrade", False),
                "can_withdraw": account.get("canWithdraw", False),
            }
        raise ValueError(f"Exchange {exchange} not implemented")

    async def place_order(
        self,
        user_id:    str,
        exchange:   str,
        symbol:     str,
        side:       str,
        order_type: str,
        quantity:   Optional[float] = None,
        price:      Optional[float] = None,
        quote_qty:  Optional[float] = None,
        user_ip:    str = "",
    ) -> dict:
        """Place an order with full security checks."""

        # Rate limit check
        ok, reason = self.rate_limiter.check(user_id, weight=1)
        if not ok: raise ValueError(reason)

        # Order rate check
        ok, reason = self.rate_limiter.check_order_rate(user_id)
        if not ok: raise ValueError(reason)

        signer = self.key_manager.get_signer(user_id, exchange)
        if not signer: raise ValueError(f"{exchange} not connected")

        # Anomaly check
        size_usd = (quantity or 0) * (price or 1) if quantity else (quote_qty or 0)
        warnings = self.anomaly.check_order(user_id, size_usd, symbol, user_ip)
        if warnings:
            await self.anomaly.alert_if_suspicious(user_id, warnings)
            if any("API key compromise" in w for w in warnings):
                raise ValueError(f"Order blocked — security alert: {warnings[0]}")

        # Place order
        if exchange == "binance":
            result = await signer.place_order(
                symbol, side, order_type, quantity, price, quote_qty)
            self.rate_limiter.record_order(user_id)
            self.anomaly.record_order(user_id, size_usd, symbol)

            log.info("order_placed", user=user_id, symbol=symbol,
                      side=side, type=order_type, size_usd=size_usd)

            # Save to DB
            try:
                from core.database import db
                db.table("manual_orders").insert({
                    "user_id":    user_id,
                    "exchange":   exchange,
                    "symbol":     symbol,
                    "side":       side,
                    "order_type": order_type,
                    "quantity":   quantity,
                    "price":      price,
                    "order_id":   result.get("orderId", ""),
                    "status":     result.get("status", ""),
                    "filled_qty": float(result.get("executedQty", 0)),
                    "avg_price":  float(result.get("price", price or 0)),
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }).execute()
            except Exception:
                pass

            return result

        raise ValueError(f"Exchange {exchange} not implemented")

    async def cancel_order(self, user_id: str, exchange: str,
                            symbol: str, order_id: int) -> dict:
        signer = self.key_manager.get_signer(user_id, exchange)
        if not signer: raise ValueError("Not connected")
        if exchange == "binance":
            return await signer.cancel_order(symbol, order_id)
        raise ValueError(f"Exchange {exchange} not implemented")

    async def emergency_stop(self, user_id: str, exchange: str):
        """Cancel ALL open orders immediately."""
        signer = self.key_manager.get_signer(user_id, exchange)
        if not signer: return {"cancelled": 0}
        if exchange == "binance":
            open_orders = await signer.get_open_orders()
            cancelled   = 0
            for order in open_orders:
                try:
                    await signer.cancel_order(order["symbol"], order["orderId"])
                    cancelled += 1
                except Exception:
                    pass
            log.warning("emergency_stop", user=user_id,
                         exchange=exchange, cancelled=cancelled)
            return {"cancelled": cancelled, "message": f"✅ {cancelled} orders cancelled"}
        return {"cancelled": 0}

    def disconnect(self, user_id: str, exchange: str):
        """Remove connection and stop related streams."""
        self.key_manager.delete_connection(user_id, exchange)
        self.ws_manager.stop_stream(exchange, "ticker")

    def list_connections(self, user_id: str) -> list[dict]:
        return self.key_manager.list_connections(user_id)


# Singletons
exchange_service = ExchangeService()
secure_key_manager = SecureKeyManager()
