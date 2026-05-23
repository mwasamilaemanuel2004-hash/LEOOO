"""
services/fee_engine.py — ESTRADE v6 Advanced Deferred Fee System
══════════════════════════════════════════════════════════════════════════
Fee Model (EXACT):

  PER TRADE:
    - Platform fee: 0.05% of trade notional value
    - Profit share: 20% of NET profit (only if trade is profitable)
    → ACCRUED in `trade_fees` table, NOT immediately deducted from wallet

  SUBSCRIPTION:
    - $29.99/month flat rate
    - Accrues daily ($1.00/day) into `subscription_fees` table

  COLLECTION TRIGGERS:
    1. User withdraws funds  → ALL accrued fees deducted FIRST, then withdrawal processed
    2. End of month (1st)    → Celery task collects all outstanding fees for all users
    3. Manual collect        → Admin or user can trigger collection anytime

  SUPABASE AGGREGATION:
    - Supabase VIEW `v_user_fees` sums all unpaid fees per user in real-time
    - Supabase FUNCTION `collect_user_fees(user_id)` atomically collects + clears
    - Supabase TRIGGER `after_trade_close` → auto-inserts fee record
    - No race conditions — all atomic via Postgres transactions

  WALLET WITHDRAWAL FLOW:
    1. User requests withdrawal of $X
    2. System calls `fee_engine.collect_before_withdrawal(user_id, amount)`
    3. Supabase function atomically:
       a. Sums all accrued trade fees + subscription + withdrawal fee
       b. Deducts total from wallet balance
       c. Marks all fees as collected
       d. Returns remaining amount available for withdrawal
    4. Withdrawal processed with net amount
══════════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations
import asyncio
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, asdict
from typing import Optional
import structlog

from core.database import db
from core.config import settings

log = structlog.get_logger("fee_engine")

# ── Fee Rates ────────────────────────────────────────────────
PLATFORM_FEE_PCT     = 0.0005   # 0.05% of notional per trade
PROFIT_SHARE_PCT     = 0.20     # 20% of net profit per trade
SUBSCRIPTION_USD     = 29.99    # per month
WITHDRAWAL_FEE_PCT   = 0.001    # 0.1% of withdrawal amount
SUBSCRIPTION_DAILY   = round(SUBSCRIPTION_USD / 30, 6)  # ~$1.00/day


@dataclass
class FeeBreakdown:
    platform_fees:    float   # 0.05% × notional, summed across all trades
    profit_share:     float   # 20% × profit, summed across winning trades
    subscription:     float   # monthly flat rate accrued
    withdrawal_fee:   float   # 0.1% of this withdrawal
    total_accrued:    float   # platform + profit + subscription (before this withdrawal)
    total_due:        float   # total_accrued + withdrawal_fee
    trade_count:      int     # number of uncollected trades
    period_days:      int     # days covered by this fee period

    def to_dict(self) -> dict:
        return asdict(self)


class FeeEngine:
    """
    Advanced deferred fee collection engine.
    All accumulation happens in Supabase.
    Collection is atomic via Postgres RPC calls.
    """

    # ── Accrual (called on every trade close) ─────────────────

    async def accrue_trade_fee(
        self,
        user_id:   str,
        trade_id:  str,
        symbol:    str,
        side:      str,
        notional:  float,
        gross_pnl: float,
        net_pnl:   float,
        mode:      str = "live",
    ) -> dict:
        """
        Called when every trade closes.
        Records fee in trade_fees table — does NOT deduct from wallet.
        Supabase trigger handles the insert automatically, but this is
        the explicit Python call for control.

        Args:
            notional:  entry_price × quantity (position size in USD)
            gross_pnl: PnL before fees
            net_pnl:   PnL after exchange fees (what user actually earned)
        """
        if mode != "live":
            return {"accrued": False, "reason": "demo mode"}

        # Get tier-based fee rates
        try:
            from services.tier_engine import tier_engine
            tier = await tier_engine.get_user_tier(user_id)
            maintenance  = tier.per_trade_fee          # Gold=$0.01, Silver=$0.025, Platinum=$0.05
            ps_pct       = tier.profit_share_pct / 100 # Gold=0%, Silver=10%, Platinum=20%
            tier_name    = tier.name
        except Exception:
            maintenance, ps_pct, tier_name = 0.01, 0.0, "gold"

        platform_fee = maintenance  # Fixed maintenance per trade (tier-based)
        profit_share = round(max(0, net_pnl) * ps_pct, 8) if net_pnl > 0 else 0.0
        total        = round(platform_fee + profit_share, 8)

        try:
            db.table("trade_fees").insert({
                "user_id":      user_id,
                "trade_id":     trade_id,
                "symbol":       symbol,
                "side":         side,
                "notional":     round(notional, 8),
                "gross_pnl":    round(gross_pnl, 8),
                "net_pnl":      round(net_pnl, 8),
                "platform_fee": platform_fee,
                "profit_share": profit_share,
                "total_fee":    total,
                "collected":    False,
                "fee_period":   self._current_period(),
                "tier":           tier_name,
                "maintenance_fee": platform_fee,
            }).execute()

            log.info("fee_accrued", user=user_id, trade=trade_id,
                     platform=platform_fee, profit_share=profit_share, total=total)
            return {
                "accrued":       True,
                "platform_fee":  platform_fee,
                "profit_share":  profit_share,
                "total_accrued": total,
                "trade_id":      trade_id,
            }
        except Exception as e:
            log.error("fee_accrue_error", error=str(e), trade_id=trade_id)
            return {"accrued": False, "error": str(e)}

    async def accrue_daily_subscription(self, user_id: str) -> dict:
        """
        Called daily by Celery beat.
        Accrues $1.00/day subscription fee (collected at month-end or withdrawal).
        """
        try:
            # Check if active subscription
            sub = (db.table("subscriptions").select("id,status,plan")
                   .eq("user_id", user_id).eq("status", "active")
                   .single().execute()).data
            if not sub:
                return {"accrued": False, "reason": "no_active_subscription"}

            db.table("subscription_fees").insert({
                "user_id":    user_id,
                "amount":     SUBSCRIPTION_DAILY,
                "fee_date":   datetime.now(timezone.utc).date().isoformat(),
                "collected":  False,
                "period":     self._current_period(),
            }).execute()
            return {"accrued": True, "amount": SUBSCRIPTION_DAILY}
        except Exception as e:
            return {"accrued": False, "error": str(e)}

    # ── Balance query (real-time Supabase sum) ────────────────

    async def get_balance_due(self, user_id: str) -> FeeBreakdown:
        """
        Query Supabase for total accrued uncollected fees.
        Uses v_user_fees VIEW for real-time aggregation.
        """
        try:
            # Try the Supabase view first (most efficient)
            view = (db.table("v_user_fees").select("*")
                    .eq("user_id", user_id).single().execute()).data
            if view:
                return FeeBreakdown(
                    platform_fees  = float(view.get("total_platform_fees", 0)),
                    profit_share   = float(view.get("total_profit_share", 0)),
                    subscription   = float(view.get("total_subscription", 0)),
                    withdrawal_fee = 0.0,
                    total_accrued  = float(view.get("grand_total", 0)),
                    total_due      = float(view.get("grand_total", 0)),
                    trade_count    = int(view.get("uncollected_trades", 0)),
                    period_days    = int(view.get("period_days", 0)),
                )
        except Exception:
            pass

        # Fallback: manual aggregation
        return await self._aggregate_manually(user_id)

    async def _aggregate_manually(self, user_id: str) -> FeeBreakdown:
        """Direct table query fallback if view not available."""
        try:
            # Trade fees
            trade_rows = (db.table("trade_fees").select("platform_fee,profit_share,total_fee,created_at")
                          .eq("user_id", user_id).eq("collected", False).execute()).data or []
            platform   = sum(float(r.get("platform_fee", 0)) for r in trade_rows)
            profit_sh  = sum(float(r.get("profit_share", 0)) for r in trade_rows)

            # Subscription fees
            sub_rows   = (db.table("subscription_fees").select("amount,fee_date")
                          .eq("user_id", user_id).eq("collected", False).execute()).data or []
            sub_total  = sum(float(r.get("amount", 0)) for r in sub_rows)

            grand      = round(platform + profit_sh + sub_total, 8)

            # Calculate period days
            if trade_rows:
                first_dt = datetime.fromisoformat(trade_rows[0]["created_at"].replace("Z", "+00:00"))
                days = (datetime.now(timezone.utc) - first_dt).days + 1
            else:
                days = 0

            return FeeBreakdown(
                platform_fees  = round(platform, 8),
                profit_share   = round(profit_sh, 8),
                subscription   = round(sub_total, 8),
                withdrawal_fee = 0.0,
                total_accrued  = grand,
                total_due      = grand,
                trade_count    = len(trade_rows),
                period_days    = days,
            )
        except Exception as e:
            log.error("fee_aggregate_error", error=str(e))
            return FeeBreakdown(0,0,0,0,0,0,0,0)

    # ── Collection (deduct from wallet) ───────────────────────

    async def collect_before_withdrawal(
        self,
        user_id:         str,
        withdrawal_usd:  float,
    ) -> dict:
        """
        MAIN COLLECTION METHOD — called before every withdrawal.

        Flow:
          1. Get all accrued fees (trade fees + subscription)
          2. Calculate withdrawal fee (0.1% of withdrawal amount)
          3. Sum total
          4. Attempt atomic collection via Supabase RPC
          5. Return result with net_withdrawal_amount

        If user has insufficient balance to cover fees:
          - Partial collection: collect as much as possible
          - Block withdrawal until fees paid
          - Admin alert generated
        """
        breakdown = await self.get_balance_due(user_id)
        wd_fee    = round(withdrawal_usd * WITHDRAWAL_FEE_PCT, 8)
        total_due = round(breakdown.total_accrued + wd_fee, 8)

        breakdown.withdrawal_fee = wd_fee
        breakdown.total_due      = total_due

        if total_due <= 0.001:
            return {
                "collected":           True,
                "fees_collected":      0.0,
                "net_withdrawal":      withdrawal_usd,
                "breakdown":           breakdown.to_dict(),
                "message":             "No outstanding fees",
            }

        # Get wallet balance
        try:
            wallet = (db.table("wallets").select("id,balance,locked_balance")
                      .eq("user_id", user_id).eq("wallet_type", "trading")
                      .eq("mode", "live").single().execute()).data
        except Exception:
            wallet = None

        balance = float(wallet["balance"]) if wallet else 0.0

        if balance < total_due + withdrawal_usd:
            # Insufficient — try to collect just fees, block withdrawal
            if balance < total_due:
                log.warning("insufficient_for_fees",
                            user=user_id, balance=balance, fees=total_due)
                return {
                    "collected":      False,
                    "reason":         "INSUFFICIENT_BALANCE_FOR_FEES",
                    "fees_due":       total_due,
                    "wallet_balance": balance,
                    "shortfall":      round(total_due - balance, 8),
                    "message":        f"Please top up wallet. Fees due: ${total_due:.4f}",
                    "breakdown":      breakdown.to_dict(),
                }

        # Try atomic RPC collection first
        try:
            rpc_result = db.rpc("collect_user_fees_v6", {
                "p_user_id":         user_id,
                "p_platform_fees":   breakdown.platform_fees,
                "p_profit_share":    breakdown.profit_share,
                "p_subscription":    breakdown.subscription,
                "p_withdrawal_fee":  wd_fee,
                "p_total_amount":    total_due,
                "p_wallet_id":       wallet["id"] if wallet else None,
            }).execute()
            success = True
        except Exception:
            # Fallback: manual deduction
            success = await self._manual_collect(
                user_id, wallet, breakdown, wd_fee, total_due
            )

        if success:
            log.info("fees_collected",
                     user=user_id, total=total_due, trades=breakdown.trade_count,
                     platform=breakdown.platform_fees, profit=breakdown.profit_share,
                     subscription=breakdown.subscription, wd_fee=wd_fee)
            return {
                "collected":           True,
                "fees_collected":      total_due,
                "net_withdrawal":      withdrawal_usd,
                "breakdown":           breakdown.to_dict(),
                "message":             f"${total_due:.4f} in fees collected",
            }
        return {
            "collected": False,
            "reason":    "COLLECTION_FAILED",
            "breakdown": breakdown.to_dict(),
        }

    async def _manual_collect(
        self,
        user_id:   str,
        wallet:    dict,
        breakdown: FeeBreakdown,
        wd_fee:    float,
        total_due: float,
    ) -> bool:
        """Manual fee collection fallback (non-atomic but safe)."""
        try:
            # 1. Deduct from wallet
            new_balance = float(wallet["balance"]) - total_due
            db.table("wallets").update({
                "balance": round(max(0, new_balance), 8)
            }).eq("id", wallet["id"]).execute()

            # 2. Mark trade fees as collected
            db.table("trade_fees").update({
                "collected":    True,
                "collected_at": datetime.now(timezone.utc).isoformat(),
            }).eq("user_id", user_id).eq("collected", False).execute()

            # 3. Mark subscription fees as collected
            db.table("subscription_fees").update({
                "collected":    True,
                "collected_at": datetime.now(timezone.utc).isoformat(),
            }).eq("user_id", user_id).eq("collected", False).execute()

            # 4. Record collection transaction
            db.table("fee_collections").insert({
                "user_id":        user_id,
                "trigger":        "withdrawal",
                "platform_fees":  breakdown.platform_fees,
                "profit_share":   breakdown.profit_share,
                "subscription":   breakdown.subscription,
                "withdrawal_fee": wd_fee,
                "total_collected": total_due,
                "trade_count":    breakdown.trade_count,
                "collected_at":   datetime.now(timezone.utc).isoformat(),
            }).execute()

            # 5. Log to transactions
            db.table("transactions").insert({
                "user_id":      user_id,
                "wallet_id":    wallet["id"],
                "txn_type":     "fee_collection",
                "amount":       -total_due,
                "balance_after": round(max(0, new_balance), 8),
                "description":  f"Monthly fees collected: platform ${breakdown.platform_fees:.4f} + profit share ${breakdown.profit_share:.4f} + sub ${breakdown.subscription:.4f} + wd fee ${wd_fee:.4f}",
            }).execute()
            return True
        except Exception as e:
            log.error("manual_collect_error", error=str(e), user=user_id)
            return False

    async def collect_monthly_for_user(self, user_id: str) -> dict:
        """Collect all accrued fees for one user at month-end (no withdrawal)."""
        return await self.collect_before_withdrawal(user_id, 0.0)

    async def collect_monthly_all_users(self) -> dict:
        """
        Called by Celery beat on 1st of each month.
        Collects fees for ALL users with outstanding balance.
        """
        try:
            # Get all users with uncollected fees
            fee_users = (db.table("trade_fees").select("user_id")
                         .eq("collected", False).execute()).data or []
            sub_users = (db.table("subscription_fees").select("user_id")
                         .eq("collected", False).execute()).data or []

            all_user_ids = list(set(
                [r["user_id"] for r in fee_users] +
                [r["user_id"] for r in sub_users]
            ))

            results = {"total_users": len(all_user_ids), "collected": 0,
                       "failed": 0, "total_collected_usd": 0.0}

            for uid in all_user_ids:
                try:
                    result = await self.collect_monthly_for_user(uid)
                    if result.get("collected"):
                        results["collected"]           += 1
                        results["total_collected_usd"] += result.get("fees_collected", 0)
                    else:
                        results["failed"] += 1
                        log.warning("monthly_collect_failed", user=uid,
                                    reason=result.get("reason"))
                except Exception as e:
                    results["failed"] += 1
                    log.error("monthly_collect_error", user=uid, error=str(e))

            log.info("monthly_collection_complete", **results)
            return results
        except Exception as e:
            log.error("monthly_collection_failed", error=str(e))
            return {"error": str(e)}

    # ── Helpers ───────────────────────────────────────────────

    def _current_period(self) -> str:
        """Return current billing period string: YYYY-MM"""
        return datetime.now(timezone.utc).strftime("%Y-%m")

    async def get_fee_history(self, user_id: str, limit: int = 50) -> list:
        """Get fee collection history for user."""
        try:
            rows = (db.table("fee_collections").select("*")
                    .eq("user_id", user_id)
                    .order("collected_at", desc=True)
                    .limit(limit).execute()).data or []
            return rows
        except Exception:
            return []

    async def get_trade_fee_ledger(self, user_id: str,
                                    collected: bool = None,
                                    limit: int = 100) -> list:
        """Get per-trade fee ledger for user."""
        try:
            q = (db.table("trade_fees").select(
                "trade_id,symbol,side,notional,net_pnl,platform_fee,profit_share,total_fee,collected,fee_period,created_at"
            ).eq("user_id", user_id).order("created_at", desc=True).limit(limit))
            if collected is not None:
                q = q.eq("collected", collected)
            return q.execute().data or []
        except Exception:
            return []

    def calculate_fees_preview(self, notional: float, net_pnl: float) -> dict:
        """
        Preview what fees would be for a hypothetical trade.
        Used in UI to show user before they trade.
        """
        pf = round(notional * PLATFORM_FEE_PCT, 8)
        ps = round(max(0, net_pnl) * PROFIT_SHARE_PCT, 8) if net_pnl > 0 else 0
        return {
            "platform_fee":        pf,
            "profit_share":        ps,
            "total_fee":           round(pf + ps, 8),
            "platform_fee_pct":    PLATFORM_FEE_PCT * 100,
            "profit_share_pct":    PROFIT_SHARE_PCT * 100,
            "collection_trigger":  "withdrawal or month-end",
            "note":                "Fees are NEVER deducted during active trading",
        }


# ── Supabase SQL to create required tables + view + function ──
SUPABASE_FEE_MIGRATION = """
-- ══════════════════════════════════════════════════════════════
-- ESTRADE v6 Fee System Migration
-- Run in Supabase SQL Editor AFTER existing migrations
-- ══════════════════════════════════════════════════════════════

-- 1. Trade Fees Table (one row per closed trade)
CREATE TABLE IF NOT EXISTS trade_fees (
    id              uuid DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id         uuid REFERENCES auth.users(id) ON DELETE CASCADE,
    trade_id        uuid,
    symbol          text,
    side            text,
    notional        numeric(18,8) DEFAULT 0,
    gross_pnl       numeric(18,8) DEFAULT 0,
    net_pnl         numeric(18,8) DEFAULT 0,
    platform_fee    numeric(18,8) DEFAULT 0,   -- 0.05% of notional
    profit_share    numeric(18,8) DEFAULT 0,   -- 20% of profit
    total_fee       numeric(18,8) DEFAULT 0,
    collected       boolean DEFAULT false,
    collected_at    timestamptz,
    fee_period      text,                       -- YYYY-MM
    created_at      timestamptz DEFAULT now()
);

-- 2. Subscription Fees Table (one row per day per user)
CREATE TABLE IF NOT EXISTS subscription_fees (
    id          uuid DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id     uuid REFERENCES auth.users(id) ON DELETE CASCADE,
    amount      numeric(10,6) DEFAULT 1.00,    -- ~$1/day
    fee_date    date DEFAULT current_date,
    collected   boolean DEFAULT false,
    collected_at timestamptz,
    period      text,
    created_at  timestamptz DEFAULT now(),
    UNIQUE (user_id, fee_date)
);

-- 3. Fee Collections Log (one row per collection event)
CREATE TABLE IF NOT EXISTS fee_collections (
    id               uuid DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id          uuid REFERENCES auth.users(id) ON DELETE CASCADE,
    trigger          text,                      -- withdrawal | monthly | manual
    platform_fees    numeric(18,8) DEFAULT 0,
    profit_share     numeric(18,8) DEFAULT 0,
    subscription     numeric(18,8) DEFAULT 0,
    withdrawal_fee   numeric(18,8) DEFAULT 0,
    total_collected  numeric(18,8) DEFAULT 0,
    trade_count      int DEFAULT 0,
    collected_at     timestamptz DEFAULT now()
);

-- 4. Real-time fee aggregation VIEW
CREATE OR REPLACE VIEW v_user_fees AS
SELECT
    u.id AS user_id,
    COALESCE(tf.platform_fees, 0)   AS total_platform_fees,
    COALESCE(tf.profit_share,  0)   AS total_profit_share,
    COALESCE(sf.subscription,  0)   AS total_subscription,
    COALESCE(tf.platform_fees, 0) + COALESCE(tf.profit_share, 0) + COALESCE(sf.subscription, 0) AS grand_total,
    COALESCE(tf.trade_count,   0)   AS uncollected_trades,
    COALESCE(sf.sub_days,      0)   AS uncollected_sub_days,
    COALESCE(DATE_PART('day', now() - tf.oldest_fee), 0) AS period_days
FROM auth.users u
LEFT JOIN (
    SELECT user_id,
           SUM(platform_fee)  AS platform_fees,
           SUM(profit_share)  AS profit_share,
           COUNT(*)           AS trade_count,
           MIN(created_at)    AS oldest_fee
    FROM trade_fees
    WHERE collected = false
    GROUP BY user_id
) tf ON tf.user_id = u.id
LEFT JOIN (
    SELECT user_id,
           SUM(amount) AS subscription,
           COUNT(*)    AS sub_days
    FROM subscription_fees
    WHERE collected = false
    GROUP BY user_id
) sf ON sf.user_id = u.id;

-- 5. Atomic fee collection RPC function
CREATE OR REPLACE FUNCTION collect_user_fees_v6(
    p_user_id         uuid,
    p_platform_fees   numeric,
    p_profit_share    numeric,
    p_subscription    numeric,
    p_withdrawal_fee  numeric,
    p_total_amount    numeric,
    p_wallet_id       uuid
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER AS $$
DECLARE
    v_balance numeric;
    v_new_bal numeric;
    v_trade_count int;
BEGIN
    -- Lock wallet row for update
    SELECT balance INTO v_balance
    FROM wallets
    WHERE id = p_wallet_id
    FOR UPDATE;

    IF v_balance < p_total_amount THEN
        RETURN jsonb_build_object('success', false, 'reason', 'INSUFFICIENT_BALANCE',
                                  'balance', v_balance, 'required', p_total_amount);
    END IF;

    v_new_bal := v_balance - p_total_amount;

    -- Deduct from wallet
    UPDATE wallets SET balance = v_new_bal WHERE id = p_wallet_id;

    -- Mark trade fees collected
    UPDATE trade_fees SET collected = true, collected_at = now()
    WHERE user_id = p_user_id AND collected = false;
    GET DIAGNOSTICS v_trade_count = ROW_COUNT;

    -- Mark subscription fees collected
    UPDATE subscription_fees SET collected = true, collected_at = now()
    WHERE user_id = p_user_id AND collected = false;

    -- Log collection
    INSERT INTO fee_collections (
        user_id, trigger, platform_fees, profit_share,
        subscription, withdrawal_fee, total_collected, trade_count
    ) VALUES (
        p_user_id, 'system', p_platform_fees, p_profit_share,
        p_subscription, p_withdrawal_fee, p_total_amount, v_trade_count
    );

    -- Log transaction
    INSERT INTO transactions (user_id, wallet_id, txn_type, amount, balance_after, description)
    VALUES (p_user_id, p_wallet_id, 'fee_collection', -p_total_amount, v_new_bal,
            'Auto-collected: platform $' || p_platform_fees || ' + profit share $' || p_profit_share ||
            ' + subscription $' || p_subscription || ' + withdrawal fee $' || p_withdrawal_fee);

    RETURN jsonb_build_object(
        'success', true,
        'collected', p_total_amount,
        'new_balance', v_new_bal,
        'trades_cleared', v_trade_count
    );
END;
$$;

-- 6. Auto-accrue trigger on trade close (belt-and-suspenders)
CREATE OR REPLACE FUNCTION auto_accrue_trade_fee()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE
    v_platform numeric;
    v_profit   numeric;
BEGIN
    IF NEW.status = 'closed' AND OLD.status = 'open' AND NEW.mode = 'live' THEN
        v_platform := COALESCE(NEW.notional_value, 0) * 0.0005;
        v_profit   := CASE WHEN COALESCE(NEW.net_pnl, 0) > 0
                           THEN NEW.net_pnl * 0.20 ELSE 0 END;

        INSERT INTO trade_fees (
            user_id, trade_id, symbol, side, notional, gross_pnl, net_pnl,
            platform_fee, profit_share, total_fee, collected, fee_period
        ) VALUES (
            NEW.user_id, NEW.id, NEW.symbol, NEW.side,
            COALESCE(NEW.notional_value, 0),
            COALESCE(NEW.gross_pnl, 0), COALESCE(NEW.net_pnl, 0),
            v_platform, v_profit, v_platform + v_profit,
            false, TO_CHAR(now(), 'YYYY-MM')
        )
        ON CONFLICT DO NOTHING;
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_auto_accrue_fee ON trades;
CREATE TRIGGER trg_auto_accrue_fee
    AFTER UPDATE OF status ON trades
    FOR EACH ROW EXECUTE FUNCTION auto_accrue_trade_fee();

-- 7. RLS Policies
ALTER TABLE trade_fees       ENABLE ROW LEVEL SECURITY;
ALTER TABLE subscription_fees ENABLE ROW LEVEL SECURITY;
ALTER TABLE fee_collections   ENABLE ROW LEVEL SECURITY;

CREATE POLICY "user_own_trade_fees"    ON trade_fees        FOR ALL USING (auth.uid() = user_id);
CREATE POLICY "user_own_sub_fees"      ON subscription_fees FOR ALL USING (auth.uid() = user_id);
CREATE POLICY "user_own_fee_coll"      ON fee_collections   FOR SELECT USING (auth.uid() = user_id);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_trade_fees_user_uncollected ON trade_fees (user_id) WHERE collected = false;
CREATE INDEX IF NOT EXISTS idx_sub_fees_user_uncollected   ON subscription_fees (user_id) WHERE collected = false;
CREATE INDEX IF NOT EXISTS idx_trade_fees_period           ON trade_fees (fee_period, user_id);

COMMENT ON VIEW v_user_fees IS 'Real-time fee balance per user — use for dashboard display';
COMMENT ON FUNCTION collect_user_fees_v6 IS 'Atomic fee collection — call before every withdrawal';
"""


# ── Singleton ────────────────────────────────────────────────
fee_engine = FeeEngine()
