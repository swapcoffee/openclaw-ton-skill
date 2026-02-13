# Swap.Coffee Yield API Documentation

Official documentation for swap.coffee Yield API v1.

## Base URL

```
https://backend.swap.coffee/v1
```

## Endpoints

### 1. List Pools

```
GET /v1/yield/pools
```

**Query Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `blockchains` | array | Filter by blockchain (e.g., `ton`) |
| `providers` | array | Filter by DEX/protocol (e.g., `stonfi`, `dedust`, `tonco`) |
| `trusted` | boolean | Only trusted pools (default: true) |
| `with_active_boosts` | boolean | Only pools with active boosts |
| `with_liquidity_from` | string | User address to check liquidity |
| `search_text` | string | Search by pool address or token tickers |
| `order` | string | Sort field (default: `tvl_usd`) |
| `descending_order` | boolean | Sort direction |
| `in_groups` | boolean | Group related pools |
| `size` | integer | Results per page (max 100, default 10) |
| `page` | integer | Page number (default 1) |

**Response:**

```json
{
  "total_count": 2000,
  "pools": [
    {
      "pool": {
        "@type": "dex_pool",
        "address": "EQA-X...",
        "protocol": "dedust",
        "is_trusted": true,
        "tokens": [
          {
            "address": {"blockchain": "ton", "address": "EQT..."},
            "metadata": {
              "name": "Toncoin",
              "symbol": "TON",
              "decimals": 9,
              "verification": "whitelist",
              "image_url": "..."
            }
          }
        ]
      },
      "pool_statistics": {
        "address": "EQA-X...",
        "tvl_usd": 1000000.0,
        "volume_usd": 50000.0,
        "fee_usd": 150.0,
        "apr": 25.5,
        "lp_apr": 20.0,
        "boost_apr": 5.5
      }
    }
  ]
}
```

### 2. Pool Details

```
GET /v1/yield/pool/{pool_address}
```

Returns detailed information about a specific pool.

### 3. User Position

```
GET /v1/yield/pool/{pool_address}/{user_address}
```

**Response:**

```json
{
  "user_lp_amount": "1000000000",
  "user_lp_wallet": "EQW...",
  "boosts": [
    {
      "boost_address": "EQB...",
      "apr": 5.5
    }
  ]
}
```

### 4. Create Transaction (POST)

```
POST /v1/yield/pool/{pool_address}/{user_address}
```

Creates transactions for deposit/withdraw operations.

**Request Body Format:**

The body uses `@type` discriminator (NOT wrapped in `request_data`):

```json
{
  "@type": "operation_type",
  "field1": "value1",
  "field2": "value2"
}
```

**Response Format:**

Array of transaction objects:

```json
[
  {
    "query_id": 1697643564986267,
    "message": {
      "payload_cell": "te6cck...",
      "address": "EQA-X...",
      "value": "100000000"
    }
  }
]
```

### 5. Check Transaction Status

```
GET /v1/yield/result?query_id={query_id}
```

**Response:**

```json
{
  "status": "pending" | "success" | "failed"
}
```

---

## Operations by `@type`

### DEX Operations

#### `dex_provide_liquidity`

Deposit liquidity into DEX pool (stonfi_v2, dedust, tonco).

```json
{
  "@type": "dex_provide_liquidity",
  "user_wallet": "EQA...",
  "asset_1_amount": "1000000000",
  "asset_2_amount": "1000000000",
  "min_lp_amount": "900000000"
}
```

| Field | Required | Description |
|-------|----------|-------------|
| `user_wallet` | Yes | Sender wallet address |
| `asset_1_amount` | Yes | Amount of first token (min units) |
| `asset_2_amount` | Yes | Amount of second token (min units) |
| `min_lp_amount` | No | Minimum LP tokens to receive |

#### `dex_withdraw_liquidity`

Withdraw liquidity from DEX pool.

```json
{
  "@type": "dex_withdraw_liquidity",
  "user_address": "EQA...",
  "lp_amount": "1000000000"
}
```

| Field | Required | Description |
|-------|----------|-------------|
| `user_address` | Yes | User wallet address (NOTE: `user_address`, not `user_wallet`!) |
| `lp_amount` | Yes | LP tokens to burn (min units) |

### STON.fi Farm Operations

#### `dex_stonfi_lock_staking`

Lock LP tokens in STON.fi farm for additional rewards.

```json
{
  "@type": "dex_stonfi_lock_staking",
  "lp_amount": "1000000000",
  "minter_address": "EQM..."
}
```

#### `dex_stonfi_withdraw_staking`

Withdraw LP tokens from STON.fi farm.

```json
{
  "@type": "dex_stonfi_withdraw_staking",
  "position_address": "EQP..."
}
```

### Liquid Staking Operations

#### `liquid_staking_stake`

Stake tokens in liquid staking pool (tonstakers, bemo, hipo, kton, stakee).

```json
{
  "@type": "liquid_staking_stake",
  "amount": "1000000000"
}
```

#### `liquid_staking_unstake`

Unstake from liquid staking pool.

```json
{
  "@type": "liquid_staking_unstake",
  "amount": "1000000000"
}
```

### Lending Operations

#### `lending_deposit`

Deposit to lending protocol (evaa).

```json
{
  "@type": "lending_deposit",
  "amount": "1000000000"
}
```

#### `lending_withdraw`

Withdraw from lending protocol.

```json
{
  "@type": "lending_withdraw",
  "amount": "1000000000"
}
```

---

## Supported Providers

| Provider | Type | Operations |
|----------|------|------------|
| `stonfi` | DEX (v1) | withdraw only |
| `stonfi_v2` | DEX (v2) | deposit, withdraw, farm |
| `dedust` | DEX | deposit, withdraw |
| `tonco` | DEX | deposit, withdraw |
| `tonstakers` | Liquid Staking | stake, unstake |
| `bemo` | Liquid Staking | stake, unstake |
| `bemo_v2` | Liquid Staking | stake, unstake |
| `hipo` | Liquid Staking | stake, unstake |
| `kton` | Liquid Staking | stake, unstake |
| `stakee` | Liquid Staking | stake, unstake |
| `evaa` | Lending | deposit, withdraw |
| `storm_trade` | Derivatives | - |
| `torch_finance` | Vault | - |
| `dao_lama_vault` | Vault | - |
| `bidask` | DEX | - |
| `coffee` | DEX | - |

---

## Example: Deposit to DEX Pool

```bash
curl -X POST "https://backend.swap.coffee/v1/yield/pool/EQCkWxfyhAkim3g2DjKQQg8T5P4g-Q1-K_jErGcDJZ4i-vqR/EQATYemb_I7KeyQVIekCXWsspttRQMjtdp3_UV5OT-u6hZLm" \
  -H "Content-Type: application/json" \
  -d '{"@type":"dex_provide_liquidity","user_wallet":"EQATYemb_I7KeyQVIekCXWsspttRQMjtdp3_UV5OT-u6hZLm","asset_1_amount":"1000000000","asset_2_amount":"1000000000"}'
```

## Example: Stake to Liquid Staking

```bash
curl -X POST "https://backend.swap.coffee/v1/yield/pool/EQCkWxfyhAkim3g2DjKQQg8T5P4g-Q1-K_jErGcDJZ4i-vqR/EQATYemb_I7KeyQVIekCXWsspttRQMjtdp3_UV5OT-u6hZLm" \
  -H "Content-Type: application/json" \
  -d '{"@type":"liquid_staking_stake","amount":"1000000000"}'
```

---

## Important Notes

1. **Body format**: Always use `@type` discriminator directly in body, NOT wrapped in `request_data`
2. **Address format**: Use URL-safe base64 (replace `+` with `-`, `/` with `_`)
3. **Amounts**: All amounts are in minimum units (nanoTON for TON = 10^-9)
4. **Response**: POST returns array of `{query_id, message: {...}}`
5. **Status check**: Use `GET /v1/yield/result?query_id=...` to check transaction status

---

*Last updated: 2026-02-13*
