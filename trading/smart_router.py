"""
services/wallet_service.py — Enterprise Wallet Service
Handles atomic balance operations for demo/real/internal wallets.
All balance changes go through this service — never direct DB writes from routes.
"""
from __future__ import annotations
from decimal import Decimal, ROUND_DOWN
from typing import Literal
import uuid
from datetime import datetime, timezone

from core.database import db
from core.security import calculate_trade_fee, apply_token_discount
from core.config import settings
import structlog

log = structlog.get_logger("wallet_service")

WalletType = Literal["demo", "real", "internal"]


class WalletService:

    # ── Balance queries ────────────────────────────────────────────

    async def get_balance(self, user_id: str, wallet_type: WalletType) -> dict:
        wallet = await db.get_wallet(user_id, wallet_type)
        if not wallet:
            raise ValueError(f"Wallet not found: {user_id}/{wallet_type}")
        available = float(wallet["balance"]) - float(wallet["locked_balance"])
        return {
            "wallet_id": wallet["id"],
            "wallet_type": wallet_type,
            "balance": float(wallet["balance"]),
            "locked": float(wallet["locked_balance"]),
            "available": round(available, 8),
            "prepaid_credit": float(wallet["prepaid_credit"]),
            "total_deposited": float(wallet["total_deposited"]),
            "total_withdrawn": float(wallet["total_withdrawn"]),
            "total_fees_paid": float(wallet["total_fees_paid"]),
        }

    async def get_all_balances(self, user_id: str) -> dict:
        wallets = await db.get_wallets(user_id)
        return {w["wallet_type"]: {
            "balance": float(w["balance"]),
            "available": float(w["balance"]) - float(w["locked_balance"]),
            "prepaid_credit": float(w.get("prepaid_credit", 0)),
        } for w in wallets}

    # ── Atomic debit ───────────────────────────────────────────────

    async def debit(self, user_id: str, wallet_type: WalletType,
                    amount: float, description: str,
                    ref_id: str = None, ref_type: str = None,
                    ip: str = None) -> dict:
        """
        Atomically debit from wallet. Raises if insufficient funds.
        Uses DB function deduct_wallet_balance for atomicity.
        """
        if amount <= 0:
            raise ValueError("Debit amount must be positive")

        wallet = await db.get_wallet(user_id, wallet_type)
        if not wallet:
            raise ValueError(f"Wallet not found: {wallet_type}")

        # Atomic deduction via DB function
        result = db.rpc("deduct_wallet_balance", {
            "p_wallet_id": wallet["id"],
            "p_amount": amount,
            "p_lock": False,
        }).execute()

        if not result.data:
            raise ValueError(f"Insufficient funds in {wallet_type} wallet")

        # Record transaction
        txn = db.table("transactions").insert({
            "user_id": user_id,
            "wallet_id": wallet["id"],
            "type": "trade_debit" if "trade" in description.lower() else "adjustment",
            "amount": -amount,
            "fee": 0,
            "net_amount": -amount,
            "status": "completed",
            "reference_id": ref_id,
            "reference_type": ref_type,
            "description": description,
            "ip_address": ip,
            "processed_at": datetime.now(timezone.utc).isoformat(),
        }).execute()

        log.info("wallet_debit", user=user_id, type=wallet_type, amount=amount)
        return {"success": True, "transaction_id": txn.data[0]["id"] if txn.data else None}

    # ── Atomic credit ──────────────────────────────────────────────

    async def credit(self, user_id: str, wallet_type: WalletType,
                     amount: float, txn_type: str, description: str,
                     ref_id: str = None, ref_type: str = None,
                     ip: str = None) -> dict:
        """Atomically credit to wallet."""
        if amount <= 0:
            raise ValueError("Credit amount must be positive")

        wallet = await db.get_wallet(user_id, wallet_type)
        if not wallet:
            raise ValueError(f"Wallet not found: {wallet_type}")

        db.rpc("credit_wallet_balance", {
            "p_wallet_id": wallet["id"],
            "p_amount": amount,
        }).execute()

        txn = db.table("transactions").insert({
            "user_id": user_id,
            "wallet_id": wallet["id"],
            "type": txn_type,
            "amount": amount,
            "fee": 0,
            "net_amount": amount,
            "status": "completed",
            "reference_id": ref_id,
            "reference_type": ref_type,
            "description": description,
            "ip_address": ip,
            "processed_at": datetime.now(timezone.utc).isoformat(),
        }).execute()

        log.info("wallet_credit", user=user_id, type=wallet_type, amount=amount)
        return {"success": True, "transaction_id": txn.data[0]["id"] if txn.data else None}

    # ── Fee deduction (server-side enforced) ──────────────────────

    async def deduct_trade_fee(self, user_id: str, wallet_type: WalletType,
                                trade_id: str, gross_amount: float) -> dict:
        """
        Calculate and deduct platform fee for a trade.
        Fee rate determined server-side only — checks user token.
        """
        # Get user token (if any)
        token = await db.get_user_token(user_id)
        base_fee = settings.TRADING_FEE_PCT

        if token and token.get("monthly_tokens"):
            t = token["monthly_tokens"]
            effective_pct = apply_token_discount(base_fee, t["token_type"], float(t.get("discount_pct", 0)))
            discount_pct = float(t.get("discount_pct", 0))
            token_type = t["token_type"]
            token_id = t["id"]
        else:
            effective_pct = base_fee
            discount_pct = 0.0
            token_type = None
            token_id = None

        fee_amount = calculate_trade_fee(gross_amount, effective_pct)

        if fee_amount <= 0:
            return {"fee_amount": 0, "fee_pct": effective_pct, "discount_pct": discount_pct}

        # Debit fee from wallet
        wallet = await db.get_wallet(user_id, wallet_type)
        db.rpc("deduct_wallet_balance", {
            "p_wallet_id": wallet["id"],
            "p_amount": fee_amount,
            "p_lock": False,
        }).execute()

        # Update wallet fee tracker
        db.table("wallets").update({
            "total_fees_paid": f"total_fees_paid + {fee_amount}"
        }).eq("id", wallet["id"]).execute()

        # Record fee transaction
        db.table("transactions").insert({
            "user_id": user_id,
            "wallet_id": wallet["id"],
            "type": "fee_debit",
            "amount": -fee_amount,
            "fee": fee_amount,
            "net_amount": -fee_amount,
            "status": "completed",
            "reference_id": trade_id,
            "reference_type": "trade",
            "description": f"Platform trading fee {effective_pct*100:.4f}%",
            "processed_at": datetime.now(timezone.utc).isoformat(),
        }).execute()

        # Record in fee ledger
        db.table("platform_fee_ledger").insert({
            "trade_id": trade_id,
            "user_id": user_id,
            "fee_type": "trading",
            "fee_pct": effective_pct,
            "gross_amount": gross_amount,
            "fee_amount": fee_amount,
            "mode": wallet_type,
            "token_override": token_id is not None,
            "discount_pct": discount_pct,
            "net_fee": fee_amount,
        }).execute()

        # Credit platform wallet
        db.table("platform_wallet").update({
            "balance": db.table("platform_wallet")
                         .select("balance").eq("wallet_key", "main_earnings")
                         .single().execute().data["balance"] + fee_amount,
            "total_earned": db.table("platform_wallet")
                              .select("total_earned").eq("wallet_key", "main_earnings")
                              .single().execute().data["total_earned"] + fee_amount,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }).eq("wallet_key", "main_earnings").execute()

        # Log token usage if applicable
        if token_id:
            db.table("token_usage_logs").insert({
                "user_id": user_id,
                "token_id": token_id,
                "trade_id": trade_id,
                "fee_saved": calculate_trade_fee(gross_amount, base_fee) - fee_amount,
                "discount_applied": discount_pct,
            }).execute()

        log.info("fee_deducted", user=user_id, amount=fee_amount, pct=effective_pct,
                 discount=discount_pct, token=token_type)

        return {
            "fee_amount": fee_amount,
            "fee_pct": effective_pct,
            "discount_pct": discount_pct,
            "token_type": token_type,
        }

    # ── Prepaid credit system ──────────────────────────────────────

    async def load_prepaid(self, user_id: str, amount: float, description: str = "") -> dict:
        """Load prepaid trading credit from real wallet."""
        # First debit real wallet
        await self.debit(user_id, "real", amount, "Prepaid credit load")

        # Credit internal wallet prepaid
        wallet = await db.get_wallet(user_id, "internal")
        db.table("wallets").update({
            "prepaid_credit": float(wallet.get("prepaid_credit", 0)) + amount,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", wallet["id"]).execute()

        db.table("prepaid_ledger").insert({
            "user_id": user_id,
            "wallet_id": wallet["id"],
            "type": "load",
            "amount": amount,
            "balance_after": float(wallet.get("prepaid_credit", 0)) + amount,
            "notes": description,
        }).execute()

        return {"prepaid_loaded": amount}

    async def check_prepaid_balance(self, user_id: str) -> float:
        wallet = await db.get_wallet(user_id, "internal")
        return float(wallet.get("prepaid_credit", 0)) if wallet else 0.0

    async def send_low_balance_alert(self, user_id: str, balance: float):
        """Alert user when prepaid balance is critically low."""
        if balance < 5.0:
            db.table("system_logs").insert({
                "level": "WARNING",
                "module": "wallet_service",
                "message": f"Low prepaid balance for user {user_id}: ${balance:.2f}",
                "context": {"user_id": user_id, "balance": balance}
            }).execute()
            log.warning("low_prepaid_balance", user=user_id, balance=balance)

    # ── Deposit / Withdrawal processing ───────────────────────────

    async def execute_withdrawal(self, withdrawal_id: str) -> dict:
        """
        Execute a withdrawal request.
        ALWAYS collects all accrued fees FIRST before releasing funds.
        Called by Celery worker or direct API.
        """
        req = (db.table("payment_requests").select("*")
               .eq("id", withdrawal_id).eq("direction","withdrawal")
               .single().execute()).data
        if not req:
            raise ValueError("Withdrawal not found")
        if req["status"] != "pending_approval":
            raise ValueError(f"Withdrawal already {req['status']}")

        user_id    = req["user_id"]
        amount_usd = float(req["amount_usd"])

        # ── STEP 1: Collect all accrued fees first ──────────────
        from services.fee_engine import fee_engine
        fee_result = await fee_engine.collect_before_withdrawal(user_id, amount_usd)

        if not fee_result.get("collected"):
            reason = fee_result.get("reason","UNKNOWN")
            db.table("payment_requests").update({
                "status": "fee_collection_failed",
                "notes": f"Fee collection failed: {reason} — fees due: ${fee_result.get('fees_collected',0):.4f}",
            }).eq("id", withdrawal_id).execute()
            return {
                "success":       False,
                "reason":        reason,
                "fee_breakdown": fee_result.get("breakdown"),
                "action_needed": "Top up wallet to cover outstanding fees before withdrawing",
            }

        # ── STEP 2: Deduct withdrawal amount from wallet ─────────
        wallet = await db.get_wallet(user_id, "live")
        if not wallet or float(wallet["balance"]) < amount_usd:
            return {"success": False, "reason": "INSUFFICIENT_BALANCE_AFTER_FEES"}

        await self.deduct(user_id, "live", amount_usd, "withdrawal",
                          f"Withdrawal {withdrawal_id[:8]}", ref_id=withdrawal_id)

        # ── STEP 3: Process via payment provider ─────────────────
        method = req.get("payment_method","")
        phone  = req.get("phone_number","")
        provider_result = {}
        try:
            from services.payment_service import payment_service
            if method in ("mpesa","airtel","tigo","mobilemoney"):
                rate  = float(req.get("exchange_rate", 2600))
                local = int(amount_usd * rate)
                if hasattr(payment_service, "mpesa"):
                    provider_result = await payment_service.mpesa.b2c_transfer(
                        phone, local, f"ESTRADE withdrawal {withdrawal_id[:8]}"
                    )
            elif method == "flutterwave":
                if hasattr(payment_service, "flutterwave"):
                    provider_result = await payment_service.flutterwave.initiate_payment(
                        user_id, amount_usd, req.get("email",""), phone, "", "USD"
                    )
        except Exception as e:
            log.error("withdrawal_provider_error", error=str(e), withdrawal_id=withdrawal_id)
            provider_result = {"error": str(e)}

        # ── STEP 4: Update request status ─────────────────────────
        db.table("payment_requests").update({
            "status":           "completed",
            "completed_at":     datetime.now(timezone.utc).isoformat(),
            "provider_response": provider_result,
            "fees_collected":    fee_result.get("fees_collected", 0),
        }).eq("id", withdrawal_id).execute()

        # ── STEP 5: Update wallet totals ──────────────────────────
        db.table("wallets").update({
            "total_withdrawn": float(wallet.get("total_withdrawn",0)) + amount_usd
        }).eq("id", wallet["id"]).execute()

        log.info("withdrawal_completed",
                 withdrawal_id=withdrawal_id, amount=amount_usd,
                 fees_collected=fee_result.get("fees_collected",0))
        return {
            "success":         True,
            "amount_usd":      amount_usd,
            "fees_collected":  fee_result.get("fees_collected",0),
            "fee_breakdown":   fee_result.get("breakdown"),
            "provider_result": provider_result,
        }

    async def deduct(self, user_id: str, mode: str, amount: float,
                      txn_type: str, description: str, ref_id: str = None) -> bool:
        """Deduct amount from wallet. Atomic via RPC."""
        try:
            wallet = await db.get_wallet(user_id, mode)
            if not wallet or float(wallet["balance"]) < amount:
                raise ValueError("Insufficient balance")
            db.rpc("deduct_wallet_balance", {
                "p_wallet_id": wallet["id"],
                "p_amount": amount,
                "p_lock": False,
            }).execute()
            db.table("transactions").insert({
                "user_id": user_id, "wallet_id": wallet["id"],
                "txn_type": txn_type, "amount": -amount,
                "description": description, "ref_id": ref_id,
            }).execute()
            return True
        except Exception as e:
            log.error("deduct_error", error=str(e), user=user_id)
            raise

    async def process_deposit_confirmation(self, payment_id: str, amount_usd: float,
                                           admin_id: str) -> dict:
        """Admin confirms payment — credits user real wallet."""
        payment = db.table("payment_requests").select("*").eq("id", payment_id).single().execute().data
        if not payment:
            raise ValueError("Payment request not found")
        if payment["status"] != "pending":
            raise ValueError(f"Payment already {payment['status']}")
        if payment["direction"] != "deposit":
            raise ValueError("Not a deposit request")

        # Credit real wallet
        await self.credit(
            user_id=payment["user_id"],
            wallet_type="real",
            amount=amount_usd,
            txn_type="deposit",
            description=f"Deposit via {payment['payment_method'].upper()}",
            ref_id=payment_id,
            ref_type="payment_request",
        )

        # Update deposit total
        wallet = await db.get_wallet(payment["user_id"], "real")
        db.table("wallets").update({
            "total_deposited": float(wallet["total_deposited"]) + amount_usd,
        }).eq("id", wallet["id"]).execute()

        # Update payment status
        db.table("payment_requests").update({
            "status": "completed",
            "amount_usd": amount_usd,
            "admin_approved_by": admin_id,
            "admin_approved_at": datetime.now(timezone.utc).isoformat(),
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", payment_id).execute()

        await db.log_audit(payment["user_id"], admin_id, "deposit_confirmed",
                           "payment_request", payment_id,
                           new_vals={"amount_usd": amount_usd})

        return {"success": True, "deposited": amount_usd}


wallet_service = WalletService()
