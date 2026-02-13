#!/usr/bin/env python3
"""
OpenClaw TON Skill — DYOR.io API Wrapper

Обёртка для DYOR.io TON Analytics API:
- Информация о токене (цена, маркеткап, объём, ликвидность)
- Рейтинг доверия / скам-скор
- История цены
- DEX пулы токена
- История свапов

Документация: https://docs.dyor.io/technical-guides/introduction
Swagger: https://dyor.io/tonapi/swagger
"""

import os
import sys
import json
import argparse
from pathlib import Path
from typing import Optional, List

# Локальный импорт
script_dir = Path(__file__).parent
sys.path.insert(0, str(script_dir))

from utils import (  # noqa: E402
    api_request,
    load_config,
    save_config,
    is_valid_address,
    tonapi_request,
)
from common import (  # noqa: E402
    KNOWN_TOKENS,
    DYOR_API_BASE_URL,
)


# =============================================================================
# Constants
# =============================================================================

DYOR_API_BASE = DYOR_API_BASE_URL


# =============================================================================
# DYOR API Client
# =============================================================================


def get_dyor_api_key() -> Optional[str]:
    """Получает DYOR API key из конфига."""
    config = load_config()
    return config.get("dyor_key") or os.environ.get("DYOR_API_KEY")


def dyor_request(
    endpoint: str,
    method: str = "GET",
    params: Optional[dict] = None,
    json_data: Optional[dict] = None,
) -> dict:
    """
    Запрос к DYOR API.

    Args:
        endpoint: API endpoint (например "/jetton/info")
        method: HTTP метод
        params: Query параметры
        json_data: JSON body

    Returns:
        dict с результатом
    """
    api_key = get_dyor_api_key()

    headers = {"Accept": "application/json", "Content-Type": "application/json"}

    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    url = f"{DYOR_API_BASE}{endpoint}"

    return api_request(
        url=url,
        method=method,
        headers=headers,
        params=params,
        json_data=json_data,
        timeout=30,
    )


def resolve_token_address(token: str) -> str:
    """
    Резолвит токен (символ или адрес) в адрес мастер-контракта.

    Args:
        token: Символ токена (TON, USDT) или адрес

    Returns:
        Адрес jetton master или "native" для TON
    """
    token_upper = token.upper()

    # Проверяем известные токены
    if token_upper in KNOWN_TOKENS:
        return KNOWN_TOKENS[token_upper]

    # Если похоже на адрес — возвращаем как есть
    if is_valid_address(token) or ":" in token:
        return token

    return token


# =============================================================================
# Token Information
# =============================================================================


def get_token_info_dyor(token_address: str) -> dict:
    """
    Получает информацию о токене через DYOR API.

    Returns:
        dict с информацией о токене (цена, mcap, volume, liquidity и т.д.)
    """
    result = dyor_request(f"/jetton/{token_address}")

    if not result["success"]:
        return result

    data = result["data"]

    # Нормализуем ответ
    return {
        "success": True,
        "source": "dyor",
        "address": token_address,
        "name": data.get("name"),
        "symbol": data.get("symbol"),
        "decimals": data.get("decimals", 9),
        "image": data.get("image"),
        "description": data.get("description"),
        "price_usd": data.get("price"),
        "price_change_24h": data.get("price_change_24h"),
        "market_cap": data.get("market_cap"),
        "fully_diluted_mcap": data.get("fdv"),
        "volume_24h": data.get("volume_24h"),
        "liquidity": data.get("liquidity"),
        "total_supply": data.get("total_supply"),
        "circulating_supply": data.get("circulating_supply"),
        "holders_count": data.get("holders"),
        "created_at": data.get("created_at"),
        "raw_data": data,
    }


def get_token_rates_tonapi(token_address: str) -> dict:
    """
    Получает курс токена через TonAPI /rates endpoint.

    Args:
        token_address: Адрес токена или "TON" для нативного токена

    Returns:
        dict с ценой и изменениями
    """
    # TonAPI /rates принимает адреса токенов
    # Для TON используем специальный адрес
    if token_address == "native":
        token_param = "TON"
    else:
        token_param = token_address

    result = tonapi_request(
        "/rates", params={"tokens": token_param, "currencies": "usd"}
    )

    if not result["success"]:
        return {"success": False, "error": result.get("error")}

    data = result["data"]
    rates = data.get("rates", {})

    # TonAPI возвращает rates по адресу токена
    token_rates = rates.get(token_param) or rates.get(token_address) or {}

    if not token_rates:
        return {"success": False, "error": "No rates found for token"}

    prices = token_rates.get("prices", {})
    diff_24h = token_rates.get("diff_24h", {})
    diff_7d = token_rates.get("diff_7d", {})
    diff_30d = token_rates.get("diff_30d", {})

    # Парсим процент изменения (приходит как "+4.63%" или "-2.10%")
    def parse_diff(diff_str):
        if not diff_str:
            return None
        try:
            return float(diff_str.replace("%", "").replace("+", ""))
        except Exception:
            return None

    return {
        "success": True,
        "price_usd": prices.get("USD"),
        "price_change_24h": parse_diff(diff_24h.get("USD")),
        "price_change_7d": parse_diff(diff_7d.get("USD")),
        "price_change_30d": parse_diff(diff_30d.get("USD")),
    }


def get_token_info_tonapi(token_address: str) -> dict:
    """
    Получает информацию о токене через TonAPI (fallback).
    Включает цены из /rates endpoint.

    Returns:
        dict с базовой информацией о токене
    """
    # Получаем цены отдельно через /rates
    rates = get_token_rates_tonapi(token_address)
    price_usd = rates.get("price_usd") if rates.get("success") else None
    price_change_24h = rates.get("price_change_24h") if rates.get("success") else None

    if token_address == "native":
        # Для TON возвращаем захардкоженные данные + цены
        return {
            "success": True,
            "source": "tonapi",
            "address": "native",
            "name": "Toncoin",
            "symbol": "TON",
            "decimals": 9,
            "image": "https://ton.org/download/ton_symbol.png",
            "price_usd": price_usd,
            "price_change_24h": price_change_24h,
        }

    result = tonapi_request(f"/jettons/{token_address}")

    if not result["success"]:
        return result

    data = result["data"]
    metadata = data.get("metadata", {})

    return {
        "success": True,
        "source": "tonapi",
        "address": token_address,
        "name": metadata.get("name"),
        "symbol": metadata.get("symbol"),
        "decimals": int(metadata.get("decimals", 9)),
        "image": metadata.get("image"),
        "description": metadata.get("description"),
        "price_usd": price_usd,
        "price_change_24h": price_change_24h,
        "total_supply": data.get("total_supply"),
        "holders_count": data.get("holders_count"),
        "verification": data.get("verification"),
        "mintable": data.get("mintable"),
        "social": metadata.get("social", []),
        "websites": metadata.get("websites", []),
        "raw_data": data,
    }


def get_token_info(token: str, prefer_dyor: bool = True) -> dict:
    """
    Получает информацию о токене (DYOR + TonAPI fallback).

    Args:
        token: Символ токена или адрес
        prefer_dyor: Попробовать DYOR API сначала

    Returns:
        dict с информацией о токене
    """
    token_address = resolve_token_address(token)

    if prefer_dyor and get_dyor_api_key():
        result = get_token_info_dyor(token_address)
        if result["success"]:
            return result

    # Fallback на TonAPI
    return get_token_info_tonapi(token_address)


# =============================================================================
# Trust Score / Scam Detection
# =============================================================================


def get_trust_score(token: str) -> dict:
    """
    Получает рейтинг доверия / скам-скор токена.

    Args:
        token: Символ токена или адрес

    Returns:
        dict с trust score и деталями
    """
    token_address = resolve_token_address(token)

    # Пробуем DYOR API
    if get_dyor_api_key():
        result = dyor_request(f"/jetton/{token_address}/trust")

        if result["success"]:
            data = result["data"]
            return {
                "success": True,
                "source": "dyor",
                "address": token_address,
                "trust_score": data.get("score"),
                "trust_level": data.get("level"),  # high, medium, low, scam
                "flags": data.get("flags", []),
                "warnings": data.get("warnings", []),
                "details": data.get("details", {}),
                "raw_data": data,
            }

    # Fallback: используем TonAPI verification
    result = tonapi_request(f"/jettons/{token_address}")

    if not result["success"]:
        return result

    data = result["data"]
    verification = data.get("verification", "unknown")

    # Маппинг verification на trust level
    trust_map = {
        "whitelist": {"score": 90, "level": "high"},
        "none": {"score": 50, "level": "medium"},
        "blacklist": {"score": 10, "level": "scam"},
    }

    trust_info = trust_map.get(verification, {"score": 50, "level": "unknown"})

    return {
        "success": True,
        "source": "tonapi",
        "address": token_address,
        "trust_score": trust_info["score"],
        "trust_level": trust_info["level"],
        "verification": verification,
        "flags": [],
        "warnings": []
        if verification == "whitelist"
        else ["Limited trust data from TonAPI"],
        "raw_data": data,
    }


# =============================================================================
# Price History
# =============================================================================


def get_price_history(token: str, days: int = 7, interval: str = "1h") -> dict:
    """
    Получает историю цены токена.

    Args:
        token: Символ токена или адрес
        days: Количество дней истории
        interval: Интервал данных (1h, 4h, 1d)

    Returns:
        dict с историей цены
    """
    token_address = resolve_token_address(token)

    # Пробуем DYOR API
    if get_dyor_api_key():
        result = dyor_request(
            f"/jetton/{token_address}/history",
            params={"days": days, "interval": interval},
        )

        if result["success"]:
            data = result["data"]
            history = data if isinstance(data, list) else data.get("history", [])

            return {
                "success": True,
                "source": "dyor",
                "address": token_address,
                "days": days,
                "interval": interval,
                "data_points": len(history),
                "history": history,
                "price_change": _calculate_price_change(history),
                "raw_data": data,
            }

    # Fallback: TonAPI rates endpoint
    result = tonapi_request(
        "/rates/history",
        params={
            "token": token_address,
            "currency": "usd",
            "points_count": days
            * (24 if interval == "1h" else (6 if interval == "4h" else 1)),
        },
    )

    if not result["success"]:
        return {
            "success": False,
            "error": "Price history not available",
            "source": "fallback",
        }

    data = result["data"]
    points = data.get("points", [])

    history = [
        {"timestamp": p.get("timestamp"), "price": p.get("price")} for p in points
    ]

    return {
        "success": True,
        "source": "tonapi",
        "address": token_address,
        "days": days,
        "interval": interval,
        "data_points": len(history),
        "history": history,
        "price_change": _calculate_price_change(history),
    }


def _calculate_price_change(history: List[dict]) -> Optional[dict]:
    """Вычисляет изменение цены из истории."""
    if not history or len(history) < 2:
        return None

    first_price = history[0].get("price")
    last_price = history[-1].get("price")

    if not first_price or not last_price:
        return None

    first_price = float(first_price)
    last_price = float(last_price)

    if first_price == 0:
        return None

    change_abs = last_price - first_price
    change_pct = (change_abs / first_price) * 100

    return {
        "start_price": first_price,
        "end_price": last_price,
        "change_absolute": change_abs,
        "change_percent": round(change_pct, 2),
    }


# =============================================================================
# DEX Pools
# =============================================================================


def get_token_pools(token: str) -> dict:
    """
    Получает список DEX пулов для токена.

    Args:
        token: Символ токена или адрес

    Returns:
        dict с пулами
    """
    token_address = resolve_token_address(token)

    # Пробуем DYOR API
    if get_dyor_api_key():
        result = dyor_request(f"/jetton/{token_address}/pools")

        if result["success"]:
            data = result["data"]
            pools = data if isinstance(data, list) else data.get("pools", [])

            return {
                "success": True,
                "source": "dyor",
                "address": token_address,
                "pools_count": len(pools),
                "pools": pools,
                "raw_data": data,
            }

    # Fallback: нет публичного TonAPI endpoint для пулов
    return {
        "success": False,
        "error": "Pools data requires DYOR API key",
        "source": "fallback",
        "address": token_address,
    }


# =============================================================================
# Swap History
# =============================================================================


def get_swap_history(token: str, limit: int = 50) -> dict:
    """
    Получает историю свапов для токена.

    Args:
        token: Символ токена или адрес
        limit: Максимум записей

    Returns:
        dict с историей свапов
    """
    token_address = resolve_token_address(token)

    # Пробуем DYOR API
    if get_dyor_api_key():
        result = dyor_request(f"/jetton/{token_address}/swaps", params={"limit": limit})

        if result["success"]:
            data = result["data"]
            swaps = data if isinstance(data, list) else data.get("swaps", [])

            # Анализ
            buys = [s for s in swaps if s.get("type") == "buy"]
            sells = [s for s in swaps if s.get("type") == "sell"]

            return {
                "success": True,
                "source": "dyor",
                "address": token_address,
                "total_swaps": len(swaps),
                "buys_count": len(buys),
                "sells_count": len(sells),
                "buy_pressure": len(buys) / len(swaps) * 100 if swaps else 0,
                "swaps": swaps,
                "raw_data": data,
            }

    # Fallback: TonAPI jetton transfers (не совсем swaps, но близко)
    result = tonapi_request(
        f"/jettons/{token_address}/transfers", params={"limit": limit}
    )

    if not result["success"]:
        return {
            "success": False,
            "error": "Swap history requires DYOR API key",
            "source": "fallback",
            "address": token_address,
        }

    data = result["data"]
    transfers = data.get("transfers", [])

    return {
        "success": True,
        "source": "tonapi",
        "address": token_address,
        "note": "This is transfer history, not swap history",
        "total_transfers": len(transfers),
        "transfers": transfers,
    }


# =============================================================================
# Compare Tokens
# =============================================================================


def compare_tokens(tokens: List[str]) -> dict:
    """
    Сравнивает несколько токенов.

    Args:
        tokens: Список символов или адресов токенов

    Returns:
        dict со сравнительной таблицей
    """
    results = []

    for token in tokens:
        info = get_token_info(token)
        trust = get_trust_score(token)

        results.append(
            {
                "token": token,
                "address": info.get("address"),
                "symbol": info.get("symbol"),
                "name": info.get("name"),
                "price_usd": info.get("price_usd"),
                "market_cap": info.get("market_cap"),
                "volume_24h": info.get("volume_24h"),
                "liquidity": info.get("liquidity"),
                "holders": info.get("holders_count"),
                "trust_score": trust.get("trust_score"),
                "trust_level": trust.get("trust_level"),
                "verification": info.get("verification"),
                "success": info.get("success", False),
            }
        )

    # Сортировка по market cap
    results.sort(key=lambda x: x.get("market_cap") or 0, reverse=True)

    return {"success": True, "tokens_count": len(tokens), "comparison": results}


# =============================================================================
# CLI
# =============================================================================


def main():
    parser = argparse.ArgumentParser(
        description="DYOR.io API wrapper for TON token analytics",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Информация о токене
  %(prog)s info --token DUST
  %(prog)s info --token EQBlqsm144Dq6SjbPI4jjZvA1hqTIP3CvHovbIfW_t-SCALE
  
  # Trust score
  %(prog)s trust --token NOT
  
  # История цены
  %(prog)s history --token STON --days 7 --interval 1h
  
  # DEX пулы
  %(prog)s pools --token USDT
  
  # История свапов
  %(prog)s swaps --token DUST --limit 100
  
  # Сравнение токенов
  %(prog)s compare --tokens DUST NOT STON

Known tokens: TON, USDT, USDC, NOT, STON, DUST, GRAM
""",
    )

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # --- info ---
    info_p = subparsers.add_parser("info", help="Get token information")
    info_p.add_argument("--token", "-t", required=True, help="Token symbol or address")

    # --- trust ---
    trust_p = subparsers.add_parser("trust", help="Get trust score")
    trust_p.add_argument("--token", "-t", required=True, help="Token symbol or address")

    # --- history ---
    history_p = subparsers.add_parser("history", help="Get price history")
    history_p.add_argument(
        "--token", "-t", required=True, help="Token symbol or address"
    )
    history_p.add_argument(
        "--days", "-d", type=int, default=7, help="Number of days (default: 7)"
    )
    history_p.add_argument(
        "--interval",
        "-i",
        default="1h",
        choices=["1h", "4h", "1d"],
        help="Data interval",
    )

    # --- pools ---
    pools_p = subparsers.add_parser("pools", help="Get DEX pools for token")
    pools_p.add_argument("--token", "-t", required=True, help="Token symbol or address")

    # --- swaps ---
    swaps_p = subparsers.add_parser("swaps", help="Get swap history")
    swaps_p.add_argument("--token", "-t", required=True, help="Token symbol or address")
    swaps_p.add_argument(
        "--limit", "-l", type=int, default=50, help="Max results (default: 50)"
    )

    # --- compare ---
    compare_p = subparsers.add_parser("compare", help="Compare multiple tokens")
    compare_p.add_argument(
        "--tokens", "-t", required=True, help="Comma-separated tokens"
    )

    # --- config ---
    config_p = subparsers.add_parser("config", help="Configure DYOR API key")
    config_p.add_argument("--key", "-k", help="DYOR API key")
    config_p.add_argument("--show", action="store_true", help="Show current key status")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    try:
        if args.command == "info":
            result = get_token_info(args.token)

        elif args.command == "trust":
            result = get_trust_score(args.token)

        elif args.command == "history":
            result = get_price_history(args.token, args.days, args.interval)

        elif args.command == "pools":
            result = get_token_pools(args.token)

        elif args.command == "swaps":
            result = get_swap_history(args.token, args.limit)

        elif args.command == "compare":
            tokens = [t.strip() for t in args.tokens.split(",")]
            result = compare_tokens(tokens)

        elif args.command == "config":
            if args.show:
                api_key = get_dyor_api_key()
                result = {
                    "configured": bool(api_key),
                    "key_preview": f"{api_key[:8]}..."
                    if api_key and len(api_key) > 8
                    else None,
                }
            elif args.key:
                config = load_config()
                config["dyor_key"] = args.key
                save_config(config)
                result = {"success": True, "message": "DYOR API key saved"}
            else:
                result = {"error": "Use --key to set API key or --show to check status"}

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
