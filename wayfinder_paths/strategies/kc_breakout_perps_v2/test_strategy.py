"""Tests for KcBreakoutPerpsV2Strategy (high-conviction variant).

Mirrors kc_breakout_perps' tests against the v2 params (kc_multiplier=2.0,
reward_factor=3.0):
  1. Class wiring (REF/SIGNAL/DECIDE, DEFAULT_PARAMS sanity).
  2. Signal invariants — long-only, leverage-bounded, correct shape.
  3. AUTHORITATIVE backtest — the event-driven engine on real HL OHLC reproduces
     the per-sleeve / portfolio ref ranges.
  4. Framework trigger plumbing — signal+decide run end-to-end through the
     close-only path without error (approximate; not the perf authority).
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

from wayfinder_paths.strategies.kc_breakout_perps_v2.signal import compute_signal
from wayfinder_paths.strategies.kc_breakout_perps_v2.strategy import (
    KcBreakoutPerpsV2Strategy,
)
from wayfinder_paths.strategies.kc_breakout_perps_v2.strategy_engine import (
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
    cls = KcBreakoutPerpsV2Strategy
    assert cls.SIGNAL.endswith(":compute_signal")
    assert cls.DECIDE.endswith(":decide")
    assert cls.REF.exists()
    p = cls.DEFAULT_PARAMS
    assert p["symbols"] == ["HYPE", "ZEC"]
    assert p["kc_multiplier"] == 2.0
    assert p["reward_factor"] == 3.0
    assert p["trend_filter"] == "ema_above_rising"
    assert p["exit_execution"] == "next_open"


@pytest.mark.smoke
def test_signal_invariants():
    prices = _multiindex_ohlc(days=80)
    sf = compute_signal(prices, None, KcBreakoutPerpsV2Strategy.DEFAULT_PARAMS)
    t = sf.targets
    assert list(t.columns) == SYMBOLS
    assert (t.values >= -1e-9).all(), "long-only: weights must be >= 0"
    max_lev = KcBreakoutPerpsV2Strategy.DEFAULT_PARAMS["max_leverage"]
    assert (t.values <= max_lev + 1e-6).all(), "weights exceed max_leverage"


@pytest.mark.smoke
def test_authoritative_backtest_reproduces_ref():
    """Run the authoritative engine on real HL OHLC; per-sleeve returns and the
    50/50 portfolio Sharpe must clear the (wide) ref ranges in examples.json."""
    from wayfinder_paths.tests.test_utils import load_strategy_examples
    ranges = load_strategy_examples(Path(__file__))["expected_backtest_ranges"]
    params = KcBreakoutPerpsV2Strategy.DEFAULT_PARAMS
    slip = {"HYPE": 0.0004, "ZEC": 0.0005}
    eqs, rets = [], {}
    for sym in SYMBOLS:
        df = asyncio.run(_fetch_ohlc(sym, days=210))
        cfg = config_from_params({**params, "slippage_bps": slip[sym] * 1e4})
        res = run(df, cfg, None, eval_start=80)
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
def test_signal_exposes_stop_distance():
    """The signal must carry extras['stop_distance']: NaN when flat, a positive
    ATR distance while in a trade — the input decide() needs to price a native stop."""
    prices = _multiindex_ohlc(days=80)
    sf = compute_signal(prices, None, KcBreakoutPerpsV2Strategy.DEFAULT_PARAMS)
    assert "stop_distance" in sf.extras, "signal must emit extras['stop_distance']"
    sd = sf.extras["stop_distance"]
    assert list(sd.columns) == SYMBOLS
    for sym in SYMBOLS:
        in_trade = sf.targets[sym] > 0
        # while in a trade, stop distance must be a positive finite number
        assert (sd[sym][in_trade] > 0).all(), f"{sym}: stop_distance must be >0 in-trade"
        # while flat, stop distance must be NaN (no stop to place)
        assert sd[sym][~in_trade].isna().all(), f"{sym}: stop_distance must be NaN when flat"


# --- native stop-loss reconciliation (live execution path) -------------------

class _FakeAdapter:
    def __init__(self):
        self.coin_to_asset = {"HYPE": 1}
        self.asset_to_sz_decimals = {1: 2}
        self.trigger_calls: list[dict] = []

    async def place_trigger_order(self, **kw):
        self.trigger_calls.append(kw)
        return True, {"response": {"data": {"statuses": [{"resting": {"oid": 4242}}]}}}


class _FakeHandler:
    def __init__(self, adapter):
        self.adapter = adapter
        self.wallet_address = "0xfeed"
        self.cancels: list = []

    async def cancel(self, oid):
        self.cancels.append(oid)
        return True


class _FakeState:
    def __init__(self):
        self._d = {}

    def get(self, k, default=None):
        return self._d.get(k, default)

    def set(self, k, v):
        self._d[k] = v


def _ctx(handler, params, t, stop_d):
    from types import SimpleNamespace

    from wayfinder_paths.core.perps.context import SignalFrame
    idx = pd.DatetimeIndex([pd.Timestamp(t)])
    sd = pd.DataFrame({"HYPE": [stop_d]}, index=idx)
    sig = SignalFrame(targets=pd.DataFrame({"HYPE": [1.0]}, index=idx),
                      extras={"stop_distance": sd})
    return SimpleNamespace(perp=handler, params=params, state=_FakeState(),
                           signal=sig, t=t)


def test_reconcile_places_reduce_only_stop_loss():
    """An open long → exactly one reduce-only SELL stop-loss trigger at entry-d."""
    from wayfinder_paths.core.perps.handlers.protocol import Position
    from wayfinder_paths.strategies.kc_breakout_perps_v2.decide import (
        _reconcile_native_stops,
    )
    adapter = _FakeAdapter()
    handler = _FakeHandler(adapter)
    t = datetime(2026, 6, 1, tzinfo=UTC)
    params = {"symbols": ["HYPE"], "native_stop_orders": True, "reward_factor": 3.0}
    ctx = _ctx(handler, params, t, stop_d=4.0)
    pos = Position(symbol="HYPE", size=10.0, entry_price=100.0,
                   mark_price=100.0, notional=1000.0)
    asyncio.run(_reconcile_native_stops(ctx, {"HYPE": pos}, entered={}))

    assert len(adapter.trigger_calls) == 1, "exactly one SL trigger expected"
    call = adapter.trigger_calls[0]
    assert call["tpsl"] == "sl"
    assert call["is_buy"] is False, "long stop-loss is a SELL trigger"
    assert call["reduce_only"] is True
    assert abs(call["trigger_price"] - 96.0) < 1e-6, "stop = entry(100) - d(4)"
    assert abs(call["size"] - 10.0) < 1e-6
    assert ctx.state.get("native_stops")["HYPE"]["sl_oid"] == "4242"


def test_reconcile_cancels_stop_when_flat():
    """Position closed → previously-placed stop is cancelled and untracked."""
    from wayfinder_paths.strategies.kc_breakout_perps_v2.decide import (
        _reconcile_native_stops,
    )
    adapter = _FakeAdapter()
    handler = _FakeHandler(adapter)
    t = datetime(2026, 6, 1, tzinfo=UTC)
    params = {"symbols": ["HYPE"], "native_stop_orders": True}
    ctx = _ctx(handler, params, t, stop_d=float("nan"))  # flat → NaN distance
    ctx.state.set("native_stops", {"HYPE": {"entry": 100.0, "stop": 96.0,
                                            "size": 10.0, "sl_oid": "4242"}})
    asyncio.run(_reconcile_native_stops(ctx, {}, entered={}))

    assert handler.cancels == ["4242"], "stale stop must be cancelled when flat"
    assert "HYPE" not in ctx.state.get("native_stops")
    assert adapter.trigger_calls == []


def test_reconcile_noop_without_adapter():
    """Backtest / non-HL venue (no .adapter) → reconciliation is a safe no-op."""
    from wayfinder_paths.core.perps.handlers.protocol import Position
    from wayfinder_paths.strategies.kc_breakout_perps_v2.decide import (
        _reconcile_native_stops,
    )

    class _NoAdapter:
        pass

    t = datetime(2026, 6, 1, tzinfo=UTC)
    ctx = _ctx(_NoAdapter(), {"symbols": ["HYPE"], "native_stop_orders": True}, t, 4.0)
    pos = Position(symbol="HYPE", size=10.0, entry_price=100.0,
                   mark_price=100.0, notional=1000.0)
    # must not raise
    asyncio.run(_reconcile_native_stops(ctx, {"HYPE": pos}, entered={}))


@pytest.mark.smoke
@pytest.mark.skipif(
    not (REPO_ROOT / "config.json").exists() or os.getenv("GITHUB_ACTIONS") == "true",
    reason="network-bound trigger plumbing check",
)
def test_trigger_plumbing_runs():
    from wayfinder_paths.core.strategies.active_perps_testing import (
        assert_active_perps_backtest_runs,
    )
    ohlc = _multiindex_ohlc(days=KcBreakoutPerpsV2Strategy.SMOKE_TEST_WINDOW_DAYS)
    closes = pd.concat({s: ohlc[s]["close"] for s in SYMBOLS}, axis=1)
    asyncio.run(assert_active_perps_backtest_runs(
        KcBreakoutPerpsV2Strategy, closes, expect_trades=False))
