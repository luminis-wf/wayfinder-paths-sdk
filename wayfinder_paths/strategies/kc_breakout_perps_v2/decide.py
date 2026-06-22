"""Execution for the KC-breakout strategy: long-only weight → market orders,
plus NATIVE venue stop-loss protection.

The signal cell for a symbol is its TARGET LEVERAGE (notional/NAV): a positive
risk-based leverage while in a trade, 0 when flat. We convert to a target size
via NAV, pre-scale all pending legs atomically (live HL FIFO-trims margin), and
place market orders. Crossing toward flat uses reduce_only.

NATIVE STOPS (live only): the signal also emits `extras["stop_distance"]` — the
ATR stop distance `d` of the active trade. After the market orders, we place a
reduce-only stop-loss TRIGGER order on Hyperliquid at `entry - d` (and optionally
a take-profit at `entry + d*reward_factor`), so the position is protected
intrabar and survives bot downtime — instead of relying solely on the hourly
re-run to flatten. This path is adapter-guarded: in the framework's close-only
backtest (no `.adapter`), it no-ops and the authoritative engine models exits.
Controlled by params `native_stop_orders` (default True) and
`native_take_profit` (default False).
"""

from __future__ import annotations

import pandas as pd

from wayfinder_paths.adapters.hyperliquid_adapter.utils import round_size_for_asset
from wayfinder_paths.core.perps.context import TriggerContext
from wayfinder_paths.core.perps.handlers.protocol import Side
from wayfinder_paths.core.perps.sizing import (
    compute_atomic_scale,
    scale_pending_atomically,
)


def _round_size(handler, symbol: str, raw_size: float) -> float:
    adapter = getattr(handler, "adapter", None)
    if adapter is None:
        return raw_size
    asset_id = adapter.coin_to_asset.get(symbol)
    if asset_id is None:
        return raw_size
    return round_size_for_asset(adapter.asset_to_sz_decimals, asset_id, raw_size)


def _extras_at_now(ctx: TriggerContext, key: str) -> pd.Series | None:
    """Stop-distance (or other extras) row at-or-before ctx.t — same floor logic
    as SignalFrame.at(), applied to an extras DataFrame."""
    ext = ctx.signal.extras.get(key) if ctx.signal.extras else None
    if ext is None or len(ext) == 0:
        return None
    idx = ext.index
    ts = pd.Timestamp(ctx.t)
    if ts.tzinfo is not None and idx.tz is None:
        ts = ts.tz_convert(None)
    elif ts.tzinfo is None and idx.tz is not None:
        ts = ts.tz_localize(idx.tz)
    try:
        return ext.loc[ts]
    except KeyError:
        pos = idx.get_indexer([ts], method="ffill")[0]
        return ext.iloc[pos] if pos >= 0 else ext.iloc[0]


def _extract_oid(raw: dict) -> str | None:
    """Best-effort extraction of the resting order id from a HL order response."""
    try:
        for s in raw["response"]["data"]["statuses"]:
            if isinstance(s, dict):
                for k in ("resting", "filled"):
                    if isinstance(s.get(k), dict) and "oid" in s[k]:
                        return str(s[k]["oid"])
    except (KeyError, TypeError, IndexError):
        pass
    return None


async def _reconcile_native_stops(
    ctx: TriggerContext, pre_positions: dict, entered: dict
) -> None:
    """Keep a reduce-only stop-loss (and optional TP) trigger resting on the venue
    for each open long, sized to the position and priced at entry - stop_distance.
    Idempotent and self-healing: re-runs cancel+replace only when the protected
    stop/size changes, and cancel orphaned triggers once flat.

    Adapter-guarded — returns immediately in backtest / non-HL venues (the
    authoritative engine already models the ATR exits there)."""
    if not bool(ctx.params.get("native_stop_orders", True)):
        return
    adapter = getattr(ctx.perp, "adapter", None)
    address = getattr(ctx.perp, "wallet_address", None)
    if adapter is None or address is None:
        return

    sd_row = _extras_at_now(ctx, "stop_distance")
    place_tp = bool(ctx.params.get("native_take_profit", False))
    reward = float(ctx.params.get("reward_factor", 3.0))
    tracked = dict(ctx.state.get("native_stops", {}) or {})

    for sym in list(ctx.params.get("symbols", [])):
        asset_id = adapter.coin_to_asset.get(sym)
        if asset_id is None:
            continue
        pos = pre_positions.get(sym)
        size = abs(pos.size) if pos is not None else 0.0
        entry = float(pos.entry_price) if pos is not None else 0.0
        # Same-bar entry: protect the intended new position immediately, using the
        # mid as the entry proxy until the real fill price is visible next run.
        if sym in entered:
            size = abs(entered[sym]["size"])
            if entry <= 0:
                entry = float(entered[sym]["mid"])
        d = float(sd_row[sym]) if (sd_row is not None and sym in sd_row.index) else float("nan")
        rec = tracked.get(sym)
        protect = size > 0 and entry > 0 and d == d and d > 0  # d==d filters NaN

        if protect:
            stop_px = entry - d  # long-only: stop below entry
            sized = _round_size(ctx.perp, sym, size)
            if sized <= 0:
                continue
            already = (
                rec is not None
                and abs(float(rec.get("stop", 0.0)) - stop_px) < 1e-9
                and abs(float(rec.get("size", 0.0)) - sized) < 1e-12
            )
            if already:
                continue
            for oid_key in ("sl_oid", "tp_oid"):
                if rec and rec.get(oid_key):
                    try:
                        await ctx.perp.cancel(rec[oid_key])
                    except Exception:
                        pass
            new_rec: dict = {"entry": entry, "stop": stop_px, "size": sized}
            try:
                ok, raw = await adapter.place_trigger_order(
                    asset_id=asset_id, is_buy=False, trigger_price=stop_px,
                    size=sized, address=address, tpsl="sl",
                    is_market=True, reduce_only=True,
                )
                new_rec["sl_oid"] = _extract_oid(raw) if ok else None
            except Exception:
                new_rec["sl_oid"] = None
            if place_tp:
                tp_px = entry + d * reward
                try:
                    ok2, raw2 = await adapter.place_trigger_order(
                        asset_id=asset_id, is_buy=False, trigger_price=tp_px,
                        size=sized, address=address, tpsl="tp",
                        is_market=True, reduce_only=True,
                    )
                    new_rec["tp_oid"] = _extract_oid(raw2) if ok2 else None
                except Exception:
                    new_rec["tp_oid"] = None
            tracked[sym] = new_rec
        elif rec is not None:
            # Flat (or no stop info): cancel any orphaned triggers we placed.
            for oid_key in ("sl_oid", "tp_oid"):
                if rec.get(oid_key):
                    try:
                        await ctx.perp.cancel(rec[oid_key])
                    except Exception:
                        pass
            tracked.pop(sym, None)

    ctx.state.set("native_stops", tracked)


async def decide(ctx: TriggerContext) -> None:
    max_gross = float(ctx.params.get("max_gross_leverage", 5.0))
    min_order_usd = float(ctx.params.get("min_order_usd", 10.0))
    rebalance_threshold = float(ctx.params.get("rebalance_threshold", 0.05))
    cost_bps = float(ctx.params.get("fee_bps", 0.0)) + float(
        ctx.params.get("slippage_bps", 0.0)
    )

    if ctx.signal.targets.empty:
        return
    target_w = ctx.signal_at_now().clip(lower=0.0)  # long-only
    gross = float(target_w.sum())
    if gross > max_gross and gross > 0:
        target_w = target_w * (max_gross / gross)

    nav = float(ctx.nav)
    if nav <= 0:
        return
    positions = await ctx.perp.get_positions()
    current_gross = sum(
        abs(positions[s].size * ctx.perp.mid(s))
        for s in positions
        if ctx.perp.mid(s) > 0
    )
    over_leveraged = nav > 0 and (current_gross / nav) > max_gross + 1e-9

    pending: list[dict] = []
    for sym in target_w.index:
        target_weight = float(target_w[sym])
        mid = ctx.perp.mid(sym)
        if mid <= 0:
            continue
        cur_size = positions[sym].size if sym in positions else 0.0
        cur_weight = (cur_size * mid) / nav if nav > 0 else 0.0
        target_size = (target_weight * nav) / mid
        reducing = abs(target_size * mid) < abs(cur_size * mid) - 1e-12
        if abs(target_weight - cur_weight) < rebalance_threshold and not (
            over_leveraged and reducing
        ):
            continue
        pending.append(
            {"symbol": sym, "mid": mid, "current_size": cur_size, "new_size": target_size}
        )

    if pending:
        scale = compute_atomic_scale(
            pending, nav=nav, leverage=max_gross, cost_bps=cost_bps,
            current_gross_override=current_gross,
        )
        if scale < 1.0:
            for p in pending:
                p["new_size"] = p["current_size"] + (p["new_size"] - p["current_size"]) * scale

    entered: dict[str, dict] = {}
    for p in pending:
        sym, mid = p["symbol"], p["mid"]
        cur_size, target_size = p["current_size"], p["new_size"]
        diff = target_size - cur_size
        if diff == 0 or abs(diff) * mid < min_order_usd:
            continue
        order_size = _round_size(ctx.perp, sym, abs(diff))
        if order_size <= 0 or order_size * mid < min_order_usd:
            continue
        side: Side = "buy" if diff > 0 else "sell"
        reduce_only = (
            cur_size != 0 and (cur_size > 0) != (diff > 0) and order_size <= abs(cur_size)
        )
        await ctx.perp.place_order(sym, side, order_size, "market", reduce_only=reduce_only)
        # Track opening/increasing longs so the native stop can be placed the
        # same bar as entry (protecting the intended post-trade position).
        if not reduce_only and target_size > 0:
            entered[sym] = {"size": target_size, "mid": mid}

    await scale_pending_atomically(ctx, leverage=max_gross)

    # Native venue stop-loss protection (live only; no-op in backtest).
    await _reconcile_native_stops(ctx, positions, entered)
