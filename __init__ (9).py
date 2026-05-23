"""
api/routes/exchange.py — Secure exchange connection endpoints
"""
from __future__ import annotations
from fastapi import APIRouter, HTTPException, Request, Depends
from pydantic import BaseModel, Field
from typing import Optional
from services.exchange_connector import exchange_service
from core.database import db
import structlog

log = structlog.get_logger("exchange_routes")
router = APIRouter()


# ── Request models ────────────────────────────────────────────

class ConnectRequest(BaseModel):
    exchange:   str = Field(..., min_length=2, max_length=20)
    api_key:    str = Field(..., min_length=10, max_length=200)
    api_secret: str = Field(..., min_length=10, max_length=200)
    label:      str = Field("", max_length=50)

class OrderRequest(BaseModel):
    exchange:   str
    symbol:     str = Field(..., min_length=3, max_length=20)
    side:       str = Field(..., pattern="^(BUY|SELL|buy|sell)$")
    order_type: str = Field(..., pattern="^(MARKET|LIMIT|market|limit)$")
    quantity:   Optional[float] = Field(None, gt=0)
    price:      Optional[float] = Field(None, gt=0)
    quote_qty:  Optional[float] = Field(None, gt=0)

class CancelRequest(BaseModel):
    exchange: str
    symbol:   str
    order_id: int

class DisconnectRequest(BaseModel):
    exchange: str


def get_user_id(request: Request) -> str:
    """Extract user from JWT (Supabase auth header)."""
    # In production, verify Supabase JWT here
    # For now, accept X-User-ID header (set by Supabase RLS middleware)
    user_id = request.headers.get("X-User-ID", "")
    if not user_id:
        raise HTTPException(401, "Not authenticated")
    return user_id

def get_client_ip(request: Request) -> str:
    xff = request.headers.get("X-Forwarded-For","")
    return xff.split(",")[0].strip() if xff else (request.client.host if request.client else "")


# ── Endpoints ─────────────────────────────────────────────────

@router.post("/exchange/connect")
async def connect_exchange(req: ConnectRequest, request: Request):
    """
    Connect exchange account.
    SECURITY: api_key and api_secret are encrypted before storage.
    This endpoint validates permissions (no withdrawal allowed).
    """
    user_id = get_user_id(request)
    ip      = get_client_ip(request)
    try:
        result = await exchange_service.connect(
            user_id   = user_id,
            exchange  = req.exchange,
            api_key   = req.api_key,
            api_secret= req.api_secret,
            label     = req.label,
            user_ip   = ip,
        )
        # Security audit log
        db.table("security_events").insert({
            "type":    "exchange_connected",
            "user_id": user_id,
            "ip":      ip,
            "data":    {"exchange": req.exchange, "label": req.label},
            "severity":"LOW",
        }).execute()
        return result
    except PermissionError as e:
        raise HTTPException(403, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        log.error("connect_failed", user=user_id, error=str(e))
        raise HTTPException(500, "Connection failed. Please check your API key.")


@router.get("/exchange/connections")
async def list_connections(request: Request):
    """List user's exchange connections. NEVER returns API keys."""
    user_id = get_user_id(request)
    return {"connections": exchange_service.list_connections(user_id)}


@router.get("/exchange/account")
async def get_account(exchange: str = "binance", request: Request = None):
    """Get account balances and info."""
    user_id = get_user_id(request)
    try:
        return await exchange_service.get_account(user_id, exchange)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/exchange/order")
async def place_order(req: OrderRequest, request: Request):
    """Place a trading order with full security checks."""
    user_id = get_user_id(request)
    ip      = get_client_ip(request)
    try:
        result = await exchange_service.place_order(
            user_id    = user_id,
            exchange   = req.exchange,
            symbol     = req.symbol.upper(),
            side       = req.side.upper(),
            order_type = req.order_type.upper(),
            quantity   = req.quantity,
            price      = req.price,
            quote_qty  = req.quote_qty,
            user_ip    = ip,
        )
        return {"success": True, "order": result}
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        log.error("order_failed", user=user_id, error=str(e))
        raise HTTPException(500, str(e))


@router.post("/exchange/cancel")
async def cancel_order(req: CancelRequest, request: Request):
    """Cancel an open order."""
    user_id = get_user_id(request)
    try:
        result = await exchange_service.cancel_order(
            user_id, req.exchange, req.symbol.upper(), req.order_id)
        return {"success": True, "result": result}
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/exchange/emergency-stop")
async def emergency_stop(exchange: str = "binance", request: Request = None):
    """Cancel ALL open orders immediately. Emergency use."""
    user_id = get_user_id(request)
    ip      = get_client_ip(request)
    result  = await exchange_service.emergency_stop(user_id, exchange)
    # Log emergency stop
    db.table("security_events").insert({
        "type":    "emergency_stop",
        "user_id": user_id,
        "ip":      ip,
        "data":    {"exchange": exchange, **result},
        "severity":"HIGH",
    }).execute()
    return result


@router.delete("/exchange/disconnect")
async def disconnect_exchange(req: DisconnectRequest, request: Request):
    """Remove exchange connection and destroy encrypted keys."""
    user_id = get_user_id(request)
    exchange_service.disconnect(user_id, req.exchange)
    return {"success": True, "message": f"{req.exchange} disconnected. Keys destroyed."}


@router.get("/exchange/ws-urls")
async def get_ws_urls(symbol: str = "BTCUSDT"):
    """
    Return WebSocket URLs for client to connect directly.
    Public streams require NO API key.
    """
    sym = symbol.lower()
    return {
        "public_streams": {
            "ticker":    f"wss://stream.binance.com:9443/ws/{sym}@ticker",
            "depth":     f"wss://stream.binance.com:9443/ws/{sym}@depth20@100ms",
            "kline_1m":  f"wss://stream.binance.com:9443/ws/{sym}@kline_1m",
            "kline_5m":  f"wss://stream.binance.com:9443/ws/{sym}@kline_5m",
            "kline_15m": f"wss://stream.binance.com:9443/ws/{sym}@kline_15m",
            "kline_1h":  f"wss://stream.binance.com:9443/ws/{sym}@kline_1h",
            "trades":    f"wss://stream.binance.com:9443/ws/{sym}@aggTrade",
            "multi": f"wss://stream.binance.com:9443/stream?streams={sym}@ticker/{sym}@depth20@100ms/{sym}@kline_1m",
        },
        "note": "Connect directly from browser. No authentication needed for public streams.",
        "private_note": "For private account streams, call POST /exchange/listen-key first.",
        "bybit":   f"wss://stream.bybit.com/v5/public/spot",
        "pionex":  "wss://ws.pionex.com/wsPub",
        "okx":     "wss://ws.okx.com:8443/ws/v5/public",
    }


@router.post("/exchange/listen-key")
async def create_listen_key(exchange: str = "binance", request: Request = None):
    """
    Create a WebSocket listenKey for private account stream.
    listenKey expires in 24h. Client must renew every 30 min.
    NEVER returns API keys — only the listenKey.
    """
    user_id = get_user_id(request)
    try:
        from services.exchange_connector import secure_key_manager
        signer = secure_key_manager.get_signer(user_id, exchange)
        if not signer:
            raise HTTPException(400, "Exchange not connected")
        listen_key = await signer.create_listen_key()
        return {
            "listen_key": listen_key,
            "ws_url": f"wss://stream.binance.com:9443/ws/{listen_key}",
            "expires_in_hours": 24,
            "renew_every_mins": 30,
            "note": "Use ws_url to receive: order updates, balance changes",
        }
    except HTTPException: raise
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/exchange/open-orders")
async def get_open_orders(exchange: str = "binance",
                            symbol: Optional[str] = None,
                            request: Request = None):
    """Get open orders."""
    user_id = get_user_id(request)
    try:
        from services.exchange_connector import secure_key_manager
        signer = secure_key_manager.get_signer(user_id, exchange)
        if not signer: raise HTTPException(400, "Exchange not connected")
        orders = await signer.get_open_orders(symbol)
        return {"orders": orders, "count": len(orders)}
    except HTTPException: raise
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/exchange/orderbook")
async def get_orderbook(symbol: str = "BTCUSDT",
                          limit: int = 20, exchange: str = "binance"):
    """Get orderbook (public — no auth needed)."""
    try:
        from services.exchange_connector import BinanceSigner
        signer = BinanceSigner("", "")   # no auth for public
        data   = await signer.get_orderbook(symbol.upper(), limit)
        return data
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/exchange/ticker")
async def get_ticker(symbol: str = "BTCUSDT"):
    """Get 24h ticker (public — no auth needed)."""
    try:
        from services.exchange_connector import BinanceSigner
        signer = BinanceSigner("", "")
        data   = await signer.get_ticker(symbol.upper())
        return data
    except Exception as e:
        raise HTTPException(500, str(e))
