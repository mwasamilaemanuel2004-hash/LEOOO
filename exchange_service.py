"""api/routes/security.py — Security dashboard"""
from fastapi import APIRouter, Request, HTTPException
from datetime import datetime, timezone, timedelta
router = APIRouter()

@router.get("/security/dashboard")
async def security_dashboard():
    try:
        from core.database import db
        if not db: return {"status":"SECURE","threat_level":"LOW"}
        now = datetime.now(timezone.utc)
        since = (now - timedelta(hours=24)).isoformat()
        events = db.table("security_events").select("*").gte("created_at", since).order("created_at", desc=True).limit(100).execute().data or []
        high = [e for e in events if e.get("severity") in ("HIGH","CRITICAL")]
        return {
            "status": "CRITICAL" if len(high)>5 else "WARNING" if len(high)>0 else "SECURE",
            "threat_level": "HIGH" if len(high)>5 else "MEDIUM" if len(high)>0 else "LOW",
            "failed_logins_24h": len([e for e in events if e.get("type")=="failed_login"]),
            "suspicious_ips": list(set(e.get("ip") for e in events if e.get("type")=="suspicious_ip" and e.get("ip"))),
            "api_calls_today": len(events),
            "recent_events": events[:10],
            "two_fa_users": 0,
            "last_audit_at": now.isoformat(),
        }
    except Exception as e:
        raise HTTPException(500, str(e))

@router.post("/security/event")
async def log_event(request: Request):
    try:
        from core.database import db
        body = await request.json()
        if db:
            db.table("security_events").insert({
                "type":     body.get("type","unknown"),
                "severity": body.get("severity","LOW"),
                "ip":       request.client.host if request.client else None,
                "data":     body.get("data",{}),
            }).execute()
        return {"logged": True}
    except Exception as e:
        raise HTTPException(500, str(e))
