---
name: allium-x402-explorer
description: >-
  Run SQL queries on historical blockchain data across 150+ chains.
  Use for long-term analysis, cross-chain metrics, custom aggregations.
  Ad-hoc SQL requires x402 or Tempo auth; saved queries work with any auth.
refetch_after: 30d
---

# Allium Explorer (SQL Analytics)

Use Explorer when the user needs **historical analysis, cross-chain comparisons, or custom aggregations** — anything that requires SQL. Think analytical warehouse queries: powerful, flexible, not realtime.

**When to use Explorer vs Realtime:**

| Explorer (this skill)                                    | Realtime (x402-developer.md)                    |
| -------------------------------------------------------- | ------------------------------------------------ |
| "How did gas prices trend over the last 6 months?"       | "What's the current gas price on Ethereum?"      |
| "Top 10 wallets by volume on Arbitrum last quarter"      | "Show my wallet balance"                         |
| "Compare daily active addresses across all L2s"          | "What's ETH worth right now?"                    |
| "Find all transfers over $1M on Base this week"          | "Get recent transactions for this wallet"        |
| Custom SQL, any table, any timeframe                     | Fast indexed lookups, latest state               |

---

## Auth Requirements

| Command                 | API Key | x402 | Tempo |
| ----------------------- | ------- | ---- | ----- |
| `explorer run`          | Yes     | Yes  | Yes   |
| `explorer status`       | Yes     | Yes  | Yes   |
| `explorer results`      | Yes     | Yes  | Yes   |
| `explorer run-sql`      | No      | Yes  | Yes   |

**Ad-hoc SQL (`run-sql`) requires machine payment auth** (x402 or Tempo). If the active profile is `api_key`, use saved queries via `explorer run` instead.

Check the active profile with `allium auth list`.

---

## Schema Discovery

Before writing SQL, discover available tables and columns. Fetch the documentation index:

```bash
curl -s https://docs.allium.so/llms.txt
```

This returns a complete listing of all Allium documentation pages. Use it to find table schemas, column names, and supported chains. **Never guess table or column names.**

SQL uses **Snowflake dialect**. Schema format: `{chain}.{table}` or `crosschain.{schema}.{table}`.

---

## Ad-hoc SQL (x402 / Tempo only)

The CLI handles the async poll loop internally — submit SQL and get results in one step.

**Important**: Don't use `--format table` as an agent unless the user specifically requests it. Otherwise, you'll be dealing with truncated responses and need to rerun queries.

**Inline SQL:**

```bash
allium explorer run-sql "SELECT block_number, block_timestamp FROM ethereum.raw.blocks ORDER BY block_number DESC LIMIT 10"
```

**From a .sql file:**

```bash
allium explorer run-sql query.sql
```

**From stdin:**

```bash
echo "SELECT COUNT(*) FROM ethereum.raw.transactions WHERE block_timestamp > '2026-03-01'" | allium explorer run-sql -
```

**With row limit:**

```bash
allium explorer run-sql --limit 100 "SELECT * FROM ethereum.raw.blocks"
```

**Async (don't wait for results):**

```bash
allium explorer run-sql --no-wait "SELECT * FROM ethereum.raw.blocks LIMIT 1000"
# prints run_id immediately; check later:
allium explorer status <RUN_ID>
allium explorer results <RUN_ID>
```

---

## Saved Queries (any auth)

Run pre-built queries created at [app.allium.so](https://app.allium.so) or via the API. Works with all auth methods including API key.

```bash
allium explorer run <QUERY_ID>
```

**With parameters:**

```bash
allium explorer run <QUERY_ID> --param chain=ethereum --param days=30
```

**With compute profile:**

```bash
allium explorer run <QUERY_ID> --compute-profile large
```

**Async:**

```bash
allium explorer run <QUERY_ID> --no-wait
allium explorer status <RUN_ID>
allium explorer results <RUN_ID>
```

---

## Response Format

Results default to JSON. Use `--format table` or `--format csv` globally.

```json
{
  "sql": "SELECT chain, block_number FROM ethereum.raw.blocks LIMIT 2",
  "data": [
    {"chain": "ethereum", "block_number": 20000000},
    {"chain": "ethereum", "block_number": 20000001}
  ],
  "meta": {
    "columns": [
      {"name": "chain", "data_type": "TEXT"},
      {"name": "block_number", "data_type": "NUMBER"}
    ],
    "row_count": 2,
    "run_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
  },
  "queried_at": "2026-03-17T18:05:00Z"
}
```

Access: `data` for rows, `meta.columns` for schema.

---

## Endpoint Costs

| Command              | Cost per call                                        |
| -------------------- | ---------------------------------------------------- |
| `explorer run-sql`   | $0.01                                                |
| `explorer run`       | $0.01                                                |
| `explorer status`    | $0.01                                                |
| `explorer results`   | ~$0.15/min of execution time (varies with complexity) |

---

## Query Status Values

| Status     | Meaning              |
| ---------- | -------------------- |
| `created`  | Queued               |
| `running`  | Executing            |
| `success`  | Results ready        |
| `failed`   | SQL error or timeout |
| `canceled` | Manually stopped     |

---

## Gotchas

1. **Always discover schemas first** — fetch `https://docs.allium.so/llms.txt` and find the right table docs before writing SQL
2. **`run-sql` needs x402/Tempo** — API key users must use saved queries via `run`
3. **Snowflake SQL dialect** — `{chain}.{table}` or `crosschain.{schema}.{table}`
4. **Server-side timeout** — queries time out after 10 minutes
5. **Result format** — `--format json` (default), `table`, or `csv`
