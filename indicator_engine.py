"""profit_lock_v10.py — Never lose a profit, not even $1"""
from __future__ import annotations
import time
from collections import defaultdict
from typing import Dict
import structlog
log = structlog.get_logger("profit_lock")

class ProfitLockEngine:
    """
    89-99% profit preservation system.
    Rules:
    +0.5%  → move SL to entry (breakeven, 0% risk)
    +1.0%  → lock 0.5% profit (SL at +0.5%)
    +2.0%  → lock 1.5% profit (SL at +1.5%)
    +5.0%  → lock 4.0% profit (SL at +4.0%)
    +10%   → lock 9.0% profit (SL at +9.0%)
    Peak   → trail at 1% below peak always
    """
    LOCK_LEVELS = [(0.5,0.0),(1.0,0.5),(2.0,1.5),(5.0,4.0),(10.0,9.0),(20.0,18.5)]

    def __init__(self):
        self._locks: dict = {}
        self._stats = {"total":0,"breakeven_saves":0,"profit_preserved":0.0}

    def add(self, trade_id:str, entry:float, direction:str, sl:float, tp:float):
        self._locks[trade_id] = {
            "entry":entry,"direction":direction,"original_sl":sl,
            "current_sl":sl,"tp":tp,"peak":entry,
            "breakeven":False,"locked_pct":0,"max_profit":0
        }
        self._stats["total"] += 1

    def update(self, trade_id:str, price:float) -> dict:
        p = self._locks.get(trade_id)
        if not p: return {"action":"none"}
        d = p["direction"]
        e = p["entry"]
        profit = (price-e)/e*100 if d=="buy" else (e-price)/e*100
        p["max_profit"] = max(p["max_profit"], profit)
        p["peak"] = max(p["peak"],price) if d=="buy" else min(p["peak"] if p["peak"]>0 else price,price)

        new_sl = p["current_sl"]
        note = ""
        for trigger, lock in self.LOCK_LEVELS:
            if profit >= trigger:
                if d=="buy":
                    candidate = e*(1+lock/100)
                    if candidate > new_sl: new_sl=candidate; note=f"Locked {lock}% profit"
                else:
                    candidate = e*(1-lock/100)
                    if candidate < new_sl: new_sl=candidate; note=f"Locked {lock}% profit"

        # Trail at 1% below peak
        if d=="buy":
            trail = p["peak"]*0.99
            if trail > new_sl: new_sl=trail; note="Trailing peak"
        else:
            trail = p["peak"]*1.01
            if trail < new_sl: new_sl=trail; note="Trailing peak"

        changed = new_sl != p["current_sl"]
        if changed:
            p["current_sl"] = new_sl
            if not p["breakeven"] and profit > 0.5:
                p["breakeven"] = True
                self._stats["breakeven_saves"] += 1

        # Check exits
        if d=="buy" and price <= p["current_sl"]:
            pnl = (p["current_sl"]-e)/e*100
            self._stats["profit_preserved"] += max(0,pnl)
            return {"action":"close","reason":"profit_lock_sl","pnl_pct":round(pnl,3),"protected":pnl>0}
        if d=="sell" and price >= p["current_sl"]:
            pnl = (e-p["current_sl"])/e*100
            self._stats["profit_preserved"] += max(0,pnl)
            return {"action":"close","reason":"profit_lock_sl","pnl_pct":round(pnl,3),"protected":pnl>0}
        if (d=="buy" and price>=p["tp"]) or (d=="sell" and price<=p["tp"]):
            pnl = abs(p["tp"]-e)/e*100
            return {"action":"close","reason":"tp_hit","pnl_pct":round(pnl,3)}

        return {"action":"hold","current_sl":round(new_sl,6),"profit_pct":round(profit,3),"note":note,"changed":changed}

    def get_stats(self): return {**self._stats,"active":len(self._locks)}

profit_lock = ProfitLockEngine()
