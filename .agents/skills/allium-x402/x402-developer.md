---
name: allium-x402-developer
description: >-
  Realtime blockchain data: token prices, wallet balances, transactions,
  PnL, and token search via the allium CLI.
refetch_after: 30d
---

# Allium Realtime APIs

Use `allium realtime` when the user needs **current or recent** data — live prices, wallet snapshots, token lookups. Fast, indexed, up-to-date.

**When to use Realtime vs Explorer:**

| Realtime (this skill)                     | Explorer (x402-explorer.md)                        |
| ----------------------------------------- | -------------------------------------------------- |
| "What's ETH worth right now?"             | "How did ETH perform over the last year?"           |
| "Show my wallet balances"                 | "What's the total value locked across all chains?"  |
| "Get the price of SOL 2 hours ago"        | "Find the top 10 wallets by volume last month"      |
| "List all tokens on Base"                 | "Compare daily active addresses across L2s"         |
| "What's my PnL on this wallet?"           | "Custom SQL on any table"                           |
| Fast, indexed, latest state               | Analytical, aggregated, historical                  |

---

## Commands

### Prices

**Latest price:**

```bash
allium realtime prices latest \
  --chain ethereum --token-address 0x0000000000000000000000000000000000000000 \
  --chain base --token-address 0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913
```

Multiple `--chain`/`--token-address` pairs in one call for batching.

**Price at a specific time:**

```bash
allium realtime prices at-timestamp \
  --chain ethereum --token-address 0x0000000000000000000000000000000000000000 \
  --timestamp 2026-01-15T12:00:00Z \
  --time-granularity 1h
```

Granularity options: `15s`, `1m`, `5m`, `1h`, `1d`.

**Price history (range):**

```bash
allium realtime prices history \
  --chain ethereum --token-address 0x0000000000000000000000000000000000000000 \
  --start-timestamp 2026-03-10T00:00:00Z \
  --end-timestamp 2026-03-17T00:00:00Z \
  --time-granularity 1h
```

**24h / 1h stats:**

```bash
allium realtime prices stats \
  --chain ethereum --token-address 0x0000000000000000000000000000000000000000
```

Returns high, low, volume, trade count, and percent change.

---

### Tokens

**Search by name/ticker:**

```bash
allium realtime tokens search -q bitcoin --limit 10
```

Optional `--chain` filter.

**Lookup by chain + address:**

```bash
allium realtime tokens chain-address \
  --chain ethereum --token-address 0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2
```

**List top tokens:**

```bash
allium realtime tokens list --chain ethereum --sort volume --order desc --limit 20
```

Sort options: `volume`, `trade_count`, `fully_diluted_valuation`, `address`, `name`.

---

### Wallet Balances

**Current balances:**

```bash
allium realtime balances latest \
  --chain ethereum --address 0x...
```

**Historical snapshots:**

```bash
allium realtime balances history \
  --chain ethereum --address 0x... \
  --start-timestamp 2026-03-01T00:00:00Z \
  --end-timestamp 2026-03-17T00:00:00Z \
  --limit 100
```

---

### Transactions

```bash
allium realtime transactions \
  --chain ethereum --address 0x... \
  --lookback-days 7 \
  --limit 50
```

Optional `--activity-type` filter (e.g. `dex_trade`, `transfer`).

---

### Holdings

**Historical Holdings:**

```bash
allium realtime holdings history \
  --chain ethereum --address 0x... \
  --start-timestamp 2026-03-01T00:00:00Z \
  --end-timestamp 2026-03-17T00:00:00Z \
  --granularity 1d \
  --limit 100
```

Granularity options: `15s`, `1m`, `5m`, `1h`, `1d`.

---

### Profit & Loss

**Current PnL:**

```bash
allium realtime pnl \
  --chain ethereum --address 0x...
```

**Historical PnL:**

```bash
allium realtime pnl history \
  --chain ethereum --address 0x... \
  --start-timestamp 2026-03-01T00:00:00Z \
  --end-timestamp 2026-03-17T00:00:00Z \
  --granularity 1d \
  --limit 100
```

Granularity options: `15s`, `1m`, `5m`, `1h`, `1d`.

---

## Response Format

All commands output JSON by default. Use `--format table` for human-readable output or `--format csv` for spreadsheets.

### Price response structure

```json
{
  "items": [{
    "timestamp": "2026-03-17T12:00:00Z",
    "chain": "ethereum",
    "address": "0x0000000000000000000000000000000000000000",
    "decimals": 18,
    "price": 1946.49,
    "open": 1943.28,
    "high": 1946.49,
    "low": 1942.69,
    "close": 1946.49
  }]
}
```

Access: `items[0].price` — NOT the top level.

### Price history — nested structure

```json
{
  "items": [{
    "mint": "0x...",
    "chain": "ethereum",
    "prices": [{
      "timestamp": "2026-03-10T00:00:00Z",
      "open": 1900.00,
      "high": 1950.00,
      "low": 1880.00,
      "close": 1940.00,
      "price": 1925.00
    }]
  }]
}
```

Access: `items[0].prices` — note the nested `prices` array.


### PnL response structure

```json
{
    "items": [
        {
            "chain": "solana",
            "address": "3e...",
            "tokens": [
                {
                    "token_address": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
                    "average_cost": {
                        "currency": "USD",
                        "amount": "0.998741156892067249"
                    },
                    "raw_balance": "488.789246",
                    "current_price": {
                        "currency": "USD",
                        "amount": "1.001312436654786531"
                    },
                    "current_balance": {
                        "currency": "USD",
                        "amount": "489.430750922915870637"
                    },
                    "realized_pnl": {
                        "currency": "USD",
                        "amount": "138.681338640813260490"
                    },
                    "unrealized_pnl": {
                        "currency": "USD",
                        "amount": "1.256813896474616383"
                    },
                    "unrealized_pnl_ratio_change": 0.00257452068033395,
                    "attributes": {
                        "total_liquidity_usd": {
                            "details": "LIQUIDITY_TOO_HIGH"
                        }
                    }
                },
                {
                    "token_address": "2YLjY53bLtsJn3Aq2wFHdF2fUeTPqYDcbNPWJ6w9pump",
                    "average_cost": {
                        "currency": "USD",
                        "amount": "0.001000297862358017"
                    },
                    "raw_balance": "85900.15",
                    "current_price": {
                        "currency": "USD",
                        "amount": "0.001000606229732188"
                    },
                    "current_balance": {
                        "currency": "USD",
                        "amount": "85.952225224929403749"
                    },
                    "realized_pnl": {
                        "currency": "USD",
                        "amount": "0E-18"
                    },
                    "unrealized_pnl": {
                        "currency": "USD",
                        "amount": "0.026488803696411861"
                    },
                    "unrealized_pnl_ratio_change": 0.0003082755504888085,
                    "attributes": {
                        "total_liquidity_usd": {
                            "amount": 2001212.5853097588
                        }
                    }
                }
            ],
            "total_balance": {
                "currency": "USD",
                "amount": "575.382976148"
            },
            "total_realized_pnl": {
                "currency": "USD",
                "amount": "138.681338640813260490"
            },
            "total_unrealized_pnl": {
                "currency": "USD",
                "amount": "1.28330270017"
            },
            "total_unrealized_pnl_ratio_change": 0.0022253819
        }
    ]
}
```

Access:
- `items[0]["tokens"]` for PnL of each token owned by the wallet
- `items[0]["total_unrealized_pnl"]` for total unrealized PnL (in USD) of the wallet
- `items[0]["total_realized_pnl"]` for total realized PnL (in USD) of the wallet
- `items[0]["total_balance"]` for total balance (in USD) of the wallet

### PnL history — nested structure

```json
{
    "items": [
        {
            "chain": "solana",
            "address": "3e...",
            "pnl": [
                {
                    "timestamp": "2025-11-04T00:00:00Z",
                    "unrealized_pnl": {
                        "currency": "USD",
                        "amount": "-4643.831342118258219999"
                    },
                    "realized_pnl": {
                        "currency": "USD",
                        "amount": "4477.313380917999945427"
                    }
                },
                {
                    "timestamp": "2025-11-05T00:00:00Z",
                    "unrealized_pnl": {
                        "currency": "USD",
                        "amount": "-5119.419867080520112712"
                    },
                    "realized_pnl": {
                        "currency": "USD",
                        "amount": "4476.494797472309850168"
                    }
                },
                {
                    "timestamp": "2025-11-06T00:00:00Z",
                    "unrealized_pnl": {
                        "currency": "USD",
                        "amount": "-5349.195516643782533032"
                    },
                    "realized_pnl": {
                        "currency": "USD",
                        "amount": "4476.170682321219571894"
                    }
                }
            ]
        }
    ]
}
```

Access: `items[0]["pnl"]` — note the nested `pnl` array.

---

## Endpoint Costs

| Command                          | Cost per call |
| -------------------------------- | ------------- |
| `realtime prices latest`         | $0.02         |
| `realtime prices at-timestamp`   | $0.02         |
| `realtime prices history`        | $0.02         |
| `realtime prices stats`          | $0.02         |
| `realtime tokens search`         | $0.03         |
| `realtime tokens chain-address`  | $0.02         |
| `realtime tokens list`           | $0.03         |
| `realtime balances latest`       | $0.01         |
| `realtime balances history`      | $0.01         |
| `realtime holdings history`      | $0.01         |
| `realtime transactions`          | $0.03         |
| `realtime pnl`                   | $0.01         |
| `realtime pnl history`           | $0.01         |

Batch calls (multiple `--chain`/`--token-address` pairs) cost the same as a single pair.

---

## JSON body override

Every command accepts `--body` to pass a raw JSON payload (inline string or path to `.json` file), overriding individual flags. Useful for complex or pre-built requests.

---

## Cost Tracking

```bash
allium mp cost           # total spend summary
allium mp cost list      # itemized payment history
```

---

## Gotchas

1. **Response access:** Always `items[0]`, never top-level array
2. **Price history:** Different structure — nested `prices` array inside each item
3. **Batch = same price:** Multiple `--chain`/`--token-address` pairs in one call cost the same as one
4. **Chain names:** Always lowercase (`ethereum`, not `Ethereum`)
