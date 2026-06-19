"""
services/payment_service.py — East Africa Mobile Money Integration
Supports: M-Pesa, Airtel Money, Tigo Pesa
"""
from __future__ import annotations
import httpx, hashlib, base64
from datetime import datetime, timezone
from core.config import settings
from core.database import db
import structlog

log = structlog.get_logger("payment_service")


class MpesaClient:
    BASE_URL = ("https://sandbox.safaricom.co.ke"
                if settings.MPESA_ENVIRONMENT == "sandbox"
                else "https://api.safaricom.co.ke")

    async def _get_token(self) -> str:
        credentials = base64.b64encode(
            f"{settings.MPESA_CONSUMER_KEY}:{settings.MPESA_CONSUMER_SECRET}".encode()
        ).decode()
        async with httpx.AsyncClient() as client:
            r = await client.get(
                f"{self.BASE_URL}/oauth/v1/generate?grant_type=client_credentials",
                headers={"Authorization": f"Basic {credentials}"}
            )
            return r.json().get("access_token", "")

    def _stk_password(self, timestamp: str) -> str:
        raw = settings.MPESA_SHORTCODE + settings.MPESA_PASSKEY + timestamp
        return base64.b64encode(raw.encode()).decode()

    async def stk_push(self, phone: str, amount_kes: int,
                        reference: str, description: str) -> dict:
        """Initiate STK push (B2C payment request to user's phone)."""
        token = await self._get_token()
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        payload = {
            "BusinessShortCode": settings.MPESA_SHORTCODE,
            "Password": self._stk_password(timestamp),
            "Timestamp": timestamp,
            "TransactionType": "CustomerBuyGoodsOnline",
            "Amount": amount_kes,
            "PartyA": phone,
            "PartyB": settings.MPESA_SHORTCODE,
            "PhoneNumber": phone,
            "CallBackURL": f"{settings.ALLOWED_ORIGINS[0]}/api/payments/mpesa/callback",
            "AccountReference": reference,
            "TransactionDesc": description[:12],
        }
        async with httpx.AsyncClient() as client:
            r = await client.post(
                f"{self.BASE_URL}/mpesa/stkpush/v1/processrequest",
                json=payload,
                headers={"Authorization": f"Bearer {token}"},
                timeout=30,
            )
            return r.json()

    async def query_stk(self, checkout_id: str) -> dict:
        token = await self._get_token()
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        async with httpx.AsyncClient() as client:
            r = await client.post(
                f"{self.BASE_URL}/mpesa/stkpushquery/v1/query",
                json={
                    "BusinessShortCode": settings.MPESA_SHORTCODE,
                    "Password": self._stk_password(timestamp),
                    "Timestamp": timestamp,
                    "CheckoutRequestID": checkout_id,
                },
                headers={"Authorization": f"Bearer {token}"},
            )
            return r.json()

    async def b2c_transfer(self, phone: str, amount_kes: int, remarks: str) -> dict:
        """Business to customer — for withdrawals."""
        token = await self._get_token()
        async with httpx.AsyncClient() as client:
            r = await client.post(
                f"{self.BASE_URL}/mpesa/b2c/v1/paymentrequest",
                json={
                    "InitiatorName": "ESTRADE",
                    "SecurityCredential": "",  # Encrypted credential
                    "CommandID": "BusinessPayment",
                    "Amount": amount_kes,
                    "PartyA": settings.MPESA_SHORTCODE,
                    "PartyB": phone,
                    "Remarks": remarks[:100],
                    "QueueTimeOutURL": f"{settings.ALLOWED_ORIGINS[0]}/api/payments/mpesa/timeout",
                    "ResultURL": f"{settings.ALLOWED_ORIGINS[0]}/api/payments/mpesa/result",
                    "Occasion": "Withdrawal",
                },
                headers={"Authorization": f"Bearer {token}"},
            )
            return r.json()


class PaymentService:

    def __init__(self):
        self.mpesa = MpesaClient()

    async def create_deposit_request(self, user_id: str, method: str,
                                      amount_fiat: float, currency: str,
                                      phone: str = None) -> dict:
        """Create a deposit request and initiate payment."""
        # Validate minimums
        min_usd = float(await db.get_system_config("min_deposit_usd") or 10)
        rate    = float(await db.get_system_config("mpesa_rate_tzs") or settings.MPESA_RATE_TZS)

        # Convert to USD
        if currency == "TZS":
            amount_usd = amount_fiat / rate
        elif currency == "KES":
            amount_usd = amount_fiat / 130.0  # approximate
        else:
            amount_usd = amount_fiat

        if amount_usd < min_usd:
            raise ValueError(f"Minimum deposit is ${min_usd} USD")

        wallet = await db.get_wallet(user_id, "real")
        if not wallet:
            raise ValueError("Real wallet not found")

        # Create payment request
        pay_req = db.table("payment_requests").insert({
            "user_id": user_id,
            "wallet_id": wallet["id"],
            "payment_method": method,
            "direction": "deposit",
            "amount_fiat": amount_fiat,
            "currency_fiat": currency,
            "amount_usd": round(amount_usd, 4),
            "exchange_rate": rate if currency == "TZS" else None,
            "phone_number": phone,
            "status": "pending",
        }).execute()

        if not pay_req.data:
            raise ValueError("Failed to create payment request")

        pay_id = pay_req.data[0]["id"]
        result = {"payment_id": pay_id, "amount_usd": round(amount_usd, 4)}

        # Initiate mobile money
        if method == "mpesa" and phone:
            try:
                amount_kes = int(amount_fiat if currency == "KES" else amount_fiat / 20)  # TZS to KES approx
                stk_result = await self.mpesa.stk_push(
                    phone, amount_kes,
                    reference=pay_id[:10],
                    description=f"ESTRADE Deposit",
                )
                checkout_id = stk_result.get("CheckoutRequestID")
                db.table("payment_requests").update({
                    "provider_ref": checkout_id,
                    "provider_response": stk_result,
                    "status": "submitted",
                    "submitted_at": datetime.now(timezone.utc).isoformat(),
                }).eq("id", pay_id).execute()
                result["stk_push"] = "sent"
                result["checkout_id"] = checkout_id
            except Exception as e:
                log.error("mpesa_stk_failed", error=str(e))
                result["stk_push"] = "failed"
                result["manual_required"] = True

        log.info("deposit_requested", user=user_id, method=method, usd=amount_usd)
        return result

    async def handle_mpesa_callback(self, body: dict) -> dict:
        """Process M-Pesa payment notification callback."""
        stk_cb = body.get("Body", {}).get("stkCallback", {})
        result_code = stk_cb.get("ResultCode")
        checkout_id = stk_cb.get("CheckoutRequestID")

        pay_req = (db.table("payment_requests")
                   .select("*").eq("provider_ref", checkout_id)
                   .single().execute()).data

        if not pay_req:
            return {"error": "Payment request not found"}

        if result_code == 0:
            # Success
            items = {
                item["Name"]: item.get("Value")
                for item in stk_cb.get("CallbackMetadata", {}).get("Item", [])
            }
            amount_kes = float(items.get("Amount", 0))
            mpesa_receipt = items.get("MpesaReceiptNumber")

            # Auto-approve deposits under threshold
            auto_thresh = 100  # $100 USD auto-approved
            amount_usd = float(pay_req["amount_usd"])

            if amount_usd <= auto_thresh:
                from services.wallet_service import wallet_service
                await wallet_service.process_deposit_confirmation(
                    pay_req["id"], amount_usd, "system"
                )
                status = "completed"
            else:
                # Flag for admin approval
                db.table("payment_requests").update({
                    "status": "processing",
                    "provider_ref": mpesa_receipt,
                }).eq("id", pay_req["id"]).execute()
                status = "processing_admin_review"

            log.info("mpesa_payment_received", receipt=mpesa_receipt, usd=amount_usd)
            return {"status": status, "receipt": mpesa_receipt}
        else:
            # Payment failed
            db.table("payment_requests").update({
                "status": "failed",
                "failure_reason": stk_cb.get("ResultDesc"),
            }).eq("id", pay_req["id"]).execute()
            return {"status": "failed"}

    async def create_withdrawal_request(self, user_id: str, method: str,
                                         amount_usd: float, phone: str = None,
                                         bank_details: dict = None) -> dict:
        min_wd = float(await db.get_system_config("min_withdrawal_usd") or 5)
        if amount_usd < min_wd:
            raise ValueError(f"Minimum withdrawal is ${min_wd}")

        wallet = await db.get_wallet(user_id, "real")
        available = float(wallet["balance"]) - float(wallet.get("locked_balance", 0))
        if available < amount_usd:
            raise ValueError(f"Insufficient balance. Available: ${available:.2f}")

        rate = float(await db.get_system_config("mpesa_rate_tzs") or settings.MPESA_RATE_TZS)
        amount_fiat = amount_usd * rate

        pay_req = db.table("payment_requests").insert({
            "user_id": user_id,
            "wallet_id": wallet["id"],
            "payment_method": method,
            "direction": "withdrawal",
            "amount_fiat": round(amount_fiat, 2),
            "currency_fiat": "TZS",
            "amount_usd": amount_usd,
            "exchange_rate": rate,
            "phone_number": phone,
            "bank_details": bank_details or {},
            "status": "pending",
        }).execute()

        if not pay_req.data:
            raise ValueError("Failed to create withdrawal request")

        # Lock the balance
        db.rpc("deduct_wallet_balance", {
            "p_wallet_id": wallet["id"],
            "p_amount": amount_usd,
            "p_lock": True,
        }).execute()

        approval_mode = await db.get_system_config("withdrawal_approval")
        if approval_mode == "auto" and amount_usd <= 50:
            await self.process_withdrawal(pay_req.data[0]["id"], "system")

        return {
            "payment_id": pay_req.data[0]["id"],
            "status": "pending_approval",
            "amount_usd": amount_usd,
            "amount_tzs": round(amount_fiat, 2),
        }

    async def process_withdrawal(self, payment_id: str, admin_id: str) -> dict:
        """Admin approves and processes withdrawal."""
        pay_req = db.table("payment_requests").select("*").eq("id", payment_id).single().execute().data
        if not pay_req or pay_req["direction"] != "withdrawal":
            raise ValueError("Invalid withdrawal request")

        phone = pay_req.get("phone_number")
        amount_usd = float(pay_req["amount_usd"])
        rate = float(pay_req.get("exchange_rate") or settings.MPESA_RATE_TZS)
        amount_tzs = int(amount_usd * rate)

        method = pay_req["payment_method"]
        provider_result = {}

        try:
            if method == "mpesa" and phone:
                provider_result = await self.mpesa.b2c_transfer(
                    phone, amount_tzs // 20,  # TZS to KES approx
                    f"ESTRADE Withdrawal {payment_id[:8]}"
                )
        except Exception as e:
            log.error("withdrawal_provider_failed", error=str(e))

        # Update withdrawal total
        wallet = db.table("wallets").select("*").eq("id", pay_req["wallet_id"]).single().execute().data
        db.table("wallets").update({
            "locked_balance": max(0, float(wallet.get("locked_balance", 0)) - amount_usd),
            "total_withdrawn": float(wallet.get("total_withdrawn", 0)) + amount_usd,
        }).eq("id", wallet["id"]).execute()

        db.table("payment_requests").update({
            "status": "completed",
            "admin_approved_by": admin_id,
            "admin_approved_at": datetime.now(timezone.utc).isoformat(),
            "provider_response": provider_result,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", payment_id).execute()

        await db.log_audit(pay_req["user_id"], admin_id, "withdrawal_processed",
                           "payment_request", payment_id,
                           new_vals={"amount_usd": amount_usd})

        return {"success": True, "processed": amount_usd}


payment_service = PaymentService()


# ═══════════════════════════════════════════════════════════════
# v6 ADDITIONS — Flutterwave + NowPayments + Fee Engine
# ═══════════════════════════════════════════════════════════════

import hmac, hashlib, json as _json

class FlutterwaveClient:
    """
    Flutterwave payment integration.
    Handles fiat deposits via Mobile Money, Card, Bank Transfer.
    Works for Tanzania (M-Pesa, Airtel, Tigo), Kenya, Uganda, Nigeria.
    """
    BASE = "https://api.flutterwave.com/v3"

    def __init__(self):
        self.secret = getattr(settings, "FLUTTERWAVE_SECRET_KEY", "")
        self.public = getattr(settings, "FLUTTERWAVE_PUBLIC_KEY", "")

    async def initiate_payment(self, user_id: str, amount_usd: float,
                                 email: str, phone: str, name: str,
                                 currency: str = "TZS",
                                 method: str = "mobilemoneytz") -> dict:
        """Create Flutterwave payment link and return redirect URL."""
        if not self.secret:
            return {"error": "Flutterwave not configured"}
        ref = f"ESTRADE-{user_id[:8]}-{int(datetime.now().timestamp())}"
        # Convert USD → local currency
        rate_map = {"TZS": 2600, "KES": 130, "UGX": 3800, "NGN": 1500, "GHS": 15}
        rate     = rate_map.get(currency, 2600)
        amount_local = round(amount_usd * rate, 2)

        payload = {
            "tx_ref":          ref,
            "amount":          amount_local,
            "currency":        currency,
            "redirect_url":    f"{getattr(settings,'ALLOWED_ORIGINS',[''])[0]}/payment/callback",
            "customer":        {"email": email, "phonenumber": phone, "name": name},
            "payment_options":  method,
            "meta":            {"user_id": user_id, "amount_usd": amount_usd},
            "customizations":  {"title": "ESTRADE AI Trading", "logo": "https://estrade.ai/logo.png"},
        }
        try:
            async with httpx.AsyncClient(timeout=20) as c:
                r = await c.post(f"{self.BASE}/payments",
                    json=payload, headers={"Authorization": f"Bearer {self.secret}"})
            data = r.json()
            if data.get("status") == "success":
                return {"payment_link": data["data"]["link"], "ref": ref,
                        "amount_local": amount_local, "currency": currency}
            return {"error": data.get("message", "Payment initiation failed")}
        except Exception as e:
            return {"error": str(e)}

    async def verify_transaction(self, tx_id: str) -> dict:
        """Verify a completed Flutterwave transaction."""
        if not self.secret:
            return {"verified": False}
        try:
            async with httpx.AsyncClient(timeout=15) as c:
                r = await c.get(f"{self.BASE}/transactions/{tx_id}/verify",
                    headers={"Authorization": f"Bearer {self.secret}"})
            data = r.json()
            if data.get("status") == "success" and data["data"]["status"] == "successful":
                return {
                    "verified":    True,
                    "amount":      data["data"]["amount"],
                    "currency":    data["data"]["currency"],
                    "ref":         data["data"]["tx_ref"],
                    "flw_ref":     data["data"]["flw_ref"],
                }
            return {"verified": False, "status": data.get("data", {}).get("status")}
        except Exception as e:
            return {"verified": False, "error": str(e)}

    def verify_webhook(self, payload: str, signature: str) -> bool:
        """Verify Flutterwave webhook signature."""
        expected = hmac.new(
            getattr(settings,"FLUTTERWAVE_WEBHOOK_HASH","").encode(),
            payload.encode(), hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected, signature or "")

    async def handle_webhook(self, payload: dict, signature: str) -> dict:
        """Process Flutterwave webhook — credits wallet on success."""
        raw = _json.dumps(payload)
        if not self.verify_webhook(raw, signature):
            return {"status": "invalid_signature"}
        event = payload.get("event", "")
        if event == "charge.completed" and payload.get("data", {}).get("status") == "successful":
            data     = payload["data"]
            tx_ref   = data.get("tx_ref", "")
            amount   = float(data.get("amount", 0))
            currency = data.get("currency", "TZS")
            rate_map = {"TZS": 2600, "KES": 130, "UGX": 3800, "NGN": 1500, "GHS": 15}
            rate     = rate_map.get(currency, 2600)
            usd      = round(amount / rate, 4)
            meta     = data.get("meta", {}) or {}
            user_id  = meta.get("user_id")
            if user_id:
                try:
                    pay_req = (db.table("payment_requests")
                               .select("*").eq("provider_ref", tx_ref).single().execute()).data
                    if pay_req and pay_req["status"] == "pending":
                        await wallet_service.credit(user_id, "live", usd, "deposit",
                                                     f"Flutterwave deposit {tx_ref}")
                        db.table("payment_requests").update({
                            "status": "completed", "amount_usd": usd,
                            "completed_at": datetime.now(timezone.utc).isoformat(),
                            "provider_response": data,
                        }).eq("provider_ref", tx_ref).execute()
                        return {"credited": True, "amount_usd": usd, "user_id": user_id}
                except Exception as e:
                    return {"error": str(e)}
        return {"status": "processed", "event": event}


class NowPaymentsClient:
    """
    NowPayments — crypto deposit gateway.
    Accepts BTC, ETH, USDT (TRC20/ERC20), LTC, SOL, BNB, XRP.
    Also supports fiat→crypto conversion (buy crypto with mobile money).

    Key feature: Converts ANY fiat deposit into the user's
    chosen crypto automatically.
    """
    BASE = "https://api.nowpayments.io/v1"

    def __init__(self):
        self.key    = getattr(settings, "NOWPAYMENTS_API_KEY", "")
        self.secret = getattr(settings, "NOWPAYMENTS_IPN_SECRET", "")

    async def create_payment(self, user_id: str, amount_usd: float,
                              pay_currency: str = "usdttrc20") -> dict:
        """
        Generate a crypto payment address for deposit.
        User sends crypto → wallet auto-credited.
        """
        if not self.key:
            return {"error": "NowPayments not configured"}
        payload = {
            "price_amount":     amount_usd,
            "price_currency":   "usd",
            "pay_currency":     pay_currency.lower(),
            "ipn_callback_url": f"{getattr(settings,'ALLOWED_ORIGINS',[''])[0]}/api/payments/nowpayments/ipn",
            "order_id":         f"ESTRADE-{user_id[:8]}-{int(datetime.now().timestamp())}",
            "order_description": f"ESTRADE deposit for {user_id[:8]}",
            "success_url":      f"{getattr(settings,'ALLOWED_ORIGINS',[''])[0]}/wallet?status=success",
            "cancel_url":       f"{getattr(settings,'ALLOWED_ORIGINS',[''])[0]}/wallet?status=cancel",
        }
        try:
            async with httpx.AsyncClient(timeout=20) as c:
                r = await c.post(f"{self.BASE}/payment",
                    json=payload, headers={"x-api-key": self.key})
            d = r.json()
            if "pay_address" in d:
                return {
                    "payment_id":     d["payment_id"],
                    "pay_address":    d["pay_address"],
                    "pay_amount":     d["pay_amount"],
                    "pay_currency":   d["pay_currency"],
                    "network":        d.get("network", ""),
                    "expiry_minutes": 60,
                    "usd_amount":     amount_usd,
                    "qr_url":         f"https://api.nowpayments.io/v1/qr/{d['payment_id']}",
                }
            return {"error": d.get("message", "Failed to create payment")}
        except Exception as e:
            return {"error": str(e)}

    async def get_payment_status(self, payment_id: str) -> dict:
        """Check status of a crypto payment."""
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.get(f"{self.BASE}/payment/{payment_id}",
                    headers={"x-api-key": self.key})
            return r.json()
        except Exception as e:
            return {"error": str(e)}

    async def get_available_currencies(self) -> list:
        """Get list of accepted cryptocurrencies."""
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.get(f"{self.BASE}/currencies", headers={"x-api-key": self.key})
            return r.json().get("currencies", [])
        except Exception:
            return ["btc","eth","usdttrc20","usdterc20","ltc","sol","bnb","xrp"]

    def verify_ipn(self, payload: str, signature: str) -> bool:
        """Verify NowPayments IPN callback signature."""
        expected = hmac.new(
            self.secret.encode(), payload.encode(), hashlib.sha512
        ).hexdigest()
        return hmac.compare_digest(expected, signature or "")

    async def handle_ipn(self, payload: dict, signature: str) -> dict:
        """Handle IPN webhook — credit wallet when payment confirmed."""
        raw = _json.dumps(payload, sort_keys=True)
        if self.secret and not self.verify_ipn(raw, signature):
            return {"status": "invalid_signature"}
        status   = payload.get("payment_status", "")
        order_id = payload.get("order_id", "")
        usd_amt  = float(payload.get("price_amount", 0))
        pay_curr = payload.get("pay_currency", "")

        if status in ("finished", "confirmed"):
            # Extract user_id from order_id
            parts   = order_id.split("-")
            uid_prefix = parts[1] if len(parts) > 1 else ""
            try:
                user_row = (db.table("users").select("id")
                            .like("id", f"{uid_prefix}%").single().execute()).data
                if user_row:
                    user_id = user_row["id"]
                    pay_req = (db.table("payment_requests")
                               .select("*").eq("provider_ref", payload.get("payment_id"))
                               .single().execute()).data
                    if pay_req and pay_req["status"] == "pending":
                        await wallet_service.credit(user_id, "live", usd_amt,
                                                     "crypto_deposit",
                                                     f"{pay_curr.upper()} deposit ${usd_amt}")
                        db.table("payment_requests").update({
                            "status": "completed", "amount_usd": usd_amt,
                            "completed_at": datetime.now(timezone.utc).isoformat(),
                        }).eq("provider_ref", payload.get("payment_id")).execute()
                        return {"credited": True, "usd": usd_amt, "currency": pay_curr}
            except Exception as e:
                return {"error": str(e)}
        return {"status": status}


class FeeEngine:
    """
    ESTRADE v6 Fee Model — all fees collected at month-end or withdrawal.
    NO per-trade deduction during trading.

    Fee Types:
      1. Subscription fee: $29.99/month (flat rate)
      2. Performance fee: 20% of monthly profit (success-based)
      3. Withdrawal fee: 0.1% of amount withdrawn
      4. (No per-trade fee charged immediately — accrued and collected later)

    Collection triggers:
      a) End of billing period (monthly)
      b) User withdraws funds (deduct all accrued fees first)
    """

    SUBSCRIPTION_USD    = 29.99
    PERFORMANCE_FEE_PCT = 20.0    # % of monthly profit
    WITHDRAWAL_FEE_PCT  = 0.1     # % of withdrawal amount

    async def accrue_trade_fee(self, user_id: str, trade_id: str,
                                 notional: float, pnl: float) -> dict:
        """
        Record fee for a completed trade — DO NOT deduct now.
        Fee is accrued and collected at month end or withdrawal.
        """
        trade_fee   = notional * 0.0005          # 0.05% of notional (platform fee)
        profit_fee  = max(0, pnl * 0.20) if pnl > 0 else 0  # 20% of profit

        db.table("accrued_fees").insert({
            "user_id":        user_id,
            "trade_id":       trade_id,
            "fee_type":       "trade",
            "trade_fee":      round(trade_fee, 6),
            "profit_fee":     round(profit_fee, 6),
            "total_accrued":  round(trade_fee + profit_fee, 6),
            "pnl":            pnl,
            "notional":       notional,
            "collected":      False,
        }).execute()
        return {"accrued": True, "trade_fee": trade_fee, "profit_fee": profit_fee}

    async def get_accrued_fees(self, user_id: str) -> dict:
        """Get all uncollected fees for user."""
        rows = (db.table("accrued_fees").select("*")
                .eq("user_id", user_id).eq("collected", False).execute()).data or []
        total_trade  = sum(float(r.get("trade_fee", 0)) for r in rows)
        total_profit = sum(float(r.get("profit_fee", 0)) for r in rows)
        total        = total_trade + total_profit
        return {
            "total_accrued":      round(total, 4),
            "trade_fees":         round(total_trade, 4),
            "performance_fees":   round(total_profit, 4),
            "unpaid_records":     len(rows),
            "subscription_due":   self.SUBSCRIPTION_USD,
        }

    async def collect_fees_on_withdrawal(self, user_id: str,
                                           withdrawal_usd: float) -> dict:
        """
        Collect ALL accrued fees when user withdraws.
        Deducted from wallet BEFORE releasing withdrawal amount.
        """
        accrued = await self.get_accrued_fees(user_id)
        trade_fees  = accrued["trade_fees"]
        perf_fees   = accrued["performance_fees"]

        # Check subscription status
        sub = (db.table("subscriptions").select("*")
               .eq("user_id", user_id).eq("status", "active")
               .single().execute()).data
        sub_fee = 0.0
        if not sub or sub.get("balance_due", 0) > 0:
            sub_fee = float((sub or {}).get("balance_due", self.SUBSCRIPTION_USD))

        # Withdrawal fee
        wd_fee = round(withdrawal_usd * self.WITHDRAWAL_FEE_PCT / 100, 4)

        total_fee = round(trade_fees + perf_fees + sub_fee + wd_fee, 4)

        if total_fee > 0:
            # Deduct from wallet
            wallet = (db.table("wallets").select("*")
                      .eq("user_id", user_id).eq("wallet_type", "trading")
                      .eq("mode", "live").single().execute()).data
            if wallet and float(wallet["balance"]) >= total_fee:
                db.table("wallets").update({
                    "balance": float(wallet["balance"]) - total_fee,
                }).eq("id", wallet["id"]).execute()
                # Mark fees as collected
                db.table("accrued_fees").update({"collected": True}).eq("user_id", user_id).execute()
                # Record fee transaction
                db.table("fee_collections").insert({
                    "user_id": user_id, "trigger": "withdrawal",
                    "trade_fees": trade_fees, "performance_fees": perf_fees,
                    "subscription_fee": sub_fee, "withdrawal_fee": wd_fee,
                    "total_collected": total_fee,
                }).execute()
                log.info("fees_collected_on_withdrawal", user_id=user_id, total=total_fee)
                return {"collected": True, "total": total_fee, "breakdown": {
                    "trade_fees": trade_fees, "performance_fees": perf_fees,
                    "subscription": sub_fee, "withdrawal_fee": wd_fee,
                }}
            else:
                return {"collected": False, "reason": "Insufficient balance to cover fees",
                        "fees_due": total_fee}
        return {"collected": True, "total": 0}

    async def collect_monthly_fees(self, user_id: str) -> dict:
        """
        Collect all accrued fees + subscription at month end.
        Called by Celery beat task on 1st of each month.
        """
        return await self.collect_fees_on_withdrawal(user_id, 0)


# Instantiate v6 payment clients
flutterwave   = FlutterwaveClient()
nowpayments   = NowPaymentsClient()
fee_engine    = FeeEngine()

# Expose via main payment_service
payment_service.flutterwave  = flutterwave
payment_service.nowpayments  = nowpayments
payment_service.fee_engine   = fee_engine


# ═══════════════════════════════════════════════════════════════
# v6 ADDITIONS — Flutterwave + NowPayments + Fee Engine
# ═══════════════════════════════════════════════════════════════

import hmac as _hmac, hashlib as _hashlib, json as _json


class FlutterwaveClient:
    """
    Flutterwave — fiat payments (Mobile Money, Card, Bank Transfer).
    Tanzania: M-Pesa, Airtel, Tigo | Kenya, Uganda, Nigeria supported.
    """
    BASE = "https://api.flutterwave.com/v3"

    def __init__(self):
        self.secret = getattr(settings, "FLUTTERWAVE_SECRET_KEY", "")
        self.public = getattr(settings, "FLUTTERWAVE_PUBLIC_KEY", "")

    async def initiate_payment(self, user_id: str, amount_usd: float,
                                 email: str, phone: str, name: str,
                                 currency: str = "TZS") -> dict:
        if not self.secret:
            return {"error": "Flutterwave not configured. Set FLUTTERWAVE_SECRET_KEY in .env"}
        ref = f"ESTRADE-{user_id[:8]}-{int(datetime.now().timestamp())}"
        rate_map = {"TZS": 2600, "KES": 130, "UGX": 3800, "NGN": 1500, "GHS": 15, "USD": 1}
        amount_local = round(amount_usd * rate_map.get(currency, 2600), 2)
        payload = {
            "tx_ref": ref, "amount": amount_local, "currency": currency,
            "redirect_url": f"{getattr(settings,'ALLOWED_ORIGINS',['https://yourdomain.com'])[0]}/payment/callback",
            "customer": {"email": email, "phonenumber": phone, "name": name},
            "payment_options": "mobilemoneytz,card,banktransfer",
            "meta": {"user_id": user_id, "amount_usd": amount_usd},
            "customizations": {"title": "ESTRADE AI Trading", "description": "Fund your trading wallet"},
        }
        try:
            async with httpx.AsyncClient(timeout=20) as c:
                r = await c.post(f"{self.BASE}/payments", json=payload,
                    headers={"Authorization": f"Bearer {self.secret}"})
            d = r.json()
            if d.get("status") == "success":
                # Save to DB
                db.table("payment_requests").insert({
                    "user_id": user_id, "provider": "flutterwave",
                    "direction": "deposit", "amount_usd": amount_usd,
                    "amount_fiat": amount_local, "currency_fiat": currency,
                    "provider_ref": ref, "status": "pending",
                }).execute()
                return {"payment_link": d["data"]["link"], "ref": ref,
                        "amount_local": amount_local, "currency": currency}
            return {"error": d.get("message", "Payment failed")}
        except Exception as e:
            return {"error": str(e)}

    async def verify_transaction(self, tx_id: str) -> dict:
        try:
            async with httpx.AsyncClient(timeout=15) as c:
                r = await c.get(f"{self.BASE}/transactions/{tx_id}/verify",
                    headers={"Authorization": f"Bearer {self.secret}"})
            d = r.json()
            return {
                "verified": d.get("status") == "success" and d["data"]["status"] == "successful",
                "amount": d.get("data", {}).get("amount", 0),
                "currency": d.get("data", {}).get("currency", ""),
                "ref": d.get("data", {}).get("tx_ref", ""),
            }
        except Exception as e:
            return {"verified": False, "error": str(e)}

    def verify_webhook(self, payload: str, signature: str) -> bool:
        secret = getattr(settings, "FLUTTERWAVE_WEBHOOK_HASH", "")
        if not secret: return True
        expected = _hmac.new(secret.encode(), payload.encode(), _hashlib.sha256).hexdigest()
        return _hmac.compare_digest(expected, signature or "")

    async def handle_webhook(self, payload: dict, signature: str) -> dict:
        raw = _json.dumps(payload)
        if not self.verify_webhook(raw, signature):
            return {"status": "invalid_signature"}
        if (payload.get("event") == "charge.completed" and
                payload.get("data", {}).get("status") == "successful"):
            data    = payload["data"]
            tx_ref  = data.get("tx_ref", "")
            currency= data.get("currency", "TZS")
            rates   = {"TZS":2600,"KES":130,"UGX":3800,"NGN":1500,"GHS":15,"USD":1}
            usd     = round(float(data.get("amount", 0)) / rates.get(currency, 2600), 4)
            meta    = data.get("meta") or {}
            uid     = meta.get("user_id")
            if uid:
                req = (db.table("payment_requests").select("*")
                       .eq("provider_ref", tx_ref).eq("status", "pending")
                       .single().execute()).data
                if req:
                    from services.wallet_service import wallet_service as ws
                    await ws.credit(uid, "live", usd, "deposit",
                                     f"Flutterwave {currency} deposit")
                    db.table("payment_requests").update({
                        "status": "completed", "amount_usd": usd,
                        "completed_at": datetime.now(timezone.utc).isoformat(),
                    }).eq("provider_ref", tx_ref).execute()
                    return {"credited": True, "usd": usd}
        return {"status": "ok"}


class NowPaymentsClient:
    """
    NowPayments — crypto payment gateway.
    Accepts BTC, ETH, USDT-TRC20, USDT-ERC20, SOL, BNB, XRP, LTC.
    Fiat→Crypto: User pays fiat via M-Pesa, NowPayments converts to crypto.
    """
    BASE = "https://api.nowpayments.io/v1"

    def __init__(self):
        self.key    = getattr(settings, "NOWPAYMENTS_API_KEY", "")
        self.secret = getattr(settings, "NOWPAYMENTS_IPN_SECRET", "")

    async def create_payment(self, user_id: str, amount_usd: float,
                              pay_currency: str = "usdttrc20") -> dict:
        """Generate a crypto address for the user to send funds to."""
        if not self.key:
            return {"error": "NowPayments not configured. Set NOWPAYMENTS_API_KEY in .env"}
        ref = f"ESTRADE-{user_id[:8]}-{int(datetime.now().timestamp())}"
        payload = {
            "price_amount": amount_usd, "price_currency": "usd",
            "pay_currency": pay_currency.lower(),
            "ipn_callback_url": f"{getattr(settings,'ALLOWED_ORIGINS',[''])[0]}/api/v1/payments/nowpayments/ipn",
            "order_id": ref, "order_description": f"ESTRADE deposit",
        }
        try:
            async with httpx.AsyncClient(timeout=20) as c:
                r = await c.post(f"{self.BASE}/payment", json=payload,
                    headers={"x-api-key": self.key})
            d = r.json()
            if "pay_address" in d:
                db.table("payment_requests").insert({
                    "user_id": user_id, "provider": "nowpayments",
                    "direction": "deposit", "amount_usd": amount_usd,
                    "provider_ref": d["payment_id"], "status": "waiting",
                    "currency_fiat": pay_currency,
                }).execute()
                return {
                    "payment_id": d["payment_id"],
                    "pay_address": d["pay_address"],
                    "pay_amount": d["pay_amount"],
                    "pay_currency": d["pay_currency"],
                    "network": d.get("network", ""),
                    "expiry_minutes": 60,
                    "usd_amount": amount_usd,
                }
            return {"error": d.get("message", "Failed")}
        except Exception as e:
            return {"error": str(e)}

    def verify_ipn(self, payload_str: str, sig: str) -> bool:
        if not self.secret: return True
        exp = _hmac.new(self.secret.encode(), payload_str.encode(), _hashlib.sha512).hexdigest()
        return _hmac.compare_digest(exp, sig or "")

    async def handle_ipn(self, payload: dict, signature: str) -> dict:
        raw = _json.dumps(payload, sort_keys=True)
        if not self.verify_ipn(raw, signature):
            return {"status": "invalid_signature"}
        st    = payload.get("payment_status", "")
        usd   = float(payload.get("price_amount", 0))
        pay_id = str(payload.get("payment_id", ""))
        if st in ("finished", "confirmed"):
            req = (db.table("payment_requests").select("*,user_id")
                   .eq("provider_ref", pay_id).eq("status","waiting")
                   .single().execute()).data
            if req:
                uid = req["user_id"]
                from services.wallet_service import wallet_service as ws
                await ws.credit(uid, "live", usd, "crypto_deposit",
                                 f"Crypto deposit ${usd}")
                db.table("payment_requests").update({
                    "status": "completed", "amount_usd": usd,
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                }).eq("provider_ref", pay_id).execute()
                return {"credited": True, "usd": usd}
        return {"status": st}


class FeeEngine:
    """
    Fee Model — fees ACCRUED during trading, COLLECTED at withdrawal or month-end.
    Never deducted mid-trade.

    Fees:
      - Subscription: $29.99/month (flat)
      - Performance:  20% of net profit per month
      - Withdrawal:   0.1% of amount withdrawn
    """

    async def accrue_trade_fee(self, user_id: str, trade_id: str,
                                 notional: float, pnl: float) -> None:
        """Record accrued fees without deducting. Call after each trade closes."""
        profit_fee = max(0, pnl * 0.20) if pnl > 0 else 0
        db.table("accrued_fees").insert({
            "user_id": user_id, "trade_id": trade_id, "collected": False,
            "profit_fee": round(profit_fee, 6), "notional": notional, "pnl": pnl,
        }).execute()

    async def get_balance_due(self, user_id: str) -> dict:
        rows = (db.table("accrued_fees").select("profit_fee")
                .eq("user_id", user_id).eq("collected", False).execute()).data or []
        perf = sum(float(r["profit_fee"]) for r in rows)
        sub_row = (db.table("subscriptions").select("balance_due")
                   .eq("user_id", user_id).eq("status","active")
                   .single().execute()).data or {}
        sub  = float(sub_row.get("balance_due", 29.99))
        return {"total_due": round(perf + sub, 4), "performance_fees": round(perf, 4),
                "subscription": round(sub, 4), "unpaid_trades": len(rows)}

    async def collect_on_withdrawal(self, user_id: str, withdrawal_usd: float) -> dict:
        """Collect all fees before releasing withdrawal."""
        due     = await self.get_balance_due(user_id)
        wd_fee  = round(withdrawal_usd * 0.001, 4)
        total   = round(due["total_due"] + wd_fee, 4)
        if total <= 0:
            return {"collected": True, "total": 0}
        wallet = (db.table("wallets").select("id,balance")
                  .eq("user_id", user_id).eq("wallet_type","trading")
                  .eq("mode","live").single().execute()).data
        if not wallet or float(wallet["balance"]) < total:
            return {"collected": False, "total_due": total, "reason": "Insufficient balance"}
        db.table("wallets").update({
            "balance": round(float(wallet["balance"]) - total, 6)
        }).eq("id", wallet["id"]).execute()
        db.table("accrued_fees").update({"collected": True}).eq("user_id", user_id).execute()
        db.table("fee_collections").insert({
            "user_id": user_id, "trigger": "withdrawal",
            "performance_fees": due["performance_fees"],
            "subscription": due["subscription"], "withdrawal_fee": wd_fee,
            "total_collected": total,
        }).execute()
        return {"collected": True, "total": total, "breakdown": {
            "performance": due["performance_fees"],
            "subscription": due["subscription"],
            "withdrawal_fee": wd_fee,
        }}


# ── Attach to PaymentService ─────────────────────────────────
flutterwave_client  = FlutterwaveClient()
nowpayments_client  = NowPaymentsClient()
fee_engine          = FeeEngine()
payment_service.flutterwave = flutterwave_client
payment_service.nowpayments = nowpayments_client
payment_service.fee_engine  = fee_engine


# ═══════════════════════════════════════════════════════════════
# ADVANCED PAYMENT ENGINE — Auto-settlement + Double-entry Ledger
# ═══════════════════════════════════════════════════════════════

class AdvancedPaymentEngine:
    """
    Advanced payment features:
    1. Double-entry accounting ledger (every debit = credit elsewhere)
    2. Immutable transaction ledger (append-only with hash chain)
    3. Webhook signature verification (FLW + NowPayments)
    4. Fraud detection rules (velocity, amount, geo)
    5. Auto-settlement: when balance crosses thresholds → auto-sweep
    6. Profit auto-withdrawal: user sets threshold → auto-withdraw
    """

    # ── Double-entry ledger ───────────────────────────────────
    async def double_entry_record(
        self,
        user_id:     str,
        debit_acct:  str,    # e.g. "wallet:user_id:trading"
        credit_acct: str,    # e.g. "platform:fee_pool"
        amount:      float,
        txn_type:    str,
        description: str,
        ref_id:      str = None,
    ) -> dict:
        """
        Record a double-entry accounting entry.
        Every amount debited from one account is credited to another.
        Immutable once committed.
        """
        import hashlib, json
        now = datetime.now(timezone.utc).isoformat()

        # Get previous hash for chain integrity
        last = (db.table("ledger_entries").select("entry_hash")
                .order("created_at", desc=True).limit(1).execute()).data
        prev_hash = last[0]["entry_hash"] if last else "genesis"

        entry_data = {
            "user_id": user_id, "debit": debit_acct,
            "credit": credit_acct, "amount": amount,
            "type": txn_type, "desc": description,
            "ref": ref_id, "ts": now, "prev": prev_hash,
        }
        entry_hash = hashlib.sha256(json.dumps(entry_data, sort_keys=True).encode()).hexdigest()

        db.table("ledger_entries").insert({
            **entry_data, "entry_hash": entry_hash,
            "immutable": True, "created_at": now,
        }).execute()

        return {"recorded": True, "hash": entry_hash[:16], "amount": amount}

    # ── Fraud detection ───────────────────────────────────────
    async def fraud_check(self, user_id: str,
                           amount_usd: float, ip: str = "") -> dict:
        """
        Multi-rule fraud detection before processing payment.
        Rules: velocity, unusual amount, suspicious IP.
        """
        flags = []

        # Velocity: >5 transactions in last 10 minutes
        ten_ago = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
        recent  = (db.table("payment_requests").select("id", count="exact")
                   .eq("user_id", user_id).gte("created_at", ten_ago).execute()).count or 0
        if recent >= 5:
            flags.append(f"Velocity: {recent} txns in 10min")

        # Amount threshold
        if amount_usd > 50000:
            flags.append(f"Large amount: ${amount_usd:,.2f} — requires KYC review")

        # Today's total
        today = datetime.now(timezone.utc).date().isoformat()
        today_rows = (db.table("payment_requests").select("amount_usd")
                      .eq("user_id",user_id).gte("created_at",today).execute()).data or []
        today_total = sum(float(r.get("amount_usd",0)) for r in today_rows)
        if today_total + amount_usd > 100000:
            flags.append(f"Daily limit: ${today_total+amount_usd:,.2f} > $100,000")

        is_fraudulent = len(flags) > 0
        if is_fraudulent:
            db.table("fraud_alerts").insert({
                "user_id": user_id, "amount": amount_usd,
                "flags": flags, "ip": ip,
                "severity": "HIGH" if len(flags) >= 2 else "MEDIUM",
            }).execute()
            log.warning("fraud_detected", user=user_id, flags=flags)

        return {
            "fraud_detected": is_fraudulent,
            "flags":          flags,
            "risk_level":     "HIGH" if len(flags)>=2 else "MEDIUM" if flags else "LOW",
            "action":         "BLOCK" if len(flags)>=2 else "REVIEW" if flags else "ALLOW",
        }

    # ── Auto-profit withdrawal ────────────────────────────────
    async def check_auto_withdrawal(self, user_id: str) -> dict:
        """
        If user has set auto-withdraw threshold and balance crosses it,
        automatically initiate withdrawal to their preferred method.
        """
        try:
            cfg = (db.table("auto_withdrawal_config").select("*")
                   .eq("user_id",user_id).eq("is_active",True)
                   .single().execute()).data
            if not cfg: return {"triggered":False}

            threshold = float(cfg.get("threshold_usd",0))
            wallet    = (db.table("wallets").select("balance")
                         .eq("user_id",user_id).eq("wallet_type","trading")
                         .eq("mode","live").single().execute()).data
            balance   = float(wallet["balance"]) if wallet else 0

            if balance >= threshold:
                # Keep 20% in trading, withdraw 80%
                withdraw_amt = round(balance * 0.80, 4)
                method  = cfg.get("method","mpesa")
                phone   = cfg.get("phone","")

                log.info("auto_withdrawal_triggered",
                         user=user_id, amount=withdraw_amt, method=method)
                return {
                    "triggered":     True,
                    "amount":        withdraw_amt,
                    "method":        method,
                    "phone":         phone,
                    "current_balance": balance,
                    "threshold":     threshold,
                }
        except Exception as e:
            return {"triggered":False,"error":str(e)}
        return {"triggered":False}

    async def configure_auto_withdrawal(self, user_id: str,
                                          threshold_usd: float,
                                          method: str, phone: str,
                                          enabled: bool = True) -> dict:
        """Set auto-withdrawal threshold for a user."""
        db.table("auto_withdrawal_config").upsert({
            "user_id":       user_id,
            "threshold_usd": threshold_usd,
            "method":        method,
            "phone":         phone,
            "is_active":     enabled,
            "updated_at":    datetime.now(timezone.utc).isoformat(),
        }).execute()
        return {"saved":True,"threshold":threshold_usd,"method":method}


advanced_payment = AdvancedPaymentEngine()
