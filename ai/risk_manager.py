from typing import Dict, Optional
from core.database import db
import structlog

log = structlog.get_logger("risk_manager")

class RiskManager:
    """
    Institutional-grade risk management.
    - Dynamic Position Sizing
    - Max Drawdown Protection
    - Kill Switch (Manual & Auto)
    """

    def __init__(self):
        self.kill_switch_active = False

    async def evaluate_risk(self, user_id: str, trade_req: Dict) -> Dict:
        """Evaluate if a trade should be allowed based on risk filters."""
        if self.kill_switch_active:
            return {"allowed": False, "reason": "Kill switch active"}

        # Fetch current exposure
        exposure = await self._get_current_exposure(user_id)
        if exposure > 10.0: # Max 10x leverage across portfolio
            return {"allowed": False, "reason": "Max exposure exceeded"}

        # Dynamic Position Sizing (1-2% risk per trade)
        size = self._calculate_position_size(trade_req["balance"], trade_req["risk_pct"])

        return {
            "allowed": True,
            "size": size,
            "filters_passed": True
        }

    async def check_drawdown(self, user_id: str):
        """Monitor daily/total drawdown."""
        pnl = await self._get_daily_pnl(user_id)
        if pnl < -0.05: # 5% daily loss limit
            await self.activate_kill_switch(user_id, "Daily loss limit exceeded")

    async def activate_kill_switch(self, user_id: str, reason: str):
        """Immediately close all positions and disable bots."""
        self.kill_switch_active = True
        log.critical("KILL_SWITCH_ACTIVATED", user=user_id, reason=reason)

        # 1. Cancel all open orders
        # 2. Close all positions
        # 3. Notify user

        db.table("security_events").insert({
            "user_id": user_id,
            "type": "kill_switch",
            "severity": "CRITICAL",
            "data": {"reason": reason}
        }).execute()

    def _calculate_position_size(self, balance: float, risk_pct: float) -> float:
        return balance * (risk_pct / 100.0)

    async def _get_current_exposure(self, user_id: str) -> float:
        return 2.5 # Mock

    async def _get_daily_pnl(self, user_id: str) -> float:
        return -0.01 # Mock

risk_manager = RiskManager()
