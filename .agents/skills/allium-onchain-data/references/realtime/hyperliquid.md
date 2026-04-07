# Hyperliquid API Reference

**Base URL:** `https://api.allium.so`
**Auth:** `X-API-KEY` header

---

### Info

`POST /api/v1/developer/trading/hyperliquid/info`

Hyperliquid API without rate limits.

#### Request

**Body:**

| Field | Type | Required | Description |
| ----- | ---- | -------- | ----------- |
| `type` | string | No | Request type parameter |
| `user` | string | No | User parameter |
| `dex` | string | No | DEX parameter |

**Example:**

```bash
curl -X POST "https://api.allium.so/api/v1/developer/trading/hyperliquid/info" \
  -H "X-API-KEY: $API_KEY" \
  -H "Content-Type: application/json"
```

#### Response

Detailed docs (supported chains, edge cases, response format): `GET /api/v1/docs/docs/browse?path=api/developer/hyperliquid/info.md`

---

### Fills

`POST /api/v1/developer/trading/hyperliquid/info/fills`

Endpoint providing fills by user address

#### Request

**Body:**

| Field | Type | Required | Description |
| ----- | ---- | -------- | ----------- |
| `type` | string | Yes | Type of fills to retrieve. Applies to all request types. |
| `user` | string | Yes | User's wallet address (hex string). Applies to all request types. |
| `startTime` | integer | No | Start time filter (Unix timestamp in milliseconds). Required for userFillsByTime. Only applies to userFillsByTime. |
| `endTime` | integer | No | End time filter (Unix timestamp in milliseconds). Only applies to userFillsByTime. |
| `aggregateByTime` | boolean | No | When true, aggregates multiple fills from the same order at the same timestamp into a single fill with combined size, weighted average price, and summed fees/PnL. Only applies to userFills and userFillsByTime. |
| `twapMode` | string | No | Controls TWAP fill filtering: 'none' (default) excludes TWAP fills, 'include' returns both regular and TWAP fills, 'only' returns only TWAP fills. Only applies to userFills and userFillsByTime. |

**Example:**

```bash
curl -X POST "https://api.allium.so/api/v1/developer/trading/hyperliquid/info/fills" \
  -H "X-API-KEY: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "type": "...",
    "user": "..."
  }'
```

#### Response

| Field | Type | Always present | Description |
| ----- | ---- | -------------- | ----------- |
| `[].closedPnl` | string | No | Realized PnL from closing a position with this fill |
| `[].coin` | string | No | Trading pair symbol (e.g., BTC, ETH) |
| `[].crossed` | boolean | No | Whether the order crossed the spread (i.e., was a taker order) |
| `[].dir` | string | No | Direction description (e.g., Open Long, Close Short, Buy, Sell) |
| `[].hash` | string | No | Transaction hash |
| `[].oid` | integer | No | Order ID |
| `[].px` | string | No | Execution price |
| `[].side` | string | No | Order side: B (buy) or A (sell) |
| `[].startPosition` | string | No | Position size before this fill was executed |
| `[].sz` | string | No | Fill size |
| `[].time` | integer | No | Fill timestamp (Unix timestamp in milliseconds) |
| `[].fee` | string | No | Trading fee amount |
| `[].feeToken` | string | No | Token used for fee payment |
| `[].tid` | integer | No | Unique trade ID |
| `[].liquidation` | any | No | Present only for liquidation fills. Contains liquidation details |
| `[].builderFee` | string | No | Builder fee if order was routed through a builder |
| `[].builderAddress` | string | No | Address of the builder if applicable |
| `[].twapId` | integer | No | TWAP order ID if this fill is part of a TWAP order |

Detailed docs (supported chains, edge cases, response format): `GET /api/v1/docs/docs/browse?path=api/developer/hyperliquid/fills.md`

---

### Order history

`POST /api/v1/developer/trading/hyperliquid/info/order/history`

Endpoint providing order history by user address

#### Request

**Body:**

| Field | Type | Required | Description |
| ----- | ---- | -------- | ----------- |
| `type` | string | Yes | Request type - must be 'historicalOrders' |
| `user` | string | Yes | User's wallet address (hex string) |
| `startTime` | integer | No | Start time filter (Unix timestamp in milliseconds) |
| `endTime` | integer | No | End time filter (Unix timestamp in milliseconds) |

**Example:**

```bash
curl -X POST "https://api.allium.so/api/v1/developer/trading/hyperliquid/info/order/history" \
  -H "X-API-KEY: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "type": "...",
    "user": "..."
  }'
```

#### Response

| Field | Type | Always present | Description |
| ----- | ---- | -------------- | ----------- |
| `[].order` | object | No |  |
| `[].order.coin` | string | No | Trading pair symbol |
| `[].order.side` | string | No | Order side (A for long/buy, B for short/sell) |
| `[].order.limitPx` | string | No | Limit price |
| `[].order.sz` | string | No | Order size |
| `[].order.oid` | integer | No | Order ID |
| `[].order.timestamp` | integer | No | Order creation timestamp |
| `[].order.triggerCondition` | string | No | Trigger condition for conditional orders |
| `[].order.isTrigger` | boolean | No | Whether this is a trigger order |
| `[].order.triggerPx` | string | No | Trigger price for conditional orders |
| `[].order.children` | any | No | Child orders (raw JSON) |
| `[].order.isPositionTpsl` | boolean | No | Whether this is a position take-profit/stop-loss order |
| `[].order.reduceOnly` | boolean | No | Whether this is a reduce-only order |
| `[].order.orderType` | string | No | Order type |
| `[].order.origSz` | string | No | Original order size |
| `[].order.tif` | string | No | Time in force |
| `[].order.cloid` | string | No | Client order ID |
| `[].status` | string | No | Order status |
| `[].statusTimestamp` | integer | No | Timestamp when status was last updated |

Detailed docs (supported chains, edge cases, response format): `GET /api/v1/docs/docs/browse?path=api/developer/hyperliquid/order-history.md`

---

### Order status

`POST /api/v1/developer/trading/hyperliquid/info/order/status`

Endpoint providing order status by user address

#### Request

**Body:**

| Field | Type | Required | Description |
| ----- | ---- | -------- | ----------- |
| `type` | string | Yes | Request type - must be 'orderStatus' |
| `user` | string | Yes | User's wallet address (hex string) |
| `oid` | any | Yes | Order ID - can be either numeric order ID or string client order ID |

**Example:**

```bash
curl -X POST "https://api.allium.so/api/v1/developer/trading/hyperliquid/info/order/status" \
  -H "X-API-KEY: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "type": "...",
    "user": "...",
    "oid": "..."
  }'
```

#### Response

Detailed docs (supported chains, edge cases, response format): `GET /api/v1/docs/docs/browse?path=api/developer/hyperliquid/order-status.md`

---

### L4 Orderbook snapshot

`GET /api/v1/developer/trading/hyperliquid/orderbook/snapshot`

Get complete orderbook snapshot for all pairs.

#### Request

**Example:**

```bash
curl -X GET "https://api.allium.so/api/v1/developer/trading/hyperliquid/orderbook/snapshot" \
  -H "X-API-KEY: $API_KEY"
```

#### Response

Detailed docs (supported chains, edge cases, response format): `GET /api/v1/docs/docs/browse?path=api/developer/hyperliquid/orderbook-snapshot.md`
