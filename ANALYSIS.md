# Strategy Performance Analysis (10-Year Backtest)

## Performance Overview
The implemented system (SMA Crossover + RSI Filter) was evaluated across three major assets using 10 years of historical data (2014-2024).

| Asset | Buy & Hold Return | Strategy Return | B&H Sharpe | Strategy Sharpe | B&H Max Drawdown | Strategy Max DD |
|-------|-------------------|-----------------|------------|-----------------|------------------|-----------------|
| SPY   | 325.43%           | 151.44%         | 0.87       | 0.64            | -33.72%          | -33.72%         |
| QQQ   | 633.68%           | 406.73%         | 0.98       | 0.92            | -35.12%          | -28.56%         |
| BTC   | 8684.04%          | 5122.41%        | 1.01       | 1.06            | -83.40%          | -69.27%         |

### Key Findings:
1. **Risk Management**: The strategy excels at reducing drawdowns in extremely volatile assets (BTC reduced DD by ~14 percentage points).
2. **Bull Market Lag**: In steady bull markets (SPY), the trend-following nature of SMAs causes late entries and early exits, lagging behind a simple Buy & Hold.
3. **Risk-Adjusted Returns**: For BTC, the Sharpe Ratio improved from 1.01 to 1.06, indicating better returns per unit of risk.

## Ability to Trade
The "ability to trade" this strategy in the real world is **High** due to the following factors:

1. **Low Frequency**: With only 9-18 trades over 10 years, the strategy is not sensitive to high-frequency noise or slippage.
2. **Transaction Costs**: Commissions (modeled at 0.1%) have a negligible impact on the final outcome (0-80 total on a 0k account).
3. **Execution Simplicity**: The signals (Daily Close SMA crossovers) are easy to execute manually or via simple automated scripts.
4. **Capital Efficiency**: The strategy stays in cash during bearish periods, allowing capital to be deployed elsewhere or earn interest (not modeled here, which would further favor the strategy).

## Weaknesses & Upgrades
- **Whipsaws**: In sideways markets, the strategy can generate false signals.
- **Lag**: As a trend-following system, it will always miss the exact top and bottom.
- **Upgrade Path**: Integration of volatility-adjusted position sizing (e.g., Kelly Criterion) and additional macro filters could further enhance performance.
