"""KC-Breakout Perps Strategy (Hyperliquid, long-only).

Keltner-Channel upper-band breakout (EMA10 ± 1.7536·ATR27) gated by a low-Ulcer
risk filter (UI39 < 6.1425) and an EMA-100-rising trend regime filter, with
ATR(14)×2.0 stop-loss and 2.59× reward take-profit, risk-based sizing (3.97%
risk/trade, ≤5x leverage), 24h cooldown, 1000-bar max hold. Long-only on
HYPE + ZEC.

Indicators reproduce the Mangrove KB definitions 1:1 (validated numerically).
The authoritative backtest is the event-driven engine in `strategy_engine.py`
(true ATR from high/low + next-bar-open stop/TP fills); the framework's
close-only target-weight backtest is an approximation, not the performance
authority — see README.md and test_strategy.py.

Backtest (208d HL data, fee 9.5bps [HL taker 4.5 + Wayfinder builder 5.0] +
per-token slippage, next-open exits, with funding):
    HYPE  +59.7%  Sharpe 2.20  maxDD -15.8%  (21 trades)
    ZEC   +71.7%  Sharpe 2.16  maxDD -15.7%  (22 trades)
"""

import time
from pathlib import Path
from typing import Any

import pandas as pd

from wayfinder_paths.core.clients.HyperliquidDataClient import HYPERLIQUID_DATA_CLIENT
from wayfinder_paths.core.perps.handlers.protocol import MarketHandler
from wayfinder_paths.core.strategies.active_perps import ActivePerpsStrategy


class KcBreakoutPerpsStrategy(ActivePerpsStrategy):
    # Wallet label (created by scripts/create_strategy.py) + StateStore dir.
    name = "kc_breakout_perps"

    REF = Path(__file__).parent / "backtest_ref.json"
    SIGNAL = "wayfinder_paths.strategies.kc_breakout_perps.signal:compute_signal"
    DECIDE = "wayfinder_paths.strategies.kc_breakout_perps.decide:decide"
    HIP3_DEXES = []

    # Close-only framework smoke window. Lenient floor: the framework trigger
    # backtest runs the signal's close-only fallback path (no high/low), which
    # approximates — it is a plumbing/regression check, not the perf authority.
    SMOKE_TEST_WINDOW_DAYS = 60
    SMOKE_MIN_TOTAL_RETURN = -0.50

    DEFAULT_PARAMS = {
        "symbols": ["HYPE", "ZEC"],
        # entry: Keltner upper-band breakout
        "kc_window": 10,
        "kc_window_atr": 27,
        "kc_multiplier": 1.7536,
        # filter: Ulcer-Index low-risk gate
        "ulcer_window": 39,
        "ulcer_threshold": 6.1425,
        # regime: EMA trend gate (only long when close > EMA and EMA rising)
        "trend_filter": "ema_above_rising",
        "trend_window": 100,
        "trend_slope_lookback": 24,
        # execution: dynamic ATR stop/TP + risk sizing
        "atr_period": 14,
        "atr_volatility_factor": 2.0,
        "reward_factor": 2.59,
        "max_risk_per_trade": 0.0397,
        "cooldown_bars": 24,
        "max_hold_bars": 1000,
        "exit_execution": "next_open",
        "max_leverage": 5.0,
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
