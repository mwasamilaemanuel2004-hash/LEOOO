"""api/routes/portfolio.py"""
from fastapi import APIRouter, HTTPException
router = APIRouter()

@router.get("/portfolio")
async def get_portfolio():
    try:
        from core.database import db
        if not db: return {"balance": 0, "total_profit": 0, "pnl_pct": 0, "total_trades": 0, "win_rate": 0}
        wallets = db.table("wallets").select("*").execute().data or []
        trades  = db.table("trades").select("pnl,pnl_pct,status").execute().data or []
        closed  = [t for t in trades if t.get("status") == "closed"]
        wins    = [t for t in closed if (t.get("pnl") or 0) > 0]
        return {
            "balance":      round(sum(w.get("balance", 0) for w in wallets), 2),
            "total_profit": round(sum(t.get("pnl", 0) for t in closed), 2),
            "pnl_pct":      round(sum(t.get("pnl_pct", 0) for t in closed[-20:]), 3),
            "total_trades": len(closed),
            "win_rate":     round(len(wins) / max(len(closed), 1) * 100, 1),
            "open_trades":  len([t for t in trades if t.get("status") == "open"]),
        }
    except Exception as e:
        raise HTTPException(500, str(e))

@router.get("/portfolio/full")
async def get_portfolio_full():
    try:
        from core.database import db
        if not db: return {}
        wallets   = db.table("wallets").select("*").execute().data or []
        bots      = db.table("bots").select("id,name,daily_pnl_pct,total_pnl,status").execute().data or []
        trades_r  = db.table("trades").select("*").order("created_at", desc=True).limit(100).execute().data or []
        return {"wallets": wallets, "bots": bots, "recent_trades": trades_r}
    except Exception as e:
        raise HTTPException(500, str(e))
