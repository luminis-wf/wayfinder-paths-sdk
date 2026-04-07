# Wallets API Reference

**Base URL:** `https://api.allium.so`
**Auth:** `X-API-KEY` header

---

### Fetch latest fungible token balances

`POST /api/v1/developer/wallet/balances`

#### Request

**Body:**

| Field | Type | Required | Description |
| ----- | ---- | -------- | ----------- |
| `chain` | string | Yes | Lowercase chain name |
| `address` | string | Yes | Wallet address |

**Query parameters:**

| Field | Type | Required | Description |
| ----- | ---- | -------- | ----------- |
| `with_liquidity_info` | boolean | No | If true, returns total_liquidity_usd as well. See this page for more details. (default: `False`) |

**Example:**

```bash
curl -X POST "https://api.allium.so/api/v1/developer/wallet/balances" \
  -H "X-API-KEY: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '[
    {
      "chain": "ethereum",
      "address": "0xab16781a13fe343a275f4bb5c883a64ceda52917"
    }
  ]'
```

#### Response

| Field | Type | Always present | Description |
| ----- | ---- | -------------- | ----------- |
| `items[].chain` | string | Yes | Lowercase chain name |
| `items[].address` | string | Yes | Wallet address |
| `items[].token` | object | Yes | Token metadata |
| `items[].token.object` | string | No |  |
| `items[].token.chain` | string | Yes | Lowercase chain name |
| `items[].token.address` | string | Yes | Token contract address |
| `items[].token.type` | string or null | No | Token standard type: evm_erc20/evm_erc721/evm_erc1155 (EVMs), sol_spl (Solana), sui_token (Sui), near_nep141/near_nep245 (Near), stellar_classic/stellar_sac/stellar_wasm (Stellar), or native (All) |
| `items[].token.price` | number or null | No | Current price (USD) |
| `items[].token.decimals` | integer or null | No | Token decimal places |
| `items[].token.info` | object or null | No | Token name and symbol |
| `items[].token.info.name` | string | Yes | Token name |
| `items[].token.info.symbol` | string | Yes | Token symbol |
| `items[].token.attributes` | object or null | No | Token market attributes |
| `items[].token.attributes.total_liquidity_usd` | object or null | No | Liquidity data: {'amount': number} when available, or {'details': 'LIQUIDITY_TOO_HIGH'} when limit exceeded |
| `items[].token.attributes.price_diff_1d` | number or null | No | Price change (USD) over last 24h |
| `items[].token.attributes.price_diff_pct_1d` | number or null | No | Price change (%) over last 24h |
| `items[].token.attributes.price_diff_1h` | number or null | No | Price change (USD) over last 1h |
| `items[].token.attributes.price_diff_pct_1h` | number or null | No | Price change (%) over last 1h |
| `items[].token.attributes.total_supply` | number or null | No | Total token supply |
| `items[].token.attributes.fully_diluted_valuation_usd` | number or null | No | Fully diluted valuation (USD) |
| `items[].token.attributes.volume_1h` | number or null | No | Trading volume over last 1h |
| `items[].token.attributes.volume_1d` | number or null | No | Trading volume over last 24h |
| `items[].token.attributes.volume_usd_1h` | number or null | No | Trading volume (USD) over last 1h |
| `items[].token.attributes.volume_usd_1d` | number or null | No | Trading volume (USD) over last 24h |
| `items[].token.attributes.volume_24h` | number or null | No | Trading volume over last 24h |
| `items[].token.attributes.volume_usd_24h` | number or null | No | Trading volume (USD) over last 24h |
| `items[].token.attributes.trade_count_1h` | integer or null | No | Trade count over last 1h |
| `items[].token.attributes.trade_count_1d` | integer or null | No | Trade count over last 24h |
| `items[].token.attributes.all_time_high` | number or null | No | All-time high price (USD) |
| `items[].token.attributes.all_time_low` | number or null | No | All-time low price (USD) |
| `items[].token.attributes.image_url` | string or null | No | Token logo URL |
| `items[].token.attributes.token_creation_time` | string or null | No | Token creation timestamp (UTC) |
| `items[].token.attributes.holders_count` | integer or null | No | Number of token holders |
| `items[].token.attributes.stellar_fields` | object or null | No | Stellar-specific metadata |
| `items[].raw_balance` | integer | Yes | Raw balance of the token |
| `items[].raw_balance_str` | string | Yes | Raw balance of the token as a string |
| `items[].block_timestamp` | string | Yes | Block timestamp (UTC) |
| `items[].block_number` | integer or null | No | Block number |
| `items[].block_hash` | string or null | No | Block hash |

Detailed docs (supported chains, edge cases, response format): `GET /api/v1/docs/docs/browse?path=api/developer/wallets/latest-token-balances.md`

---

### Fetch historical fungible token balances

`POST /api/v1/developer/wallet/balances/history`

#### Request

**Body:**

| Field | Type | Required | Description |
| ----- | ---- | -------- | ----------- |
| `start_timestamp` | string | Yes | Start of time range (UTC ISO 8601) |
| `end_timestamp` | string | Yes | End of time range (UTC ISO 8601) |
| `addresses` | array of objects | Yes | List of wallet chain+address pairs |

**Query parameters:**

| Field | Type | Required | Description |
| ----- | ---- | -------- | ----------- |
| `limit` | integer | No | Max number of items returned. Default is 1000. (default: `1000`) |
| `cursor` | string | No | Cursor to request the next page of results. |

**Example:**

```bash
curl -X POST "https://api.allium.so/api/v1/developer/wallet/balances/history" \
  -H "X-API-KEY: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "addresses": [
      {
        "address": "125Z6k4ZAxsgdG7JxrKZpwbcS1rxqpAeqM9GSCKd66Wp",
        "chain": "solana"
      }
    ],
    "end_timestamp": "2025-04-01T13:00:00Z",
    "start_timestamp": "2025-04-01T12:00:00Z"
  }'
```

#### Response

| Field | Type | Always present | Description |
| ----- | ---- | -------------- | ----------- |
| `items[].chain` | string | Yes | Lowercase chain name |
| `items[].address` | string | Yes | Wallet address |
| `items[].token` | object | Yes | Token metadata |
| `items[].token.object` | string | No |  |
| `items[].token.chain` | string | Yes | Lowercase chain name |
| `items[].token.address` | string | Yes | Token contract address |
| `items[].token.type` | string or null | No | Token standard type: evm_erc20/evm_erc721/evm_erc1155 (EVMs), sol_spl (Solana), sui_token (Sui), near_nep141/near_nep245 (Near), stellar_classic/stellar_sac/stellar_wasm (Stellar), or native (All) |
| `items[].token.price` | number or null | No | Current price (USD) |
| `items[].token.decimals` | integer or null | No | Token decimal places |
| `items[].token.info` | object or null | No | Token name and symbol |
| `items[].token.info.name` | string | Yes | Token name |
| `items[].token.info.symbol` | string | Yes | Token symbol |
| `items[].token.attributes` | object or null | No | Token market attributes |
| `items[].token.attributes.total_liquidity_usd` | object or null | No | Liquidity data: {'amount': number} when available, or {'details': 'LIQUIDITY_TOO_HIGH'} when limit exceeded |
| `items[].token.attributes.price_diff_1d` | number or null | No | Price change (USD) over last 24h |
| `items[].token.attributes.price_diff_pct_1d` | number or null | No | Price change (%) over last 24h |
| `items[].token.attributes.price_diff_1h` | number or null | No | Price change (USD) over last 1h |
| `items[].token.attributes.price_diff_pct_1h` | number or null | No | Price change (%) over last 1h |
| `items[].token.attributes.total_supply` | number or null | No | Total token supply |
| `items[].token.attributes.fully_diluted_valuation_usd` | number or null | No | Fully diluted valuation (USD) |
| `items[].token.attributes.volume_1h` | number or null | No | Trading volume over last 1h |
| `items[].token.attributes.volume_1d` | number or null | No | Trading volume over last 24h |
| `items[].token.attributes.volume_usd_1h` | number or null | No | Trading volume (USD) over last 1h |
| `items[].token.attributes.volume_usd_1d` | number or null | No | Trading volume (USD) over last 24h |
| `items[].token.attributes.volume_24h` | number or null | No | Trading volume over last 24h |
| `items[].token.attributes.volume_usd_24h` | number or null | No | Trading volume (USD) over last 24h |
| `items[].token.attributes.trade_count_1h` | integer or null | No | Trade count over last 1h |
| `items[].token.attributes.trade_count_1d` | integer or null | No | Trade count over last 24h |
| `items[].token.attributes.all_time_high` | number or null | No | All-time high price (USD) |
| `items[].token.attributes.all_time_low` | number or null | No | All-time low price (USD) |
| `items[].token.attributes.image_url` | string or null | No | Token logo URL |
| `items[].token.attributes.token_creation_time` | string or null | No | Token creation timestamp (UTC) |
| `items[].token.attributes.holders_count` | integer or null | No | Number of token holders |
| `items[].token.attributes.stellar_fields` | object or null | No | Stellar-specific metadata |
| `items[].raw_balance` | integer | Yes | Raw balance of the token |
| `items[].raw_balance_str` | string | Yes | Raw balance of the token as a string |
| `items[].block_timestamp` | string | Yes | Block timestamp (UTC) |
| `items[].block_slot` | integer | Yes | Block slot |
| `items[].txn_index` | integer | Yes | Transaction index |
| `items[].token_account` | string or null | No | Token account |
| `items[].block_hash` | string | Yes | Block hash |
| `items[].txn_id` | string | Yes | Transaction ID |

Detailed docs (supported chains, edge cases, response format): `GET /api/v1/docs/docs/browse?path=api/developer/wallets/historical-token-balances.md`

---

### Fetch transactions

`POST /api/v1/developer/wallet/transactions`

Get rich transaction activity data for wallets, including activities, asset transfers, and labels.

#### Request

**Body:**

| Field | Type | Required | Description |
| ----- | ---- | -------- | ----------- |
| `chain` | string | Yes |  |
| `address` | string | Yes |  |

**Query parameters:**

| Field | Type | Required | Description |
| ----- | ---- | -------- | ----------- |
| `activity_type` | string | No | Activity type to filter transactions by |
| `limit` | integer | No | Limit the number of transactions returned. Default is 25. (default: `25`) |
| `transaction_hash` | string | No | Filter by transaction hash |
| `cursor` | string | No | Cursor to request the next page of results. |

**Example:**

```bash
curl -X POST "https://api.allium.so/api/v1/developer/wallet/transactions" \
  -H "X-API-KEY: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '[{"chain": "...", "address": "..."}]'
```

#### Response

| Field | Type | Always present | Description |
| ----- | ---- | -------------- | ----------- |
| `items[].id` | string | Yes |  |
| `items[].type` | integer or null | No |  |
| `items[].address` | string | Yes |  |
| `items[].chain` | string | Yes |  |
| `items[].hash` | string | Yes |  |
| `items[].index` | integer | Yes |  |
| `items[].within_block_order_key` | integer | Yes |  |
| `items[].block_timestamp` | string | Yes |  |
| `items[].block_number` | integer | Yes |  |
| `items[].block_hash` | string or null | No |  |
| `items[].fee` | object | Yes |  |
| `items[].fee.raw_amount` | string or null | No |  |
| `items[].fee.amount_str` | string or null | No |  |
| `items[].fee.amount` | number or null | No |  |
| `items[].labels` | array of string | Yes |  |
| `items[].from_address` | string or null | No |  |
| `items[].to_address` | string or null | No |  |
| `items[].asset_transfers` | array of objects | Yes |  |
| `items[].asset_transfers[].transfer_type` | string | Yes |  |
| `items[].asset_transfers[].operation` | string or null | No |  |
| `items[].asset_transfers[].transaction_hash` | string | Yes |  |
| `items[].asset_transfers[].log_index` | integer or null | No |  |
| `items[].asset_transfers[].from_address` | string | Yes |  |
| `items[].asset_transfers[].to_address` | string | Yes |  |
| `items[].asset_transfers[].asset` | object | Yes |  |
| `items[].asset_transfers[].asset.type` | string or null | No |  |
| `items[].asset_transfers[].asset.address` | string or null | No |  |
| `items[].asset_transfers[].asset.name` | string or null | No |  |
| `items[].asset_transfers[].asset.symbol` | string or null | No |  |
| `items[].asset_transfers[].asset.decimals` | integer or null | No |  |
| `items[].asset_transfers[].asset.token_id` | string or null | No |  |
| `items[].asset_transfers[].amount` | object | Yes |  |
| `items[].asset_transfers[].amount.raw_amount` | string or null | No |  |
| `items[].asset_transfers[].amount.amount_str` | string or null | No |  |
| `items[].asset_transfers[].amount.amount` | number or null | No |  |
| `items[].activities` | array of object | Yes |  |

Detailed docs (supported chains, edge cases, response format): `GET /api/v1/docs/docs/browse?path=api/developer/wallets/transactions.md`
