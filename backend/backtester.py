import pandas as pd
import numpy as np

class Backtester:
    def __init__(self, data: pd.DataFrame, initial_capital: float = 10000.0):
        self.data = data.copy()
        if not isinstance(self.data.index, pd.DatetimeIndex):
            self.data.index = pd.to_datetime(self.data.index, utc=True)
        self.initial_capital = initial_capital
        self.results = None

    def run_sma_crossover(self, short_window: int = 50, long_window: int = 200):
        """
        Simple SMA Crossover Strategy.
        """
        df = self.data.copy()
        df['SMA_Short'] = df['Close'].rolling(window=short_window).mean()
        df['SMA_Long'] = df['Close'].rolling(window=long_window).mean()

        df['Signal'] = 0.0
        mask = (df['SMA_Short'] > df['SMA_Long'])
        df.loc[mask, 'Signal'] = 1.0

        return self._calculate_backtest(df)

    def run_upgraded_strategy(self, short_window: int = 50, long_window: int = 200, rsi_period: int = 14):
        """
        Upgraded Strategy: SMA Crossover + RSI Filter.
        Avoids buying when RSI is extremely overbought (> 70) and
        stays in trade only if price is above a trailing stop or
        exits if SMA crosses back.
        """
        df = self.data.copy()
        df['SMA_Short'] = df['Close'].rolling(window=short_window).mean()
        df['SMA_Long'] = df['Close'].rolling(window=long_window).mean()

        # RSI Calculation
        delta = df['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=rsi_period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=rsi_period).mean()
        rs = gain / loss
        df['RSI'] = 100 - (100 / (1 + rs))

        df['Signal'] = 0.0

        # Logic:
        # Buy if SMA_Short > SMA_Long AND RSI < 70
        # Exit if SMA_Short < SMA_Long

        current_signal = 0.0
        signals = []
        for i in range(len(df)):
            if pd.isna(df['SMA_Long'].iloc[i]):
                signals.append(0.0)
                continue

            if df['SMA_Short'].iloc[i] > df['SMA_Long'].iloc[i]:
                if current_signal == 0.0:
                    if df['RSI'].iloc[i] < 70:
                        current_signal = 1.0
                # else keep signal at 1.0
            else:
                current_signal = 0.0

            signals.append(current_signal)

        df['Signal'] = signals
        return self._calculate_backtest(df)

    def _calculate_backtest(self, df):
        df['Position'] = df['Signal'].diff()
        df['Returns'] = df['Close'].pct_change()
        df['Strategy_Returns'] = df['Returns'] * df['Signal'].shift(1)

        df['Equity_Curve'] = (1.0 + df['Strategy_Returns'].fillna(0)).cumprod() * self.initial_capital

        self.results = df
        return self.calculate_metrics(df)

    def calculate_metrics(self, df):
        total_return = (df['Equity_Curve'].iloc[-1] / self.initial_capital) - 1

        days = (df.index[-1] - df.index[0]).days
        if days == 0:
            annualized_return = 0
        else:
            annualized_return = (1 + total_return) ** (365.0 / days) - 1

        daily_std = df['Strategy_Returns'].std()
        annualized_vol = daily_std * np.sqrt(252) if not np.isnan(daily_std) else 0

        sharpe_ratio = annualized_return / annualized_vol if annualized_vol > 0 else 0

        rolling_max = df['Equity_Curve'].cummax()
        drawdown = df['Equity_Curve'] / rolling_max - 1
        max_drawdown = drawdown.min()

        return {
            "total_return": float(total_return),
            "annualized_return": float(annualized_return),
            "annualized_vol": float(annualized_vol),
            "sharpe_ratio": float(sharpe_ratio),
            "max_drawdown": float(max_drawdown),
            "final_value": float(df['Equity_Curve'].iloc[-1])
        }

if __name__ == "__main__":
    from data_loader import fetch_data
    import os
    if os.path.basename(os.getcwd()) == "backend":
        os.chdir("..")
    df = fetch_data("SPY")
    bt = Backtester(df)

    print("Standard SMA Crossover:")
    print(bt.run_sma_crossover())

    print("\nUpgraded SMA + RSI Filter:")
    print(bt.run_upgraded_strategy())
