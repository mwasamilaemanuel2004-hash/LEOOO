"""
ai/signal_engine_v9.py — estrading.machine v9 GODMODE SIGNAL ENGINE
═══════════════════════════════════════════════════════════════════════════════
WHAT THIS ENGINE DOES:
  Generates professional trading signals from 9 AI engines combined.
  User can either:
    A) Let bot trade automatically (fully automated)
    B) Receive signal → trade manually on any platform
    C) Forward signal to: Telegram, MT4/5, TradingView, 3Commas, email

SIGNAL CONTAINS:
  • Symbol, Direction (BUY/SELL), Entry price
  • Stop Loss (price + % + pips)
  • Take Profit 1, 2, 3 (multiple targets)
  • Risk:Reward ratio
  • Confidence (0-100%)
  • Timeframe recommendation
  • Strategy name + special edge
  • Market feeling (emotion state)
  • Engines that agreed (vote breakdown)
  • Manual trade instructions (step-by-step)
  • Platform-specific format (MT4/5, TradingView, 3Commas, etc.)

SIGNAL DELIVERY:
  1. In-app dashboard (real-time)
  2. Telegram bot message
  3. Email alert
  4. TradingView webhook
  5. MT4/5 magic number order
  6. 3Commas signal
  7. Cornix Telegram format
  8. WhatsApp (via Twilio)
  9. Push notification (PWA)
═══════════════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations
import asyncio, json, time, math
from collections import deque
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional, List, Dict
import httpx
import structlog

log = structlog.get_logger("signal_engine_v9")


# ══════════════════════════════════════════════════════════════
# SIGNAL DATA STRUCTURE
# ══════════════════════════════════════════════════════════════

@dataclass
class TradingSignal:
    """Complete trading signal — everything a trader needs."""

    # Identity
    signal_id:    str = ""
    bot_key:      str = ""
    symbol:       str = ""
    timeframe:    str = "5m"
    timestamp:    float = field(default_factory=time.time)

    # Core signal
    direction:    str = "neutral"   # "BUY" | "SELL" | "NEUTRAL"
    signal_type:  str = "standard"  # standard | scalp | swing | reversal

    # Price levels
    entry_price:  float = 0.0
    entry_zone_lo:float = 0.0  # entry zone (low)
    entry_zone_hi:float = 0.0  # entry zone (high)
    stop_loss:    float = 0.0
    take_profit_1:float = 0.0  # conservative (1:1.5)
    take_profit_2:float = 0.0  # standard     (1:3)
    take_profit_3:float = 0.0  # aggressive   (1:5)

    # Risk metrics
    sl_pct:       float = 0.0   # SL distance as %
    tp1_pct:      float = 0.0
    tp2_pct:      float = 0.0
    tp3_pct:      float = 0.0
    rr_ratio:     float = 0.0   # TP2 / SL
    sl_pips:      float = 0.0   # for forex
    pip_value:    float = 10.0  # $ per pip (standard lot)

    # AI quality metrics
    confidence:   float = 0.0   # 0-100%
    engines_agree:int   = 0     # how many of 9 engines agreed
    engines_total:int   = 9
    emotion:      str   = "neutral"
    feeling_boost:float = 1.0

    # Strategy context
    strategy_name:str = ""
    strategy_code:str = ""
    special_edge:  str = ""
    entry_reason:  str = ""
    exit_reason:   str = ""

    # Position sizing guide
    risk_per_trade_pct: float = 1.0  # % of capital to risk
    position_size_formula: str = ""

    # Status
    status:       str = "active"    # active | hit_tp1 | hit_tp2 | hit_tp3 | stopped | expired
    pnl_pct:      float = 0.0
    won:          bool  = False

    # Platform formats (generated on demand)
    telegram_msg: str = ""
    mt4_comment:  str = ""
    tv_alert:     str = ""
    cornix_fmt:   str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    def is_valid(self) -> bool:
        return (self.direction in ("BUY","SELL") and
                self.confidence >= 60 and
                self.entry_price > 0 and
                self.stop_loss > 0 and
                self.take_profit_2 > 0)


# ══════════════════════════════════════════════════════════════
# SIGNAL GENERATOR
# ══════════════════════════════════════════════════════════════

class SignalGenerator:
    """
    Generates complete trading signals from candle + AI data.
    Includes all price levels, manual trade guide, platform formats.
    """

    # Pip size per symbol
    PIP_SIZE = {
        "EURUSD":0.0001,"GBPUSD":0.0001,"USDJPY":0.01,
        "AUDUSD":0.0001,"USDCAD":0.0001,"USDCHF":0.0001,
        "EURJPY":0.01,"GBPJPY":0.01,"XAUUSD":0.1,
        "XAGUSD":0.001,"BTCUSDT":1.0,"ETHUSDT":0.1,"SOLUSDT":0.01,
    }

    def generate(
        self,
        symbol:       str,
        candles:      List[dict],
        direction:    str,         # "BUY" | "SELL"
        confidence:   float,
        engines_agree:int,
        emotion:      str,
        feeling_boost:float,
        bot_key:      str,
        strategy_name:str,
        strategy_code:str,
        special_edge:  str,
        timeframe:    str = "5m",
        risk_pct:     float = 1.0,
    ) -> Optional[TradingSignal]:
        """Generate complete signal from AI decision."""

        if direction not in ("BUY","SELL"):
            return None
        if not candles or len(candles) < 20:
            return None

        # ── Price data ──────────────────────────────────────
        closes = [c["close"] for c in candles]
        highs  = [c["high"]  for c in candles]
        lows   = [c["low"]   for c in candles]
        price  = closes[-1]

        # ── ATR for SL/TP ───────────────────────────────────
        atrs = [max(highs[i]-lows[i], abs(highs[i]-closes[i-1]),
                    abs(lows[i]-closes[i-1]))
                for i in range(1, len(closes))]
        atr = sum(atrs[-14:]) / min(14, len(atrs)) if atrs else price * 0.01

        # ── Confidence-based SL/TP multipliers ─────────────
        # Higher confidence → tighter SL, wider TP
        if confidence >= 85:   sl_m, tp_m = 1.5, 5.0
        elif confidence >= 75: sl_m, tp_m = 2.0, 4.5
        elif confidence >= 65: sl_m, tp_m = 2.0, 3.5
        else:                  sl_m, tp_m = 2.5, 3.0

        # ── Key price levels ────────────────────────────────
        # Entry zone (±0.1% from current price for limit orders)
        entry    = price
        ez_lo    = price * (0.9995 if direction=="BUY" else 1.0005)
        ez_hi    = price * (1.0005 if direction=="BUY" else 0.9995)

        if direction == "BUY":
            sl  = price - atr * sl_m
            tp1 = price + atr * tp_m * 0.40   # 40% of full TP
            tp2 = price + atr * tp_m           # 100% — main target
            tp3 = price + atr * tp_m * 1.80   # 180% — runners
        else:
            sl  = price + atr * sl_m
            tp1 = price - atr * tp_m * 0.40
            tp2 = price - atr * tp_m
            tp3 = price - atr * tp_m * 1.80

        # ── % distances ─────────────────────────────────────
        sl_pct  = abs(price - sl)  / price * 100
        tp1_pct = abs(price - tp1) / price * 100
        tp2_pct = abs(price - tp2) / price * 100
        tp3_pct = abs(price - tp3) / price * 100
        rr      = tp2_pct / (sl_pct + 1e-9)

        # ── Pip calculation ─────────────────────────────────
        pip_size = self.PIP_SIZE.get(symbol.upper(), 0.0001)
        sl_pips  = abs(price - sl) / pip_size

        # ── Position sizing formula ─────────────────────────
        pos_formula = (
            f"Risk ${'{account_balance}'} × {risk_pct}% ÷ "
            f"({sl_pct:.2f}% × entry) = position size"
        )

        # ── Entry/exit reasons ──────────────────────────────
        entry_reason = self._build_entry_reason(direction, emotion, engines_agree, confidence)
        exit_reason  = self._build_exit_reason(direction, tp2_pct, sl_pct, rr)

        # ── Build signal ────────────────────────────────────
        import hashlib
        sig_id = hashlib.md5(f"{symbol}{time.time_ns()}".encode()).hexdigest()[:12]

        sig = TradingSignal(
            signal_id    = sig_id,
            bot_key      = bot_key,
            symbol       = symbol,
            timeframe    = timeframe,
            timestamp    = time.time(),
            direction    = direction,
            signal_type  = self._classify_type(confidence, timeframe),
            entry_price  = round(price, 6),
            entry_zone_lo= round(ez_lo, 6),
            entry_zone_hi= round(ez_hi, 6),
            stop_loss    = round(sl, 6),
            take_profit_1= round(tp1, 6),
            take_profit_2= round(tp2, 6),
            take_profit_3= round(tp3, 6),
            sl_pct       = round(sl_pct, 3),
            tp1_pct      = round(tp1_pct, 3),
            tp2_pct      = round(tp2_pct, 3),
            tp3_pct      = round(tp3_pct, 3),
            rr_ratio     = round(rr, 2),
            sl_pips      = round(sl_pips, 1),
            confidence   = round(confidence, 1),
            engines_agree= engines_agree,
            emotion      = emotion,
            feeling_boost= feeling_boost,
            strategy_name= strategy_name,
            strategy_code= strategy_code,
            special_edge  = special_edge,
            entry_reason  = entry_reason,
            exit_reason   = exit_reason,
            risk_per_trade_pct = risk_pct,
            position_size_formula = pos_formula,
            status       = "active",
        )

        # ── Generate platform formats ───────────────────────
        sig.telegram_msg = self._telegram_format(sig)
        sig.mt4_comment  = self._mt4_format(sig)
        sig.tv_alert     = self._tv_format(sig)
        sig.cornix_fmt   = self._cornix_format(sig)

        return sig

    def _classify_type(self, confidence: float, tf: str) -> str:
        if tf in ("1m","3m","5m"):      return "scalp"
        if tf in ("15m","30m"):         return "session"
        if confidence >= 80:            return "reversal" if tf in ("1h","4h") else "swing"
        return "swing"

    def _build_entry_reason(self, direction: str, emotion: str, engines: int, conf: float) -> str:
        emo_map = {
            "panic":    "Panic bottom detected — maximum fear = maximum opportunity",
            "euphoria": "Euphoria peak — contrarian reversal signal",
            "fear":     "Confirmed fear state — shorting trend continuation",
            "greed":    "Greed pullback opportunity — buy the dip",
            "optimism": "Optimistic trend — buy with trend",
            "anxiety":  "Pre-fear signal — early positioning",
            "neutral":  "Neutral conditions — technical signal only",
        }
        emo_note = emo_map.get(emotion, "")
        return (
            f"{engines}/9 AI engines agree on {direction}. "
            f"Confidence: {conf:.1f}%. "
            f"{emo_note}"
        )

    def _build_exit_reason(self, direction: str, tp2_pct: float, sl_pct: float, rr: float) -> str:
        return (
            f"Exit at TP1 ({tp2_pct*0.4:.2f}%) → move SL to breakeven. "
            f"Hold to TP2 ({tp2_pct:.2f}%) = main target. "
            f"Trail to TP3 for runners. "
            f"Hard SL at -{sl_pct:.2f}% (R:R = {rr:.1f}:1)"
        )

    def _telegram_format(self, s: TradingSignal) -> str:
        arrow = "🟢" if s.direction == "BUY" else "🔴"
        emo_icons = {"panic":"💀","euphoria":"🚀","fear":"😱","greed":"😈","optimism":"😊","neutral":"😐","anxiety":"😰"}
        emo_icon  = emo_icons.get(s.emotion, "📊")
        return (
            f"{arrow} *{s.direction} {s.symbol}* {arrow}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🎯 *Strategy:* {s.strategy_name}\n"
            f"{emo_icon} *Market Feel:* {s.emotion.upper()} ({s.confidence:.0f}% conf)\n"
            f"🤖 *AI Engines:* {s.engines_agree}/9 agree\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📥 *Entry:* `{s.entry_price}`\n"
            f"   Zone: `{s.entry_zone_lo}` – `{s.entry_zone_hi}`\n"
            f"🛑 *Stop Loss:* `{s.stop_loss}` (-{s.sl_pct:.2f}%)\n"
            f"🎯 *TP1:* `{s.take_profit_1}` (+{s.tp1_pct:.2f}%) — partial exit\n"
            f"🎯 *TP2:* `{s.take_profit_2}` (+{s.tp2_pct:.2f}%) — main target\n"
            f"🎯 *TP3:* `{s.take_profit_3}` (+{s.tp3_pct:.2f}%) — runners\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"⚖️ *R:R Ratio:* {s.rr_ratio:.1f}:1\n"
            f"📊 *Timeframe:* {s.timeframe}\n"
            f"⚡ *Edge:* {s.special_edge[:80]}...\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📋 *HOW TO TRADE MANUALLY:*\n"
            f"1️⃣ Open {s.symbol} on your platform\n"
            f"2️⃣ Place {s.direction} order at `{s.entry_price}`\n"
            f"3️⃣ Set SL at `{s.stop_loss}`\n"
            f"4️⃣ Set TP1={s.take_profit_1} | TP2={s.take_profit_2}\n"
            f"5️⃣ Risk 1-2% of account\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🤖 _estrading.machine v9 GODMODE_\n"
            f"🕐 {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC"
        )

    def _mt4_format(self, s: TradingSignal) -> str:
        action = "OP_BUY" if s.direction == "BUY" else "OP_SELL"
        return (
            f"// MT4/MT5 EA Signal — estrading.machine v9\n"
            f"// Signal ID: {s.signal_id}\n"
            f"string   symbol    = \"{s.symbol}\";\n"
            f"int      operation = {action};\n"
            f"double   price     = {s.entry_price};\n"
            f"double   stoploss  = {s.stop_loss};\n"
            f"double   takeprofit= {s.take_profit_2};\n"
            f"string   comment   = \"{s.strategy_code}_{s.signal_id}\";\n"
            f"double   lots      = 0.01; // Adjust to your risk\n"
            f"// Confidence: {s.confidence}% | R:R: {s.rr_ratio}:1\n"
            f"OrderSend(symbol,operation,lots,price,3,stoploss,takeprofit,comment,0,0,clrGreen);"
        )

    def _tv_format(self, s: TradingSignal) -> str:
        return json.dumps({
            "action":   s.direction.lower(),
            "ticker":   s.symbol,
            "price":    s.entry_price,
            "sl":       s.stop_loss,
            "tp":       s.take_profit_2,
            "qty":      "1%",
            "comment":  f"{s.strategy_code}|{s.signal_id}|conf={s.confidence}",
            "source":   "estrading_machine_v9",
            "timeframe":s.timeframe,
            "rr":       s.rr_ratio,
        })

    def _cornix_format(self, s: TradingSignal) -> str:
        return (
            f"#{s.symbol} #{s.direction}\n\n"
            f"Exchange: Binance\n"
            f"Leverage: Cross (1-3x)\n\n"
            f"Entry: {s.entry_zone_lo} - {s.entry_zone_hi}\n\n"
            f"Take-Profit Targets:\n"
            f"1) {s.take_profit_1}\n"
            f"2) {s.take_profit_2}\n"
            f"3) {s.take_profit_3}\n\n"
            f"Stop Targets:\n"
            f"1) {s.stop_loss}\n\n"
            f"Risk Level: {int(s.confidence)}% Confidence\n"
            f"Strategy: {s.strategy_name}"
        )


signal_generator = SignalGenerator()


# ══════════════════════════════════════════════════════════════
# SIGNAL DELIVERY ENGINE
# ══════════════════════════════════════════════════════════════

class SignalDelivery:
    """
    Delivers signals to multiple platforms simultaneously.
    Each delivery is non-blocking and fault-tolerant.
    """

    def __init__(self):
        self.delivered:  deque = deque(maxlen=500)
        self.failed:     deque = deque(maxlen=100)
        self.stats = {"telegram":0,"email":0,"webhook":0,"db":0,"total":0}

    async def deliver_all(
        self,
        signal:      TradingSignal,
        user_config: dict,
        db_client=None,
    ):
        """Deliver signal to all configured channels."""
        tasks = []

        # 1. Always save to Supabase DB
        if db_client:
            tasks.append(self._save_to_db(signal, user_config.get("user_id"), db_client))

        # 2. Telegram
        if user_config.get("telegram_token") and user_config.get("telegram_chat_id"):
            tasks.append(self._send_telegram(
                signal,
                user_config["telegram_token"],
                user_config["telegram_chat_id"],
            ))

        # 3. Email (via SendGrid or SMTP)
        if user_config.get("email") and user_config.get("email_alerts"):
            tasks.append(self._send_email(signal, user_config["email"]))

        # 4. TradingView Webhook
        if user_config.get("tv_webhook_url"):
            tasks.append(self._send_webhook(signal, user_config["tv_webhook_url"]))

        # 5. Custom webhook (3Commas, Cornix, etc.)
        if user_config.get("custom_webhook"):
            tasks.append(self._send_webhook(signal, user_config["custom_webhook"],
                                            format="cornix"))

        # Run all deliveries concurrently
        results = await asyncio.gather(*tasks, return_exceptions=True)
        self.stats["total"] += 1
        self.delivered.append({"sig_id": signal.signal_id, "ts": time.time(),
                                "results": str(results)})
        return results

    async def _save_to_db(self, sig: TradingSignal, user_id: str, db):
        """Save signal to Supabase signals table."""
        try:
            row = {
                "signal_id":     sig.signal_id,
                "user_id":       user_id,
                "bot_key":       sig.bot_key,
                "symbol":        sig.symbol,
                "timeframe":     sig.timeframe,
                "direction":     sig.direction,
                "signal_type":   sig.signal_type,
                "entry_price":   sig.entry_price,
                "entry_zone_lo": sig.entry_zone_lo,
                "entry_zone_hi": sig.entry_zone_hi,
                "stop_loss":     sig.stop_loss,
                "take_profit_1": sig.take_profit_1,
                "take_profit_2": sig.take_profit_2,
                "take_profit_3": sig.take_profit_3,
                "sl_pct":        sig.sl_pct,
                "tp2_pct":       sig.tp2_pct,
                "rr_ratio":      sig.rr_ratio,
                "sl_pips":       sig.sl_pips,
                "confidence":    sig.confidence,
                "engines_agree": sig.engines_agree,
                "emotion":       sig.emotion,
                "feeling_boost": sig.feeling_boost,
                "strategy_name": sig.strategy_name,
                "strategy_code": sig.strategy_code,
                "special_edge":  sig.special_edge[:500] if sig.special_edge else "",
                "entry_reason":  sig.entry_reason,
                "status":        "active",
                "telegram_msg":  sig.telegram_msg[:2000],
                "mt4_comment":   sig.mt4_comment[:500],
                "tv_alert":      sig.tv_alert[:1000],
                "cornix_fmt":    sig.cornix_fmt[:1000],
            }
            db.table("signals_v9").insert(row).execute()
            self.stats["db"] += 1
            log.info("Signal saved to DB", sig_id=sig.signal_id)
        except Exception as e:
            log.error("DB save failed", error=str(e))

    async def _send_telegram(self, sig: TradingSignal, token: str, chat_id: str):
        """Send signal via Telegram Bot API."""
        try:
            url = f"https://api.telegram.org/bot{token}/sendMessage"
            async with httpx.AsyncClient(timeout=10) as cl:
                r = await cl.post(url, json={
                    "chat_id":    chat_id,
                    "text":       sig.telegram_msg,
                    "parse_mode": "Markdown",
                })
                if r.status_code == 200:
                    self.stats["telegram"] += 1
                    log.info("Telegram signal sent", sig_id=sig.signal_id)
                else:
                    log.warning("Telegram failed", status=r.status_code)
        except Exception as e:
            log.error("Telegram error", error=str(e))

    async def _send_email(self, sig: TradingSignal, email: str):
        """Send signal via email (placeholder — configure SMTP or SendGrid)."""
        try:
            # Email body
            body = f"""
estrading.machine v9 — New Trading Signal
==========================================
{sig.direction} {sig.symbol} | {sig.strategy_name}
Confidence: {sig.confidence:.1f}% | Engines: {sig.engines_agree}/9

Entry:    {sig.entry_price}
Stop Loss:{sig.stop_loss} (-{sig.sl_pct:.2f}%)
TP1:      {sig.take_profit_1} (+{sig.tp1_pct:.2f}%)
TP2:      {sig.take_profit_2} (+{sig.tp2_pct:.2f}%)
TP3:      {sig.take_profit_3} (+{sig.tp3_pct:.2f}%)
R:R:      {sig.rr_ratio:.1f}:1

Strategy Edge: {sig.special_edge}
Emotion: {sig.emotion.upper()}

HOW TO TRADE MANUALLY:
1. Open {sig.symbol} on your broker
2. Place {sig.direction} at {sig.entry_price}
3. Set Stop Loss: {sig.stop_loss}
4. Set Take Profit: {sig.take_profit_2}
5. Risk 1-2% of your account

Signal ID: {sig.signal_id}
"""
            self.stats["email"] += 1
            log.info("Email signal prepared", to=email, sig_id=sig.signal_id)
        except Exception as e:
            log.error("Email error", error=str(e))

    async def _send_webhook(self, sig: TradingSignal, url: str, format: str = "json"):
        """Send signal to custom webhook (3Commas, TradingView, Cornix, etc.)."""
        try:
            payload = sig.cornix_fmt if format == "cornix" else json.loads(sig.tv_alert)
            async with httpx.AsyncClient(timeout=10) as cl:
                if format == "cornix":
                    r = await cl.post(url, content=payload,
                                      headers={"Content-Type":"text/plain"})
                else:
                    r = await cl.post(url, json=payload)
                if r.status_code < 400:
                    self.stats["webhook"] += 1
                    log.info("Webhook delivered", url=url[:50], sig_id=sig.signal_id)
        except Exception as e:
            log.error("Webhook error", error=str(e))


signal_delivery = SignalDelivery()


# ══════════════════════════════════════════════════════════════
# LIVE SIGNAL TRACKER
# ══════════════════════════════════════════════════════════════

class SignalTracker:
    """
    Tracks open signals. Updates status when TP/SL hit.
    Calculates signal accuracy over time.
    """

    def __init__(self):
        self.active: Dict[str, TradingSignal] = {}
        self.history: deque = deque(maxlen=1000)
        self.accuracy_stats = {
            "total":0,"tp1_hit":0,"tp2_hit":0,"tp3_hit":0,"sl_hit":0,
            "tp2_rate":0.0,"avg_rr":0.0,
        }

    def add(self, sig: TradingSignal):
        self.active[sig.signal_id] = sig

    def update_price(self, symbol: str, current_price: float):
        """Check if any active signals hit TP or SL."""
        to_close = []
        for sig_id, sig in self.active.items():
            if sig.symbol != symbol: continue
            if sig.direction == "BUY":
                if current_price <= sig.stop_loss:
                    sig.status = "stopped"; sig.won = False
                    sig.pnl_pct = -sig.sl_pct; to_close.append(sig_id)
                elif current_price >= sig.take_profit_3:
                    sig.status = "hit_tp3"; sig.won = True
                    sig.pnl_pct = sig.tp3_pct; to_close.append(sig_id)
                elif current_price >= sig.take_profit_2:
                    sig.status = "hit_tp2"; sig.won = True
                    sig.pnl_pct = sig.tp2_pct
                elif current_price >= sig.take_profit_1:
                    sig.status = "hit_tp1"
            else:
                if current_price >= sig.stop_loss:
                    sig.status = "stopped"; sig.won = False
                    sig.pnl_pct = -sig.sl_pct; to_close.append(sig_id)
                elif current_price <= sig.take_profit_3:
                    sig.status = "hit_tp3"; sig.won = True
                    sig.pnl_pct = sig.tp3_pct; to_close.append(sig_id)
                elif current_price <= sig.take_profit_2:
                    sig.status = "hit_tp2"; sig.won = True
                    sig.pnl_pct = sig.tp2_pct
                elif current_price <= sig.take_profit_1:
                    sig.status = "hit_tp1"

        for sid in to_close:
            sig = self.active.pop(sid, None)
            if sig:
                self.history.append(sig)
                self._update_stats(sig)

    def _update_stats(self, sig: TradingSignal):
        s = self.accuracy_stats
        s["total"] += 1
        if sig.status == "hit_tp1": s["tp1_hit"] += 1
        if sig.status == "hit_tp2": s["tp2_hit"] += 1
        if sig.status == "hit_tp3": s["tp3_hit"] += 1
        if sig.status == "stopped": s["sl_hit"]  += 1
        s["tp2_rate"] = round(s["tp2_hit"] / max(s["total"],1) * 100, 1)
        pnls = [h.pnl_pct for h in self.history if h.pnl_pct != 0]
        if pnls:
            avg_win  = sum(p for p in pnls if p>0) / max(sum(1 for p in pnls if p>0),1)
            avg_loss = abs(sum(p for p in pnls if p<0) / max(sum(1 for p in pnls if p<0),1))
            s["avg_rr"] = round(avg_win / (avg_loss+1e-9), 2)

    def get_active(self, symbol: str = None) -> List[dict]:
        sigs = list(self.active.values())
        if symbol:
            sigs = [s for s in sigs if s.symbol == symbol]
        return [s.to_dict() for s in sigs]

    def get_history(self, limit: int = 50) -> List[dict]:
        return [s.to_dict() for s in list(self.history)[-limit:]]

    def get_accuracy(self) -> dict:
        return self.accuracy_stats


signal_tracker = SignalTracker()
