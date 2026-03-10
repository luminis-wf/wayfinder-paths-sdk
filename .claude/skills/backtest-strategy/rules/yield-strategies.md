# Backtesting Yield & Lending Strategies

The engine doesn't care whether "prices" are market prices or compounded APR — build
**synthetic price indices** from rate data and the standard Sharpe/drawdown metrics apply.

## Core primitive

```python
from wayfinder_paths.core.backtesting import build_yield_index

# Convert APR rates into a cumulative price index
prices = build_yield_index(rates_df, periods_per_year=365)
# rates_df: DataFrame[timestamp × venue/symbol], values = decimal APR (0.05 = 5%)
# prices: starts at 1.0, grows with yield each period
```

## Data fetchers for lending

```python
# Per-venue supply + borrow (use for rotation / carry)
rates = await fetch_lending_rates("USDC", start, end, venues=["aave", "moonwell", "morpho"])
supply = rates["supply"]   # DataFrame[timestamp × venue]
borrow = rates["borrow"]   # DataFrame[timestamp × venue]

# Symbol-level averages (simpler queries)
avg_supply = await fetch_supply_rates(["USDC", "ETH"], start, end)
avg_borrow = await fetch_borrow_rates(["USDC"], start, end, protocol="aave")
```

## Pattern 1: Supply rate rotation → `backtest_yield_rotation()`

One-liner for rotating capital to the highest-yielding venue:

```python
result = await backtest_yield_rotation(
    "USDC", ["aave", "moonwell", "morpho"], "2025-08-01", "2026-01-01",
    lookback_signal_days=7,  # Trailing avg window; higher = fewer switches
    fee_rate=0.0005,          # Amortized gas per switch; higher on mainnet (~0.002)
)
# Check trade_count: if > 20, increase lookback_signal_days
```

Manual version (when you need custom logic):
```python
rates = await fetch_lending_rates("USDC", start, end, venues=["aave", "moonwell", "morpho"])
prices = build_yield_index(rates["supply"])
rolling_avg = rates["supply"].rolling(7, min_periods=1).mean()
best_venue = rolling_avg.idxmax(axis=1)
target = pd.DataFrame(0.0, index=prices.index, columns=prices.columns)
for v in prices.columns:
    target.loc[best_venue == v, v] = 1.0
config = BacktestConfig(fee_rate=0.0005, slippage_rate=0.0, enable_liquidation=False, periods_per_year=365)
result = run_backtest(prices, target, config)
```

## Pattern 2: Leveraged yield (collateral loop)

Bake leverage into the synthetic price — don't use `config.leverage` for this:

```python
eth_prices = await fetch_prices(["ETH"], start, end)
borrow_rates = await fetch_borrow_rates(["USDC"], start, end, protocol="aave")
eth_prices, borrow_rates = await align_dataframes(eth_prices, borrow_rates)

leverage = 2.0
strategy_returns = (
    eth_prices["ETH"].pct_change().fillna(0) * leverage
    - (borrow_rates["USDC"] / 365) * (leverage - 1)
)
strategy_price = (1 + strategy_returns).cumprod()
prices = pd.DataFrame({"ETH_LOOP": strategy_price})
target = pd.DataFrame({"ETH_LOOP": 1.0}, index=prices.index)

config = BacktestConfig(
    fee_rate=0.001, leverage=1.0, enable_liquidation=True,
    maintenance_margin_rate=0.15, periods_per_year=365,
)
result = run_backtest(prices, target, config)
print(f"Liquidated: {result.liquidated}")
```

Test multiple leverage levels by varying `leverage` in the returns formula.

## Pattern 3: Carry trade → `backtest_carry_trade()`

```python
result = await backtest_carry_trade(
    "USDC", "2025-08-01", "2026-01-01",
    venues=["aave", "moonwell", "morpho"],
    min_spread=0.01,   # Only active when spread > 1% APR
)
# exposure_time_pct shows fraction of time the spread was positive
```

## Metric interpretation

| Metric | Yield context |
|---|---|
| `sharpe` | >3.0 is achievable for stable yield |
| `max_drawdown` | Near-zero for supply-only; any drawdown = rate compression |
| `trade_count` | Keep low — each switch costs gas |
| `exposure_time_pct` | For carry: fraction of time spread was positive |

## What doesn't work for yield

- `funding_rates` config: bake borrow costs into synthetic price instead
- Negative weights: lending is always long (supply capital)
- Intraday intervals: use `periods_per_year=365` (rates change at most daily)
- Reward token APR: Delta Lab timeseries may not include incentive rewards — factor in manually
