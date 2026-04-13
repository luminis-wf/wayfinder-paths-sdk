"""Oil Macro Hedge — Polymarket WTI oil bearish + Hyperliquid ETH short hedge.

Two-leg strategy with automatic monthly rollover of Polymarket prediction
markets and a correlated macro hedge via ETH perp short on Hyperliquid.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from loguru import logger

from wayfinder_paths.adapters.hyperliquid_adapter.adapter import HyperliquidAdapter
from wayfinder_paths.adapters.polymarket_adapter.adapter import PolymarketAdapter
from wayfinder_paths.core.constants.hyperliquid import (
    DEFAULT_HYPERLIQUID_BUILDER_FEE_TENTHS_BP,
    HYPE_FEE_WALLET,
)
from wayfinder_paths.mcp.scripting import get_adapter

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ETH_PERP_ASSET_ID = 1
POLYGON_CHAIN_ID = 137
ARBITRUM_CHAIN_ID = 42161

# Polymarket USDC.e on Polygon
POLYGON_USDC_E = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
# Native USDC on Polygon
POLYGON_USDC = "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"
# USDC on Arbitrum
ARBITRUM_USDC = "0xaf88d065e77c8cC2239327C5EDb3A432268e5831"

DEFAULT_POLYMARKET_ALLOC = 0.70
DEFAULT_HL_ALLOC = 0.30
DEFAULT_ROLLOVER_DAYS = 3
ROLLOVER_COOLDOWN_HOURS = 12
DEFAULT_LEVERAGE = 1
MAX_LEVERAGE = 2
FUNDING_GUARD_REDUCE = -0.001  # 8h rate; reduce hedge at this level
FUNDING_GUARD_CLOSE = -0.003  # close hedge entirely
REBALANCE_DRIFT_PCT = 0.10
MIN_DEPOSIT_USD = 50.0
HL_MIN_NOTIONAL = 10.0
HL_SLIPPAGE = 0.05

STATE_FILE = ".oil_macro_hedge_state.json"

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------


@dataclass
class OilPosition:
    market_slug: str
    condition_id: str
    outcome: str
    shares: float
    cost_basis_usdc: float
    buy_price: float
    end_date_iso: str
    question: str
    strike: float | None = None


@dataclass
class HedgePosition:
    size_eth: float  # negative = short
    entry_price: float
    leverage: int
    unrealized_pnl: float = 0.0


@dataclass
class StrategyState:
    polymarket_positions: list[OilPosition] = field(default_factory=list)
    hedge: HedgePosition | None = None
    last_rollover_iso: str | None = None
    net_deposit_usdc: float = 0.0
    created_at: str = ""

    def save(self, path: Path) -> None:
        path.write_text(json.dumps(asdict(self), indent=2))

    @classmethod
    def load(cls, path: Path) -> StrategyState:
        if not path.exists():
            return cls(created_at=datetime.now(UTC).isoformat())
        raw = json.loads(path.read_text())
        positions = [OilPosition(**p) for p in raw.get("polymarket_positions", [])]
        hedge_raw = raw.get("hedge")
        hedge = HedgePosition(**hedge_raw) if hedge_raw else None
        return cls(
            polymarket_positions=positions,
            hedge=hedge,
            last_rollover_iso=raw.get("last_rollover_iso"),
            net_deposit_usdc=raw.get("net_deposit_usdc", 0.0),
            created_at=raw.get("created_at", ""),
        )


# ---------------------------------------------------------------------------
# Market discovery
# ---------------------------------------------------------------------------


def _parse_strike(question: str) -> float | None:
    m = re.search(r"\$(\d+(?:\.\d+)?)", question)
    return float(m.group(1)) if m else None


def _is_bearish_oil_market(question: str) -> bool:
    q = question.lower()
    bearish_keywords = ["dip", "below", "low", "fall", "drop"]
    oil_keywords = ["wti", "crude", "oil"]
    return any(k in q for k in oil_keywords) and any(k in q for k in bearish_keywords)


async def discover_wti_market(
    pm: PolymarketAdapter,
    *,
    target_month: str | None = None,
    strike: float | None = None,
) -> dict[str, Any] | None:
    """Find the best WTI crude oil bearish prediction market.

    Returns the raw market dict from Polymarket or None.
    """
    if target_month:
        year, month = target_month.split("-")
        month_name = datetime(int(year), int(month), 1).strftime("%B")
    else:
        next_m = datetime.now(UTC) + timedelta(days=15)
        month_name = next_m.strftime("%B")
        year = next_m.strftime("%Y")
        target_month = next_m.strftime("%Y-%m")

    queries = []
    if strike:
        queries.append(f"WTI crude oil ${strike:.0f} {month_name}")
        queries.append(f"oil ${strike:.0f} {month_name} {year}")
    queries.extend([
        f"WTI crude oil {month_name} {year}",
        f"oil price {month_name} {year}",
        "WTI crude oil",
    ])

    best: dict[str, Any] | None = None
    best_score = 0.0

    for query in queries:
        ok, result = await pm.search_markets_fuzzy(query=query, limit=20)
        if not ok or not isinstance(result, list):
            continue

        for m in result:
            if not m.get("clobTokenIds") or not m.get("acceptingOrders"):
                continue
            if m.get("closed"):
                continue

            question = m.get("question", "")
            if not _is_bearish_oil_market(question):
                continue

            end_date = m.get("endDateIso", "")
            month_match = end_date.startswith(target_month)
            parsed_strike = _parse_strike(question)
            strike_match = strike and parsed_strike and abs(parsed_strike - strike) < 1

            score = 1.0
            if month_match:
                score += 2.0
            if strike_match:
                score += 3.0
            volume = float(m.get("volume", 0) or 0)
            score += min(volume / 100_000, 1.0)

            if score > best_score:
                best_score = score
                best = {**m, "_parsed_strike": parsed_strike, "_score": best_score}

    return best


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------


async def action_discover(args: argparse.Namespace) -> None:
    """Search Polymarket for WTI oil markets."""
    pm: PolymarketAdapter = await get_adapter(PolymarketAdapter)

    market = await discover_wti_market(
        pm, target_month=args.month, strike=args.strike
    )
    if not market:
        print("No suitable WTI oil market found on Polymarket.")
        return

    print(f"Best market (score {market['_score']:.1f}):")
    print(f"  Question : {market['question']}")
    print(f"  Slug     : {market['slug']}")
    print(f"  End date : {market.get('endDateIso', '?')}")
    print(f"  Strike   : ${market.get('_parsed_strike', '?')}")
    yes_price = market.get("outcomePrices", ["?", "?"])
    print(f"  YES price: {yes_price[0] if isinstance(yes_price, list) else yes_price}")
    print(f"  Volume   : ${float(market.get('volume', 0)):,.0f}")
    print(f"  Liquidity: ${float(market.get('liquidity', 0)):,.0f}")


async def action_status(args: argparse.Namespace) -> None:
    """Show current strategy state."""
    state_path = Path(args.state_file)
    state = StrategyState.load(state_path)

    print("=== Oil Macro Hedge Status ===")
    print(f"Net deposit: ${state.net_deposit_usdc:,.2f}")
    print(f"Last rollover: {state.last_rollover_iso or 'never'}")
    print()

    if state.polymarket_positions:
        print("-- Polymarket Positions --")
        for p in state.polymarket_positions:
            end = datetime.fromisoformat(p.end_date_iso.replace("Z", "+00:00"))
            days_left = (end - datetime.now(UTC)).total_seconds() / 86400
            print(f"  {p.question}")
            print(f"    Slug: {p.market_slug}")
            print(f"    Outcome: {p.outcome} | Shares: {p.shares:.2f} | Cost: ${p.cost_basis_usdc:.2f}")
            print(f"    Buy price: ${p.buy_price:.3f} | Strike: ${p.strike or '?'}")
            print(f"    Expires: {p.end_date_iso} ({days_left:.1f} days)")
            print()
    else:
        print("No Polymarket positions.")
        print()

    if state.hedge:
        h = state.hedge
        direction = "SHORT" if h.size_eth < 0 else "LONG"
        print("-- Hyperliquid ETH Hedge --")
        print(f"  Direction: {direction} | Size: {abs(h.size_eth):.4f} ETH")
        print(f"  Entry: ${h.entry_price:,.2f} | Leverage: {h.leverage}x")
        print(f"  Unrealized PnL: ${h.unrealized_pnl:,.2f}")
    else:
        print("No Hyperliquid hedge position.")


async def action_deposit(args: argparse.Namespace) -> None:
    """Open initial positions on both legs."""
    amount = args.amount
    if amount < MIN_DEPOSIT_USD:
        print(f"Minimum deposit is ${MIN_DEPOSIT_USD}. Got ${amount}.")
        return

    pm_alloc = amount * args.polymarket_alloc
    hl_alloc = amount * args.hl_alloc

    state_path = Path(args.state_file)
    state = StrategyState.load(state_path)

    wallet_label = args.wallet

    # --- Polymarket leg ---
    print(f"\n[1/2] Polymarket leg: ${pm_alloc:,.2f}")

    pm: PolymarketAdapter = await get_adapter(PolymarketAdapter, wallet_label)

    market = await discover_wti_market(
        pm, target_month=args.month, strike=args.strike
    )
    if not market:
        print("  ERROR: No WTI market found. Polymarket leg skipped.")
    else:
        print(f"  Market: {market['question']}")
        print(f"  Slug: {market['slug']}")

        # Bridge USDC to Polygon USDC.e for Polymarket
        print(f"  Bridging ${pm_alloc:,.2f} USDC -> Polygon USDC.e ...")
        ok, bridge_result = await pm.bridge_deposit(
            from_chain_id=ARBITRUM_CHAIN_ID,
            from_token_address=ARBITRUM_USDC,
            amount=pm_alloc,
            recipient_address=pm.wallet_address,
        )
        if not ok:
            print(f"  ERROR bridging: {bridge_result}")
        else:
            print("  Bridge complete. Buying YES shares...")
            ok, buy_result = await pm.place_prediction(
                market_slug=market["slug"],
                outcome="YES",
                amount_usdc=pm_alloc,
            )
            if not ok:
                print(f"  ERROR buying: {buy_result}")
            else:
                yes_price = float(market.get("outcomePrices", [0])[0])
                shares = pm_alloc / yes_price if yes_price > 0 else 0
                state.polymarket_positions.append(OilPosition(
                    market_slug=market["slug"],
                    condition_id=market.get("conditionId", ""),
                    outcome="YES",
                    shares=shares,
                    cost_basis_usdc=pm_alloc,
                    buy_price=yes_price,
                    end_date_iso=market.get("endDateIso", ""),
                    question=market.get("question", ""),
                    strike=market.get("_parsed_strike"),
                ))
                print(f"  Bought ~{shares:.1f} YES shares at ${yes_price:.3f}")

    # --- Hyperliquid leg ---
    print(f"\n[2/2] Hyperliquid ETH short: ${hl_alloc:,.2f}")

    if hl_alloc < HL_MIN_NOTIONAL:
        print(f"  Skipping: ${hl_alloc:.2f} below HL minimum ${HL_MIN_NOTIONAL}")
    else:
        hl: HyperliquidAdapter = await get_adapter(HyperliquidAdapter, wallet_label)
        hl_address = hl.wallet_address

        leverage = min(args.leverage, MAX_LEVERAGE)
        ok, lev_result = await hl.update_leverage(
            ETH_PERP_ASSET_ID, leverage, is_cross=True, address=hl_address
        )
        if not ok:
            print(f"  WARNING: leverage update failed: {lev_result}")

        # Get ETH price for sizing
        ok, user_state = await hl.get_user_state(hl_address)
        if not ok:
            print(f"  ERROR getting HL state: {user_state}")
        else:
            # Estimate ETH price from midprice
            ok_meta, meta = await hl.get_meta_and_asset_ctxs()
            if ok_meta:
                eth_ctx = meta[1][ETH_PERP_ASSET_ID]  # asset contexts
                eth_price = float(eth_ctx.get("markPx", 0))
            else:
                eth_price = 2000.0  # fallback

            notional = hl_alloc * leverage
            size_eth = notional / eth_price if eth_price > 0 else 0
            size_eth = hl.get_valid_order_size(ETH_PERP_ASSET_ID, size_eth)

            if size_eth <= 0:
                print("  ERROR: computed size is 0 after rounding.")
            else:
                builder = {"b": HYPE_FEE_WALLET, "f": DEFAULT_HYPERLIQUID_BUILDER_FEE_TENTHS_BP}
                ok, order_result = await hl.place_market_order(
                    asset_id=ETH_PERP_ASSET_ID,
                    is_buy=False,  # short
                    slippage=HL_SLIPPAGE,
                    size=size_eth,
                    address=hl_address,
                    builder=builder,
                )
                if not ok:
                    print(f"  ERROR placing short: {order_result}")
                else:
                    state.hedge = HedgePosition(
                        size_eth=-size_eth,
                        entry_price=eth_price,
                        leverage=leverage,
                    )
                    print(f"  Opened {size_eth:.4f} ETH short at ~${eth_price:,.2f} ({leverage}x)")

    state.net_deposit_usdc += amount
    if not state.created_at:
        state.created_at = datetime.now(UTC).isoformat()
    state.save(state_path)
    print(f"\nDeposit complete. State saved to {state_path}")


async def action_update(args: argparse.Namespace) -> None:
    """Periodic update: check resolution, rollover, rebalance, funding guard."""
    state_path = Path(args.state_file)
    state = StrategyState.load(state_path)
    wallet_label = args.wallet
    changed = False

    pm: PolymarketAdapter = await get_adapter(PolymarketAdapter, wallet_label)

    # --- Step 1: Check for resolved markets ---
    still_active: list[OilPosition] = []
    for pos in state.polymarket_positions:
        ok, market = await pm.get_market_by_slug(pos.market_slug)
        if not ok:
            logger.warning(f"Could not fetch market {pos.market_slug}: {market}")
            still_active.append(pos)
            continue

        if market.get("closed"):
            print(f"Market resolved: {pos.question}")
            ok_r, redeem_result = await pm.redeem_positions(
                condition_id=pos.condition_id,
                holder=pm.wallet_address,
            )
            if ok_r:
                print(f"  Redeemed successfully: {redeem_result}")
            else:
                print(f"  Redeem failed (may have no winning shares): {redeem_result}")
            changed = True
        else:
            still_active.append(pos)

    state.polymarket_positions = still_active

    # --- Step 2: Check rollover ---
    for i, pos in enumerate(list(state.polymarket_positions)):
        try:
            end = datetime.fromisoformat(pos.end_date_iso.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            continue

        days_left = (end - datetime.now(UTC)).total_seconds() / 86400
        if days_left > args.rollover_days:
            continue

        # Check cooldown
        if state.last_rollover_iso:
            last_roll = datetime.fromisoformat(state.last_rollover_iso)
            hours_since = (datetime.now(UTC) - last_roll).total_seconds() / 3600
            if hours_since < ROLLOVER_COOLDOWN_HOURS:
                print(f"Rollover cooldown: {hours_since:.1f}h < {ROLLOVER_COOLDOWN_HOURS}h")
                continue

        print(f"Rolling over: {pos.question} ({days_left:.1f} days to expiry)")

        # Sell current position
        ok, sell_result = await pm.cash_out_prediction(
            market_slug=pos.market_slug,
            outcome=pos.outcome,
            shares=pos.shares,
        )
        if not ok:
            print(f"  Sell failed: {sell_result}")
            continue

        print(f"  Sold {pos.shares:.1f} shares")

        # Discover next month
        next_month = (datetime.now(UTC) + timedelta(days=30)).strftime("%Y-%m")
        new_market = await discover_wti_market(
            pm, target_month=next_month, strike=pos.strike
        )
        if not new_market:
            print("  No next-month market found. Position closed without rollover.")
            state.polymarket_positions.remove(pos)
            changed = True
            continue

        # Buy new position with proceeds
        # Use the cost basis as approximate available amount
        buy_amount = pos.cost_basis_usdc
        ok, buy_result = await pm.place_prediction(
            market_slug=new_market["slug"],
            outcome="YES",
            amount_usdc=buy_amount,
        )
        if not ok:
            print(f"  Buy failed on new market: {buy_result}")
            state.polymarket_positions.remove(pos)
            changed = True
            continue

        yes_price = float(new_market.get("outcomePrices", [0])[0])
        new_shares = buy_amount / yes_price if yes_price > 0 else 0

        new_pos = OilPosition(
            market_slug=new_market["slug"],
            condition_id=new_market.get("conditionId", ""),
            outcome="YES",
            shares=new_shares,
            cost_basis_usdc=buy_amount,
            buy_price=yes_price,
            end_date_iso=new_market.get("endDateIso", ""),
            question=new_market.get("question", ""),
            strike=new_market.get("_parsed_strike"),
        )
        state.polymarket_positions[i] = new_pos
        state.last_rollover_iso = datetime.now(UTC).isoformat()
        changed = True

        print(f"  Rolled to: {new_market['question']}")
        print(f"  Bought ~{new_shares:.1f} shares at ${yes_price:.3f}")

    # --- Step 3: Funding guard on ETH short ---
    if state.hedge:
        hl: HyperliquidAdapter = await get_adapter(HyperliquidAdapter, wallet_label)
        hl_address = hl.wallet_address

        ok, meta = await hl.get_meta_and_asset_ctxs()
        if ok:
            eth_ctx = meta[1][ETH_PERP_ASSET_ID]
            funding_8h = float(eth_ctx.get("funding", 0))

            if funding_8h < FUNDING_GUARD_CLOSE:
                print(f"Funding guard CLOSE: 8h rate {funding_8h:.6f} < {FUNDING_GUARD_CLOSE}")
                close_size = abs(state.hedge.size_eth)
                close_size = hl.get_valid_order_size(ETH_PERP_ASSET_ID, close_size)
                builder = {"b": HYPE_FEE_WALLET, "f": DEFAULT_HYPERLIQUID_BUILDER_FEE_TENTHS_BP}
                ok, res = await hl.place_market_order(
                    asset_id=ETH_PERP_ASSET_ID,
                    is_buy=True,
                    slippage=HL_SLIPPAGE,
                    size=close_size,
                    address=hl_address,
                    reduce_only=True,
                    builder=builder,
                )
                if ok:
                    state.hedge = None
                    changed = True
                    print("  Closed ETH short hedge entirely.")
                else:
                    print(f"  Failed to close hedge: {res}")

            elif funding_8h < FUNDING_GUARD_REDUCE and state.hedge:
                print(f"Funding guard REDUCE: 8h rate {funding_8h:.6f} < {FUNDING_GUARD_REDUCE}")
                reduce_size = abs(state.hedge.size_eth) * 0.5
                reduce_size = hl.get_valid_order_size(ETH_PERP_ASSET_ID, reduce_size)
                if reduce_size > 0:
                    builder = {"b": HYPE_FEE_WALLET, "f": DEFAULT_HYPERLIQUID_BUILDER_FEE_TENTHS_BP}
                    ok, res = await hl.place_market_order(
                        asset_id=ETH_PERP_ASSET_ID,
                        is_buy=True,
                        slippage=HL_SLIPPAGE,
                        size=reduce_size,
                        address=hl_address,
                        reduce_only=True,
                        builder=builder,
                    )
                    if ok:
                        state.hedge.size_eth += reduce_size  # reduce magnitude
                        changed = True
                        print(f"  Reduced ETH short by {reduce_size:.4f} ETH")
                    else:
                        print(f"  Failed to reduce hedge: {res}")

    if changed:
        state.save(state_path)
        print(f"\nState updated and saved to {state_path}")
    else:
        print("\nNo changes needed.")


async def action_withdraw(args: argparse.Namespace) -> None:
    """Close all positions on both legs."""
    state_path = Path(args.state_file)
    state = StrategyState.load(state_path)
    wallet_label = args.wallet

    # --- Close Polymarket positions ---
    if state.polymarket_positions:
        pm: PolymarketAdapter = await get_adapter(PolymarketAdapter, wallet_label)

        for pos in state.polymarket_positions:
            # Try to check if resolved first
            ok, market = await pm.get_market_by_slug(pos.market_slug)
            if ok and market.get("closed"):
                print(f"Redeeming resolved market: {pos.question}")
                await pm.redeem_positions(
                    condition_id=pos.condition_id,
                    holder=pm.wallet_address,
                )
            else:
                print(f"Selling: {pos.question} ({pos.shares:.1f} shares)")
                ok, result = await pm.cash_out_prediction(
                    market_slug=pos.market_slug,
                    outcome=pos.outcome,
                    shares=pos.shares,
                )
                if not ok:
                    print(f"  Sell failed: {result}")

        state.polymarket_positions = []

    # --- Close Hyperliquid hedge ---
    if state.hedge:
        hl: HyperliquidAdapter = await get_adapter(HyperliquidAdapter, wallet_label)
        hl_address = hl.wallet_address
        close_size = abs(state.hedge.size_eth)
        close_size = hl.get_valid_order_size(ETH_PERP_ASSET_ID, close_size)

        if close_size > 0:
            print(f"Closing ETH short: {close_size:.4f} ETH")
            builder = {"b": HYPE_FEE_WALLET, "f": DEFAULT_HYPERLIQUID_BUILDER_FEE_TENTHS_BP}
            ok, result = await hl.place_market_order(
                asset_id=ETH_PERP_ASSET_ID,
                is_buy=True,
                slippage=HL_SLIPPAGE,
                size=close_size,
                address=hl_address,
                reduce_only=True,
                builder=builder,
            )
            if ok:
                print("  Closed ETH short.")
            else:
                print(f"  Failed to close: {result}")

        state.hedge = None

    state.save(state_path)
    print(f"\nAll positions closed. State saved to {state_path}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Oil Macro Hedge: Polymarket WTI + Hyperliquid ETH short"
    )
    parser.add_argument(
        "--action",
        choices=["discover", "status", "deposit", "update", "withdraw"],
        required=True,
    )
    parser.add_argument("--config", type=str, default="config.json")
    parser.add_argument("--wallet", type=str, default="main")
    parser.add_argument("--state-file", type=str, default=STATE_FILE)

    # Deposit params
    parser.add_argument("--amount", type=float, default=100.0, help="USDC deposit amount")
    parser.add_argument("--gas", type=float, default=0.01, help="ETH gas amount")
    parser.add_argument("--polymarket-alloc", type=float, default=DEFAULT_POLYMARKET_ALLOC)
    parser.add_argument("--hl-alloc", type=float, default=DEFAULT_HL_ALLOC)
    parser.add_argument("--leverage", type=int, default=DEFAULT_LEVERAGE)

    # Market discovery params
    parser.add_argument("--month", type=str, default=None, help="Target month YYYY-MM")
    parser.add_argument("--strike", type=float, default=None, help="WTI strike price")

    # Update params
    parser.add_argument("--rollover-days", type=int, default=DEFAULT_ROLLOVER_DAYS)

    return parser


async def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    actions = {
        "discover": action_discover,
        "status": action_status,
        "deposit": action_deposit,
        "update": action_update,
        "withdraw": action_withdraw,
    }

    await actions[args.action](args)


if __name__ == "__main__":
    asyncio.run(main())
