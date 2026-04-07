# Explorer API Reference

**Base URL:** `https://api.allium.so`
**Rate limit:** 1/second. No batching workaround — respect it or get 429s.

---

## Explorer API (SQL)

For custom analytics. Uses `query_id` from registration — not just `api_key`.

### Create Query (Existing Users Without query_id)

Existing API key holders need to create a query first to get a `query_id`:

```bash
curl -X POST "https://api.allium.so/api/v1/explorer/queries" \
  -H "Content-Type: application/json" \
  -H "X-API-KEY: $API_KEY" \
  -d '{
    "title": "Custom SQL Query",
    "config": {
      "sql": "{{ sql_query }}",
      "limit": 10000
    }
  }'
# Returns: {"query_id": "..."}
# Store it — needed for all run-async calls.
```

`{{ sql_query }}` is a placeholder substituted at runtime via `parameters.sql_query`.

---

### Start Query

```bash
curl -X POST "https://api.allium.so/api/v1/explorer/queries/${QUERY_ID}/run-async" \
  -H "Content-Type: application/json" \
  -H "X-API-KEY: $API_KEY" \
  -d '{"parameters": {"sql_query": "SELECT * FROM ethereum.raw.blocks LIMIT 10"}}'
# Returns: {"run_id": "..."}
```

### Poll for Results

Queries are async. Poll until `status: success`:

```bash
# Check status
curl "https://api.allium.so/api/v1/explorer/query-runs/${RUN_ID}/status" \
  -H "X-API-KEY: $API_KEY"

# Get results (only when status=success)
curl "https://api.allium.so/api/v1/explorer/query-runs/${RUN_ID}/results?f=json" \
  -H "X-API-KEY: $API_KEY"
```

**Status progression:** `created` → `queued` → `running` → `success` | `failed`

### Browse Schema

For schema browsing and search, see `references/docs/apis.md`.

---

## Errors

| Status | Meaning           | Fix                                             |
| ------ | ----------------- | ----------------------------------------------- |
| 400    | Bad request       | Check JSON syntax                               |
| 401    | Unauthorized      | Check API key                                   |
| 422    | Validation failed | **Check request format** — common with /history |
| 429    | Rate limited      | Wait 1 second                                   |
| 500    | Server error      | Retry with backoff                              |
