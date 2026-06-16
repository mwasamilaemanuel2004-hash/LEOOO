"""api/routes/stream.py — Live data streaming endpoints"""
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
import asyncio, json, time
router = APIRouter()

@router.get("/stream/price/{symbol}")
async def price_stream(symbol: str):
    """SSE endpoint for live price stream."""
    async def event_stream():
        try:
            from services.data_streamer import market_data
        except ImportError:
            market_data = None

        while True:
            try:
                price = None
                if market_data:
                    price = market_data.get_latest_price(symbol)
                if price is None:
                    # Fallback: Binance REST
                    import httpx
                    async with httpx.AsyncClient(timeout=3) as c:
                        r = await c.get(
                            "https://api.binance.com/api/v3/ticker/price",
                            params={"symbol": symbol.upper()}
                        )
                        price = float(r.json().get("price", 0))

                data = json.dumps({"symbol": symbol, "price": price, "ts": time.time()})
                yield f"data: {data}\n\n"
            except Exception as e:
                yield f"data: {json.dumps({'error': str(e)})}\n\n"

            await asyncio.sleep(1)

    return StreamingResponse(event_stream(), media_type="text/event-stream",
                              headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

@router.get("/stream/status")
async def stream_status():
    try:
        from services.data_streamer import market_data
        return market_data.get_status() if market_data else {"running": False}
    except Exception as e:
        raise HTTPException(500, str(e))

@router.get("/stream/candles/{symbol}/{timeframe}")
async def get_candles(symbol: str, timeframe: str = "5m", n: int = 200):
    try:
        from services.data_streamer import market_data
        candles = market_data.get_candles(symbol, timeframe, n) if market_data else []

        if not candles:
            import httpx
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.get(
                    "https://api.binance.com/api/v3/klines",
                    params={"symbol": symbol.upper(), "interval": timeframe, "limit": min(n, 500)}
                )
                data = r.json()
                candles = [
                    {"timestamp": k[0]/1000, "open": float(k[1]), "high": float(k[2]),
                     "low": float(k[3]), "close": float(k[4]), "volume": float(k[5])}
                    for k in data
                ]

        return {"symbol": symbol, "timeframe": timeframe, "candles": candles, "count": len(candles)}
    except Exception as e:
        raise HTTPException(500, str(e))

@router.get("/stream/orderbook/{symbol}")
async def get_orderbook(symbol: str):
    try:
        from services.data_streamer import market_data
        ob = market_data.get_order_book(symbol) if market_data else None
        if ob:
            return {"symbol": symbol, "bids": ob.bids[:10], "asks": ob.asks[:10],
                    "spread": round(ob.spread, 6), "imbalance": round(ob.imbalance, 4)}
        # Fallback REST
        import httpx
        async with httpx.AsyncClient(timeout=5) as c:
            r = await c.get("https://api.binance.com/api/v3/depth",
                            params={"symbol": symbol.upper(), "limit": 10})
            d = r.json()
            bids = [[float(p), float(q)] for p, q in d.get("bids", [])]
            asks = [[float(p), float(q)] for p, q in d.get("asks", [])]
            spread = asks[0][0] - bids[0][0] if bids and asks else 0
            return {"symbol": symbol, "bids": bids, "asks": asks, "spread": round(spread, 6)}
    except Exception as e:
        raise HTTPException(500, str(e))

@router.post("/stream/subscribe/{symbol}")
async def subscribe(symbol: str, timeframes: list[str] = None):
    try:
        from services.data_streamer import market_data
        if market_data:
            market_data.ws_client.subscribe(symbol, timeframes or ["1m", "5m", "15m", "1h"])
        return {"success": True, "symbol": symbol}
    except Exception as e:
        raise HTTPException(500, str(e))
