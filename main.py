"""main.py — estrading.machine v10 GODMODE — All 39 subsystems"""
from __future__ import annotations
import asyncio, os, sys
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
import uvicorn

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("🚀 estrading.machine v10 GODMODE starting...")
    tasks = []
    for mod, attr in [
        ("ai.self_healing_monitor","self_healing_monitor"),
        ("ai.self_updater","ai_self_updater"),
        ("ai.whale_tracker","whale_tracker"),
    ]:
        try:
            import importlib
            m = importlib.import_module(mod)
            obj = getattr(m, attr, None)
            if obj and hasattr(obj, "run"):
                tasks.append(asyncio.create_task(obj.run()))
                print(f"  ✅ {attr} started")
        except Exception as e:
            print(f"  ⚠ {attr}: {e}")
    print(f"✅ {len(tasks)} background services running")
    yield
    for t in tasks: t.cancel()
    print("🛑 v10 shutdown complete")

app = FastAPI(
    title="estrading.machine v10 GODMODE API",
    description="Ultra-Advanced AI Trading System | +255653712466 | estradingmachine@gmail.com",
    version="10.0.0",
    docs_url="/api/docs",
    lifespan=lifespan,
)

ORIGINS = [
    os.getenv("FRONTEND_URL","https://estrading-machine.vercel.app"),
    "https://estrading.machine","https://www.estrading.machine",
    "http://localhost:5173","http://localhost:3000","*"
]
app.add_middleware(CORSMiddleware, allow_origins=ORIGINS,
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.add_middleware(GZipMiddleware, minimum_size=1000)

@app.get("/")
@app.get("/api/health")
async def health():
    return {
        "status":"ok","version":"10.0.0","service":"estrading.machine v10 GODMODE",
        "subsystems":39,"bots":43,"ai_models":9,"contact":"+255653712466",
        "email":"estradingmachine@gmail.com",
        "features":["RL_PPO_DQN_A3C","LSTM","Transformer","DualAI","MarketFeeling",
                    "StrategyEvolver","MoneyPrinter","TrailingEngine","ProfitLock",
                    "DisciplineEngine","WhaleTracker","SignalEngine","ReinvestEngine",
                    "AdminTokens","GrowthTracker","TimeframeEngine"]
    }

ROUTERS = [
    "api.routes.auth","api.routes.users","api.routes.wallets","api.routes.tokens",
    "api.routes.bots","api.routes.trades","api.routes.portfolio","api.routes.exchange",
    "api.routes.rl","api.routes.backtest","api.routes.strategy","api.routes.strategies",
    "api.routes.signals","api.routes.analytics","api.routes.risk","api.routes.money_print",
    "api.routes.stream","api.routes.security","api.routes.maintenance",
    "api.routes.payments","api.routes.payment","api.routes.multiplier",
    "api.routes.admin","api.routes.admin_tokens","api.routes.reinvest",
    "api.routes.timeframes","api.routes.growth",
]

for module in ROUTERS:
    try:
        import importlib
        mod = importlib.import_module(module)
        tag = module.split(".")[-1]
        app.include_router(mod.router, prefix="/api", tags=[tag])
        print(f"  ✅ {tag}")
    except Exception as e:
        print(f"  ⚠ {module}: {e}")

@app.exception_handler(Exception)
async def global_exc(req: Request, exc: Exception):
    return JSONResponse(500, {"error": str(exc), "service": "estrading.machine v10"})

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0",
                port=int(os.getenv("PORT", 8000)),
                reload=os.getenv("ENV","production")=="development")
