"""api/routes/payment.py — Stripe payments"""
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
router = APIRouter()

PLANS = {
    "gold":     {"price": 2900, "name": "Gold Plan",     "features": ["Advanced AI","Priority signals"]},
    "platinum": {"price": 9900, "name": "Platinum Plan", "features": ["Full AI","DL models","Dedicated support"]},
}

class CheckoutReq(BaseModel):
    plan: str

@router.post("/payment/checkout")
async def create_checkout(req: CheckoutReq):
    try:
        from core.config import settings
        if not settings.stripe_key:
            return {"url": None, "error": "Stripe not configured. Add STRIPE_SECRET_KEY to env."}
        import stripe
        stripe.api_key = settings.stripe_key
        plan = PLANS.get(req.plan)
        if not plan: raise HTTPException(400, "Invalid plan")
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{"price_data": {
                "currency": "usd",
                "unit_amount": plan["price"],
                "recurring": {"interval": "month"},
                "product_data": {"name": plan["name"]},
            }, "quantity": 1}],
            mode="subscription",
            success_url=f"{settings.frontend_url}/settings?upgraded=1",
            cancel_url=f"{settings.frontend_url}/settings?cancelled=1",
        )
        return {"url": session.url}
    except Exception as e:
        raise HTTPException(500, str(e))

@router.get("/payment/plans")
async def get_plans():
    return {"plans": PLANS}
