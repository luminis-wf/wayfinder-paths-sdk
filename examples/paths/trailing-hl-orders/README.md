# Trailing Orders for Hyperliquid

## What this does

Hyperliquid lets you set a stop-loss at a fixed price. This path adds
**trailing** stops (and take-profits) — they follow the price as your trade
moves in your favor, so you lock in more gains without watching the chart
all day.

**Example.** You buy HYPE at $30 and set a 5% trailing stop. If HYPE climbs
to $40, your stop automatically moves up to $38 (5% below the peak). If HYPE
then drops, the trade closes at $38 — locking in an $8 gain instead of
getting stopped out at $28.50 like a fixed stop would do.

## How to install

In Claude Code, just say:

> "Install the Hyperliquid trailing orders path."

Claude will pull the path, wire up the skill, and register the background
checker automatically. No files to edit; no settings to paste.

## How to use it

Next time you ask Claude to place a Hyperliquid trade, it'll ask if you want
to add a trailing stop or take-profit. Say yes, pick a percentage, and
you're done. A background checker keeps an eye on the price every few
minutes and acts for you.

You can cancel at any time with:

> "Stop the Hyperliquid trailing checker."

## Two safety modes

- **Safer (recommended).** A live stop order sits on Hyperliquid at the
  current trailing price. Even if your computer is off, Hyperliquid itself
  will fire the stop. The background checker just moves that stop up as the
  price rises.
- **Lighter.** No live stop order on Hyperliquid. The background checker
  watches the price and closes the trade when the trailing threshold is
  hit. This uses less exchange bandwidth but only works while your checker
  is running.

Claude asks which mode you want. If you don't know, stick with Safer.

## What gets installed

- A skill that tells Claude how to offer trailing orders before any
  Hyperliquid trade. Claude loads it automatically whenever you're placing
  or talking about an HL trade.
- A small background checker that the Wayfinder runner invokes every 5
  minutes to trail your open stops.
- An applet — a demo page where you can move a slider and see how a
  trailing stop would have handled recent price moves for BTC, HYPE, and
  three HIP-3 markets, versus a fixed stop.

## Order types supported

- **Trailing stop-loss.** Closes your position after a pullback from the
  best price it has seen.
- **Trailing take-profit.** Waits until the trade is already in profit by
  an amount you choose (the "activation"), then trails like a stop-loss.
- **Trailing entry.** Doesn't buy yet — watches the price dip first, then
  buys once it reverses up by your chosen amount. The mirror of that
  works for shorts.

You can also ask for a trailing stop **and** a trailing take-profit on the
same trade. Whichever one fires first automatically cancels the other.

## What it won't do

- It will not open a brand new trade for you. You start the trade the usual
  way; the trailing logic attaches on top.
- It will not move money between wallets or exchanges. Everything happens
  on your main Hyperliquid account.
- It will not work on exchanges other than Hyperliquid in this version.

## Checking on it later

- "Show me active Hyperliquid trailing orders." — Claude reads the list.
- "Cancel the trailing stop on HYPE." — Claude removes it.
- "Pause the background checker." — Claude pauses the runner job.

## Running the demo applet locally

Open `applet/dist/index.html` in a browser. Pick a token, a window, and
drag the percentage slider to compare a fixed stop with a trailing stop
on a replayable price path. The math matches the live controller, so the
results show how the real thing would behave in a similar market.

## Advanced: dedicated strategy wallet

By default the background checker runs on your main wallet — the simplest
setup. If you want a walled-off copy of capital for this, ask Claude to
"create a dedicated strategy wallet for trailing orders" and follow the
prompts. The checker will move to that wallet.

## File layout (for the curious)

```
examples/paths/trailing-hl-orders/
├── controller.py      # decides when to move, fire, or cancel (no exchange calls)
├── monitor.py         # runs every few minutes; talks to Hyperliquid
├── attach.py          # hooks a trailing config onto a fresh trade
├── state.py           # atomic JSON storage (survives session restarts)
├── tests/             # unit tests for the controller logic
├── skill/             # what Claude reads + pre-trade nudge
├── applet/            # the static backtest demo page
└── wfpath.yaml        # path manifest
```
