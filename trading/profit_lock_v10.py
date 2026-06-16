"""
ai/news_service.py — Production News Sentiment Engine
Polls public RSS/API feeds every 3 minutes.
Scores headlines with weighted lexicon + negation handling.
Stores results in Supabase news_sentiment table.
Provides per-coin sentiment for strategy boosting.
"""
from __future__ import annotations
import asyncio, hashlib, re
from datetime import datetime, timezone
from typing import Optional
import httpx
from core.database import db
import structlog

log = structlog.get_logger("news_service")

BULLISH = {
    "surge":1.0,"soar":1.0,"rally":0.9,"breakout":0.85,"record high":1.0,
    "all-time high":1.0,"ath":1.0,"approved":0.85,"etf":0.8,"adoption":0.8,
    "partnership":0.7,"upgrade":0.7,"bullish":0.9,"inflows":0.8,
    "accumulation":0.8,"institutional":0.75,"bullrun":0.9,"moon":0.9,
    "listing":0.7,"milestone":0.65,"growth":0.6,"invest":0.6,"launch":0.6,
    "outperform":0.75,"positive":0.5,"gain":0.65,"whale buy":0.9,
}
BEARISH = {
    "crash":-1.0,"collapse":-1.0,"dump":-0.9,"plunge":-0.95,
    "ban":-0.9,"banned":-1.0,"hack":-0.95,"exploit":-0.9,"fraud":-1.0,
    "scam":-1.0,"rug":-1.0,"bearish":-0.9,"sec charges":-1.0,"lawsuit":-0.85,
    "warning":-0.7,"fear":-0.7,"panic":-0.85,"liquidation":-0.8,
    "outflows":-0.8,"sell-off":-0.8,"decline":-0.7,"drop":-0.75,
    "suspended":-0.85,"delisted":-0.95,"shutdown":-0.9,"regulation":-0.5,
    "investigation":-0.75,"fine":-0.7,"penalty":-0.65,"risk":-0.4,
}
AMPLIFIERS = {
    "massive":1.4,"historic":1.3,"huge":1.3,"extreme":1.25,"record":1.2,
    "minor":0.5,"small":0.6,"slight":0.5,"tiny":0.4,"possible":0.6,
}
NEGATIONS = {"not","never","no","without","despite","against","failed","denies"}
COIN_MAP = {
    "BTC":["bitcoin","btc","satoshi"],"ETH":["ethereum","eth","ether"],
    "BNB":["binance","bnb","bsc"],"SOL":["solana","sol"],
    "XRP":["ripple","xrp"],"ADA":["cardano","ada"],
    "DOT":["polkadot","dot"],"MATIC":["polygon","matic"],
    "AVAX":["avalanche","avax"],"LINK":["chainlink","link"],
    "DOGE":["dogecoin","doge"],"EUR/USD":["euro","eurusd","ecb"],
    "GBP/USD":["pound","gbp","sterling"],"USD/JPY":["yen","jpy","boj"],
}
RSS_FEEDS = [
    "https://cointelegraph.com/rss",
    "https://coindesk.com/arc/outboundfeeds/rss/",
    "https://cryptoslate.com/feed/",
    "https://decrypt.co/feed",
]


def _score(text: str) -> tuple[float, str]:
    words = text.lower().split()
    score, count, negated = 0.0, 0, False
    for i, w in enumerate(words):
        c = w.strip(".,!?;:()'\"")
        if c in NEGATIONS:
            negated = True; continue
        amp = next((v for k, v in AMPLIFIERS.items() if k in words[max(0,i-2):i]), 1.0)
        for phrase, val in {**BULLISH, **BEARISH}.items():
            bigram = f"{words[i-1].strip('.,!?') if i>0 else ''} {c}"
            if phrase in c or (phrase in bigram):
                adj = val * amp * (-0.7 if negated else 1.0)
                score += adj; count += 1; negated = False; break
    if count == 0:
        return 0.0, "NEUTRAL"
    norm = max(-1.0, min(1.0, score / max(count, 3)))
    label = "BULLISH" if norm > 0.15 else "BEARISH" if norm < -0.15 else "NEUTRAL"
    return round(norm, 4), label


def _coins(text: str) -> list[str]:
    t = text.lower()
    return [coin for coin, kws in COIN_MAP.items() if any(k in t for k in kws)]


def _impact(score: float, text: str) -> str:
    high_words = ["etf","sec","hack","exploit","crash","all-time high","federal reserve","ban","approve","regulation"]
    if abs(score) > 0.6 or any(w in text.lower() for w in high_words):
        return "HIGH"
    return "MEDIUM" if abs(score) > 0.3 else "LOW"


def _parse_rss(xml: str, source: str) -> list[dict]:
    items = []
    for block in re.findall(r'<item>(.*?)</item>', xml, re.DOTALL):
        title = re.search(r'<title>(.*?)</title>', block, re.DOTALL)
        desc  = re.search(r'<description>(.*?)</description>', block, re.DOTALL)
        pub   = re.search(r'<pubDate>(.*?)</pubDate>', block)
        link  = re.search(r'<link>(.*?)</link>', block)
        if not title:
            continue
        headline = re.sub(r'<[^>]+>', '', title.group(1)).strip()[:300]
        body = headline + " " + (re.sub(r'<[^>]+>', '', (desc.group(1) if desc else "")).strip()[:500])
        score, label = _score(body)
        items.append({
            "headline": headline,
            "source": source.split("/")[2] if "/" in source else source,
            "sentiment": label,
            "sentiment_score": score,
            "coins_mentioned": _coins(body),
            "impact_level": _impact(score, body),
            "raw_url": (link.group(1).strip() if link else "")[:500],
            "published_at": (pub.group(1).strip() if pub else None),
        })
    return items[:15]


class NewsService:
    def __init__(self):
        self._cache: dict[str, float] = {}   # headline_hash → score
        self._running = False

    async def start(self):
        self._running = True
        log.info("news_service_started")
        while self._running:
            try:
                await self._fetch_cycle()
            except Exception as e:
                log.error("news_cycle_error", error=str(e))
            await asyncio.sleep(180)  # 3 minutes

    async def _fetch_cycle(self):
        new_items = []
        async with httpx.AsyncClient(
            timeout=10,
            headers={"User-Agent": "ESTRADE-NewsBot/5.0"}
        ) as client:
            for url in RSS_FEEDS:
                try:
                    r = await client.get(url)
                    if r.status_code == 200:
                        parsed = _parse_rss(r.text, url)
                        for item in parsed:
                            h = hashlib.md5(item["headline"].encode()).hexdigest()
                            if h not in self._cache:
                                self._cache[h] = item["sentiment_score"]
                                new_items.append(item)
                except Exception:
                    pass

        if new_items:
            db.table("news_sentiment").insert(new_items).execute()
            log.info("news_fetched", count=len(new_items))
        # Keep cache bounded
        if len(self._cache) > 2000:
            oldest = list(self._cache.keys())[:500]
            for k in oldest:
                del self._cache[k]

    async def get_coin_sentiment(self, coin: str, hours: int = 6) -> dict:
        since = (datetime.now(timezone.utc).replace(tzinfo=None)
                 - __import__('datetime').timedelta(hours=hours)).isoformat()
        rows = (db.table("news_sentiment")
                .select("sentiment_score, impact_level")
                .gte("created_at", since)
                .execute()).data or []

        relevant = [r for r in rows
                    if coin in (r.get("coins_mentioned") or [])]
        if not relevant:
            return {"coin": coin, "score": 0.0, "label": "NEUTRAL",
                    "articles": 0, "impact_articles": 0}

        # Weight high-impact articles 2x
        weighted = sum(
            float(r["sentiment_score"]) * (2 if r.get("impact_level") == "HIGH" else 1)
            for r in relevant
        )
        weight_sum = sum(2 if r.get("impact_level") == "HIGH" else 1 for r in relevant)
        score = weighted / weight_sum if weight_sum > 0 else 0.0
        label = "BULLISH" if score > 0.1 else "BEARISH" if score < -0.1 else "NEUTRAL"
        return {
            "coin": coin,
            "score": round(score, 4),
            "label": label,
            "articles": len(relevant),
            "impact_articles": sum(1 for r in relevant if r.get("impact_level") == "HIGH"),
        }

    async def get_market_narrative(self) -> dict:
        rows = (db.table("news_sentiment")
                .select("sentiment_score, coins_mentioned, impact_level")
                .order("created_at", desc=True)
                .limit(60)
                .execute()).data or []
        if not rows:
            return {"narrative": "NEUTRAL", "score": 0.0, "confidence": 0}
        scores = [float(r.get("sentiment_score") or 0) for r in rows]
        avg    = sum(scores) / len(scores)
        narrative = "BULLISH" if avg > 0.1 else "BEARISH" if avg < -0.1 else "NEUTRAL"
        high_count = sum(1 for r in rows if r.get("impact_level") == "HIGH")
        return {
            "narrative": narrative,
            "score": round(avg, 4),
            "confidence": min(100, int(abs(avg) * 150 + high_count * 5)),
            "total_articles": len(rows),
            "high_impact": high_count,
            "last_update": datetime.now(timezone.utc).isoformat(),
        }

    async def get_latest(self, limit: int = 20, coin: str = None) -> list:
        q = db.table("news_sentiment").select("*").order("created_at", desc=True).limit(limit)
        rows = q.execute().data or []
        if coin:
            rows = [r for r in rows if coin in (r.get("coins_mentioned") or [])]
        return rows[:limit]


news_service = NewsService()
