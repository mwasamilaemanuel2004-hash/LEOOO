"""api/routes/analytics.py — Complete analytics API"""
from fastapi import APIRouter, Query, HTTPException
from typing import Optional
router = APIRouter()

@router.get("/analytics/dashboard")
async def dashboard_stats():
    try:
        from core.database import db
        if not db: return {"demo":True,"total_pnl":4247,"win_rate":68.4,"sharpe":2.87}
        trades = db.table("trades").select("pnl,pnl_pct,status,direction,symbol,created_at").execute().data or []
        closed = [t for t in trades if t.get("status")=="closed"]
        wins   = [t for t in closed if (t.get("pnl") or 0)>0]
        import statistics as st
        pnls   = [t.get("pnl_pct",0) for t in closed]
        sharpe = 0.0
        if len(pnls) > 2:
            m = st.mean(pnls); s = st.stdev(pnls)+1e-9
            sharpe = m/s*(252**0.5)
        return {
            "total_trades": len(closed),
            "win_trades":   len(wins),
            "win_rate":     round(len(wins)/max(len(closed),1)*100,2),
            "total_pnl":    round(sum(t.get("pnl",0) for t in closed),2),
            "avg_pnl_pct":  round(st.mean(pnls) if pnls else 0,3),
            "sharpe":       round(sharpe,3),
            "open_trades":  len([t for t in trades if t.get("status")=="open"]),
        }
    except Exception as e: raise HTTPException(500,str(e))

@router.get("/analytics/pnl-history")
async def pnl_history(days: int = 30):
    try:
        from core.database import db
        from datetime import datetime, timezone, timedelta
        if not db: return {"data":[]}
        since = (datetime.now(timezone.utc)-timedelta(days=days)).isoformat()
        r = db.table("trades").select("pnl,pnl_pct,created_at,symbol,direction,status").gte("created_at",since).order("created_at",desc=False).execute()
        return {"data": r.data or [], "days": days}
    except Exception as e: raise HTTPException(500,str(e))

@router.get("/analytics/emotion-stats")
async def emotion_stats():
    try:
        from core.database import db
        if not db: return {"stats":[]}
        r = db.table("emotion_performance").select("*").execute()
        return {"stats": r.data or []}
    except Exception as e: raise HTTPException(500,str(e))

@router.get("/analytics/bot-performance")
async def bot_performance():
    try:
        from core.database import db
        if not db: return {"bots":[]}
        r = db.table("bots").select("id,name,bot_id,total_trades,win_trades,daily_pnl_pct,total_pnl,sharpe_ratio").execute()
        return {"bots": r.data or []}
    except Exception as e: raise HTTPException(500,str(e))

@router.get("/analytics/signal-accuracy")
async def signal_accuracy():
    try:
        from ai.signal_engine_v9 import signal_tracker
        return signal_tracker.get_accuracy()
    except Exception as e: raise HTTPException(500,str(e))
