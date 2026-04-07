---
name: allium-x402-setup
description: >-
  First-time setup for Allium: install the CLI and configure authentication.
  Supports API key, x402 (Privy or raw private key), and Tempo methods.
refetch_after: 30d
---

# Allium Setup — Interactive Agent Instructions

You are driving this setup end-to-end. Execute each step using your tools. Do not just print instructions — run the commands, ask for input when needed, and confirm success before moving on.

---

## Step 1: Check if CLI is installed

Run `allium --version` (or `which allium`). If it is missing, install it:

```bash
curl -sSL http://agents.allium.so/cli/install.sh | sh
```

After install, verify `allium --help` works. If `allium: command not found`, add `~/.local/bin` to PATH and retry.

---

## Step 2: Ask the user which auth method to use

Use AskUserQuestion to ask:

> Which authentication method would you like to use?
> - `tempo` — Tempo MPP (chain-id 42431)
> - `api_key` — Allium API key
> - `x402_key` — x402 with a raw private key (Base network)
> - `x402_privy` — x402 with a Privy managed wallet

Then collect the required credentials for the chosen method using AskUserQuestion (one question per credential):

**tempo / x402_key:**
- Ask: "Please paste your private key (without the 0x prefix)."

**api_key:**
- Ask: "Please paste your Allium API key."

**x402_privy:**
- Ask for: Privy App ID, Privy App Secret, Privy Wallet ID (one at a time).

---

## Step 3: Run the non-interactive setup command

Construct and run the appropriate command based on the method and credentials provided:

**Tempo:**
```bash
allium auth setup --method tempo \
  --private-key <key> \
  --chain-id 42431
```

**API Key:**
```bash
allium auth setup --method api_key --api-key <key>
```

**x402 raw key:**
```bash
allium auth setup --method x402_key \
  --private-key <key> \
  --network eip155:8453
```

**x402 Privy:**
```bash
allium auth setup --method x402_privy \
  --privy-app-id <APP_ID> \
  --privy-app-secret <APP_SECRET> \
  --privy-wallet-id <WALLET_ID> \
  --network eip155:8453
```

---

## Step 4: Verify

Run and show the output:

```bash
allium auth list
```

Confirm the new profile is active (marked with a bullet) and the method/network look correct.

---

## Step 5: Test

Run:

```bash
allium realtime prices latest --chain ethereum \
  --token-address 0x0000000000000000000000000000000000000000
```

If you see a price for ETH, tell the user setup is complete.

---

## Troubleshooting

- **`allium: command not found`:** Ensure `~/.local/bin` is on PATH. Re-source the shell profile.
- **Authentication errors:** Re-run Step 3 and double-check credentials.
- **No payment option (x402):** Wallet must have USDC on Base mainnet, not Ethereum.
