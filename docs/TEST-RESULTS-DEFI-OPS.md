# DeFi Operations Test Results

**Test Date:** 2026-02-13  
**Tester:** QA Bot  
**Wallet:** test-4 (EQDuyIdfo8DTt5yIQChAneS_mWMhi5_qQJcNzhDc40ClXVzd)  
**Initial Balance:** 5 TON  
**Budget:** ~5 TON

---

## Summary

| Feature | Status | Notes |
|---------|--------|-------|
| Yield Pools List | ✅ PASS | Server-side filtering works |
| Pool Details | ⚠️ BUG | Returns null address, empty tokens |
| Liquid Staking (stake) | ✅ PASS | Fixed & tested with real TX |
| Liquid Staking (unstake) | ✅ PASS | Simulation works |
| Staking.py pools | ✅ PASS | Lists all staking protocols |
| Staking.py positions | ✅ PASS | Detects positions correctly |
| Staking.py stake | ✅ PASS | **BUG FIXED** - API format corrected |
| Staking.py unstake | ✅ PASS | **BUG FIXED** - API format corrected |
| Profile history | ❌ FAIL | API returns 404 |
| Profile stats | ❌ FAIL | API returns 404 |
| Contests | ❌ FAIL | API endpoint error |

---

## 1. Yield Pools Tests

### 1.1 List Pools ✅

```bash
python3 yield_cmd.py pools --sort tvl --size 20
```

**Result:** SUCCESS - Returns 2000 pools from 16 protocols including:
- tonstakers: TON/tsTON (TVL $64.5M, APR 2.96%)
- stonfi_v2: USDT/TON (TVL $4.9M, APR 8.3%)
- dedust: TON/USDT (TVL $931K, APR 14.67%)
- bemo: TON/stTON (TVL $3.4M, APR 2.16%)

### 1.2 Search Pools ✅

```bash
python3 yield_cmd.py pools --search "USDT" --size 5
```

**Result:** SUCCESS - Finds USDT pools correctly

### 1.3 Pool Details ⚠️ BUG

```bash
python3 yield_cmd.py pool --id EQA-X_yo3fzzbDbJ_0bzFWKqtRuZFIRa1sJsveZJ1YpViO3r
```

**Result:** Returns incomplete data:
```json
{
  "pool": {
    "address": null,        // BUG: Should have address
    "tokens": [],           // BUG: Should have tokens
    "tvl_usd": 931582.45,   // OK
    "apr": 14.67            // OK
  }
}
```

**Bug:** `_normalize_pool()` doesn't extract address/tokens from single pool response.

### 1.4 DEX Deposit (Requires Both Tokens)

```bash
python3 yield_cmd.py deposit --pool EQCGScrZe... --wallet EQDuy... --amount1 1e9 --amount2 0
```

**Result:** Expected error "Both token amounts must be positive" - correct behavior for DEX pools.

---

## 2. Liquid Staking Tests

### 2.1 Staking Pools List ✅

```bash
python3 staking.py pools --sort apr
```

**Result:** SUCCESS - Lists 6 staking protocols:
- kton: 4.06% APR
- hipo: 3.26% APR
- stakee: 3.17% APR
- tonstakers: 2.96% APR
- bemo: 2.16% APR
- bemo_v2: 2.16% APR

### 2.2 Get Position ✅

```bash
python3 staking.py position --pool EQCkWx... --wallet test-4 -p test123
```

**Result:** SUCCESS - Returns position info (with wallet resolution)

### 2.3 Stake (yield_cmd.py) ✅

```bash
python3 yield_cmd.py stake --pool EQCkWx... --wallet EQDuy... --amount 1000000000
```

**Result:** SUCCESS - Builds transaction for TonConnect:
```json
{
  "query_id": 1697643564986288,
  "message": {
    "address": "EQCkWxfyhAkim3g2DjKQQg8T5P4g-Q1-K_jErGcDJZ4i-vqR",
    "value": "2000000000"
  }
}
```

### 2.4 Stake (staking.py) ✅ **BUG FIXED**

**Before Fix:**
```bash
python3 staking.py stake --pool EQCkWx... --wallet test-4 --amount 1 -p test123
```
**Error:** `"Some of required json fields were not received: requestData(request_data)"`

**Bug:** `build_stake_tx()` was sending wrong API format:
```python
# WRONG:
{"action": "provide", "input_amount": amount}

# CORRECT:
{"request_data": {"yieldTypeResolver": "liquid_staking_stake", "amount": str(amount)}}
```

**After Fix:**
```bash
python3 staking.py --password test123 stake --pool EQCkWx... --wallet test-4 --amount 1
```

**Result:** SUCCESS - Simulation shows:
- Deposit 1 TON to Tonstakers
- Receive ~0.918 tsTON
- Fee: ~0.034 TON
- Contract deploy (first tx initializes wallet)

### 2.5 Stake with --confirm ✅ **REAL TX**

```bash
python3 staking.py --password test123 stake --pool EQCkWx... --wallet test-4 --amount 1 --confirm
```

**Result:** SUCCESS - Transaction executed:
- **TX Hash:** 4468b36ab58517aa5647bf31f05d635938167d8c2b4c78108b49a246af7c4993
- **Before:** 5.0 TON, 0 tsTON
- **After:** 3.96 TON, 0.918 tsTON
- **Cost:** ~1.04 TON (1 TON staked + fees + contract deploy)

### 2.6 Unstake (staking.py) ✅ **BUG FIXED**

**After Fix:**
```bash
python3 staking.py --password test123 unstake --pool EQCkWx... --wallet test-4 --amount 0.5
```

**Result:** SUCCESS - Simulation shows:
- Withdraw 0.5 TON from Tonstakers
- Fee: ~0.12 TON
- Receive withdrawal receipt NFT

---

## 3. Profile Tests

### 3.1 Profile History ❌ FAIL

```bash
python3 profile.py profile-history --wallet EQDuy...
```

**Result:** 404 Not Found

**Root Cause:** API endpoint `/v1/profile/history` doesn't exist or requires different parameters.

### 3.2 DEX Statistics ❌ FAIL

```bash
python3 profile.py stats
```

**Result:** 404 Not Found

**Root Cause:** API endpoint `/v1/statistics` doesn't exist.

### 3.3 Active Contests ❌ FAIL

```bash
python3 profile.py contests-active
```

**Result:** `"Path parameter 'id' has invalid value 'active'"`

**Root Cause:** API expects `/v1/contests/{id}` not `/v1/contests/active`

---

## 4. Bugs Fixed

### Bug #1: staking.py Wrong API Format

**File:** `scripts/staking.py`  
**Functions:** `build_stake_tx()`, `build_unstake_tx()`

**Problem:** API was being called with wrong JSON format:
```python
{"action": "provide", "input_amount": amount}  # WRONG
```

**Fix:** Use correct format with `request_data` wrapper:
```python
{
  "request_data": {
    "yieldTypeResolver": "liquid_staking_stake",  # or "liquid_staking_unstake"
    "amount": str(amount_nano)
  }
}
```

**Commit:** Will be committed after tests.

---

## 5. Bugs to Fix (Remaining)

### Bug #2: Pool Details Missing Data

**File:** `scripts/yield_cmd.py`  
**Function:** `get_pool_details()` → `_normalize_pool()`

**Problem:** When fetching single pool, address and tokens are null/empty.

**Fix Needed:** Handle different response format for single pool vs list.

### Bug #3: Profile API 404 Errors

**File:** `scripts/profile.py`

**Problem:** Multiple endpoints return 404:
- `/v1/profile/history`
- `/v1/statistics`
- `/v1/contests/active`

**Fix Needed:** Verify correct API endpoints with swap.coffee documentation or remove unsupported features.

---

## 6. Final Wallet State

```json
{
  "address": "EQDuyIdfo8DTt5yIQChAneS_mWMhi5_qQJcNzhDc40ClXVzd",
  "status": "active",
  "ton_balance": 3.965891194,
  "jettons": [
    {
      "symbol": "tsTON",
      "name": "Tonstakers TON",
      "balance": 0.918988802,
      "verified": true
    }
  ]
}
```

**Budget Used:** ~1.04 TON  
**Budget Remaining:** ~3.96 TON

---

## 7. Test Commands Reference

```bash
# Yield pools
python3 yield_cmd.py pools --sort tvl --size 20
python3 yield_cmd.py pools --provider tonstakers --size 5
python3 yield_cmd.py pools --search "USDT" --size 5
python3 yield_cmd.py pool --id EQA-X_yo...

# Liquid staking (yield_cmd.py)
python3 yield_cmd.py stake --pool EQCkWx... --wallet EQDuy... --amount 1000000000
python3 yield_cmd.py unstake --pool EQCkWx... --wallet EQDuy... --amount 500000000

# Staking (staking.py with signing)
python3 staking.py pools --sort apr
python3 staking.py --password test123 position --pool EQCkWx... --wallet test-4
python3 staking.py --password test123 stake --pool EQCkWx... --wallet test-4 --amount 1
python3 staking.py --password test123 stake --pool EQCkWx... --wallet test-4 --amount 1 --confirm
python3 staking.py --password test123 unstake --pool EQCkWx... --wallet test-4 --amount 0.5 --confirm
```

---

## 8. Recommendations

1. **Fix Pool Details Bug** - Update `_normalize_pool()` to handle single pool responses
2. **Remove/Update Profile APIs** - Many profile endpoints don't exist; either remove or find correct endpoints
3. **Add SKILL.md Corrections** - Update documentation to match actual CLI options
4. **Add Integration Tests** - Create automated tests for DeFi operations
