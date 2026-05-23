"""api/routes/auth.py v10 — Dual auth: admin + user, token support"""
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import Optional
router = APIRouter()

class LoginReq(BaseModel):
    email: str
    password: str
    admin_token: Optional[str] = None  # for token-based free/discount login

class RegisterReq(BaseModel):
    email: str
    password: str
    full_name: str
    phone: Optional[str] = ""
    referral_code: Optional[str] = None
    admin_token: Optional[str] = None

@router.post("/auth/login")
async def login(req: LoginReq, request: Request):
    try:
        from core.database import db
        from core.security import verify_password, create_token
        if not db:
            # Demo mode — allow admin login
            if req.email == "admin@estrading.machine" and req.password == "EstradingV10Admin!2026":
                tok = create_token({"sub":"demo-admin","role":"admin","email":req.email})
                return {"token":tok,"user":{"id":"demo-admin","email":req.email,"role":"admin","tier":"platinum","full_name":"Admin","signal_mode":"both"}}
            raise HTTPException(401,"Invalid credentials")

        # Check failed login attempts
        ip = request.client.host if request.client else "unknown"
        block = db.rpc("check_failed_login", {"p_email":req.email,"p_ip":ip}).execute()
        if block.data and block.data.get("blocked"):
            raise HTTPException(429, f"Too many failed attempts. Try again later.")

        # Find user
        r = db.table("users").select("*").eq("email", req.email.lower()).eq("is_active", True).maybe_single().execute()
        if not r.data:
            raise HTTPException(401, "Invalid email or password")

        user = r.data
        if not verify_password(req.password, user.get("password_hash","")):
            raise HTTPException(401, "Invalid email or password")

        if user.get("is_suspended"):
            raise HTTPException(403, "Account suspended. Contact support: +255653712466")

        # Admin token — grant premium access
        token_discount = 0
        if req.admin_token:
            from core.admin_tokens import admin_token_manager
            tok_result = admin_token_manager.validate(req.admin_token)
            if tok_result:
                admin_token_manager.use(req.admin_token)
                if tok_result["type"] == "free":
                    db.table("users").update({"tier":"platinum","subscription_plan":"free_token"}).eq("id",user["id"]).execute()
                token_discount = tok_result.get("discount_pct", 0)

        # Update login stats
        db.table("users").update({
            "last_login": "now()", "login_count": user.get("login_count",0)+1, "last_ip": ip
        }).eq("id", user["id"]).execute()
        db.rpc("clear_failed_login", {"p_ip": ip}).execute()

        # Create session token
        jwt_token = create_token({"sub":user["id"],"role":user.get("role","user"),"email":user["email"]})

        # Store session
        import hashlib
        db.table("auth_sessions").insert({
            "user_id": user["id"], "token_hash": hashlib.sha256(jwt_token.encode()).hexdigest(),
            "ip_address": ip, "is_active": True,
            "expires_at": "now() + interval '7 days'"
        }).execute()

        safe_user = {k:v for k,v in user.items() if k not in ("password_hash","two_fa_secret")}
        if token_discount: safe_user["discount_pct"] = token_discount

        return {"token": jwt_token, "user": safe_user, "expires_in": 86400*7}
    except HTTPException: raise
    except Exception as e: raise HTTPException(500, str(e))

@router.post("/auth/register")
async def register(req: RegisterReq, request: Request):
    try:
        from core.database import db
        from core.security import hash_password, create_token
        if not db: raise HTTPException(503, "Database not connected")

        # Check existing
        existing = db.table("users").select("id").eq("email", req.email.lower()).maybe_single().execute()
        if existing.data: raise HTTPException(409, "Email already registered")

        # Admin token validation
        tier = "silver"
        plan = "free"
        if req.admin_token:
            from core.admin_tokens import admin_token_manager
            tok_res = admin_token_manager.validate(req.admin_token)
            if tok_res:
                admin_token_manager.use(req.admin_token)
                if tok_res["type"] == "free": tier="platinum"; plan="free_token"
                elif tok_res["type"] == "discount": plan="discounted"

        # Find referrer
        referred_by = None
        if req.referral_code:
            ref = db.table("users").select("id").eq("referral_code", req.referral_code).maybe_single().execute()
            if ref.data: referred_by = ref.data["id"]

        new_user = {
            "email": req.email.lower(), "password_hash": hash_password(req.password),
            "full_name": req.full_name, "phone": req.phone or "",
            "role": "user", "tier": tier, "subscription_plan": plan,
            "is_active": True, "is_verified": False,
            "referred_by": referred_by,
        }
        r = db.table("users").insert(new_user).execute()
        user = r.data[0] if r.data else new_user

        token = create_token({"sub":user.get("id","new"),"role":"user","email":req.email})
        return {"token": token, "user": {k:v for k,v in user.items() if k!="password_hash"}, "message":"Registration successful!"}
    except HTTPException: raise
    except Exception as e: raise HTTPException(500, str(e))

@router.post("/auth/logout")
async def logout(request: Request):
    try:
        from core.database import db
        import hashlib
        token = request.headers.get("Authorization","").replace("Bearer ","")
        if db and token:
            h = hashlib.sha256(token.encode()).hexdigest()
            db.table("auth_sessions").update({"is_active":False}).eq("token_hash",h).execute()
        return {"logged_out": True}
    except: return {"logged_out": True}

@router.get("/auth/me")
async def me(request: Request):
    try:
        import jwt
        from core.config import settings
        from core.database import db
        token = request.headers.get("Authorization","").replace("Bearer ","")
        if not token: raise HTTPException(401,"No token")
        payload = jwt.decode(token, settings.secret_key, algorithms=["HS256"])
        if not db: return {"id":payload.get("sub"),"role":payload.get("role","user"),"email":payload.get("email","")}
        r = db.table("users").select("id,email,full_name,role,tier,signal_mode,reinvest_global,telegram_chat_id").eq("id",payload["sub"]).maybe_single().execute()
        if not r.data: raise HTTPException(404,"User not found")
        return r.data
    except HTTPException: raise
    except Exception as e: raise HTTPException(401, str(e))
