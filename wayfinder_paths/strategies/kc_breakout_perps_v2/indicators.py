"""1:1 reimplementation of the Mangrove KB indicators used by this strategy.

Transcribed from MangroveKnowledgeBase/mangrove_kb/indicators/{volatility_indicators,utils}.py
and signals/volatility.py. Validated numerically against the originals in
validate_indicators.py. Price-only (no volume) — matches kc/atr/ulcer needs.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    # np.fmax ignores NaN, so at index 0 (prev_close NaN) tr falls back to tr1.
    tr = np.fmax(tr1, np.fmax(tr2, tr3))
    return pd.Series(tr, index=close.index)


def atr_wilder(high: pd.Series, low: pd.Series, close: pd.Series, window: int) -> pd.Series:
    """Wilder RMA of true range. Warm-up bars [0, window-2] are exactly 0.0,
    atr[window-1] = mean(first `window` TRs), then EMA(alpha=1/window, adjust=False)."""
    tr_arr = true_range(high, low, close).to_numpy(dtype=float)
    n = len(tr_arr)
    atr_arr = np.zeros(n)
    if n >= window:
        seed = np.nanmean(tr_arr[:window])
        tail = np.concatenate(([seed], tr_arr[window:]))
        smoothed = pd.Series(tail).ewm(alpha=1.0 / window, adjust=False).mean().to_numpy()
        atr_arr[window - 1:] = smoothed
    return pd.Series(atr_arr, index=close.index)


def keltner_channel(
    high: pd.Series, low: pd.Series, close: pd.Series,
    window: int = 20, window_atr: int = 10, multiplier: float = 2.0,
    original_version: bool = False,
) -> dict[str, pd.Series]:
    """Returns {'mband','hband','lband'}. original_version=False is the EMA+ATR
    standard Keltner; True is the SMA-of-typical-price-triplets form (no ATR)."""
    if not original_version:
        tp = close.ewm(span=window, min_periods=window, adjust=False).mean()
        atr = atr_wilder(high, low, close, window_atr)
        hband = tp + multiplier * atr
        lband = tp - multiplier * atr
    else:
        typical = (high + low + close) / 3.0
        tp = typical.rolling(window, min_periods=window).mean()
        hband = (((4 * high) - (2 * low) + close) / 3.0).rolling(window, min_periods=window).mean()
        lband = (((-2 * high) + (4 * low) + close) / 3.0).rolling(window, min_periods=window).mean()
    return {"mband": tp, "hband": hband, "lband": lband}


def ulcer_index(close: pd.Series, window: int = 14) -> pd.Series:
    ui_max = close.rolling(window, min_periods=1).max()
    r = 100.0 * (close - ui_max) / ui_max
    return np.sqrt((r ** 2).rolling(window, min_periods=window).mean())


# --- vectorized signal columns (per-bar booleans) -------------------------

def kc_upper_breakout_series(
    high: pd.Series, low: pd.Series, close: pd.Series,
    window: int = 20, window_atr: int = 10, multiplier: float = 2.0,
    original_version: bool = False,
) -> pd.Series:
    """Cross above upper band: prev_close <= prev_upper AND close > upper."""
    kc = keltner_channel(high, low, close, window, window_atr, multiplier, original_version)
    upper = kc["hband"]
    cond = (close.shift(1) <= upper.shift(1)) & (close > upper)
    return cond.fillna(False)


def kc_lower_breakout_series(
    high: pd.Series, low: pd.Series, close: pd.Series,
    window: int = 20, window_atr: int = 10, multiplier: float = 2.0,
    original_version: bool = False,
) -> pd.Series:
    """Cross below lower band: prev_close >= prev_lower AND close < lower."""
    kc = keltner_channel(high, low, close, window, window_atr, multiplier, original_version)
    lower = kc["lband"]
    cond = (close.shift(1) >= lower.shift(1)) & (close < lower)
    return cond.fillna(False)


def ulcer_low_risk_series(close: pd.Series, window: int = 14, threshold: float = 5.0) -> pd.Series:
    ui = ulcer_index(close, window)
    return (ui < threshold).fillna(False)
