from fastapi import APIRouter, HTTPException, Request, Depends
from pydantic import BaseModel, Field
from typing import Optional, List
from core.database import db
from core.security import security_manager
from services.exchange_service import exchange_service
import structlog

log = structlog.get_logger("exchange_routes")
router = APIRouter()

class ConnectRequest(BaseModel):
    exchange: str
    api_key: str
    secret_key: str
    passphrase: Optional[str] = None

@router.post("/exchange/connect")
async def connect_exchange(req: ConnectRequest, request: Request):
    user_id = request.headers.get("X-User-ID")
    if not user_id: raise HTTPException(401, "Auth required")

    # 1. Test connection before saving
    is_valid = await exchange_service.test_connection(req.exchange, req.api_key, req.secret_key, req.passphrase)
    if not is_valid:
        raise HTTPException(400, "Invalid API credentials or connection failed")

    # 2. Encrypt and store
    data = {
        "user_id": user_id,
        "exchange": req.exchange.lower(),
        "api_key": security_manager.encrypt(req.api_key),
        "secret_key": security_manager.encrypt(req.secret_key),
        "passphrase": security_manager.encrypt(req.passphrase) if req.passphrase else None,
        "status": "connected"
    }
    db.table("exchange_connections").upsert(data, on_conflict="user_id,exchange").execute()

    # 3. Audit log
    db.table("audit_logs").insert({
        "user_id": user_id,
        "action": "connect_exchange",
        "metadata": {"exchange": req.exchange}
    }).execute()

    return {"success": True}

@router.get("/exchange/list")
async def list_connections(request: Request):
    user_id = request.headers.get("X-User-ID")
    res = db.table("exchange_connections").select("exchange,status").eq("user_id", user_id).execute()
    return {"connections": res.data}

@router.delete("/exchange/{exchange}")
async def delete_connection(exchange: str, request: Request):
    user_id = request.headers.get("X-User-ID")
    db.table("exchange_connections").delete().eq("user_id", user_id).eq("exchange", exchange.lower()).execute()
    return {"success": True}
