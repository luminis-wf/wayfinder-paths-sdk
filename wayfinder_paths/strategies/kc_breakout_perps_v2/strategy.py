"""KC-Breakout Perps v2 — high-conviction variant (Hyperliquid, long-only).

Same engine as `kc_breakout_perps` (Keltner upper-band breakout, Ulcer low-risk
filter, EMA-100-rising trend gate, ATR stop/TP, risk-based sizing, long-only on
HYPE + ZEC), with two validated parameter changes that together raised
risk-adjusted return without overfitting:

    kc_multiplier : 1.7536 -> 2.0   (wider Keltner band: fewer, higher-conviction
                                     breakouts — demands a stronger push above the
                                     channel before entering)
    reward_factor : 2.59   -> 3.0   (larger take-profit multiple: lets the momentum
                                     winners run further before the TP fills)

The two reinforce each other: the combination — not either change alone — is what
produced a robust, both-token-consistent, out-of-sample-validated improvement.

How it was validated (research/kc_breakout_lab, authoritative event-driven engine,
HYPE+ZEC 1h, walk-forward with a held-out final ~30% never used in the search):

    metric (50/50 portfolio)   baseline(v1)   v2(this)
    FULL Sharpe                2.85           4.33
    FULL total return (208d)   +65.8%         +109.4%
    fold-Sharpe dispersion     1.69           0.45   (3.7x more consistent)
    HOLDOUT Sharpe             4.64           7.50   (improved out-of-sample)
    per-sleeve FULL Sharpe     -              HYPE 3.55 / ZEC 3.02 (both up)

Caveat: kc_multiplier=2.0 sits near a cliff (>=2.05 collapses); 1.95 is a more
conservative one-step-back alternative. Still a single ~208-day cycle (~20
trades) — consistent across 3 time folds and both tokens, but not a substitute
for forward/paper validation before live capital.

Authoritative backtest = the event-driven engine in strategy_engine.py (true ATR
from high/low + next-bar-open stop/TP fills); the framework's close-only
target-weight backtest is an approximation only — see README.md / test_strategy.py.
"""

import time
from pathlib import Path
from typing import Any

import pandas as pd

from wayfinder_paths.core.clients.HyperliquidDataClient import HYPERLIQUID_DATA_CLIENT
from wayfinder_paths.core.perps.handlers.protocol import MarketHandler
from wayfinder_paths.core.strategies.active_perps import ActivePerpsStrategy


class KcBreakoutPerpsV2Strategy(ActivePerpsStrategy):
    # Wallet label (created by scripts/create_strategy.py) + StateStore dir.
    name = "kc_breakout_perps_v2"

    REF = Path(__file__).parent / "backtest_ref.json"
    SIGNAL = "wayfinder_paths.strategies.kc_breakout_perps_v2.signal:compute_signal"
    DECIDE = "wayfinder_paths.strategies.kc_breakout_perps_v2.decide:decide"
    HIP3_DEXES = []

    SMOKE_TEST_WINDOW_DAYS = 60
    SMOKE_MIN_TOTAL_RETURN = -0.50

    DEFAULT_PARAMS = {
        "symbols": ["HYPE", "ZEC"],
        # entry: Keltner upper-band breakout (v2: wider band, higher conviction)
        "kc_window": 10,
        "kc_window_atr": 27,
        "kc_multiplier": 2.0,
        # filter: Ulcer-Index low-risk gate
        "ulcer_window": 39,
        "ulcer_threshold": 6.1425,
        # regime: EMA trend gate (only long when close > EMA and EMA rising)
        "trend_filter": "ema_above_rising",
        "trend_window": 100,
        "trend_slope_lookback": 24,
        # execution: dynamic ATR stop/TP + risk sizing (v2: larger reward multiple)
        "atr_period": 14,
        "atr_volatility_factor": 2.0,
        "reward_factor": 3.0,
        "max_risk_per_trade": 0.0397,
        "cooldown_bars": 24,
        "max_hold_bars": 1000,
        "exit_execution": "next_open",
        "max_leverage": 5.0,
        # native venue stop protection (live only; backtest uses the engine's
        # ATR exits). When True, decide() rests a reduce-only stop-loss trigger
        # on Hyperliquid at entry - ATR*atr_volatility_factor so the position is
        # protected intrabar and survives bot downtime. TP trigger is opt-in.
        "native_stop_orders": True,
        "native_take_profit": False,
        # portfolio / order execution
        "max_gross_leverage": 5.0,
        "rebalance_threshold": 0.05,
        "min_order_usd": 10.0,
        # costs (for backtest cost accounting; live fees come from the venue)
        "fee_bps": 9.5,
        "slippage_bps": 5.0,
        "include_funding": True,
        # live signal window: must exceed max_hold_bars so an in-flight trade's
        # entry is captured when the state machine is replayed each bar.
        "signal_lookback_bars": 1200,
    }

    # Pull OHLC (high/low needed for true ATR) and hand the signal a MultiIndex
    # (symbol, field) frame. The default base fetch returns close-only.
    async def _fetch_recent_data(self, perp: MarketHandler) -> tuple[Any, Any]:
        symbols = self._ref.data.symbols
        lookback = int(self._ref.params.get("signal_lookback_bars", 1200))
        end_ms = int(time.time() * 1000)
        start_ms = end_ms - (lookback + 48) * 3600 * 1000

        async def one(coin: str) -> pd.DataFrame:
            rows = await HYPERLIQUID_DATA_CLIENT.get_candles(coin, start_ms, end_ms, "1h")
            df = pd.DataFrame(rows)
            df["t"] = pd.to_datetime(df["t"], unit="ms", utc=True)
            df = df.set_index("t").sort_index()
            return pd.DataFrame({
                "open": df["o"].astype(float), "high": df["h"].astype(float),
                "low": df["l"].astype(float), "close": df["c"].astype(float),
            })

        frames = {s: await one(s) for s in symbols}
        prices = pd.concat(frames, axis=1).dropna()  # MultiIndex (symbol, field)
        return prices, pd.DataFrame()
