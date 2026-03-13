import asyncio
import math
import re
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from loguru import logger

from wayfinder_paths.adapters.aave_v3_adapter.adapter import AaveV3Adapter
from wayfinder_paths.adapters.avantis_adapter.adapter import AvantisAdapter
from wayfinder_paths.adapters.balance_adapter.adapter import BalanceAdapter
from wayfinder_paths.adapters.brap_adapter.adapter import BRAPAdapter
from wayfinder_paths.adapters.euler_v2_adapter.adapter import EulerV2Adapter
from wayfinder_paths.adapters.moonwell_adapter.adapter import MoonwellAdapter
from wayfinder_paths.adapters.morpho_adapter.adapter import MorphoAdapter
from wayfinder_paths.adapters.pool_adapter.adapter import PoolAdapter
from wayfinder_paths.adapters.token_adapter.adapter import TokenAdapter
from wayfinder_paths.core.adapters.models import SWAP as SWAP_OP
from wayfinder_paths.core.constants.contracts import ENSO_ROUTER
from wayfinder_paths.core.strategies.descriptors import (
    Complexity,
    Directionality,
    Frequency,
    StratDescriptor,
    TokenExposure,
    Volatility,
)
from wayfinder_paths.core.strategies.Strategy import StatusDict, StatusTuple, Strategy
from wayfinder_paths.core.utils.symbols import is_pt_symbol, is_usd_pool_symbol


class UsdYieldStrategy(Strategy):
    name = "USD Yield Strategy"

    # Strategy parameters
    MIN_AMOUNT_USDC = 2
    MINIMUM_DAYS_UNTIL_PROFIT = 7
    MIN_TVL = 5_000_000
    DUST_APY = 0.01
    MIN_GAS = 10e-4
    SEARCH_DEPTH = 10
    ROTATION_MIN_INTERVAL = timedelta(days=4)
    MINIMUM_APY_IMPROVEMENT = 0.01
    GAS_MAXIMUM = 10e-4
    GAS_SAFETY_FRACTION = 1 / 3
    # Pools where external reward APY exceeds this fraction of total are ranked
    # by base APY only.  Reward tokens (e.g. YO, governance airdrops) may be
    # non-tradeable, illiquid, or require manual claiming — the strategy should
    # not chase yield it cannot realise.
    MAX_REWARD_RATIO = 0.5
    # Projects that require NFT LP positions or gauge staking — the strategy
    # can only enter simple ERC-20 positions via BRAP/Enso swaps.
    EXCLUDED_PROJECTS: frozenset[str] = frozenset({
        "aerodrome-v1",
        "aerodrome-slipstream",
        "velodrome-v2",
        "uniswap-v3",
        "pancakeswap-v3",
        "sushiswap-v3",
        "baseswap-v3",
    })
    # Protocols with native adapter support — deposits go through the adapter
    # instead of BRAP swaps. Keys are DefiLlama project names.
    PROTOCOL_ROUTES: dict[str, type] = {
        "morpho": MorphoAdapter,
        "moonwell": MoonwellAdapter,
        "aave-v3": AaveV3Adapter,
        "avantis": AvantisAdapter,
        "euler": EulerV2Adapter,
    }

    INFO = StratDescriptor(
        description=(
            "An automated USD yield optimization strategy that maximizes returns on USDC deposits on Base.\n\n"
            "What it does: Continuously scans and evaluates yield opportunities across Base-based DeFi protocols to find the "
            "highest-yielding, low-risk positions for USD stablecoins only. Filters out non-USD pools (EUR, GBP, etc.) to avoid "
            "foreign exchange risk. Automatically rebalances positions when better opportunities emerge.\n\n"
            "Exposure type: Stable USD-denominated exposure with minimal impermanent loss risk. Focuses exclusively on USDC "
            "and USD-pegged stablecoins on the Base network to preserve capital and maximize yield.\n\n"
            "Chains: Operates solely on the Base network.\n\n"
            f"Deposit/Withdrawal: Accepts deposits only in USDC on Base with a minimum of {MIN_AMOUNT_USDC} USDC. Gas: Requires Base ETH "
            "for gas fees during position entry, rebalancing, and exit (~0.001-0.02 ETH per rebalance cycle). Strategy automatically "
            "deploys funds to an optimal USD yield farming position on Base. Withdrawals exit current positions and return USDC to the "
            "user wallet.\n\n"
            f"Risks: Primary risks include smart contract vulnerabilities in underlying Base DeFi protocols, temporary yield fluctuations, "
            f"gas costs during rebalancing, and potential brief capital lock-up during protocol transitions. Strategy filters for a minimum TVL of ${MIN_TVL:,}."
        ),
        summary=(
            "Automated USD stablecoin yield farming across DeFi protocols on Base. "
            "Filters out non-USD pools (EUR, GBP, etc.) to avoid FX risk. "
            f"Continuously optimizes positions for maximum stable yield while avoiding impermanent loss. "
            f"Min: {MIN_AMOUNT_USDC} USDC + ETH gas. Filters for ${MIN_TVL:,}+ TVL protocols."
        ),
        risk_description=f"Protocol risk is always present when engaging with DeFi strategies, this includes underlying DeFi protocols and Wayfinder itself. Additional risks include temporary yield fluctuations, gas costs during rebalancing, and potential brief capital lock-up during protocol transitions. Strategy filters for protocols with a minimum TVL of ${MIN_TVL:,} to ensure low-risk exposure.",
        gas_token_symbol="ETH",
        gas_token_id="ethereum-base",
        deposit_token_id="usd-coin-base",
        minimum_net_deposit=50,
        gas_maximum=GAS_MAXIMUM,
        # Anything below this level triggers a gas top-up
        gas_threshold=GAS_MAXIMUM * GAS_SAFETY_FRACTION,
        # risk indicators
        volatility=Volatility.LOW,
        volatility_description=(
            "Capital sits in Base stablecoin lending pools, so price swings are minimal."
        ),
        directionality=Directionality.MARKET_NEUTRAL,
        directionality_description=(
            "Fully USD-denominated yield farming with no directional crypto beta."
        ),
        complexity=Complexity.LOW,
        complexity_description="Agent handles optimal pool finding and rebalancing",
        token_exposure=TokenExposure.STABLECOINS,
        token_exposure_description=(
            "Only Base USDC (and occasional stable swaps) with no volatile assets."
        ),
        frequency=Frequency.LOW,
        frequency_description=(
            "Updates every 2 hours; rebalances infrequent (bi-weekly cooldowns)."
        ),
        return_drivers=["pool yield"],
        # config metadata for UIs/agents
        config={
            "deposit": {
                "parameters": {
                    "main_token_amount": {
                        "type": "float",
                        "description": "amount of Base USDC (token id: usd-coin-base) to deposit",
                    },
                    "gas_token_amount": {
                        "type": "float",
                        "description": "amount of Base ETH (token id: ethereum-base) to deposit for gas fees",
                        "minimum": 0,
                        "maximum": GAS_MAXIMUM,
                    },
                },
                "process": "Deposits USDC on Base and searches for the highest yield opportunities among Base-based DeFi protocols",
                "requirements": [
                    "Sufficient USDC balance on Base",
                    "Base ETH available for gas",
                ],
                "result": "Funds deployed to a yield farming position on Base",
            },
            "withdraw": {
                "parameters": {},
                "process": "Exits yield positions on Base and returns USDC to the user wallet",
                "requirements": [
                    "Active positions to exit",
                    "Gas for transactions on Base",
                ],
                "result": "USDC returned to wallet and positions closed on Base",
            },
            "update": {
                "parameters": {},
                "process": "Scans for better yield opportunities on Base and rebalances positions automatically",
                "frequency": "Call daily or when significant yield changes occur",
                "requirements": [
                    "Active strategy positions on Base",
                    "Sufficient Base gas for rebalancing",
                ],
                "result": "Positions optimized for maximum yield on Base",
            },
            "technical_details": {
                "wallet_structure": "Uses strategy subwallet for isolation",
                "chains": ["Base"],
                "protocols": ["Various Base DeFi yield protocols"],
                "tokens": ["USDC"],
                "gas_requirements": "~0.001-0.02 ETH per rebalance on Base",
                "search_depth": SEARCH_DEPTH,
                "minimum_tvl": MIN_TVL,
                "dust_apy_threshold": DUST_APY,
                "minimum_apy_edge": MINIMUM_APY_IMPROVEMENT,
                "rotation_cooldown_days": ROTATION_MIN_INTERVAL.days,
                "profit_horizon_days": MINIMUM_DAYS_UNTIL_PROFIT,
            },
        },
    )

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        *,
        main_wallet: dict[str, Any] | None = None,
        strategy_wallet: dict[str, Any] | None = None,
        main_wallet_signing_callback: Callable[[dict], Awaitable[str]] | None = None,
        strategy_wallet_signing_callback: Callable[[dict], Awaitable[str]]
        | None = None,
        strategy_sign_typed_data: Callable[[dict], Awaitable[str]] | None = None,
    ):
        super().__init__(
            main_wallet_signing_callback=main_wallet_signing_callback,
            strategy_wallet_signing_callback=strategy_wallet_signing_callback,
            strategy_sign_typed_data=strategy_sign_typed_data,
        )
        merged_config: dict[str, Any] = dict(config or {})
        if main_wallet is not None:
            merged_config["main_wallet"] = main_wallet
        if strategy_wallet is not None:
            merged_config["strategy_wallet"] = strategy_wallet

        self.config: dict[str, Any] = merged_config
        self.deposited_amount = 0
        self.current_pool = None
        self.current_apy = 0
        self.current_route: str | None = None
        self._protocol_adapters: dict[str, Any] = {}

        # State tracking for deterministic token management
        # All tokens strategy might hold
        self.tracked_token_ids: set[str] = set()
        # token_id -> balance in wei
        self.tracked_balances: dict[str, int] = {}

        try:
            main_wallet_cfg = self.config.get("main_wallet")
            strategy_wallet_cfg = self.config.get("strategy_wallet")

            adapter_config = {
                "main_wallet": main_wallet_cfg or None,
                "strategy_wallet": strategy_wallet_cfg or None,
                "strategy": self.config,
            }

            strat_addr = (strategy_wallet_cfg or {}).get("address")
            main_addr = (main_wallet_cfg or {}).get("address")

            self.balance_adapter = BalanceAdapter(
                adapter_config,
                main_sign_callback=self.main_wallet_signing_callback,
                strategy_sign_callback=self.strategy_wallet_signing_callback,
                main_wallet_address=main_addr,
                strategy_wallet_address=strat_addr,
            )
            self.token_adapter = TokenAdapter()
            self.pool_adapter = PoolAdapter()
            self.brap_adapter = BRAPAdapter(
                adapter_config,
                sign_callback=self.strategy_wallet_signing_callback,
                wallet_address=strat_addr,
            )
        except Exception as e:
            logger.error(f"Failed to initialize strategy adapters: {e}")
            raise

    def _track_token(self, token_id: str, balance_wei: int = 0):
        if token_id:
            self.tracked_token_ids.add(token_id)
            if balance_wei > 0:
                self.tracked_balances[token_id] = balance_wei

    def _update_balance(self, token_id: str, balance_wei: int):
        if token_id:
            self.tracked_balances[token_id] = balance_wei
            if balance_wei > 0:
                self.tracked_token_ids.add(token_id)

    async def _refresh_tracked_balances(self):
        strategy_address = self._get_strategy_wallet_address()
        for token_id in self.tracked_token_ids:
            try:
                success, balance_wei = await self.balance_adapter.get_balance(
                    token_id=token_id,
                    wallet_address=strategy_address,
                )
                if success and balance_wei:
                    self.tracked_balances[token_id] = int(balance_wei)
                else:
                    self.tracked_balances[token_id] = 0
            except Exception as e:
                logger.warning(f"Failed to refresh balance for {token_id}: {e}")
                self.tracked_balances[token_id] = 0

    def _get_non_zero_tracked_tokens(self) -> list[tuple[str, int]]:
        return [
            (token_id, balance)
            for token_id, balance in self.tracked_balances.items()
            if balance > 0
        ]

    async def setup(self):
        logger.info("Starting StablecoinYieldStrategy setup")
        start_time = time.time()

        await super().setup()
        self.current_combined_apy_pct = 0.0

        try:
            logger.info("Fetching strategy net deposit from ledger")
            strategy_address = self._get_strategy_wallet_address()
            success, deposit_data = await self.ledger_adapter.get_strategy_net_deposit(
                wallet_address=strategy_address,
            )
            if success and deposit_data is not None:
                self.DEPOSIT_USDC = float(deposit_data)
                logger.info(f"Strategy net deposit: {self.DEPOSIT_USDC} USDC")
            else:
                logger.error(f"Failed to fetch strategy net deposit: {deposit_data}")
                self.DEPOSIT_USDC = 0
        except Exception as e:
            logger.error(f"Failed to fetch strategy net deposit: {e}")
            self.DEPOSIT_USDC = 0

        try:
            logger.info("Fetching USDC token information")
            success, self.usdc_token_info = await self.token_adapter.get_token(
                "usd-coin-base"
            )
            if not success:
                logger.warning("Failed to fetch USDC token info, using empty dict")
                self.usdc_token_info = {}
            else:
                logger.info(
                    f"USDC token info loaded: {self.usdc_token_info.get('symbol', 'Unknown')} on {self.usdc_token_info.get('chain', {}).get('name', 'Unknown')}"
                )
        except Exception as e:
            logger.error(f"Error fetching USDC token info: {e}")
            self.usdc_token_info = {}

        # Always track USDC as baseline token
        if self.usdc_token_info.get("token_id"):
            self._track_token(self.usdc_token_info.get("token_id"))

        self.current_pool = {
            "token_id": self.usdc_token_info.get("token_id"),
            "name": self.usdc_token_info.get("name"),
            "symbol": self.usdc_token_info.get("symbol"),
            "decimals": self.usdc_token_info.get("decimals", 18),
            "address": self.usdc_token_info.get("address"),
            "chain": self.usdc_token_info.get("chain", {"code": "base", "id": 8453}),
        }

        self.current_pool_data = None

        chain_code = "base"
        if self.current_pool and self.current_pool.get("chain"):
            chain_code = self.current_pool.get("chain").get("code", "base")

        try:
            logger.info(f"Fetching gas token for chain: {chain_code}")
            success, gas_token_data = await self.token_adapter.get_gas_token(chain_code)
            if success:
                self.gas_token = gas_token_data
                logger.info(
                    f"Gas token loaded: {gas_token_data.get('symbol', 'Unknown')}"
                )
                # Track gas token (but don't count it as a strategy asset)
                if self.gas_token.get("token_id"):
                    self._track_token(self.gas_token.get("token_id"))
            else:
                logger.warning("Failed to fetch gas token info, using empty dict")
                self.gas_token = {}
        except Exception as e:
            logger.error(f"Error fetching gas token info: {e}")
            self.gas_token = {}

        if not self.DEPOSIT_USDC:
            logger.info("No deposits found, setting current pool balance to 0")
            self.current_pool_balance = 0
            return

        try:
            logger.info("Fetching strategy transaction history to build state")
            success, txns_data = await self.ledger_adapter.get_strategy_transactions(
                wallet_address=self._get_strategy_wallet_address(),
            )
            if success:
                txns = [
                    txn
                    for txn in txns_data.get("transactions", [])
                    if txn.get("operation") != "DEPOSIT"
                ]
                logger.info(f"Found {len(txns)} non-deposit transactions")

                for txn in txns:
                    op_data = txn.get("op_data", {})
                    if op_data.get("to_token_id"):
                        self._track_token(op_data.get("to_token_id"))
                    if op_data.get("from_token_id"):
                        self._track_token(op_data.get("from_token_id"))

                logger.info(
                    f"Tracking {len(self.tracked_token_ids)} tokens from history"
                )
            else:
                logger.error(f"Failed to fetch strategy transactions: {txns_data}")
                txns = []
        except Exception as e:
            logger.error(f"Failed to fetch strategy transactions: {e}")
            txns = []

        if txns and txns[-1].get("operation") != "WITHDRAW":
            last_txn = txns[-1]
            pos = last_txn.get("op_data", {})
            if pos and pos.get("to_token_id"):
                success, token_info = await self.token_adapter.get_token(
                    pos.get("to_token_id")
                )
                if not success:
                    token_info = {}
                to_token_id = pos.get("to_token_id")
                ledger_adapter_name = pos.get("adapter", "")
                ledger_route = self.PROJECT_ALIASES.get(
                    ledger_adapter_name.lower()
                ) if ledger_adapter_name else None

                if token_info:
                    self.current_pool = {
                        "token_id": token_info.get("token_id"),
                        "name": token_info.get("name"),
                        "symbol": token_info.get("symbol"),
                        "decimals": token_info.get("decimals"),
                        "address": token_info.get("address"),
                        "chain": token_info.get("chain"),
                    }
                    if token_info.get("token_id"):
                        self._track_token(token_info.get("token_id"))
                elif to_token_id:
                    # Token API doesn't know this token (e.g. avUSDC vault
                    # token). Build minimal pool info from ledger data so
                    # the adapter route can still be reconstructed.
                    parts = to_token_id.split("_", 1)
                    chain_code = parts[0] if len(parts) == 2 else "base"
                    address = parts[1] if len(parts) == 2 else to_token_id
                    chain_id_map = {
                        "base": 8453, "ethereum": 1, "arbitrum": 42161,
                        "polygon": 137, "hyperevm": 999,
                    }
                    self.current_pool = {
                        "token_id": to_token_id,
                        "name": None,
                        "symbol": None,
                        "decimals": 6,
                        "address": address,
                        "chain": {
                            "id": chain_id_map.get(chain_code, 8453),
                            "code": chain_code,
                        },
                    }
                    self._track_token(to_token_id)
                    logger.info(
                        f"Token lookup failed for {to_token_id}, "
                        f"built minimal pool from ledger"
                    )

                if ledger_route:
                    self.current_route = ledger_route
                    logger.info(
                        f"Reconstructed route={ledger_route} from "
                        f"ledger adapter={ledger_adapter_name}"
                    )

                success, reports = await self.pool_adapter.get_pools_by_ids(
                    pool_ids=[self.current_pool.get("token_id")]
                )
                if success and reports.get("pools"):
                    self.current_pool_data = reports.get("pools", [])[0]
                    route = self._get_route_for_pool(self.current_pool_data)
                    if route:
                        self.current_route = route
                        logger.info(f"Reconstructed route={route} from pool project={self.current_pool_data.get('project')}")

        pool_ids = []
        pool_id = self.current_pool.get("token_id", None)
        if isinstance(pool_id, str):
            pool_ids.append(pool_id)

        pool_address = self.current_pool.get("address", None)
        pool_chain = self.current_pool.get("chain", None)
        chain_code = ((pool_chain or {}).get("code")) or None
        if isinstance(pool_address, str) and isinstance(chain_code, str):
            pool_ids.append(f"{chain_code.lower()}_{pool_address.lower()}")

        llama_report = None
        if pool_ids:
            success, pool_list_response = await self.pool_adapter.get_pools_by_ids(
                pool_ids=pool_ids
            )
            if success and isinstance(pool_list_response, dict):
                pools = pool_list_response.get("pools", [])
                # Search for matching pool by id or constructed identifier
                for identifier in pool_ids:
                    if not isinstance(identifier, str):
                        continue
                    identifier_lower = identifier.lower()
                    for pool in pools:
                        pool_id = pool.get("id", "").lower()
                        pool_address = pool.get("address", "").lower()
                        pool_chain_code = pool.get("chain_code", "").lower()
                        constructed_id = f"{pool_chain_code}_{pool_address}"
                        if (
                            pool_id == identifier_lower
                            or constructed_id == identifier_lower
                        ):
                            llama_report = pool
                            break
                    if llama_report:
                        break

        if self.current_pool_data is None and llama_report:
            self.current_pool_data = {"llama_report": llama_report}
            if not self.current_route:
                route = self._get_route_for_pool(llama_report)
                if route:
                    self.current_route = route
                    logger.info(f"Reconstructed route={route} from llama project={llama_report.get('project')}")

        if llama_report and llama_report.get("combined_apy_pct") is not None:
            self.current_combined_apy_pct = (
                llama_report.get("combined_apy_pct", 0) / 100
            )
        elif llama_report and llama_report.get("apy") is not None:
            self.current_combined_apy_pct = llama_report.get("apy", 0) / 100
        elif self.current_pool_data:
            apy_pct = self.current_pool_data.get("combined_apy_pct")
            if apy_pct is not None:
                self.current_combined_apy_pct = float(apy_pct) / 100
            else:
                apy_val = self.current_pool_data.get("apy", 0)
                self.current_combined_apy_pct = (
                    float(apy_val) / 100 if apy_val is not None else 0
                )

        pool_address = self.current_pool.get("address")
        chain_id = self.current_pool.get("chain", {}).get("id")
        user_address = self._get_strategy_wallet_address()
        if (
            pool_address
            and chain_id
            and user_address
            and pool_address != self.usdc_token_info.get("address")
        ):
            try:
                (
                    success,
                    current_pool_balance_raw,
                ) = await self.balance_adapter.get_balance(
                    token_address=pool_address,
                    wallet_address=user_address,
                    chain_id=chain_id,
                )
                self.current_pool_balance = current_pool_balance_raw if success else 0
            except Exception as e:
                logger.warning(f"Warning: Failed to get pool balance: {e}")
                self.current_pool_balance = 0
        else:
            self.current_pool_balance = 0

        baseline_token = (
            self.usdc_token_info
            if self.usdc_token_info.get("chain", {}).get("id")
            == self.current_pool.get("chain").get("id")
            else None
        )
        await self._refresh_tracked_balances()
        logger.info(
            f"Refreshed balances for {len(self.tracked_balances)} tracked tokens"
        )

        if (
            baseline_token
            and self.current_pool.get("token_id") != baseline_token.get("token_id")
            and self.current_pool_balance
        ):
            return

        # Fallback: Try to infer active pool from tracked tokens with balances
        inferred = await self._infer_active_pool_from_tracked_tokens()
        if inferred is not None:
            inferred_token, inferred_balance, inferred_entry = inferred
            self.current_pool = inferred_token
            self.current_pool_balance = inferred_balance
            if inferred_entry:
                self.current_pool_data = inferred_entry
                route = self._get_route_for_pool(inferred_entry)
                if route:
                    self.current_route = route
                llama_combined = inferred_entry.get("combined_apy_pct")
                llama_apy = inferred_entry.get("apy")
                if llama_combined is not None:
                    self.current_combined_apy_pct = float(llama_combined) / 100
                elif llama_apy is not None:
                    self.current_combined_apy_pct = float(llama_apy) / 100
            return

        # Fallback: query protocol adapters directly for a live position.
        # This catches cases where the token API doesn't know the vault
        # token (e.g. avUSDC) but the adapter can still read the position.
        detected_route = await self._detect_active_protocol_route()
        if detected_route:
            usd_val, assets_wei = await self._get_protocol_position_value()
            if assets_wei > 0:
                self.current_pool_balance = assets_wei
                # Try to fetch pool data for APY reporting
                pool_project = detected_route
                try:
                    ok, pool_data = await self.pool_adapter.get_pools(
                        chain_id=(self.usdc_token_info or {}).get(
                            "chain", {}
                        ).get("id", 8453)
                    )
                    if ok:
                        for p in pool_data.get("matches", []):
                            proj = (p.get("project") or "").lower()
                            alias = self.PROJECT_ALIASES.get(proj)
                            if alias == detected_route:
                                self.current_pool_data = p
                                apy_pct = p.get("combined_apy_pct") or p.get("apy") or 0
                                self.current_combined_apy_pct = float(apy_pct) / 100
                                # Update current_pool identity to match
                                _, pool_addr = self._extract_pool_address(p)
                                if pool_addr:
                                    self.current_pool = {
                                        "token_id": self.current_pool.get("token_id"),
                                        "name": p.get("symbol"),
                                        "symbol": p.get("symbol"),
                                        "decimals": self.current_pool.get("decimals", 6),
                                        "address": pool_addr,
                                        "chain": self.current_pool.get("chain"),
                                    }
                                logger.info(
                                    f"Matched {detected_route} pool: "
                                    f"APY={apy_pct:.2f}%"
                                )
                                break
                except Exception as e:
                    logger.warning(
                        f"Failed to fetch pool data for {detected_route}: {e}"
                    )
                logger.info(
                    f"Detected live {detected_route} position: "
                    f"assets={assets_wei}, usd={usd_val}"
                )
                return

        if self.usdc_token_info:
            status, raw_balance = await self.balance_adapter.get_balance(
                token_id=self.usdc_token_info.get("token_id"),
                wallet_address=self._get_strategy_wallet_address(),
            )
            if not status or not raw_balance:
                return
            try:
                balance_wei = int(raw_balance)
            except (TypeError, ValueError):
                return
            if balance_wei <= 0:
                return

            self.current_pool = self.usdc_token_info
            self.current_pool_balance = balance_wei
            self.current_combined_apy_pct = 0.0
            self.current_pool_data = None

            return

        elapsed_time = time.time() - start_time
        logger.info(
            f"StablecoinYieldStrategy setup completed in {elapsed_time:.2f} seconds"
        )

    def _sum_non_gas_balance_usd(self, balances: list[dict[str, Any]] | None) -> float:
        total_usd = 0.0
        for bal in balances or []:
            if self._is_gas_balance_entry(bal):
                continue
            usd_value = bal.get("balanceUSD")
            try:
                total_usd += float(usd_value or 0.0)
            except (TypeError, ValueError):
                continue
        return total_usd

    async def _infer_active_pool_from_tracked_tokens(self):
        try:
            await self._refresh_tracked_balances()

            usdc_token_id = self.usdc_token_info.get("token_id")
            gas_token_id = self.gas_token.get("token_id") if self.gas_token else None

            best_token_id = None
            best_balance_wei = 0

            for token_id, balance_wei in self.tracked_balances.items():
                if balance_wei <= 0:
                    continue
                if token_id == gas_token_id:
                    continue
                if token_id == usdc_token_id:
                    continue

                if balance_wei > best_balance_wei:
                    best_token_id = token_id
                    best_balance_wei = balance_wei

            if not best_token_id:
                return None

            success, token = await self.token_adapter.get_token(best_token_id)
            if not success:
                return None

            strategy_address = self._get_strategy_wallet_address()
            try:
                success, onchain_balance = await self.balance_adapter.get_balance(
                    token_id=token.get("token_id"),
                    wallet_address=strategy_address,
                )
                if success and onchain_balance:
                    best_balance_wei = int(onchain_balance)
            except Exception:
                pass

            logger.info(
                f"Inferred active pool: {token.get('symbol')} with balance {best_balance_wei}"
            )
            return token, best_balance_wei, None

        except Exception as e:
            logger.error(f"Failed to infer active pool from tracked tokens: {e}")
            return None

    def _is_gas_balance_entry(self, balance: dict[str, Any]) -> bool:
        if not self.gas_token:
            return False
        assert self.current_pool is not None

        token_id = balance.get("token_id")
        if (
            isinstance(token_id, str)
            and token_id.lower() == self.gas_token.get("token_id", "").lower()
        ):
            return True

        token_address = balance.get("tokenAddress")
        if isinstance(token_address, str):
            if token_address.lower() == self.gas_token.get("address", "").lower():
                return True

            network = (balance.get("network") or "").lower()
            chain_code = self.current_pool.get("chain", {}).get("code", "").lower()
            if (
                token_address.lower() == self.gas_token.get("address", "").lower()
                and network == chain_code
            ):
                return True

        return False

    async def deposit(
        self, main_token_amount: float = 0.0, gas_token_amount: float = 0.0
    ) -> StatusTuple:
        if main_token_amount == 0.0 and gas_token_amount == 0.0:
            return (
                False,
                "Either main_token_amount or gas_token_amount must be provided",
            )

        logger.info(
            f"Starting deposit process for {main_token_amount} USDC and {gas_token_amount} gas"
        )
        start_time = time.time()

        try:
            token_info = self.usdc_token_info
            current_pool = {
                "token_id": token_info.get("token_id"),
                "name": token_info.get("name"),
                "symbol": token_info.get("symbol"),
                "decimals": token_info.get("decimals"),
                "address": token_info.get("address"),
                "chain": token_info.get("chain"),
            }
            self.current_pool = current_pool
            gas_token_id = self.gas_token.get("token_id")
            logger.info(
                f"Current pool set to: {token_info.get('symbol')} on {token_info.get('chain', {}).get('name')}"
            )

            if main_token_amount > 0:
                logger.info("Checking main wallet USDC balance")
                (
                    main_usdc_status,
                    main_usdc_balance,
                ) = await self.balance_adapter.get_balance(
                    token_id=token_info.get("token_id"),
                    wallet_address=self._get_main_wallet_address(),
                )
                if main_usdc_status and main_usdc_balance is not None:
                    try:
                        available_main_usdc = float(main_usdc_balance) / (
                            10 ** current_pool.get("decimals")
                        )
                        logger.info(f"Main wallet USDC balance: {available_main_usdc}")
                        if available_main_usdc >= 0:
                            main_token_amount = min(
                                main_token_amount, available_main_usdc
                            )
                            logger.info(
                                f"Adjusted deposit amount to available balance: {main_token_amount}"
                            )
                    except Exception as e:
                        logger.warning(f"Error processing main wallet balance: {e}")
                else:
                    logger.warning("Could not fetch main wallet USDC balance")

                if main_token_amount < self.MIN_AMOUNT_USDC:
                    logger.warning(
                        f"Deposit amount {main_token_amount} below minimum {self.MIN_AMOUNT_USDC}"
                    )
                    return (
                        False,
                        f"Minimum deposit is {self.MIN_AMOUNT_USDC} USDC on Base. Received: {main_token_amount}",
                    )

            if gas_token_amount > 0:
                if gas_token_amount > self.GAS_MAXIMUM:
                    return (
                        False,
                        f"Gas token amount exceeds maximum configured gas buffer: {self.GAS_MAXIMUM}",
                    )

                logger.info("Checking main wallet gas token balance")
                gas_decimals = self.gas_token.get("decimals")
                gas_symbol = self.gas_token.get("symbol")
                (
                    _,
                    main_gas_raw,
                ) = await self.balance_adapter.get_balance(
                    token_id=gas_token_id,
                    wallet_address=self._get_main_wallet_address(),
                )
                main_gas_int = (
                    int(main_gas_raw)
                    if isinstance(main_gas_raw, int)
                    else int(float(main_gas_raw or 0))
                )
                main_gas_native = float(main_gas_int) / (10**gas_decimals)

                if main_gas_native < gas_token_amount:
                    return (
                        False,
                        f"Main wallet {gas_symbol} balance is less than the deposit amount: {main_gas_native} < {gas_token_amount}",
                    )

            if main_token_amount > 0:
                logger.info("Checking gas token balances for operations")
                gas_decimals = self.gas_token.get("decimals")
                gas_symbol = self.gas_token.get("symbol")
                (
                    _,
                    main_gas_raw,
                ) = await self.balance_adapter.get_balance(
                    token_id=gas_token_id,
                    wallet_address=self._get_main_wallet_address(),
                )
                (
                    _,
                    strategy_gas_raw,
                ) = await self.balance_adapter.get_balance(
                    token_id=gas_token_id,
                    wallet_address=self._get_strategy_wallet_address(),
                )
                main_gas_int = (
                    int(main_gas_raw)
                    if isinstance(main_gas_raw, int)
                    else int(float(main_gas_raw or 0))
                )
                strategy_gas_int = (
                    int(strategy_gas_raw)
                    if isinstance(strategy_gas_raw, int)
                    else int(float(strategy_gas_raw or 0))
                )
                main_gas_native = float(main_gas_int) / (10**gas_decimals)
                strategy_gas_native = float(strategy_gas_int) / (10**gas_decimals)
                total_gas = main_gas_native + strategy_gas_native
                logger.info(
                    f"Gas balances - Main: {main_gas_native} {gas_symbol}, Strategy: {strategy_gas_native} {gas_symbol}, Total: {total_gas} {gas_symbol}"
                )

                # Use provided gas_token_amount if available, otherwise ensure minimum
                required_gas = (
                    gas_token_amount if gas_token_amount > 0 else self.MIN_GAS
                )
                if total_gas < required_gas:
                    logger.warning(
                        f"Insufficient gas: {total_gas} < {required_gas} {gas_symbol}"
                    )
                    return (
                        False,
                        f"Need at least {required_gas} {gas_symbol} on Base for gas. You have: {total_gas}",
                    )

            if main_token_amount > 0:
                self.current_pool_balance = int(
                    main_token_amount * (10 ** current_pool.get("decimals"))
                )
                self.DEPOSIT_USDC = main_token_amount
                logger.info(f"Set deposit amount to {main_token_amount} USDC")

                logger.info("Initiating USDC transfer from main to strategy wallet")
                (
                    success,
                    msg,
                ) = await self.balance_adapter.move_from_main_wallet_to_strategy_wallet(
                    self.usdc_token_info.get("token_id"),
                    main_token_amount,
                    strategy_name=self.name,
                )
                if not success:
                    logger.error(f"USDC transfer failed: {msg}")
                    return (False, f"USDC transfer to strategy failed: {msg}")
                logger.info("USDC transfer completed successfully")

                self._track_token(self.usdc_token_info.get("token_id"))
                self._update_balance(
                    self.usdc_token_info.get("token_id"),
                    int(main_token_amount * (10 ** current_pool.get("decimals"))),
                )

            # Transfer gas if provided or if strategy needs top-up
            if gas_token_amount > 0:
                if main_token_amount == 0:
                    gas_symbol = self.gas_token.get("symbol")

                # Transfer the specified gas amount
                logger.info(
                    f"Transferring {gas_token_amount} {gas_symbol} from main wallet to strategy"
                )
                (
                    success,
                    msg,
                ) = await self.balance_adapter.move_from_main_wallet_to_strategy_wallet(
                    gas_token_id, gas_token_amount, strategy_name=self.name
                )
                if not success:
                    logger.error(f"Gas transfer failed: {msg}")
                    return (False, f"Gas transfer to strategy failed: {msg}")
                logger.info("Gas transfer completed successfully")
            elif main_token_amount > 0 and strategy_gas_native < self.MIN_GAS:
                # Auto-top-up to minimum if no gas amount specified and depositing main token
                top_up_amount = self.MIN_GAS - strategy_gas_native
                logger.info(
                    f"Strategy gas insufficient, transferring {top_up_amount} {gas_symbol} from main wallet"
                )
                (
                    success,
                    msg,
                ) = await self.balance_adapter.move_from_main_wallet_to_strategy_wallet(
                    gas_token_id, top_up_amount, strategy_name=self.name
                )
                if not success:
                    logger.error(f"Gas transfer failed: {msg}")
                    return (False, f"Gas transfer to strategy failed: {msg}")
                logger.info("Gas transfer completed successfully")

            elapsed_time = time.time() - start_time
            logger.info(f"Deposit completed successfully in {elapsed_time:.2f} seconds")
            return (
                True,
                "Deposit successful! Call update to open a position and start earning",
            )
        except Exception as e:
            logger.error(f"Deposit process failed: {e}")
            return (False, f"Deposit error: {e}")

    async def withdraw(self, amount: float | None = None, **kwargs) -> StatusTuple:
        logger.info(f"Starting withdrawal process for amount: {amount}")
        start_time = time.time()

        if not self.DEPOSIT_USDC:
            logger.warning("No deposits found, nothing to withdraw")
            return (
                False,
                "Nothing to withdraw from strategy, wallet should be empty already. If not, an error has happened please manually remove funds",
            )
        assert self.current_pool is not None
        logger.info("Fetching current pool balance")
        try:
            (
                _,
                self.current_pool_balance,
            ) = await self.balance_adapter.get_balance(
                token_address=self.current_pool.get("address"),
                wallet_address=self._get_strategy_wallet_address(),
                chain_id=self.current_pool.get("chain").get("id"),
            )
            logger.info(f"Current pool balance: {self.current_pool_balance}")
        except Exception as e:
            logger.error(f"Failed to fetch pool balance: {e}")
            self.current_pool_balance = 0

        # If current_route is unknown, probe protocol adapters for an active position
        if not self.current_route and self.DEPOSIT_USDC:
            await self._detect_active_protocol_route()

        chain_id = self.current_pool.get("chain", {}).get("id", 8453)

        # Check if we have a protocol adapter position (even when pool_balance is 0)
        if self.current_route and self.current_route in self.PROTOCOL_ROUTES:
            adapter_usd, adapter_assets = await self._get_protocol_position_value()
            if adapter_assets > 0 or self.current_pool_balance:
                withdraw_balance = self.current_pool_balance or adapter_assets
                logger.info(
                    f"Withdrawing via {self.current_route} adapter (balance={withdraw_balance})"
                )
                success, result = await self._withdraw_via_adapter(
                    self.current_route,
                    self.current_pool_data or {},
                    withdraw_balance,
                    chain_id,
                )
                if not success:
                    return (
                        False,
                        f"Failed to withdraw via {self.current_route}: {result}",
                    )
        elif (
            self.current_pool.get("token_id") != self.usdc_token_info.get("token_id")
            and self.current_pool_balance
        ):
            logger.info(
                f"Need to exit from {self.current_pool.get('symbol')} to USDC before withdrawal"
            )
            logger.info("Withdrawing via BRAP swap")
            success, quote = await self.brap_adapter.best_quote(
                from_token_address=self.current_pool.get("address"),
                to_token_address=self.usdc_token_info.get("address"),
                from_chain_id=chain_id,
                to_chain_id=self.usdc_token_info.get("chain").get("id"),
                from_address=self._get_strategy_wallet_address(),
                amount=str(self.current_pool_balance),
                retries=4,
            )
            if not success:
                return (
                    False,
                    "Could not swap tokens out due to market conditions (balances too small to move or slippage required is too high) please manually move funds out",
                )

            success, swap_result = await self.brap_adapter.swap_from_quote(
                self.current_pool,
                self.usdc_token_info,
                self._get_strategy_wallet_address(),
                quote,
                strategy_name=self.name,
            )
            if not success:
                return (
                    False,
                    f"Failed to unwind position via swap: {swap_result}",
                )

        await self._sweep_wallet(self.usdc_token_info)

        status, raw_balance = await self.balance_adapter.get_balance(
            token_id=self.usdc_token_info.get("token_id"),
            wallet_address=self._get_strategy_wallet_address(),
        )
        usdc_amount = 0.0
        if status and raw_balance:
            usdc_amount = float(raw_balance) / 10 ** self.usdc_token_info.get(
                "decimals"
            )

        gas_amount = 0.0
        if self.gas_token:
            status, raw_gas = await self.balance_adapter.get_balance(
                token_id=self.gas_token.get("token_id"),
                wallet_address=self._get_strategy_wallet_address(),
            )
            if status and raw_gas:
                gas_amount = float(raw_gas) / 10 ** self.gas_token.get("decimals")

        self.DEPOSIT_USDC = 0
        self.current_pool_balance = 0
        self.current_route = None

        elapsed_time = time.time() - start_time
        logger.info(f"Withdrawal completed successfully in {elapsed_time:.2f} seconds")

        strategy_address = self._get_strategy_wallet_address()
        breakdown_parts = [f"{usdc_amount:.2f} USDC"]
        if gas_amount > 0:
            breakdown_parts.append(
                f"{gas_amount:.6f} {self.gas_token.get('symbol', 'ETH')}"
            )

        return (
            True,
            f"Liquidated positions to strategy wallet ({strategy_address}): {', '.join(breakdown_parts)}. "
            f"Call exit() to transfer to main wallet.",
        )

    async def exit(self, **kwargs) -> StatusTuple:
        logger.info("EXIT: Transferring remaining funds to main wallet")

        strategy_address = self._get_strategy_wallet_address()
        main_address = self._get_main_wallet_address()

        if strategy_address.lower() == main_address.lower():
            return (True, "Main wallet is strategy wallet, no transfer needed")

        usdc_token_id = (
            self.usdc_token_info.get("token_id", "usd-coin-base")
            if isinstance(self.usdc_token_info, dict)
            else "usd-coin-base"
        )
        usdc_decimals = (
            self.usdc_token_info.get("decimals", 6)
            if isinstance(self.usdc_token_info, dict)
            else 6
        )
        gas_token_id = (
            self.gas_token.get("token_id", "ethereum-base")
            if isinstance(self.gas_token, dict)
            else "ethereum-base"
        )
        gas_decimals = (
            self.gas_token.get("decimals", 18)
            if isinstance(self.gas_token, dict)
            else 18
        )

        transferred_items = []

        usdc_ok, usdc_raw = await self.balance_adapter.get_balance(
            token_id=usdc_token_id,
            wallet_address=strategy_address,
        )
        if usdc_ok and isinstance(usdc_raw, int) and usdc_raw > 0:
            usdc_balance = float(usdc_raw) / (10**usdc_decimals)
            if usdc_balance > 1.0:
                logger.info(f"Transferring {usdc_balance:.2f} USDC to main wallet")
                (
                    success,
                    msg,
                ) = await self.balance_adapter.move_from_strategy_wallet_to_main_wallet(
                    token_id=usdc_token_id,
                    amount=usdc_balance,
                    strategy_name=self.name,
                    skip_ledger=False,
                )
                if success:
                    transferred_items.append(f"{usdc_balance:.2f} USDC")
                else:
                    logger.warning(f"USDC transfer failed: {msg}")

        eth_ok, eth_raw = await self.balance_adapter.get_balance(
            token_id=gas_token_id,
            wallet_address=strategy_address,
        )
        if eth_ok and isinstance(eth_raw, int) and eth_raw > 0:
            eth_balance = float(eth_raw) / (10**gas_decimals)
            tx_fee_reserve = 0.0002
            transferable_eth = eth_balance - tx_fee_reserve
            if transferable_eth > 0.0001:
                logger.info(f"Transferring {transferable_eth:.6f} ETH to main wallet")
                (
                    success,
                    msg,
                ) = await self.balance_adapter.move_from_strategy_wallet_to_main_wallet(
                    token_id=gas_token_id,
                    amount=transferable_eth,
                    strategy_name=self.name,
                    skip_ledger=False,
                )
                if success:
                    transferred_items.append(f"{transferable_eth:.6f} ETH")
                else:
                    logger.warning(f"ETH transfer failed: {msg}")

        if not transferred_items:
            return (True, "No funds to transfer to main wallet")

        return (True, f"Transferred to main wallet: {', '.join(transferred_items)}")

    async def _get_last_rotation_time(self, wallet_address: str) -> datetime | None:
        result = await self.ledger_adapter.get_strategy_latest_transactions(
            wallet_address=self._get_strategy_wallet_address(),
        )
        if not result[0]:
            return None
        for transaction in result[1].get("transactions", []):
            op_data = transaction.get("op_data", {})
            to_token = op_data.get("to_token_id")
            if (
                op_data.get("type") == "SWAP"
                and to_token
                and str(to_token).lower()
                not in [
                    "usd-coin-base",
                    "base_0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
                ]
            ):
                created_str = transaction.get("created")
                if not created_str:
                    continue
                try:
                    dt = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=UTC)
                    return dt
                except (ValueError, AttributeError):
                    continue
        return None

    async def update(self) -> StatusTuple:
        logger.info("Starting strategy update process")
        start_time = time.time()

        if not self.DEPOSIT_USDC:
            logger.warning("No deposits found, cannot update strategy")
            return (
                False,
                "Nothing has been deposited in this strategy, cannot update",
            )

        logger.info("Getting non-gas balances")
        non_gas_balances = await self._get_non_gas_balances()
        current_target = self.current_pool
        if current_target is None:
            current_target = self.usdc_token_info
            logger.info("No current pool set, using USDC as target")

        logger.info("Searching for best yield opportunities")
        should_deposit, pool_data = await self._find_best_pool()
        if not should_deposit:
            if (
                current_target
                and isinstance(current_target, dict)
                and await self._has_idle_assets(non_gas_balances, current_target)
            ):
                await self._sweep_wallet(current_target)
                await self._refresh_current_pool_balance()
                return (
                    True,
                    f"Consolidated assets into existing position {current_target.get('id')}",
                )

            if isinstance(pool_data, dict):
                message = pool_data.get(
                    "message", "No profitable pools found, staying in current pool"
                )
            else:
                message = (
                    str(pool_data)
                    if pool_data
                    else "No profitable pools found, staying in current pool"
                )
            return False, message

        if not isinstance(pool_data, dict):
            return (False, f"Invalid pool data format: {type(pool_data).__name__}")

        target_pool = pool_data.get("target_pool")
        target_pool_data = pool_data.get("target_pool_data")
        route = pool_data.get("route", "brap")
        brap_quote = pool_data.get("brap_quote")

        if not target_pool_data:
            return (False, "Missing required pool data for rebalancing")
        if route == "brap" and (not target_pool or not brap_quote):
            return (False, "Missing required pool data for BRAP rebalancing")

        gas_status, gas_message = await self._rebalance_gas(
            target_pool or self.usdc_token_info
        )
        if not gas_status:
            return (False, gas_message)

        previous_pool = self.current_pool

        last_rotation = await self._get_last_rotation_time(
            wallet_address=self._get_strategy_wallet_address(),
        )
        if (
            previous_pool
            and isinstance(previous_pool, dict)
            and previous_pool.get("token_id") != self.usdc_token_info.get("token_id")
            and last_rotation is not None
        ):
            now = datetime.now(UTC)
            if (now - last_rotation) < self.ROTATION_MIN_INTERVAL:
                elapsed = now - last_rotation
                remaining = self.ROTATION_MIN_INTERVAL - elapsed
                remaining_days_cooldown = max(0.0, remaining.total_seconds() / 86400)
                cooldown_notice = (
                    "Within 7-day cooldown; existing {coin} position retained. "
                    "≈{days:.1f} days until rotation window reopens."
                ).format(
                    coin=(
                        previous_pool.get("token_id", "unknown")
                        if isinstance(previous_pool, dict)
                        else "unknown"
                    ),
                    days=remaining_days_cooldown,
                )
                return (True, cooldown_notice)

        chain_id = (self.usdc_token_info or {}).get("chain", {}).get("id", 8453)

        if route != "brap" and route in self.PROTOCOL_ROUTES:
            # If currently in a non-USDC position, first withdraw back to USDC
            if (
                previous_pool
                and isinstance(previous_pool, dict)
                and previous_pool.get("token_id")
                != self.usdc_token_info.get("token_id")
            ):
                if not self.current_route and self.DEPOSIT_USDC:
                    await self._detect_active_protocol_route()
                if self.current_route and self.current_route in self.PROTOCOL_ROUTES:
                    _, adapter_assets = await self._get_protocol_position_value()
                    withdraw_balance = self.current_pool_balance or adapter_assets
                    w_ok, w_res = await self._withdraw_via_adapter(
                        self.current_route,
                        self.current_pool_data or {},
                        withdraw_balance,
                        chain_id,
                    )
                    if not w_ok:
                        return False, f"Failed to exit current position: {w_res}"
                else:
                    # Exit via BRAP swap back to USDC
                    ok, quote = await self.brap_adapter.best_quote(
                        from_token_address=previous_pool.get("address"),
                        to_token_address=self.usdc_token_info.get("address"),
                        from_chain_id=chain_id,
                        to_chain_id=chain_id,
                        from_address=self._get_strategy_wallet_address(),
                        amount=str(self.current_pool_balance),
                    )
                    if ok and isinstance(quote, dict):
                        await self.brap_adapter.swap_from_quote(
                            previous_pool,
                            self.usdc_token_info,
                            self._get_strategy_wallet_address(),
                            quote,
                            strategy_name=self.name,
                        )
                    else:
                        return False, "Failed to swap current position back to USDC"

            # Refresh USDC balance
            await self._refresh_tracked_balances()
            usdc_token_id = self.usdc_token_info.get("token_id")
            usdc_balance = self.tracked_balances.get(usdc_token_id, 0)
            if usdc_balance <= 0:
                return False, "No USDC balance available for deposit"

            logger.info(f"Depositing {usdc_balance} wei USDC via {route}")
            ok, result = await self._deposit_via_adapter(
                route, target_pool_data, usdc_balance, chain_id
            )
            if not ok:
                return False, f"Adapter deposit failed: {result}"

            # Record adapter deposit in ledger so setup() can reconstruct state
            vault_token_id = None
            if target_pool and target_pool.get("token_id"):
                vault_token_id = target_pool.get("token_id")
            elif target_pool and target_pool.get("address") and target_pool.get("chain"):
                chain_code = target_pool.get("chain", {}).get("code", "base")
                vault_token_id = f"{chain_code}_{target_pool.get('address')}"
            else:
                _, addr = self._extract_pool_address(target_pool_data)
                if addr:
                    vault_token_id = f"base_{addr}"

            if vault_token_id:
                usdc_token_id = self.usdc_token_info.get("token_id", "usd-coin-base")
                usdc_decimals = self.usdc_token_info.get("decimals", 6)
                deposit_usd = float(usdc_balance) / (10 ** usdc_decimals)
                try:
                    lend_record = SWAP_OP(
                        adapter=route,
                        from_token_id=usdc_token_id,
                        to_token_id=vault_token_id,
                        from_amount=str(usdc_balance),
                        to_amount="0",
                        from_amount_usd=deposit_usd,
                        to_amount_usd=deposit_usd,
                        transaction_chain_id=chain_id,
                    )
                    await self.ledger_adapter.record_operation(
                        wallet_address=self._get_strategy_wallet_address(),
                        operation_data=lend_record,
                        usd_value=deposit_usd,
                        strategy_name=self.name,
                    )
                except Exception as e:
                    logger.warning(f"Failed to record adapter deposit in ledger: {e}")

            self.current_route = route
            self.current_pool_data = target_pool_data
            # For adapter deposits, target_pool may be None if token lookup
            # failed — build minimal pool info from pool_data.
            if target_pool:
                self.current_pool = target_pool
                if target_pool.get("token_id"):
                    self._track_token(target_pool.get("token_id"))
            else:
                _, addr = self._extract_pool_address(target_pool_data)
                chain_code = "base"
                fallback_token_id = f"{chain_code}_{addr}" if addr else None
                self.current_pool = {
                    "token_id": fallback_token_id,
                    "address": addr,
                    "symbol": target_pool_data.get("symbol"),
                    "decimals": 6,
                    "chain": {"id": chain_id, "code": chain_code},
                }
                if fallback_token_id:
                    self._track_token(fallback_token_id)
        else:
            # BRAP swap path (existing)
            if not previous_pool:
                return (False, "No source pool available for swap")
            await self.brap_adapter.swap_from_quote(
                previous_pool,
                target_pool,
                self._get_strategy_wallet_address(),
                brap_quote,
                strategy_name=self.name,
            )
            self.current_route = "brap"

            if target_pool and target_pool.get("token_id"):
                self._track_token(target_pool.get("token_id"))
            self.current_pool = target_pool

        # Update APY tracking from pool data
        if self.current_pool and self.current_pool.get("token_id"):
            success, pool_reports = await self.pool_adapter.get_pools_by_ids(
                pool_ids=[self.current_pool.get("token_id")]
            )
            if success and pool_reports.get("pools"):
                self.current_pool_data = pool_reports.get("pools", [])[0]
        if self.current_pool_data:
            apy_pct = self.current_pool_data.get("combined_apy_pct")
            if apy_pct is not None:
                self.current_combined_apy_pct = float(apy_pct) / 100
            else:
                apy_val = self.current_pool_data.get("apy", 0)
                self.current_combined_apy_pct = (
                    float(apy_val) / 100 if apy_val is not None else 0
                )
        else:
            self.current_combined_apy_pct = (
                target_pool_data.get("combined_apy_pct", 0) / 100
                if target_pool_data
                else 0
            )

        if route == "brap" and brap_quote and isinstance(brap_quote, dict):
            output_amount = brap_quote.get("output_amount")
            self.current_pool_balance = (
                int(output_amount) if output_amount is not None else 0
            )
        else:
            # For adapter deposits, refresh balance from chain
            await self._refresh_tracked_balances()

        await asyncio.sleep(2)
        if target_pool:
            await self._sweep_wallet(target_pool)
        await self._refresh_current_pool_balance()

        elapsed_time = time.time() - start_time
        logger.info(
            f"Strategy update completed successfully in {elapsed_time:.2f} seconds"
        )
        return (True, "Updated successfully")

    async def _refresh_current_pool_balance(self):
        pool = self.current_pool
        if not pool or pool.get("chain") is None:
            return

        strategy_address = self._get_strategy_wallet_address()
        try:
            (
                _,
                refreshed_pool_balance,
            ) = await self.balance_adapter.get_balance(
                token_address=pool.get("address"),
                wallet_address=strategy_address,
                chain_id=pool.get("chain").get("id"),
            )
            self.current_pool_balance = int(refreshed_pool_balance)
        except Exception:
            pass

    async def _query_protocol_position(
        self, route: str
    ) -> tuple[float, int]:
        """Query a single protocol adapter for position value.

        Returns (usd_value, underlying_assets_wei).
        """
        strategy_address = self._get_strategy_wallet_address()
        chain_id = (self.usdc_token_info or {}).get("chain", {}).get("id", 8453)
        adapter = self._get_protocol_adapter(route)

        if route == "avantis":
            ok, state = await adapter.get_full_user_state(
                account=strategy_address, include_usd=True
            )
            if ok and isinstance(state, dict):
                usd = state.get("usd_value") or 0.0
                positions = state.get("positions", [])
                assets = sum(p.get("assets", 0) for p in positions)
                return float(usd), assets

        elif route == "moonwell":
            ok, state = await adapter.get_full_user_state(
                account=strategy_address, include_usd=True
            )
            if ok and isinstance(state, dict):
                totals = state.get("totalsUsd", {})
                usd = totals.get("net", 0.0)
                positions = state.get("positions", [])
                supplied = sum(
                    p.get("suppliedUnderlying", 0) for p in positions
                )
                return float(usd), supplied

        elif route == "aave-v3":
            ok, state = await adapter.get_full_user_state(
                account=strategy_address, include_rewards=False
            )
            if ok and isinstance(state, dict):
                positions = state.get("positions", [])
                usd = sum(
                    p.get("supply_usd", 0.0) - p.get("variable_borrow_usd", 0.0)
                    for p in positions
                )
                supplied = sum(p.get("supply_raw", 0) for p in positions)
                return float(usd), supplied

        elif route == "morpho":
            ok, state = await adapter.get_full_user_state(
                account=strategy_address
            )
            if ok and isinstance(state, dict):
                positions = state.get("positions", [])
                supply = sum(
                    p.get("state", {}).get("supplyShares", 0)
                    for p in positions
                )
                return 0.0, supply

        elif route == "euler":
            ok, state = await adapter.get_full_user_state(
                chain_id=chain_id, account=strategy_address
            )
            if ok and isinstance(state, dict):
                positions = state.get("positions", [])
                assets = sum(p.get("assets", 0) for p in positions)
                return 0.0, assets

        return 0.0, 0

    async def _detect_active_protocol_route(self) -> str | None:
        """Scan all protocol adapters to find which one holds an active position.

        Sets self.current_route if a position is found. Returns the route name or None.
        """
        for route in self.PROTOCOL_ROUTES:
            try:
                usd, assets = await self._query_protocol_position(route)
                if usd > 0 or assets > 0:
                    logger.info(
                        f"Detected active position in {route}: usd={usd}, assets={assets}"
                    )
                    self.current_route = route
                    return route
            except Exception as e:
                logger.debug(f"No position found in {route}: {e}")
        return None

    async def _get_protocol_position_value(self) -> tuple[float, int]:
        """Query the active protocol adapter for position USD value and underlying asset balance.

        Returns (usd_value, underlying_assets_wei). Falls back to (0.0, 0) on failure.
        """
        route = self.current_route
        if not route or route not in self.PROTOCOL_ROUTES:
            return 0.0, 0

        try:
            return await self._query_protocol_position(route)
        except Exception as e:
            logger.warning(f"Failed to query {route} adapter for position: {e}")

        return 0.0, 0

    async def _sweep_wallet(self, target_token):
        await self._refresh_tracked_balances()

        target_token_id = target_token.get("token_id")
        target_chain = target_token.get("chain").get("code", "").lower()
        target_address = target_token.get("address", "").lower()
        gas_token_id = self.gas_token.get("token_id") if self.gas_token else None

        for token_id, balance_wei in list(self.tracked_balances.items()):
            if balance_wei <= 0:
                continue

            if token_id == gas_token_id:
                continue

            if token_id == target_token_id:
                continue

            try:
                success, fresh_balance = await self.balance_adapter.get_balance(
                    token_id=token_id,
                    wallet_address=self._get_strategy_wallet_address(),
                )
                if not success or not fresh_balance or int(fresh_balance) <= 0:
                    self._update_balance(token_id, 0)
                    continue

                balance_wei = int(fresh_balance)
            except Exception:
                continue

            # Use the coingecko-style token ID for swap (not address format)
            target_token_id_for_swap = target_token_id

            try:
                logger.info(
                    f"Sweeping {token_id} (balance: {balance_wei}) to {target_token_id}"
                )
                success, msg = await self.brap_adapter.swap_from_token_ids(
                    token_id,
                    target_token_id_for_swap,
                    self._get_strategy_wallet_address(),
                    str(balance_wei),
                    strategy_name=self.name,
                )
                if success:
                    self._update_balance(token_id, 0)
                    logger.info(f"Successfully swept {token_id} to {target_token_id}")
                else:
                    logger.warning(f"Failed to sweep {token_id}: {msg}")
            except Exception as e:
                logger.error(f"Error sweeping {token_id}: {e}")
                continue

        self._track_token(target_token_id)
        try:
            success, target_balance = await self.balance_adapter.get_balance(
                token_id=target_token_id,
                wallet_address=self._get_strategy_wallet_address(),
            )
            if success and target_balance:
                self._update_balance(target_token_id, int(target_balance))
        except Exception:
            pass

    async def _rebalance_gas(self, target_pool) -> tuple[bool, str]:
        if self.gas_token.get("chain").get("id") != target_pool.get("chain").get("id"):
            return False, "Unsupported chain for gas management."

        # TODO: do we need to categorize strategy wallet addresses?
        strategy_address = self._get_strategy_wallet_address()

        required_gas = int(self.MIN_GAS * (10 ** self.gas_token.get("decimals")))
        _, current_gas = await self.balance_adapter.get_balance(
            token_id=self.gas_token.get("token_id"),
            wallet_address=strategy_address,
        )
        if current_gas >= required_gas:
            return True, "Enough gas balance found."

        current_native = float(current_gas) / 10 ** self.gas_token.get("decimals")
        shortfall = max(self.MIN_GAS - current_native, 0)

        return (
            False,
            f"Strategy wallet does not have enough gas. Shortfall: {shortfall} {self.gas_token.get('symbol')}",
        )

    async def _has_idle_assets(self, balances, target_token) -> bool:
        for balance in balances:
            if self._balance_matches_token(balance, target_token):
                continue
            amount = balance.get("_amount_wei")
            if isinstance(amount, int) and amount > 0:
                return True
        return False

    def _balance_matches_token(self, balance, token) -> bool:
        token_id = balance.get("token_id")
        if (
            isinstance(token_id, str)
            and token_id.lower() == token.get("token_id").lower()
        ):
            return True

        token_address = balance.get("tokenAddress")
        if not isinstance(token_address, str):
            return False

        network = (balance.get("network") or "").lower()
        chain_names = {
            getattr(token.get("chain"), "name", "").lower(),
            getattr(token.get("chain"), "code", "").lower(),
        }

        return network in chain_names and token_address.lower() == token.address.lower()

    async def _get_pool_usd_value(self, token, amount):
        return await self.token_adapter.get_amount_usd(
            token_id=token.get("token_id"),
            raw_amount=amount,
            decimals=token.get("decimals", 18),
        )

    async def _get_non_gas_balances(self) -> list[dict[str, Any]]:
        await self._refresh_tracked_balances()

        gas_token_id = self.gas_token.get("token_id") if self.gas_token else None
        results = []

        for token_id, balance_wei in self.tracked_balances.items():
            if token_id == gas_token_id:
                continue

            if balance_wei <= 0:
                continue

            try:
                success, token_info = await self.token_adapter.get_token(token_id)
                if not success or not token_info or isinstance(token_info, str):
                    continue

                results.append(
                    {
                        "token_id": token_id,
                        "tokenAddress": token_info.get("address"),
                        "network": token_info.get("chain", {}).get("code", "").upper(),
                        "_amount_wei": balance_wei,
                    }
                )
            except Exception as e:
                logger.warning(f"Failed to get token info for {token_id}: {e}")
                continue

        return results

    # ------------------------------------------------------------------
    # Protocol adapter routing
    # ------------------------------------------------------------------

    def _get_protocol_adapter(self, route: str) -> Any:
        """Lazily init and cache a protocol adapter by route name."""
        if route in self._protocol_adapters:
            return self._protocol_adapters[route]

        adapter_cls = self.PROTOCOL_ROUTES.get(route)
        if adapter_cls is None:
            raise ValueError(f"No adapter registered for route: {route}")

        strat_cfg = {
            "strategy_wallet": self.config.get("strategy_wallet"),
            "strategy": self.config,
        }
        strat_addr = (self.config.get("strategy_wallet") or {}).get("address")
        sign_cb = self.strategy_wallet_signing_callback

        if adapter_cls is EulerV2Adapter:
            adapter = adapter_cls(
                config=strat_cfg,
                strategy_wallet_signing_callback=sign_cb,
            )
        else:
            adapter = adapter_cls(
                config=strat_cfg,
                sign_callback=sign_cb,
                wallet_address=strat_addr,
            )
        self._protocol_adapters[route] = adapter
        return adapter

    # Map pool API project names to our PROTOCOL_ROUTES keys.
    # The pool API uses suffixed names like "morpho-v1", "moonwell-lending".
    PROJECT_ALIASES: dict[str, str] = {
        "morpho": "morpho",
        "morpho-v1": "morpho",
        "morpho-blue": "morpho",
        "moonwell": "moonwell",
        "moonwell-lending": "moonwell",
        "aave-v3": "aave-v3",
        "avantis": "avantis",
        "euler": "euler",
        "euler-v2": "euler",
    }

    def _get_route_for_pool(self, pool_data: dict[str, Any]) -> str | None:
        project = (pool_data.get("project") or "").lower()
        return self.PROJECT_ALIASES.get(project)

    async def _deposit_via_adapter(
        self,
        route: str,
        pool_data: dict[str, Any],
        amount_wei: int,
        chain_id: int,
    ) -> tuple[bool, Any]:
        """Deposit USDC into a pool via its native protocol adapter."""
        adapter = self._get_protocol_adapter(route)
        usdc_address = self.usdc_token_info.get("address")
        _, pool_address = self._extract_pool_address(pool_data)

        if route == "morpho":
            return await self._deposit_morpho(
                adapter, pool_data, pool_address, amount_wei, chain_id
            )
        elif route == "moonwell":
            return await self._deposit_moonwell(
                adapter, pool_data, usdc_address, amount_wei
            )
        elif route == "aave-v3":
            return await adapter.lend(
                underlying_token=usdc_address,
                qty=amount_wei,
                chain_id=chain_id,
            )
        elif route == "avantis":
            return await adapter.deposit(amount=amount_wei)
        elif route == "euler":
            if not pool_address:
                return False, "Cannot determine Euler vault address"
            return await adapter.lend(
                chain_id=chain_id, vault=pool_address, amount=amount_wei
            )
        return False, f"No deposit handler for route: {route}"

    async def _withdraw_via_adapter(
        self,
        route: str,
        pool_data: dict[str, Any],
        amount_wei: int,
        chain_id: int,
    ) -> tuple[bool, Any]:
        """Withdraw from a pool via its native protocol adapter."""
        adapter = self._get_protocol_adapter(route)
        usdc_address = self.usdc_token_info.get("address")
        _, pool_address = self._extract_pool_address(pool_data)

        if route == "morpho":
            return await self._withdraw_morpho(
                adapter, pool_data, pool_address, amount_wei, chain_id
            )
        elif route == "moonwell":
            return await self._withdraw_moonwell(adapter, pool_data, amount_wei)
        elif route == "aave-v3":
            return await adapter.withdraw_lend(
                underlying_token=usdc_address,
                qty=amount_wei,
                chain_id=chain_id,
            )
        elif route == "avantis":
            return await adapter.withdraw(amount=amount_wei, redeem_full=True)
        elif route == "euler":
            if not pool_address:
                return False, "Cannot determine Euler vault address"
            return await adapter.withdraw(
                chain_id=chain_id, vault=pool_address, amount=amount_wei
            )
        return False, f"No withdraw handler for route: {route}"

    async def _deposit_morpho(
        self,
        adapter: MorphoAdapter,
        pool_data: dict[str, Any],
        pool_address: str | None,
        amount_wei: int,
        chain_id: int,
    ) -> tuple[bool, Any]:
        """Route Morpho deposits to vault_deposit or lend depending on pool type."""
        pool_id = pool_data.get("pool_id", "") or pool_data.get("id", "")
        # Morpho vaults have pool IDs starting with "vault-"
        if pool_id.startswith("vault-") and pool_address:
            return await adapter.vault_deposit(
                chain_id=chain_id, vault_address=pool_address, assets=amount_wei
            )
        # Morpho Blue markets use market_unique_key
        # The pool_id for blue markets looks like "blue-0x<market_key>-<chain>"
        if pool_id.startswith("blue-"):
            market_key = pool_id.split("-", 1)[1]
            # Strip trailing chain suffix (e.g. "-base")
            if "-" in market_key:
                market_key = market_key.rsplit("-", 1)[0]
            return await adapter.lend(
                chain_id=chain_id, market_unique_key=market_key, qty=amount_wei
            )
        # Fallback: if pool has a valid address, try vault deposit
        if pool_address:
            return await adapter.vault_deposit(
                chain_id=chain_id, vault_address=pool_address, assets=amount_wei
            )
        return False, "Cannot determine Morpho deposit method"

    async def _withdraw_morpho(
        self,
        adapter: MorphoAdapter,
        pool_data: dict[str, Any],
        pool_address: str | None,
        amount_wei: int,
        chain_id: int,
    ) -> tuple[bool, Any]:
        pool_id = pool_data.get("pool_id", "") or pool_data.get("id", "")
        if pool_id.startswith("vault-") and pool_address:
            return await adapter.vault_redeem(
                chain_id=chain_id, vault_address=pool_address, shares=amount_wei
            )
        if pool_id.startswith("blue-"):
            market_key = pool_id.split("-", 1)[1]
            if "-" in market_key:
                market_key = market_key.rsplit("-", 1)[0]
            return await adapter.withdraw(
                chain_id=chain_id, market_unique_key=market_key, qty=amount_wei
            )
        if pool_address:
            return await adapter.vault_redeem(
                chain_id=chain_id, vault_address=pool_address, shares=amount_wei
            )
        return False, "Cannot determine Morpho withdraw method"

    async def _deposit_moonwell(
        self,
        adapter: MoonwellAdapter,
        pool_data: dict[str, Any],
        usdc_address: str,
        amount_wei: int,
    ) -> tuple[bool, Any]:
        """Resolve mToken from Moonwell markets and deposit."""
        _, pool_address = self._extract_pool_address(pool_data)
        # pool_address might be the mToken itself
        if pool_address:
            return await adapter.lend(
                mtoken=pool_address,
                underlying_token=usdc_address,
                amount=amount_wei,
            )
        # Fallback: search markets for USDC
        ok, markets = await adapter.get_all_markets()
        if ok and isinstance(markets, list):
            for m in markets:
                if (m.get("underlying_address") or "").lower() == usdc_address.lower():
                    return await adapter.lend(
                        mtoken=m.get("mtoken_address"),
                        underlying_token=usdc_address,
                        amount=amount_wei,
                    )
        return False, "Cannot find Moonwell USDC market"

    async def _withdraw_moonwell(
        self,
        adapter: MoonwellAdapter,
        pool_data: dict[str, Any],
        amount_wei: int,
    ) -> tuple[bool, Any]:
        _, pool_address = self._extract_pool_address(pool_data)
        if pool_address:
            return await adapter.redeem(mtoken=pool_address, amount=amount_wei)
        return False, "Cannot determine Moonwell mToken for withdraw"

    @staticmethod
    def _extract_pool_address(pool: dict[str, Any]) -> tuple[str | None, str | None]:
        """Extract (chain_code, address) from pool data.

        Pool API returns non-standard formats for some protocols:
          - Morpho vaults: address="morpho", chain_code="vault-v2-0xbeeff...-base"
          - Morpho blue:   address="morpho", chain_code="blue-0x1a3e69...-base"
          - Avantis:        address="avantis", chain_code="0x9447...-base"
          - Aura:           address="0x7ab...", chain_code="aura"

        Returns the real EVM address and chain code when possible.
        """
        address = pool.get("address", "")
        chain_code = pool.get("chain_code", "")

        # Already well-formed
        if address.startswith("0x") and len(address) == 42 and chain_code.isalpha():
            return chain_code, address

        # Address is a protocol name (e.g. "morpho", "avantis") —
        # try to extract real address + chain from chain_code.
        addr_match = re.search(r"(0x[0-9a-fA-F]{40})", chain_code)
        if addr_match:
            real_address = addr_match.group(1)
            # Chain code is typically the last segment: "vault-v2-0x...-base" → "base"
            tail = chain_code[addr_match.end() :]
            if tail.startswith("-") and tail[1:].isalpha():
                return tail[1:], real_address
            # Fallback: chain_code starts with address "0x...-base"
            head = chain_code[: addr_match.start()].rstrip("-")
            if not head:
                # e.g. "0x944766...-base" — chain is after the address
                pass
            return None, real_address

        # chain_code is a protocol name (e.g. "aura") but address is valid
        if address.startswith("0x") and len(address) == 42:
            return None, address

        return None, None

    @staticmethod
    def _effective_apy_pct(pool: dict[str, Any], max_reward_ratio: float) -> float:
        """Return the APY that the strategy can actually realise.

        Rules:
        1. If ``apyBase`` is None the yield composition is unknown (common for
           wrapper vaults that inherit an underlying APY). Unknown composition
           → 0 effective APY (we can't verify what's natively accrued).
        2. If external reward tokens account for more than *max_reward_ratio*
           of the advertised combined APY, fall back to base APY only — reward
           tokens may be non-tradeable, illiquid, or require manual claiming.
        3. Otherwise return the full combined APY.
        """
        combined = pool.get("combined_apy_pct") or pool.get("apy") or 0.0
        raw_base = pool.get("apyBase")
        reward = pool.get("apyReward") or 0.0
        has_reward_tokens = bool(pool.get("rewardTokens"))

        # Unknown base yield — wrapper vault or missing data
        if raw_base is None and reward == 0 and pool.get("underlying_apy_pct"):
            return 0.0

        base = raw_base or 0.0

        if has_reward_tokens and combined > 0 and reward / combined > max_reward_ratio:
            return base
        return combined

    async def _find_best_pool(self) -> tuple[bool, dict[str, Any]]:
        chain_id = (self.usdc_token_info or {}).get("chain", {}).get("id")
        if chain_id is None:
            chain_id = 8453
        success, llama_data = await self.pool_adapter.get_pools(chain_id=chain_id)
        if not success or isinstance(llama_data, str):
            return False, {"message": f"Failed to fetch Llama data: {llama_data}"}

        # chain_id filter is applied by get_pools() at the API level,
        # so no need for a local network/chain_code check.
        # Pendle pools are excluded — PT/YT/LP positions have maturity
        # constraints and can't be exited freely without loss.
        # NFT-based LP / gauge-staking projects (EXCLUDED_PROJECTS) are
        # excluded because the strategy enters positions via BRAP/Enso
        # ERC-20 swaps and cannot provision CL NFTs or stake in gauges.
        llama_pools = [
            pool
            for pool in llama_data.get("matches", [])
            if (pool.get("stablecoin") or is_usd_pool_symbol(pool.get("symbol", "")))
            and pool.get("ilRisk", "no") == "no"
            and (pool.get("tvlUsd") or 0) > self.MIN_TVL
            and self._effective_apy_pct(pool, self.MAX_REWARD_RATIO) > self.DUST_APY
            and is_usd_pool_symbol(pool.get("symbol", ""))
            and not is_pt_symbol(pool.get("symbol", ""))
            and (pool.get("project") or "").lower() != "pendle"
            and (pool.get("project") or "").lower() not in self.EXCLUDED_PROJECTS
        ]
        llama_pools = sorted(
            llama_pools,
            key=lambda pool: self._effective_apy_pct(pool, self.MAX_REWARD_RATIO),
            reverse=True,
        )
        if not llama_pools:
            return False, {"message": "No suitable pools found."}

        assert self.current_pool is not None
        for candidate in llama_pools[: self.SEARCH_DEPTH]:
            real_chain, real_addr = self._extract_pool_address(candidate)
            current_addr = (self.current_pool.get("address") or "").lower()
            if real_addr and real_addr.lower() == current_addr:
                return False, {"message": "Already in the best pool, no action needed."}

            route = self._get_route_for_pool(candidate)

            # Adapter-routed pool — no BRAP quote needed, just need token info
            if route:
                try:
                    target_status, target_pool = False, None
                    if real_chain and real_addr:
                        target_status, target_pool = (
                            await self.token_adapter.get_token(
                                f"{real_chain}_{real_addr}"
                            )
                        )
                        if not target_status and real_addr.startswith("0x"):
                            target_status, target_pool = (
                                await self.token_adapter.get_token(
                                    real_addr, chain_id=chain_id
                                )
                            )
                    elif real_addr:
                        usdc_chain = (self.usdc_token_info or {}).get(
                            "chain", {}
                        ).get("code", "base")
                        target_status, target_pool = (
                            await self.token_adapter.get_token(
                                f"{usdc_chain}_{real_addr}"
                            )
                        )
                        if not target_status and real_addr.startswith("0x"):
                            target_status, target_pool = (
                                await self.token_adapter.get_token(
                                    real_addr, chain_id=chain_id
                                )
                            )
                    # For adapter routes, token lookup failure is OK — we can
                    # still deposit via the adapter using pool_data alone.
                    # Ensure target_pool is None (not an error string) on failure.
                    if not target_status:
                        target_pool = None
                    eff_apy = self._effective_apy_pct(
                        candidate, self.MAX_REWARD_RATIO
                    )
                    logger.info(
                        f"Adapter route '{route}' for "
                        f"{candidate.get('symbol')} "
                        f"effective APY={eff_apy:.2f}% "
                        f"(combined={candidate.get('combined_apy_pct', 0):.2f}%)"
                    )
                    return True, {
                        "target_pool": target_pool,
                        "target_pool_data": candidate,
                        "route": route,
                    }
                except Exception as e:
                    logger.error(f"Error evaluating adapter route {route}: {e}")
                    continue

            # BRAP-routed pool — need token lookup + swap quote
            try:
                target_status, target_pool = False, None
                if real_chain and real_addr:
                    chain_scoped_id = f"{real_chain}_{real_addr}"
                    target_status, target_pool = (
                        await self.token_adapter.get_token(chain_scoped_id)
                    )
                    if not target_status and real_addr.startswith("0x"):
                        target_status, target_pool = (
                            await self.token_adapter.get_token(
                                real_addr, chain_id=chain_id
                            )
                        )
                elif real_addr and not real_chain:
                    usdc_chain = (self.usdc_token_info or {}).get(
                        "chain", {}
                    ).get("code", "base")
                    chain_scoped_id = f"{usdc_chain}_{real_addr}"
                    target_status, target_pool = (
                        await self.token_adapter.get_token(chain_scoped_id)
                    )
                    if not target_status and real_addr.startswith("0x"):
                        target_status, target_pool = (
                            await self.token_adapter.get_token(
                                real_addr, chain_id=chain_id
                            )
                        )
                if not target_status and candidate.get("token_id"):
                    target_status, target_pool = (
                        await self.token_adapter.get_token(
                            query=candidate.get("token_id")
                        )
                    )
                if not target_status and candidate.get("pool_id"):
                    target_status, target_pool = (
                        await self.token_adapter.get_token(
                            query=candidate.get("pool_id")
                        )
                    )
                if not target_status:
                    continue
            except Exception as e:
                logger.error(f"Error getting target pool: {e}")
                continue

            # current_pool_balance is already in raw units (wei)
            brap_quote = await self._search(
                candidate,
                self.current_pool,
                target_pool,
                self.current_combined_apy_pct,
                int(self.current_pool_balance),
            )
            if brap_quote:
                return True, {
                    "target_pool": target_pool,
                    "target_pool_data": candidate,
                    "route": "brap",
                    "brap_quote": brap_quote,
                }

        return False, {"message": "No suitable pools found after searching."}

    async def _search(
        self,
        pool_data,
        current_token,
        token,
        current_combined_apy_pct,
        current_token_balance,
    ):
        if token is None or current_token is None:
            return None
        if token is None or token.get("chain") is None:
            return None
        if current_token is None or current_token.get("chain") is None:
            return None

        try:
            apy_pct = self._effective_apy_pct(pool_data, self.MAX_REWARD_RATIO)
            combined_apy_pct = float(apy_pct) / 100
            success, best_quote = await self.brap_adapter.best_quote(
                from_token_address=current_token.get("address"),
                to_token_address=token.get("address"),
                from_chain_id=current_token.get("chain").get("id"),
                to_chain_id=token.get("chain").get("id"),
                from_address=self._get_strategy_wallet_address(),
                amount=str(current_token_balance),
            )
            if not success or not isinstance(best_quote, dict):
                return None

            target_pool_usd_val = await self._get_pool_usd_value(
                token, best_quote.get("output_amount")
            )

            if current_token.get("token_id") != self.usdc_token_info.get("token_id"):
                current_pool_usd_val = await self._get_pool_usd_value(
                    current_token, best_quote.get("input_amount")
                )
            else:
                current_pool_usd_val = float(
                    float(self.current_pool_balance)
                    / (10 ** current_token.get("decimals"))
                )

            gas_cost = await self._get_gas_value(best_quote.get("input_amount"))
            fee_cost = (current_pool_usd_val - target_pool_usd_val) + gas_cost
            delta_combined_apy_pct = combined_apy_pct - current_combined_apy_pct

            if delta_combined_apy_pct < self.MINIMUM_APY_IMPROVEMENT:
                return None

            estimated_profit = (
                self.MINIMUM_DAYS_UNTIL_PROFIT
                * ((delta_combined_apy_pct * current_pool_usd_val) / 365)
                - fee_cost
            )

            if estimated_profit > 0:
                best_quote["from_amount_usd"] = current_pool_usd_val
                best_quote["to_amount_usd"] = target_pool_usd_val
                return best_quote

        except Exception:
            return {}

    async def _get_gas_value(self, amount):
        token = self.gas_token
        success, gas_price_data = await self.token_adapter.get_token_price(
            token.get("token_id")
        )
        if not success:
            return 0.0
        gas_price = gas_price_data.get("current_price", 0.0)
        return float(gas_price) * float(amount) / (10 ** token.get("decimals"))

    async def _status(self) -> StatusDict:
        gas_success, gas_balance_wei = await self.balance_adapter.get_balance(
            token_id=self.gas_token.get("token_id"),
            wallet_address=self._get_strategy_wallet_address(),
        )
        gas_balance = (
            float(gas_balance_wei) / (10 ** self.gas_token.get("decimals"))
            if gas_success
            else 0.0
        )

        if not self.DEPOSIT_USDC:
            status_payload = {
                "info": "No recorded strategy deposits.",
                "idle_usd": 0.0,
            }

            return StatusDict(
                portfolio_value=0.0,
                net_deposit=0,
                strategy_status=status_payload,
                gas_available=gas_balance,
                gassed_up=gas_balance >= self.GAS_MAXIMUM * self.GAS_SAFETY_FRACTION,
            )

        # Refresh tracked balances
        await self._refresh_tracked_balances()

        total_value = 0.0
        gas_token_id = self.gas_token.get("token_id") if self.gas_token else None

        for token_id, balance_wei in self.tracked_balances.items():
            if token_id == gas_token_id:
                continue
            if balance_wei <= 0:
                continue

            try:
                success, price_data = await self.token_adapter.get_token_price(token_id)
                if not success or isinstance(price_data, str):
                    continue

                success, token_info = await self.token_adapter.get_token(token_id)
                if not success or isinstance(token_info, str):
                    continue

                decimals = token_info.get("decimals", 18)
                price = price_data.get("current_price", 0.0)
                balance_usd = (float(balance_wei) / (10**decimals)) * price
                total_value += balance_usd
            except Exception as e:
                logger.warning(f"Failed to calculate value for {token_id}: {e}")
                continue

        # If tracked-balance pricing found nothing, query the protocol adapter directly
        if total_value == 0:
            if not self.current_route and self.DEPOSIT_USDC:
                await self._detect_active_protocol_route()
            adapter_usd, adapter_assets = await self._get_protocol_position_value()
            if adapter_usd > 0:
                total_value = adapter_usd
            elif adapter_assets > 0:
                pool_decimals = (
                    self.current_pool.get("decimals", 6) if self.current_pool else 6
                )
                total_value = float(adapter_assets) / (10 ** pool_decimals)

            if adapter_assets > 0:
                self.current_pool_balance = adapter_assets
            elif self.current_pool_balance > 0:
                await self._refresh_current_pool_balance()
                pool_decimals = (
                    self.current_pool.get("decimals", 6) if self.current_pool else 6
                )
                if total_value == 0:
                    total_value = float(self.current_pool_balance) / (10 ** pool_decimals)

        status_payload = (
            {
                "current_pool": self.current_pool.get("token_id"),
                "carrying_loss": None,
                "pool_balance": self.current_pool_balance
                / (10 ** self.current_pool.get("decimals")),
                "pool_apy": f"{self.current_combined_apy_pct * 100}%",
                "pool_tvl": (
                    self.current_pool_data.get("tvl")
                    if self.current_pool_data
                    else None
                ),
            }
            if self.current_pool
            else {}
        )

        return StatusDict(
            portfolio_value=total_value,
            net_deposit=self.DEPOSIT_USDC,
            strategy_status=status_payload,
            gas_available=gas_balance,
            gassed_up=gas_balance >= self.GAS_MAXIMUM * self.GAS_SAFETY_FRACTION,
        )

    async def quote(self, deposit_amount: float | None = None) -> dict:
        apy = self.current_combined_apy_pct or 0.0
        pool_name = (
            self.current_pool.get("symbol") or self.current_pool.get("name")
            if self.current_pool
            else "USDC"
        )
        pool_tvl = self.current_pool_data.get("tvl") if self.current_pool_data else None

        summary = f"Expected APY: {apy * 100:.2f}%"
        if pool_name:
            summary += f" via {pool_name}"

        return {
            "expected_apy": float(apy),
            "apy_type": "combined",
            "confidence": "high" if apy > 0 else "medium",
            "methodology": "Current pool yield from DefiLlama, auto-rotates to highest-yield stablecoin pool on Base",
            "components": {
                "pool_apy": apy,
                "pool_tvl": pool_tvl,
            },
            "deposit_amount": deposit_amount,
            "as_of": datetime.now(UTC).isoformat(),
            "summary": summary,
        }

    @staticmethod
    async def policies() -> list[str]:
        enso_router = ENSO_ROUTER.lower()
        approve_enso = (
            "eth.tx.data[0..10] == '0x095ea7b3' && "
            f"eth.tx.data[34..74] == '{enso_router[2:]}'"
        )
        swap_enso = f"eth.tx.to == '{enso_router}'"
        wallet_id = "wallet.id == 'FORMAT_WALLET_ID'"
        return [f"({wallet_id}) && (({approve_enso}) || ({swap_enso})) "]

    async def partial_liquidate(self, usd_value: float) -> StatusTuple:
        await self._refresh_tracked_balances()

        usdc_token_id = self.usdc_token_info.get("token_id")
        usdc_decimals = self.usdc_token_info.get("decimals")
        gas_token_id = self.gas_token.get("token_id") if self.gas_token else None

        available_usdc_wei = self.tracked_balances.get(usdc_token_id, 0)
        available_usdc_usd = float(available_usdc_wei) / (10**usdc_decimals)

        for token_id, balance_wei in list(self.tracked_balances.items()):
            if available_usdc_usd >= usd_value:
                break

            if token_id == usdc_token_id:
                continue
            if token_id == gas_token_id:
                continue
            if self.current_pool and token_id == self.current_pool.get("token_id"):
                continue

            if balance_wei <= 0:
                continue

            try:
                success, token_info = await self.token_adapter.get_token(token_id)
                if not success or isinstance(token_info, str):
                    continue

                success, price_data = await self.token_adapter.get_token_price(token_id)
                if not success or isinstance(price_data, str):
                    continue

                decimals = token_info.get("decimals", 18)
                price = price_data.get("current_price", 0.0)
                token_usd_value = price * float(balance_wei) / (10**decimals)

                if token_usd_value > 1.0:
                    needed_usd = usd_value - available_usdc_usd
                    required_token_wei = int(
                        math.ceil((needed_usd * (10**decimals)) / price)
                    )
                    amount_to_swap = min(required_token_wei, balance_wei)

                    logger.info(f"Liquidating {token_id} to USDC: {amount_to_swap} wei")
                    success, msg = await self.brap_adapter.swap_from_token_ids(
                        token_id,
                        f"{self.usdc_token_info.get('chain').get('code')}_{self.usdc_token_info.get('address').lower()}",
                        self._get_strategy_wallet_address(),
                        str(amount_to_swap),
                        strategy_name=self.name,
                    )
                    if success:
                        swapped_usd = (amount_to_swap / (10**decimals)) * price
                        available_usdc_usd += swapped_usd
                        self._update_balance(token_id, balance_wei - amount_to_swap)
                    else:
                        logger.warning(f"Failed to liquidate {token_id}: {msg}")
            except Exception as e:
                logger.error(f"Error liquidating {token_id}: {e}")
                continue

        # Refresh USDC balance after swaps
        success, usdc_wei = await self.balance_adapter.get_balance(
            token_id=usdc_token_id,
            wallet_address=self._get_strategy_wallet_address(),
        )
        if success and usdc_wei:
            available_usdc_wei = int(usdc_wei)
            available_usdc_usd = float(available_usdc_wei) / (10**usdc_decimals)
            self._update_balance(usdc_token_id, available_usdc_wei)

        if (
            available_usdc_usd < usd_value
            and self.current_pool
            and self.current_pool.get("token_id") != usdc_token_id
        ):
            remaining_usd = usd_value - available_usdc_usd
            pool_balance_wei = self.tracked_balances.get(
                self.current_pool.get("token_id"), 0
            )
            pool_decimals = self.current_pool.get("decimals")
            amount_to_swap = min(
                pool_balance_wei, int(remaining_usd * (10**pool_decimals))
            )

            if amount_to_swap > 0:
                try:
                    logger.info(
                        f"Liquidating from current pool {self.current_pool.get('token_id')}"
                    )
                    success, msg = await self.brap_adapter.swap_from_token_ids(
                        self.current_pool.get("token_id"),
                        f"{self.usdc_token_info.get('chain').get('code')}_{self.usdc_token_info.get('address').lower()}",
                        self._get_strategy_wallet_address(),
                        str(amount_to_swap),
                        strategy_name=self.name,
                    )
                    if success:
                        self._update_balance(
                            self.current_pool.get("token_id"),
                            pool_balance_wei - amount_to_swap,
                        )
                except Exception as e:
                    logger.error(f"Error swapping pool to USDC: {e}")

                success, usdc_wei = await self.balance_adapter.get_balance(
                    token_id=usdc_token_id,
                    wallet_address=self._get_strategy_wallet_address(),
                )
                if success and usdc_wei:
                    available_usdc_wei = int(usdc_wei)
                    self._update_balance(usdc_token_id, available_usdc_wei)

        to_pay = min(available_usdc_wei, int(usd_value * (10**usdc_decimals)))
        to_pay_usd = float(to_pay) / (10**usdc_decimals)
        return (
            True,
            f"Partial liquidation completed. Available: {to_pay_usd:.2f} USDC",
        )
