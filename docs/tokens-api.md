# swap.coffee Tokens API

**Base URL:** `https://tokens.swap.coffee`

**OpenAPI Spec:** `/api/v3/openapi.yaml`

## Overview

The Tokens API provides comprehensive jetton (TON tokens) data including:
- Token metadata and verification status
- Real-time market stats (price, volume, TVL, market cap)
- Price history charts
- Top holders
- Account balances
- Hybrid search with memepad support

## Authentication

Most endpoints are public and don't require authentication.
Some admin endpoints (verification updates, imports) require `X-Api-Key` header.

---

## Endpoints

### GET /api/v3/jettons

List jettons with optional filters.

**Parameters:**
| Param | Type | Default | Description |
|-------|------|---------|-------------|
| search | string | - | Search query (name, symbol, address) |
| verification | array | WHITELISTED | Filter: WHITELISTED, COMMUNITY, UNKNOWN, BLACKLISTED |
| label_id | integer | - | Filter by label ID |
| page | integer | 1 | Page number (1-indexed) |
| size | integer | 100 | Results per page (max 100) |

**Response:**
```json
[
  {
    "address": "0:...",
    "name": "Tether USD",
    "symbol": "USDT",
    "decimals": 6,
    "verification": "WHITELISTED",
    "image_url": "https://...",
    "total_supply": "1000000000",
    "mintable": false,
    "created_at": "2023-10-01T12:00:00Z",
    "market_stats": {...},
    "labels": [...]
  }
]
```

---

### GET /api/v3/jettons/{address}

Get detailed jetton information.

**Parameters:**
| Param | Type | Default | Description |
|-------|------|---------|-------------|
| address | string | required | Jetton master address |
| refresh_price | boolean | true | Whether to refresh price data |

**Response:**
```json
{
  "address": "0:...",
  "name": "Tether USD",
  "symbol": "USDT",
  "decimals": 6,
  "verification": "WHITELISTED",
  "image_url": "https://...",
  "total_supply": "1000000000",
  "mintable": false,
  "market_stats": {
    "holders_count": 1000,
    "price_usd": 1.0,
    "price_change_5m": 0.01,
    "price_change_1h": 0.02,
    "price_change_6h": 0.03,
    "price_change_24h": 0.1,
    "price_change_7d": 0.2,
    "volume_usd_24h": 1000000.0,
    "tvl_usd": 1000000.0,
    "fdmc": 1000000.0,
    "mcap": 1000000.0,
    "trust_score": 100
  }
}
```

---

### GET /api/v3/jettons/{address}/price-chart

Get price chart data.

**Parameters:**
| Param | Type | Default | Description |
|-------|------|---------|-------------|
| address | string | required | Jetton master address |
| from | string | required | Start timestamp (ISO 8601) |
| to | string | required | End timestamp (ISO 8601) |
| currency | string | usd | Currency: usd or ton |

**Response:**
```json
{
  "points": [
    {"value": 1.234, "time": "2024-01-15T10:30:00Z"},
    {"value": 1.235, "time": "2024-01-15T10:35:00Z"}
  ]
}
```

---

### GET /api/v3/jettons/{address}/holders

Get top 10 jetton holders.

**Parameters:**
| Param | Type | Description |
|-------|------|-------------|
| address | string | Jetton master address |

**Response:**
```json
[
  {
    "owner": "UQAp9u76...",
    "wallet": "0:251F2F00...",
    "master": "0:29F6EEFA...",
    "balance": "1234567890"
  }
]
```

---

### POST /api/v3/jettons/by-addresses

Bulk fetch jettons by addresses (up to 100).

**Parameters:**
| Param | Type | Default | Description |
|-------|------|---------|-------------|
| refresh_price | boolean | true | Whether to refresh prices |

**Body:**
```json
[
  "0:a5d12e31be87867851a28d3ce271203c8fa1a28ae826256e73c506d94d49edad",
  "0:..."
]
```

**Response:** Array of jetton objects.

---

### GET /api/v3/accounts/{address}/jettons

Get all jettons owned by an account.

**Parameters:**
| Param | Type | Description |
|-------|------|-------------|
| address | string | Owner wallet address |

**Response:**
```json
{
  "items": [
    {
      "balance": "1000000000",
      "jetton_address": "0:...",
      "jetton_wallet": "0:...",
      "jetton": {...}
    }
  ]
}
```

---

### GET /api/v3/hybrid-search

Advanced search with memepad support.

**Parameters:**
| Param | Type | Default | Description |
|-------|------|---------|-------------|
| search | string | - | Search query |
| verification | array | WHITELISTED | Verification levels |
| size | integer | 20 | Results per page (max 100) |
| page | integer | 1 | Page number |
| kind | string | DEXES | Search kind (see below) |
| sort | string | - | Sort field (see below) |

**Kind values:**
- `DEXES` — Regular DEX tokens
- `ALL` — All tokens (requires COMMUNITY verification)
- `MEMES_ALL` — All meme tokens
- `MEMES_DEXES` — Meme tokens on DEXes
- `MEMES_MEMEPADS` — Memepad tokens only

**Sort values:**
- `FDMC` — Fully Diluted Market Cap
- `TVL` — Total Value Locked
- `MCAP` — Market Cap
- `VOLUME_24H` — 24h Volume
- `PRICE_CHANGE_24H` — 24h Price Change

**Response:** Array of ApiPolyJetton (common or memepad jettons).

---

### GET /api/v3/labels

Get all available labels.

**Response:**
```json
[
  {
    "id": 1,
    "label": "defi",
    "created_at": "2023-10-01T12:00:00Z"
  }
]
```

---

## Market Stats Schema

```typescript
interface ApiJettonMarketStats {
  holders_count: number;      // Number of holders
  price_usd: number;          // Current price in USD
  price_change_5m: number;    // 5-minute price change (%)
  price_change_1h: number;    // 1-hour price change (%)
  price_change_6h: number;    // 6-hour price change (%)
  price_change_24h: number;   // 24-hour price change (%)
  price_change_7d: number;    // 7-day price change (%)
  volume_usd_24h: number;     // 24-hour trading volume in USD
  tvl_usd: number;            // Total Value Locked in USD
  fdmc: number;               // Fully Diluted Market Cap
  mcap: number;               // Market Cap
  trust_score?: number;       // Trust score (0-100)
}
```

---

## Verification Levels

| Level | Description |
|-------|-------------|
| `WHITELISTED` | Verified by swap.coffee team |
| `COMMUNITY` | Community-verified |
| `UNKNOWN` | Not verified |
| `BLACKLISTED` | Known scam or blacklisted |

---

## Example Usage

### Python

```python
from tokens import (
    list_jettons,
    get_jetton_info,
    get_price_chart,
    get_jetton_holders,
    hybrid_search,
    get_account_jettons,
)

# List USDT tokens
result = list_jettons(search="USDT", verification=["WHITELISTED"])

# Get token info with market stats
info = get_jetton_info("EQCxE6mUtQJKFnGfaROTKOt1lZbDiiX1kCixRv7Nw2Id_sDs")
print(f"Price: ${info['market_stats']['price_usd']}")
print(f"24h Change: {info['market_stats']['price_change_24h']}%")

# Search memecoins
memes = hybrid_search(search="pepe", kind="MEMES_ALL", sort="VOLUME_24H")

# Get wallet balances
balances = get_account_jettons("UQBvW8Z5huBkMJYdnfAEM5JqTNkgxvhw...")
```

### CLI

```bash
# List jettons
python tokens.py list --search USDT --size 3

# Get info
python tokens.py info EQCxE6mUtQJKFnGfaROTKOt1lZbDiiX1kCixRv7Nw2Id_sDs

# Price chart (last 24h)
python tokens.py price-chart EQCxE6mUtQJKFnGfaROTKOt1lZbDiiX1kCixRv7Nw2Id_sDs --hours 24

# Top holders
python tokens.py holders EQCxE6mUtQJKFnGfaROTKOt1lZbDiiX1kCixRv7Nw2Id_sDs

# Search memes
python tokens.py search --query pepe --kind MEMES_ALL --sort VOLUME_24H

# Account balances
python tokens.py balances UQBvW8Z5huBkMJYdnfAEM5JqTNkgxvhw...

# Bulk fetch
python tokens.py bulk EQCxE6... EQBlqs... EQAvlW...
```

---

## Error Handling

All endpoints return JSON with error structure:

```json
{
  "error": "Error description"
}
```

HTTP Status Codes:
- `200` — Success
- `400` — Invalid request
- `404` — Not found
- `500` — Server error

---

## Rate Limits

Public API — no strict limits, but recommended:
- Max 10 requests/second
- Use bulk endpoints when possible
- Cache responses where appropriate
