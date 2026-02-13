#!/usr/bin/env python3
"""
OpenClaw TON Skill — DEX Statistics, Contests, and Profile via swap.coffee API

Available Features:
- Statistics: General DEX stats, volumes, top tokens
- Contests: Active contests, leaderboards
- Profile: History, settings, TON proof validation

API Base: https://backend.swap.coffee/v1

Profile Endpoints (from official SDK):
- GET  /v1/profile/{address}/transactions  — Historical transactions
- POST /v1/profile/{address}/proof         — Validate TON proof
- GET  /v1/profile/{address}/settings      — Get user settings
- POST /v1/profile/{address}/settings      — Update user settings
"""

import os
import sys
import json
import argparse
from pathlib import Path
from typing import Optional

# Local import
script_dir = Path(__file__).parent
sys.path.insert(0, str(script_dir))

from utils import api_request, load_config, is_valid_address  # noqa: E402


# =============================================================================
# Constants
# =============================================================================

SWAP_COFFEE_API = "https://backend.swap.coffee"


# =============================================================================
# API Helper
# =============================================================================


def get_swap_coffee_key() -> Optional[str]:
    """Get swap.coffee API key from config."""
    config = load_config()
    return config.get("swap_coffee_key") or os.environ.get("SWAP_COFFEE_KEY")


def swap_coffee_request(
    endpoint: str,
    method: str = "GET",
    params: Optional[dict] = None,
    json_data: Optional[dict] = None,
    version: str = "v1",
) -> dict:
    """Make request to swap.coffee API."""
    base_url = f"{SWAP_COFFEE_API}/{version}"
    api_key = get_swap_coffee_key()

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["X-Api-Key"] = api_key

    return api_request(
        url=f"{base_url}{endpoint}",
        method=method,
        headers=headers,
        params=params,
        json_data=json_data,
    )


def _make_url_safe(address: str) -> str:
    """Convert address to URL-safe format."""
    return address.replace("+", "-").replace("/", "_")


# =============================================================================
# Statistics API
# =============================================================================


def get_dex_statistics() -> dict:
    """
    Get general DEX statistics.

    GET /v1/statistics

    Returns:
        dict with DEX statistics
    """
    result = swap_coffee_request("/statistics")

    if result["success"]:
        return {
            "success": True,
            "statistics": result["data"],
        }

    return {
        "success": False,
        "error": result.get("error", "Failed to get DEX statistics"),
        "status_code": result.get("status_code"),
    }


def get_statistics_volume(period: str = "24h") -> dict:
    """
    Get volume statistics.

    GET /v1/statistics/volume

    Args:
        period: Period (24h, 7d, 30d)

    Returns:
        dict with volume statistics
    """
    params = {"period": period}
    result = swap_coffee_request("/statistics/volume", params=params)

    if result["success"]:
        return {
            "success": True,
            "period": period,
            "volume": result["data"],
        }

    return {
        "success": False,
        "error": result.get("error", "Failed to get volume statistics"),
        "status_code": result.get("status_code"),
    }


def get_statistics_tokens(
    sort_by: str = "volume",
    limit: int = 20,
) -> dict:
    """
    Get top tokens by volume/liquidity.

    GET /v1/statistics/tokens

    Args:
        sort_by: Sort by (volume, liquidity, txs)
        limit: Number of tokens

    Returns:
        dict with top tokens
    """
    params = {
        "sort_by": sort_by,
        "limit": min(limit, 100),
    }

    result = swap_coffee_request("/statistics/tokens", params=params)

    if result["success"]:
        return {
            "success": True,
            "sort_by": sort_by,
            "tokens": result["data"],
        }

    return {
        "success": False,
        "error": result.get("error", "Failed to get token statistics"),
        "status_code": result.get("status_code"),
    }


# =============================================================================
# Contests API
# =============================================================================


def get_active_contests() -> dict:
    """
    Get list of active contests.

    GET /v1/contests/active

    Returns:
        dict with active contests
    """
    result = swap_coffee_request("/contests/active")

    if result["success"]:
        contests = result["data"]
        return {
            "success": True,
            "contests_count": len(contests) if isinstance(contests, list) else 1,
            "contests": contests,
        }

    return {
        "success": False,
        "error": result.get("error", "Failed to get active contests"),
        "status_code": result.get("status_code"),
    }


def get_contest_info(contest_id: str) -> dict:
    """
    Get contest information.

    GET /v1/contests/{contest_id}

    Args:
        contest_id: Contest ID

    Returns:
        dict with contest info
    """
    result = swap_coffee_request(f"/contests/{contest_id}")

    if result["success"]:
        return {
            "success": True,
            "contest_id": contest_id,
            "contest": result["data"],
        }

    return {
        "success": False,
        "error": result.get("error", "Failed to get contest info"),
        "status_code": result.get("status_code"),
    }


def get_contest_leaderboard(
    contest_id: str,
    page: int = 1,
    size: int = 50,
) -> dict:
    """
    Get contest leaderboard.

    GET /v1/contests/{contest_id}/leaderboard

    Args:
        contest_id: Contest ID
        page: Page number
        size: Results per page

    Returns:
        dict with leaderboard
    """
    params = {
        "page": page,
        "size": min(size, 100),
    }

    result = swap_coffee_request(f"/contests/{contest_id}/leaderboard", params=params)

    if result["success"]:
        data = result["data"]
        return {
            "success": True,
            "contest_id": contest_id,
            "page": page,
            "leaderboard": data.get("leaderboard", data)
            if isinstance(data, dict)
            else data,
            "total_count": data.get("total_count") if isinstance(data, dict) else None,
        }

    return {
        "success": False,
        "error": result.get("error", "Failed to get contest leaderboard"),
        "status_code": result.get("status_code"),
    }


def get_contest_user_position(
    contest_id: str,
    wallet_address: str,
) -> dict:
    """
    Get user position in contest.

    GET /v1/contests/{contest_id}/user

    Args:
        contest_id: Contest ID
        wallet_address: User wallet address

    Returns:
        dict with user position
    """
    if not is_valid_address(wallet_address):
        return {"success": False, "error": f"Invalid wallet address: {wallet_address}"}

    params = {"wallet_address": wallet_address}
    result = swap_coffee_request(f"/contests/{contest_id}/user", params=params)

    if result["success"]:
        return {
            "success": True,
            "contest_id": contest_id,
            "wallet": wallet_address,
            "position": result["data"],
        }

    return {
        "success": False,
        "error": result.get("error", "Failed to get user contest position"),
        "status_code": result.get("status_code"),
    }


def get_all_contests(
    include_finished: bool = False,
    page: int = 1,
    size: int = 20,
) -> dict:
    """
    Get list of all contests.

    GET /v1/contests

    Args:
        include_finished: Include finished contests
        page: Page number
        size: Results per page

    Returns:
        dict with contests
    """
    params = {
        "include_finished": include_finished,
        "page": page,
        "size": min(size, 100),
    }

    result = swap_coffee_request("/contests", params=params)

    if result["success"]:
        data = result["data"]
        contests = data.get("contests", data) if isinstance(data, dict) else data
        return {
            "success": True,
            "page": page,
            "contests_count": len(contests) if isinstance(contests, list) else 1,
            "contests": contests,
            "total_count": data.get("total_count") if isinstance(data, dict) else None,
        }

    return {
        "success": False,
        "error": result.get("error", "Failed to get contests"),
        "status_code": result.get("status_code"),
    }


# =============================================================================
# Profile API
# =============================================================================


def get_profile_history(
    wallet_address: str,
    xverify: Optional[str] = None,
    page: int = 1,
    size: int = 50,
) -> dict:
    """
    Get historical transactions for wallet.

    GET /v1/profile/{address}/transactions

    Args:
        wallet_address: User wallet address
        xverify: x-verify header (TonConnect proof)
        page: Page number
        size: Results per page

    Returns:
        dict with transaction history
    """
    if not is_valid_address(wallet_address):
        return {"success": False, "error": f"Invalid wallet address: {wallet_address}"}

    addr_safe = _make_url_safe(wallet_address)

    params = {
        "page": page,
        "size": min(size, 100),
    }

    headers = {"Content-Type": "application/json"}
    if xverify:
        headers["x-verify"] = xverify

    api_key = get_swap_coffee_key()
    if api_key:
        headers["X-Api-Key"] = api_key

    result = api_request(
        url=f"{SWAP_COFFEE_API}/v1/profile/{addr_safe}/transactions",
        method="GET",
        headers=headers,
        params=params,
    )

    if result["success"]:
        data = result["data"]
        history = data.get("history", data) if isinstance(data, dict) else data
        return {
            "success": True,
            "wallet": wallet_address,
            "page": page,
            "history": history,
            "total_count": data.get("total_count") if isinstance(data, dict) else None,
        }

    return {
        "success": False,
        "error": result.get("error", "Failed to get profile history"),
        "status_code": result.get("status_code"),
    }


def validate_ton_proof(
    address: str,
    proof: dict,
) -> dict:
    """
    Validate TON proof for wallet ownership.

    POST /v1/profile/{address}/proof

    Args:
        address: Wallet address
        proof: TON proof object

    Returns:
        dict with validation result
    """
    addr_safe = _make_url_safe(address)

    result = swap_coffee_request(
        f"/profile/{addr_safe}/proof",
        method="POST",
        json_data=proof,
    )

    if result["success"]:
        return {
            "success": True,
            "address": address,
            "valid": result["data"].get("valid", True)
            if isinstance(result["data"], dict)
            else True,
            "data": result["data"],
        }

    return {
        "success": False,
        "error": result.get("error", "Failed to validate TON proof"),
        "status_code": result.get("status_code"),
    }


def get_profile_settings(
    wallet_address: str,
    xverify: Optional[str] = None,
) -> dict:
    """
    Get user settings.

    GET /v1/profile/{address}/settings

    Args:
        wallet_address: User wallet address
        xverify: x-verify header (TonConnect proof)

    Returns:
        dict with user settings
    """
    if not is_valid_address(wallet_address):
        return {"success": False, "error": f"Invalid wallet address: {wallet_address}"}

    addr_safe = _make_url_safe(wallet_address)

    headers = {"Content-Type": "application/json"}
    if xverify:
        headers["x-verify"] = xverify

    api_key = get_swap_coffee_key()
    if api_key:
        headers["X-Api-Key"] = api_key

    result = api_request(
        url=f"{SWAP_COFFEE_API}/v1/profile/{addr_safe}/settings",
        method="GET",
        headers=headers,
    )

    if result["success"]:
        return {
            "success": True,
            "wallet": wallet_address,
            "settings": result["data"],
        }

    return {
        "success": False,
        "error": result.get("error", "Failed to get profile settings"),
        "status_code": result.get("status_code"),
    }


def update_profile_settings(
    wallet_address: str,
    settings: dict,
    xverify: str,
) -> dict:
    """
    Update user settings.

    POST /v1/profile/{address}/settings

    Args:
        wallet_address: User wallet address
        settings: Settings to update
        xverify: x-verify header (required)

    Returns:
        dict with updated settings
    """
    if not is_valid_address(wallet_address):
        return {"success": False, "error": f"Invalid wallet address: {wallet_address}"}

    addr_safe = _make_url_safe(wallet_address)

    headers = {
        "Content-Type": "application/json",
        "x-verify": xverify,
    }

    api_key = get_swap_coffee_key()
    if api_key:
        headers["X-Api-Key"] = api_key

    result = api_request(
        url=f"{SWAP_COFFEE_API}/v1/profile/{addr_safe}/settings",
        method="POST",
        headers=headers,
        json_data=settings,
    )

    if result["success"]:
        return {
            "success": True,
            "wallet": wallet_address,
            "settings": result["data"],
            "message": "Settings updated successfully",
        }

    return {
        "success": False,
        "error": result.get("error", "Failed to update profile settings"),
        "status_code": result.get("status_code"),
    }


# =============================================================================
# CLI
# =============================================================================


def main():
    parser = argparse.ArgumentParser(
        description="DEX Statistics & Contests via swap.coffee API",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Statistics
  %(prog)s stats
  %(prog)s stats-volume --period 7d
  %(prog)s stats-tokens --sort volume --limit 10
  
  # Contests
  %(prog)s contests-active
  %(prog)s contests --include-finished
  %(prog)s contest --id contest123
  %(prog)s contest-leaderboard --id contest123 --size 20
  %(prog)s contest-position --id contest123 --wallet UQBvW8...
  
  # Profile
  %(prog)s profile-history --wallet UQBvW8...
  %(prog)s profile-settings --wallet UQBvW8...

API Categories:
  Statistics:  DEX stats, volumes, top tokens
  Contests:    Active contests, leaderboards
  Profile:     Transaction history, settings
""",
    )

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # --- Statistics ---
    subparsers.add_parser("stats", help="Get DEX statistics")

    stv_p = subparsers.add_parser("stats-volume", help="Get volume statistics")
    stv_p.add_argument("--period", "-p", default="24h", choices=["24h", "7d", "30d"])

    stt_p = subparsers.add_parser("stats-tokens", help="Get top tokens")
    stt_p.add_argument(
        "--sort", "-s", default="volume", choices=["volume", "liquidity", "txs"]
    )
    stt_p.add_argument("--limit", "-l", type=int, default=20, help="Number of tokens")

    # --- Contests ---
    subparsers.add_parser("contests-active", help="Get active contests")

    cal_p = subparsers.add_parser("contests", help="Get all contests")
    cal_p.add_argument(
        "--include-finished", action="store_true", help="Include finished"
    )
    cal_p.add_argument("--page", "-p", type=int, default=1, help="Page number")
    cal_p.add_argument("--size", "-s", type=int, default=20, help="Results per page")

    co_p = subparsers.add_parser("contest", help="Get contest info")
    co_p.add_argument("--id", "-i", required=True, help="Contest ID")

    col_p = subparsers.add_parser("contest-leaderboard", help="Get contest leaderboard")
    col_p.add_argument("--id", "-i", required=True, help="Contest ID")
    col_p.add_argument("--page", "-p", type=int, default=1, help="Page number")
    col_p.add_argument("--size", "-s", type=int, default=50, help="Results per page")

    cop_p = subparsers.add_parser("contest-position", help="Get user contest position")
    cop_p.add_argument("--id", "-i", required=True, help="Contest ID")
    cop_p.add_argument("--wallet", "-w", required=True, help="Wallet address")

    # --- Profile ---
    ph_p = subparsers.add_parser("profile-history", help="Get transaction history")
    ph_p.add_argument("--wallet", "-w", required=True, help="Wallet address")
    ph_p.add_argument("--page", "-p", type=int, default=1, help="Page number")
    ph_p.add_argument("--size", "-s", type=int, default=50, help="Results per page")

    ps_p = subparsers.add_parser("profile-settings", help="Get profile settings")
    ps_p.add_argument("--wallet", "-w", required=True, help="Wallet address")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    try:
        # Statistics
        if args.command == "stats":
            result = get_dex_statistics()
        elif args.command == "stats-volume":
            result = get_statistics_volume(period=args.period)
        elif args.command == "stats-tokens":
            result = get_statistics_tokens(sort_by=args.sort, limit=args.limit)

        # Contests
        elif args.command == "contests-active":
            result = get_active_contests()
        elif args.command == "contests":
            result = get_all_contests(
                include_finished=getattr(args, "include_finished", False),
                page=args.page,
                size=args.size,
            )
        elif args.command == "contest":
            result = get_contest_info(contest_id=args.id)
        elif args.command == "contest-leaderboard":
            result = get_contest_leaderboard(
                contest_id=args.id,
                page=args.page,
                size=args.size,
            )
        elif args.command == "contest-position":
            result = get_contest_user_position(
                contest_id=args.id,
                wallet_address=args.wallet,
            )

        # Profile
        elif args.command == "profile-history":
            result = get_profile_history(
                wallet_address=args.wallet,
                page=args.page,
                size=args.size,
            )
        elif args.command == "profile-settings":
            result = get_profile_settings(wallet_address=args.wallet)

        else:
            result = {"success": False, "error": f"Unknown command: {args.command}"}

        print(json.dumps(result, indent=2, ensure_ascii=False))

        if not result.get("success", True):
            return sys.exit(1)

    except Exception as e:
        print(json.dumps({"success": False, "error": str(e)}, indent=2))
        return sys.exit(1)


if __name__ == "__main__":
    main()
