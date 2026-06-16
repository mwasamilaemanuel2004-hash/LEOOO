"""
services/token_service.py — Monthly Trading Token Service
Manages free/discount/VIP token lifecycle for trading fee overrides.
"""
from __future__ import annotations
from datetime import datetime, timezone, timedelta
from core.database import db
from core.config import settings
import structlog

log = structlog.get_logger("token_service")


class TokenService:

    async def get_active_token(self, user_id: str) -> dict | None:
        row = (db.table("token_assignments")
               .select("*, monthly_tokens(*)")
               .eq("user_id", user_id)
               .eq("is_active", True)
               .gt("expires_at", datetime.now(timezone.utc).isoformat())
               .single().execute()).data
        return row

    async def get_user_fee_rate(self, user_id: str) -> dict:
        """Returns effective fee rate for user — used server-side only."""
        base = settings.TRADING_FEE_PCT
        token = await self.get_active_token(user_id)
        if not token or not token.get("monthly_tokens"):
            return {"fee_pct": base, "discount_pct": 0, "token_type": None, "token_active": False}

        t = token["monthly_tokens"]
        token_type = t["token_type"]
        discount   = float(t.get("discount_pct") or 0)

        if token_type == "free":
            effective = 0.0
        elif token_type == "vip":
            effective = base * 0.25
        else:
            effective = base * (1 - discount / 100)

        return {
            "fee_pct": round(effective, 8),
            "discount_pct": discount,
            "token_type": token_type,
            "token_active": True,
            "expires_at": token.get("expires_at"),
        }

    async def check_token_expiry(self, user_id: str) -> bool:
        """Deactivate expired tokens. Called by trading loop."""
        expired = (db.table("token_assignments")
                   .select("id")
                   .eq("user_id", user_id)
                   .eq("is_active", True)
                   .lt("expires_at", datetime.now(timezone.utc).isoformat())
                   .execute()).data or []
        for t in expired:
            db.table("token_assignments").update({
                "is_active": False,
                "revoked_at": datetime.now(timezone.utc).isoformat(),
                "revoke_reason": "auto_expired",
            }).eq("id", t["id"]).execute()
            log.info("token_expired", assignment_id=t["id"], user=user_id)
        return len(expired) > 0

    async def get_all_tokens(self) -> list:
        return (db.table("monthly_tokens")
                .select("*").order("created_at", desc=True).execute()).data or []

    async def get_user_assignments(self, user_id: str) -> list:
        return (db.table("token_assignments")
                .select("*, monthly_tokens(*)")
                .eq("user_id", user_id)
                .order("activated_at", desc=True).execute()).data or []


token_service = TokenService()
