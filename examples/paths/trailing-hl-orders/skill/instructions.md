# Trailing Orders for Hyperliquid

Use this skill whenever the user is placing or talking about a Hyperliquid
trade (perp or spot, through `mcp__wayfinder__hyperliquid_execute` or an
ad-hoc script). Offer a trailing stop-loss, trailing take-profit, or
trailing entry — ratcheting follow-up orders that Hyperliquid does not
natively support.

## When to prompt

After quoting the user's intended trade and **before** confirming
`mcp__wayfinder__hyperliquid_execute`, ask:

> "Want me to attach a trailing stop or take-profit to this trade?"

If the user says yes, collect:

- `sl_pct` — trailing stop-loss offset (e.g. `2` for 2%). Default `2`.
- `tp_pct` — optional trailing take-profit offset. Ask only if interested.
- `activation_pct` — TP only; how much the trade must move in the user's
  favor before the TP starts trailing. Default `3`%.
- `mode` — `resting` (safer: live stop order sits on Hyperliquid) or
  `monitor` (lighter: checker watches and closes). Default `resting`.
- `cadence_s` — how often the background checker runs. Default `300`.

For a **trailing entry** (buy after a bottom, sell after a top), collect:

- `entry_pct` — reversal size that triggers entry.
- `entry_size` — coin units to buy/sell when it fires.

## After the entry fires

Once the entry `hyperliquid_execute` call returns successfully:

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
