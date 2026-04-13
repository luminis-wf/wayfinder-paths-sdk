---
name: oil-macro-hedge
description: "Operate the Oil Macro Hedge pack: deposit, update (rollover), withdraw, and monitor Polymarket oil positions + Hyperliquid ETH short hedge."
metadata:
  tags:
    - polymarket
    - hyperliquid
    - oil
    - macro
    - hedge
---

# Oil Macro Hedge

Use this skill to operate the Oil Macro Hedge pack — a two-leg strategy combining Polymarket WTI crude oil prediction markets with a Hyperliquid ETH short perp hedge.

## What this pack does

- **Polymarket leg (70%):** Buys YES on "WTI dips to $X" markets (bearish oil thesis)
- **Hyperliquid leg (30%):** Shorts ETH perp as a macro risk-off correlation hedge
- **Auto-rollover:** When Polymarket markets approach expiry (~3 days before), the strategy sells the current month and buys the next month's WTI market
- **Funding guard:** Reduces the ETH short if funding rates turn very negative for shorts
- **Rebalance:** Adjusts hedge size if allocation drifts beyond threshold

## Actions

- `deposit` — Fund the strategy: bridges USDC to Polygon (Polymarket) and Hyperliquid, opens initial positions
- `update` — Periodic check: redeems resolved markets, rolls over expiring ones, rebalances hedge
- `status` — Shows both legs: Polymarket positions (shares, cost basis, days to expiry) + HL perp (size, PnL, funding)
- `withdraw` — Closes all positions on both platforms, consolidates USDC
- `discover` — Search for available WTI oil markets on Polymarket for a given month/strike

## Running the script

```bash
python scripts/oil_macro_hedge.py --action status --wallet main
python scripts/oil_macro_hedge.py --action discover --month 2026-05 --strike 70
python scripts/oil_macro_hedge.py --action deposit --amount 100 --gas 0.01 --wallet main
python scripts/oil_macro_hedge.py --action update --wallet main
python scripts/oil_macro_hedge.py --action withdraw --wallet main
```

## Configuration

Key parameters (set via CLI args or defaults):
- `--polymarket-alloc` — Fraction to Polymarket (default 0.70)
- `--hl-alloc` — Fraction to Hyperliquid ETH short (default 0.30)
- `--strike` — WTI strike price for market discovery (e.g., 70 for "WTI dips to $70")
- `--rollover-days` — Days before expiry to trigger rollover (default 3)
- `--leverage` — ETH short leverage (default 1, max 2)

## Key gotchas

- Polymarket requires USDC.e (not native USDC) — the script bridges automatically via BRAP
- Hyperliquid minimum deposit is $5, minimum order is $10 notional
- ETH short is an imperfect hedge — oil and crypto correlate during macro regime shifts but not perfectly
- Negative funding means shorts PAY longs (bad for us) — the funding guard handles this
