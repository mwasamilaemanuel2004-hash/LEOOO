"""middleware/auth.py — JWT Auth Dependency"""
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from core.security import decode_token, hash_token
from core.database import db

security = HTTPBearer()


async def get_current_user(
    req: Request,
    creds: HTTPAuthorizationCredentials = Depends(security)
) -> dict:
    token = creds.credentials
    try:
        payload = decode_token(token)
    except Exception:
        raise HTTPException(401, "Invalid or expired token")

    if payload.get("type") != "access":
        raise HTTPException(401, "Invalid token type")

    # Check session not revoked
    token_hash = hash_token(token)
    session = (db.table("auth_sessions")
               .select("id,is_revoked")
               .eq("token_hash", token_hash)
               .single()
               .execute())
    if not session.data or session.data.get("is_revoked"):
        raise HTTPException(401, "Session revoked. Please login again.")

    user = await db.get_user(payload["sub"])
    if not user:
        raise HTTPException(401, "User not found")
    if not user.get("is_active"):
        raise HTTPException(403, "Account disabled")

    return user


async def require_admin(user: dict = Depends(get_current_user)) -> dict:
    if user.get("role") != "admin":
        raise HTTPException(403, "Admin access required")
    return user


async def require_trading_enabled(user: dict = Depends(get_current_user)) -> dict:
    if not user.get("trading_enabled", True):
        raise HTTPException(403, "Trading has been disabled for your account. Contact support.")
    return user
