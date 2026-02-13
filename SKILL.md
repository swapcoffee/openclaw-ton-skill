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

## Auto-Start: Transaction Monitor

On first use or after skill installation, check if wallets exist and monitor is not running:

```bash
python wallet.py -p <password> list
python monitor.py status
```

If wallets exist and monitor is NOT running:
1. Start the monitor daemon: `python monitor.py start -p <password> --daemon`
2. Create a cron job (every 60s) to check `~/.openclaw/ton-skill/monitor.log` for new transactions
3. Alert the user on any incoming/outgoing transfer, swap, or NFT event
4. Clear the log after processing

**After creating or importing a new wallet**, ask the user:
1. "Хочешь включить эмуляцию транзакций перед отправкой?"
   - **Да, на всё** → set `emulation_mode: all` in config
   - **Только на крупные** → ask threshold, set `emulation_mode: threshold`, `emulation_threshold_ton: <amount>`
   - **Только на определённые** → set `emulation_mode: selective` (emulate only swaps/nft/yield, skip simple transfers)
   - **Нет** → set `emulation_mode: none`

Configure: `python utils.py config set emulation_mode <all|threshold|selective|none>`

Then always:
1. Restart the monitor to pick up the new wallet: `python monitor.py stop && python monitor.py start -p <password> --daemon`
2. If monitor cron doesn't exist yet, create it

This ensures real-time transaction alerts are always active for ALL wallets.

## Setup

### First-Time Setup

On first use, prompt the user to configure API keys. At minimum:
1. **Marketapp** (required for NFT floor prices, buy/sell): Get token at https://marketapp.ws/api-token
2. **TonAPI** (optional, free tier works): Get at https://tonscan.org/api
3. **DYOR** (optional, for token analytics): Get at https://dyor.io/tonapi?pricing

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

## Tokens API (swap.coffee)

Script: `tokens.py`

Rich token data from swap.coffee Tokens API: market stats, price charts, holders, search.

### List Jettons

```bash
python tokens.py list --search USDT --size 10
python tokens.py list --verification WHITELISTED,COMMUNITY
python tokens.py list --page 2 --size 50
```

### Get Jetton Info (with Market Stats)

```bash
python tokens.py info EQCxE6mUtQJKFnGfaROTKOt1lZbDiiX1kCixRv7Nw2Id_sDs
```

Returns: price_usd, price_change (5m/1h/6h/24h/7d), volume_24h, tvl, mcap, fdmc, holders_count, trust_score.

### Price Chart

```bash
python tokens.py price-chart EQCxE6... --hours 24
python tokens.py price-chart EQCxE6... --from "2024-01-01T00:00:00Z" --to "2024-01-02T00:00:00Z"
python tokens.py price-chart EQCxE6... --currency ton
```

### Top Holders

```bash
python tokens.py holders EQCxE6mUtQJKFnGfaROTKOt1lZbDiiX1kCixRv7Nw2Id_sDs
```

### Hybrid Search (with Memepad)

```bash
python tokens.py search --query pepe --kind MEMES_ALL
python tokens.py search --query NOT --sort VOLUME_24H
python tokens.py search --kind MEMES_MEMEPADS --sort TVL
```

Kinds: `ALL`, `DEXES`, `MEMES_ALL`, `MEMES_DEXES`, `MEMES_MEMEPADS`
Sort: `FDMC`, `TVL`, `MCAP`, `VOLUME_24H`, `PRICE_CHANGE_24H`

### Account Jetton Balances

```bash
python tokens.py balances UQBvW8Z5huBkMJYdnfAEM5JqTNkgxvhw...
```

### Bulk Fetch

```bash
python tokens.py bulk EQCxE6... EQBlqs... EQAvlW...
```

### Labels

```bash
python tokens.py labels
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

**swap.coffee yield API aggregates 2000 pools from 16 protocols:**
stonfi, stonfi_v2, dedust, tonco, evaa, tonstakers, stakee, bemo,
bemo_v2, hipo, kton, storm_trade, torch_finance, dao_lama_vault, bidask, coffee

### List Pools

```bash
python yield_cmd.py pools --sort apr
python yield_cmd.py pools --sort tvl --limit 50
python yield_cmd.py pools --page 2 --limit 100   # pagination
python yield_cmd.py pools --all                   # all 2000 pools

# Client-side filters (auto-fetches all pools, cached 5 min)
python yield_cmd.py pools --protocol stonfi
python yield_cmd.py pools --token TON
python yield_cmd.py pools --min-tvl 1000000
python yield_cmd.py pools --trusted-only
python yield_cmd.py pools --protocol dedust --token USDT --min-tvl 100000
```

Sort: `apr`, `tvl`, `volume`
Pagination: `--page N` (1-indexed), max 100 per page
Cache: `python yield_cmd.py cache --status` / `--clear`

**Note:** Server-side filters don't work — all filtering is client-side.

### Pool Details

```bash
python yield_cmd.py pool --id EQD...abc
```

Returns: TVL (USD), volume, fees, APR, LP APR, boost APR, tokens, protocol.

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

### View Positions

```bash
python yield_cmd.py positions --wallet EQD...xyz
```

Detects LP tokens in wallet via TonAPI (heuristic by name).

### List Protocols

```bash
python yield_cmd.py protocols
```

### Deposit / Withdraw (Not Supported via API)

⚠️ **swap.coffee yield API is a read-only aggregator.**

Deposit and withdraw operations require direct interaction with DEX smart contracts
(STON.fi, DeDust, TONCO, etc.). Use DEX-specific SDKs or swap.py for liquidity operations.

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
3. **Show confirmation with inline buttons** (see below)
4. User clicks ✅ or ❌
5. Sign and broadcast (or cancel)

### Confirmation with Inline Buttons

When a transaction requires confirmation (transfer, swap, deposit, withdraw, NFT buy/sell),
**always send the confirmation message with inline buttons** using the `message` tool:

```
message action=send buttons=[[{"text":"✅ Подтвердить","callback_data":"ton_tx_confirm"},{"text":"❌ Отменить","callback_data":"ton_tx_cancel"}]]
```

The message should include:
- Transaction type (transfer/swap/deposit/etc.)
- Amount and destination
- Estimated fee from emulation
- Any warnings (large amount, unverified token, etc.)

Example confirmation message:
```
🔄 Свап 3.7 TON → ~5.09 USDT
📍 DEX: Moon (swap.coffee)
💰 Fee: ~0.15 TON
⚠️ Slippage: 1%
```

When user clicks:
- `ton_tx_confirm` → **immediately** send pre-signed BOCs from `/tmp/ton_pending_tx.json`, report result
- `ton_tx_cancel` → reply "Отменено ✅", delete `/tmp/ton_pending_tx.json`

### Pre-signing Flow (CRITICAL for fast response)

When preparing a transaction for confirmation:
1. Build transactions via API
2. Sign ALL transactions with wallet (get seqno, create transfer messages)
3. Save signed BOCs to `/tmp/ton_pending_tx.json`:
```json
{
  "description": "Deposit 7.2 TON + 10 USDT → Coffee DEX",
  "txs": [
    {"boc": "base64...", "amount_ton": 7.4, "to": "0:db2e..."},
    {"boc": "base64...", "amount_ton": 0.19, "to": "0:2b25..."}
  ],
  "query_id": 123456,
  "created_at": 1234567890
}
```
4. Show confirmation message with inline buttons
5. When `ton_tx_confirm` arrives → just POST each BOC to `/blockchain/message`, done!

**DO NOT re-build or re-sign on confirm!** The BOCs are ready to send.
If pending TX is older than 60 seconds, re-sign before sending (valid_until expires).

### Handling callback_data

When you receive a message matching `ton_tx_confirm`:
1. Read `/tmp/ton_pending_tx.json`
2. Send each `boc` via TonAPI
3. Reply with ✅ result
4. Delete the pending file

When you receive `ton_tx_cancel`:
1. Delete `/tmp/ton_pending_tx.json`
2. Reply "Отменено ✅"

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

## Transaction Monitor

Script: `monitor.py`

Real-time мониторинг транзакций кошельков через TonAPI SSE (Server-Sent Events) или polling fallback.

### Start Monitor

```bash
# Foreground
python monitor.py start -p <password>

# Background (daemon)
python monitor.py start -p <password> --daemon

# Specific wallets only
python monitor.py start -p <password> --wallet trading --wallet main

# Force polling instead of SSE
python monitor.py start -p <password> --polling
```

### Status

```bash
python monitor.py status
```

Output:
```json
{
  "running": true,
  "pid": 12345,
  "started_at": "2026-02-13T02:15:00",
  "wallets": ["trading", "main"],
  "mode": "sse",
  "last_seen": {...}
}
```

### Stop Monitor

```bash
python monitor.py stop
```

### Event Format

Stdout JSON (for agent parsing):
```json
{
  "type": "incoming_transfer",
  "wallet": "trading",
  "address": "EQ...",
  "amount": "5.0 TON",
  "from": "EQ...",
  "timestamp": "2026-02-13T02:12:00",
  "tx_hash": "abc..."
}
```

Event types:
- `incoming_transfer` — Получение TON/jettons
- `outgoing_transfer` — Отправка TON/jettons
- `swap` — DEX swap
- `nft_transfer` — Передача NFT
- `other` — Прочие операции

### LaunchAgent (Автозапуск)

```bash
# Установка с паролем
WALLET_PASSWORD=xxx ./scripts/install-launchagent.sh

# Запуск
launchctl load ~/Library/LaunchAgents/com.openclaw.ton-monitor.plist

# Остановка
launchctl unload ~/Library/LaunchAgents/com.openclaw.ton-monitor.plist

# Логи
tail -f ~/Library/Logs/ton-monitor.log
```

### Storage

- State: `~/.openclaw/ton-skill/monitor_state.json`
- Logs: `~/.openclaw/ton-skill/monitor.log`
- PID: `~/.openclaw/ton-skill/monitor.pid`

### Dependencies

```bash
pip install sseclient-py  # For SSE mode (recommended)
```

---

## Storage Locations

- Config: `~/.openclaw/ton-skill/config.json`
- Wallets: `~/.openclaw/ton-skill/wallets.enc` (encrypted)
- Monitor state: `~/.openclaw/ton-skill/monitor_state.json`
- Monitor logs: `~/.openclaw/ton-skill/monitor.log`
