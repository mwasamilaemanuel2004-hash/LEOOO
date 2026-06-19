"""
api/routes/bots.py — Bot management API v8
"""
from __future__ import annotations
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import Optional
import structlog

log = structlog.get_logger("routes.bots")
router = APIRouter()

# ── Models ─────────────────────────────────────────────────────
class StartBotReq(BaseModel):
    exchange_conn_id: Optional[str] = None
    mt5_conn_id: Optional[str] = None

class TwoPctReq(BaseModel):
    enable: bool

class ProfitRangeReq(BaseModel):
    target_pct: float
    mode: str = "per_session"

class AIUpgradeReq(BaseModel):
    tier: str

class ReinvestReq(BaseModel):
    mode: str

class PairReq(BaseModel):
    pairs: list[str]

# ── Routes ─────────────────────────────────────────────────────
@router.get("/bots")
async def get_bots():
    try:
        from core.database   import db
        from core.bot_registry import BOT_REGISTRY, get_bot
        from ai.trading_loop_v8 import loop_controller, two_pct_engine
        from services.capital_maximizer import profit_range_engine

        result   = db.table("bots").select("*").execute() if db else None
        bots_db  = (result.data or []) if result else []

        enriched = []
        for b in bots_db:
            bid = b.get("bot_id", "")
            reg = get_bot(bid)
            ls  = loop_controller.get_bot_state(b.get("id", "")) or {}
            enriched.append({
                **b,
                "icon":        reg.get("icon", "🤖"),
                "color":       reg.get("color", "#6366f1"),
                "badge":       reg.get("badge", ""),
                "description": reg.get("description", ""),
                "special_feature": reg.get("special_feature", ""),
                "pairs_default":   reg.get("pairs_default", []),
                "timeframes":      reg.get("timeframes", []),
                "risk_profile":    reg.get("risk_profile", {}),
                "live_state":      ls,
                "two_pct_state":   two_pct_engine.get_state(b.get("id", "")),
            })

        if not enriched:
            enriched = [
                {
                    "id": k, "bot_id": k,
                    "name": v["name"], "icon": v["icon"], "color": v["color"],
                    "badge": v.get("badge",""), "category": v["category"],
                    "platform": v["platform"], "description": v.get("description",""),
                    "status": "stopped", "ai_tier": v["ai_tier_default"],
                    "pairs_default": v.get("pairs_default",[]),
                    "timeframes": v.get("timeframes",[]),
                    "risk_profile": v.get("risk_profile",{}),
                    "special_feature": v.get("special_feature",""),
                    "ribbon": v.get("ribbon",""),
                    "two_pct_mode": False, "profit_range_target": 0,
                    "daily_pnl_pct": 0, "total_trades": 0, "win_trades": 0,
                    "allocated_capital": 1000,
                }
                for k, v in BOT_REGISTRY.items()
            ]

        return {"bots": enriched, "total": len(enriched)}
    except Exception as e:
        log.error("get_bots", error=str(e))
        raise HTTPException(500, str(e))


@router.post("/bots/{bot_id}/start")
async def start_bot(bot_id: str, req: StartBotReq = StartBotReq()):
    try:
        from core.database      import db
        from ai.trading_loop_v8 import loop_controller
        result = db.table("bots").select("*").eq("id", bot_id).maybe_single().execute() if db else None
        bot    = (result.data or {}) if result else {}
        if req.exchange_conn_id: bot["exchange_conn_id"] = req.exchange_conn_id
        if req.mt5_conn_id:      bot["mt5_conn_id"]      = req.mt5_conn_id
        r = await loop_controller.start_bot(bot)
        return r
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/bots/{bot_id}/stop")
async def stop_bot(bot_id: str):
    try:
        from ai.trading_loop_v8 import loop_controller
        return await loop_controller.stop_bot(bot_id, "manual")
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/bots/{bot_id}/two-pct-mode")
async def toggle_two_pct(bot_id: str, req: TwoPctReq):
    try:
        from ai.trading_loop_v8 import loop_controller
        return await loop_controller.toggle_two_pct_mode(bot_id, req.enable)
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/bots/{bot_id}/profit-range")
async def set_profit_range(bot_id: str, req: ProfitRangeReq):
    try:
        from ai.trading_loop_v8 import loop_controller
        return await loop_controller.set_profit_range(bot_id, req.target_pct, req.mode)
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/bots/{bot_id}/upgrade-ai")
async def upgrade_ai(bot_id: str, req: AIUpgradeReq):
    try:
        from core.database import db
        if req.tier not in ("silver", "gold", "platinum"):
            raise HTTPException(400, "Invalid tier")
        if db: db.table("bots").update({"ai_tier": req.tier}).eq("id", bot_id).execute()
        return {"success": True, "ai_tier": req.tier}
    except HTTPException: raise
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/bots/{bot_id}/reinvest")
async def set_reinvest(bot_id: str, req: ReinvestReq):
    try:
        from core.database import db
        from services.reinvestment_engine import reinvestment_engine
        reinvestment_engine.set_mode(bot_id, req.mode)
        if db: db.table("bots").update({"reinvest_mode": req.mode}).eq("id", bot_id).execute()
        return {"success": True, "mode": req.mode}
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/bots/{bot_id}/state")
async def get_bot_state(bot_id: str):
    try:
        from ai.trading_loop_v8 import loop_controller
        s = loop_controller.get_bot_state(bot_id)
        return s or {"not_running": True}
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/bots/{bot_id}/emergency-stop")
async def emergency_stop(bot_id: str):
    try:
        from ai.trading_loop_v8 import loop_controller
        await loop_controller.stop_bot(bot_id, "emergency")
        return {"success": True, "halted": True}
    except Exception as e:
        raise HTTPException(500, str(e))
