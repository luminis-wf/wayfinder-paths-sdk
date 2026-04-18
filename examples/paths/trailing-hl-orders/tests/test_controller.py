from __future__ import annotations

import pytest
from controller import (
    Action,
    ControllerDecision,
    TrailingConfig,
    TrailingState,
    step,
)


def _run(cfg: TrailingConfig, series: list[float]) -> list[ControllerDecision]:
    decisions: list[ControllerDecision] = []
    state = TrailingState()
    for mid in series:
        decision = step(cfg, state, mid)
        decisions.append(decision)
        state = decision.next_state
    return decisions


# --- trailing_sl long -------------------------------------------------------


def test_trailing_sl_long_initializes_then_ratchets_then_fires() -> None:
    cfg = TrailingConfig(coin="HYPE", side="long", kind="trailing_sl", offset_pct=0.05)
    decisions = _run(cfg, [100.0, 105.0, 103.0, 110.0, 104.0])
    assert [d.action for d in decisions] == [
        Action.INITIALIZE,  # peak=100, trigger=95
        Action.UPDATE_TRAIL,  # peak=105, trigger=99.75
        Action.HOLD,  # peak stays 105, mid 103 above trigger 99.75
        Action.UPDATE_TRAIL,  # peak=110, trigger=104.5
        Action.FIRE_CLOSE,  # mid 104 <= 104.5
    ]
    assert decisions[-1].trigger_price == pytest.approx(104.5)
    assert decisions[-1].next_state.fired is True


def test_trailing_sl_long_does_not_ratchet_down() -> None:
    cfg = TrailingConfig(coin="BTC", side="long", kind="trailing_sl", offset_pct=0.1)
    decisions = _run(cfg, [100.0, 90.0, 85.0])  # adverse-only sequence
    # Initialize at 100, trigger=90. Next tick mid=90 crosses exactly.
    assert decisions[0].action == Action.INITIALIZE
    assert decisions[1].action == Action.FIRE_CLOSE
    assert decisions[2].action == Action.HOLD  # terminal
    # Peak never moved down.
    assert decisions[1].next_state.peak == 100.0


# --- trailing_sl short ------------------------------------------------------


def test_trailing_sl_short_initializes_then_ratchets_then_fires() -> None:
    cfg = TrailingConfig(coin="ETH", side="short", kind="trailing_sl", offset_pct=0.05)
    decisions = _run(cfg, [100.0, 95.0, 97.0, 90.0, 94.6])
    assert [d.action for d in decisions] == [
        Action.INITIALIZE,  # peak=100, trigger=105
        Action.UPDATE_TRAIL,  # peak=95, trigger=99.75
        Action.HOLD,  # mid 97 below trigger 99.75
        Action.UPDATE_TRAIL,  # peak=90, trigger=94.5
        Action.FIRE_CLOSE,  # mid 94.6 >= 94.5
    ]


# --- trailing_tp without activation ----------------------------------------


def test_trailing_tp_long_without_activation_is_symmetric_to_sl() -> None:
    # Same shape as trailing_sl but semantically a TP (fires on pullback from favorable extreme).
    cfg = TrailingConfig(coin="HYPE", side="long", kind="trailing_tp", offset_pct=0.03)
    decisions = _run(cfg, [50.0, 52.0, 55.0, 53.3])
    assert [d.action for d in decisions] == [
        Action.INITIALIZE,  # peak=50, trigger=48.5
        Action.UPDATE_TRAIL,  # peak=52, trigger=50.44
        Action.UPDATE_TRAIL,  # peak=55, trigger=53.35
        Action.FIRE_CLOSE,  # mid 53.3 <= 53.35
    ]


# --- trailing_tp with activation -------------------------------------------


def test_trailing_tp_long_with_activation_waits_then_trails() -> None:
    cfg = TrailingConfig(
        coin="HYPE",
        side="long",
        kind="trailing_tp",
        offset_pct=0.02,
        activation_pct=0.05,
    )
    decisions = _run(cfg, [100.0, 102.0, 104.9, 105.0, 107.0, 104.85])
    assert decisions[0].action == Action.INITIALIZE  # reference=100, no peak yet
    assert decisions[0].next_state.reference_price == 100.0
    assert decisions[0].next_state.activated is False
    assert decisions[1].action == Action.HOLD  # moved 2%, below 5% activation
    assert decisions[2].action == Action.HOLD  # moved 4.9%, still below
    assert decisions[3].action == Action.INITIALIZE  # activates at 105 (moved 5.0%)
    assert decisions[3].next_state.activated is True
    assert decisions[3].next_state.peak == 105.0
    assert decisions[3].trigger_price == pytest.approx(102.9)
    assert decisions[4].action == Action.UPDATE_TRAIL  # peak=107, trigger=104.86
    assert decisions[4].trigger_price == pytest.approx(107 * 0.98)
    assert decisions[5].action == Action.FIRE_CLOSE  # 104.85 <= 104.86


def test_trailing_tp_short_with_activation() -> None:
    cfg = TrailingConfig(
        coin="BTC",
        side="short",
        kind="trailing_tp",
        offset_pct=0.01,
        activation_pct=0.03,
    )
    # Reference 100, needs to drop to 97 (3%), then trail 1% up from trough.
    decisions = _run(cfg, [100.0, 99.0, 96.8, 95.0, 95.96])
    assert decisions[0].action == Action.INITIALIZE
    assert decisions[1].action == Action.HOLD
    assert decisions[2].action == Action.INITIALIZE  # activated at 96.8 (3.2% move)
    assert decisions[2].next_state.activated is True
    assert decisions[3].action == Action.UPDATE_TRAIL  # trough=95, trigger=95.95
    assert decisions[4].action == Action.FIRE_CLOSE  # 95.96 >= 95.95


# --- trailing_entry ---------------------------------------------------------


def test_trailing_entry_long_waits_for_reversal() -> None:
    cfg = TrailingConfig(
        coin="HYPE", side="long", kind="trailing_entry", offset_pct=0.02
    )
    # Track the trough; fire once price reverses 2% up from the lowest seen.
    decisions = _run(cfg, [100.0, 95.0, 93.0, 94.86, 94.87])
    assert decisions[0].action == Action.INITIALIZE  # trough=100, trigger=102
    assert decisions[1].action == Action.UPDATE_TRAIL  # trough=95, trigger=96.9
    assert decisions[2].action == Action.UPDATE_TRAIL  # trough=93, trigger=94.86
    assert decisions[3].action == Action.FIRE_ENTRY  # 94.86 >= 94.86
    assert decisions[3].next_state.fired is True


def test_trailing_entry_short_waits_for_reversal() -> None:
    cfg = TrailingConfig(
        coin="BTC", side="short", kind="trailing_entry", offset_pct=0.02
    )
    # Track the peak; fire once price reverses 2% down from the highest seen.
    decisions = _run(cfg, [100.0, 105.0, 108.0, 105.84])
    assert decisions[0].action == Action.INITIALIZE  # peak=100, trigger=98
    assert decisions[1].action == Action.UPDATE_TRAIL  # peak=105, trigger=102.9
    assert decisions[2].action == Action.UPDATE_TRAIL  # peak=108, trigger=105.84
    assert decisions[3].action == Action.FIRE_ENTRY  # 105.84 <= 105.84


# --- OCO + terminal states --------------------------------------------------


def test_peer_fired_cancels() -> None:
    cfg = TrailingConfig(coin="HYPE", side="long", kind="trailing_sl", offset_pct=0.05)
    state = TrailingState(peak=100.0, last_trigger_price=95.0)
    decision = step(cfg, state, 100.5, peer_fired=True)
    assert decision.action == Action.CANCEL
    assert decision.next_state.cancelled is True


def test_terminal_state_is_sticky() -> None:
    cfg = TrailingConfig(coin="HYPE", side="long", kind="trailing_sl", offset_pct=0.05)
    fired = TrailingState(peak=100.0, last_trigger_price=95.0, fired=True)
    cancelled = TrailingState(peak=100.0, last_trigger_price=95.0, cancelled=True)
    assert step(cfg, fired, 50.0).action == Action.HOLD
    assert step(cfg, cancelled, 200.0).action == Action.HOLD


def test_hold_when_peak_unchanged_and_untriggered() -> None:
    cfg = TrailingConfig(coin="HYPE", side="long", kind="trailing_sl", offset_pct=0.05)
    state = TrailingState(peak=100.0, last_trigger_price=95.0)
    decision = step(cfg, state, 99.5)
    assert decision.action == Action.HOLD
    assert decision.next_state == state
