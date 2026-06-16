"""api/routes/maintenance.py"""
from fastapi import APIRouter, HTTPException
router = APIRouter()

@router.get("/maintenance/status")
async def maint_status():
    try:
        from core.database import db
        if not db: return {"global_maintenance": False}
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        r = db.table("maintenance_windows").select("*").eq("is_active", True).gte("ends_at", now).execute()
        windows = r.data or []
        return {
            "global_maintenance": len(windows) > 0,
            "windows": windows,
            "message": windows[0].get("message","") if windows else "",
        }
    except Exception as e:
        return {"global_maintenance": False, "error": str(e)}
