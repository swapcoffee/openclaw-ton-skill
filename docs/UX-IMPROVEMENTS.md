# UX Improvements Roadmap

**Document Version:** 1.0  
**Created:** 2026-02-13  
**Author:** AI Product Manager

---

## Overview

This document outlines concrete UX improvements for the OpenClaw TON Skill to make blockchain interactions more intuitive, safer, and efficient for end users.

---

## 🎯 Priority 1: Critical UX Fixes

### 1.1 Clearer Error Messages

**Current State:**  
Error messages often expose raw API responses or technical details.

**Example:**
```
"error": "Cannot resolve recipient: {'error': \"not resolved: can't unmarshal null\"}"
```

**Proposed Improvement:**
```
❌ Domain "test.ton" not found

Possible reasons:
• Domain doesn't exist or expired
• No wallet address linked to this domain
• Network connectivity issue

💡 Tip: Try using the full wallet address instead
```

**Implementation:**
- Create `errors.py` module with user-friendly error mapping
- Wrap all API errors with contextual explanations
- Include actionable suggestions where possible

---

### 1.2 Transaction Confirmation UX

**Current State:**  
Users must pass `--confirm` flag. No visual summary before execution.

**Proposed Improvement:**

Before executing, show a clear summary card:

```
╔══════════════════════════════════════════════════════════╗
║                    📤 OUTGOING TRANSFER                  ║
╠══════════════════════════════════════════════════════════╣
║  From:     main-wallet                                   ║
║  To:       foundation.ton (UQBvW8...)                    ║
║  Amount:   10 TON (~$55.20 USD)                          ║
║  Fee:      ~0.005 TON                                    ║
║  Total:    10.005 TON                                    ║
╠══════════════════════════════════════════════════════════╣
║  ⚠️  First time sending to this address                  ║
╚══════════════════════════════════════════════════════════╝

Type 'yes' to confirm or 'no' to cancel:
```

**For Telegram/Chat Interface:**
- Use inline buttons: `[✅ Confirm] [❌ Cancel]`
- Add timeout (60s) to prevent stale confirmations

---

### 1.3 Progress Indicators

**Current State:**  
Long operations (balance fetch, pool scan) show no feedback.

**Proposed Improvement:**
```
⏳ Fetching wallet balance...
  ├── TON balance ✓
  ├── Jettons (5 found) ✓
  └── USD conversion ✓
✅ Done in 1.2s
```

**Implementation:**
- Add `--quiet` flag for script-mode (JSON only)
- Default to progress output for interactive use
- Use spinners or progress bars where appropriate

---

## 🎯 Priority 2: Usability Enhancements

### 2.1 Smart Defaults

**Current State:**  
Users must specify many parameters explicitly.

**Proposed Improvements:**

| Parameter | Current | Smart Default |
|-----------|---------|---------------|
| Slippage | Required | 1% (standard) |
| Wallet | Required | Use "default" wallet if only one exists |
| Amount format | Number | Accept "all", "half", "10%" |
| Token names | Case-sensitive | Case-insensitive |

**Examples:**
```bash
# Currently:
python swap.py execute --wallet main --from TON --to USDT --amount 5 --slippage 1.0

# Improved:
python swap.py TON→USDT 5  # Uses default wallet, 1% slippage
```

---

### 2.2 Interactive Mode

**Current State:**  
CLI only, requires full command each time.

**Proposed Improvement:**
Add interactive shell mode:

```bash
$ python ton-shell.py
Welcome to TON Skill Interactive Mode
Type 'help' for commands, 'exit' to quit

ton> balance
┌─────────────┬──────────────┬───────────┐
│ Wallet      │ TON          │ USD       │
├─────────────┼──────────────┼───────────┤
│ main        │ 125.50 TON   │ $691.00   │
│ trading     │ 45.20 TON    │ $249.00   │
└─────────────┴──────────────┴───────────┘

ton> swap 10 TON → USDT
Quote: 10 TON → 55.15 USDT
Route: TON → STON.fi → USDT
Fee: 0.15 TON
Proceed? [y/n]:
```

---

### 2.3 Aliases and Shortcuts

**Current State:**  
Full command names required.

**Proposed Aliases:**

| Full Command | Alias |
|--------------|-------|
| `wallet.py balance` | `bal` |
| `transfer.py ton` | `send` |
| `swap.py execute` | `swap` |
| `yield_cmd.py pools` | `pools` |
| `analytics.py trust` | `check` |

**Plus command shortcuts:**
```bash
ton send 10 @alice          # Send 10 TON to contact "alice"
ton send 10 wallet.ton      # Send 10 TON to .ton domain
ton swap TON USDT 100       # Swap 100 TON to USDT
ton check SCALE             # Check token trust score
```

---

### 2.4 Better Output Formatting

**Current State:**  
Raw JSON output for most commands.

**Proposed Improvements:**

#### For `wallet balance --full`:
```
💼 Wallet: main-wallet
📍 Address: UQBvW8Z5huBkMJYdnf...

┌───────────┬────────────────┬──────────────┐
│ Token     │ Balance        │ Value (USD)  │
├───────────┼────────────────┼──────────────┤
│ TON       │ 125.50         │ $691.00      │
│ USDT      │ 500.00         │ $500.00      │
│ NOT       │ 10,000.00      │ $89.50       │
├───────────┼────────────────┼──────────────┤
│ TOTAL     │                │ $1,280.50    │
└───────────┴────────────────┴──────────────┘
```

#### For `yield pools`:
```
🌾 Top Yield Pools (sorted by APR)

 #  │ Pool          │ APR     │ TVL         │ Protocol   │ Risk
────┼───────────────┼─────────┼─────────────┼────────────┼──────
 1  │ TON/USDT      │ 45.2%   │ $12.5M      │ STON.fi    │ 🟢 Low
 2  │ TON/STON      │ 38.7%   │ $8.2M       │ DeDust     │ 🟡 Med
 3  │ NOT/TON       │ 125.3%  │ $2.1M       │ TONCO      │ 🔴 High

Use: yield pool --id <address> for details
```

**Implementation:**
- Add `--format` flag: `json` (default for scripts), `table`, `pretty`
- Auto-detect TTY and use pretty format for interactive use

---

## 🎯 Priority 3: Safety Improvements

### 3.1 Transaction Warnings

Add contextual warnings based on transaction analysis:

| Scenario | Warning |
|----------|---------|
| First-time recipient | ⚠️ You've never sent to this address before. Double-check it's correct. |
| Large amount (>$100) | 💰 This is a significant amount. Please verify all details. |
| Unverified token | 🚨 This token is not on the whitelist. Trust score: 35/100. |
| High slippage | ⚠️ Slippage set to 5%. You may receive significantly less. |
| Low liquidity | 📉 Low liquidity detected. Price impact: ~3.5%. |
| Contract interaction | 🔐 This transaction interacts with a smart contract. |

---

### 3.2 Confirmation Levels

**Current State:**  
Single `--confirm` flag for all operations.

**Proposed Improvement:**
Tiered confirmation based on risk:

| Tier | Trigger | Confirmation |
|------|---------|--------------|
| 🟢 Low | Balance check, quotes | None |
| 🟡 Medium | Transfers < $50 | Single confirm |
| 🟠 High | Transfers $50-500 | Confirm + re-type amount |
| 🔴 Critical | Transfers > $500, new addresses | Confirm + password + countdown |

**Example critical confirmation:**
```
🔴 HIGH-VALUE TRANSACTION

You are about to send 1,000 TON (~$5,520 USD)
To: NEW ADDRESS (never used before)

This action cannot be undone.

To confirm, type the amount you are sending: _____
Enter wallet password: _____
Transaction will execute in 10...9...8...
```

---

### 3.3 Dry Run by Default

**Current State:**  
Emulation requires explicit request.

**Proposed Improvement:**
- Make `--dry-run` (emulation) the default behavior
- Use `--execute` or `--confirm` for actual execution
- Show clear "SIMULATION" label in output

```
╔════════════════════════════════════════╗
║          🧪 SIMULATION MODE            ║
║    No actual transaction sent          ║
╚════════════════════════════════════════╝

If executed:
• 10 TON would be sent to recipient
• Fee: ~0.005 TON
• Remaining balance: 115.495 TON

To execute for real, add --execute flag
```

---

## 🎯 Priority 4: Discoverability

### 4.1 Contextual Help

**Current State:**  
`--help` shows all options. Hard to find relevant commands.

**Proposed Improvement:**
Add contextual suggestions:

```bash
$ python wallet.py balance trading
Balance: 50.25 TON

💡 Related commands:
   • wallet.py balance trading --full    # Include jettons
   • transfer.py ton --from trading      # Send TON
   • swap.py quote --wallet trading      # Get swap quote
```

---

### 4.2 Onboarding Flow

**Current State:**  
Users must read docs to get started.

**Proposed Improvement:**
First-run wizard:

```
Welcome to OpenClaw TON Skill! 🔷

Let's get you set up:

Step 1 of 4: API Keys
━━━━━━━━━━━━━━━━━━━━
TonAPI key enables blockchain queries.
Get yours free at: https://tonscan.org/api

Enter TonAPI key (or press Enter to skip): _____

[Continue to Step 2...]
```

---

### 4.3 Command Suggestions

When user makes a typo or invalid command:

```bash
$ python walet.py list
Error: Unknown script 'walet.py'

Did you mean?
  • wallet.py list     # List all wallets
  • wallet.py balance  # Check wallet balance
```

---

## 🎯 Priority 5: Monitoring & Notifications

### 5.1 Rich Transaction Notifications

**Current State:**  
Monitor outputs raw JSON events.

**Proposed Improvement:**
Formatted notifications:

```
📥 Incoming Transfer
━━━━━━━━━━━━━━━━━━━━━
Wallet: trading
Amount: +25.00 TON (~$137.50)
From: UQBvW8Z5... (unknown)
Time: Just now
TX: tonscan.org/tx/abc123...
```

---

### 5.2 Daily Digest

Optional daily summary:

```
📊 Daily Wallet Summary — Feb 13, 2026
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Portfolio Value: $2,450.25 (+$125.50 / +5.4%)

Transactions (3):
  📥 +25 TON from UQBvW8...
  📤 -10 USDT to wallet.ton
  🔄 Swapped 5 TON → 27.5 USDT

Top Movers:
  📈 NOT +12.5%
  📉 SCALE -3.2%

Active Yield: $45.20 earned this week
```

---

### 5.3 Price Alerts

```bash
python alert.py set --token TON --above 6.00
python alert.py set --token TON --below 4.50

# Later...
🔔 Price Alert: TON reached $6.05 (+8.2%)
Your alert: TON above $6.00
```

---

## 📋 Implementation Roadmap

| Phase | Improvements | Timeline |
|-------|--------------|----------|
| **Phase 1** | Error messages, confirmation UX, progress indicators | Week 1-2 |
| **Phase 2** | Smart defaults, output formatting, aliases | Week 3-4 |
| **Phase 3** | Safety warnings, confirmation tiers | Week 5-6 |
| **Phase 4** | Interactive mode, onboarding wizard | Week 7-8 |
| **Phase 5** | Rich notifications, daily digest, price alerts | Week 9-10 |

---

## 📊 Success Metrics

| Metric | Current | Target |
|--------|---------|--------|
| User errors due to confusing output | Unknown | -50% |
| Time to complete first transaction | ~10 min | <3 min |
| Support requests for "how to X" | Unknown | -70% |
| User-reported "unsafe" feelings | Unknown | Near 0 |

---

## 🗣️ User Feedback Integration

Future improvements should be driven by:
1. GitHub Issues tagged `ux`
2. Community Discord feedback
3. Usage analytics (opt-in)
4. Direct user interviews

---

## Conclusion

These UX improvements aim to make the OpenClaw TON Skill more intuitive, safer, and pleasant to use. By focusing on clear communication, smart defaults, and contextual guidance, we can lower the barrier to entry for blockchain interactions while maintaining the power and flexibility needed by advanced users.

The key principles:
- **Safety first**: Make it hard to make mistakes
- **Progressive disclosure**: Simple by default, powerful when needed
- **Clear feedback**: Always tell the user what's happening
- **Smart defaults**: Reduce cognitive load
- **Contextual help**: Guide users where they are

---

*Document maintained by AI Product Manager*  
*Last updated: 2026-02-13*
