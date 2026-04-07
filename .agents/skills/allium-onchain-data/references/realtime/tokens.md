# Tokens API Reference

**Base URL:** `https://api.allium.so`
**Auth:** `X-API-KEY` header

---

### List tokens

`GET /api/v1/developer/tokens`

List tokens, optionally sorted by a field.

#### Request

**Query parameters:**

| Field | Type | Required | Description |
| ----- | ---- | -------- | ----------- |
| `chain` | string | No | The chain of the tokens. Do not pass anything to search across all tokens. |
| `sort` | string | No | Sort by a certain field. One of: volume, trade_count, fully_diluted_valuation, address, name (default: `volume`) |
| `granularity` | string or null | No | Granularity of the sorting field. Only used if sort is volume or trade_count. |
| `order` | string | No | Sorting order. One of: asc, desc (default: `desc`) |
| `limit` | integer | No | Maximum number of tokens to return. (default: `200`) |
| `volume_usd_1d_threshold` | number | No | Minimum 1d volume in USD. Only returns tokens with volume >= this value. |
| `volume_usd_1h_threshold` | number | No | Minimum 1h volume in USD. Only returns tokens with volume >= this value. |

**Example:**

```bash
curl -X GET "https://api.allium.so/api/v1/developer/tokens" \
  -H "X-API-KEY: $API_KEY"
```

#### Response

| Field | Type | Always present | Description |
| ----- | ---- | -------------- | ----------- |
| `[].object` | string | No |  |
| `[].chain` | string | Yes | Lowercase chain name |
| `[].address` | string | Yes | Token contract address |
| `[].type` | string or null | No | Token standard type: evm_erc20/evm_erc721/evm_erc1155 (EVMs), sol_spl (Solana), sui_token (Sui), near_nep141/near_nep245 (Near), stellar_classic/stellar_sac/stellar_wasm (Stellar), or native (All) |
| `[].price` | number or null | No | Current price (USD) |
| `[].decimals` | integer or null | No | Token decimal places |
| `[].info` | object or null | No | Token name and symbol |
| `[].info.name` | string | Yes | Token name |
| `[].info.symbol` | string | Yes | Token symbol |
| `[].attributes` | object or null | No | Token market attributes |
| `[].attributes.total_liquidity_usd` | object or null | No | Liquidity data: {'amount': number} when available, or {'details': 'LIQUIDITY_TOO_HIGH'} when limit exceeded |
| `[].attributes.total_liquidity_usd.amount` | number or null | No | Liquidity amount (USD) |
| `[].attributes.total_liquidity_usd.details` | string or null | No | Status when amount unavailable (e.g. LIQUIDITY_TOO_HIGH) |
| `[].attributes.price_diff_1d` | number or null | No | Price change (USD) over last 24h |
| `[].attributes.price_diff_pct_1d` | number or null | No | Price change (%) over last 24h |
| `[].attributes.price_diff_1h` | number or null | No | Price change (USD) over last 1h |
| `[].attributes.price_diff_pct_1h` | number or null | No | Price change (%) over last 1h |
| `[].attributes.total_supply` | number or null | No | Total token supply |
| `[].attributes.fully_diluted_valuation_usd` | number or null | No | Fully diluted valuation (USD) |
| `[].attributes.volume_1h` | number or null | No | Trading volume over last 1h |
| `[].attributes.volume_1d` | number or null | No | Trading volume over last 24h |
| `[].attributes.volume_usd_1h` | number or null | No | Trading volume (USD) over last 1h |
| `[].attributes.volume_usd_1d` | number or null | No | Trading volume (USD) over last 24h |
| `[].attributes.volume_24h` | number or null | No | Trading volume over last 24h |
| `[].attributes.volume_usd_24h` | number or null | No | Trading volume (USD) over last 24h |
| `[].attributes.trade_count_1h` | integer or null | No | Trade count over last 1h |
| `[].attributes.trade_count_1d` | integer or null | No | Trade count over last 24h |
| `[].attributes.all_time_high` | number or null | No | All-time high price (USD) |
| `[].attributes.all_time_low` | number or null | No | All-time low price (USD) |
| `[].attributes.image_url` | string or null | No | Token logo URL |
| `[].attributes.token_creation_time` | string or null | No | Token creation timestamp (UTC) |
| `[].attributes.holders_count` | integer or null | No | Number of token holders |
| `[].attributes.stellar_fields` | object or null | No | Stellar-specific metadata |

Detailed docs (supported chains, edge cases, response format): `GET /api/v1/docs/docs/browse?path=api/developer/tokens/list-tokens.md`

---

### Fetch tokens by keyword

`GET /api/v1/developer/tokens/search`

Search tokens with a query string.

#### Request

**Query parameters:**

| Field | Type | Required | Description |
| ----- | ---- | -------- | ----------- |
| `q` | string | Yes | The query string to search in name and symbol. Performs a case-insensitive substring search. |
| `chain` | string | No | The chain of the tokens. Do not pass anything to search across all tokens. |
| `sort` | string | No | Sort by a certain field. One of: volume, trade_count, fully_diluted_valuation, address, name (default: `volume`) |
| `granularity` | string or null | No | Granularity of the sorting field. Only used if sort is volume or trade_count. |
| `order` | string | No | Sorting order. One of: asc, desc (default: `desc`) |
| `limit` | integer | No | Maximum number of tokens to return. (default: `200`) |
| `volume_usd_1d_threshold` | number | No | Minimum 1d volume in USD. Only returns tokens with volume >= this value. |
| `volume_usd_1h_threshold` | number | No | Minimum 1h volume in USD. Only returns tokens with volume >= this value. |

**Example:**

```bash
curl -X GET "https://api.allium.so/api/v1/developer/tokens/search?q=..." \
  -H "X-API-KEY: $API_KEY"
```

#### Response

| Field | Type | Always present | Description |
| ----- | ---- | -------------- | ----------- |
| `[].object` | string | No |  |
| `[].chain` | string | Yes | Lowercase chain name |
| `[].address` | string | Yes | Token contract address |
| `[].type` | string or null | No | Token standard type: evm_erc20/evm_erc721/evm_erc1155 (EVMs), sol_spl (Solana), sui_token (Sui), near_nep141/near_nep245 (Near), stellar_classic/stellar_sac/stellar_wasm (Stellar), or native (All) |
| `[].price` | number or null | No | Current price (USD) |
| `[].decimals` | integer or null | No | Token decimal places |
| `[].info` | object or null | No | Token name and symbol |
| `[].info.name` | string | Yes | Token name |
| `[].info.symbol` | string | Yes | Token symbol |
| `[].attributes` | object or null | No | Token market attributes |
| `[].attributes.total_liquidity_usd` | object or null | No | Liquidity data: {'amount': number} when available, or {'details': 'LIQUIDITY_TOO_HIGH'} when limit exceeded |
| `[].attributes.total_liquidity_usd.amount` | number or null | No | Liquidity amount (USD) |
| `[].attributes.total_liquidity_usd.details` | string or null | No | Status when amount unavailable (e.g. LIQUIDITY_TOO_HIGH) |
| `[].attributes.price_diff_1d` | number or null | No | Price change (USD) over last 24h |
| `[].attributes.price_diff_pct_1d` | number or null | No | Price change (%) over last 24h |
| `[].attributes.price_diff_1h` | number or null | No | Price change (USD) over last 1h |
| `[].attributes.price_diff_pct_1h` | number or null | No | Price change (%) over last 1h |
| `[].attributes.total_supply` | number or null | No | Total token supply |
| `[].attributes.fully_diluted_valuation_usd` | number or null | No | Fully diluted valuation (USD) |
| `[].attributes.volume_1h` | number or null | No | Trading volume over last 1h |
| `[].attributes.volume_1d` | number or null | No | Trading volume over last 24h |
| `[].attributes.volume_usd_1h` | number or null | No | Trading volume (USD) over last 1h |
| `[].attributes.volume_usd_1d` | number or null | No | Trading volume (USD) over last 24h |
| `[].attributes.volume_24h` | number or null | No | Trading volume over last 24h |
| `[].attributes.volume_usd_24h` | number or null | No | Trading volume (USD) over last 24h |
| `[].attributes.trade_count_1h` | integer or null | No | Trade count over last 1h |
| `[].attributes.trade_count_1d` | integer or null | No | Trade count over last 24h |
| `[].attributes.all_time_high` | number or null | No | All-time high price (USD) |
| `[].attributes.all_time_low` | number or null | No | All-time low price (USD) |
| `[].attributes.image_url` | string or null | No | Token logo URL |
| `[].attributes.token_creation_time` | string or null | No | Token creation timestamp (UTC) |
| `[].attributes.holders_count` | integer or null | No | Number of token holders |
| `[].attributes.stellar_fields` | object or null | No | Stellar-specific metadata |

Detailed docs (supported chains, edge cases, response format): `GET /api/v1/docs/docs/browse?path=api/developer/tokens/search-tokens.md`

---

### Fetch token by address

`POST /api/v1/developer/tokens/chain-address`

Get token details for the given token addresses and chains.

#### Request

**Body:**

| Field | Type | Required | Description |
| ----- | ---- | -------- | ----------- |
| `token_address` | string | Yes | Token contract address |
| `chain` | string | Yes | Lowercase chain name |

**Example:**

```bash
curl -X POST "https://api.allium.so/api/v1/developer/tokens/chain-address" \
  -H "X-API-KEY: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '[
    {
      "chain": "string",
      "token_address": "string"
    }
  ]'
```

#### Response

| Field | Type | Always present | Description |
| ----- | ---- | -------------- | ----------- |
| `[].object` | string | No |  |
| `[].chain` | string | Yes | Lowercase chain name |
| `[].address` | string | Yes | Token contract address |
| `[].type` | string or null | No | Token standard type: evm_erc20/evm_erc721/evm_erc1155 (EVMs), sol_spl (Solana), sui_token (Sui), near_nep141/near_nep245 (Near), stellar_classic/stellar_sac/stellar_wasm (Stellar), or native (All) |
| `[].price` | number or null | No | Current price (USD) |
| `[].decimals` | integer or null | No | Token decimal places |
| `[].info` | object or null | No | Token name and symbol |
| `[].info.name` | string | Yes | Token name |
| `[].info.symbol` | string | Yes | Token symbol |
| `[].attributes` | object or null | No | Token market attributes |
| `[].attributes.total_liquidity_usd` | object or null | No | Liquidity data: {'amount': number} when available, or {'details': 'LIQUIDITY_TOO_HIGH'} when limit exceeded |
| `[].attributes.total_liquidity_usd.amount` | number or null | No | Liquidity amount (USD) |
| `[].attributes.total_liquidity_usd.details` | string or null | No | Status when amount unavailable (e.g. LIQUIDITY_TOO_HIGH) |
| `[].attributes.price_diff_1d` | number or null | No | Price change (USD) over last 24h |
| `[].attributes.price_diff_pct_1d` | number or null | No | Price change (%) over last 24h |
| `[].attributes.price_diff_1h` | number or null | No | Price change (USD) over last 1h |
| `[].attributes.price_diff_pct_1h` | number or null | No | Price change (%) over last 1h |
| `[].attributes.total_supply` | number or null | No | Total token supply |
| `[].attributes.fully_diluted_valuation_usd` | number or null | No | Fully diluted valuation (USD) |
| `[].attributes.volume_1h` | number or null | No | Trading volume over last 1h |
| `[].attributes.volume_1d` | number or null | No | Trading volume over last 24h |
| `[].attributes.volume_usd_1h` | number or null | No | Trading volume (USD) over last 1h |
| `[].attributes.volume_usd_1d` | number or null | No | Trading volume (USD) over last 24h |
| `[].attributes.volume_24h` | number or null | No | Trading volume over last 24h |
| `[].attributes.volume_usd_24h` | number or null | No | Trading volume (USD) over last 24h |
| `[].attributes.trade_count_1h` | integer or null | No | Trade count over last 1h |
| `[].attributes.trade_count_1d` | integer or null | No | Trade count over last 24h |
| `[].attributes.all_time_high` | number or null | No | All-time high price (USD) |
| `[].attributes.all_time_low` | number or null | No | All-time low price (USD) |
| `[].attributes.image_url` | string or null | No | Token logo URL |
| `[].attributes.token_creation_time` | string or null | No | Token creation timestamp (UTC) |
| `[].attributes.holders_count` | integer or null | No | Number of token holders |
| `[].attributes.stellar_fields` | object or null | No | Stellar-specific metadata |

Detailed docs (supported chains, edge cases, response format): `GET /api/v1/docs/docs/browse?path=api/developer/tokens/get-tokens-by-chain-address.md`
