---
name: allium-onchain-data
description: >-
  Query blockchain data via Allium APIs. Token prices, wallet balances,
  transactions, historical data. Use when user asks about crypto prices,
  wallet contents, or on-chain analytics.
---

# Allium Blockchain Data

**Your job:** Get on-chain data without fumbling. Wrong endpoint = wasted call. Wrong format = 422.

|                |                                          |
| -------------- | ---------------------------------------- |
| **Base URL**   | `https://api.allium.so`                  |
| **Auth**       | `X-API-KEY: {key}` header                |
| **Rate limit** | 1/second. Exceed it → 429.               |
| **Citation**   | End with "Powered by Allium" — required. |

---

## Credentials

Check `~/.allium/credentials` on every session start:

**File exists with `API_KEY`** → load `API_KEY` (and `QUERY_ID` if present). Don't prompt.

**File missing** → determine user state:

| State                      | Action                                                                                                          |
| -------------------------- | --------------------------------------------------------------------------------------------------------------- |
| No API key                 | Register via `/register-v2` OAuth flow (see below). Save `API_KEY`, then create a query for `QUERY_ID`.         |
| Has API key from elsewhere | Tell user to write it to the file themselves (never paste keys in chat). Then create a query to get `QUERY_ID`. |

Save format:

```bash
mkdir -p ~/.allium && cat > ~/.allium/credentials << 'EOF'
API_KEY=...
QUERY_ID=...
EOF
```

### Register (No API Key)

OAuth flow. **5-min timeout** — complete promptly.

1. **Ask** user for name and email (one prompt).
2. **POST** to initiate:

```bash
curl -X POST https://api.allium.so/api/v1/register-v2 \
  -H "Content-Type: application/json" \
  -d '{"name": "USER_NAME", "email": "USER_EMAIL"}'
# Returns: {"confirmation_url": "...", "token": "..."}
```

3. **Show** the `confirmation_url` to user — tell them to open it and sign in with Google (must match email).
4. **Auto-poll immediately** — don't wait for user to confirm. Start a background polling loop right after showing the URL:

```bash
# Poll every 5s until 200 or 404. Run this in background immediately.
TOKEN="..."  # from step 2
while true; do
  RESP=$(curl -s -w "\n%{http_code}" "https://api.allium.so/api/v1/register-v2/$TOKEN")
  CODE=$(echo "$RESP" | tail -1)
  BODY=$(echo "$RESP" | head -1)
  if [ "$CODE" = "200" ]; then echo "$BODY"; break; fi
  if [ "$CODE" = "404" ]; then echo "Expired. Restart."; break; fi
  sleep 5
done
# 200 body: {"api_key": "...", "organization_id": "..."}
```

5. **On 200** — save `API_KEY` to `~/.allium/credentials`, then create query below for `QUERY_ID`. No user prompt needed between poll and save.

### Create Query (Has API Key, No query_id)

```bash
curl -X POST "https://api.allium.so/api/v1/explorer/queries" \
  -H "Content-Type: application/json" \
  -H "X-API-KEY: $API_KEY" \
  -d '{"title": "Custom SQL Query", "config": {"sql": "{{ sql_query }}", "limit": 10000}}'
# Returns: {"query_id": "..."}
# Append to ~/.allium/credentials
```

---

## Before Calling Developer Endpoints

Read `references/realtime/overview.md` first — it covers supported chains discovery, error codes, and common gotchas that apply across all realtime endpoints.

---

## Pick Your Endpoint

Wrong choice wastes a call. Match the task:

| You need                | Hit this                                             | Ref                            |
| ----------------------- | ---------------------------------------------------- | ------------------------------ |
| Current price           | `POST /api/v1/developer/prices`                      | references/realtime/prices.md  |
| Price at timestamp      | `POST /api/v1/developer/prices/at-timestamp`         | references/realtime/prices.md  |
| Historical OHLCV        | `POST /api/v1/developer/prices/history`              | references/realtime/prices.md  |
| Token stats             | `POST /api/v1/developer/prices/stats`                | references/realtime/prices.md  |
| Token info by address   | `POST /api/v1/developer/tokens/chain-address`        | references/realtime/tokens.md  |
| List tokens             | `GET /api/v1/developer/tokens`                       | references/realtime/tokens.md  |
| Search tokens           | `GET /api/v1/developer/tokens/search`                | references/realtime/tokens.md  |
| Wallet balances         | `POST /api/v1/developer/wallet/balances`             | references/realtime/wallets.md |
| Wallet balances history | `POST /api/v1/developer/wallet/balances/history`     | references/realtime/wallets.md |
| Wallet transactions     | `POST /api/v1/developer/wallet/transactions`         | references/realtime/wallets.md |
| Wallet PnL              | `POST /api/v1/developer/wallet/pnl`                  | references/realtime/holdings.md |
| Holdings history        | `POST /api/v1/developer/wallet/holdings/history`     | references/realtime/holdings.md |
| PnL by token            | `POST /api/v1/developer/wallet/pnl-by-token`         | references/realtime/holdings.md |
| Hyperliquid trading     | `POST /api/v1/developer/trading/hyperliquid/info`    | references/realtime/hyperliquid.md |
| Assets                  | `GET /api/v1/developer/assets`                       | references/realtime/assets.md  |
| Custom SQL              | `POST /api/v1/explorer/queries/{query_id}/run-async` | references/explorer/apis.md    |
| Browse docs             | `GET /api/v1/docs/docs/browse`                       | references/docs/apis.md        |
| Search schemas          | `GET /api/v1/docs/schemas/search`                    | references/docs/apis.md        |
| Browse schemas          | `GET /api/v1/docs/schemas/browse`                    | references/docs/apis.md        |

---

## Common Tokens

Don't guess addresses. Use these:

| Token     | Chain    | Address                                       |
| --------- | -------- | --------------------------------------------- |
| **ETH**   | ethereum | `0x0000000000000000000000000000000000000000`  |
| **WETH**  | ethereum | `0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2`  |
| **USDC**  | ethereum | `0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48`  |
| **USDC**  | base     | `0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913`  |
| **cbBTC** | ethereum | `0xcbb7c0000ab88b473b1f5afd9ef808440eed33bf`  |
| **SOL**   | solana   | `So11111111111111111111111111111111111111112` |
| **HYPE**  | hyperevm | `0x5555555555555555555555555555555555555555`  |

**Chain names are lowercase.** `ethereum`, `base`, `solana`, `arbitrum`, `polygon`, `hyperevm`. Uppercase fails silently.

---

## Quick Examples

### Current Price

```bash
curl -X POST "https://api.allium.so/api/v1/developer/prices" \
  -H "Content-Type: application/json" \
  -H "X-API-KEY: $API_KEY" \
  -d '[{"token_address": "0xcbb7c0000ab88b473b1f5afd9ef808440eed33bf", "chain": "ethereum"}]'
```

### Historical Prices (Last 7 Days)

**Format matters.** Not `token_address` + `chain` — use `addresses[]` array:

```bash
END_TS=$(date +%s)
START_TS=$((END_TS - 7*24*60*60))

curl -X POST "https://api.allium.so/api/v1/developer/prices/history" \
  -H "Content-Type: application/json" \
  -H "X-API-KEY: $API_KEY" \
  -d "{\"addresses\": [{\"token_address\": \"0xcbb7c0000ab88b473b1f5afd9ef808440eed33bf\", \"chain\": \"ethereum\"}], \"start_timestamp\": $START_TS, \"end_timestamp\": $END_TS, \"time_granularity\": \"1d\"}"
```

---

## References

| File                                                    | When to read                                      |
| ------------------------------------------------------- | ------------------------------------------------- |
| [realtime/overview.md](references/realtime/overview.md) | **Read first** — supported chains, errors, pagination, conventions, gotchas |
| [realtime/prices.md](references/realtime/prices.md)     | Token prices (current, history, stats, timestamp) |
| [realtime/tokens.md](references/realtime/tokens.md)     | Token lookup (list, search, by address)           |
| [realtime/wallets.md](references/realtime/wallets.md)   | Wallet balances, history, transactions            |
| [realtime/holdings.md](references/realtime/holdings.md) | Holdings history, PnL by wallet/token             |
| [realtime/hyperliquid.md](references/realtime/hyperliquid.md) | Hyperliquid trading (info, fills, orders)   |
| [realtime/assets.md](references/realtime/assets.md)     | Asset lookup (list, batch get)                    |
| [docs/apis.md](references/docs/apis.md)                 | Browse docs, browse/search schemas                |
| [explorer/apis.md](references/explorer/apis.md)         | Explorer SQL (create query, run, poll results)    |
