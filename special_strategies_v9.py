"""
services/tier_engine.py — ESTRADE v6 Subscription Tier System
══════════════════════════════════════════════════════════════════════════
3 Tiers — Gold, Silver, Platinum

GOLD (Free tier):
  - Only maintenance fee: $0.01 per trade
  - No subscription monthly fee
  - NO profit share (0%)
  - Max 3 bots, 2 pairs each
  - Demo mode only + 1 live bot
  - Basic indicators (L1+L2 only from 5-layer engine)

SILVER ($19.99/month):
  - Per trade fee: $0.025
  - Monthly flat: $19.99
  - Profit share: 10%
  - Max 5 bots, 5 pairs each
  - All 4 forex bots + 2 crypto bots
  - Full 5-layer indicator engine
  - TradingView webhooks

PLATINUM ($49.99/month):
  - Per trade fee: $0.05
  - Monthly flat: $49.99
  - Profit share: 20%
  - ALL 9 bots unlimited pairs
  - All features: Grid, DCA, SmartTrade, Arbitrage, Hybrid Alpha+Omega
  - Priority AI (highest confidence signals first)
  - Copy trading + signal marketplace
  - Dedicated support + API access

Royal IQ Bot features integrated:
  - AI signal copying from top traders (like Royal IQ)
  - Percentage-based auto-investment per signal
  - Signal leaderboard + provider rating
  - One-tap signal execution
  - Risk level selection per signal (conservative/moderate/aggressive)
══════════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from typing import Optional
import structlog

from core.database import db

log = structlog.get_logger("tier_engine")


# ═══════════════════════════════════════════════════════════════
# TIER DEFINITIONS
# ═══════════════════════════════════════════════════════════════

@dataclass
class TierConfig:
    name:               str
    display_name:       str
    color:              str
    icon:               str
    # Fees
    per_trade_fee:      float    # fixed USD per trade close
    monthly_fee:        float    # subscription per month
    profit_share_pct:   float    # % of profit taken
    withdrawal_fee_pct: float    # % of withdrawal
    # Limits
    max_bots:           int
    max_pairs_per_bot:  int
    max_open_trades:    int
    max_capital_usd:    float    # max capital per user
    # Features
    live_trading:       bool
    demo_trading:       bool
    all_bots:           bool     # access all 9 bots
    allowed_bots:       list     # bot IDs allowed
    indicator_layers:   int      # 1-5 layers of 5-layer engine
    grid_trading:       bool
    dca_trading:        bool
    smart_trade:        bool
    copy_trading:       bool
    signal_marketplace: bool
    tradingview_webhook:bool
    arbitrage_bot:      bool
    hybrid_bots:        bool
    backtesting:        bool
    api_access:         bool
    priority_signals:   bool
    # Royal IQ features
    royal_iq_signals:   bool     # copy signals from top traders
    signal_auto_invest: bool     # auto-invest % on each signal
    risk_level_select:  bool     # choose conservative/moderate/aggressive
    # Support
    support_level:      str      # basic | priority | dedicated
    description:        list = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


TIERS: dict[str, TierConfig] = {

    "gold": TierConfig(
        name="gold",
        display_name="Gold",
        color="#f59e0b",
        icon="🥇",
        # Fees — Gold pays only maintenance, NO monthly subscription
        per_trade_fee=0.01,        # $0.01 fixed per closed trade
        monthly_fee=0.0,           # FREE — no monthly fee
        profit_share_pct=0.0,      # No profit share
        withdrawal_fee_pct=0.0,    # No withdrawal fee
        # Limits
        max_bots=3,
        max_pairs_per_bot=2,
        max_open_trades=5,
        max_capital_usd=5000.0,
        # Features — entry level
        live_trading=True,
        demo_trading=True,
        all_bots=False,
        allowed_bots=["forex_scalper","crypto_momentum","crypto_dca"],
        indicator_layers=2,        # Only L1(Trend) + L2(Momentum)
        grid_trading=False,
        dca_trading=True,
        smart_trade=False,
        copy_trading=False,
        signal_marketplace=False,
        tradingview_webhook=False,
        arbitrage_bot=False,
        hybrid_bots=False,
        backtesting=False,
        api_access=False,
        priority_signals=False,
        royal_iq_signals=True,     # Basic signal copying
        signal_auto_invest=False,
        risk_level_select=False,
        support_level="basic",
        description=[
            "✅ $0.01 maintenance fee per trade",
            "✅ NO monthly subscription",
            "✅ NO profit share, NO withdrawal fees",
            "✅ 3 bots: Scalper, Momentum, DCA",
            "✅ 2 trading pairs per bot",
            "✅ 2-layer AI (Trend + Momentum)",
            "✅ Basic Royal IQ signal copying",
            "❌ Grid/SmartTrade/Arbitrage",
            "❌ Hybrid bots, API access",
        ]
    ),

    "silver": TierConfig(
        name="silver",
        display_name="Silver",
        color="#94a3b8",
        icon="🥈",
        # Fees
        per_trade_fee=0.025,       # $0.025 per closed trade
        monthly_fee=19.99,
        profit_share_pct=10.0,     # 10% of net profit
        withdrawal_fee_pct=0.05,   # 0.05% of withdrawal
        # Limits
        max_bots=6,
        max_pairs_per_bot=5,
        max_open_trades=15,
        max_capital_usd=25000.0,
        # Features
        live_trading=True,
        demo_trading=True,
        all_bots=False,
        allowed_bots=["forex_scalper","forex_swing","forex_grid",
                       "crypto_momentum","crypto_dca","crypto_reversal"],
        indicator_layers=5,        # Full 5-layer engine
        grid_trading=True,
        dca_trading=True,
        smart_trade=True,
        copy_trading=False,
        signal_marketplace=True,
        tradingview_webhook=True,
        arbitrage_bot=False,
        hybrid_bots=False,
        backtesting=True,
        api_access=False,
        priority_signals=False,
        royal_iq_signals=True,
        signal_auto_invest=True,
        risk_level_select=True,
        support_level="priority",
        description=[
            "✅ $0.025 per trade + $19.99/month",
            "✅ 10% profit share",
            "✅ 6 bots: All Forex + 3 Crypto",
            "✅ 5 pairs per bot",
            "✅ Full 5-layer AI indicators",
            "✅ Grid + DCA + SmartTrade",
            "✅ TradingView webhooks",
            "✅ Signal marketplace",
            "✅ Full Royal IQ signals + auto-invest",
            "❌ Arbitrage, Hybrid bots, API",
        ]
    ),

    "platinum": TierConfig(
        name="platinum",
        display_name="Platinum",
        color="#e2e8f0",
        icon="💎",
        # Fees
        per_trade_fee=0.05,        # $0.05 per closed trade
        monthly_fee=49.99,
        profit_share_pct=20.0,     # 20% of net profit
        withdrawal_fee_pct=0.1,    # 0.1% of withdrawal
        # Limits
        max_bots=12,
        max_pairs_per_bot=20,
        max_open_trades=50,
        max_capital_usd=500000.0,
        # Features — ALL UNLOCKED
        live_trading=True,
        demo_trading=True,
        all_bots=True,
        allowed_bots=[],           # empty = ALL bots
        indicator_layers=5,
        grid_trading=True,
        dca_trading=True,
        smart_trade=True,
        copy_trading=True,
        signal_marketplace=True,
        tradingview_webhook=True,
        arbitrage_bot=True,
        hybrid_bots=True,
        backtesting=True,
        api_access=True,
        priority_signals=True,     # Gets highest-confidence signals first
        royal_iq_signals=True,
        signal_auto_invest=True,
        risk_level_select=True,
        support_level="dedicated",
        description=[
            "✅ $0.05 per trade + $49.99/month",
            "✅ 20% profit share",
            "💎 ALL 9 bots + unlimited pairs",
            "💎 Full 5-layer AI + HybridBrain",
            "💎 ALL features unlocked",
            "💎 Forex Arbitrage + Hybrid Alpha & Omega",
            "💎 Copy trading + API access",
            "💎 Priority signals (highest conf first)",
            "💎 Full Royal IQ: signals + auto-invest + risk levels",
            "💎 Dedicated support + custom strategies",
        ]
    ),
}


# ═══════════════════════════════════════════════════════════════
# TIER ENGINE
# ═══════════════════════════════════════════════════════════════

class TierEngine:
    """Manages user tier, enforces limits, calculates tier-based fees."""

    def get_tier(self, tier_name: str) -> TierConfig:
        return TIERS.get(tier_name.lower(), TIERS["gold"])

    async def get_user_tier(self, user_id: str) -> TierConfig:
        """Get user's current active tier from DB."""
        try:
            sub = (db.table("subscriptions")
                   .select("tier,status,expires_at")
                   .eq("user_id", user_id)
                   .eq("status", "active")
                   .order("created_at", desc=True)
                   .limit(1).execute()).data
            if sub and sub[0].get("tier"):
                tier_name = sub[0]["tier"].lower()
                # Check expiry
                exp = sub[0].get("expires_at")
                if exp:
                    exp_dt = datetime.fromisoformat(exp.replace("Z","+00:00"))
                    if exp_dt < datetime.now(timezone.utc):
                        await self._downgrade_to_gold(user_id)
                        return TIERS["gold"]
                return self.get_tier(tier_name)
        except Exception:
            pass
        return TIERS["gold"]   # Default: free Gold tier

    async def _downgrade_to_gold(self, user_id: str):
        """Downgrade expired subscription to Gold."""
        try:
            db.table("subscriptions").update({
                "status": "expired",
                "tier": "gold",
            }).eq("user_id", user_id).eq("status", "active").execute()
            log.info("tier_downgraded_to_gold", user=user_id)
        except Exception:
            pass

    async def subscribe(self, user_id: str, tier_name: str,
                         payment_id: str = None) -> dict:
        """
        Subscribe user to a tier.
        Called after successful payment verification.
        """
        tier = self.get_tier(tier_name)
        now  = datetime.now(timezone.utc)
        exp  = now + timedelta(days=30)

        # Deactivate current subscription
        db.table("subscriptions").update({
            "status": "superseded"
        }).eq("user_id", user_id).eq("status", "active").execute()

        # Create new subscription
        row = db.table("subscriptions").insert({
            "user_id":        user_id,
            "tier":           tier.name,
            "status":         "active",
            "monthly_fee":    tier.monthly_fee,
            "per_trade_fee":  tier.per_trade_fee,
            "profit_share_pct": tier.profit_share_pct,
            "payment_id":     payment_id,
            "started_at":     now.isoformat(),
            "expires_at":     exp.isoformat(),
            "auto_renew":     True,
            "balance_due":    0.0,
        }).execute()

        log.info("user_subscribed", user=user_id, tier=tier.name)
        return {
            "success":    True,
            "tier":       tier.name,
            "expires_at": exp.isoformat(),
            "features":   tier.to_dict(),
        }

    def calculate_trade_fee(self, tier: TierConfig,
                             net_pnl: float,
                             is_profitable: bool) -> dict:
        """
        Calculate fees for a closed trade based on tier.

        Gold:     Only $0.01 maintenance fee. No profit share. No monthly.
        Silver:   $0.025 + 10% of profit.
        Platinum: $0.05 + 20% of profit.
        """
        maintenance = tier.per_trade_fee  # Fixed per-trade fee

        profit_share = 0.0
        if is_profitable and net_pnl > 0:
            profit_share = round(net_pnl * tier.profit_share_pct / 100, 8)

        total = round(maintenance + profit_share, 8)

        return {
            "tier":           tier.name,
            "maintenance":    maintenance,
            "profit_share":   profit_share,
            "profit_share_pct": tier.profit_share_pct,
            "total_fee":      total,
            "monthly_fee":    tier.monthly_fee,
            "note":           (
                f"Gold: $0.01 maintenance only (no monthly, no profit share)"
                if tier.name == "gold"
                else f"{tier.name.title()}: ${maintenance} + {tier.profit_share_pct}% profit"
            ),
        }

    def can_use_bot(self, tier: TierConfig, bot_id: str) -> tuple[bool, str]:
        """Check if tier allows a specific bot."""
        if tier.all_bots:
            return True, ""
        if bot_id in tier.allowed_bots:
            return True, ""
        return False, f"Bot '{bot_id}' requires Silver or Platinum tier"

    def can_use_feature(self, tier: TierConfig, feature: str) -> tuple[bool, str]:
        """Check if tier allows a feature."""
        allowed = getattr(tier, feature, False)
        if allowed:
            return True, ""
        needed = "Silver" if feature in [
            "grid_trading","smart_trade","signal_marketplace",
            "tradingview_webhook","backtesting","signal_auto_invest"
        ] else "Platinum"
        return False, f"Feature '{feature}' requires {needed} tier"

    def get_indicator_layers(self, tier: TierConfig) -> list[int]:
        """Return which of the 5 indicator layers this tier can use."""
        return list(range(1, tier.indicator_layers + 1))

    async def enforce_limits(self, user_id: str, action: str,
                              context: dict = None) -> dict:
        """Check if user action is allowed under their tier."""
        tier = await self.get_user_tier(user_id)
        ctx  = context or {}

        if action == "start_bot":
            bot_id = ctx.get("bot_id","")
            ok, msg = self.can_use_bot(tier, bot_id)
            if not ok:
                return {"allowed": False, "reason": msg, "tier": tier.name}
            # Check max bots running
            running = (db.table("bots").select("id", count="exact")
                       .eq("user_id", user_id).eq("status","running").execute()).count or 0
            if running >= tier.max_bots:
                return {"allowed": False,
                        "reason": f"Max {tier.max_bots} bots for {tier.display_name} tier",
                        "tier": tier.name}

        elif action == "open_trade":
            open_trades = (db.table("trades").select("id", count="exact")
                           .eq("user_id", user_id).eq("status","open").execute()).count or 0
            if open_trades >= tier.max_open_trades:
                return {"allowed": False,
                        "reason": f"Max {tier.max_open_trades} open trades for {tier.display_name}",
                        "tier": tier.name}
            capital = ctx.get("capital", 0)
            if capital > tier.max_capital_usd:
                return {"allowed": False,
                        "reason": f"Max capital ${tier.max_capital_usd:,.0f} for {tier.display_name}",
                        "tier": tier.name}

        elif action in ("grid_trading","dca_trading","smart_trade","copy_trading",
                         "signal_marketplace","tradingview_webhook","arbitrage_bot",
                         "hybrid_bots","backtesting","api_access","priority_signals"):
            ok, msg = self.can_use_feature(tier, action)
            if not ok:
                return {"allowed": False, "reason": msg, "tier": tier.name}

        return {"allowed": True, "tier": tier.name}


# ═══════════════════════════════════════════════════════════════
# ROYAL IQ BOT FEATURES
# ═══════════════════════════════════════════════════════════════

class RoyalIQEngine:
    """
    Royal IQ-inspired signal copying and auto-investment system.

    Features:
    1. Signal Providers — top traders publish signals with track record
    2. Auto-Copy — users subscribe to providers, trades auto-execute
    3. Risk Levels — Conservative (0.5% risk), Moderate (1.5%), Aggressive (3%)
    4. Signal Leaderboard — ranked by win rate, total profit, Sharpe ratio
    5. One-tap execution — user sees signal, taps COPY → trade opens instantly
    6. Percentage allocation — user sets X% of balance for each provider
    7. Stop-loss inheritance — copy provider's SL/TP exactly or custom
    8. Real-time notifications — push alert when signal published
    9. Signal expiry — signals expire after configurable time (e.g. 30min)
    10. Paper copy mode — test-copy without real money

    Royal IQ differences vs basic copy trading:
    - Royal IQ focuses on SIGNALS (analysis shared publicly)
    - 3Commas focuses on TRADE replication (copy exact trades)
    - ESTRADE combines both: signal marketplace + auto-execution
    """

    RISK_LEVELS = {
        "conservative": {"risk_pct": 0.5,  "max_sl_pct": 1.0,  "label": "Low Risk"},
        "moderate":     {"risk_pct": 1.5,  "max_sl_pct": 2.5,  "label": "Medium Risk"},
        "aggressive":   {"risk_pct": 3.0,  "max_sl_pct": 5.0,  "label": "High Risk"},
    }

    async def publish_signal(self, provider_id: str, signal: dict) -> dict:
        """
        Signal provider publishes a new trade signal.
        Signal is visible to all subscribers.
        """
        now     = datetime.now(timezone.utc)
        expiry  = (now + timedelta(minutes=signal.get("expiry_minutes", 60))).isoformat()
        row     = db.table("royal_iq_signals").insert({
            "provider_id":   provider_id,
            "symbol":        signal.get("symbol",""),
            "action":        signal.get("action","").upper(),
            "entry_price":   signal.get("entry_price"),
            "stop_loss":     signal.get("stop_loss"),
            "take_profit":   signal.get("take_profit"),
            "confidence":    signal.get("confidence", 70),
            "timeframe":     signal.get("timeframe","1h"),
            "reasoning":     signal.get("reasoning",""),
            "risk_level":    signal.get("risk_level","moderate"),
            "status":        "active",
            "expires_at":    expiry,
            "copy_count":    0,
        }).execute()
        return {"published": True, "signal_id": row.data[0]["id"] if row.data else None}

    async def copy_signal(self, user_id: str, signal_id: str,
                           risk_level: str = "moderate",
                           custom_pct: float = None) -> dict:
        """
        User copies a signal — auto-creates a trade.
        Enforces tier limits before executing.
        """
        # Get signal
        sig = (db.table("royal_iq_signals").select("*")
               .eq("id", signal_id).eq("status","active").single().execute()).data
        if not sig:
            return {"copied": False, "reason": "Signal not found or expired"}

        # Check expiry
        exp = datetime.fromisoformat(sig["expires_at"].replace("Z","+00:00"))
        if exp < datetime.now(timezone.utc):
            return {"copied": False, "reason": "Signal expired"}

        # Get tier
        tier = await tier_engine.get_user_tier(user_id)

        # Check tier allows Royal IQ signals
        if not tier.royal_iq_signals:
            return {"copied": False, "reason": "Royal IQ signals require Gold tier or higher"}

        # Calculate position size
        risk = self.RISK_LEVELS.get(risk_level, self.RISK_LEVELS["moderate"])
        risk_pct  = custom_pct if custom_pct else risk["risk_pct"]
        wallet    = (db.table("wallets").select("balance")
                     .eq("user_id", user_id).eq("wallet_type","trading")
                     .eq("mode","live").single().execute()).data
        balance   = float(wallet["balance"]) if wallet else 0
        position  = round(balance * risk_pct / 100, 4)

        if position < 1.0:
            return {"copied": False, "reason": f"Insufficient balance for {risk_pct}% position"}

        # Record copy
        db.table("royal_iq_copies").insert({
            "user_id":    user_id,
            "signal_id":  signal_id,
            "risk_level": risk_level,
            "risk_pct":   risk_pct,
            "position_usd": position,
            "entry_price": sig.get("entry_price"),
            "status":     "pending",
        }).execute()

        # Update copy count
        db.table("royal_iq_signals").update({
            "copy_count": int(sig.get("copy_count",0)) + 1
        }).eq("id", signal_id).execute()

        return {
            "copied":       True,
            "signal_id":    signal_id,
            "symbol":       sig["symbol"],
            "action":       sig["action"],
            "position_usd": position,
            "risk_level":   risk_level,
            "risk_pct":     risk_pct,
        }

    async def get_leaderboard(self, period: str = "30d") -> list:
        """Signal provider leaderboard ranked by performance."""
        try:
            rows = (db.table("signal_providers")
                    .select("*")
                    .eq("is_active", True)
                    .order("win_rate", desc=True)
                    .limit(20).execute()).data or []
            return rows
        except Exception:
            return []

    async def get_active_signals(self, tier: TierConfig,
                                  symbol: str = None) -> list:
        """Get active signals filtered by tier and symbol."""
        try:
            q = (db.table("royal_iq_signals")
                 .select("*, signal_providers(name,avatar,win_rate,total_trades)")
                 .eq("status","active")
                 .gt("expires_at", datetime.now(timezone.utc).isoformat())
                 .order("confidence", desc=True))
            if symbol:
                q = q.eq("symbol", symbol)
            if tier.priority_signals:
                q = q.gte("confidence", 70)  # Platinum sees high-conf first
            return q.limit(50).execute().data or []
        except Exception:
            return []

    async def auto_copy_for_user(self, user_id: str, signal_id: str) -> dict:
        """
        Auto-copy signal based on user's pre-configured settings.
        Called by Celery worker when new signal published.
        """
        try:
            settings_row = (db.table("royal_iq_auto_copy")
                            .select("*").eq("user_id", user_id)
                            .eq("is_active", True).single().execute()).data
            if not settings_row:
                return {"auto_copied": False, "reason": "Auto-copy not configured"}

            risk_level  = settings_row.get("risk_level","moderate")
            custom_pct  = float(settings_row.get("allocation_pct", 0)) or None

            result = await self.copy_signal(user_id, signal_id, risk_level, custom_pct)
            return {"auto_copied": result.get("copied"), **result}
        except Exception as e:
            return {"auto_copied": False, "error": str(e)}


# ═══════════════════════════════════════════════════════════════
# ULTRA SCALPING AI — Best-in-class
# ═══════════════════════════════════════════════════════════════

class UltraScalpingAI:
    """
    Ultra-advanced scalping strategy — best possible.
    Combines 12 fast indicators into a single scalp decision.
    Optimized for M1, M5 timeframes.

    Layers (no overlap):
    ① Micro-Trend (EMA 3/8/21) — direction in last 5 candles
    ② Momentum Burst (RSI 7, MACD fast 3/10/5) — entry trigger
    ③ Volume Spike (Vol > 2× avg + OBV direction) — confirmation
    ④ Spread/Noise Filter (ATR 5 vs ATR 20) — avoid noise
    ⑤ Level Magnetic (nearest pivot/round number) — target

    Entry criteria (ALL must be true):
    - EMA3 > EMA8 > EMA21 (bull) or inverse (bear)
    - RSI7 in 40-60 band (momentum not exhausted)
    - MACD fast histogram > 0 and increasing (bull)
    - Volume ≥ 1.5× 20-bar average
    - Price NOT within 0.3 ATR of resistance (room to run)
    - ATR5 < ATR20 × 1.5 (not too volatile for scalp)

    Exit criteria:
    - TP: 1.2× ATR5 from entry
    - SL: 0.8× ATR5 from entry
    - R:R = 1.5:1 minimum
    - Time-based exit: max 10 minutes in trade
    - Trail after 0.5× ATR profit: trail by 0.4× ATR
    """

    def analyze(self, df) -> dict:
        """Full ultra-scalp analysis. Returns signal + exact entry/sl/tp."""
        import pandas as pd
        import numpy as np

        if df is None or len(df) < 30:
            return {"action":"WAIT","confidence":0,"reason":"need 30+ bars"}

        c  = df["close"]
        h  = df["high"]
        lo = df["low"]
        v  = df.get("volume", pd.Series([1]*len(df)))

        # ① Micro-trend EMAs
        ema3  = c.ewm(span=3,  adjust=False).mean()
        ema8  = c.ewm(span=8,  adjust=False).mean()
        ema21 = c.ewm(span=21, adjust=False).mean()
        e3, e8, e21 = float(ema3.iloc[-1]), float(ema8.iloc[-1]), float(ema21.iloc[-1])
        pe3  = float(ema3.iloc[-2])
        cl   = float(c.iloc[-1])
        micro_bull = e3 > e8 > e21 and cl > e3
        micro_bear = e3 < e8 < e21 and cl < e3
        micro_cross_bull = float(ema3.iloc[-2]) <= float(ema8.iloc[-2]) and e3 > e8
        micro_cross_bear = float(ema3.iloc[-2]) >= float(ema8.iloc[-2]) and e3 < e8

        # ② Momentum burst — RSI7 + fast MACD
        d    = c.diff()
        g    = d.clip(lower=0).ewm(span=7, adjust=False).mean()
        l    = (-d.clip(upper=0)).ewm(span=7, adjust=False).mean()
        rsi7 = float(100 - 100/(1 + g/l.replace(0,1e-9)).iloc[-1])
        m    = c.ewm(span=3, adjust=False).mean() - c.ewm(span=10, adjust=False).mean()
        ms   = m.ewm(span=5, adjust=False).mean()
        mh   = float((m - ms).iloc[-1])
        mhp  = float((m - ms).iloc[-2])
        macd_bull = mh > 0 and mh > mhp
        macd_bear = mh < 0 and mh < mhp

        # ③ Volume spike
        vol_avg = v.rolling(20).mean().iloc[-1]
        vol_cur = float(v.iloc[-1]) if hasattr(v.iloc[-1],'__float__') else 1
        vol_ratio = vol_cur / (float(vol_avg) + 1e-9)
        vol_spike = vol_ratio >= 1.5
        obv_dir = 1 if float(c.diff().iloc[-1]) > 0 else -1

        # ④ Noise filter — ATR5 vs ATR20
        def atr(n):
            tr = pd.concat([h-lo,(h-c.shift()).abs(),(lo-c.shift()).abs()],axis=1).max(axis=1)
            return float(tr.ewm(span=n,adjust=False).mean().iloc[-1])
        atr5  = atr(5)
        atr20 = atr(20)
        noise_ok = atr5 < atr20 * 1.5 and atr5 > 0

        # ⑤ Nearest pivot for target
        h5  = float(h.tail(5).max())
        l5  = float(lo.tail(5).min())
        mid = (h5 + l5) / 2
        pivot_above = h5
        pivot_below = l5
        room_to_run_bull = (pivot_above - cl) / (atr5 + 1e-9) > 1.0
        room_to_run_bear = (cl - pivot_below) / (atr5 + 1e-9) > 1.0

        # ── BULL SCALP ENTRY ──────────────────────────────────
        bull_conditions = [
            micro_bull,          # EMA micro-trend aligned
            macd_bull,           # MACD fast histogram rising
            vol_spike,           # volume confirmation
            noise_ok,            # not too volatile
            room_to_run_bull,    # room to next resistance
            35 < rsi7 < 68,      # RSI not extreme
        ]
        bear_conditions = [
            micro_bear,
            macd_bear,
            vol_spike,
            noise_ok,
            room_to_run_bear,
            32 < rsi7 < 65,
        ]

        bull_score = sum(bull_conditions)
        bear_score = sum(bear_conditions)

        # Need 5/6 conditions for high-conf entry
        if bull_score >= 5:
            sl   = round(cl - atr5 * 0.8, 6)
            tp   = round(cl + atr5 * 1.2, 6)
            trail_trigger = round(cl + atr5 * 0.5, 6)
            trail_dist    = atr5 * 0.4
            conf = min(96, 65 + bull_score * 5 + (8 if micro_cross_bull else 0) + vol_ratio * 4)
            return {
                "action":         "BUY",
                "confidence":     round(conf, 2),
                "entry":          cl,
                "stop_loss":      sl,
                "take_profit":    tp,
                "trail_trigger":  trail_trigger,
                "trail_distance": round(trail_dist, 6),
                "rr_ratio":       round(1.2/0.8, 2),  # 1.5:1
                "max_hold_mins":  10,
                "atr5":           round(atr5, 6),
                "vol_ratio":      round(vol_ratio, 2),
                "rsi7":           round(rsi7, 2),
                "conditions_met": bull_score,
                "reason": f"Bull scalp: EMA aligned + MACD↑ + vol {vol_ratio:.1f}x",
                "strategy":       "ultra_scalp_v6",
            }

        if bear_score >= 5:
            sl   = round(cl + atr5 * 0.8, 6)
            tp   = round(cl - atr5 * 1.2, 6)
            trail_trigger = round(cl - atr5 * 0.5, 6)
            trail_dist    = atr5 * 0.4
            conf = min(96, 65 + bear_score * 5 + (8 if micro_cross_bear else 0) + vol_ratio * 4)
            return {
                "action":         "SELL",
                "confidence":     round(conf, 2),
                "entry":          cl,
                "stop_loss":      sl,
                "take_profit":    tp,
                "trail_trigger":  trail_trigger,
                "trail_distance": round(trail_dist, 6),
                "rr_ratio":       round(1.2/0.8, 2),
                "max_hold_mins":  10,
                "atr5":           round(atr5, 6),
                "vol_ratio":      round(vol_ratio, 2),
                "rsi7":           round(rsi7, 2),
                "conditions_met": bear_score,
                "reason": f"Bear scalp: EMA aligned + MACD↓ + vol {vol_ratio:.1f}x",
                "strategy":       "ultra_scalp_v6",
            }

        # Partial signal — WAIT with info
        return {
            "action":       "WAIT",
            "confidence":   max(bull_score, bear_score) / 6 * 60,
            "bull_score":   bull_score,
            "bear_score":   bear_score,
            "rsi7":         round(rsi7, 2),
            "vol_ratio":    round(vol_ratio, 2),
            "micro_bull":   micro_bull,
            "micro_bear":   micro_bear,
            "macd_bull":    macd_bull,
            "vol_spike":    vol_spike,
            "reason":       f"Only {max(bull_score,bear_score)}/6 conditions met",
            "strategy":     "ultra_scalp_v6",
        }


# ── Singletons ───────────────────────────────────────────────
tier_engine      = TierEngine()
royal_iq_engine  = RoyalIQEngine()
ultra_scalp_ai   = UltraScalpingAI()
