from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import os

from .data_loader import fetch_data
from .backtester import Backtester

app = FastAPI()

class BacktestRequest(BaseModel):
    symbol: str = "SPY"
    strategy: str = "sma_crossover"
    short_window: int = 50
    long_window: int = 200
    initial_capital: float = 10000.0

@app.get("/api/health")
def health():
    return {"status": "ok"}

@app.post("/api/backtest")
def run_backtest(request: BacktestRequest):
    try:
        df = fetch_data(request.symbol)
        bt = Backtester(df, initial_capital=request.initial_capital)

        if request.strategy == "sma_crossover":
            metrics = bt.run_sma_crossover(request.short_window, request.long_window)
        elif request.strategy == "upgraded":
            metrics = bt.run_upgraded_strategy(request.short_window, request.long_window)
        else:
            raise HTTPException(status_code=400, detail="Strategy not supported")

        chart_data = {
            "labels": bt.results.index.strftime('%Y-%m-%d').tolist(),
            "equity": bt.results['Equity_Curve'].tolist(),
            "price": bt.results['Close'].tolist()
        }

        return {
            "metrics": metrics,
            "chart_data": chart_data
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if os.path.exists("frontend"):
    app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
