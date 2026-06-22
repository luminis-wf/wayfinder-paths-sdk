# KC-Breakout Perps v2 (high-conviction)

Long-only Keltner-Channel breakout momentum on Hyperliquid perps (**HYPE + ZEC**) —
the **tuned successor to `kc_breakout_perps`**.

- **Module**: `wayfinder_paths.strategies.kc_breakout_perps_v2.strategy.KcBreakoutPerpsV2Strategy`
- **Venue**: Hyperliquid perps · 1h bars · long-only · Universe: HYPE, ZEC

## What changed vs v1
Two validated parameter changes, kept together because the **pair** is what is robust:

| param | v1 | v2 | rationale |
|-------|----|----|-----------|
| `kc_multiplier` | 1.7536 | **2.0** | wider Keltner band → fewer, higher-conviction breakouts |
| `reward_factor` | 2.59 | **3.0** | larger take-profit multiple → let momentum winners run |

Everything else (engine, indicators, Ulcer filter, EMA-100-rising trend gate,
ATR(14)×2.0 stop, 3.97% risk sizing, 24h cooldown, next-open fills) is identical
to `kc_breakout_perps`.

## Validation (authoritative event-driven engine, HYPE+ZEC 1h)
Found and validated in `research/kc_breakout_lab` via walk-forward with a held-out
final ~30% that was **never used during the parameter search**:

| metric (50/50 portfolio) | v1 | **v2** |
|---|---|---|
| FULL Sharpe | 2.85 | **4.31** |
| FULL total return (~208d) | +65.7% | **+109.4%** |
| FULL max drawdown | −8.2% | −10.1% |
| fold-Sharpe dispersion (lower = more robust) | 1.69 | **0.45** |
| HOLDOUT Sharpe (out-of-sample) | 4.64 | **7.50** |
| per-sleeve FULL Sharpe | — | HYPE 3.55 · ZEC 3.02 (both up) |

The signal of quality isn't just the higher return — the historically hard middle
fold went from 0.23 → 2.52, and the holdout the optimizer never saw *improved*.
That is the opposite of an overfit signature, and both tokens benefit.

## Caveats / before live capital
- **`kc_multiplier=2.0` sits near a cliff** — values ≥2.05 collapse (the hard fold
  goes negative). 2.0 is the edge of a good plateau. If you want a safety margin,
  **`kc_multiplier=1.95`** is one step back (slightly higher OPT Sharpe, marginally
  worse middle-fold consistency). `reward_factor` is the safe axis (2.85/3.0/3.15
  all strong).
- **Risk sizing is a return↔DD dial, not a Sharpe lever** — `max_risk_per_trade`
  scales return and drawdown roughly together with Sharpe ~flat (0.025→+62%/−6.5%,
  0.0397→+109%/−10.1%, 0.08→+290%/−19.3%). `max_leverage` is non-binding here.
- Still a single ~208-day cycle (~20 portfolio trades). Consistent across 3 time
  folds and both tokens, but **forward/paper-validate before live capital**.

## Authoritative backtest
Same as v1: the event-driven engine in `strategy_engine.py` (true ATR from
high/low + next-bar-open stop/TP fills) is the performance authority. The
framework's close-only target-weight backtest is an approximation only.

## Usage
```bash
poetry run pytest wayfinder_paths/strategies/kc_breakout_perps_v2/ -v
```
Deploys against the wallet labelled `kc_breakout_perps_v2` in `config.json`.
