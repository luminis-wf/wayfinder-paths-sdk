# Oil Macro Hedge

Bearish oil thesis via Polymarket WTI prediction markets + ETH short hedge on Hyperliquid, with automatic monthly rollovers.

## How it works

| Leg | Platform | Allocation | Action |
|-----|----------|-----------|--------|
| Oil bearish | Polymarket | 70% | Buy YES on "WTI dips to $X" |
| Macro hedge | Hyperliquid | 30% | Short ETH perp (1x leverage) |

The strategy automatically rolls Polymarket positions to the next month's WTI markets as they approach expiry.

## Quick start

```bash
# Discover available WTI markets
poetry run python scripts/oil_macro_hedge.py --action discover --month 2026-05 --strike 70

# Check status
poetry run python scripts/oil_macro_hedge.py --action status

# Deposit $100 (70/30 split)
poetry run python scripts/oil_macro_hedge.py --action deposit --amount 100 --wallet main --config ../../config.json

# Periodic update (rollover + rebalance)
poetry run python scripts/oil_macro_hedge.py --action update --wallet main --config ../../config.json

# Close everything
poetry run python scripts/oil_macro_hedge.py --action withdraw --wallet main --config ../../config.json
```

## Build & publish

```bash
poetry run wayfinder pack fmt --path .
poetry run wayfinder pack doctor --path .
poetry run wayfinder pack render-skill --path .
poetry run wayfinder pack build --path . --out dist/bundle.zip
poetry run wayfinder pack publish --path .
```
