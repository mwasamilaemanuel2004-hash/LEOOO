"""api/routes/tokens.py v10 — JWT token management"""
from fastapi import APIRouter,HTTPException,Request
from pydantic import BaseModel
router = APIRouter()

class RefreshReq(BaseModel):
    token:str

@router.post("/tokens/refresh")
async def refresh(req:RefreshReq):
    try:
        import jwt,time
        from core.config import settings
        payload=jwt.decode(req.token,settings.secret_key,algorithms=["HS256"],
                          options={"verify_exp":False})
        new_token=jwt.encode({"sub":payload["sub"],"exp":int(time.time())+86400*7},
                             settings.secret_key,"HS256")
        return {"token":new_token,"expires_in":86400*7}
    except Exception as e:raise HTTPException(401,str(e))

@router.post("/tokens/verify")
async def verify(req:RefreshReq):
    try:
        import jwt
        from core.config import settings
        payload=jwt.decode(req.token,settings.secret_key,algorithms=["HS256"])
        return {"valid":True,"user_id":payload.get("sub")}
    except Exception as e:return {"valid":False,"error":str(e)}

@router.delete("/tokens/revoke")
async def revoke(request:Request):
    try:
        from core.database import db
        token=request.headers.get("Authorization","").replace("Bearer ","")
        if db and token:
            import hashlib
            h=hashlib.sha256(token.encode()).hexdigest()
            db.table("auth_sessions").update({"is_active":False}).eq("token_hash",h).execute()
        return {"revoked":True}
    except Exception as e:raise HTTPException(500,str(e))
