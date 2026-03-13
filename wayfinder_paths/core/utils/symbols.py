from __future__ import annotations

import unicodedata

SYMBOL_TRANSLATION_TABLE = str.maketrans(
    {
        "₮": "T",
        "₿": "B",
        "Ξ": "X",
    }
)

STABLE_SYMBOL_KEYWORDS = {
    "USD",
    "USDC",
    "USDT",
    "USDP",
    "USDD",
    "USDS",
    "DAI",
    "USKB",
    "USDE",
    "USDH",
    "USDL",
    "USDR",
    "USDX",
    "SUSD",
    "LUSD",
    "GUSD",
    "TUSD",
    "USR",
    "USDHL",
}


def normalize_symbol(symbol: str | None) -> str:
    """Normalize a token symbol for stable comparisons / keys.

    - Unicode NFKD normalization
    - Common crypto symbol translation (₮/₿/Ξ)
    - ASCII-only
    - Keep only alphanumerics
    - Lowercase
    """
    if symbol is None:
        return ""
    normalized = unicodedata.normalize("NFKD", str(symbol)).translate(
        SYMBOL_TRANSLATION_TABLE
    )
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    filtered = "".join(ch for ch in ascii_only if ch.isalnum())
    if filtered:
        return filtered.lower()
    return str(symbol).lower()


def is_stable_symbol(symbol: str | None) -> bool:
    if not symbol:
        return False
    upper = str(symbol).upper()
    return any(keyword in upper for keyword in STABLE_SYMBOL_KEYWORDS)


# ---------------------------------------------------------------------------
# USD-specific stablecoin filtering
# ---------------------------------------------------------------------------

USD_STABLE_KEYWORDS: frozenset[str] = frozenset(
    {
        "USD",
        "USDC",
        "USDT",
        "USDP",
        "USDD",
        "USDS",
        "DAI",
        "USDE",
        "USDH",
        "USDL",
        "USDR",
        "USDX",
        "SUSD",
        "LUSD",
        "GUSD",
        "TUSD",
        "USR",
        "USDHL",
        "FRAX",
        "GHO",
        "PYUSD",
        "CRVUSD",
        "DOLA",
        "MIM",
        "BUSD",
        "FDUSD",
        "USDBC",
        "USDB",
        "USKB",
    }
)

NON_USD_STABLE_PREFIXES: frozenset[str] = frozenset(
    {
        "EUR",
        "GBP",
        "JPY",
        "CHF",
        "AUD",
        "CAD",
        "KRW",
        "CNY",
        "BRL",
        "TRY",
        "SGD",
        "HKD",
        "MXN",
    }
)


def is_usd_symbol(symbol: str | None) -> bool:
    """Return True if *symbol* looks like a USD-pegged stablecoin."""
    if not symbol:
        return False
    upper = str(symbol).upper()
    # Reject anything that starts with a non-USD fiat prefix
    for prefix in NON_USD_STABLE_PREFIXES:
        if upper.startswith(prefix):
            return False
    return any(kw in upper for kw in USD_STABLE_KEYWORDS)


def is_pt_symbol(symbol: str | None) -> bool:
    if not symbol:
        return False
    return str(symbol).upper().startswith("PT-")


def is_usd_pool_symbol(pool_symbol: str | None) -> bool:
    """Return True if every constituent token in *pool_symbol* is USD-denominated.

    Pool symbols use ``-`` as separator (e.g. ``USDC-USDT``).
    Returns False for empty / None input.
    """
    if not pool_symbol:
        return False
    parts = str(pool_symbol).split("-")
    return all(is_usd_symbol(part) for part in parts)
