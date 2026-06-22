# KC-Breakout Perps Strategy

Long-only Keltner-Channel breakout momentum on Hyperliquid perps (**HYPE + ZEC**).

- **Module**: `wayfinder_paths.strategies.kc_breakout_perps.strategy.KcBreakoutPerpsStrategy`
- **Venue**: Hyperliquid perps (core markets) · 1h bars · long-only
- **Universe**: HYPE, ZEC

## Strategy logic

**Entry** (all three must hold on the closed 1h bar):
1. **Trigger — `kc_upper_breakout`**: close crosses above the upper Keltner Channel,
   `EMA(close,10) + 1.7536 × ATR(27)`.
2. **Filter — `ulcer_low_risk`**: Ulcer Index over 39 bars `< 6.1425` (calm regime).
3. **Regime — EMA trend gate**: only long when `close > EMA(close,100)` **and** EMA100
   is rising (vs 24 bars ago). This is the key addition over the raw Mangrove config —
   it keeps the strategy out of chop and made performance robust across *both* the
   trending and ranging halves of the backtest (see below).

**Exit** — no signal; pure trade management:
- **Stop** = entry − `2.0 × ATR(14)`; **take-profit** = entry + `2.59 × stop_distance`.
- A stop/TP touched intrabar is detected on the completed bar and filled at the **next
  bar's open** (realistic for an hourly live strategy). 1000-bar max hold.

**Sizing** — risk-based: `size = 3.97% × NAV / stop_distance`, capped at **5× leverage**
(actual usage ~1–3.5×). **24-bar (24h) cooldown** after each trade.

The indicators (Keltner, Wilder ATR, Ulcer Index) reproduce the Mangrove Knowledge Base
definitions **1:1** — validated numerically against the upstream implementation
(`max_abs = 0.0`).

## Backtest

208 days of Hyperliquid 1h data, **realistic cost stack**: fee **9.5 bps/side**
(HL taker 4.5 + Wayfinder builder 5.0) + per-token slippage (HYPE 4 bp, ZEC 5 bp, measured
from the live L2 book), next-open exits, with funding. 50/50 two-sleeve portfolio:

| Scope | Return | Sharpe | Max DD | Trades |
|-------|--------|--------|--------|--------|
| **Portfolio (HYPE+ZEC, 50/50)** | **+65.7%** | **2.85** | **−8.2%** | 43 |
| HYPE sleeve | +59.7% | 2.20 | −15.8% | 21 |
| ZEC sleeve | +71.7% | 2.16 | −15.7% | 22 |

Diversifying across the two sleeves roughly halves the drawdown (~16% → 8%) while keeping
the return.

### How these tokens / params were chosen
A full multi-token, walk-forward study (BTC, HYPE, ZEC, NEAR, CC, SPCX; long/short) found:
- Only **HYPE** and **ZEC** have a genuine, regime-robust edge. BTC is ~breakeven; CC, NEAR,
  SPCX do not survive.
- **Shorts** are a net drag (only ZEC short was marginally positive) → strategy is long-only.
- **Naive per-token parameter re-tuning overfits** — re-tuned params looked great in-sample and
  collapsed out-of-sample. So params are the **original Mangrove values plus the trend filter**,
  which is consistent across both tokens and mechanistically sound (don't fight the trend).

## Important: which backtest is authoritative

This strategy uses **OHLC** (true ATR needs high/low) and **intrabar ATR stop/TP exits**.
The Wayfinder framework's built-in backtest (`run_backtest` / `backtest_perps_trigger`) is
**close-only** and target-weight — it **cannot** model these faithfully.

- **Authoritative backtest** = the event-driven engine in `strategy_engine.py` (true ATR,
  next-open fills, cooldown, max-hold). `test_authoritative_backtest_reproduces_ref` runs it
  on live HL OHLC and is the performance authority; `backtest_ref.json` is generated from it.
- The framework's close-only path is exercised only by `test_trigger_plumbing_runs` as a
  signal+decide **plumbing/divergence** check (`signal.py` falls back to a close-based ATR
  approximation when given close-only input) — **not** a performance check.

## Caveats / before live capital

- Single ~208-day cycle; **no multi-fold walk-forward** yet. Recommended next step.
- `risk_limits.json` caps are conservative placeholders — recalibrate to your NAV.
- Recommended deposit ≥ ~$50 NAV so per-position notional clears the $10 HL minimum.

## Usage

```bash
# Tests
poetry run pytest wayfinder_paths/strategies/kc_breakout_perps/ -v

# Via MCP / runner (standard ActivePerpsStrategy interface)
#   actions: status | analyze | quote | deposit | update | withdraw | exit
```

Deploys against the wallet labelled `kc_breakout_perps` in `config.json`.
