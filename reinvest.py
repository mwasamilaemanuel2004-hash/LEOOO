"""api/routes/admin.py — Admin Control Panel"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from middleware.auth import require_admin
from core.database import db
from datetime import datetime, timezone

router = APIRouter()


class UserToggle(BaseModel):
    user_id: str
    trading_enabled: bool

class FeeConfig(BaseModel):
    fee_pct: float  # Must be between 0.0001 and 0.01

class TokenCreate(BaseModel):
    token_type: str  # free | discount | vip | trial
    discount_pct: float = 0
    duration_days: int = 30
    max_uses: int = 1
    notes: str = ""

class TokenAssign(BaseModel):
    user_id: str
    token_code: str

class TokenRevoke(BaseModel):
    user_id: str
    assignment_id: str
    reason: str = ""

class DepositConfirm(BaseModel):
    payment_id: str
    amount_usd: float

class WithdrawalApprove(BaseModel):
    payment_id: str

class WalletAdjust(BaseModel):
    user_id: str
    wallet_type: str
    amount: float
    reason: str


@router.get("/dashboard")
async def admin_dashboard(admin: dict = Depends(require_admin)):
    """Admin overview: users, trades, earnings, system health."""
    users_count = len(db.table("users").select("id").execute().data or [])
    active_bots = len(db.table("bots").select("id").eq("status", "running").execute().data or [])
    open_trades = len(db.table("trades").select("id").eq("status", "open").execute().data or [])

    # Platform earnings
    earnings = db.table("platform_wallet").select("*").eq("wallet_key", "main_earnings").single().execute().data
    total_earned = float((earnings or {}).get("total_earned", 0))

    # Pending payments
    pending_deposits = len(db.table("payment_requests").select("id")
                           .eq("direction", "deposit").eq("status", "pending").execute().data or [])
    pending_withdrawals = len(db.table("payment_requests").select("id")
                              .eq("direction", "withdrawal").eq("status", "pending").execute().data or [])

    # Today's trades
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    today_trades = db.table("trades").select("net_pnl, mode").gte("created_at", today).execute().data or []
    today_pnl = sum(float(t.get("net_pnl") or 0) for t in today_trades)

    return {
        "stats": {
            "total_users": users_count,
            "active_bots": active_bots,
            "open_trades": open_trades,
            "platform_earnings_usd": round(total_earned, 4),
            "pending_deposits": pending_deposits,
            "pending_withdrawals": pending_withdrawals,
            "today_trades": len(today_trades),
            "today_pnl": round(today_pnl, 4),
        }
    }


@router.get("/users")
async def list_users(admin: dict = Depends(require_admin)):
    users = db.table("users").select(
        "id, email, role, full_name, phone, is_active, trading_enabled, "
        "created_at, last_login_at, kyc_status"
    ).order("created_at", desc=True).execute().data or []
    return {"users": users}


@router.post("/users/toggle-trading")
async def toggle_user_trading(body: UserToggle, admin: dict = Depends(require_admin)):
    db.table("users").update({
        "trading_enabled": body.trading_enabled,
        "updated_at": datetime.now(timezone.utc).isoformat()
    }).eq("id", body.user_id).execute()

    await db.log_audit(body.user_id, admin["id"],
                       "trading_enabled" if body.trading_enabled else "trading_disabled",
                       "user", body.user_id,
                       new_vals={"trading_enabled": body.trading_enabled})
    return {"success": True}


@router.post("/bots/pause-all")
async def pause_all_bots(admin: dict = Depends(require_admin)):
    db.table("bots").update({
        "status": "paused",
        "updated_at": datetime.now(timezone.utc).isoformat()
    }).eq("status", "running").execute()

    await db.log_audit(None, admin["id"], "pause_all_bots", "system", "all")
    return {"success": True, "message": "All running bots paused"}


@router.post("/bots/resume-all")
async def resume_all_bots(admin: dict = Depends(require_admin)):
    db.table("bots").update({
        "status": "running",
        "updated_at": datetime.now(timezone.utc).isoformat()
    }).eq("status", "paused").execute()
    return {"success": True}


@router.post("/bots/force-close/{bot_id}")
async def force_close_bot(bot_id: str, admin: dict = Depends(require_admin)):
    from services.bot_service import bot_service
    bot = db.table("bots").select("*, user_id").eq("id", bot_id).single().execute().data
    if not bot:
        raise HTTPException(404, "Bot not found")
    await bot_service.stop_bot(bot_id, bot["user_id"], "admin_force_close")
    await db.log_audit(bot["user_id"], admin["id"], "force_close_bot", "bot", bot_id)
    return {"success": True}


@router.post("/tokens/create")
async def create_token(body: TokenCreate, admin: dict = Depends(require_admin)):
    if body.token_type not in ("free", "discount", "vip", "trial"):
        raise HTTPException(400, "Invalid token type")
    if body.discount_pct < 0 or body.discount_pct > 100:
        raise HTTPException(400, "Discount must be 0-100%")

    from datetime import timedelta
    token = db.table("monthly_tokens").insert({
        "token_type": body.token_type,
        "discount_pct": body.discount_pct,
        "duration_days": body.duration_days,
        "max_uses": body.max_uses,
        "notes": body.notes,
        "created_by": admin["id"],
        "valid_until": (datetime.now(timezone.utc) + timedelta(days=body.duration_days + 30)).isoformat(),
    }).execute()

    if not token.data:
        raise HTTPException(500, "Failed to create token")

    t = token.data[0]
    await db.log_audit(None, admin["id"], "token_created", "monthly_token", t["id"],
                       new_vals={"type": body.token_type, "discount": body.discount_pct})

    return {"token": t, "token_code": t["token_code"]}


@router.post("/tokens/assign")
async def assign_token(body: TokenAssign, admin: dict = Depends(require_admin)):
    token = (db.table("monthly_tokens")
             .select("*").eq("token_code", body.token_code)
             .eq("is_active", True).single().execute()).data
    if not token:
        raise HTTPException(404, "Token not found or inactive")

    if token["uses_count"] >= token["max_uses"]:
        raise HTTPException(409, "Token has reached maximum uses")

    from datetime import timedelta
    assignment = db.table("token_assignments").insert({
        "user_id": body.user_id,
        "token_id": token["id"],
        "assigned_by": admin["id"],
        "expires_at": (datetime.now(timezone.utc) + timedelta(days=token["duration_days"])).isoformat(),
    }).execute()

    db.table("monthly_tokens").update({
        "uses_count": token["uses_count"] + 1
    }).eq("id", token["id"]).execute()

    await db.log_audit(body.user_id, admin["id"], "token_assigned",
                       "token_assignment", assignment.data[0]["id"] if assignment.data else None,
                       new_vals={"token_code": body.token_code, "type": token["token_type"]})

    return {"success": True, "assignment": assignment.data[0] if assignment.data else {}}


@router.post("/tokens/revoke")
async def revoke_token(body: TokenRevoke, admin: dict = Depends(require_admin)):
    db.table("token_assignments").update({
        "is_active": False,
        "revoked_at": datetime.now(timezone.utc).isoformat(),
        "revoked_by": admin["id"],
        "revoke_reason": body.reason,
    }).eq("id", body.assignment_id).eq("user_id", body.user_id).execute()

    await db.log_audit(body.user_id, admin["id"], "token_revoked",
                       "token_assignment", body.assignment_id,
                       new_vals={"reason": body.reason})
    return {"success": True}


@router.get("/payments/pending")
async def pending_payments(admin: dict = Depends(require_admin)):
    deposits = (db.table("payment_requests")
                .select("*, users(email, full_name, phone)")
                .eq("status", "pending").eq("direction", "deposit")
                .order("created_at", desc=True).execute()).data or []
    withdrawals = (db.table("payment_requests")
                   .select("*, users(email, full_name, phone)")
                   .in_("status", ["pending", "processing"]).eq("direction", "withdrawal")
                   .order("created_at", desc=True).execute()).data or []
    return {"deposits": deposits, "withdrawals": withdrawals}


@router.post("/payments/confirm-deposit")
async def confirm_deposit(body: DepositConfirm, admin: dict = Depends(require_admin)):
    from services.wallet_service import wallet_service
    result = await wallet_service.process_deposit_confirmation(
        body.payment_id, body.amount_usd, admin["id"]
    )
    return result


@router.post("/payments/approve-withdrawal")
async def approve_withdrawal(body: WithdrawalApprove, admin: dict = Depends(require_admin)):
    from services.payment_service import payment_service
    result = await payment_service.process_withdrawal(body.payment_id, admin["id"])
    return result


@router.post("/wallets/adjust")
async def adjust_wallet(body: WalletAdjust, admin: dict = Depends(require_admin)):
    """Admin wallet adjustment (bonus, correction, etc.)"""
    if abs(body.amount) > 10000:
        raise HTTPException(400, "Single adjustment cannot exceed $10,000")

    wallet = await db.get_wallet(body.user_id, body.wallet_type)
    if not wallet:
        raise HTTPException(404, "Wallet not found")

    if body.amount > 0:
        from services.wallet_service import wallet_service
        await wallet_service.credit(body.user_id, body.wallet_type, body.amount,
                                    "adjustment", f"Admin adjustment: {body.reason}",
                                    ip="admin")
    else:
        from services.wallet_service import wallet_service
        await wallet_service.debit(body.user_id, body.wallet_type, abs(body.amount),
                                   f"Admin adjustment: {body.reason}", ip="admin")

    await db.log_audit(body.user_id, admin["id"], "wallet_adjusted",
                       "wallet", wallet["id"],
                       new_vals={"amount": body.amount, "reason": body.reason})
    return {"success": True}


@router.get("/earnings")
async def platform_earnings(admin: dict = Depends(require_admin)):
    wallets = db.table("platform_wallet").select("*").execute().data or []
    fee_summary = db.table("platform_fee_ledger").select("fee_type, net_fee").execute().data or []
    by_type = {}
    for f in fee_summary:
        t = f.get("fee_type", "other")
        by_type[t] = by_type.get(t, 0) + float(f.get("net_fee", 0))

    return {"platform_wallets": wallets, "fee_by_type": by_type}


@router.get("/audit-logs")
async def audit_logs(limit: int = 100, admin: dict = Depends(require_admin)):
    logs = (db.table("audit_logs")
            .select("*, users!audit_logs_user_id_fkey(email)")
            .order("created_at", desc=True).limit(limit).execute()).data or []
    return {"logs": logs}


@router.get("/system/config")
async def get_system_config(admin: dict = Depends(require_admin)):
    config = db.table("system_config").select("key, value, description").execute().data or []
    return {"config": config}


@router.post("/system/config/{key}")
async def update_config(key: str, value: str, admin: dict = Depends(require_admin)):
    protected_keys = ["trading_fee_pct"]  # Never allow frontend to change fee
    if key in protected_keys:
        raise HTTPException(403, "This setting is system-protected")

    db.table("system_config").update({
        "value": value,
        "updated_at": datetime.now(timezone.utc).isoformat()
    }).eq("key", key).execute()

    await db.log_audit(None, admin["id"], "config_updated", "system_config", key,
                       new_vals={"value": value})
    return {"success": True}


@router.post("/system/maintenance/{enabled}")
async def set_maintenance(enabled: bool, admin: dict = Depends(require_admin)):
    db.table("system_config").update({
        "value": str(enabled).lower()
    }).eq("key", "maintenance_mode").execute()
    return {"maintenance_mode": enabled}
