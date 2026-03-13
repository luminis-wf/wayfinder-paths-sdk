import pytest

from wayfinder_paths.core.utils.symbols import is_pt_symbol, is_usd_pool_symbol, is_usd_symbol


class TestIsUsdSymbol:
    @pytest.mark.parametrize(
        "symbol",
        ["USDC", "USDT", "DAI", "FRAX", "GHO", "PYUSD", "CRVUSD", "LUSD", "GUSD"],
    )
    def test_usd_stablecoins_pass(self, symbol: str):
        assert is_usd_symbol(symbol) is True

    @pytest.mark.parametrize(
        "symbol",
        ["sUSDe", "cUSDC", "aUSDT", "USDBC", "FDUSD"],
    )
    def test_wrapped_usd_variants_pass(self, symbol: str):
        assert is_usd_symbol(symbol) is True

    @pytest.mark.parametrize(
        "symbol",
        ["agEUR", "EURe", "EURS", "EURT"],
    )
    def test_eur_stables_rejected(self, symbol: str):
        assert is_usd_symbol(symbol) is False

    @pytest.mark.parametrize(
        "symbol",
        ["GBPT", "JPYC", "CADC", "CHFR"],
    )
    def test_non_usd_fiat_rejected(self, symbol: str):
        assert is_usd_symbol(symbol) is False

    def test_empty_and_none(self):
        assert is_usd_symbol("") is False
        assert is_usd_symbol(None) is False

    def test_non_stable_token(self):
        assert is_usd_symbol("ETH") is False
        assert is_usd_symbol("BTC") is False
        assert is_usd_symbol("WETH") is False


class TestIsUsdPoolSymbol:
    def test_usd_pair(self):
        assert is_usd_pool_symbol("USDC-USDT") is True

    def test_single_usd(self):
        assert is_usd_pool_symbol("USDC") is True

    def test_eur_usd_pair_rejected(self):
        assert is_usd_pool_symbol("agEUR-USDC") is False

    def test_triple_usd_pool(self):
        assert is_usd_pool_symbol("USDC-DAI-USDT") is True

    def test_empty_and_none(self):
        assert is_usd_pool_symbol("") is False
        assert is_usd_pool_symbol(None) is False

    def test_non_stable_pair(self):
        assert is_usd_pool_symbol("ETH-USDC") is False

    def test_eur_only_pool(self):
        assert is_usd_pool_symbol("agEUR-EURe") is False


class TestIsPtSymbol:
    def test_pt_prefix_detected(self):
        assert is_pt_symbol("PT-yoUSD") is True
        assert is_pt_symbol("PT-sUSDe") is True

    def test_non_pt_rejected(self):
        assert is_pt_symbol("USDC") is False
        assert is_pt_symbol("PT") is False

    def test_empty_and_none(self):
        assert is_pt_symbol("") is False
        assert is_pt_symbol(None) is False
