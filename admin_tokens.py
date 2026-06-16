"""api/routes/trades.py"""
from fastapi import APIRouter, Query, HTTPException
from typing import Optional

router = APIRouter()

@router.get("/trades")
async def get_trades(limit: int = Query(50, ge=1, le=200), status: str = "all", pair: Optional[str] = None):
    try:
        from core.database import db
        if not db: return {"trades": [], "total": 0}
        q = db.table("trades").select("*")
        if status != "all": q = q.eq("status", status)
        if pair: q = q.eq("symbol", pair)
        r = q.order("created_at", desc=True).limit(limit).execute()
        return {"trades": r.data or [], "total": len(r.data or [])}
    except Exception as e:
        raise HTTPException(500, str(e))

@router.get("/trades/live")
async def get_live_trades():
    try:
        from core.database import db
        if not db: return {"trades": []}
        r = db.table("trades").select("*").eq("status", "open").execute()
        return {"trades": r.data or []}
    except Exception as e:
        raise HTTPException(500, str(e))

@router.get("/trades/stats")
async def get_trade_stats():
    try:
        from core.database import db
        if not db: return {}
        r = db.table("trades").select("pnl,pnl_pct,status,direction,symbol").execute()
        trades = r.data or []
        closed = [t for t in trades if t.get("status") == "closed"]
        wins   = [t for t in closed if (t.get("pnl") or 0) > 0]
        pnls   = [t.get("pnl_pct", 0) for t in closed]
        import statistics
        return {
            "total":         len(closed),
            "wins":          len(wins),
            "losses":        len(closed) - len(wins),
            "win_rate":      round(len(wins) / max(len(closed), 1) * 100, 1),
            "avg_pnl_pct":   round(statistics.mean(pnls), 3) if pnls else 0,
            "total_pnl":     round(sum(t.get("pnl", 0) for t in closed), 2),
        }
    except Exception as e:
        raise HTTPException(500, str(e))
