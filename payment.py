"""api/routes/timeframes.py v10"""
from fastapi import APIRouter,HTTPException
router = APIRouter()

@router.get("/timeframes/configs")
async def get_configs():
    try:
        from strategies.timeframe_profit_engine import get_all_configs
        return get_all_configs()
    except Exception as e:raise HTTPException(500,str(e))

@router.get("/timeframes/strategy")
async def get_strategy(tf:str="5m",profit:str="5pct",symbol:str="BTCUSDT"):
    try:
        from strategies.timeframe_profit_engine import get_timeframe_strategy
        return get_timeframe_strategy(tf,profit,symbol)
    except Exception as e:raise HTTPException(500,str(e))

@router.post("/timeframes/{bot_id}/apply")
async def apply_to_bot(bot_id:str,tf:str="5m",profit:str="5pct"):
    try:
        from core.database import db
        from strategies.timeframe_profit_engine import get_timeframe_strategy
        cfg=get_timeframe_strategy(tf,profit)
        if db:
            db.table("bots").update({
                "active_timeframe":tf,"active_profit_profile":profit,
                "profit_range_target":cfg["profit_target_pct"],
                "capital_pct":cfg["capital_pct"],
            }).eq("id",bot_id).execute()
        return {"success":True,"bot_id":bot_id,"config":cfg}
    except Exception as e:raise HTTPException(500,str(e))
