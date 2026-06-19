"""api/routes/users.py v10"""
from fastapi import APIRouter,HTTPException,Request
from pydantic import BaseModel
from typing import Optional
router = APIRouter()

class UpdateUserReq(BaseModel):
    full_name:Optional[str]=None; phone:Optional[str]=None
    telegram_chat_id:Optional[str]=None; signal_mode:Optional[str]=None
    reinvest_global:Optional[int]=None; preferred_exchange:Optional[str]=None
    timezone:Optional[str]=None; language:Optional[str]=None

@router.get("/users/me")
async def get_me(request:Request):
    try:
        import jwt
        from core.config import settings
        from core.database import db
        token=request.headers.get("Authorization","").replace("Bearer ","")
        if not token: raise HTTPException(401,"No token")
        payload=jwt.decode(token,settings.secret_key,algorithms=["HS256"])
        r=db.table("users").select("*").eq("id",payload["sub"]).maybe_single().execute()
        if not r.data: raise HTTPException(404,"User not found")
        user={k:v for k,v in r.data.items() if k!="password_hash"}
        wallet=db.table("wallets").select("*").eq("user_id",payload["sub"]).eq("is_primary",True).maybe_single().execute()
        user["wallet"]=wallet.data or {}
        return user
    except HTTPException:raise
    except Exception as e:raise HTTPException(500,str(e))

@router.put("/users/me")
async def update_me(request:Request,req:UpdateUserReq):
    try:
        import jwt
        from core.config import settings
        from core.database import db
        token=request.headers.get("Authorization","").replace("Bearer ","")
        payload=jwt.decode(token,settings.secret_key,algorithms=["HS256"])
        updates={k:v for k,v in req.dict().items() if v is not None}
        if updates:
            db.table("users").update(updates).eq("id",payload["sub"]).execute()
        return {"success":True,"updated":list(updates.keys())}
    except Exception as e:raise HTTPException(500,str(e))

@router.get("/users/stats")
async def user_stats(request:Request):
    try:
        import jwt
        from core.config import settings
        from core.database import db
        token=request.headers.get("Authorization","").replace("Bearer ","")
        payload=jwt.decode(token,settings.secret_key,algorithms=["HS256"])
        uid=payload["sub"]
        trades=db.table("trades").select("pnl,pnl_pct,status").eq("user_id",uid).execute().data or []
        closed=[t for t in trades if t.get("status")=="closed"]
        wins=[t for t in closed if (t.get("pnl") or 0)>0]
        bots=db.table("bots").select("id,status").eq("user_id",uid).execute().data or []
        return {
            "total_trades":len(closed),"wins":len(wins),
            "win_rate":round(len(wins)/max(len(closed),1)*100,2),
            "total_pnl":round(sum(t.get("pnl",0) for t in closed),2),
            "running_bots":len([b for b in bots if b.get("status")=="running"]),
            "total_bots":len(bots),
        }
    except Exception as e:raise HTTPException(500,str(e))
