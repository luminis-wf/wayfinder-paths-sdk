# Backtesting LP / AMM Strategies

Models 50/50 constant-product AMM liquidity provision by combining **impermanent loss**
and **fee income** into a synthetic price index.

## Key concept: LP P&L decomposition

```
LP position value = hold_value × (1 + IL) × cumulative_fee_multiplier

where:
- hold_value = equal-weight hold of both assets, normalized to 1.0 at start
- IL ≤ 0 always (you never outperform holding from IL alone)
- fee_multiplier = (1 + fee_rate/periods)^t, grows over time
```

LP is profitable when fees > IL. If IL dominates, you'd have been better off just holding.

## Quick start

```python
from wayfinder_paths.core.backtesting import backtest_lp_position

result = await backtest_lp_position(
    pool_assets=("ETH", "USDC"),
    start_date="2025-08-01",
    end_date="2026-01-01",
    fee_income_rate=0.25,   # 25% APY from trading fees — estimate from pool analytics
    interval="1h",
)

print(f"LP return:   {result.stats['total_return']:.2%}")
print(f"Hold return: {result.stats['buy_hold_return']:.2%}")
# If LP return > hold return: fees beat IL ✓
# If LP return < hold return: IL dominates ✗
```

## Building the synthetic price manually

```python
from wayfinder_paths.core.backtesting import (
    fetch_prices, build_lp_price_index, simulate_il, run_backtest, BacktestConfig
)

prices = await fetch_prices(["ETH", "USDC"], "2025-08-01", "2026-01-01", interval="1h")

# Inspect IL alone
il = simulate_il(prices, ("ETH", "USDC"))
print(f"Max IL: {il.min():.2%}")     # Worst point
print(f"End IL: {il.iloc[-1]:.2%}") # Current IL

# Build LP price index
lp_prices = build_lp_price_index(prices, ("ETH", "USDC"), fee_income_rate=0.25, periods_per_year=8760)

target = pd.DataFrame({"LP_ETH_USDC": 1.0}, index=lp_prices.index)
config = BacktestConfig(enable_liquidation=False, periods_per_year=8760)
result = run_backtest(lp_prices, target, config)
```

## Estimating fee_income_rate

The model requires an annualized fee APY — this cannot be fetched automatically.
Estimate it from pool analytics dashboards:

```
fee_income_rate ≈ (24h_volume × fee_tier) / TVL × 365

Example: $5M daily volume, 0.3% fee tier, $20M TVL
→ fee_income_rate = (5_000_000 × 0.003) / 20_000_000 × 365 = 0.274 (27.4% APY)
```

Typical ranges:
- Stable/stable pools (USDC/USDT): 2-10% APY
- ETH/stablecoin pools: 10-30% APY
- Volatile pairs: 20-100%+ APY (but higher IL too)

## Sensitivity analysis: break-even fee rate

Find the fee rate at which LP is profitable vs holding:

```python
from wayfinder_paths.core.backtesting import fetch_prices, simulate_il
import numpy as np

prices = await fetch_prices(["ETH", "USDC"], "2025-08-01", "2026-01-01")
il = simulate_il(prices, ("ETH", "USDC"))

# Total IL drag over the period
total_il = float(il.iloc[-1])  # e.g. -0.08 = IL cost 8% vs holding

# Time in years
n_hours = len(prices)
years = n_hours / 8760

# Break-even fee rate (annualized): must earn this much to offset IL
breakeven_fee = (-total_il) / years
print(f"IL cost: {total_il:.2%} over {years:.1f} years")
print(f"Break-even fee APY: {breakeven_fee:.2%}")
```

## Gotchas

- **fee_income_rate must be estimated** — no historical fee data in Delta Lab
- **50/50 constant-product only** — Uniswap V3 concentrated liquidity has amplified IL within range
- **Stable pairs**: ETH/USDC has significant IL during bull runs; USDC/USDT has near-zero IL
- **IL can be zero even at non-initial prices** if the price ratio returns to start
- `build_lp_price_index` does not model gas costs of entering/exiting positions
- LP positions cannot be liquidated — always use `enable_liquidation=False`
