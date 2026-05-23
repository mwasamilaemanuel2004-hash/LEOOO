from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from middleware.auth import get_current_user
from services.payment_service import payment_service
from core.database import db
router = APIRouter()

class DepositReq(BaseModel):
    method: str; amount_fiat: float; currency: str = "TZS"; phone: str | None = None
class WithdrawReq(BaseModel):
    method: str; amount_usd: float; phone: str | None = None

@router.post("/deposit")
async def deposit(body: DepositReq, user: dict = Depends(get_current_user)):
    return await payment_service.create_deposit_request(user["id"], body.method, body.amount_fiat, body.currency, body.phone)

@router.post("/withdraw")
async def withdraw(body: WithdrawReq, user: dict = Depends(get_current_user)):
    return await payment_service.create_withdrawal_request(user["id"], body.method, body.amount_usd, body.phone)

@router.post("/mpesa/callback")
async def mpesa_callback(req: Request):
    body = await req.json()
    return await payment_service.handle_mpesa_callback(body)

@router.get("/history")
async def payment_history(user: dict = Depends(get_current_user)):
    data = db.table("payment_requests").select("*").eq("user_id", user["id"]).order("created_at", desc=True).limit(50).execute().data or []
    return {"payments": data}


# ═══════════════════════════════════════════════════════════════
# v6 ROUTES — Flutterwave + NowPayments + Fee Collection
# ═══════════════════════════════════════════════════════════════

class FLWDepositReq(BaseModel):
    amount_usd: float
    currency: str = "TZS"
    phone: str
    email: str = ""
    name: str = ""

class CryptoDepositReq(BaseModel):
    amount_usd: float
    pay_currency: str = "usdttrc20"   # btc | eth | usdttrc20 | usdterc20 | sol | bnb

@router.post("/flutterwave/deposit")
async def flw_deposit(body: FLWDepositReq, user: dict = Depends(get_current_user)):
    """Initiate Flutterwave payment — returns redirect link."""
    email = body.email or user.get("email", "")
    name  = body.name  or user.get("full_name", "ESTRADE User")
    result = await payment_service.flutterwave.initiate_payment(
        user["id"], body.amount_usd, email, body.phone, name, body.currency
    )
    return result

@router.post("/flutterwave/verify/{tx_id}")
async def flw_verify(tx_id: str, user: dict = Depends(get_current_user)):
    """Manually verify a Flutterwave transaction."""
    return await payment_service.flutterwave.verify_transaction(tx_id)

@router.post("/flutterwave/webhook")
async def flw_webhook(request: Request):
    """Flutterwave IPN webhook — verifies signature and credits wallet."""
    body = await request.json()
    sig  = request.headers.get("verif-hash", "")
    return await payment_service.flutterwave.handle_webhook(body, sig)

@router.post("/crypto/create")
async def crypto_deposit(body: CryptoDepositReq, user: dict = Depends(get_current_user)):
    """Generate NowPayments crypto address for deposit."""
    return await payment_service.nowpayments.create_payment(
        user["id"], body.amount_usd, body.pay_currency
    )

@router.get("/crypto/currencies")
async def crypto_currencies():
    """List of accepted cryptocurrencies."""
    currencies = await payment_service.nowpayments.get_available_currencies()
    return {"currencies": currencies, "recommended": ["usdttrc20","btc","eth","sol","bnb"]}

@router.get("/crypto/status/{payment_id}")
async def crypto_status(payment_id: str, user: dict = Depends(get_current_user)):
    """Check status of a crypto deposit."""
    return await payment_service.nowpayments.get_payment_status(payment_id)

@router.post("/nowpayments/ipn")
async def nowpayments_ipn(request: Request):
    """NowPayments IPN webhook — credits wallet on confirmation."""
    body = await request.json()
    sig  = request.headers.get("x-nowpayments-sig", "")
    return await payment_service.nowpayments.handle_ipn(body, sig)

@router.get("/fees/balance")
async def fees_balance(user: dict = Depends(get_current_user)):
    """Get user's total accrued fees pending collection."""
    return await payment_service.fee_engine.get_balance_due(user["id"])

@router.post("/fees/collect")
async def fees_collect(user: dict = Depends(get_current_user)):
    """Manually collect all accrued fees (called before withdrawal)."""
    return await payment_service.fee_engine.collect_on_withdrawal(user["id"], 0)


# ── Fee Engine Routes ────────────────────────────────────────
from services.fee_engine import fee_engine as _fe

@router.get("/fees/summary")
async def fees_summary(user: dict = Depends(get_current_user)):
    """Real-time fee summary from Supabase v_user_fees view."""
    breakdown = await _fe.get_balance_due(user["id"])
    return {**breakdown.to_dict(), "rates": {
        "platform_fee_pct": 0.05,
        "profit_share_pct": 20.0,
        "subscription_usd": 29.99,
        "withdrawal_fee_pct": 0.1,
        "collection_trigger": "On withdrawal or month-end",
        "note": "Fees are NEVER deducted during active trading",
    }}

@router.get("/fees/ledger")
async def fees_ledger(collected: bool = None, limit: int = 50,
                       user: dict = Depends(get_current_user)):
    """Per-trade fee ledger — shows platform_fee + profit_share per trade."""
    rows = await _fe.get_trade_fee_ledger(user["id"], collected, limit)
    return {"trades": rows, "count": len(rows)}

@router.get("/fees/history")
async def fees_history(user: dict = Depends(get_current_user)):
    """History of past fee collection events."""
    rows = await _fe.get_fee_history(user["id"])
    return {"collections": rows}

class FeePreviewReq(BaseModel):
    notional: float
    net_pnl:  float = 0.0

@router.post("/fees/preview")
async def fees_preview(body: FeePreviewReq, user: dict = Depends(get_current_user)):
    """Preview fees for a hypothetical trade — show in UI before entering trade."""
    return _fe.calculate_fees_preview(body.notional, body.net_pnl)

@router.post("/fees/collect-now")
async def fees_collect_now(user: dict = Depends(get_current_user)):
    """Manually trigger fee collection (no withdrawal)."""
    result = await _fe.collect_monthly_for_user(user["id"])
    return result
