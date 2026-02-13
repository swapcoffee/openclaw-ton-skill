#!/usr/bin/env python3
"""
OpenClaw TON Skill — swap.coffee Tokens API

Endpoints (https://tokens.swap.coffee):
- GET /api/v3/jettons — List jettons (search, verification filter, pagination)
- GET /api/v3/jettons/{address} — Get jetton details with market stats
- GET /api/v3/jettons/{address}/price-chart — Price chart
- GET /api/v3/jettons/{address}/holders — Top 10 holders
- POST /api/v3/jettons/by-addresses — Bulk fetch (up to 100)
- GET /api/v3/accounts/{address}/jettons — Account's jetton balances
- GET /api/v3/hybrid-search — Advanced search with memepad support
- GET /api/v3/labels — List all labels
"""

import sys
import json
import argparse
from pathlib import Path
from typing import Optional, List
from datetime import datetime, timezone

# Локальный импорт
script_dir = Path(__file__).parent
sys.path.insert(0, str(script_dir))

from utils import tokens_api_request  # noqa: E402
from common import (  # noqa: E402
    format_price,
    format_large_number,
)


# =============================================================================
# Constants
# =============================================================================

# Search kinds for hybrid-search endpoint
SEARCH_KINDS = ["ALL", "DEXES", "MEMES_ALL", "MEMES_DEXES", "MEMES_MEMEPADS"]

# Sort options for search results
SORT_OPTIONS = ["FDMC", "TVL", "MCAP", "VOLUME_24H", "PRICE_CHANGE_24H"]


# =============================================================================
# Jettons API
# =============================================================================


def list_jettons(
    search: Optional[str] = None,
    verification: Optional[List[str]] = None,
    label_id: Optional[int] = None,
    page: int = 1,
    size: int = 20,
) -> dict:
    """
    List jettons with optional filters.

    Args:
        search: Search query (name, symbol, address)
        verification: List of verification levels (WHITELISTED, COMMUNITY, UNKNOWN, BLACKLISTED)
        label_id: Filter by label ID
        page: Page number (1-indexed)
        size: Results per page (max 100)

    Returns:
        dict with jettons list
    """
    params = {
        "page": page,
        "size": min(size, 100),
    }

    if search:
        params["search"] = search
    if verification:
        params["verification"] = ",".join(verification)
    if label_id is not None:
        params["label_id"] = label_id

    result = tokens_api_request("/api/v3/jettons", params=params)

    if not result["success"]:
        return result

    jettons = result["data"]

    # Format output
    return {
        "success": True,
        "count": len(jettons),
        "page": page,
        "size": size,
        "jettons": [_format_jetton(j) for j in jettons],
    }


def get_jetton_info(address: str, refresh_price: bool = True) -> dict:
    """
    Get detailed jetton information with market stats.

    Args:
        address: Jetton master address
        refresh_price: Whether to refresh price data

    Returns:
        dict with jetton info and market stats
    """
    params = {"refresh_price": str(refresh_price).lower()}

    result = tokens_api_request(f"/api/v3/jettons/{address}", params=params)

    if not result["success"]:
        return result

    jetton = result["data"]

    return {
        "success": True,
        "jetton": _format_jetton(jetton),
        "market_stats": _format_market_stats(jetton.get("market_stats", {})),
    }


def get_price_chart(
    address: str,
    from_time: str,
    to_time: str,
    currency: str = "usd",
) -> dict:
    """
    Get jetton price chart data.

    Args:
        address: Jetton master address
        from_time: Start timestamp (ISO datetime)
        to_time: End timestamp (ISO datetime)
        currency: Currency for price data (usd or ton)

    Returns:
        dict with price chart points
    """
    params = {
        "from": from_time,
        "to": to_time,
        "currency": currency,
    }

    result = tokens_api_request(f"/api/v3/jettons/{address}/price-chart", params=params)

    if not result["success"]:
        return result

    points = result["data"].get("points", [])

    return {
        "success": True,
        "address": address,
        "currency": currency,
        "points_count": len(points),
        "points": points,
        "from": from_time,
        "to": to_time,
    }


def get_jetton_holders(address: str) -> dict:
    """
    Get top 10 jetton holders.

    Args:
        address: Jetton master address

    Returns:
        dict with holders list
    """
    result = tokens_api_request(f"/api/v3/jettons/{address}/holders")

    if not result["success"]:
        return result

    holders = result["data"]

    return {
        "success": True,
        "address": address,
        "holders_count": len(holders),
        "holders": holders,
    }


def bulk_fetch_jettons(
    addresses: List[str],
    refresh_price: bool = True,
) -> dict:
    """
    Bulk fetch jettons by addresses (up to 100).

    Args:
        addresses: List of jetton master addresses
        refresh_price: Whether to refresh price data

    Returns:
        dict with jettons list
    """
    if len(addresses) > 100:
        return {
            "success": False,
            "error": "Maximum 100 addresses allowed per request",
        }

    params = {"refresh_price": str(refresh_price).lower()}

    result = tokens_api_request(
        "/api/v3/jettons/by-addresses",
        method="POST",
        params=params,
        json_data=addresses,
    )

    if not result["success"]:
        return result

    jettons = result["data"]

    return {
        "success": True,
        "count": len(jettons),
        "requested": len(addresses),
        "jettons": [_format_jetton(j) for j in jettons],
    }


# =============================================================================
# Accounts API
# =============================================================================


def get_account_jettons(wallet_address: str) -> dict:
    """
    Get all jettons owned by an account.

    Args:
        wallet_address: Owner wallet address

    Returns:
        dict with jetton balances
    """
    result = tokens_api_request(f"/api/v3/accounts/{wallet_address}/jettons")

    if not result["success"]:
        return result

    data = result["data"]
    items = data.get("items", [])

    balances = []
    for item in items:
        jetton = item.get("jetton", {})
        decimals = jetton.get("decimals", 9)
        raw_balance = item.get("balance", "0")

        try:
            balance_human = int(raw_balance) / (10**decimals)
        except (ValueError, TypeError):
            balance_human = 0

        balances.append(
            {
                "jetton_address": item.get("jetton_address"),
                "jetton_wallet": item.get("jetton_wallet"),
                "balance_raw": raw_balance,
                "balance": balance_human,
                "jetton": _format_jetton(jetton) if jetton else None,
            }
        )

    return {
        "success": True,
        "wallet_address": wallet_address,
        "count": len(balances),
        "balances": balances,
    }


# =============================================================================
# Search API
# =============================================================================


def hybrid_search(
    search: Optional[str] = None,
    verification: Optional[List[str]] = None,
    kind: str = "DEXES",
    sort: Optional[str] = None,
    page: int = 1,
    size: int = 20,
) -> dict:
    """
    Advanced hybrid search with memepad support.

    Args:
        search: Search query
        verification: List of verification levels
        kind: Search kind (ALL, DEXES, MEMES_ALL, MEMES_DEXES, MEMES_MEMEPADS)
        sort: Sort by (FDMC, TVL, MCAP, VOLUME_24H, PRICE_CHANGE_24H)
        page: Page number
        size: Results per page (max 100)

    Returns:
        dict with search results
    """
    params = {
        "page": page,
        "size": min(size, 100),
        "kind": kind,
    }

    if search:
        params["search"] = search
    if verification:
        params["verification"] = ",".join(verification)
    if sort:
        params["sort"] = sort

    result = tokens_api_request("/api/v3/hybrid-search", params=params)

    if not result["success"]:
        return result

    jettons = result["data"]

    return {
        "success": True,
        "count": len(jettons),
        "page": page,
        "size": size,
        "kind": kind,
        "sort": sort,
        "jettons": [_format_poly_jetton(j) for j in jettons],
    }


# =============================================================================
# Labels API
# =============================================================================


def get_labels() -> dict:
    """
    Get all available labels.

    Returns:
        dict with labels list
    """
    result = tokens_api_request("/api/v3/labels")

    if not result["success"]:
        return result

    labels = result["data"]

    return {
        "success": True,
        "count": len(labels),
        "labels": labels,
    }


# =============================================================================
# Helpers
# =============================================================================


def _format_jetton(jetton: dict) -> dict:
    """Format jetton data for output."""
    return {
        "address": jetton.get("address"),
        "name": jetton.get("name"),
        "symbol": jetton.get("symbol"),
        "decimals": jetton.get("decimals"),
        "verification": jetton.get("verification"),
        "image_url": jetton.get("image_url"),
        "total_supply": jetton.get("total_supply"),
        "mintable": jetton.get("mintable"),
        "created_at": jetton.get("created_at"),
        "labels": jetton.get("labels", []),
    }


def _format_market_stats(stats: dict) -> dict:
    """Format market stats for output."""
    if not stats:
        return {}

    return {
        "price_usd": stats.get("price_usd"),
        "price_change_5m": stats.get("price_change_5m"),
        "price_change_1h": stats.get("price_change_1h"),
        "price_change_6h": stats.get("price_change_6h"),
        "price_change_24h": stats.get("price_change_24h"),
        "price_change_7d": stats.get("price_change_7d"),
        "volume_usd_24h": stats.get("volume_usd_24h"),
        "tvl_usd": stats.get("tvl_usd"),
        "fdmc": stats.get("fdmc"),
        "mcap": stats.get("mcap"),
        "holders_count": stats.get("holders_count"),
        "trust_score": stats.get("trust_score"),
        # Formatted versions
        "formatted": {
            "price": _format_price(stats.get("price_usd")),
            "volume_24h": _format_large_number(stats.get("volume_usd_24h")),
            "tvl": _format_large_number(stats.get("tvl_usd")),
            "mcap": _format_large_number(stats.get("mcap")),
            "fdmc": _format_large_number(stats.get("fdmc")),
        },
    }


def _format_poly_jetton(jetton: dict) -> dict:
    """Format poly jetton (common or memepad) for output."""
    # Check if it's a memepad jetton
    if "protocol" in jetton:
        # Memepad jetton
        return {
            "type": "memepad",
            "address": jetton.get("address"),
            "name": jetton.get("name"),
            "symbol": jetton.get("symbol"),
            "decimals": jetton.get("decimals"),
            "protocol": jetton.get("protocol"),
            "image_url": jetton.get("image_url"),
            "created_at": jetton.get("created_at"),
            "market_stats": _format_memepad_stats(jetton.get("market_stats", {})),
        }
    else:
        # Common jetton
        formatted = _format_jetton(jetton)
        formatted["type"] = "common"
        formatted["market_stats"] = _format_market_stats(jetton.get("market_stats", {}))
        return formatted


def _format_memepad_stats(stats: dict) -> dict:
    """Format memepad market stats."""
    if not stats:
        return {}

    return {
        "price_usd": stats.get("price_usd"),
        "tvl_usd": stats.get("tvl_usd"),
        "fdmc_usd": stats.get("fdmc_usd"),
        "collected_ton": stats.get("collected_ton"),
        "max_ton": stats.get("max_ton"),
        "progress": stats.get("progress"),
    }


def _format_price(price: Optional[float]) -> str:
    """Format price for display. Delegates to common.format_price."""
    return format_price(price)


def _format_large_number(num: Optional[float]) -> str:
    """Format large number (1.5M, 2.3B, etc.). Delegates to common.format_large_number."""
    return format_large_number(num)


# =============================================================================
# Token Resolution (for swap.py integration)
# =============================================================================


def resolve_token_by_symbol(symbol: str) -> Optional[dict]:
    """
    Resolve token by symbol using Tokens API.

    Args:
        symbol: Token symbol (e.g., "USDT", "NOT")

    Returns:
        dict with token info or None if not found
    """
    result = list_jettons(search=symbol, verification=["WHITELISTED"], size=10)

    if not result["success"]:
        return None

    jettons = result.get("jettons", [])

    # Find exact match by symbol
    for j in jettons:
        if j.get("symbol", "").upper() == symbol.upper():
            return j

    # Return first result if no exact match
    return jettons[0] if jettons else None


def get_token_market_data(address: str) -> dict:
    """
    Get token market data for analytics.

    Args:
        address: Jetton master address

    Returns:
        dict with market data (price, volume, mcap, trust_score)
    """
    result = get_jetton_info(address)

    if not result["success"]:
        return result

    stats = result.get("market_stats", {})
    jetton = result.get("jetton", {})

    return {
        "success": True,
        "address": address,
        "symbol": jetton.get("symbol"),
        "name": jetton.get("name"),
        "price_usd": stats.get("price_usd"),
        "price_change_24h": stats.get("price_change_24h"),
        "volume_usd_24h": stats.get("volume_usd_24h"),
        "tvl_usd": stats.get("tvl_usd"),
        "mcap": stats.get("mcap"),
        "fdmc": stats.get("fdmc"),
        "holders_count": stats.get("holders_count"),
        "trust_score": stats.get("trust_score"),
        "verification": jetton.get("verification"),
    }


# =============================================================================
# CLI
# =============================================================================


def main():
    parser = argparse.ArgumentParser(
        description="swap.coffee Tokens API CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # List jettons
  %(prog)s list --search USDT --size 10
  %(prog)s list --verification WHITELISTED,COMMUNITY
  
  # Get jetton info with market stats
  %(prog)s info EQCxE6mUtQJKFnGfaROTKOt1lZbDiiX1kCixRv7Nw2Id_sDs
  
  # Price chart (last 24h)
  %(prog)s price-chart EQCxE6mUtQJKFnGfaROTKOt1lZbDiiX1kCixRv7Nw2Id_sDs
  
  # Top holders
  %(prog)s holders EQCxE6mUtQJKFnGfaROTKOt1lZbDiiX1kCixRv7Nw2Id_sDs
  
  # Hybrid search (memepad support)
  %(prog)s search --query pepe --kind MEMES_ALL
  %(prog)s search --query NOT --sort VOLUME_24H
  
  # Account balances
  %(prog)s balances UQBvW8Z5huBkMJYdnfAEM5JqTNkgxvhw...
  
  # Bulk fetch
  %(prog)s bulk EQCxE6... EQBlqs... EQAvlW...
  
  # Labels
  %(prog)s labels

Verification levels: WHITELISTED, COMMUNITY, UNKNOWN, BLACKLISTED
Search kinds: ALL, DEXES, MEMES_ALL, MEMES_DEXES, MEMES_MEMEPADS
Sort options: FDMC, TVL, MCAP, VOLUME_24H, PRICE_CHANGE_24H
""",
    )

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # --- list ---
    list_p = subparsers.add_parser("list", help="List jettons")
    list_p.add_argument("--search", "-s", help="Search query")
    list_p.add_argument(
        "--verification",
        "-v",
        help="Verification levels (comma-separated: WHITELISTED,COMMUNITY)",
    )
    list_p.add_argument("--label-id", type=int, help="Filter by label ID")
    list_p.add_argument("--page", type=int, default=1, help="Page number")
    list_p.add_argument(
        "--size", type=int, default=20, help="Results per page (max 100)"
    )

    # --- info ---
    info_p = subparsers.add_parser("info", help="Get jetton info with market stats")
    info_p.add_argument("address", help="Jetton master address")
    info_p.add_argument("--no-refresh", action="store_true", help="Don't refresh price")

    # --- price-chart ---
    chart_p = subparsers.add_parser("price-chart", help="Get price chart")
    chart_p.add_argument("address", help="Jetton master address")
    chart_p.add_argument("--from", dest="from_time", help="Start time (ISO datetime)")
    chart_p.add_argument("--to", dest="to_time", help="End time (ISO datetime)")
    chart_p.add_argument(
        "--currency", "-c", default="usd", choices=["usd", "ton"], help="Price currency"
    )
    chart_p.add_argument(
        "--hours", type=int, default=24, help="Hours back from now (default: 24)"
    )

    # --- holders ---
    holders_p = subparsers.add_parser("holders", help="Get top 10 holders")
    holders_p.add_argument("address", help="Jetton master address")

    # --- search ---
    search_p = subparsers.add_parser(
        "search", help="Hybrid search with memepad support"
    )
    search_p.add_argument("--query", "-q", help="Search query")
    search_p.add_argument(
        "--kind",
        "-k",
        default="DEXES",
        choices=SEARCH_KINDS,
        help="Search kind",
    )
    search_p.add_argument("--sort", choices=SORT_OPTIONS, help="Sort by")
    search_p.add_argument(
        "--verification",
        "-v",
        help="Verification levels (comma-separated)",
    )
    search_p.add_argument("--page", type=int, default=1, help="Page number")
    search_p.add_argument("--size", type=int, default=20, help="Results per page")

    # --- balances ---
    balances_p = subparsers.add_parser("balances", help="Get account jetton balances")
    balances_p.add_argument("wallet_address", help="Wallet address")

    # --- bulk ---
    bulk_p = subparsers.add_parser("bulk", help="Bulk fetch jettons by addresses")
    bulk_p.add_argument("addresses", nargs="+", help="Jetton addresses (up to 100)")
    bulk_p.add_argument(
        "--no-refresh", action="store_true", help="Don't refresh prices"
    )

    # --- labels ---
    subparsers.add_parser("labels", help="List all labels")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    try:
        if args.command == "list":
            verification = None
            if args.verification:
                verification = [v.strip().upper() for v in args.verification.split(",")]

            result = list_jettons(
                search=args.search,
                verification=verification,
                label_id=args.label_id,
                page=args.page,
                size=args.size,
            )

        elif args.command == "info":
            result = get_jetton_info(
                address=args.address,
                refresh_price=not args.no_refresh,
            )

        elif args.command == "price-chart":
            # Calculate time range
            if args.from_time and args.to_time:
                from_time = args.from_time
                to_time = args.to_time
            else:
                from datetime import timedelta

                now = datetime.now(timezone.utc)
                to_time = now.isoformat()
                from_time = (now - timedelta(hours=args.hours)).isoformat()

            result = get_price_chart(
                address=args.address,
                from_time=from_time,
                to_time=to_time,
                currency=args.currency,
            )

        elif args.command == "holders":
            result = get_jetton_holders(args.address)

        elif args.command == "search":
            verification = None
            if args.verification:
                verification = [v.strip().upper() for v in args.verification.split(",")]

            result = hybrid_search(
                search=args.query,
                verification=verification,
                kind=args.kind,
                sort=args.sort,
                page=args.page,
                size=args.size,
            )

        elif args.command == "balances":
            result = get_account_jettons(args.wallet_address)

        elif args.command == "bulk":
            result = bulk_fetch_jettons(
                addresses=args.addresses,
                refresh_price=not args.no_refresh,
            )

        elif args.command == "labels":
            result = get_labels()

        else:
            result = {"error": f"Unknown command: {args.command}"}

        print(json.dumps(result, indent=2, ensure_ascii=False))

        if not result.get("success", True):
            return sys.exit(1)

    except Exception as e:
        print(json.dumps({"error": str(e)}, indent=2))
        return sys.exit(1)


if __name__ == "__main__":
    main()
