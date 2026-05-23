"""
services/risk_service.py — Enterprise Risk Management
Evaluates fortress levels, enforces limits, emergency stops.
"""
from __future__ import annotations
from datetime import datetime, timezone
from core.database import db
import structlog

log = structlog.get_logger("risk_service")

FORTRESS_LEVELS = {
    "OPEN":      {"risk_mult": 1.00, "max_trades": 10, "allow_new": True},
    "CAUTION":   {"risk_mult": 0.75, "max_trades": 6,  "allow_new": True},
    "FORTRESS":  {"risk_mult": 0.40, "max_trades": 3,  "allow_new": True},
    "LOCKDOWN":  {"risk_mult": 0.10, "max_trades": 0,  "allow_new": False},
    "EMERGENCY": {"risk_mult": 0.00, "max_trades": 0,  "allow_new": False},
}


class RiskService:

    async def evaluate_fortress(self, user_id: str,
                                 balance: float, daily_pnl: float,
                                 open_trades: int) -> dict:
        risk = await db.get_risk_profile(user_id)
        if not risk:
            return {"level": "OPEN", **FORTRESS_LEVELS["OPEN"]}

        peak = float(risk.get("peak_balance") or balance)
        if balance > peak:
            peak = balance
            db.table("risk_profiles").update({"peak_balance": peak}).eq("user_id", user_id).execute()

        consec        = int(risk.get("consecutive_losses") or 0)
        dd_from_peak  = (peak - balance) / peak * 100 if peak > 0 else 0
        daily_loss_pct = (-daily_pnl / max(balance, 1)) * 100 if daily_pnl < 0 else 0
        max_dd_cfg    = float(risk.get("max_drawdown_pct") or 10)
        daily_limit   = float(risk.get("daily_loss_limit") or 5)

        if dd_from_peak >= 15 or daily_loss_pct >= 15:
            level = "EMERGENCY"
        elif dd_from_peak >= max_dd_cfg or daily_loss_pct >= daily_limit or consec >= 8:
            level = "LOCKDOWN"
        elif dd_from_peak >= max_dd_cfg * 0.5 or daily_loss_pct >= daily_limit * 0.5 or consec >= 5:
            level = "FORTRESS"
        elif consec >= 3 or dd_from_peak >= max_dd_cfg * 0.25:
            level = "CAUTION"
        else:
            level = "OPEN"

        if level != risk.get("fortress_level"):
            db.table("risk_profiles").update({
                "fortress_level": level, "daily_pnl": daily_pnl,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }).eq("user_id", user_id).execute()

        return {
            "level": level,
            "dd_from_peak_pct": round(dd_from_peak, 2),
            "daily_loss_pct": round(daily_loss_pct, 2),
            "consecutive_losses": consec,
            **FORTRESS_LEVELS[level],
        }

    async def emergency_stop_all(self, user_id: str) -> dict:
        db.table("bots").update({
            "status": "stopped",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }).eq("user_id", user_id).in_("status", ["running", "paused"]).execute()
        db.table("risk_profiles").update({
            "emergency_stop": True, "fortress_level": "EMERGENCY",
        }).eq("user_id", user_id).execute()
        return {"stopped": True}

    async def reset_fortress(self, user_id: str, admin_id: str) -> dict:
        db.table("risk_profiles").update({
            "fortress_level": "OPEN", "consecutive_losses": 0,
            "emergency_stop": False, "daily_pnl": 0,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }).eq("user_id", user_id).execute()
        await db.log_audit(user_id, admin_id, "fortress_reset", "risk_profile", user_id)
        return {"success": True, "level": "OPEN"}


risk_service = RiskService()
