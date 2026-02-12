---
name: ton-blockchain
description: |
  TON blockchain operations: wallet management, TON/jetton transfers, DEX swaps,
  token analytics, yield/DeFi pools, NFT trading, and DNS resolution.
  
  Use when user wants to:
  - Create/import/manage TON wallets
  - Check balances (TON, jettons, NFTs)
  - Send TON or jettons to address/.ton domain
  - Swap tokens (TON↔USDT, etc.) via DEX
  - Analyze tokens (price, trust score, scam detection)
  - Find yield pools, add/remove liquidity
  - Buy/sell/transfer NFTs
  - Resolve .ton domains
---

# TON Blockchain Skill

Scripts: `~/.openclaw/workspace/openclaw-ton-skill/scripts/`

## Setup

### API Keys

Configure via CLI or edit `~/.openclaw/ton-skill/config.json`:

```bash
# TonAPI (required for most operations)
python utils.py config set tonapi_key "YOUR_TONAPI_KEY"

# swap.coffee (for swaps and yield)
python utils.py config set swap_coffee_key "YOUR_SWAP_COFFEE_KEY"

# DYOR (for token analytics)
python utils.py config set dyor_key "YOUR_DYOR_KEY"

# Marketapp (for NFT trading)
python utils.py config set marketapp_key "YOUR_MARKETAPP_KEY"
```

### Dependencies

```bash
pip install requests cryptography tonsdk
```

### Wallet Password

Set `WALLET_PASSWORD` env or use `--password` flag for wallet operations.

---

## Wallet Management

Script: `wallet.py`

### Create Wallet

```bash
python wallet.py create --label "trading"
python wallet.py create --label "cold" --version v4r2
```

**Output includes mnemonic — save it! Shown only once.**

### Import Wallet

```bash
python wallet.py import --mnemonic "word1 word2 ... word24" --label "imported"
```

### List Wallets

```bash
python wallet.py list
python wallet.py list --balances   # Include TON balances (slower)
```

### Get Balance

```bash
python wallet.py balance trading
python wallet.py balance trading --full   # Include jettons
python wallet.py balance UQBvW8Z5huBk...  # By address
```

### Rename Wallet

```bash
python wallet.py label trading "main-trading"
```

### Export Mnemonic

```bash
python wallet.py export trading
```

### Remove Wallet

```bash
python wallet.py remove old-wallet
```

---

## Transfers

Script: `transfer.py`

### Send TON

```bash
# Emulate (no send)
python transfer.py ton --from trading --to UQBvW8Z5... --amount 5

# With comment
python transfer.py ton --from trading --to wallet.ton --amount 1 --comment "Thanks!"

# Execute transfer
python transfer.py ton --from trading --to UQBvW8Z5... --amount 5 --confirm
```

### Send Jettons

```bash
# Emulate USDT transfer
python transfer.py jetton --from trading --to wallet.ton --jetton USDT --amount 100

# Execute
python transfer.py jetton --from trading --to UQBvW8Z5... --jetton USDT --amount 100 --confirm
```

**Always emulates first. Add `--confirm` to execute.**

---

## Swaps (DEX)

Script: `swap.py`

### Get Quote

```bash
python swap.py quote --from TON --to USDT --amount 10 --wallet UQBvW8...
python swap.py quote --from USDT --to TON --amount 100 --wallet trading --slippage 1.0
```

### Execute Swap

```bash
# Emulate
python swap.py execute --wallet trading --from TON --to USDT --amount 10

# Execute with slippage
python swap.py execute --wallet trading --from USDT --to NOT --amount 50 --slippage 1.0 --confirm
```

### Check Status

```bash
python swap.py status --hash abc123...
```

### Known Tokens

```bash
python swap.py tokens
```

Supported: TON, USDT, USDC, NOT, STON, SCALE

---

## DNS (.ton Domains)

Script: `dns.py`

### Resolve Domain

```bash
python dns.py resolve wallet.ton
python dns.py resolve foundation   # .ton suffix optional
```

### Domain Info

```bash
python dns.py info wallet.ton   # Owner, expiry, NFT address
```

### Check Address or Domain

```bash
python dns.py check wallet.ton
python dns.py check UQBvW8Z5...
```

---

## Token Analytics

Script: `analytics.py`

### Full Token Info

```bash
python analytics.py info --token SCALE
python analytics.py info --token EQBlqsm144Dq...  # By address
```

### Trust Score (Scam Detection)

```bash
python analytics.py trust --token NOT
```

Output includes assessment:
- ✅ HIGH TRUST (≥80) — Generally safe
- ⚠️ MEDIUM TRUST (50-79) — Proceed with caution
- 🔴 LOW TRUST (20-49) — High risk
- 🚨 VERY LOW TRUST (<20) — Likely scam

### Price History

```bash
python analytics.py history --token STON --days 7
python analytics.py history --token TON --days 30
```

### DEX Pools

```bash
python analytics.py pools --token USDT
```

### Compare Tokens

```bash
python analytics.py compare --tokens "SCALE,NOT,STON"
```

### API Status

```bash
python analytics.py status   # Check DYOR/TonAPI availability
```

---

## Yield / DeFi

Script: `yield_cmd.py`

### List Pools

```bash
python yield_cmd.py pools --sort apy
python yield_cmd.py pools --sort tvl --min-tvl 1000000
python yield_cmd.py pools --token TON --limit 10
```

Sort options: `apy`, `tvl`, `volume`

### Pool Details

```bash
python yield_cmd.py pool --id EQD...abc
```

### Recommendations

```bash
python yield_cmd.py recommend --risk low
python yield_cmd.py recommend --token TON --risk medium
python yield_cmd.py recommend --risk high --amount 100
```

Risk levels:
- `low` — TVL ≥1M, stable pairs, minimal IL
- `medium` — TVL ≥100K, moderate IL
- `high` — TVL ≥10K, any pairs

### Deposit Liquidity

```bash
# Emulate
python yield_cmd.py deposit --pool EQD...abc --amount 100 --wallet trading

# Execute
python yield_cmd.py deposit --pool EQD...abc --amount 100 --wallet trading --confirm
```

### Withdraw Liquidity

```bash
python yield_cmd.py withdraw --pool EQD...abc --wallet trading --confirm
python yield_cmd.py withdraw --pool EQD...abc --wallet trading --percentage 50 --confirm
```

### View Positions

```bash
python yield_cmd.py positions --wallet trading
```

---

## NFT

Script: `nft.py`

### List NFTs in Wallet

```bash
python nft.py list --wallet trading
python nft.py list --wallet UQBvW8... --limit 50
```

### NFT Info

```bash
python nft.py info --address EQC7...
```

### Collection Info

```bash
python nft.py collection --address EQCV...
python nft.py collection --address EQCV... --filter onsale --limit 20
```

### Search Collections

```bash
python nft.py search --query "TON Diamonds"
```

### Telegram Gifts on Sale

```bash
python nft.py gifts
python nft.py gifts --min-price 1 --max-price 10
python nft.py gifts --model "Plush Pepe" --symbol "🐸"
```

### Buy NFT

```bash
# Emulate
python nft.py buy --nft EQC7... --wallet trading

# Execute
python nft.py buy --nft EQC7... --wallet trading --confirm
```

### Sell NFT

```bash
python nft.py sell --nft EQC7... --price 5.5 --wallet trading --confirm
```

### Change Price

```bash
python nft.py change-price --nft EQC7... --price 10 --wallet trading --confirm
```

### Cancel Sale

```bash
python nft.py cancel-sale --nft EQC7... --wallet trading --confirm
```

### Transfer NFT

```bash
python nft.py transfer --nft EQC7... --from trading --to wallet.ton --confirm
```

---

## Utilities

Script: `utils.py`

### Config

```bash
python utils.py config show
python utils.py config get tonapi_key
python utils.py config set tonapi_key "YOUR_KEY"
python utils.py config set limits.max_transfer_ton 500
```

### Address Conversion

```bash
python utils.py address to-raw UQBvW8Z5huBk...
python utils.py address to-friendly 0:6f5bc679...
python utils.py address validate UQBvW8Z5huBk...
```

---

## Security

### Critical Rules

1. **Encrypted storage** — Private keys stored AES-256 encrypted in `~/.openclaw/ton-skill/wallets.enc`
2. **Emulation first** — All transactions emulate before execution (shows fees, balance changes)
3. **Explicit confirmation** — `--confirm` required for any blockchain write
4. **Never log secrets** — Mnemonics/keys never written to logs

### Transaction Flow

1. Build transaction
2. Emulate via TonAPI (show fee, result)
3. **User confirms**
4. Sign and broadcast

### Limits

Configure in `~/.openclaw/ton-skill/config.json`:

```json
{
  "limits": {
    "max_transfer_ton": 100,
    "require_confirmation": true
  }
}
```

---

## Common Patterns

### Check Balance Before Transfer

```bash
python wallet.py balance trading --full
python transfer.py ton --from trading --to recipient.ton --amount 10
# Review emulation output
python transfer.py ton --from trading --to recipient.ton --amount 10 --confirm
```

### Analyze Token Before Swap

```bash
python analytics.py trust --token NEWTOKEN
python analytics.py info --token NEWTOKEN
python swap.py quote --from TON --to NEWTOKEN --amount 1 --wallet trading
```

### Find Best Yield

```bash
python yield_cmd.py recommend --risk medium --token TON
python yield_cmd.py pool --id <recommended_pool_id>
python yield_cmd.py deposit --pool <id> --amount 100 --wallet trading
```

---

## Error Handling

All commands return JSON with `success` field:

```json
{"success": true, "data": ...}
{"success": false, "error": "Error message"}
```

Exit codes: `0` = success, `1` = error

---

## Storage Locations

- Config: `~/.openclaw/ton-skill/config.json`
- Wallets: `~/.openclaw/ton-skill/wallets.enc` (encrypted)
