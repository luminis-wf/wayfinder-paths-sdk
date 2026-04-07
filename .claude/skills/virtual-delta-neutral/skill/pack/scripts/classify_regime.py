"""Hourly regime classifier for VIRTUAL delta-neutral strategy.

Fetches latest rates from Delta Lab, runs the confirmation + cooldown
logic against persisted state, and emits a signal/event with the
current regime classification.

Run on a schedule (e.g. every hour):
    poetry run python scripts/classify_regime.py

Persists state to .state/regime.json so confirmation hours and cooldown
carry across invocations.
"""

import argparse
import asyncio
import json
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

from wayfinder_paths.core.clients.DeltaLabClient import DeltaLabClient

SLUG = "virtual-delta-neutral"
STATE_DIR = Path(__file__).parent.parent / ".state"
STATE_FILE = STATE_DIR / "regime.json"

DEFAULTS = {
    "confirm_hours": 6,
    "cooldown_hours": 48,
}


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {
        "regime": "usdc",
        "consecutive_hours": 0,
        "last_switch_at": None,
    }


def save_state(state: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, default=str))


async def fetch_latest_rates() -> dict:
    client = DeltaLabClient()

    virtual_ts = await client.get_asset_timeseries(
        symbol="VIRTUAL",
        series=["price", "funding", "lending"],
        lookback_days=1,
        limit=24,
    )
    usdc_ts = await client.get_asset_timeseries(
        symbol="USDC",
        series=["lending"],
        lookback_days=1,
        limit=24,
    )

    import pandas as pd

    # Latest price
    prices = virtual_ts.get("price", pd.DataFrame())
    if isinstance(prices, pd.DataFrame) and not prices.empty:
        price = prices.iloc[-1]["price_usd"]
    elif isinstance(prices, list) and prices:
        price = prices[-1]["price_usd"]
    else:
        price = 0

    # Latest funding (last row — oi_usd may be None)
    funding_df = virtual_ts.get("funding", pd.DataFrame())
    funding_rate = 0.0
    if isinstance(funding_df, pd.DataFrame) and not funding_df.empty:
        funding_rate = funding_df.iloc[-1]["funding_rate"]
    elif isinstance(funding_df, list) and funding_df:
        funding_rate = funding_df[-1].get("funding_rate", 0)

    # Latest Moonwell VIRTUAL supply APR
    virtual_supply_apr = 0.0
    lending_v = virtual_ts.get("lending", pd.DataFrame())
    if isinstance(lending_v, pd.DataFrame) and not lending_v.empty:
        moonwell = lending_v[lending_v["venue"].str.contains("moonwell", case=False, na=False)]
        if not moonwell.empty:
            row = moonwell.iloc[-1]
            virtual_supply_apr = row.get("supply_apr") or row.get("net_supply_apr") or 0
    elif isinstance(lending_v, list):
        for lp in reversed(lending_v):
            venue = (lp.get("venue") or "").lower()
            if "moonwell" in venue:
                virtual_supply_apr = lp.get("supply_apr") or lp.get("net_supply_apr") or 0
                break

    # Latest Moonwell USDC supply APR
    usdc_supply_apr = 0.0
    lending_u = usdc_ts.get("lending", pd.DataFrame())
    if isinstance(lending_u, pd.DataFrame) and not lending_u.empty:
        moonwell = lending_u[lending_u["venue"].str.contains("moonwell", case=False, na=False)]
        if not moonwell.empty:
            row = moonwell.iloc[-1]
            usdc_supply_apr = row.get("supply_apr") or row.get("net_supply_apr") or 0
    elif isinstance(lending_u, list):
        for lp in reversed(lending_u):
            venue = (lp.get("venue") or "").lower()
            if "moonwell" in venue:
                usdc_supply_apr = lp.get("supply_apr") or lp.get("net_supply_apr") or 0
                break

    funding_ann = funding_rate * 8760
    dn_yield = virtual_supply_apr + funding_ann
    spread = dn_yield - usdc_supply_apr

    return {
        "ts": datetime.now(UTC).isoformat(),
        "price": price,
        "funding_rate": funding_rate,
        "funding_ann": funding_ann,
        "virtual_supply_apr": virtual_supply_apr,
        "usdc_supply_apr": usdc_supply_apr,
        "dn_yield": dn_yield,
        "spread": spread,
    }


def classify(
    rates: dict,
    state: dict,
    confirm_hours: int,
    cooldown_hours: int,
) -> dict:
    spread = rates["spread"]
    favors = "delta-neutral" if spread > 0 else "usdc"
    current = state["regime"]
    consecutive = state["consecutive_hours"]
    last_switch = state.get("last_switch_at")

    # Cooldown check
    cooldown_active = False
    if last_switch:
        elapsed = datetime.now(UTC) - datetime.fromisoformat(last_switch)
        cooldown_active = elapsed < timedelta(hours=cooldown_hours)

    # Confirmation counter
    if favors != current and not cooldown_active:
        consecutive += 1
    elif favors == current:
        consecutive = 0

    # Switch?
    switched = False
    if consecutive >= confirm_hours and not cooldown_active:
        current = favors
        consecutive = 0
        last_switch = datetime.now(UTC).isoformat()
        switched = True

    new_state = {
        "regime": current,
        "consecutive_hours": consecutive,
        "last_switch_at": last_switch,
    }

    return {
        "regime": current,
        "favors": favors,
        "switched": switched,
        "cooldown_active": cooldown_active,
        "consecutive_hours": consecutive,
        "confirm_threshold": confirm_hours,
        "state": new_state,
    }


def emit_signal(regime: str, rates: dict, switched: bool) -> None:
    level = "warning" if switched else "info"
    title = f"Regime: {regime.upper()}"
    if switched:
        title = f"SWITCH -> {regime.upper()}"

    cmd = [
        "poetry", "run", "wayfinder", "pack", "signal", "emit",
        "--slug", SLUG,
        "--title", title,
        "--level", level,
        "--metric", f"regime={'1' if regime == 'delta-neutral' else '0'}",
        "--metric", f"spread={rates['spread']:.4f}",
        "--metric", f"dn_yield={rates['dn_yield']:.4f}",
        "--metric", f"usdc_yield={rates['usdc_supply_apr']:.4f}",
        "--metric", f"funding_ann={rates['funding_ann']:.4f}",
        "--metric", f"price={rates['price']:.2f}",
    ]
    subprocess.run(cmd, capture_output=True)


def emit_event(regime: str, rates: dict, classification: dict) -> None:
    payload = {
        "regime": regime,
        "switched": classification["switched"],
        "cooldown_active": classification["cooldown_active"],
        "consecutive_hours": classification["consecutive_hours"],
        "rates": {
            "dn_yield": rates["dn_yield"],
            "usdc_yield": rates["usdc_supply_apr"],
            "spread": rates["spread"],
            "funding_ann": rates["funding_ann"],
            "virtual_supply_apr": rates["virtual_supply_apr"],
            "price": rates["price"],
        },
    }
    cmd = [
        "poetry", "run", "wayfinder", "pack", "event", "emit",
        "--slug", SLUG,
        "--type", "state_snapshot",
        "--payload-json", json.dumps(payload),
    ]
    subprocess.run(cmd, capture_output=True)


async def async_main(args: argparse.Namespace) -> None:
    state = load_state()
    rates = await fetch_latest_rates()
    result = classify(rates, state, args.confirm_hours, args.cooldown_hours)

    regime = result["regime"]
    spread_pct = rates["spread"] * 100
    dn_pct = rates["dn_yield"] * 100
    usdc_pct = rates["usdc_supply_apr"] * 100

    print(f"[{rates['ts']}]")
    print(f"  Regime:     {regime.upper()}")
    print(f"  DN yield:   {dn_pct:+.1f}%  (supply {rates['virtual_supply_apr']*100:.1f}% + funding {rates['funding_ann']*100:.1f}%)")
    print(f"  USDC yield: {usdc_pct:.1f}%")
    print(f"  Spread:     {spread_pct:+.1f}%  (favors {result['favors']})")
    print(f"  Confirm:    {result['consecutive_hours']}/{args.confirm_hours}h")
    if result["cooldown_active"]:
        print("  Cooldown:   ACTIVE")
    if result["switched"]:
        print(f"  *** REGIME SWITCH -> {regime.upper()} ***")

    if args.dry_run:
        print("\n  (dry-run: state not saved, no signals emitted)")
        print(json.dumps(result, indent=2, default=str))
        return

    save_state(result["state"])
    emit_signal(regime, rates, result["switched"])
    emit_event(regime, rates, result)


def main() -> None:
    parser = argparse.ArgumentParser(description="Classify VIRTUAL delta-neutral regime")
    parser.add_argument("--confirm-hours", type=int, default=DEFAULTS["confirm_hours"])
    parser.add_argument("--cooldown-hours", type=int, default=DEFAULTS["cooldown_hours"])
    parser.add_argument("--dry-run", action="store_true", help="Don't emit signals or persist state")
    args = parser.parse_args()
    asyncio.run(async_main(args))


if __name__ == "__main__":
    main()
