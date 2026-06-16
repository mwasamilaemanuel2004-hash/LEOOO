"""api/routes/wallets.py"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from middleware.auth import get_current_user, require_trading_enabled
from services.wallet_service import wallet_service
from services.payment_service import payment_service

router = APIRouter()

class DepositReq(BaseModel):
    method: str  # mpesa | airtel | tigo
    amount_fiat: float
    currency: str = "TZS"
    phone: str | None = None

class WithdrawReq(BaseModel):
    method: str
    amount_usd: float
    phone: str | None = None

class PrepaidLoad(BaseModel):
    amount: float

@router.get("/")
async def get_wallets(user: dict = Depends(get_current_user)):
    return await wallet_service.get_all_balances(user["id"])

@router.get("/{wallet_type}")
async def get_wallet(wallet_type: str, user: dict = Depends(get_current_user)):
    if wallet_type not in ("demo", "real", "internal"):
        raise HTTPException(400, "Invalid wallet type")
    return await wallet_service.get_balance(user["id"], wallet_type)

@router.post("/deposit")
async def deposit(body: DepositReq, user: dict = Depends(get_current_user)):
    return await payment_service.create_deposit_request(
        user["id"], body.method, body.amount_fiat, body.currency, body.phone
    )

@router.post("/withdraw")
async def withdraw(body: WithdrawReq, user: dict = Depends(get_current_user)):
    return await payment_service.create_withdrawal_request(
        user["id"], body.method, body.amount_usd, body.phone
    )

@router.post("/prepaid/load")
async def load_prepaid(body: PrepaidLoad, user: dict = Depends(get_current_user)):
    return await wallet_service.load_prepaid(user["id"], body.amount)

@router.get("/transactions/history")
async def transactions(limit: int = 50, user: dict = Depends(get_current_user)):
    from core.database import db
    txns = (db.table("transactions").select("*")
            .eq("user_id", user["id"])
            .order("created_at", desc=True).limit(limit).execute()).data or []
    return {"transactions": txns}
