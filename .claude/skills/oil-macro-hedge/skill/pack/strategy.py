"""Pack entry point — delegates to scripts/oil_macro_hedge.py."""

from __future__ import annotations

from typing import Any


def wfpack_meta() -> dict[str, Any]:
    return {
        "name": "Oil Macro Hedge",
        "kind": "strategy",
        "ui_mode": "auto",
        "tracking_mode": "hybrid",
    }


def wfpack_state() -> dict[str, Any]:
    return {
        "status": "idle",
        "selection": {},
        "metrics": {},
        "positions": [],
    }


def wfpack_decision() -> dict[str, Any]:
    return {
        "summary": "Bearish oil via Polymarket WTI markets + ETH short hedge on Hyperliquid.",
        "selected": {},
        "candidates": [],
    }
