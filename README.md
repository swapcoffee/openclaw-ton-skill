# 🔷 OpenClaw TON Blockchain Skill

[![OpenClaw Skill](https://img.shields.io/badge/OpenClaw-Skill-blue?style=flat-square&logo=data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIyNCIgaGVpZ2h0PSIyNCIgdmlld0JveD0iMCAwIDI0IDI0IiBmaWxsPSJub25lIiBzdHJva2U9IndoaXRlIiBzdHJva2Utd2lkdGg9IjIiIHN0cm9rZS1saW5lY2FwPSJyb3VuZCIgc3Ryb2tlLWxpbmVqb2luPSJyb3VuZCI+PHBhdGggZD0iTTEyIDJMNCAyMmgxNkwxMiAyeiIvPjwvc3ZnPg==)](https://openclaw.io)
[![TON Blockchain](https://img.shields.io/badge/TON-Blockchain-0088CC?style=flat-square&logo=ton&logoColor=white)](https://ton.org)
[![Beta](https://img.shields.io/badge/Status-BETA-orange?style=flat-square)](https://github.com/swapcoffee/openclaw-ton-skill)
[![License: MIT](https://img.shields.io/badge/License-MIT-green?style=flat-square)](LICENSE)
[![swap.coffee](https://img.shields.io/badge/Built%20by-swap.coffee-brown?style=flat-square)](https://swap.coffee)

---

## ⚠️ BETA DISCLAIMER

> **🚨 THIS SKILL IS IN BETA — USE AT YOUR OWN RISK**
>
> - This software is **experimental** and under active development
> - There **may be bugs, errors, and unexpected behavior**
> - **swap.coffee bears NO responsibility** for any losses, damages, or issues arising from the use of this repository
> - **DO NOT use with funds you cannot afford to lose**
> - **Always test with small amounts first** before any real transactions
> - This is **NOT financial advice** — do your own research
> - By using this skill, you acknowledge and accept these risks

---

## 📖 Description

The **OpenClaw TON Blockchain Skill** is a comprehensive integration for [OpenClaw](https://openclaw.io) that enables AI agents to interact with the TON blockchain ecosystem. It provides full wallet management, token swaps via DEX aggregators, DeFi/yield pool analytics, NFT trading, and much more.

### Integrated APIs

| API | Purpose |
|-----|---------|
| **[swap.coffee](https://swap.coffee)** | DEX aggregation, swaps, yield pools, token data |
| **[TonAPI](https://tonapi.io)** | Blockchain queries, transaction emulation, account data |
| **[DYOR.io](https://dyor.io)** | Token analytics, trust scores, scam detection |
| **[Marketapp](https://marketapp.ws)** | NFT trading, floor prices, buy/sell orders |

---

## 🤖 Built by AI Agents

> **This entire skill was built by a team of AI agents, with love from swap.coffee for the TON ecosystem ☕️❤️**

The development of this skill was orchestrated by a collaborative team of specialized AI agents:

| Role | Responsibility |
|------|----------------|
| 🔧 **Backend Developers** | Core implementation, API integrations, wallet management |
| 🧪 **QA Tester** | Test case design, validation, bug hunting |
| 📋 **Product Manager** | Requirements, coordination, feature prioritization |
| 📝 **README Writer** | Documentation (yes, this README!) |

A proof-of-concept for AI-driven open source development. The future is here. 🚀

---

## ✨ Features

### 💼 Wallet Management
- Create new TON wallets (V3R2, V4R2, V5R1)
- Import wallets via 24-word mnemonic
- Encrypted local storage (AES-256)
- Multi-wallet support with labels
- Balance checking (TON + jettons)

### 💱 Token Swaps
- DEX aggregation via swap.coffee
- Optimal routing across multiple DEXs
- Slippage protection
- Transaction emulation before execution
- Support for TON, USDT, USDC, NOT, STON, SCALE, and more

### 📊 Token Analytics
- Real-time price data and charts
- Trust score & scam detection (DYOR.io)
- Market cap, volume, TVL metrics
- Holder analysis
- Token comparison tools

### 🌾 Yield / DeFi
- 2000+ pools from 16 protocols aggregated
- APR/TVL sorting and filtering
- Pool recommendations by risk level
- Position tracking
- Protocols: STON.fi, DeDust, TONCO, EVAA, TonStakers, and more

### 🖼️ NFT Trading
- List wallet NFTs
- Collection search & analytics
- Buy/sell on Marketapp
- Transfer NFTs
- Telegram Gifts market support

### 🌐 DNS Resolution
- Resolve `.ton` domains to addresses
- Domain ownership info
- Expiry tracking

### 📡 Transaction Monitor
- Real-time transaction alerts
- SSE (Server-Sent Events) support
- Background daemon mode
- Multi-wallet monitoring

### 🛡️ Security
- Transaction emulation before execution
- Confirmation required for all writes
- Configurable transfer limits
- Never logs private keys or mnemonics

---

## 📦 Installation

### As OpenClaw Skill

```bash
# Clone the repository
git clone https://github.com/swapcoffee/openclaw-ton-skill.git ~/.openclaw/skills/ton-blockchain

# Install dependencies
cd ~/.openclaw/skills/ton-blockchain
pip install -r requirements.txt

# Optional: Install SSE support for real-time monitoring
pip install sseclient-py
```

### Register with OpenClaw

Add to your OpenClaw skills configuration or let OpenClaw auto-detect from the skills directory.

---

## ⚙️ Configuration

### Required API Keys

Configure API keys via CLI or edit `~/.openclaw/ton-skill/config.json`:

```bash
cd ~/.openclaw/skills/ton-blockchain/scripts

# TonAPI (required for most operations)
python utils.py config set tonapi_key "YOUR_TONAPI_KEY"

# swap.coffee (for swaps and yield) — optional, works without key
python utils.py config set swap_coffee_key "YOUR_SWAP_COFFEE_KEY"

# DYOR (for token analytics) — optional
python utils.py config set dyor_key "YOUR_DYOR_KEY"

# Marketapp (for NFT trading)
python utils.py config set marketapp_key "YOUR_MARKETAPP_KEY"
```

### Where to Get API Keys

| Service | URL | Notes |
|---------|-----|-------|
| TonAPI | https://tonscan.org/api | Free tier available |
| DYOR | https://dyor.io/tonapi?pricing | Token analytics |
| Marketapp | https://marketapp.ws/api-token | NFT trading |

### Wallet Password

Set `WALLET_PASSWORD` environment variable or use `--password` flag for wallet operations.

---

## 🚀 Quick Start

### 1. Create a Wallet

```bash
python wallet.py create --label "main"
# ⚠️ Save the mnemonic phrase! Shown only once.
```

### 2. Check Balance

```bash
python wallet.py balance main --full
```

### 3. Get a Swap Quote

```bash
python swap.py quote --from TON --to USDT --amount 10 --wallet main
```

### 4. Check Token Trust Score

```bash
python analytics.py trust --token NOT
```

### 5. Find Yield Pools

```bash
python yield_cmd.py pools --sort apr --limit 10
```

### 6. Search NFT Collections

```bash
python nft.py search --query "TON Diamonds"
```

### 7. Resolve .ton Domain

```bash
python dns.py resolve wallet.ton
```

### 8. Send TON (with emulation)

```bash
# Emulate first (no actual send)
python transfer.py ton --from main --to recipient.ton --amount 1

# Execute after reviewing emulation
python transfer.py ton --from main --to recipient.ton --amount 1 --confirm
```

### 9. Execute Swap

```bash
python swap.py execute --wallet main --from TON --to USDT --amount 5 --confirm
```

### 10. Start Transaction Monitor

```bash
python monitor.py start -p <password> --daemon
```

---

## 🧪 Test Cases

| ID | Test Case | Command | Expected Output | Status |
|----|-----------|---------|-----------------|--------|
| TC-001 | Create wallet | `python wallet.py create --label test` | New wallet with mnemonic | ✅ |
| TC-002 | Check balance | `python wallet.py balance test` | TON balance in JSON | ✅ |
| TC-003 | Get swap quote (TON → USDT) | `python swap.py quote --from TON --to USDT --amount 1 --wallet test` | Quote with rate and fees | ✅ |
| TC-004 | Execute swap (small amount) | `python swap.py execute --wallet test --from TON --to USDT --amount 0.5 --confirm` | Swap transaction hash | ⚠️ Requires funds |
| TC-005 | Token trust score | `python analytics.py trust --token NOT` | Trust score 0-100 with assessment | ✅ |
| TC-006 | List yield pools | `python yield_cmd.py pools --sort apr --limit 5` | Top 5 pools by APR | ✅ |
| TC-007 | NFT collection search | `python nft.py search --query "TON Diamonds"` | Collection list with addresses | ✅ |
| TC-008 | Resolve .ton domain | `python dns.py resolve foundation.ton` | Wallet address | ✅ |
| TC-009 | Get staking info | `python yield_cmd.py pools --protocol tonstakers` | TonStakers pools data | ✅ |
| TC-010 | Create DCA order | — | Not yet implemented | ❌ |

### Status Legend
- ✅ **Working** — Tested and functional
- ⚠️ **Conditional** — Works but requires specific conditions (funds, API key, etc.)
- ❌ **Not Implemented** — Feature not yet available

---

## 📊 API Coverage

| API Section | Endpoints | Integration Status |
|-------------|-----------|-------------------|
| **swap.coffee Swap** | Route, Build, Status | ✅ Full |
| **swap.coffee Tokens** | List, Info, Search, Holders, Charts | ✅ Full |
| **swap.coffee Yield** | Pools, Protocols, Recommendations | ✅ Full (read-only) |
| **TonAPI Accounts** | Balance, Jettons, NFTs, Transactions | ✅ Full |
| **TonAPI Blockchain** | Send message, Emulate | ✅ Full |
| **TonAPI DNS** | Resolve, Domain info | ✅ Full |
| **TonAPI Staking** | Pool info, Nominators | ✅ Full |
| **DYOR Analytics** | Token info, Trust score, History | ✅ Full |
| **Marketapp NFT** | Collections, Buy, Sell, Gifts | ✅ Full |
| **DCA Orders** | Create, List, Cancel | ❌ Not implemented |
| **Limit Orders** | Create, List, Cancel | ❌ Not implemented |

---

## ⚠️ Known Issues

1. **Yield deposit/withdraw not supported** — swap.coffee yield API is read-only; direct DEX interaction required for LP operations

2. **DCA orders not implemented** — Scheduled purchases feature pending API support

3. **Rate limiting** — Some APIs may rate-limit heavy usage; implement appropriate delays

4. **NFT floor prices** — Requires Marketapp API key; some collections may lack data

5. **Token search** — Server-side filters on yield pools don't work; all filtering is client-side

6. **Transaction monitor SSE** — May fall back to polling if SSE connection drops

---

## 🤝 Contributing

We welcome contributions! Here's how to get started:

### Development Setup

```bash
# Clone the repo
git clone https://github.com/swapcoffee/openclaw-ton-skill.git
cd openclaw-ton-skill

# Install dev dependencies
pip install -r requirements-dev.txt

# Run tests
pytest

# Run linter
ruff check scripts/
```

### Guidelines

1. **Fork** the repository
2. **Create** a feature branch (`git checkout -b feature/amazing-feature`)
3. **Write tests** for new functionality
4. **Ensure** all tests pass (`pytest`)
5. **Lint** your code (`ruff check --fix`)
6. **Commit** with clear messages
7. **Push** and open a Pull Request

### Areas for Contribution

- [ ] DCA order implementation
- [ ] Limit order support
- [ ] Additional DEX integrations
- [ ] Multi-language support
- [ ] Web dashboard
- [ ] More test coverage

---

## 📄 License

This project is licensed under the **MIT License** — see the [LICENSE](LICENSE) file for details.

```
MIT License — Copyright (c) 2026 swap.coffee
```

---

## 🔗 Links

- **swap.coffee**: https://swap.coffee
- **OpenClaw**: https://openclaw.io
- **TON Blockchain**: https://ton.org
- **GitHub Issues**: https://github.com/swapcoffee/openclaw-ton-skill/issues

---

<div align="center">

**Made with ☕️ and ❤️ by AI agents at swap.coffee**

*For the TON ecosystem*

</div>
