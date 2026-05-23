"""api/routes/admin_tokens.py v10 - Admin token management"""
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import Optional
router = APIRouter()

class CreateTokenReq(BaseModel):
    type: str = "discount"  # free|commission|discount
    discount_pct: float = 0.0
    commission_pct: float = 0.0
    max_uses: int = 1
    expires_days: int = 30
    notes: str = ""

class ValidateTokenReq(BaseModel):
    token: str

@router.post("/admin/tokens/create")
async def create_token(req: CreateTokenReq, request: Request):
    try:
        import jwt
        from core.config import settings
        from core.admin_tokens import admin_token_manager
        from core.database import db
        auth = request.headers.get("Authorization","").replace("Bearer ","")
        if not auth: raise HTTPException(401,"Auth required")
        payload = jwt.decode(auth, settings.secret_key, algorithms=["HS256"])
        # Check admin
        user = db.table("users").select("role").eq("id", payload["sub"]).maybe_single().execute()
        if not user.data or user.data.get("role") != "admin":
            raise HTTPException(403, "Admin only")
        token = admin_token_manager.create(
            type_=req.type, created_by=payload["sub"],
            discount_pct=req.discount_pct, commission_pct=req.commission_pct,
            max_uses=req.max_uses, expires_days=req.expires_days, notes=req.notes
        )
        return {"success": True, "token": token.token, "type": token.type,
                "discount_pct": token.discount_pct, "max_uses": token.max_uses,
                "expires_days": req.expires_days}
    except HTTPException: raise
    except Exception as e: raise HTTPException(500, str(e))

@router.get("/admin/tokens/list")
async def list_tokens(request: Request):
    try:
        import jwt
        from core.config import settings
        from core.admin_tokens import admin_token_manager
        from core.database import db
        auth = request.headers.get("Authorization","").replace("Bearer ","")
        payload = jwt.decode(auth, settings.secret_key, algorithms=["HS256"])
        user = db.table("users").select("role").eq("id", payload["sub"]).maybe_single().execute()
        if not user.data or user.data.get("role") != "admin":
            raise HTTPException(403, "Admin only")
        return {"tokens": admin_token_manager.list_tokens()}
    except HTTPException: raise
    except Exception as e: raise HTTPException(500, str(e))

@router.post("/admin/tokens/validate")
async def validate_token(req: ValidateTokenReq):
    try:
        from core.admin_tokens import admin_token_manager
        result = admin_token_manager.validate(req.token)
        if not result: raise HTTPException(400, "Invalid or expired token")
        return result
    except HTTPException: raise
    except Exception as e: raise HTTPException(500, str(e))

@router.delete("/admin/tokens/{token}/revoke")
async def revoke_token(token: str, request: Request):
    try:
        import jwt
        from core.config import settings
        from core.admin_tokens import admin_token_manager
        from core.database import db
        auth = request.headers.get("Authorization","").replace("Bearer ","")
        payload = jwt.decode(auth, settings.secret_key, algorithms=["HS256"])
        user = db.table("users").select("role").eq("id", payload["sub"]).maybe_single().execute()
        if not user.data or user.data.get("role") != "admin":
            raise HTTPException(403, "Admin only")
        admin_token_manager.revoke(token)
        return {"success": True, "revoked": token}
    except HTTPException: raise
    except Exception as e: raise HTTPException(500, str(e))
