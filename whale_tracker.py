"""
ai/analyst.py — ESTRADE v6 AI Analyst System
══════════════════════════════════════════════════════════════════════════
Visible to users: explains WHY every trade happened in plain language.

The AI Analyst:
1. Reads trade data + explainability dict from the trade engine
2. Generates human-readable analysis in 3 sections:
   - Why the trade was taken (signal reasoning)
   - Risk assessment (what could go wrong)
   - Expected outcome (profit probability + scenarios)
3. Detects anomalies (abnormal losses, suspicious withdrawals)
4. Alerts user + admin on security events
5. Tracks analyst performance over time

Security & Protection:
- Monitors consecutive losses → freezes bot if threshold hit
- Detects rapid withdrawals → alerts admin
- Spots unusual trade frequency → rate-limits bot
══════════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, asdict
from typing import Optional
import structlog

from core.database import db

log = structlog.get_logger("analyst")


# ── Trade Analysis Output ─────────────────────────────────────

@dataclass
class TradeAnalysis:
    trade_id:         str
    bot_id:           str
    symbol:           str
    action:           str
    # Why it was taken
    primary_signal:   str
    signal_sources:   list     # list of indicator names that fired
    ai_confidence:    float
    ai_tier:          str
    regime:           str
    strategy:         str
    # Risk
    risk_level:       str      # LOW | MEDIUM | HIGH | CRITICAL
    risk_factors:     list     # list of risk warning strings
    max_loss_usd:     float
    sl_distance_pct:  float
    # Expected outcome
    win_probability:  float    # 0-100
    expected_profit:  float
    expected_loss:    float
    rr_ratio:         float
    scenarios:        dict     # bull, bear, base
    # Narrative
    headline:         str      # one-line summary
    reasoning:        str      # 2-3 sentence explanation
    recommendation:   str      # what user should do
    # Metadata
    top_features:     dict     # SHAP-proxy contributions
    timestamp:        str

    def to_dict(self) -> dict:
        return asdict(self)

    def to_display(self) -> dict:
        """Formatted version for frontend display."""
        col = {"LOW":"#22c55e","MEDIUM":"#f59e0b","HIGH":"#f97316","CRITICAL":"#ef4444"}
        return {
            "headline":     self.headline,
            "reasoning":    self.reasoning,
            "recommendation": self.recommendation,
            "risk": {
                "level":  self.risk_level,
                "color":  col.get(self.risk_level,"#94a3b8"),
                "factors": self.risk_factors,
                "max_loss": f"${self.max_loss_usd:.4f}",
                "sl_dist":  f"{self.sl_distance_pct:.2f}%",
            },
            "confidence": {
                "value": round(self.ai_confidence, 1),
                "tier":  self.ai_tier,
                "signals": self.signal_sources,
            },
            "outcome": {
                "win_probability": round(self.win_probability, 1),
                "expected_profit": f"+${self.expected_profit:.4f}",
                "expected_loss":   f"-${self.expected_loss:.4f}",
                "rr_ratio":        f"{self.rr_ratio:.2f}:1",
                "scenarios":       self.scenarios,
            },
            "strategy":  self.strategy,
            "regime":    self.regime,
            "timestamp": self.timestamp,
            "top_features": self.top_features,
        }


class AIAnalyst:
    """
    Analyzes every trade and produces human-readable explanations.
    Also monitors for security events and anomalies.
    """

    # ── Trade analysis ────────────────────────────────────────

    def analyze_trade(
        self,
        trade: dict,
        signal: dict,
        bot_config: dict,
        balance: float = 1000.0,
    ) -> TradeAnalysis:
        """
        Generate full trade analysis from signal data.
        Called immediately after a trade opens.
        """
        action       = trade.get("side","long").upper()
        symbol       = trade.get("symbol","")
        entry        = float(trade.get("entry_price",0))
        sl           = float(trade.get("stop_loss",0))
        tp           = float(trade.get("take_profit",0))
        qty          = float(trade.get("quantity",0))
        ai_conf      = float(signal.get("confidence",0))
        regime       = signal.get("regime","unknown")
        strategy     = signal.get("strategy","unknown")
        ml_score     = float(signal.get("ml_score",0))
        rule_conf    = float(signal.get("rule_conf",0))
        expl         = signal.get("explainability",{}) or {}
        mode         = bot_config.get("ai_tier_default","silver")

        # Signal sources (which indicators fired)
        sources      = self._get_signal_sources(signal, expl)

        # Risk assessment
        sl_dist      = abs(entry - sl) / (entry + 1e-9) * 100 if sl else 2.0
        max_loss     = qty * abs(entry - sl) if sl else qty * entry * 0.02
        tp_dist      = abs(tp - entry) / (entry + 1e-9) * 100 if tp else 4.0
        rr           = tp_dist / (sl_dist + 1e-9)
        risk_level   = self._assess_risk(ai_conf, sl_dist, rr, regime)
        risk_factors = self._risk_factors(ai_conf, sl_dist, rr, regime, signal)

        # Win probability from conf + RR
        base_win_p   = min(90, ai_conf * 0.7 + rr * 5)
        win_prob     = round(base_win_p, 1)

        # Scenarios
        d = 1 if action in ("BUY","LONG") else -1
        atr = entry * 0.02
        scenarios = {
            "bull":  {"price": round(entry + d*atr*5,4), "pnl": f"+${qty*atr*5:.2f}"},
            "base":  {"price": round(entry + d*atr*2,4), "pnl": f"+${qty*atr*2:.2f}"},
            "bear":  {"price": round(entry - d*atr*1.5,4), "pnl": f"-${qty*atr*1.5:.2f}"},
        }

        # SHAP-proxy top features
        ml_block    = expl.get("ml",{}) or {}
        contribs    = ml_block.get("contributions",{}) or {}
        top_feats   = dict(sorted(contribs.items(), key=lambda x:x[1], reverse=True)[:5]) if contribs else {}
        top_feature = ml_block.get("top_feature","") or signal.get("reason","")

        # Headline
        direction_word = "LONG" if action in ("BUY","LONG") else "SHORT"
        headline = (
            f"{direction_word} {symbol} | "
            f"{strategy.replace('_',' ').title()} signal | "
            f"AI: {ai_conf:.0f}% ({mode.upper()}) | "
            f"RR: {rr:.1f}:1"
        )

        # Reasoning (plain language)
        regime_desc = {
            "trending":"The market is in a clear trend","ranging":"The market is in a range",
            "volatile":"High volatility detected","strong_uptrend":"Strong bullish momentum",
            "strong_downtrend":"Strong bearish momentum","oversold":"Price is oversold",
            "overbought":"Price is overbought","consolidating_pre_breakout":"Consolidation before breakout",
        }.get(regime,"The market conditions are")

        strategy_desc = {
            "trend":"trend-following indicators aligned",
            "mean_reversion":"mean-reversion signals triggered",
            "breakout":"price broke out of a key level with volume",
            "scalp":"short-term momentum burst detected",
            "ema_scalp":"EMA micro-cross with volume confirmation",
            "breakout_whale":"breakout confirmed by whale activity",
            "order_flow_imbalance":"order-flow shows buying pressure",
            "beta_ultra_scalp":"all 8 BETA conditions satisfied",
            "gramma_corr_hedge":"correlation divergence detected",
            "news_volatility":"high-impact news event detected",
            "swing_ichimoku":"Ichimoku cloud + MACD divergence aligned",
        }.get(strategy, f"{strategy} conditions met")

        sources_str = ", ".join(sources[:4]) if sources else "multiple indicators"
        reasoning = (
            f"{regime_desc}. {strategy_desc.capitalize()}. "
            f"Confirmation from: {sources_str}. "
            f"AI ensemble confidence: {ai_conf:.0f}% "
            f"(rule: {rule_conf:.0f}%, ML: {ml_score*100:.0f}%)."
        )

        # Recommendation
        if risk_level == "CRITICAL":
            rec = "⚠️ CRITICAL RISK: Consider reducing position size or skipping this trade."
        elif risk_level == "HIGH":
            rec = "Manage this position carefully. Monitor SL closely."
        elif win_prob > 70:
            rec = f"High-quality setup. Target: ${qty*atr*2:.2f} profit at TP."
        else:
            rec = f"Moderate setup. Stick to your SL at ${sl:.4f}."

        now = datetime.now(timezone.utc).isoformat()

        return TradeAnalysis(
            trade_id=trade.get("id",""),
            bot_id=bot_config.get("id",""),
            symbol=symbol,
            action=action,
            primary_signal=signal.get("reason",""),
            signal_sources=sources,
            ai_confidence=ai_conf,
            ai_tier=mode,
            regime=regime,
            strategy=strategy,
            risk_level=risk_level,
            risk_factors=risk_factors,
            max_loss_usd=round(max_loss,4),
            sl_distance_pct=round(sl_dist,3),
            win_probability=win_prob,
            expected_profit=round(qty*atr*2,4),
            expected_loss=round(max_loss,4),
            rr_ratio=round(rr,2),
            scenarios=scenarios,
            headline=headline,
            reasoning=reasoning,
            recommendation=rec,
            top_features=top_feats,
            timestamp=now,
        )

    def _get_signal_sources(self, signal: dict, expl: dict) -> list:
        """Extract which indicators triggered the signal."""
        sources = []
        rule = expl.get("rule",{}) or {}
        ml   = expl.get("ml",{})   or {}
        reg  = expl.get("regime",{}) or {}

        strat = signal.get("strategy","")
        if "ema" in strat:           sources.append("EMA Cross")
        if "rsi" in str(signal):     sources.append("RSI")
        if "macd" in str(signal):    sources.append("MACD")
        if "breakout" in strat:      sources.append("Breakout")
        if "whale" in strat:         sources.append("Whale Tracker")
        if "order_flow" in strat:    sources.append("Order Flow")
        if "vol_burst" in strat:     sources.append("BB Squeeze")
        if "ichimoku" in strat:      sources.append("Ichimoku")
        if "fibonacci" in strat:     sources.append("Fibonacci")
        if "news" in strat:          sources.append("News Sentiment")
        if ml.get("ml_enabled"):     sources.append("ML Model")
        if ml.get("dl_enabled"):     sources.append("DL Model")
        if reg.get("regime"):        sources.append(f"Regime:{reg['regime']}")

        top = ml.get("top_feature","")
        if top and top not in " ".join(sources):
            sources.append(f"Feature:{top}")

        return sources[:6] if sources else ["Rule-Based AI"]

    def _assess_risk(self, conf: float, sl_dist: float, rr: float, regime: str) -> str:
        score = 0
        if conf < 60:    score += 3
        elif conf < 70:  score += 1
        if sl_dist > 5:  score += 2
        elif sl_dist > 3:score += 1
        if rr < 1.5:     score += 2
        elif rr < 2.0:   score += 1
        if regime in ("volatile","unknown"): score += 1

        if score >= 5:   return "CRITICAL"
        elif score >= 3: return "HIGH"
        elif score >= 1: return "MEDIUM"
        return "LOW"

    def _risk_factors(self, conf,sl_dist,rr,regime,signal) -> list:
        factors = []
        if conf < 65:      factors.append(f"Low AI confidence ({conf:.0f}%)")
        if sl_dist > 4:    factors.append(f"Wide stop-loss ({sl_dist:.1f}% from entry)")
        if rr < 1.5:       factors.append(f"Low risk-reward ratio ({rr:.2f}:1)")
        if regime=="volatile": factors.append("High market volatility")
        if regime=="unknown":  factors.append("Market regime uncertain")
        vol_r = signal.get("vol_ratio",1)
        if isinstance(vol_r,float) and vol_r < 0.8: factors.append("Below-average volume")
        return factors

    # ── Save to DB ────────────────────────────────────────────

    async def save_analysis(self, analysis: TradeAnalysis) -> None:
        """Persist trade analysis to DB for user viewing."""
        try:
            db.table("trade_analyses").upsert({
                "trade_id":       analysis.trade_id,
                "bot_id":         analysis.bot_id,
                "headline":       analysis.headline,
                "reasoning":      analysis.reasoning,
                "recommendation": analysis.recommendation,
                "risk_level":     analysis.risk_level,
                "risk_factors":   analysis.risk_factors,
                "signal_sources": analysis.signal_sources,
                "ai_confidence":  analysis.ai_confidence,
                "ai_tier":        analysis.ai_tier,
                "win_probability":analysis.win_probability,
                "rr_ratio":       analysis.rr_ratio,
                "scenarios":      analysis.scenarios,
                "top_features":   analysis.top_features,
                "full_analysis":  analysis.to_dict(),
                "created_at":     analysis.timestamp,
            }).execute()
        except Exception as e:
            log.error("analysis_save_error", error=str(e))

    async def get_analysis(self, trade_id: str) -> Optional[dict]:
        """Retrieve analysis for a specific trade."""
        try:
            row = (db.table("trade_analyses").select("*")
                   .eq("trade_id",trade_id).single().execute()).data
            return row
        except Exception:
            return None

    # ── Security Monitor ──────────────────────────────────────

    async def security_check(self, user_id: str, bot_id: str) -> dict:
        """
        Run security + anomaly detection checks.
        Returns threats and recommended actions.
        """
        alerts    = []
        actions   = []
        severity  = "OK"
        now       = datetime.now(timezone.utc)

        # 1. Consecutive losses
        recent = (db.table("trades").select("net_pnl,closed_at")
                  .eq("user_id",user_id).eq("bot_id",bot_id)
                  .eq("status","closed").order("closed_at",desc=True)
                  .limit(10).execute()).data or []
        losses = 0
        for t in recent:
            if float(t.get("net_pnl",0)) < 0: losses += 1
            else: break
        if losses >= 5:
            alerts.append(f"🔴 {losses} consecutive losses detected")
            actions.append("FREEZE_BOT")
            severity = "HIGH"
        elif losses >= 3:
            alerts.append(f"🟡 {losses} consecutive losses — monitor closely")
            severity = "MEDIUM"

        # 2. Abnormal withdrawal velocity
        hour_ago = (now-timedelta(hours=1)).isoformat()
        recent_wd = (db.table("payment_requests").select("amount_usd","created_at")
                     .eq("user_id",user_id).eq("direction","withdrawal")
                     .gte("created_at",hour_ago).execute()).data or []
        wd_total = sum(float(r.get("amount_usd",0)) for r in recent_wd)
        if len(recent_wd) >= 3 or wd_total > 5000:
            alerts.append(f"⚠️ Unusual withdrawals: {len(recent_wd)} txns, ${wd_total:.2f} in 1hr")
            actions.append("ALERT_ADMIN")
            severity = "HIGH"

        # 3. Daily loss > 10%
        today      = now.date().isoformat()
        today_pnl  = (db.table("trades").select("net_pnl")
                      .eq("user_id",user_id).eq("status","closed")
                      .gte("closed_at",today).execute()).data or []
        day_loss   = sum(float(t.get("net_pnl",0)) for t in today_pnl)
        wallet     = (db.table("wallets").select("balance")
                      .eq("user_id",user_id).eq("wallet_type","trading")
                      .eq("mode","live").single().execute()).data
        balance    = float(wallet["balance"]) if wallet else 1000
        if balance > 0 and abs(min(0,day_loss))/balance > 0.10:
            alerts.append(f"🔴 Daily loss exceeds 10%: ${abs(day_loss):.2f}")
            actions.append("FREEZE_ALL_BOTS")
            severity = "CRITICAL"

        # 4. Trade frequency anomaly
        min_ago5 = (now-timedelta(minutes=5)).isoformat()
        rapid = (db.table("trades").select("id",count="exact")
                 .eq("user_id",user_id).eq("bot_id",bot_id)
                 .gte("opened_at",min_ago5).execute()).count or 0
        if rapid >= 10:
            alerts.append(f"⚡ High frequency: {rapid} trades in 5 minutes")
            actions.append("RATE_LIMIT_BOT")
            if severity == "OK": severity = "MEDIUM"

        # Execute actions
        if "FREEZE_BOT" in actions:
            try:
                db.table("bots").update({"is_frozen":True,"freeze_reason":"AI analyst: consecutive losses"
                    }).eq("id",bot_id).execute()
            except Exception: pass

        if "FREEZE_ALL_BOTS" in actions or "ALERT_ADMIN" in actions:
            try:
                db.table("security_alerts").insert({
                    "user_id":user_id,"bot_id":bot_id,
                    "severity":severity,"alerts":alerts,"actions":actions,
                    "created_at":now.isoformat(),
                }).execute()
            except Exception: pass

        if alerts:
            log.warning("security_alert", user=user_id, bot=bot_id,
                        severity=severity, alerts=alerts)

        return {
            "status":   severity,
            "alerts":   alerts,
            "actions":  actions,
            "checked_at": now.isoformat(),
        }

    # ── Analyst Summary (dashboard panel) ─────────────────────

    async def get_analyst_panel(self, user_id: str,
                                  limit: int = 10) -> dict:
        """
        Returns the AI Analyst panel data for the frontend dashboard.
        Shows last N trade analyses + security status.
        """
        try:
            analyses = (db.table("trade_analyses")
                        .select("headline,reasoning,risk_level,win_probability,ai_confidence,created_at,bot_id")
                        .eq("user_id",user_id)
                        .order("created_at",desc=True)
                        .limit(limit).execute()).data or []
        except Exception:
            analyses = []

        # Overall stats
        try:
            all_trades = (db.table("trades").select("net_pnl,status")
                          .eq("user_id",user_id).eq("status","closed")
                          .limit(100).execute()).data or []
            wins    = sum(1 for t in all_trades if float(t.get("net_pnl",0)) > 0)
            total   = len(all_trades)
            avg_pnl = sum(float(t.get("net_pnl",0)) for t in all_trades) / (total or 1)
        except Exception:
            wins, total, avg_pnl = 0, 0, 0

        return {
            "recent_analyses":   analyses,
            "summary": {
                "total_analyzed": total,
                "win_rate":       round(wins/total*100 if total else 0, 1),
                "avg_pnl":        round(avg_pnl, 4),
                "analyst_grade":  "A" if wins/total > 0.65 else "B" if wins/total > 0.50 else "C" if total else "N/A",
            },
        }


# ── Singleton ────────────────────────────────────────────────
ai_analyst = AIAnalyst()
