"""api/routes/money_print.py — Money Printing Analytics API"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
router = APIRouter()

class PrintConfigReq(BaseModel):
    bot_key:         str
    capital_pct:     float = 50.0
    compound_ratio:  float = 1.0
    pyramid_enabled: bool  = True
    daily_target:    float = 5.0

@router.get("/money-print/projections")
async def get_projections():
    """Get all 43 bot daily profit projections."""
    try:
        from core.database import db
        if db:
            r = db.table("daily_projections").select("*").order("base_daily_pct", desc=True).execute()
            rows = r.data or []
        else:
            rows = []

        # Also compute totals from strategy module
        from strategies.money_printer_v8 import get_all_projections
        calcs = get_all_projections(10000)
        totals = next((c for c in calcs if c.get("bot_id") == "TOTAL_ALL_BOTS"), {})

        return {
            "projections":     rows,
            "calculated":      calcs[:43],
            "totals_at_10k":   totals,
            "compound_view_url": "/api/money-print/compound-sim",
        }
    except Exception as e:
        raise HTTPException(500, str(e))

@router.get("/money-print/compound-sim")
async def compound_simulation(start: float = 10000.0, days: int = 30, daily_pct: float = 5.0):
    """Simulate compound growth over N days."""
    try:
        result = []
        balance = start
        for day in range(1, days + 1):
            profit  = balance * daily_pct / 100
            balance += profit
            result.append({
                "day":         day,
                "balance":     round(balance, 2),
                "profit":      round(profit, 2),
                "total_profit":round(balance - start, 2),
                "multiplier":  round(balance / start, 3),
            })
        return {
            "start":          start,
            "daily_pct":      daily_pct,
            "days":           days,
            "final_balance":  round(balance, 2),
            "total_profit":   round(balance - start, 2),
            "multiplier":     round(balance / start, 3),
            "curve":          result,
        }
    except Exception as e:
        raise HTTPException(500, str(e))

@router.get("/money-print/live")
async def get_live_print_stats():
    """Get live compound pool and pyramid levels for all running bots."""
    try:
        from strategies.money_printer_v8 import money_printer, PRINT_CONFIGS
        stats = {}
        for bot_key in PRINT_CONFIGS:
            stats[bot_key] = money_printer.get_print_stats(bot_key)
        return {"bot_stats": stats, "total_bots": len(stats)}
    except Exception as e:
        raise HTTPException(500, str(e))

@router.get("/money-print/strategy/{bot_key}")
async def get_bot_print_strategy(bot_key: str):
    """Get full money printing strategy for a specific bot."""
    try:
        from strategies.money_printer_v8 import PRINT_CONFIGS, money_printer, get_all_projections
        config = PRINT_CONFIGS.get(bot_key)
        if not config:
            raise HTTPException(404, f"Bot {bot_key} not found")
        stats = money_printer.get_print_stats(bot_key)
        proj  = next((p for p in get_all_projections() if p.get("bot_id") == bot_key), {})
        from dataclasses import asdict
        return {
            "bot_key":   bot_key,
            "config":    asdict(config),
            "live_stats":stats,
            "projection":proj,
        }
    except HTTPException: raise
    except Exception as e:
        raise HTTPException(500, str(e))

@router.post("/money-print/execute/{bot_key}")
async def execute_print(bot_key: str, balance: float = 10000.0, confidence: float = 75.0):
    """Test money printing position calculation."""
    try:
        from strategies.money_printer_v8 import execute_money_print, money_printer
        signal = {"confidence": confidence, "drawdown_pct": 0, "type": "test"}
        result = execute_money_print(bot_key, signal, balance, money_printer)
        return result
    except Exception as e:
        raise HTTPException(500, str(e))
