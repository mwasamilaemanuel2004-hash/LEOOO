import yfinance as yf
import pandas as pd
import os

def fetch_data(symbol: str, period: str = "10y") -> pd.DataFrame:
    """
    Fetches historical data for a given symbol from Yahoo Finance.
    """
    data_dir = "data"
    if not os.path.exists(data_dir):
        os.makedirs(data_dir)

    file_path = os.path.join(data_dir, f"{symbol}_{period}.csv")

    if os.path.exists(file_path):
        print(f"Loading data from {file_path}")
        return pd.read_csv(file_path, index_col=0, parse_dates=True)

    print(f"Fetching data for {symbol} for period {period}")
    ticker = yf.Ticker(symbol)
    df = ticker.history(period=period)

    if df.empty:
        raise ValueError(f"No data found for symbol {symbol}")

    df.to_csv(file_path)
    return df

if __name__ == "__main__":
    # Test fetching data
    df = fetch_data("SPY")
    print(df.head())
    print(df.tail())
