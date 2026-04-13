# VIRTUAL Delta-Neutral Monitor

Delta-neutral strategy: Moonwell VIRTUAL supply + short perp vs USDC yield. Anti-churn with 6h confirmation and 2-day cooldown.

## What’s inside

- `wfpack.yaml` (pack manifest)
- `scripts/main.py` (main component)
- `skill/instructions.md` (canonical skill instructions, optional)
- `applet/` (static UI, optional)

## Build

```bash
wayfinder pack fmt --path .
wayfinder pack doctor --path .
wayfinder pack render-skill --path .
wayfinder pack build --path . --out dist/bundle.zip
```

## Publish

```bash
wayfinder pack publish --path . --owner-wallet 0xYourWallet
```

## Delta Lab presentation note

For the browser applet on prod, use the public Delta Lab timeseries route on the Strategies origin:

- prod: `https://strategies.wayfinder.ai/api/v1/delta-lab/public/assets/<symbol>/timeseries/`
- dev: `https://strategies-dev.wayfinder.ai/api/v1/delta-lab/public/assets/<symbol>/timeseries/`

If the applet is served by the pack page itself, same-origin `/api/v1/delta-lab/public/assets/<symbol>/timeseries/` is fine. Do not probe both dev and prod from one applet build, and do not call `/api/v1/delta-lab/symbols/`.
