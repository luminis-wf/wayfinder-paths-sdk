"""Background monitor — runner invokes this every `interval_seconds`.

For each attached trailing config, read the latest mid, step the controller,
and act on the emitted decision (update resting trigger, fire close/entry,
or hold). Resolves OCO pairs so firing one leg cancels the other.
"""

from __future__ import annotations

import asyncio
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

RUNNER_JOB_NAME = "trailing-hl-monitor"

# Make sibling modules (controller, state) importable when run as a script.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from controller import (  # noqa: E402
    Action,
    TrailingConfig,
    TrailingState,
    step,
)
from state import (  # noqa: E402
    load_configs,
    load_states,
    remove_config,
    set_state,
)


async def _build_adapter(wallet_label: str) -> Any:
    # HL signs EIP-712 typed-data (not raw transactions), so we can't use the
    # generic `get_adapter()` helper — it wires the tx-signing callback and
    # every order fails with "Transaction must include these fields". Mirror
    # the wiring used by `mcp/tools/hyperliquid.py` instead.
    from wayfinder_paths.adapters.hyperliquid_adapter.adapter import HyperliquidAdapter
    from wayfinder_paths.core.config import CONFIG
    from wayfinder_paths.core.utils.wallets import (
        get_wallet_sign_typed_data_callback,
    )

    sign_cb, address = await get_wallet_sign_typed_data_callback(wallet_label)

    strategy_raw = CONFIG.get("strategy")
    strategy_cfg = strategy_raw if isinstance(strategy_raw, dict) else {}
    adapter_config: dict[str, Any] = dict(strategy_cfg)
    adapter_config["main_wallet"] = {"address": address}
    adapter_config["strategy_wallet"] = {"address": address}

    return HyperliquidAdapter(
        config=adapter_config,
        sign_callback=sign_cb,
        wallet_address=address,
    )


async def _position_size(adapter: Any, address: str, coin: str) -> float | None:
    ok, data = await adapter.get_user_state(address)
    if not ok:
        return None
    for pos in data.get("assetPositions", []) or []:
        inner = pos.get("position", pos)
        if str(inner.get("coin")) == coin:
            try:
                return abs(float(inner.get("szi", 0.0)))
            except (TypeError, ValueError):
                return None
    return None


async def _execute_close(
    adapter: Any, cfg_payload: dict[str, Any], trigger_price: float
) -> tuple[bool, str]:
    coin = cfg_payload["coin"]
    side = cfg_payload["side"]
    mode = cfg_payload.get("mode", "resting")

    asset_id = adapter.coin_to_asset.get(coin)
    if asset_id is None:
        return False, f"Unknown coin {coin!r}"
    size = await _position_size(adapter, adapter.wallet_address, coin)
    if not size or size <= 0:
        return False, f"No open {coin} position to close"

    is_buy_to_close = side == "short"
    if mode == "monitor":
        ok, result = await adapter.place_market_order(
            asset_id=asset_id,
            is_buy=is_buy_to_close,
            slippage=0.01,
            size=size,
            address=adapter.wallet_address,
            reduce_only=True,
        )
        return ok, "market close" if ok else f"market close failed: {result}"

    # Resting mode — the trigger already exists on HL; the cross is just our
    # local confirmation. Nothing to broadcast here.
    return True, "resting trigger already armed"


async def _place_or_move_resting_trigger(
    adapter: Any,
    cfg_payload: dict[str, Any],
    new_trigger: float,
    existing_cloid: str | None,
) -> tuple[bool, str | None, str]:
    coin = cfg_payload["coin"]
    side = cfg_payload["side"]
    kind = cfg_payload["kind"]
    asset_id = adapter.coin_to_asset.get(coin)
    if asset_id is None:
        return False, existing_cloid, f"Unknown coin {coin!r}"
    size = await _position_size(adapter, adapter.wallet_address, coin)
    if not size or size <= 0:
        return False, existing_cloid, f"No open {coin} position"

    if existing_cloid:
        await adapter.cancel_order_by_cloid(
            asset_id, existing_cloid, adapter.wallet_address
        )

    tpsl = "sl" if kind == "trailing_sl" else "tp"
    is_buy_to_close = side == "short"
    ok, result = await adapter.place_trigger_order(
        asset_id=asset_id,
        is_buy=is_buy_to_close,
        trigger_price=new_trigger,
        size=size,
        address=adapter.wallet_address,
        tpsl=tpsl,
    )
    new_cloid = _extract_cloid(result) if ok else existing_cloid
    return ok, new_cloid, "ok" if ok else f"place_trigger_order failed: {result}"


def _extract_cloid(result: dict[str, Any]) -> str | None:
    try:
        statuses = result.get("response", {}).get("data", {}).get("statuses", [])
        for s in statuses:
            if isinstance(s, dict):
                resting = s.get("resting") or {}
                if cloid := resting.get("cloid"):
                    return str(cloid)
    except Exception:
        return None
    return None


def _cfg_from_payload(payload: dict[str, Any]) -> TrailingConfig:
    keys = TrailingConfig.__dataclass_fields__.keys()
    return TrailingConfig(**{k: payload[k] for k in keys if k in payload})


def _state_from_raw(raw: dict[str, Any] | None) -> TrailingState:
    if not raw:
        return TrailingState()
    keys = TrailingState.__dataclass_fields__.keys()
    return TrailingState(**{k: raw[k] for k in keys if k in raw})


async def _tick_for_wallet(
    wallet_label: str, entries: list[tuple[str, dict[str, Any]]]
) -> None:
    adapter = await _build_adapter(wallet_label)
    ok, mids = await adapter.get_all_mid_prices()
    if not ok:
        print(f"[trailing-hl] {wallet_label}: failed to fetch mids; skipping")
        return

    peer_fires: set[str] = set()
    states_raw = load_states()

    # OCO peers reference each other by position_id (e.g. "HYPE-TP-...") but
    # state/config are keyed by the full "<wallet>::<coin>::<position_id>".
    # Index up front so a fire can map peer position_id → full key.
    key_by_position_id: dict[str, str] = {
        str(payload.get("position_id")): key for key, payload in entries
    }

    # First pass — detect crossings and enqueue peer cancels.
    pending: list[tuple[str, dict[str, Any], TrailingState, Any]] = []
    for key, payload in entries:
        cfg = _cfg_from_payload(payload)
        mid = mids.get(cfg.coin)
        if mid is None:
            print(f"[trailing-hl] {key}: no mid for {cfg.coin}; skipping")
            continue
        state = _state_from_raw(states_raw.get(key))
        decision = step(cfg, state, float(mid))
        pending.append((key, payload, state, decision))
        if decision.action in (Action.FIRE_CLOSE, Action.FIRE_ENTRY) and payload.get(
            "oco_peer"
        ):
            peer_key = key_by_position_id.get(str(payload["oco_peer"]))
            if peer_key:
                peer_fires.add(peer_key)

    # Second pass — apply decisions, honoring peer-cancel signals.
    for key, payload, prior, decision in pending:
        cfg = _cfg_from_payload(payload)
        if key in peer_fires and not decision.next_state.fired:
            cancelled = step(cfg, prior, 0.0, peer_fired=True)
            set_state(key, cancelled.next_state)
            remove_config(key)
            print(f"[trailing-hl] {key}: cancelled (peer fired)")
            continue

        if decision.action == Action.HOLD:
            continue

        if decision.action in (Action.INITIALIZE, Action.UPDATE_TRAIL):
            if cfg.mode == "resting" and decision.trigger_price is not None:
                ok, new_cloid, note = await _place_or_move_resting_trigger(
                    adapter, payload, decision.trigger_price, prior.cloid
                )
                final_state = TrailingState(
                    peak=decision.next_state.peak,
                    activated=decision.next_state.activated,
                    reference_price=decision.next_state.reference_price,
                    last_trigger_price=decision.next_state.last_trigger_price,
                    cloid=new_cloid,
                    fired=decision.next_state.fired,
                    cancelled=decision.next_state.cancelled,
                )
                set_state(key, final_state)
                print(
                    f"[trailing-hl] {key}: {decision.action.value} @ {decision.trigger_price:.6g} ({note})"
                )
            else:
                set_state(key, decision.next_state)
                print(f"[trailing-hl] {key}: {decision.action.value} (monitor mode)")
            continue

        if decision.action == Action.FIRE_CLOSE:
            ok, note = await _execute_close(
                adapter, payload, decision.trigger_price or 0.0
            )
            set_state(key, decision.next_state)
            if ok:
                remove_config(key)
                print(f"[trailing-hl] {key}: FIRE_CLOSE ({note})")
            else:
                print(f"[trailing-hl] {key}: FIRE_CLOSE FAILED ({note})")
            continue

        if decision.action == Action.FIRE_ENTRY:
            # Trailing entry: fire a market order to open the position.
            asset_id = adapter.coin_to_asset.get(cfg.coin)
            size = payload.get("entry_size")
            if asset_id is None or not size:
                print(
                    f"[trailing-hl] {key}: FIRE_ENTRY skipped (missing asset_id or entry_size)"
                )
                continue
            ok, result = await adapter.place_market_order(
                asset_id=asset_id,
                is_buy=(cfg.side == "long"),
                slippage=0.01,
                size=float(size),
                address=adapter.wallet_address,
            )
            set_state(key, decision.next_state)
            if ok:
                remove_config(key)
                print(f"[trailing-hl] {key}: FIRE_ENTRY ok")
            else:
                print(f"[trailing-hl] {key}: FIRE_ENTRY FAILED ({result})")
            continue

        if decision.action == Action.CANCEL:
            set_state(key, decision.next_state)
            remove_config(key)
            print(f"[trailing-hl] {key}: cancelled")


def _schedule_runner_self_delete() -> None:
    # Self-cleanup: once every config is gone there's nothing left to monitor,
    # so the job should not keep waking every interval. attach.py re-registers
    # it the next time a position is attached.
    #
    # The runner daemon refuses to delete a job that is currently running
    # (this one), so we detach a delayed delete that fires after this process
    # exits.
    wf = shutil.which("wayfinder")
    cmd = [wf] if wf else None
    if cmd is None and (poetry := shutil.which("poetry")):
        cmd = [poetry, "run", "wayfinder"]
    if cmd is None:
        print("[trailing-hl] no configs remaining; wayfinder CLI not on PATH, leaving runner job in place")
        return
    quoted = " ".join(shlex.quote(s) for s in [*cmd, "runner", "delete", RUNNER_JOB_NAME])
    subprocess.Popen(
        ["bash", "-c", f"sleep 5 && {quoted} >/dev/null 2>&1"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
    )
    print(f"[trailing-hl] no configs remaining; scheduled runner job '{RUNNER_JOB_NAME}' for deletion")


async def main() -> None:
    configs = load_configs()
    if not configs:
        print("[trailing-hl] no active configs")
        _schedule_runner_self_delete()
        return

    by_wallet: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    for key, payload in configs.items():
        wallet = str(payload.get("wallet_label") or "main")
        by_wallet.setdefault(wallet, []).append((key, payload))

    for wallet_label, entries in by_wallet.items():
        try:
            await _tick_for_wallet(wallet_label, entries)
        except Exception as exc:
            print(f"[trailing-hl] wallet={wallet_label}: tick failed: {exc!r}")

    if not load_configs():
        _schedule_runner_self_delete()


if __name__ == "__main__":
    asyncio.run(main())
