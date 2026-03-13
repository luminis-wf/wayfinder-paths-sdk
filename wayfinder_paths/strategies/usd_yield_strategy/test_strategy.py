from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from wayfinder_paths.strategies.usd_yield_strategy.strategy import (
    UsdYieldStrategy,
)
from wayfinder_paths.tests.test_utils import (
    assert_quote_result,
    assert_status_dict,
    assert_status_tuple,
    get_canonical_examples,
    load_strategy_examples,
)

_UsdYieldStrategy = UsdYieldStrategy


@pytest.fixture
def strategy():
    mock_config = {
        "main_wallet": {"address": "0x1234567890123456789012345678901234567890"},
        "strategy_wallet": {"address": "0xabcdefabcdefabcdefabcdefabcdefabcdefabcd"},
    }

    s = UsdYieldStrategy(
        config=mock_config,
    )

    if hasattr(s, "balance_adapter") and s.balance_adapter:

        def get_balance_side_effect(
            *, wallet_address, token_id=None, token_address=None, chain_id=None
        ):
            if token_id == "usd-coin-base" or token_id == "usd-coin":
                return (True, 60000000)
            elif token_id == "ethereum-base" or token_id == "ethereum":
                return (True, 2000000000000000)
            return (True, 1000000000)

        s.balance_adapter.get_balance = AsyncMock(side_effect=get_balance_side_effect)

    if hasattr(s, "token_adapter") and s.token_adapter:
        default_usdc = {
            "id": "usd-coin-base",
            "token_id": "usd-coin-base",
            "symbol": "USDC",
            "name": "USD Coin",
            "decimals": 6,
            "address": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
            "chain": {"code": "base", "id": 8453, "name": "Base"},
        }

        default_pool_token = {
            "id": "test-pool-base",
            "token_id": "test-pool-base",
            "symbol": "POOL",
            "name": "Test Pool",
            "decimals": 18,
            "address": "0x1234567890123456789012345678901234567890",
            "chain": {"code": "base", "id": 8453, "name": "Base"},
        }

        def get_token_side_effect(address=None, token_id=None, **kwargs):
            if token_id == "usd-coin-base" or token_id == "usd-coin":
                return (True, default_usdc)
            elif (
                token_id == "test-pool-base"
                or address == "0x1234567890123456789012345678901234567890"
            ):
                return (True, default_pool_token)
            return (True, default_usdc)

        s.token_adapter.get_token = AsyncMock(side_effect=get_token_side_effect)
        s.token_adapter.get_gas_token = AsyncMock(
            return_value=(
                True,
                {
                    "id": "ethereum-base",
                    "token_id": "ethereum-base",
                    "symbol": "ETH",
                    "name": "Ethereum",
                    "decimals": 18,
                    "address": "0x4200000000000000000000000000000000000006",
                    "chain": {"code": "base", "id": 8453, "name": "Base"},
                },
            )
        )

    if hasattr(s, "balance_adapter") and s.balance_adapter:
        s.balance_adapter.move_from_main_wallet_to_strategy_wallet = AsyncMock(
            return_value=(True, "0xtxhash_transfer")
        )
        s.balance_adapter.move_from_strategy_wallet_to_main_wallet = AsyncMock(
            return_value=(True, "0xtxhash_transfer")
        )

    if hasattr(s, "ledger_adapter") and s.ledger_adapter:
        s.ledger_adapter.get_strategy_net_deposit = AsyncMock(return_value=(True, 0.0))
        s.ledger_adapter.get_strategy_transactions = AsyncMock(
            return_value=(True, {"transactions": []})
        )

    if hasattr(s, "pool_adapter") and s.pool_adapter:
        s.pool_adapter.get_pools_by_ids = AsyncMock(
            return_value=(
                True,
                {"pools": [{"id": "test-pool-base", "apy": 15.0, "symbol": "USDC"}]},
            )
        )
        s.pool_adapter.get_pools = AsyncMock(
            return_value=(
                True,
                {
                    "matches": [
                        {
                            "stablecoin": True,
                            "ilRisk": "no",
                            "tvlUsd": 2000000,
                            "apy": 5.0,
                            "symbol": "USDC",
                            "network": "base",
                            "address": "0x1234567890123456789012345678901234567890",
                            "token_id": "test-pool-base",
                            "pool_id": "test-pool-base",
                            "combined_apy_pct": 15.0,
                        }
                    ]
                },
            ),
        )

    if hasattr(s, "brap_adapter") and s.brap_adapter:

        def best_quote_side_effect(*args, **kwargs):
            to_token_address = kwargs.get("to_token_address", "")
            if to_token_address == "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913":
                return (True, {"output_amount": "99900000"})
            return (
                True,
                {
                    "output_amount": "105000000",
                    "input_amount": "50000000000000",
                    "toAmount": "105000000",
                    "estimatedGas": "1000000000",
                    "fromAmount": "100000000",
                    "fromToken": {"symbol": "USDC"},
                    "toToken": {"symbol": "POOL"},
                },
            )

        s.brap_adapter.best_quote = AsyncMock(side_effect=best_quote_side_effect)

    if (
        hasattr(s, "brap_adapter")
        and s.brap_adapter
        and hasattr(s.brap_adapter, "swap_from_quote")
    ):
        s.brap_adapter.swap_from_quote = AsyncMock(
            return_value=(
                True,
                {"tx_hash": "0xmockhash", "from_amount": "100", "to_amount": "99"},
            )
        )

    s.DEPOSIT_USDC = 0
    s.usdc_token_info = {
        "id": "usd-coin-base",
        "token_id": "usd-coin-base",
        "symbol": "USDC",
        "name": "USD Coin",
        "decimals": 6,
        "address": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
        "chain": {"code": "base", "id": 8453, "name": "Base"},
    }
    s.gas_token = {
        "id": "ethereum-base",
        "token_id": "ethereum-base",
        "symbol": "ETH",
        "name": "Ethereum",
        "decimals": 18,
        "address": "0x4200000000000000000000000000000000000006",
        "chain": {"code": "base", "id": 8453, "name": "Base"},
    }
    s.current_pool = {
        "id": "usd-coin-base",
        "token_id": "usd-coin-base",
        "symbol": "USDC",
        "decimals": 6,
        "chain": {"code": "base", "id": 8453, "name": "Base"},
    }
    s.current_pool_balance = 100000000
    s.current_combined_apy_pct = 0.0
    s.current_pool_data = None

    if hasattr(s, "token_adapter") and s.token_adapter:
        if not hasattr(s.token_adapter, "get_token_price"):
            s.token_adapter.get_token_price = AsyncMock()

        def get_token_price_side_effect(token_id):
            if token_id == "ethereum-base":
                return (True, {"current_price": 2000.0})
            else:
                return (True, {"current_price": 1.0})

        s.token_adapter.get_token_price = AsyncMock(
            side_effect=get_token_price_side_effect
        )

    async def mock_refresh_current_pool_balance():
        pass

    async def mock_rebalance_gas(target_pool):
        return (True, "Gas rebalanced")

    async def mock_has_idle_assets(balances, target):
        return True

    s._refresh_current_pool_balance = mock_refresh_current_pool_balance
    s._rebalance_gas = mock_rebalance_gas
    s._has_idle_assets = mock_has_idle_assets

    return s


@pytest.mark.asyncio
@pytest.mark.smoke
async def test_smoke(strategy):
    examples = load_strategy_examples(Path(__file__))
    smoke_data = examples["smoke"]

    st = assert_status_dict(await strategy.status())
    assert "portfolio_value" in st
    assert "net_deposit" in st
    assert "strategy_status" in st

    deposit_params = smoke_data.get("deposit", {})
    ok, msg = assert_status_tuple(await strategy.deposit(**deposit_params))
    assert isinstance(ok, bool)
    assert isinstance(msg, str)

    ok, msg = assert_status_tuple(await strategy.update(**smoke_data.get("update", {})))
    assert isinstance(ok, bool)

    ok, msg = assert_status_tuple(
        await strategy.withdraw(**smoke_data.get("withdraw", {}))
    )
    assert isinstance(ok, bool)


@pytest.mark.asyncio
async def test_canonical_usage(strategy):
    examples = load_strategy_examples(Path(__file__))
    canonical = get_canonical_examples(examples)

    for example_name, example_data in canonical.items():
        if "deposit" in example_data:
            deposit_params = example_data.get("deposit", {})
            ok, _ = assert_status_tuple(await strategy.deposit(**deposit_params))
            assert ok, f"Canonical example '{example_name}' deposit failed"

        if "update" in example_data:
            ok, msg = assert_status_tuple(await strategy.update())
            assert ok, f"Canonical example '{example_name}' update failed: {msg}"

        if "status" in example_data:
            st = assert_status_dict(await strategy.status())
            assert isinstance(st, dict), (
                f"Canonical example '{example_name}' status failed"
            )


@pytest.mark.asyncio
async def test_quote_returns_quote_result(strategy):
    assert_quote_result(await strategy.quote(deposit_amount=1000.0))


@pytest.mark.asyncio
async def test_exit_returns_status_tuple(strategy):
    assert_status_tuple(await strategy.exit())


@pytest.mark.asyncio
async def test_error_cases(strategy):
    examples = load_strategy_examples(Path(__file__))

    for example_name, example_data in examples.items():
        if isinstance(example_data, dict) and "expect" in example_data:
            expect = example_data.get("expect", {})

            if "deposit" in example_data:
                deposit_params = example_data.get("deposit", {})
                ok, _ = assert_status_tuple(await strategy.deposit(**deposit_params))

                if expect.get("success") is False:
                    assert ok is False, (
                        f"Expected {example_name} deposit to fail but it succeeded"
                    )
                elif expect.get("success") is True:
                    assert ok is True, (
                        f"Expected {example_name} deposit to succeed but it failed"
                    )

            if "update" in example_data:
                ok, _ = assert_status_tuple(await strategy.update())
                if "success" in expect:
                    expected_success = expect.get("success")
                    assert ok == expected_success, (
                        f"Expected {example_name} update to "
                        f"{'succeed' if expected_success else 'fail'} but got opposite"
                    )


@pytest.mark.asyncio
async def test_setup_handles_float_net_deposit(strategy):
    strategy.ledger_adapter.get_strategy_net_deposit = AsyncMock(
        return_value=(True, 1500.0)
    )
    await strategy.setup()
    assert strategy.DEPOSIT_USDC == 1500.0


@pytest.mark.asyncio
async def test_usd_pool_filtering(strategy):
    """Verify that non-USD pools (e.g. EUR) are excluded even when they have higher APY."""
    # Mock pools: EUR pool has higher APY but should be filtered out
    strategy.pool_adapter.get_pools = AsyncMock(
        return_value=(
            True,
            {
                "matches": [
                    {
                        "stablecoin": True,
                        "ilRisk": "no",
                        "tvlUsd": 5000000,
                        "apy": 20.0,
                        "symbol": "agEUR-USDC",
                        "network": "base",
                        "address": "0xEURPool",
                        "token_id": "ageur-pool",
                        "pool_id": "ageur-pool",
                        "combined_apy_pct": 20.0,
                    },
                    {
                        "stablecoin": True,
                        "ilRisk": "no",
                        "tvlUsd": 3000000,
                        "apy": 8.0,
                        "symbol": "USDC-USDT",
                        "network": "base",
                        "address": "0xUSDPool",
                        "token_id": "usdc-usdt-pool",
                        "pool_id": "usdc-usdt-pool",
                        "combined_apy_pct": 8.0,
                    },
                ]
            },
        ),
    )

    # Set current pool to something different so _find_best_pool doesn't short-circuit
    strategy.current_pool = {
        "id": "usd-coin-base",
        "token_id": "usd-coin-base",
        "symbol": "USDC",
        "decimals": 6,
        "address": "0xSomethingElse",
        "chain": {"code": "base", "id": 8453, "name": "Base"},
    }
    strategy.current_combined_apy_pct = 1.0
    strategy.current_pool_balance = 100

    ok, result = await strategy._find_best_pool()

    # The EUR pool (20% APY) should be filtered out.
    # If a pool is selected, it must be the USDC-USDT pool, not the agEUR one.
    if ok:
        target_data = result.get("target_pool_data", {})
        assert target_data.get("symbol") != "agEUR-USDC", (
            "EUR pool should have been filtered out"
        )
