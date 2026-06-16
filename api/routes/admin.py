"""api/routes/rl.py — Reinforcement Learning endpoints"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
router = APIRouter()

@router.get("/rl/stats")
async def rl_stats():
    try:
        from ai.reinforcement_engine import rl_engine
        return rl_engine.get_stats()
    except Exception as e:
        raise HTTPException(500, str(e))

@router.get("/rl/weights")
async def rl_weights():
    try:
        from ai.reinforcement_engine import rl_engine
        return {
            "ppo_weight": round(rl_engine.meta.ppo_weight, 3),
            "dqn_weight": round(rl_engine.meta.dqn_weight, 3),
            "dqn_epsilon": round(rl_engine.dqn.epsilon, 4),
            "ppo_updates": rl_engine.ppo.total_updates,
            "dqn_updates": rl_engine.dqn.total_updates,
            "regime_weights": rl_engine.meta.regime_weights,
        }
    except Exception as e:
        raise HTTPException(500, str(e))

@router.post("/rl/reset")
async def rl_reset():
    try:
        from ai.reinforcement_engine import RLEngine, rl_engine
        rl_engine.__init__()
        return {"success": True, "message": "RL engine reset"}
    except Exception as e:
        raise HTTPException(500, str(e))
