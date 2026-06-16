"""api/routes/risk.py"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
router = APIRouter()

@router.get("/risk/stats")
async def risk_stats():
    try:
        from ai.risk_ai_engine import risk_ai
        return risk_ai.get_stats()
    except Exception as e:
        raise HTTPException(500, str(e))

@router.get("/risk/heat-map")
async def heat_map():
    try:
        from ai.risk_ai_engine import risk_ai
        return risk_ai.heat_map.get_heat_map()
    except Exception as e:
        raise HTTPException(500, str(e))

@router.get("/risk/var")
async def get_var():
    try:
        from ai.risk_ai_engine import risk_ai
        return risk_ai.var_calc.monte_carlo_var()
    except Exception as e:
        raise HTTPException(500, str(e))

@router.get("/risk/circuits")
async def get_circuits():
    try:
        from ai.risk_ai_engine import risk_ai
        return risk_ai.breakers.get_status()
    except Exception as e:
        raise HTTPException(500, str(e))

@router.post("/risk/circuits/{circuit}/reset")
async def reset_circuit(circuit: str):
    try:
        from ai.risk_ai_engine import risk_ai
        risk_ai.breakers.manual_reset(circuit)
        return {"success": True, "circuit": circuit}
    except Exception as e:
        raise HTTPException(500, str(e))

@router.get("/risk/drawdown/{bot_id}")
async def get_drawdown(bot_id: str):
    try:
        from ai.risk_ai_engine import risk_ai
        s = risk_ai.defense.states.get(bot_id)
        if not s: return {"not_found": True}
        return {
            "dd_pct":     round(s.current_dd_pct, 2),
            "dd_level":   s.dd_level,
            "peak":       round(s.peak_balance, 2),
            "balance":    round(s.current_balance, 2),
            "daily_loss": round(s.daily_loss_pct, 2),
        }
    except Exception as e:
        raise HTTPException(500, str(e))
