"""Signal: Keltner-breakout + Ulcer filter + EMA trend gate (long-only).

Per symbol, runs the event-driven state machine (breakout entry, Ulcer-Index
risk filter, EMA-trend regime gate, ATR stop/TP exits, cooldown, max-hold) over
the OHLC history and emits a per-bar TARGET LEVERAGE series: the risk-based
leverage while in a trade (held constant), 0 when flat. decide() multiplies by
live NAV to get the target position size.

It also emits `extras["stop_distance"]`: the per-bar ATR stop distance
(d = ATR*atr_volatility_factor) of the active trade, NaN when flat. decide()
uses this with the live fill price to place a native reduce-only stop-loss
trigger on the venue (stop = entry - d for a long).

Input contract for `prices`:
  - LIVE (preferred): MultiIndex columns (symbol, {open,high,low,close}). The
    strategy's `_fetch_recent_data` override supplies this so true ATR (high/low)
    and intrabar stop detection are available.
  - Framework close-only backtest: flat columns (one close per symbol). We build
    a degenerate OHLC (high=low=open=close) so the trigger path still runs — but
    ATR degrades to a close-to-close proxy and stops become close-based. This
    path is NOT the performance authority; see strategy_engine.py / tests.
"""

from __future__ import annotations

import pandas as pd

from wayfinder_paths.core.perps.context import SignalFrame

from .strategy_engine import config_from_params, run


def _symbol_ohlc(prices: pd.DataFrame, sym: str) -> pd.DataFrame | None:
    if isinstance(prices.columns, pd.MultiIndex):
        if sym not in prices.columns.get_level_values(0):
            return None
        sub = prices[sym]
        need = {"open", "high", "low", "close"}
        if not need.issubset(sub.columns):
            return None
        return sub[["open", "high", "low", "close"]].astype(float)
    if sym not in prices.columns:
        return None
    c = prices[sym].astype(float)
    return pd.DataFrame({"open": c, "high": c, "low": c, "close": c})


def compute_signal(
    prices: pd.DataFrame,
    funding: pd.DataFrame | None,
    params: dict,
) -> SignalFrame:
    symbols = list(params.get("symbols", []))
    cfg = config_from_params(params)
    cols: dict[str, pd.Series] = {}
    sd_cols: dict[str, pd.Series] = {}
    for sym in symbols:
        ohlc = _symbol_ohlc(prices, sym)
        if ohlc is None or len(ohlc) <= max(cfg.kc_window_atr, cfg.ulcer_window) + 2:
            cols[sym] = pd.Series(0.0, index=prices.index)
            sd_cols[sym] = pd.Series(float("nan"), index=prices.index)
            continue
        res = run(ohlc, cfg)
        cols[sym] = res.weights.reindex(prices.index).fillna(0.0)
        # stop distance: reindex but DO NOT fill NaN (NaN means flat -> no stop)
        sd_cols[sym] = res.stop_distance.reindex(prices.index)
    targets = pd.DataFrame(cols, index=prices.index).reindex(columns=symbols).fillna(0.0)
    stop_distance = pd.DataFrame(sd_cols, index=prices.index).reindex(columns=symbols)
    return SignalFrame(targets=targets, extras={"stop_distance": stop_distance})
