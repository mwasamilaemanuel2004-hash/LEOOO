"""services/notification_service.py — Notification service"""
from __future__ import annotations
import httpx, structlog
from core.config import settings

log = structlog.get_logger("notifications")

class NotificationService:
    async def send(self, user_id:str, event:str, title:str, body:str,
                   data:dict=None, is_urgent:bool=False):
        log.info("notification", user_id=user_id, event=event, title=title)
        try:
            from core.database import db
            db.table("notifications").insert({
                "user_id": user_id, "type": event,
                "title": title, "body": body,
                "data": data or {}, "is_urgent": is_urgent,
            }).execute()
        except Exception: pass

    async def send_admin_alert(self, title:str, body:str,
                               severity:str="medium", data:dict=None):
        log.warning("admin_alert", title=title, severity=severity)
        if settings.telegram_token and settings.telegram_chat_id:
            try:
                async with httpx.AsyncClient(timeout=10) as c:
                    await c.post(
                        f"https://api.telegram.org/bot{settings.telegram_token}/sendMessage",
                        json={"chat_id": settings.telegram_chat_id,
                              "text": f"🚨 *{title}*\n_{body}_",
                              "parse_mode": "Markdown"},
                    )
            except Exception: pass

    async def email_service(self):
        pass  # Add SendGrid/Resend integration here

notification_service = NotificationService()
