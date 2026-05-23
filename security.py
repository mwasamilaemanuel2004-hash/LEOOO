"""api/routes/growth.py v10 — Annual/Monthly/Weekly/Daily growth"""
from fastapi import APIRouter, HTTPException
router = APIRouter()

@router.get("/growth/stats")
async def growth_stats():
    try:
        from ai.master_brain_v10 import master_brain_v10
        return master_brain_v10.get_growth()
    except Exception as e: raise HTTPException(500, str(e))

@router.get("/growth/condition-performance")
async def condition_perf():
    try:
        from ai.master_brain_v10 import master_brain_v10
        s = master_brain_v10.get_stats()
        return {"condition_wins":s["condition_wins"],"accuracy":s["accuracy"],"conditions":s["conditions"]}
    except Exception as e: raise HTTPException(500, str(e))

@router.get("/growth/trailing-stats")
async def trailing_stats():
    try:
        from ai.trailing_engine_v10 import trailing_engine
        from ai.profit_lock_v10 import profit_lock
        return {"trailing":trailing_engine.get_stats(),"profit_lock":profit_lock.get_stats()}
    except Exception as e: raise HTTPException(500, str(e))

@router.get("/growth/discipline/{bot_id}")
async def discipline_status(bot_id: str):
    try:
        from ai.discipline_engine import discipline_engine
        return discipline_engine.get_status(bot_id)
    except Exception as e: raise HTTPException(500, str(e))
