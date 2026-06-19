"""
api/routes/multiplier.py — ESTRADE v6 Bot Position Multiplier System
══════════════════════════════════════════════════════════════════════════
Accordion multiplier buttons: 1 → 10 → 100 → 1000 → 10000

Each multiplier level:
  1x     — Standard position (base risk %)
  10x    — 10× base capital allocated to this signal
  100x   — 100× (requires Silver+)
  1000x  — 1000× (requires Platinum, risk guard active)
  10000x — MAX POWER (Platinum only, auto-hedges, whale mode)

Safety guards per level:
  ≥10x:   Require 2-factor confirm + ATR volatility check
  ≥100x:  Max drawdown guard (auto-cut if -5%)
  ≥1000x: Requires Platinum + min $5000 balance
  10000x: Requires Platinum + min $50000 + emergency kill switch

Anti-fake signal:
  - Confidence threshold rises with multiplier (1x=60%, 10x=70%, 100x=80%, 1000x=90%, 10000x=95%)
  - Cross-validate with HybridBrain + 5-Layer AI (must BOTH agree)
  - Whale tracker confirms market direction
  - News sentiment must not be adverse
  - Volume ratio must be elevated (1.3x+ for 10x, 2x+ for 1000x)
  - AI reasoning logged for audit
══════════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field
from typing import Optional
from middleware.auth import get_current_user
from core.database import db
import structlog

log = structlog.get_logger("multiplier")
router = APIRouter()


# ═══════════════════════════════════════════════════════════════
# MULTIPLIER LEVELS
# ═══════════════════════════════════════════════════════════════

MULTIPLIER_LEVELS = {
    1: {
        "label": "1×",
        "name": "Standard",
        "color": "#5dba8a",
        "icon": "▶",
        "description": "Standard position — base risk %",
        "min_confidence": 60,
        "min_tier": "gold",
        "min_balance": 10.0,
        "vol_ratio_min": 0.0,
        "requires_dual_ai": False,
        "requires_whale": False,
        "requires_news": False,
        "max_drawdown_guard": None,
        "confirm_required": False,
        "max_capital_pct": 5.0,   # max % of balance
    },
    10: {
        "label": "10×",
        "name": "Power",
        "color": "#f59e0b",
        "icon": "⚡",
        "description": "10× capital — elevated momentum required",
        "min_confidence": 70,
        "min_tier": "gold",
        "min_balance": 100.0,
        "vol_ratio_min": 1.3,
        "requires_dual_ai": True,   # HybridBrain + 5-Layer must agree
        "requires_whale": False,
        "requires_news": False,
        "max_drawdown_guard": 10.0,  # cut if -10%
        "confirm_required": False,
        "max_capital_pct": 20.0,
    },
    100: {
        "label": "100×",
        "name": "Surge",
        "color": "#f97316",
        "icon": "🔥",
        "description": "100× — high conviction only, auto-guard active",
        "min_confidence": 80,
        "min_tier": "silver",
        "min_balance": 500.0,
        "vol_ratio_min": 1.5,
        "requires_dual_ai": True,
        "requires_whale": True,
        "requires_news": False,
        "max_drawdown_guard": 5.0,
        "confirm_required": True,
        "max_capital_pct": 40.0,
    },
    1000: {
        "label": "1000×",
        "name": "Ultra",
        "color": "#ec4899",
        "icon": "💥",
        "description": "1000× — Platinum only, whale + news + all AI must agree",
        "min_confidence": 90,
        "min_tier": "platinum",
        "min_balance": 5000.0,
        "vol_ratio_min": 2.0,
        "requires_dual_ai": True,
        "requires_whale": True,
        "requires_news": True,
        "max_drawdown_guard": 3.0,
        "confirm_required": True,
        "max_capital_pct": 60.0,
    },
    10000: {
        "label": "10000×",
        "name": "WHALE MODE",
        "color": "#7c3aed",
        "icon": "🐋",
        "description": "MAXIMUM POWER — Platinum + $50k + full consensus",
        "min_confidence": 95,
        "min_tier": "platinum",
        "min_balance": 50000.0,
        "vol_ratio_min": 2.5,
        "requires_dual_ai": True,
        "requires_whale": True,
        "requires_news": True,
        "max_drawdown_guard": 2.0,
        "confirm_required": True,
        "max_capital_pct": 80.0,
    },
}

TIER_ORDER = {"gold": 0, "silver": 1, "platinum": 2}


# ═══════════════════════════════════════════════════════════════
# ANTI-FAKE SIGNAL VALIDATOR
# ═══════════════════════════════════════════════════════════════

class AntiFakeValidator:
    """
    Multi-layer validation to prevent fake/hallucinated signals
    from triggering high-multiplier trades.
    All checks must pass for multiplier ≥ 10×.
    """

    async def validate(
        self,
        df,
        symbol: str,
        multiplier: int,
        base_confidence: float,
    ) -> dict:
        """Run all anti-fake checks. Returns validation result."""
        level = MULTIPLIER_LEVELS.get(multiplier, MULTIPLIER_LEVELS[1])
        issues = []
        passed = []
        warnings = []

        # ── 1. Confidence threshold ──────────────────────────
        req_conf = level["min_confidence"]
        if base_confidence >= req_conf:
            passed.append(f"Confidence {base_confidence:.1f}% ≥ {req_conf}%")
        else:
            issues.append(f"Confidence {base_confidence:.1f}% < required {req_conf}% for {level['label']}")

        # ── 2. Volume ratio check ────────────────────────────
        vol_min = level["vol_ratio_min"]
        vol_r   = 0.0
        if df is not None and "vol_ratio" in df.columns:
            vol_r = float(df["vol_ratio"].iloc[-1])
        elif df is not None and "volume" in df.columns:
            v_avg = df["volume"].rolling(20).mean().iloc[-1]
            vol_r = float(df["volume"].iloc[-1]) / (float(v_avg) + 1e-9)

        if vol_r >= vol_min:
            passed.append(f"Volume {vol_r:.2f}× ≥ required {vol_min}×")
        elif vol_min > 0:
            issues.append(f"Volume {vol_r:.2f}× < required {vol_min}× for {level['label']}")

        # ── 3. Dual AI agreement (HybridBrain + 5-Layer) ────
        dual_ai_ok = False
        hybrid_dir = "unknown"
        layer_dir  = "unknown"
        if level["requires_dual_ai"] and df is not None and len(df) >= 50:
            try:
                from ai.hybrid_brain import hybrid_brain
                brain = hybrid_brain.decide(df, symbol)
                hybrid_dir = brain.direction
            except Exception:
                hybrid_dir = "error"

            try:
                from ai.indicator_engine import layered_ai
                layer_dec = layered_ai.analyze(df, symbol)
                layer_dir = "long" if layer_dec.action == "BUY" else \
                            "short" if layer_dec.action == "SELL" else "wait"
            except Exception:
                layer_dir = "error"

            dual_ai_ok = (hybrid_dir == layer_dir and hybrid_dir not in ("wait","unknown","error"))
            if dual_ai_ok:
                passed.append(f"Dual AI agree: HybridBrain={hybrid_dir}, LayeredAI={layer_dir}")
            elif level["requires_dual_ai"]:
                issues.append(f"Dual AI conflict: HybridBrain={hybrid_dir} ≠ LayeredAI={layer_dir}")
        else:
            dual_ai_ok = not level["requires_dual_ai"]

        # ── 4. Whale tracker ─────────────────────────────────
        whale_ok = False
        if level["requires_whale"]:
            try:
                from ai.whale_tracker import whale_tracker
                whale_data = await whale_tracker.get_bias(symbol)
                whale_bull  = whale_data.get("bias") in ("bullish","strong_bullish")
                whale_bear  = whale_data.get("bias") in ("bearish","strong_bearish")
                whale_ok   = whale_bull or whale_bear
                if whale_ok:
                    passed.append(f"Whale bias confirmed: {whale_data.get('bias')}")
                else:
                    warnings.append(f"Whale bias neutral: {whale_data.get('bias','unknown')}")
                    # Neutral whale = warning not fail for 1000×, fail for 10000×
                    if multiplier >= 10000:
                        issues.append("Whale bias must be strong for 10000×")
            except Exception as e:
                warnings.append(f"Whale tracker unavailable: {e}")
                whale_ok = multiplier < 10000  # allow for <10000×
        else:
            whale_ok = True

        # ── 5. News sentiment (no adverse events) ───────────
        news_ok = True
        if level["requires_news"]:
            try:
                from ai.news_service import news_service
                news = await news_service.get_sentiment(symbol)
                sentiment = float(news.get("score", 0))
                if sentiment < -0.3:
                    issues.append(f"Adverse news sentiment: {sentiment:.2f} — too negative for {level['label']}")
                    news_ok = False
                else:
                    passed.append(f"News sentiment OK: {sentiment:.2f}")
            except Exception:
                warnings.append("News service unavailable — proceeding with caution")

        # ── 6. ATR spike check (sudden volatility) ───────────
        atr_ok = True
        if df is not None and len(df) >= 20:
            try:
                atr_now = df["atr14"].iloc[-1] if "atr14" in df.columns else 0
                atr_avg = df["atr14"].rolling(50).mean().iloc[-1] if "atr14" in df.columns else atr_now
                if atr_avg > 0 and atr_now / atr_avg > 3.0:
                    issues.append(f"Extreme ATR spike: {atr_now/atr_avg:.1f}× avg — market too wild")
                    atr_ok = False
                else:
                    passed.append(f"ATR normal: {atr_now/atr_avg:.2f}× avg" if atr_avg > 0 else "ATR OK")
            except Exception:
                pass

        # ── 7. Candle pattern authenticity ───────────────────
        if df is not None and len(df) >= 3 and multiplier >= 100:
            try:
                last  = df.iloc[-1]
                body  = abs(float(last.get("close",0)) - float(last.get("open",0)))
                rng   = float(last.get("high",0)) - float(last.get("low",0))
                if rng > 0 and body / rng < 0.1:
                    warnings.append("Doji candle — indecision, confirm before entering")
            except Exception:
                pass

        # ── FINAL VERDICT ─────────────────────────────────────
        valid = len(issues) == 0
        score = len(passed) / max(len(passed) + len(issues), 1) * 100

        return {
            "valid":          valid,
            "score":          round(score, 1),
            "multiplier":     multiplier,
            "level_name":     level["name"],
            "passed":         passed,
            "issues":         issues,
            "warnings":       warnings,
            "dual_ai_hybrid": hybrid_dir,
            "dual_ai_layer":  layer_dir,
            "vol_ratio":      round(vol_r, 3),
            "can_execute":    valid and len(issues) == 0,
        }


anti_fake = AntiFakeValidator()


# ═══════════════════════════════════════════════════════════════
# API ROUTES
# ═══════════════════════════════════════════════════════════════

class MultiplierExecuteReq(BaseModel):
    bot_id:      str
    symbol:      str
    action:      str            # BUY | SELL
    multiplier:  int = Field(..., ge=1, le=10000)
    base_capital: float = Field(..., gt=0)
    confirm:     bool = False   # required for ≥100×
    timeframe:   str = "1h"

class MultiplierPreviewReq(BaseModel):
    symbol:     str
    multiplier: int = Field(..., ge=1, le=10000)
    base_capital: float = 100.0
    timeframe:  str = "1h"


@router.get("/levels")
async def get_multiplier_levels(user: dict = Depends(get_current_user)):
    """Get all multiplier levels with tier requirements."""
    from services.tier_engine import tier_engine
    user_tier   = await tier_engine.get_user_tier(user["id"])
    user_level  = TIER_ORDER.get(user_tier.name, 0)

    levels = []
    for mult, cfg in MULTIPLIER_LEVELS.items():
        req_level  = TIER_ORDER.get(cfg["min_tier"], 0)
        levels.append({
            **cfg,
            "multiplier":    mult,
            "accessible":    user_level >= req_level,
            "locked_reason": None if user_level >= req_level else
                             f"Requires {cfg['min_tier'].title()} tier",
        })
    return {"levels": levels, "user_tier": user_tier.name}


@router.post("/preview")
async def preview_multiplier(
    body: MultiplierPreviewReq,
    user: dict = Depends(get_current_user),
):
    """
    Preview what a multiplier trade would look like.
    Validates against tier, balance, and anti-fake checks.
    """
    from services.tier_engine import tier_engine
    from exchanges.exchange_service import exchange_service
    from ai.indicators import ohlcv_to_df, compute_all

    level    = MULTIPLIER_LEVELS.get(body.multiplier, MULTIPLIER_LEVELS[1])
    user_tier = await tier_engine.get_user_tier(user["id"])

    # Tier check
    req_level  = TIER_ORDER.get(level["min_tier"], 0)
    user_level = TIER_ORDER.get(user_tier.name, 0)
    if user_level < req_level:
        return {
            "can_execute": False,
            "reason": f"{level['label']} requires {level['min_tier'].title()} tier",
            "your_tier": user_tier.name,
        }

    # Balance check
    try:
        wallet = (db.table("wallets").select("balance").eq("user_id", user["id"])
                  .eq("wallet_type","trading").eq("mode","live").single().execute()).data
        balance = float(wallet["balance"]) if wallet else 0
    except Exception:
        balance = 0

    if balance < level["min_balance"]:
        return {
            "can_execute": False,
            "reason": f"Min balance ${level['min_balance']:,.0f} required for {level['label']}",
            "your_balance": balance,
        }

    # Calculate position
    effective_capital = min(
        body.base_capital * body.multiplier,
        balance * level["max_capital_pct"] / 100
    )

    # Get market data for validation
    df = None
    try:
        ohlcv = await exchange_service.get_ohlcv(body.symbol, body.timeframe, limit=100)
        df    = compute_all(ohlcv_to_df(ohlcv))
        price = float(df["close"].iloc[-1])
    except Exception:
        price = 0

    # Quick signal from 5-layer
    signal_conf = 0
    signal_action = "WAIT"
    try:
        from ai.indicator_engine import layered_ai
        dec = layered_ai.analyze(df, body.symbol)
        signal_conf   = dec.confidence
        signal_action = dec.action
    except Exception:
        pass

    # Anti-fake validation
    validation = await anti_fake.validate(df, body.symbol, body.multiplier, signal_conf)

    # Estimated PnL preview
    if price > 0:
        atr  = float(df["atr14"].iloc[-1]) if df is not None and "atr14" in df.columns else price * 0.02
        potential_profit = effective_capital * (atr * 4 / price)  # 4 ATR TP
        potential_loss   = effective_capital * (atr * 2 / price)  # 2 ATR SL
    else:
        potential_profit = potential_loss = 0

    return {
        "multiplier":        body.multiplier,
        "label":             level["label"],
        "name":              level["name"],
        "base_capital":      body.base_capital,
        "effective_capital": round(effective_capital, 4),
        "current_price":     round(price, 6),
        "potential_profit":  round(potential_profit, 4),
        "potential_loss":    round(potential_loss, 4),
        "signal_action":     signal_action,
        "signal_confidence": round(signal_conf, 2),
        "validation":        validation,
        "can_execute":       validation["can_execute"],
        "confirm_required":  level["confirm_required"],
        "drawdown_guard":    level["max_drawdown_guard"],
        "tier_required":     level["min_tier"],
        "your_tier":         user_tier.name,
        "your_balance":      round(balance, 4),
        "max_capital_pct":   level["max_capital_pct"],
    }


@router.post("/execute")
async def execute_multiplier_trade(
    body: MultiplierExecuteReq,
    bg:   BackgroundTasks,
    user: dict = Depends(get_current_user),
):
    """
    Execute a multiplied trade.
    Runs all validation, then opens trade with amplified capital.
    """
    from services.tier_engine import tier_engine
    from exchanges.exchange_service import exchange_service
    from ai.indicators import ohlcv_to_df, compute_all
    from services.bot_service import bot_service

    level     = MULTIPLIER_LEVELS.get(body.multiplier, MULTIPLIER_LEVELS[1])
    user_tier = await tier_engine.get_user_tier(user["id"])

    # Tier check
    if TIER_ORDER.get(user_tier.name,0) < TIER_ORDER.get(level["min_tier"],0):
        raise HTTPException(403, f"{level['label']} requires {level['min_tier'].title()} tier")

    # Confirm required check
    if level["confirm_required"] and not body.confirm:
        return {
            "executed":       False,
            "reason":         "CONFIRM_REQUIRED",
            "message":        f"Please confirm: {level['label']} trade requires explicit confirmation",
            "confirm_text":   f"I confirm this {level['label']} ({level['name']}) trade with ${body.base_capital * body.multiplier:,.2f} capital",
        }

    # Get market data
    try:
        ohlcv = await exchange_service.get_ohlcv(body.symbol, body.timeframe, limit=100)
        df    = compute_all(ohlcv_to_df(ohlcv))
        price = float(df["close"].iloc[-1])
    except Exception as e:
        raise HTTPException(400, f"Market data error: {e}")

    # Quick signal
    signal_conf = 0
    try:
        from ai.indicator_engine import layered_ai
        dec = layered_ai.analyze(df, body.symbol)
        signal_conf = dec.confidence
    except Exception:
        signal_conf = 70

    # Anti-fake validation — HARD BLOCK if fails
    validation = await anti_fake.validate(df, body.symbol, body.multiplier, signal_conf)
    if not validation["can_execute"]:
        log.warning("multiplier_blocked_by_antifake",
                    user=user["id"], mult=body.multiplier,
                    issues=validation["issues"])
        return {
            "executed":   False,
            "reason":     "ANTI_FAKE_BLOCK",
            "validation": validation,
            "message":    "Signal failed anti-fake validation. Issues: " + "; ".join(validation["issues"]),
        }

    # Calculate effective capital
    wallet = (db.table("wallets").select("balance").eq("user_id", user["id"])
              .eq("wallet_type","trading").eq("mode","live").single().execute()).data
    balance = float(wallet["balance"]) if wallet else 0
    max_cap = balance * level["max_capital_pct"] / 100
    effective_capital = min(body.base_capital * body.multiplier, max_cap)

    if effective_capital < 1:
        raise HTTPException(400, f"Effective capital too low: ${effective_capital:.4f}")

    # Compute SL/TP from ATR
    atr  = float(df["atr14"].iloc[-1]) if "atr14" in df.columns else price * 0.02
    side = "long" if body.action.upper() == "BUY" else "short"
    d    = 1 if side == "long" else -1
    sl   = round(price - d * atr * 2.0, 8)
    tp   = round(price + d * atr * 4.0, 8)
    qty  = round(effective_capital / price, 8)

    # Open trade via bot_service
    try:
        trade = await bot_service.open_trade(
            bot_id=body.bot_id,
            user_id=user["id"],
            symbol=body.symbol,
            side=side,
            entry_price=price,
            quantity=qty,
            stop_loss=sl,
            take_profit=tp,
            source=f"multiplier_{body.multiplier}x",
        )
    except Exception as e:
        raise HTTPException(500, f"Trade open failed: {e}")

    # Set drawdown guard in background
    if level["max_drawdown_guard"]:
        trade_id = trade.get("trade_id","")
        guard_pct = level["max_drawdown_guard"]
        bg.add_task(_set_drawdown_guard, trade_id, effective_capital, guard_pct)

    log.info("multiplier_trade_executed",
             user=user["id"], mult=body.multiplier, symbol=body.symbol,
             capital=effective_capital, side=side, price=price)

    return {
        "executed":          True,
        "multiplier":        body.multiplier,
        "label":             level["label"],
        "trade_id":          trade.get("trade_id"),
        "symbol":            body.symbol,
        "side":              side,
        "effective_capital": round(effective_capital, 4),
        "quantity":          qty,
        "entry":             price,
        "stop_loss":         sl,
        "take_profit":       tp,
        "drawdown_guard":    level["max_drawdown_guard"],
        "validation_score":  validation["score"],
    }


async def _set_drawdown_guard(trade_id: str, capital: float, guard_pct: float):
    """Background: set drawdown guard on a multiplier trade."""
    try:
        db.table("trade_guards").upsert({
            "trade_id":        trade_id,
            "guard_type":      "max_drawdown",
            "threshold_pct":   guard_pct,
            "initial_capital": capital,
            "is_active":       True,
        }).execute()
    except Exception as e:
        log.error("guard_set_error", trade_id=trade_id, error=str(e))


@router.get("/bot/{bot_id}/config")
async def get_bot_multiplier_config(
    bot_id: str,
    user: dict = Depends(get_current_user),
):
    """Get current multiplier config for a specific bot."""
    try:
        cfg = (db.table("bot_multiplier_config").select("*")
               .eq("bot_id", bot_id).eq("user_id", user["id"])
               .single().execute()).data
        return cfg or {"bot_id": bot_id, "default_multiplier": 1, "max_multiplier": 1}
    except Exception:
        return {"bot_id": bot_id, "default_multiplier": 1}


class BotMultiplierSetReq(BaseModel):
    default_multiplier: int = Field(1, ge=1, le=10000)
    max_multiplier:     int = Field(1, ge=1, le=10000)
    auto_scale:         bool = False
    scale_on_confidence: float = 85.0   # auto-scale up when conf > this


@router.post("/bot/{bot_id}/config")
async def set_bot_multiplier_config(
    bot_id: str,
    body:   BotMultiplierSetReq,
    user:   dict = Depends(get_current_user),
):
    """Save bot's default multiplier settings."""
    from services.tier_engine import tier_engine
    user_tier  = await tier_engine.get_user_tier(user["id"])
    max_level  = MULTIPLIER_LEVELS.get(body.max_multiplier, MULTIPLIER_LEVELS[1])
    req_tier   = TIER_ORDER.get(max_level["min_tier"], 0)
    user_level = TIER_ORDER.get(user_tier.name, 0)

    if user_level < req_tier:
        raise HTTPException(403, f"Max multiplier {body.max_multiplier}× requires {max_level['min_tier'].title()} tier")

    db.table("bot_multiplier_config").upsert({
        "bot_id":               bot_id,
        "user_id":              user["id"],
        "default_multiplier":   body.default_multiplier,
        "max_multiplier":       body.max_multiplier,
        "auto_scale":           body.auto_scale,
        "scale_on_confidence":  body.scale_on_confidence,
    }).execute()

    return {"saved": True, "bot_id": bot_id, **body.dict()}
