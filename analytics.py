"""api/routes/strategy.py"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
router = APIRouter()

@router.get("/strategy/stats")
async def strategy_stats():
    try:
        from ai.strategy_evolver import strategy_evolver
        return strategy_evolver.get_stats()
    except Exception as e:
        raise HTTPException(500, str(e))

@router.get("/strategy/top")
async def top_strategies(n: int = 5):
    try:
        from ai.strategy_evolver import strategy_evolver
        from dataclasses import asdict
        genomes = strategy_evolver.get_top_n_genomes(n)
        return {"strategies": [asdict(g) for g in genomes]}
    except Exception as e:
        raise HTTPException(500, str(e))

@router.get("/strategy/best")
async def best_strategy():
    try:
        from ai.strategy_evolver import strategy_evolver
        from dataclasses import asdict
        g = strategy_evolver.get_best_genome()
        return asdict(g)
    except Exception as e:
        raise HTTPException(500, str(e))

@router.get("/strategy/regime/{regime}")
async def strategy_for_regime(regime: str):
    try:
        from ai.strategy_evolver import strategy_evolver
        from dataclasses import asdict
        g = strategy_evolver.get_genome_for_regime(regime)
        return asdict(g) if g else {}
    except Exception as e:
        raise HTTPException(500, str(e))
