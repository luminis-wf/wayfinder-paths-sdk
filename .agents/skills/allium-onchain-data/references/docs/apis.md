# Documentation & Schema Discovery API Reference

**Base URL:** `https://api.allium.so`
**Auth:** `X-API-KEY` header

| Endpoint                      | Method | Purpose                                |
| ----------------------------- | ------ | -------------------------------------- |
| `/api/v1/docs/docs/browse`    | GET    | Browse doc hierarchy like a filesystem |
| `/api/v1/docs/schemas/browse` | GET    | Browse databases → schemas → tables    |
| `/api/v1/docs/schemas/search` | GET    | Semantic search for table names        |

---

## Browse Docs

Browse the documentation like a filesystem. Use this to get detailed endpoint docs including supported chains, edge cases, and response formats.

```bash
# List root directories
curl "https://api.allium.so/api/v1/docs/docs/browse?path=" -H "X-API-KEY: $API_KEY"

# List files in a directory
curl "https://api.allium.so/api/v1/docs/docs/browse?path=api/developer" -H "X-API-KEY: $API_KEY"

# Get detailed docs for a specific endpoint
curl "https://api.allium.so/api/v1/docs/docs/browse?path=api/developer/prices/token-latest-price.md" -H "X-API-KEY: $API_KEY"
```

Each realtime API endpoint has a corresponding docs page. The path is listed in each endpoint's reference file (e.g. `references/realtime/prices.md`). Use it to get supported chains, edge cases, and full response schemas before calling an unfamiliar endpoint.

---

## Browse Schemas

Browse database schemas for use with Explorer SQL queries. Don't guess table names.

```bash
# List all databases
curl "https://api.allium.so/api/v1/docs/schemas/browse?path=" -H "X-API-KEY: $API_KEY"

# List tables in a schema
curl "https://api.allium.so/api/v1/docs/schemas/browse?path=ethereum.raw" -H "X-API-KEY: $API_KEY"

# Get full table details (columns, types)
curl "https://api.allium.so/api/v1/docs/schemas/browse?path=ethereum.raw.blocks" -H "X-API-KEY: $API_KEY"
```

---

## Search Schemas

Find tables by meaning, not exact name:

```bash
curl "https://api.allium.so/api/v1/docs/schemas/search?q=DEX+trades+swaps" -H "X-API-KEY: $API_KEY"
```

Returns table name matches. Feed these into Browse Schemas for column details.
