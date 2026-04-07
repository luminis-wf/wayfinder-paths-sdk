# Realtime API Overview

**Base URL:** `https://api.allium.so`
**Auth:** `X-API-KEY` header
**Rate limit:** 1/second. Exceed it → 429.

---

## Supported Chains Discovery

**Call once per session** before any `/developer/` endpoint. Returns all endpoints and their chains in one response — cache it, don't re-call.

```bash
curl "https://api.allium.so/api/v1/supported-chains/realtime-apis/simple"
```

**Response:** Map of endpoint path → array of supported chain names.

```json
{
  "/api/v1/developer/prices": ["arbitrum", "avalanche", "bsc", "base", "ethereum", "solana", ...],
  "/api/v1/developer/prices/at-timestamp": ["arbitrum", "avalanche", "bsc", "base", "ethereum", "solana", ...],
  "/api/v1/developer/prices/history": ["arbitrum", "avalanche", "bsc", "base", "ethereum", "solana", ...],
  "/api/v1/developer/prices/stats": ["arbitrum", "avalanche", "bsc", "base", "ethereum", "solana", ...],
  "/api/v1/developer/wallet/balances": ["arbitrum", "base", "bitcoin", "ethereum", "solana", ...],
  "/api/v1/developer/wallet/balances/history": ["arbitrum", "base", "bitcoin", "ethereum", "solana", ...],
  "/api/v1/developer/wallet/transactions": ["abstract", "arbitrum", "ethereum", "solana", ...],
  "/api/v1/developer/wallet/holdings/history": ["arbitrum", "avalanche", "base", "bitcoin", "ethereum", "solana", ...],
  "/api/v1/developer/wallet/pnl": ["arbitrum", "avalanche", "base", "ethereum", "solana", ...],
  "/api/v1/developer/wallet/pnl/history": ["arbitrum", "avalanche", "base", "ethereum", "solana", ...],
  "/api/v1/developer/wallet/pnl-by-token": ["arbitrum", "avalanche", "base", "ethereum", "solana", ...],
  "/api/v1/developer/wallet/pnl-by-token/history": ["arbitrum", "avalanche", "base", "ethereum", "solana", ...],
  "/api/v1/developer/tokens": ["arbitrum", "avalanche", "base", "ethereum", "solana", ...],
  "/api/v1/developer/tokens/search": ["arbitrum", "avalanche", "base", "ethereum", "solana", ...],
}
```

Use this to validate chain support before making data calls. Chain coverage varies per endpoint — e.g. `pnl` only supports 3 chains while `transactions` supports 20+.

---

## Errors

| Status | Meaning           | Fix                                             |
| ------ | ----------------- | ----------------------------------------------- |
| 400    | Bad request       | Check JSON syntax                               |
| 401    | Unauthorized      | Check API key                                   |
| 422    | Validation failed | **Check request format** — common with /history |
| 429    | Rate limited      | Wait 1 second                                   |
| 500    | Server error      | Retry with backoff                              |

---

## Pagination

| Endpoint | Paginates? | Mechanism | Max page size |
|---|---|---|---|
| `POST /developer/prices` | No | All results returned. Batch via multiple `chain`/`token-address` pairs in `addresses` request body field. | N/A |
| `POST /developer/prices/at-timestamp` | No | All results returned. Batch via multiple `chain`/`token-address` pairs in `addresses` request body field. | N/A |
| `POST /developer/prices/history` | Yes | Paginated via `cursor` query parameters | N/A |
| `POST /developer/prices/stats` | No | All results returned. Batch via multiple `chain`/`token-address` pairs in `addresses` request body field. | N/A |
| `POST /developer/tokens/chain-address` | No | N/A — send multiple tokens in array | N/A |
| `GET /developer/tokens` | No | `limit` query params | 200 |
| `GET /developer/tokens/search` | No | `limit` query param | 200 |
| `POST /developer/wallet/balances` | No | All results returned. Batch via multiple `chain`/`address` pairs in `addresses` request body field. | N/A |
| `POST /developer/wallet/balances/history` | Yes | Paginated via `limit` + `cursor` query parameters | N/A |
| `POST /developer/wallet/holdings/history` | No | All results returned. Batch via multiple `chain`/`address` pairs in `addresses` request body field. | N/A |
| `POST /developer/wallet/transactions` | Yes | Paginated via `limit` + `cursor` query parameters | N/A |
| `POST /developer/wallet/pnl` | No | All results returned. Batch via multiple `chain`/`address` pairs in `addresses` request body field. | N/A |
| `POST /developer/wallet/pnl/history` | No | All results returned. Batch via multiple `chain`/`address` pairs in `addresses` request body field. | N/A |
| `POST /developer/wallet/pnl-by-token` | No | All results returned. Batch via multiple `chain`/`address`/`token-address` triples in `addresses` request body field. | N/A |
| `POST /developer/wallet/pnl-by-token/history` | No | All results returned. Batch via multiple `chain`/`address`/`token-address` triples in `addresses` request body field. | N/A |

**How to detect more results:**

1. For paginated commands, if the `cursor` field in the response is not None, there are more pages to fetch. When number of items returned is 0 or `cursor` field is None, that means we have fetched all results. Use the non-null `cursor` field in the response and pass `limit` and `cursor` as query parameters to fetch the next page.

2. For historical prices pagination, `limit` parameter is not provided. Keep calling with the newly returned cursor until `cursor` in the response is None, which means all results have been fetched.

---

## Conventions

These apply to all `/developer/` endpoints:

- **Money amounts:** `{ "currency": "USD", "amount": "string" }` — `amount` is a string for arbitrary precision (e.g. `"138.681338640813260490"`). Never parse as float for financial calculations.
- **Timestamps:** Responses use ISO 8601 UTC. Requests accept ISO 8601 strings — see [Timestamp Formats](#timestamp-formats).
- **Nullable fields:** Present in the response but set to `null`, sometimes omitted. Not safe to access without key-existence checks.
- **Naming:** `mint` in price history responses = `token_address` in requests = `address` in other responses. All three mean the on-chain contract address.

> **AI agent guidance:** Always use ISO 8601 strings (e.g. `"2025-12-25T00:00:00Z"`).
> Never compute Unix timestamps manually — LLMs routinely miscalculate them.

- **In requests:** Use ISO 8601 UTC strings (e.g. `"2024-01-30T00:00:00Z"`).
- **In responses:** Always ISO 8601 UTC format (`"2024-01-30T00:00:00Z"`).

---

## Common Gotchas

- **Chain names are lowercase.** `ethereum`, `base`, `solana`, `arbitrum`, `polygon`, `hyperevm`. Uppercase fails silently.
- **Different endpoints have different body formats.** `/prices` takes an array of `{token_address, chain}`. `/prices/history` takes an object with `addresses`, `start_timestamp`, `end_timestamp`, `time_granularity`. Don't copy-paste between them — it will 422.
- **Timestamps are Unix seconds** for most endpoints (not milliseconds). Hyperliquid endpoints use milliseconds.
- **Pagination:** Most list/history endpoints support `cursor` for pagination. Check the endpoint reference for specifics.
