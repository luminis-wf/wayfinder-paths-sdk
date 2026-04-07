# Assets API Reference

**Base URL:** `https://api.allium.so`
**Auth:** `X-API-KEY` header

---

### List assets

`GET /api/v1/developer/assets`

List assets.

#### Request

**Query parameters:**

| Field | Type | Required | Description |
| ----- | ---- | -------- | ----------- |
| `cursor` | string | No | Cursor for pagination |
| `limit` | integer | No | Number of results per page (default: `100`) |

**Example:**

```bash
curl -X GET "https://api.allium.so/api/v1/developer/assets" \
  -H "X-API-KEY: $API_KEY"
```

#### Response

| Field | Type | Always present | Description |
| ----- | ---- | -------------- | ----------- |
| `items[].id` | integer | Yes | Unique asset identifier |
| `items[].slug` | string | Yes | URL-friendly asset identifier |
| `items[].source` | string | Yes | Data source (e.g. allium) |
| `items[].chain_specific_data` | object | Yes | Per-chain contract addresses and decimals |
| `items[].name` | string | Yes | Token name |
| `items[].symbol` | string | Yes | Token symbol |
| `items[].image_url` | string or null | No | Token logo URL |
| `items[].circulating_supply` | number or null | No | Circulating token supply |
| `items[].token_creation_time` | string or null | No | Token creation timestamp (UTC) |

Detailed docs (supported chains, edge cases, response format): `GET /api/v1/docs/docs/browse?path=api/developer/assets/list-assets.md`

---

### Get assets

`POST /api/v1/developer/assets/batch`

Get assets by ID, slug, or (chain, address).

#### Request

**Body:**

| Field | Type | Required | Description |
| ----- | ---- | -------- | ----------- |
| `id` | integer or null | No | Asset ID to look up |
| `slug` | string or null | No | Asset slug to look up |
| `chain` | string or null | No | Lowercase chain name (required with address) |
| `address` | string or null | No | Token contract address |

**Example:**

```bash
curl -X POST "https://api.allium.so/api/v1/developer/assets/batch" \
  -H "X-API-KEY: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '[{"id": "...", "slug": "...", "chain": "...", "address": "..."}]'
```

#### Response

| Field | Type | Always present | Description |
| ----- | ---- | -------------- | ----------- |
| `[].id` | integer | Yes | Unique asset identifier |
| `[].slug` | string | Yes | URL-friendly asset identifier |
| `[].source` | string | Yes | Data source (e.g. allium) |
| `[].chain_specific_data` | object | Yes | Per-chain contract addresses and decimals |
| `[].name` | string | Yes | Token name |
| `[].symbol` | string | Yes | Token symbol |
| `[].image_url` | string or null | No | Token logo URL |
| `[].circulating_supply` | number or null | No | Circulating token supply |
| `[].token_creation_time` | string or null | No | Token creation timestamp (UTC) |

Detailed docs (supported chains, edge cases, response format): `GET /api/v1/docs/docs/browse?path=api/developer/assets/get-assets.md`
