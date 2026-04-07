# Holdings API Reference

**Base URL:** `https://api.allium.so`
**Auth:** `X-API-KEY` header

---

### Fetch holdings history

`POST /api/v1/developer/wallet/holdings/history`

Get historical aggregated USD holdings for an address.

#### Request

**Body:**

| Field | Type | Required | Description |
| ----- | ---- | -------- | ----------- |
| `start_timestamp` | string | Yes | Start of time range (UTC ISO 8601) |
| `end_timestamp` | string | Yes | End of time range (UTC ISO 8601) |
| `granularity` | string | Yes | Time interval granularity (15s, 1m, 5m, 1h, 1d) |
| `addresses` | array of objects | Yes | List of wallet chain+address pairs |
| `include_token_breakdown` | boolean | No | If true, includes per-token breakdown in each interval (default: `False`) |
| `min_liquidity` | number or null | No | Minimum USD liquidity threshold to include a token |

**Query parameters:**

| Field | Type | Required | Description |
| ----- | ---- | -------- | ----------- |
| `cursor` | string | No | cursor |

**Example:**

```bash
curl -X POST "https://api.allium.so/api/v1/developer/wallet/holdings/history" \
  -H "X-API-KEY: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "addresses": [
      {
        "address": "125Z6k4ZAxsgdG7JxrKZpwbcS1rxqpAeqM9GSCKd66Wp",
        "chain": "solana"
      }
    ],
    "end_timestamp": "2025-04-10T00:00:00Z",
    "granularity": "1h",
    "include_token_breakdown": false,
    "min_liquidity": 5000,
    "start_timestamp": "2025-04-01T00:00:00Z"
  }'
```

#### Response

| Field | Type | Always present | Description |
| ----- | ---- | -------------- | ----------- |
| `items[].chain` | string | No | Lowercase chain name |
| `items[].address` | string | No | Wallet address |
| `items[].timestamp` | string | Yes | Interval start time (UTC) |
| `items[].amount` | object | Yes | Total USD value of all holdings at this timestamp |
| `items[].amount.currency` | string | Yes | Currency code |
| `items[].amount.amount` | number | Yes | Value in the specified currency |
| `items[].token_breakdown` | array of objects or null | No | Per-token breakdown (included when include_token_breakdown=true) |
| `items[].token_breakdown[].token_address` | string | Yes | Token contract address |
| `items[].token_breakdown[].amount` | object | Yes | Token value (USD) |
| `items[].token_breakdown[].amount.currency` | string | Yes | Currency code |
| `items[].token_breakdown[].amount.amount` | number | Yes | Value in the specified currency |
| `items[].token_breakdown[].liquidity` | object or null | No | Token liquidity info |
| `items[].token_breakdown[].liquidity.amount` | number or null | No | Liquidity amount (USD) |
| `items[].token_breakdown[].liquidity.details` | string or null | No | Status when amount unavailable (e.g. LIQUIDITY_TOO_HIGH) |

Detailed docs (supported chains, edge cases, response format): `GET /api/v1/docs/docs/browse?path=api/developer/holdings/holdings-history.md`

---

### Fetch current PnL by Wallet

`POST /api/v1/developer/wallet/pnl`

Get the PnL for a given wallet address.

#### Request

**Body:**

| Field | Type | Required | Description |
| ----- | ---- | -------- | ----------- |
| `chain` | string | Yes | Lowercase chain name |
| `address` | string | Yes | Wallet address |

**Query parameters:**

| Field | Type | Required | Description |
| ----- | ---- | -------- | ----------- |
| `min_liquidity` | number | No | Minimum liquidity of which tokens must have to be included in the response. |

**Example:**

```bash
curl -X POST "https://api.allium.so/api/v1/developer/wallet/pnl" \
  -H "X-API-KEY: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '[
    {
      "chain": "solana",
      "address": "125Z6k4ZAxsgdG7JxrKZpwbcS1rxqpAeqM9GSCKd66Wp"
    }
  ]'
```

#### Response

| Field | Type | Always present | Description |
| ----- | ---- | -------------- | ----------- |
| `items[].chain` | string | Yes | Lowercase chain name |
| `items[].address` | string | Yes | Wallet address |
| `items[].tokens` | array of objects | Yes | Per-token PnL breakdown |
| `items[].tokens[].token_address` | string | Yes | Token contract address |
| `items[].tokens[].average_cost` | object or null | No | Average cost basis (USD) |
| `items[].tokens[].average_cost.currency` | string | No | Currency code |
| `items[].tokens[].average_cost.amount` | string | Yes | Value in the specified currency |
| `items[].tokens[].raw_balance` | string | Yes | Token balance (native units) |
| `items[].tokens[].current_price` | object | Yes | Current token price (USD) |
| `items[].tokens[].current_price.currency` | string | No | Currency code |
| `items[].tokens[].current_price.amount` | string | Yes | Value in the specified currency |
| `items[].tokens[].current_balance` | object or null | No | Current token balance (USD) |
| `items[].tokens[].current_balance.currency` | string | No | Currency code |
| `items[].tokens[].current_balance.amount` | string | Yes | Value in the specified currency |
| `items[].tokens[].realized_pnl` | object | Yes | Realized PnL of the token (USD) |
| `items[].tokens[].realized_pnl.currency` | string | No | Currency code |
| `items[].tokens[].realized_pnl.amount` | string | Yes | Value in the specified currency |
| `items[].tokens[].unrealized_pnl` | object or null | No | Unrealized PnL of the token (USD) |
| `items[].tokens[].unrealized_pnl.currency` | string | No | Currency code |
| `items[].tokens[].unrealized_pnl.amount` | string | Yes | Value in the specified currency |
| `items[].tokens[].unrealized_pnl_ratio_change` | number or null | No | Unrealized PnL ratio change (decimal) |
| `items[].tokens[].attributes` | object or null | No | Token attributes |
| `items[].tokens[].attributes.total_liquidity_usd` | object or null | No | Liquidity data: {'amount': number} when available, or {'details': 'LIQUIDITY_TOO_HIGH'} when limit exceeded |
| `items[].tokens[].attributes.price_diff_1d` | number or null | No | Price change (USD) over last 24h |
| `items[].tokens[].attributes.price_diff_pct_1d` | number or null | No | Price change (%) over last 24h |
| `items[].tokens[].attributes.price_diff_1h` | number or null | No | Price change (USD) over last 1h |
| `items[].tokens[].attributes.price_diff_pct_1h` | number or null | No | Price change (%) over last 1h |
| `items[].tokens[].attributes.total_supply` | number or null | No | Total token supply |
| `items[].tokens[].attributes.fully_diluted_valuation_usd` | number or null | No | Fully diluted valuation (USD) |
| `items[].tokens[].attributes.volume_1h` | number or null | No | Trading volume over last 1h |
| `items[].tokens[].attributes.volume_1d` | number or null | No | Trading volume over last 24h |
| `items[].tokens[].attributes.volume_usd_1h` | number or null | No | Trading volume (USD) over last 1h |
| `items[].tokens[].attributes.volume_usd_1d` | number or null | No | Trading volume (USD) over last 24h |
| `items[].tokens[].attributes.volume_24h` | number or null | No | Trading volume over last 24h |
| `items[].tokens[].attributes.volume_usd_24h` | number or null | No | Trading volume (USD) over last 24h |
| `items[].tokens[].attributes.trade_count_1h` | integer or null | No | Trade count over last 1h |
| `items[].tokens[].attributes.trade_count_1d` | integer or null | No | Trade count over last 24h |
| `items[].tokens[].attributes.all_time_high` | number or null | No | All-time high price (USD) |
| `items[].tokens[].attributes.all_time_low` | number or null | No | All-time low price (USD) |
| `items[].tokens[].attributes.image_url` | string or null | No | Token logo URL |
| `items[].tokens[].attributes.token_creation_time` | string or null | No | Token creation timestamp (UTC) |
| `items[].tokens[].attributes.holders_count` | integer or null | No | Number of token holders |
| `items[].tokens[].attributes.stellar_fields` | object or null | No | Stellar-specific metadata |
| `items[].tokens[].historical_breakdown` | array of objects or null | No | Historical breakdown of the token transactions |
| `items[].tokens[].historical_breakdown[].trade` | object | Yes | Trade details |
| `items[].tokens[].historical_breakdown[].average_cost` | object or null | No | Average cost basis after this trade in USD |
| `items[].tokens[].historical_breakdown[].realized_pnl` | object | Yes | Realized PnL from this trade in USD |
| `items[].total_balance` | object | Yes | Total balance (USD) |
| `items[].total_balance.currency` | string | No | Currency code |
| `items[].total_balance.amount` | string | Yes | Value in the specified currency |
| `items[].total_realized_pnl` | object | Yes | Total realized PnL (USD) |
| `items[].total_realized_pnl.currency` | string | No | Currency code |
| `items[].total_realized_pnl.amount` | string | Yes | Value in the specified currency |
| `items[].total_unrealized_pnl` | object | Yes | Total unrealized PnL (USD) |
| `items[].total_unrealized_pnl.currency` | string | No | Currency code |
| `items[].total_unrealized_pnl.amount` | string | Yes | Value in the specified currency |
| `items[].total_unrealized_pnl_ratio_change` | number or null | No | Total unrealized PnL ratio change (decimal) |

**Example:**

```json
{
  "items": [
    {
      "address": "125Z6k4ZAxsgdG7JxrKZpwbcS1rxqpAeqM9GSCKd66Wp",
      "chain": "solana",
      "tokens": [
        {
          "attributes": {
            "total_liquidity_usd": {
              "details": "LIQUIDITY_TOO_HIGH"
            }
          },
          "average_cost": {
            "amount": "127.643159342305505704",
            "currency": "USD"
          },
          "current_balance": {
            "amount": "1831.966741963714540927",
            "currency": "USD"
          },
          "current_price": {
            "amount": "90.881678182871411309",
            "currency": "USD"
          },
          "raw_balance": "20.157712518",
          "realized_pnl": {
            "amount": "-102.802362175169957013",
            "currency": "USD"
          },
          "token_address": "So11111111111111111111111111111111111111112",
          "unrealized_pnl": {
            "amount": "-741.027368947745798389",
            "currency": "USD"
          },
          "unrealized_pnl_ratio_change": -0.28800196852578236
        }
      ],
      "total_balance": {
        "amount": "1831.966741963714540927",
        "currency": "USD"
      },
      "total_realized_pnl": {
        "amount": "-102.802362175169957013",
        "currency": "USD"
      },
      "total_unrealized_pnl": {
        "amount": "-741.027368947745798389",
        "currency": "USD"
      },
      "total_unrealized_pnl_ratio_change": -0.28800196852578236
    }
  ]
}
```

Detailed docs (supported chains, edge cases, response format): `GET /api/v1/docs/docs/browse?path=api/developer/holdings/holdings-pnl.md`

---

### Fetch historical PnL by Wallet

`POST /api/v1/developer/wallet/pnl/history`

Get the Historical PnL for a given wallet address.

#### Request

**Body:**

| Field | Type | Required | Description |
| ----- | ---- | -------- | ----------- |
| `start_timestamp` | string | Yes | Start of time range (UTC ISO 8601) |
| `end_timestamp` | string | Yes | End of time range (UTC ISO 8601) |
| `granularity` | string | Yes | Time interval granularity (1d, 1h, 5m, 1m, 15s) |
| `addresses` | array of objects | Yes | List of wallet chain+address pairs |

**Query parameters:**

| Field | Type | Required | Description |
| ----- | ---- | -------- | ----------- |
| `min_liquidity` | number | No | Minimum liquidity of which tokens must have to be included in the response. |

**Example:**

```bash
curl -X POST "https://api.allium.so/api/v1/developer/wallet/pnl/history" \
  -H "X-API-KEY: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "addresses": [
      {
        "address": "125Z6k4ZAxsgdG7JxrKZpwbcS1rxqpAeqM9GSCKd66Wp",
        "chain": "solana"
      }
    ],
    "end_timestamp": "2025-04-10T00:00:00Z",
    "granularity": "1h",
    "start_timestamp": "2025-04-01T00:00:00Z"
  }'
```

#### Response

| Field | Type | Always present | Description |
| ----- | ---- | -------------- | ----------- |
| `items[].chain` | string | Yes | Lowercase chain name |
| `items[].address` | string | Yes | Wallet address |
| `items[].pnl` | array of objects | Yes | PnL snapshots per time interval |
| `items[].pnl[].timestamp` | string | Yes | Interval start time (UTC) |
| `items[].pnl[].unrealized_pnl` | object | Yes | Unrealized PnL at this interval (USD) |
| `items[].pnl[].unrealized_pnl.currency` | string | No | Currency code |
| `items[].pnl[].unrealized_pnl.amount` | string | Yes | Value in the specified currency |
| `items[].pnl[].realized_pnl` | object | Yes | Cumulative realized PnL at this interval (USD) |
| `items[].pnl[].realized_pnl.currency` | string | No | Currency code |
| `items[].pnl[].realized_pnl.amount` | string | Yes | Value in the specified currency |

**Example:**

```json
{
  "items": [
    {
      "address": "125Z6k4ZAxsgdG7JxrKZpwbcS1rxqpAeqM9GSCKd66Wp",
      "chain": "solana",
      "pnl": [
        {
          "realized_pnl": {
            "amount": "0.002335373911312482",
            "currency": "USD"
          },
          "timestamp": "2026-03-19T22:00:00Z",
          "unrealized_pnl": {
            "amount": "0.145848378518889629",
            "currency": "USD"
          }
        },
        {
          "realized_pnl": {
            "amount": "0.002335373911312482",
            "currency": "USD"
          },
          "timestamp": "2026-03-19T23:00:00Z",
          "unrealized_pnl": {
            "amount": "0.137894957302491137",
            "currency": "USD"
          }
        }
      ]
    }
  ]
}
```

Detailed docs (supported chains, edge cases, response format): `GET /api/v1/docs/docs/browse?path=api/developer/holdings/holdings-pnl-history.md`

---

### Fetch current PnL by Wallet & Token

`POST /api/v1/developer/wallet/pnl-by-token`

Get the PnL for a given wallet and token address.

#### Request

**Body:**

| Field | Type | Required | Description |
| ----- | ---- | -------- | ----------- |
| `chain` | string | Yes | Lowercase chain name |
| `address` | string | Yes | Wallet address |
| `token_address` | string | Yes | Token contract address |

**Example:**

```bash
curl -X POST "https://api.allium.so/api/v1/developer/wallet/pnl-by-token" \
  -H "X-API-KEY: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '[{"chain": "...", "address": "...", "token_address": "..."}]'
```

#### Response

| Field | Type | Always present | Description |
| ----- | ---- | -------------- | ----------- |
| `items[].chain` | string | Yes | Lowercase chain name |
| `items[].address` | string | Yes | Wallet address |
| `items[].token_address` | string | Yes | Token contract address |
| `items[].current_tokens` | string | Yes | Current token balance (native units) |
| `items[].current_balance` | object | Yes | Current token balance (USD) |
| `items[].current_balance.currency` | string | No | Currency code |
| `items[].current_balance.amount` | string | Yes | Value in the specified currency |
| `items[].current_price` | object | Yes | Current token price (USD) |
| `items[].current_price.currency` | string | No | Currency code |
| `items[].current_price.amount` | string | Yes | Value in the specified currency |
| `items[].unrealized_pnl` | object or null | No | Unrealized PnL (USD) |
| `items[].unrealized_pnl.currency` | string | No | Currency code |
| `items[].unrealized_pnl.amount` | string | Yes | Value in the specified currency |
| `items[].realized_pnl` | object or null | No | Realized PnL (USD) |
| `items[].realized_pnl.currency` | string | No | Currency code |
| `items[].realized_pnl.amount` | string | Yes | Value in the specified currency |
| `items[].average_cost` | object or null | No | Average cost basis (USD) |
| `items[].average_cost.currency` | string | No | Currency code |
| `items[].average_cost.amount` | string | Yes | Value in the specified currency |
| `items[].unrealized_pnl_ratio_change` | number or null | No | Unrealized PnL ratio change (decimal) |
| `items[].attributes` | object or null | No | Token attributes |
| `items[].attributes.total_liquidity_usd` | object or null | No | Liquidity data: {'amount': number} when available, or {'details': 'LIQUIDITY_TOO_HIGH'} when limit exceeded |
| `items[].attributes.total_liquidity_usd.amount` | number or null | No | Liquidity amount (USD) |
| `items[].attributes.total_liquidity_usd.details` | string or null | No | Status when amount unavailable (e.g. LIQUIDITY_TOO_HIGH) |
| `items[].attributes.price_diff_1d` | number or null | No | Price change (USD) over last 24h |
| `items[].attributes.price_diff_pct_1d` | number or null | No | Price change (%) over last 24h |
| `items[].attributes.price_diff_1h` | number or null | No | Price change (USD) over last 1h |
| `items[].attributes.price_diff_pct_1h` | number or null | No | Price change (%) over last 1h |
| `items[].attributes.total_supply` | number or null | No | Total token supply |
| `items[].attributes.fully_diluted_valuation_usd` | number or null | No | Fully diluted valuation (USD) |
| `items[].attributes.volume_1h` | number or null | No | Trading volume over last 1h |
| `items[].attributes.volume_1d` | number or null | No | Trading volume over last 24h |
| `items[].attributes.volume_usd_1h` | number or null | No | Trading volume (USD) over last 1h |
| `items[].attributes.volume_usd_1d` | number or null | No | Trading volume (USD) over last 24h |
| `items[].attributes.volume_24h` | number or null | No | Trading volume over last 24h |
| `items[].attributes.volume_usd_24h` | number or null | No | Trading volume (USD) over last 24h |
| `items[].attributes.trade_count_1h` | integer or null | No | Trade count over last 1h |
| `items[].attributes.trade_count_1d` | integer or null | No | Trade count over last 24h |
| `items[].attributes.all_time_high` | number or null | No | All-time high price (USD) |
| `items[].attributes.all_time_low` | number or null | No | All-time low price (USD) |
| `items[].attributes.image_url` | string or null | No | Token logo URL |
| `items[].attributes.token_creation_time` | string or null | No | Token creation timestamp (UTC) |
| `items[].attributes.holders_count` | integer or null | No | Number of token holders |
| `items[].attributes.stellar_fields` | object or null | No | Stellar-specific metadata |
| `items[].historical_breakdown` | array of objects or null | No | Historical breakdown of the token transactions |
| `items[].historical_breakdown[].trade` | object | Yes | Trade details |
| `items[].historical_breakdown[].trade.token_address` | string | Yes | Token contract address |
| `items[].historical_breakdown[].trade.token_amount` | string | Yes | Amount of tokens traded (native units) |
| `items[].historical_breakdown[].trade.token_price_usd` | string or null | No | Token price at time of trade (USD) |
| `items[].historical_breakdown[].trade.timestamp` | string | Yes | Trade execution time (UTC) |
| `items[].historical_breakdown[].average_cost` | object or null | No | Average cost basis after this trade in USD |
| `items[].historical_breakdown[].average_cost.currency` | string | No | Currency code |
| `items[].historical_breakdown[].average_cost.amount` | string | Yes | Value in the specified currency |
| `items[].historical_breakdown[].realized_pnl` | object | Yes | Realized PnL from this trade in USD |
| `items[].historical_breakdown[].realized_pnl.currency` | string | No | Currency code |
| `items[].historical_breakdown[].realized_pnl.amount` | string | Yes | Value in the specified currency |

Detailed docs (supported chains, edge cases, response format): `GET /api/v1/docs/docs/browse?path=api/developer/holdings/holdings-pnl-by-token.md`

---

### Fetch historical PnL by Wallet & Token

`POST /api/v1/developer/wallet/pnl-by-token/history`

Get the Historical PnL for a given wallet address and token address.

#### Request

**Body:**

| Field | Type | Required | Description |
| ----- | ---- | -------- | ----------- |
| `start_timestamp` | string | Yes | Start of time range (UTC ISO 8601) |
| `end_timestamp` | string | Yes | End of time range (UTC ISO 8601) |
| `granularity` | string | Yes | Time interval granularity (1d, 1h, 5m, 1m, 15s) |
| `addresses` | array of objects | Yes | List of wallet chain+address+token triples |

**Example:**

```bash
curl -X POST "https://api.allium.so/api/v1/developer/wallet/pnl-by-token/history" \
  -H "X-API-KEY: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "addresses": [
      {
        "address": "125Z6k4ZAxsgdG7JxrKZpwbcS1rxqpAeqM9GSCKd66Wp",
        "chain": "solana",
        "token_address": "So11111111111111111111111111111111111111112"
      }
    ],
    "end_timestamp": "2025-04-10T00:00:00Z",
    "granularity": "1h",
    "start_timestamp": "2025-04-01T00:00:00Z"
  }'
```

#### Response

| Field | Type | Always present | Description |
| ----- | ---- | -------------- | ----------- |
| `items[].chain` | string | Yes | Lowercase chain name |
| `items[].address` | string | Yes | Wallet address |
| `items[].token_address` | string | Yes | Token contract address |
| `items[].pnl` | array of objects | Yes | PnL snapshots per time interval |
| `items[].pnl[].timestamp` | string | Yes | Interval start time (UTC) |
| `items[].pnl[].unrealized_pnl` | object | Yes | Unrealized PnL at this interval (USD) |
| `items[].pnl[].unrealized_pnl.currency` | string | No | Currency code |
| `items[].pnl[].unrealized_pnl.amount` | string | Yes | Value in the specified currency |
| `items[].pnl[].realized_pnl` | object | Yes | Cumulative realized PnL at this interval (USD) |
| `items[].pnl[].realized_pnl.currency` | string | No | Currency code |
| `items[].pnl[].realized_pnl.amount` | string | Yes | Value in the specified currency |

Detailed docs (supported chains, edge cases, response format): `GET /api/v1/docs/docs/browse?path=api/developer/holdings/holdings-pnl-by-token-history.md`
