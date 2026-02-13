# Advanced Feature Testing Results

**Date:** 2026-02-13
**Tester:** QA Subagent
**Wallet:** skill-test (24.37 TON initial)
**Budget:** ~8 TON for tests

---

## Test Summary

| Test | Status | TON Used |
|------|--------|----------|
| 1.1 Basic Swap TON→USDT | 🔄 Running | 0.5 |
| 1.2 Smart Routing | ⏳ Pending | 0.3 |
| 1.3 Swap Back USDT→TON | ⏳ Pending | - |
| 2.1 NFT Search | ⏳ Pending | 0 |
| 2.2 Gift List | ⏳ Pending | 0 |
| 2.3 NFT Buy | ⏳ Pending | <1 |
| 2.4 NFT Sell | ⏳ Pending | 0 |
| 3.1 Staking List | ⏳ Pending | 0 |
| 3.2 Stake TON | ⏳ Pending | 1 |
| 3.3 Unstake | ⏳ Pending | - |
| 4.1 LP Provide | ⏳ Pending | 1 |
| 4.2 LP Withdraw | ⏳ Pending | - |
| 5.1 Strategy Eligible | ⏳ Pending | 0 |
| 5.2 Create Proxy | ⏳ Pending | ~0.5 |
| 5.3 Limit Order | ⏳ Pending | 0.5 |
| 5.4 DCA Order | ⏳ Pending | 0.1 |
| 6.1 Buy NOT | ⏳ Pending | 0.3 |
| 6.2 Sell NOT | ⏳ Pending | - |

---

## 1. Swap Tests

### 1.1 Basic Swap: 0.5 TON → USDT

**Command:**
```bash
python3 swap.py -p test123 execute --wallet skill-test --from TON --to USDT --amount 0.5 --confirm
```

**Output:**
```
[testing...]
```

---
