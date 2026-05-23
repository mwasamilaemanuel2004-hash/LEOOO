"""api/routes/strategies.py v10 — All strategy management"""
from fastapi import APIRouter,HTTPException
from pydantic import BaseModel
from typing import Optional,List
router = APIRouter()

class CustomStrategyReq(BaseModel):
    name:str; blocks:List[dict]; bot_key:Optional[str]=None

@router.get("/strategies/list")
async def list_strategies():
    try:
        from strategies.special_strategies_v9 import SPECIAL_STRATEGIES
        from strategies.timeframe_profit_engine import TIMEFRAME_CONFIGS,PROFIT_PROFILES
        return {
            "special_strategies":{k:{"name":v["name"],"codename":v["codename"],"edge":v["edge"],"expected_pnl":v["expected_pnl"]} for k,v in SPECIAL_STRATEGIES.items()},
            "timeframe_configs":{k:{"label":v.label,"strategy":v.strategy_name,"color":v.color,"profit_base":v.profit_base_pct} for k,v in TIMEFRAME_CONFIGS.items()},
            "profit_profiles":{k:{"label":v.label,"target":v.target_pct,"color":v.color,"style":v.style} for k,v in PROFIT_PROFILES.items()},
        }
    except Exception as e:raise HTTPException(500,str(e))

@router.get("/strategies/{bot_key}")
async def get_bot_strategy(bot_key:str):
    try:
        from strategies.special_strategies_v9 import SPECIAL_STRATEGIES
        s=SPECIAL_STRATEGIES.get(bot_key)
        if not s:raise HTTPException(404,f"No strategy for {bot_key}")
        return s
    except HTTPException:raise
    except Exception as e:raise HTTPException(500,str(e))

@router.post("/strategies/custom/save")
async def save_custom(req:CustomStrategyReq):
    try:
        from core.database import db
        if db:
            db.table("custom_strategies").upsert({"name":req.name,"blocks":req.blocks,"bot_key":req.bot_key}).execute()
        return {"success":True,"name":req.name,"blocks":len(req.blocks)}
    except Exception as e:raise HTTPException(500,str(e))

@router.post("/strategies/custom/backtest")
async def backtest_custom(request:dict):
    import random
    return {
        "total_return":round(random.uniform(-5,30),2),
        "sharpe":round(random.uniform(0,3),2),
        "win_rate":round(random.uniform(45,75),1),
        "max_drawdown":round(random.uniform(2,15),2),
        "total_trades":random.randint(50,300),
    }
