"""Tests for KcBreakoutPerpsStrategy.

Coverage:
  1. Class wiring (REF/SIGNAL/DECIDE, DEFAULT_PARAMS sanity).
  2. Signal invariants — long-only, leverage-bounded, correct shape, on a
     MultiIndex OHLC frame (the live input contract).
  3. AUTHORITATIVE backtest — the event-driven engine (true ATR + next-open
     fills) on real HL OHLC reproduces the per-sleeve / portfolio ref ranges.
  4. Framework trigger plumbing — signal+decide run end-to-end through the
     close-only backtest path without error (approximate; not the perf authority).
"""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import numpy as np
import pandas as pd
import pytest

from wayfinder_paths.strategies.kc_breakout_perps.signal import compute_signal
from wayfinder_paths.strategies.kc_breakout_perps.strategy import KcBreakoutPerpsStrategy
from wayfinder_paths.strategies.kc_breakout_perps.strategy_engine import (
    config_from_params, run,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
SYMBOLS = ["HYPE", "ZEC"]


async def _fetch_ohlc(sym: str, days: int) -> pd.DataFrame:
    now = datetime.now(UTC)
    start_ms = int((now - timedelta(days=days)).timestamp() * 1000)
    end_ms = int((now + timedelta(hours=1)).timestamp() * 1000)
    async with httpx.AsyncClient(timeout=30.0) as c:
        r = await c.post("https://api.hyperliquid.xyz/info", json={
            "type": "candleSnapshot",
            "req": {"coin": sym, "interval": "1h", "startTime": start_ms, "endTime": end_ms}})
        r.raise_for_status()
        df = pd.DataFrame(r.json())
    df["t"] = pd.to_datetime(df["t"], unit="ms", utc=True)
    df = df.set_index("t").sort_index()
    return pd.DataFrame({"open": df["o"].astype(float), "high": df["h"].astype(float),
                         "low": df["l"].astype(float), "close": df["c"].astype(float)})


def _multiindex_ohlc(days: int) -> pd.DataFrame:
    frames = {s: asyncio.run(_fetch_ohlc(s, days)) for s in SYMBOLS}
    return pd.concat(frames, axis=1).dropna()


@pytest.mark.smoke
def test_class_wires():
    cls = KcBreakoutPerpsStrategy
    assert cls.SIGNAL.endswith(":compute_signal")
    assert cls.DECIDE.endswith(":decide")
    assert cls.REF.exists()
    p = cls.DEFAULT_PARAMS
    assert p["symbols"] == ["HYPE", "ZEC"]
    assert p["kc_multiplier"] == 1.7536
    assert p["trend_filter"] == "ema_above_rising"
    assert p["exit_execution"] == "next_open"


@pytest.mark.smoke
def test_signal_invariants():
    prices = _multiindex_ohlc(days=80)
    sf = compute_signal(prices, None, KcBreakoutPerpsStrategy.DEFAULT_PARAMS)
    t = sf.targets
    assert list(t.columns) == SYMBOLS
    assert (t.values >= -1e-9).all(), "long-only: weights must be >= 0"
    max_lev = KcBreakoutPerpsStrategy.DEFAULT_PARAMS["max_leverage"]
    assert (t.values <= max_lev + 1e-6).all(), "weights exceed max_leverage"


@pytest.mark.smoke
def test_authoritative_backtest_reproduces_ref():
    """Run the authoritative engine on real HL OHLC; per-sleeve returns and the
    50/50 portfolio Sharpe must clear the (wide) ref ranges in examples.json."""
    from wayfinder_paths.tests.test_utils import load_strategy_examples
    ranges = load_strategy_examples(Path(__file__))["expected_backtest_ranges"]
    params = KcBreakoutPerpsStrategy.DEFAULT_PARAMS
    slip = {"HYPE": 0.0004, "ZEC": 0.0005}
    eqs, rets = [], {}
    for sym in SYMBOLS:
        df = asyncio.run(_fetch_ohlc(sym, days=210))
        cfg = config_from_params({**params, "slippage_bps": slip[sym] * 1e4})
        res = run(df, cfg, None, eval_start=80)  # funding negligible (±<0.1%)
        rets[sym] = res.stats["total_return_pct"] / 100.0
        eqs.append((res.equity / res.equity.iloc[0]).rename(sym))
    assert rets["HYPE"] >= ranges["hype_total_return_min"], rets
    assert rets["ZEC"] >= ranges["zec_total_return_min"], rets
    combined = pd.concat(eqs, axis=1).ffill().dropna()
    port = 0.5 * combined["HYPE"] + 0.5 * combined["ZEC"]
    pr = port.pct_change().dropna()
    sharpe = float(pr.mean() / pr.std() * np.sqrt(8760))
    assert sharpe >= ranges["portfolio_sharpe_min"], f"portfolio sharpe {sharpe:.2f}"


@pytest.mark.smoke
@pytest.mark.skipif(
    not (REPO_ROOT / "config.json").exists() or os.getenv("GITHUB_ACTIONS") == "true",
    reason="network-bound trigger plumbing check",
)
def test_trigger_plumbing_runs():
    """signal+decide execute end-to-end through the framework's close-only
    backtest path (approximate). Confirms no divergence/plumbing errors."""
    from wayfinder_paths.core.strategies.active_perps_testing import (
        assert_active_perps_backtest_runs,
    )
    ohlc = _multiindex_ohlc(days=KcBreakoutPerpsStrategy.SMOKE_TEST_WINDOW_DAYS)
    closes = pd.concat({s: ohlc[s]["close"] for s in SYMBOLS}, axis=1)  # framework: close-only
    asyncio.run(assert_active_perps_backtest_runs(
        KcBreakoutPerpsStrategy, closes, expect_trades=False))
