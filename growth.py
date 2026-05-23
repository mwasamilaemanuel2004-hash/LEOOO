"""api/routes/backtest.py"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, List
router = APIRouter()

class BacktestReq(BaseModel):
    symbol: str = "BTCUSDT"
    timeframe: str = "1h"
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    genome_id: Optional[str] = None
    initial_balance: float = 10000.0
    use_best_genome: bool = True

@router.post("/backtest/run")
async def run_backtest(req: BacktestReq):
    try:
        from ai.strategy_evolver import strategy_evolver, backtest_genome
        from services.data_streamer import market_data

        # Get candles
        candles = market_data.get_candles(req.symbol, req.timeframe, n=1000) if market_data else []

        if not candles:
            # Fetch from Binance REST directly
            import httpx
            async with httpx.AsyncClient(timeout=15) as c:
                r = await c.get(
                    "https://api.binance.com/api/v3/klines",
                    params={"symbol": req.symbol.upper(), "interval": req.timeframe, "limit": 1000}
                )
                data = r.json()
                candles = [
                    {"timestamp": k[0]/1000, "open": float(k[1]), "high": float(k[2]),
                     "low": float(k[3]), "close": float(k[4]), "volume": float(k[5])}
                    for k in data
                ]

        if not candles:
            raise HTTPException(400, "No candle data available")

        # Select genome
        genome = strategy_evolver.get_best_genome() if req.use_best_genome else strategy_evolver.get_best_genome()

        # Run backtest
        result = backtest_genome(genome, candles, req.initial_balance)

        return {
            "symbol":       req.symbol,
            "timeframe":    req.timeframe,
            "candles_used": len(candles),
            "genome_id":    genome.genome_id,
            "result":       result,
            "genome": {
                "ema_fast": genome.ema_fast, "ema_slow": genome.ema_slow,
                "rsi_ob": genome.rsi_ob, "rsi_os": genome.rsi_os,
                "atr_sl_mult": genome.atr_sl_mult, "atr_tp_mult": genome.atr_tp_mult,
                "min_confidence": genome.min_confidence, "min_rr": genome.min_rr,
            },
        }
    except HTTPException: raise
    except Exception as e:
        raise HTTPException(500, str(e))

@router.get("/backtest/hall-of-fame")
async def get_hof():
    try:
        from ai.strategy_evolver import strategy_evolver
        from dataclasses import asdict
        return {
            "hall_of_fame": [asdict(g) for g in strategy_evolver.hall_of_fame],
            "stats": strategy_evolver.get_stats(),
        }
    except Exception as e:
        raise HTTPException(500, str(e))

@router.post("/backtest/evolve")
async def trigger_evolution():
    try:
        import asyncio
        from ai.strategy_evolver import strategy_evolver
        from services.data_streamer import market_data

        candles = market_data.get_candles("BTCUSDT", "1h", n=500) if market_data else []
        if candles: strategy_evolver.add_candles(candles)

        best = await asyncio.get_event_loop().run_in_executor(None, strategy_evolver.evolve)
        from dataclasses import asdict
        return {"success": True, "best": asdict(best), "generation": strategy_evolver.generation}
    except Exception as e:
        raise HTTPException(500, str(e))
