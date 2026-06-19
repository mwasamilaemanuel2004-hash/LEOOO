"""api/routes/reinvest.py v10"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
router = APIRouter()

class ModeReq(BaseModel):
    mode: int

@router.get("/reinvest/modes")
async def get_modes():
    from services.reinvestment_engine_v9 import reinvest_engine
    return {"modes": reinvest_engine.get_all_modes()}

@router.post("/reinvest/{bot_id}/mode")
async def set_mode(bot_id: str, req: ModeReq):
    try:
        from services.reinvestment_engine_v9 import reinvest_engine
        from core.database import db
        r = reinvest_engine.set_mode(bot_id, req.mode)
        if db:
            try: db.table("bots").update({"reinvest_mode":req.mode}).eq("id",bot_id).execute()
            except: pass
        return r
    except Exception as e: raise HTTPException(500, str(e))

@router.post("/reinvest/global")
async def set_global(req: ModeReq):
    try:
        from services.reinvestment_engine_v9 import reinvest_engine
        from core.database import db
        if db:
            bots = db.table("bots").select("id").eq("status","running").execute().data or []
            for b in bots:
                reinvest_engine.set_mode(str(b["id"]), req.mode)
                db.table("bots").update({"reinvest_mode":req.mode}).eq("id",b["id"]).execute()
        return {"success":True,"mode":req.mode,"applied_to":"all_running_bots"}
    except Exception as e: raise HTTPException(500, str(e))

@router.get("/reinvest/{bot_id}/stats")
async def get_stats(bot_id: str):
    try:
        from services.reinvestment_engine_v9 import reinvest_engine
        return reinvest_engine.get_stats(bot_id)
    except Exception as e: raise HTTPException(500, str(e))

@router.get("/reinvest/{bot_id}/projections")
async def get_proj(bot_id: str, daily_pct: float = 5.0, days: int = 30):
    try:
        from services.reinvestment_engine_v9 import reinvest_engine
        return reinvest_engine.get_projections(bot_id, daily_pct, days)
    except Exception as e: raise HTTPException(500, str(e))
