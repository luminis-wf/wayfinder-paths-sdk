---
name: virtual-delta-neutral
description: "Execute a VIRTUAL delta-neutral strategy: supply VIRTUAL on Moonwell, short VIRTUAL perp on Hyperliquid, with regime switching to USDC when spreads compress."
metadata:
  tags:
    - strategy
    - virtual
    - delta-neutral
    - moonwell
    - hyperliquid
---

# VIRTUAL Delta-Neutral Strategy

Execute a delta-neutral position: supply VIRTUAL on Moonwell (Base) + short VIRTUAL perp on Hyperliquid, switching to USDC-only when the spread compresses. The applet monitors performance in real time.

## Strategy overview

The strategy alternates between two regimes based on net yield:

- **Delta-Neutral regime**: Supply VIRTUAL on Moonwell (earn supply APR) + short VIRTUAL perp on Hyperliquid (earn positive funding). Net yield = Moonwell supply APR + annualized funding rate.
- **USDC regime**: Park funds in Moonwell USDC supply when USDC yield > delta-neutral net yield.

Anti-churn: require 6 consecutive hours of signal before switching, plus a 2-day cooldown after each switch.

## Execution flow

### 1. Assess current rates

Before entering, fetch live rates from Delta Lab to confirm the trade is attractive:

```python
from wayfinder_paths.core.clients import DELTA_LAB_CLIENT

# VIRTUAL funding + lending
data = await DELTA_LAB_CLIENT.get_basis_apy_sources(symbol="VIRTUAL", lookback_days=7, limit=20)
# Look for: Moonwell supply APR, Hyperliquid funding rate
# Delta-neutral yield = supply_apr + (funding_rate * 8760)  [funding is hourly]

# USDC lending baseline
usdc = await DELTA_LAB_CLIENT.get_basis_apy_sources(symbol="USDC", lookback_days=7, limit=20)
# Filter for Moonwell venue
```

Only proceed if delta-neutral net yield meaningfully exceeds USDC yield (spread > 2-3% annualized).

For applet presentation on prod, do not reuse the authenticated SDK route directly in the browser. Use the public timeseries endpoint on the Strategies origin:

- prod: `https://strategies.wayfinder.ai/api/v1/delta-lab/public/assets/<symbol>/timeseries/`
- dev: `https://strategies-dev.wayfinder.ai/api/v1/delta-lab/public/assets/<symbol>/timeseries/`

If the applet is embedded by the pack page, same-origin `/api/v1/delta-lab/public/assets/<symbol>/timeseries/` is acceptable. Do not probe both dev and prod from one applet build, and do not call `/api/v1/delta-lab/symbols/`.

### 2. Deposit into delta-neutral

**Step A — Acquire VIRTUAL on Base**

Swap half the deposit from USDC to VIRTUAL via MCP:

```
mcp__wayfinder__quote_swap(from_token="usd-coin-base", to_token="virtual-protocol-base", amount="<half_deposit>", wallet_label="main")
```

Confirm the quote, then execute:

```
mcp__wayfinder__execute(kind="swap", from_token="usd-coin-base", to_token="virtual-protocol-base", amount="<half_deposit>", wallet_label="main")
```

**Step B — Supply VIRTUAL on Moonwell**

Use the Moonwell adapter to supply VIRTUAL. The mToken address for VIRTUAL on Moonwell must be looked up first (check Moonwell markets via the adapter or on-chain).

```python
from wayfinder_paths.mcp.scripting import get_adapter
from wayfinder_paths.adapters.moonwell_adapter import MoonwellAdapter

adapter = get_adapter(MoonwellAdapter, "main")

# Look up the VIRTUAL mToken address from Moonwell markets
# Supply VIRTUAL (amount in wei)
ok, tx = await adapter.lend(mtoken=MVIRTUAL_ADDRESS, underlying_token=VIRTUAL_ADDRESS, amount=amount_wei)
```

**Step C — Short VIRTUAL perp on Hyperliquid**

Ensure the Hyperliquid wallet has USDC margin (deposit if needed), then open the short:

```python
from wayfinder_paths.adapters.hyperliquid_adapter import HyperliquidAdapter

hl = get_adapter(HyperliquidAdapter, "main")

# Set leverage (1x for delta-neutral)
ok, res = await hl.update_leverage(asset_id=virtual_asset_id, leverage=1, is_cross=True, address=wallet_address)

# Open short — size should match the VIRTUAL supplied on Moonwell in USD terms
ok, res = await hl.place_market_order(asset_id=virtual_asset_id, is_buy=False, slippage=0.01, size=virtual_quantity, address=wallet_address)
```

### 3. Monitor and rebalance (update)

Run the regime classifier hourly to determine whether to switch:

```bash
# If installed via pack runtime:
python scripts/wf_run.py

# Or run the classifier directly:
python scripts/classify_regime.py
```

The classifier fetches the latest rates from Delta Lab, applies the confirmation + cooldown logic against persisted state (`.state/regime.json`), and emits a signal + event with the current regime. Use `--dry-run` to inspect without persisting or emitting.

When the classifier outputs a `REGIME SWITCH`, execute the corresponding rebalance:

**Switching to USDC regime:**
- Close the Hyperliquid short (buy back, `reduce_only=True`)
- Withdraw VIRTUAL from Moonwell (`unlend`)
- Swap VIRTUAL → USDC
- Supply USDC on Moonwell

**Switching to delta-neutral regime:**
- Withdraw USDC from Moonwell
- Swap half to VIRTUAL
- Supply VIRTUAL on Moonwell
- Open VIRTUAL short on Hyperliquid

### 4. Withdraw

To exit the strategy:

1. Close any Hyperliquid perp position (`place_market_order` with `is_buy=True, reduce_only=True`)
2. Withdraw from Moonwell (`unlend` whatever is supplied)
3. Swap VIRTUAL → USDC if in delta-neutral regime
4. Transfer funds back to main wallet

## Key safety rules

- **Funding rate sign**: Positive funding = shorts receive, negative = shorts pay. Only enter delta-neutral when funding is positive.
- **Minimum Hyperliquid deposit**: $5 USD (below this is lost). Minimum order: $10 notional.
- **Quote before every swap** — verify token addresses and estimated output before executing.
- **Check gas** on Base before any on-chain operation (`wayfinder://balances/main`).
- **1x leverage only** for the short hedge — this is delta-neutral, not leveraged.
- If any step fails/reverts, stop and report — don't continue past a failed transaction.

## Protocols used

| Protocol | Chain | Purpose |
|----------|-------|---------|
| Moonwell | Base (8453) | Supply VIRTUAL or USDC for lending yield |
| Hyperliquid | Hyperliquid L1 | Short VIRTUAL perp for funding income |
| BRAP | Base | Swap between USDC and VIRTUAL |
| Delta Lab | API | Rate monitoring and regime signals |
