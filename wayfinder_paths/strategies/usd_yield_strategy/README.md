# UsdYieldStrategy

Automated USD stablecoin yield farming on Base. Forked from `StablecoinYieldStrategy` with an additional symbol-level filter that restricts pool selection to USD-denominated stablecoins only, avoiding FX losses from EUR/GBP/other-currency pools.

- **Module**: `wayfinder_paths.strategies.usd_yield_strategy.strategy.UsdYieldStrategy`
- **Chain**: Base (8453)
- **Token**: USDC (usd-coin-base)

## Key Difference from Stablecoin Yield Strategy

The original `StablecoinYieldStrategy` uses DefiLlama's `stablecoin: true` flag to filter pools, which includes non-USD stablecoins (e.g., agEUR-USDC). This strategy adds `is_usd_pool_symbol()` filtering in `_find_best_pool()` so that only pools where every constituent token is a USD stablecoin are considered.

## Adapters Used

- **BALANCE** — wallet reads and transfers
- **LEDGER** — transaction recording
- **TOKEN** — token metadata and pricing
- **POOL** — pool discovery and analytics
- **BRAP** — cross-chain quotes and swaps

## Testing

```bash
poetry run pytest wayfinder_paths/strategies/usd_yield_strategy/ -v
```
