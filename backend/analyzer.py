import pandas as pd
import numpy as np
from backend.data_loader import fetch_data
from backend.backtester import Backtester

def analyze_and_compare(symbol):
    print(f"\n--- Analysis for {symbol} ---")
    df = fetch_data(symbol)
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index, utc=True)

    bt = Backtester(df, commission=0.001) # 0.1% commission

    # Buy and Hold Metrics
    bh_returns = df['Close'].pct_change().fillna(0)
    bh_equity = (1 + bh_returns).cumprod() * 10000
    bh_total_return = (bh_equity.iloc[-1] / 10000) - 1

    days = (df.index[-1] - df.index[0]).days
    bh_annualized = (1 + bh_total_return) ** (365.0 / days) - 1
    bh_vol = bh_returns.std() * np.sqrt(252)
    bh_sharpe = bh_annualized / bh_vol if bh_vol > 0 else 0
    bh_drawdown = (bh_equity / bh_equity.cummax() - 1).min()

    print(f"Buy & Hold: Return={bh_total_return:.2%}, Ann.={bh_annualized:.2%}, Sharpe={bh_sharpe:.2f}, MaxDD={bh_drawdown:.2%}")

    # Strategy Metrics
    upgraded_metrics = bt.run_upgraded_strategy()
    print(f"Upgraded SMA+RSI: Return={upgraded_metrics['total_return']:.2%}, Ann.={upgraded_metrics['annualized_return']:.2%}, Sharpe={upgraded_metrics['sharpe_ratio']:.2f}, MaxDD={upgraded_metrics['max_drawdown']:.2%}")
    print(f"Stats: Trades={upgraded_metrics['num_trades']}, Estimated Comm.=${upgraded_metrics['total_commissions']:.2f}")

if __name__ == "__main__":
    for s in ["SPY", "QQQ", "BTC-USD"]:
        try:
            analyze_and_compare(s)
        except Exception as e:
            print(f"Failed to analyze {s}: {e}")
