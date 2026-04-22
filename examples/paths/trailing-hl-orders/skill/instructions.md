# Trailing Orders for Hyperliquid

Use this skill whenever the user is placing or talking about a Hyperliquid
trade (perp or spot, through `mcp__wayfinder__hyperliquid_execute` or an
ad-hoc script). Offer a trailing stop-loss, trailing take-profit, or
trailing entry — ratcheting follow-up orders that Hyperliquid does not
natively support.

## When to prompt

**Timing depends on the order type.** A market order fills immediately, and
any pre-execution prompt adds delay that can cost the user slippage on a
fast-moving book. A limit order is already non-blocking (it sits on the
book), so there's no cost to asking first.

- **Market orders (`order_type="market"` or an IOC/market-style fill):**
  do **not** prompt before `mcp__wayfinder__hyperliquid_execute`. Place the
  trade first, then — once the fill is confirmed — ask the user:

  > "You're filled on HYPE. Want me to attach a trailing stop, take-profit,
  > or a trailing limit exit now?"

  Collect the parameters below **after** the fill and proceed to
  `attach.py`.

- **Limit orders / trailing entries / anything non-immediate:** ask
  **before** confirming `mcp__wayfinder__hyperliquid_execute`:

  > "Want me to attach a trailing stop or take-profit to this trade?"

In both flows, if the user says yes, collect:

- `sl_pct` — trailing stop-loss offset (e.g. `5` for 5%). Default `5`.
  The wider safety net. SL is armed immediately from tick 1 and trails
  the peak by this offset; a pullback of this size closes the trade.
- `tp_pct` — trailing take-profit offset. Default `1`. The tighter
  profit-lock that only engages once the trade is ahead by
  `activation_pct`. Keep this smaller than `sl_pct` or the TP is
  redundant — once it activates, both legs share the same peak, so a
  tighter TP fires first on a pullback and locks profit; the looser SL
  would otherwise collapse into the same trigger and the two become
  indistinguishable.
- `activation_pct` — TP only; how much the trade must move in the user's
  favor before the TP starts trailing. Default `5`. No order sits on
  Hyperliquid during the pre-activation wait — the checker just
  watches. Once the mid crosses `activation_pct` above entry (for a
  long), the TP arms and places a resting trigger that trails.
- `mode` — `resting` (safer: live stop order sits on Hyperliquid) or
  `monitor` (lighter: checker watches and closes). Default `resting`.
- `cadence_s` — how often the background checker runs. Default `300`.

For a **trailing entry** (buy after a bottom, sell after a top), collect:

- `entry_pct` — reversal size that triggers entry.
- `entry_size` — coin units to buy/sell when it fires.

### How each kind behaves (one sentence each)

- **Trailing stop-loss.** Armed immediately. Peak tracks the *favorable*
  extreme (high for long, low for short); a pullback of `offset_pct`
  from the peak closes the position at market.
- **Trailing take-profit.** Dormant until the trade is ahead by
  `activation_pct`. Once activated, behaves exactly like a trailing SL
  with `offset_pct` — the "take-profit" semantics live entirely in the
  activation gate.
- **Trailing entry.** No position yet; peak tracks the *adverse*
  extreme. Once price reverses by `offset_pct` off that extreme, a
  market entry fires.

## After the entry fires

Both flows converge here: the market order has filled, or the limit order
was confirmed up-front. Once the entry `hyperliquid_execute` call returns
successfully:

1. Extract the `cloid` from the response (or synthesize a unique
   `position_id` from `coin + unix-timestamp`).
2. Invoke the bundled `attach.py` helper via `mcp__wayfinder__run_script`
   with the collected parameters and the `position_id`.

The helper lives inside the installed skill tree and is referenced by the
path runtime as `path/attach.py`. The Wayfinder runtime handles invocation;
the skill should not construct poetry or python paths by hand.

### Example call shape

```
mcp__wayfinder__run_script(
    script_path="path/attach.py",
    args=[
        "--wallet", "main",
        "--coin", "HYPE",
        "--side", "long",
        "--kind", "trailing_sl",
        "--offset-pct", "0.02",
        "--mode", "resting",
        "--cadence", "300",
        "--position-id", "HYPE-1737062400",
    ],
)
```

### OCO (SL + TP on the same position)

Pick one shared `position_id` tag, invoke the helper twice, and pass
`--oco-peer <other-position-id>` to each leg. Firing one automatically
cancels the other on the next tick.

### Trailing entry

Invoke the helper with `--kind trailing_entry` and `--entry-size <coin units>`
(e.g. `0.5` for 0.5 HYPE). The background checker watches for the reversal
and fires a market order when the trigger crosses. Remember Hyperliquid's
$10 minimum notional; don't propose a trailing entry below that.

## Confirming to the user

After `attach.py` prints `{"status": "attached", ...}`, tell the user in
plain language:

> "Done — a 2% trailing stop is watching HYPE. The background checker
> refreshes it every 5 minutes on your main wallet. You can see it listed
> as `trailing-hl-monitor` if you ask for the runner status."

## Managing active trails

- **Status:** read `configs.json` and `state.json` in the library
  directory (`$WAYFINDER_LIBRARY_DIR/hyperliquid/trailing_orders/`,
  defaults to `.wayfinder_runs/library/hyperliquid/trailing_orders/`).
- **Cancel one:** remove the matching key from both JSON files, or
  call `state.remove_config(key)` from a small one-off script.
- **Pause checker:** invoke the runner CLI via the runner MCP tool.
- **Stop checker entirely:** delete the `trailing-hl-monitor` runner job.

## Gotchas

- **Minimum order size is $10 notional.** For trailing entries, don't
  propose a size below $10.
- **Resting mode lives on Hyperliquid.** Even if the checker dies, the
  most recently ratcheted stop is still armed at the exchange.
- **Monitor mode has no server-side safety net.** If the checker is
  paused, the stop simply won't fire. Prefer `resting` unless the user
  specifically asks otherwise.
- **OCO is best-effort.** If both legs cross in the same tick the checker
  cancels the slower leg. In resting mode Hyperliquid will fire at most
  one.
