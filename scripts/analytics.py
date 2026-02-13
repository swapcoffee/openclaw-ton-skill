#!/usr/bin/env python3
"""
OpenClaw TON Skill — Token Analytics CLI

Аналитика токенов TON:
- Полная информация о токене
- Trust score / скам-детекция
- История цены
- DEX пулы
- Сравнение токенов

Использует DYOR API (если ключ настроен) + TonAPI как fallback.
"""

import sys
import json
import argparse
from pathlib import Path
from typing import Optional, List, Union
from datetime import datetime, UTC

# Локальный импорт
script_dir = Path(__file__).parent
sys.path.insert(0, str(script_dir))

from dyor import (  # noqa: E402
    get_token_info,
    get_trust_score,
    get_price_history,
    get_token_pools,
    resolve_token_address,
    get_dyor_api_key,
    KNOWN_TOKENS,
)
from tokens import get_token_market_data  # noqa: E402


# =============================================================================
# Enhanced Token Info
# =============================================================================


def get_full_token_info(token: str) -> dict:
    """
    Получает полную информацию о токене (агрегация из разных источников).

    Uses swap.coffee Tokens API as primary source for market data,
    with DYOR/TonAPI as fallback.

    Args:
        token: Символ токена или адрес

    Returns:
        dict с полной информацией
    """
    token_address = resolve_token_address(token)

    # Базовая информация
    info = get_token_info(token)

    # Trust score
    trust = get_trust_score(token)

    # Try swap.coffee Tokens API for better market stats
    tokens_api_data = {}
    try:
        tokens_result = get_token_market_data(token_address)
        if tokens_result.get("success"):
            tokens_api_data = tokens_result
    except Exception:
        pass

    holders_count: Union[int, None] = tokens_api_data.get("holders_count") or info.get(
        "holders_count"
    )
    liquidity: Union[int, float, None] = tokens_api_data.get("tvl_usd") or info.get(
        "liquidity"
    )
    price_usd: Union[float, None] = tokens_api_data.get("price_usd") or info.get(
        "price_usd"
    )
    market_cap: Union[int, float, None] = tokens_api_data.get("mcap") or info.get(
        "market_cap"
    )
    volume_24h: Union[int, float, None] = tokens_api_data.get(
        "volume_usd_24h"
    ) or info.get("volume_24h")

    # Объединяем (swap.coffee > DYOR > TonAPI)
    result = {
        "success": info.get("success", False) or bool(tokens_api_data),
        "token": token,
        "address": token_address,
        "sources": [
            s
            for s in [
                info.get("source"),
                trust.get("source"),
                "swap.coffee" if tokens_api_data else None,
            ]
            if s
        ],
        # Metadata
        "name": tokens_api_data.get("name") or info.get("name"),
        "symbol": tokens_api_data.get("symbol") or info.get("symbol"),
        "decimals": info.get("decimals"),
        "image": info.get("image"),
        "description": info.get("description"),
        # Market data (prefer swap.coffee)
        "price_usd": price_usd,
        "price_change_24h": tokens_api_data.get("price_change_24h")
        or info.get("price_change_24h"),
        "market_cap": market_cap,
        "fully_diluted_mcap": tokens_api_data.get("fdmc")
        or info.get("fully_diluted_mcap"),
        "volume_24h": volume_24h,
        "liquidity": liquidity,
        # Supply
        "total_supply": info.get("total_supply"),
        "circulating_supply": info.get("circulating_supply"),
        "holders_count": holders_count,
        "mintable": info.get("mintable"),
        # Trust (prefer swap.coffee trust_score)
        "trust_score": tokens_api_data.get("trust_score") or trust.get("trust_score"),
        "trust_level": trust.get("trust_level"),
        "verification": tokens_api_data.get("verification")
        or info.get("verification")
        or trust.get("verification"),
        "warnings": trust.get("warnings", []),
        "flags": trust.get("flags", []),
        # Links
        "social": info.get("social", []),
        "websites": info.get("websites", []),
        # Meta
        "created_at": info.get("created_at"),
        "fetched_at": datetime.now(UTC).isoformat(),
    }

    # Форматируем большие числа
    result["formatted"] = {
        "price": _format_price(price_usd),
        "market_cap": _format_large_number(market_cap),
        "volume_24h": _format_large_number(volume_24h),
        "liquidity": _format_large_number(liquidity),
        "holders": _format_number(holders_count),
    }

    return result


def _format_price(price: Optional[float]) -> str:
    """Форматирует цену."""
    if price is None:
        return "N/A"
    if price < 0.0001:
        return f"${price:.8f}"
    elif price < 1:
        return f"${price:.6f}"
    elif price < 100:
        return f"${price:.4f}"
    else:
        return f"${price:,.2f}"


def _format_large_number(num: Optional[float]) -> str:
    """Форматирует большое число (1.5M, 2.3B и т.д.)."""
    if num is None:
        return "N/A"

    num = float(num)

    if num >= 1_000_000_000:
        return f"${num / 1_000_000_000:.2f}B"
    elif num >= 1_000_000:
        return f"${num / 1_000_000:.2f}M"
    elif num >= 1_000:
        return f"${num / 1_000:.2f}K"
    else:
        return f"${num:,.2f}"


def _format_number(num: Optional[int]) -> str:
    """Форматирует число с разделителями."""
    if num is None:
        return "N/A"
    return f"{int(num):,}"


# =============================================================================
# Price Analysis
# =============================================================================


def analyze_price_history(token: str, days: int = 7) -> dict:
    """
    Анализирует историю цены токена.

    Args:
        token: Символ токена или адрес
        days: Количество дней

    Returns:
        dict с анализом
    """
    history = get_price_history(token, days=days, interval="1h")

    if not history.get("success"):
        return history

    data = history.get("history", [])

    if not data:
        return {"success": False, "error": "No price data available"}

    # Извлекаем цены
    prices = [float(p.get("price", 0)) for p in data if p.get("price")]

    if not prices:
        return {"success": False, "error": "No valid prices in history"}

    # Статистика
    current_price = prices[-1]
    start_price = prices[0]
    high_price = max(prices)
    low_price = min(prices)
    avg_price = sum(prices) / len(prices)

    # Изменения
    change_abs = current_price - start_price
    change_pct = (change_abs / start_price * 100) if start_price > 0 else 0

    # Волатильность (стандартное отклонение)
    variance = sum((p - avg_price) ** 2 for p in prices) / len(prices)
    volatility = variance**0.5
    volatility_pct = (volatility / avg_price * 100) if avg_price > 0 else 0

    # Тренд
    trend = "up" if change_pct > 5 else ("down" if change_pct < -5 else "sideways")

    return {
        "success": True,
        "token": token,
        "period_days": days,
        "data_points": len(prices),
        "current_price": current_price,
        "start_price": start_price,
        "high": high_price,
        "low": low_price,
        "average": avg_price,
        "change": {
            "absolute": change_abs,
            "percent": round(change_pct, 2),
            "direction": "+" if change_pct >= 0 else "",
        },
        "volatility": {
            "value": volatility,
            "percent": round(volatility_pct, 2),
            "level": "high"
            if volatility_pct > 20
            else ("medium" if volatility_pct > 10 else "low"),
        },
        "trend": trend,
        "formatted": {
            "current": _format_price(current_price),
            "high": _format_price(high_price),
            "low": _format_price(low_price),
            "change": f"{'+' if change_pct >= 0 else ''}{change_pct:.2f}%",
        },
        "history": history.get("history"),
    }


# =============================================================================
# Pool Analysis
# =============================================================================


def analyze_pools(token: str) -> dict:
    """
    Анализирует пулы токена.

    Args:
        token: Символ токена или адрес

    Returns:
        dict с анализом пулов
    """
    pools_data = get_token_pools(token)

    if not pools_data.get("success"):
        return pools_data

    pools = pools_data.get("pools", [])

    if not pools:
        return {
            "success": True,
            "token": token,
            "pools_count": 0,
            "message": "No pools found for this token",
        }

    # Группировка по DEX
    dex_stats = {}
    total_liquidity = 0
    total_volume = 0

    for pool in pools:
        dex = pool.get("dex", pool.get("dex_name", "unknown"))
        liq = pool.get("liquidity", 0) or 0
        vol = pool.get("volume_24h", 0) or 0

        if dex not in dex_stats:
            dex_stats[dex] = {
                "pools_count": 0,
                "total_liquidity": 0,
                "total_volume_24h": 0,
                "pairs": [],
            }

        dex_stats[dex]["pools_count"] += 1
        dex_stats[dex]["total_liquidity"] += liq
        dex_stats[dex]["total_volume_24h"] += vol
        dex_stats[dex]["pairs"].append(
            {
                "pair": pool.get("pair_name")
                or f"{pool.get('token0_symbol')}/{pool.get('token1_symbol')}",
                "liquidity": liq,
                "volume_24h": vol,
            }
        )

        total_liquidity += liq
        total_volume += vol

    # Сортировка пулов по ликвидности
    top_pools = sorted(pools, key=lambda x: x.get("liquidity", 0) or 0, reverse=True)[
        :5
    ]

    return {
        "success": True,
        "token": token,
        "pools_count": len(pools),
        "total_liquidity": total_liquidity,
        "total_volume_24h": total_volume,
        "dex_breakdown": dex_stats,
        "top_pools": top_pools,
        "formatted": {
            "total_liquidity": _format_large_number(total_liquidity),
            "total_volume_24h": _format_large_number(total_volume),
        },
    }


# =============================================================================
# Token Comparison
# =============================================================================


def compare_tokens_detailed(tokens: List[str]) -> dict:
    """
    Детальное сравнение токенов.

    Args:
        tokens: Список токенов

    Returns:
        dict со сравнением
    """
    results = []

    for token in tokens:
        info = get_full_token_info(token)

        results.append(
            {
                "token": token,
                "symbol": info.get("symbol"),
                "name": info.get("name"),
                "price_usd": info.get("price_usd"),
                "price_formatted": info.get("formatted", {}).get("price"),
                "market_cap": info.get("market_cap"),
                "market_cap_formatted": info.get("formatted", {}).get("market_cap"),
                "volume_24h": info.get("volume_24h"),
                "volume_formatted": info.get("formatted", {}).get("volume_24h"),
                "liquidity": info.get("liquidity"),
                "liquidity_formatted": info.get("formatted", {}).get("liquidity"),
                "holders": info.get("holders_count"),
                "holders_formatted": info.get("formatted", {}).get("holders"),
                "trust_score": info.get("trust_score"),
                "trust_level": info.get("trust_level"),
                "verification": info.get("verification"),
                "price_change_24h": info.get("price_change_24h"),
            }
        )

    # Рейтинги
    if len(results) > 1:
        # По market cap
        by_mcap = sorted(results, key=lambda x: x.get("market_cap") or 0, reverse=True)
        for i, r in enumerate(by_mcap):
            r["rank_by_mcap"] = i + 1

        # По ликвидности
        by_liq = sorted(results, key=lambda x: x.get("liquidity") or 0, reverse=True)
        for i, r in enumerate(by_liq):
            r["rank_by_liquidity"] = i + 1

        # По trust
        by_trust = sorted(
            results, key=lambda x: x.get("trust_score") or 0, reverse=True
        )
        for i, r in enumerate(by_trust):
            r["rank_by_trust"] = i + 1

    return {
        "success": True,
        "tokens_count": len(tokens),
        "comparison": results,
        "best_by_mcap": results[0]["symbol"] if results else None,
        "best_by_trust": max(results, key=lambda x: x.get("trust_score") or 0)["symbol"]
        if results
        else None,
    }


# =============================================================================
# CLI
# =============================================================================


def main():
    parser = argparse.ArgumentParser(
        description="TON Token Analytics CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Полная информация о токене
  %(prog)s info --token DUST
  
  # Trust score / скам-детекция
  %(prog)s trust --token NOT
  
  # История цены с анализом
  %(prog)s history --token STON --days 7
  
  # DEX пулы
  %(prog)s pools --token USDT
  
  # Сравнение токенов
  %(prog)s compare --tokens "DUST,NOT,STON"
  
  # Список известных токенов
  %(prog)s tokens

Notes:
  - Без DYOR API key используется только TonAPI (ограниченные данные)
  - Установить DYOR key: python dyor.py config --key YOUR_KEY
""",
    )

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # --- info ---
    info_p = subparsers.add_parser("info", help="Full token information")
    info_p.add_argument("--token", "-t", required=True, help="Token symbol or address")

    # --- trust ---
    trust_p = subparsers.add_parser("trust", help="Trust score / scam detection")
    trust_p.add_argument("--token", "-t", required=True, help="Token symbol or address")

    # --- history ---
    history_p = subparsers.add_parser("history", help="Price history analysis")
    history_p.add_argument(
        "--token", "-t", required=True, help="Token symbol or address"
    )
    history_p.add_argument(
        "--days", "-d", type=int, default=7, help="Number of days (default: 7)"
    )

    # --- pools ---
    pools_p = subparsers.add_parser("pools", help="DEX pools analysis")
    pools_p.add_argument("--token", "-t", required=True, help="Token symbol or address")

    # --- compare ---
    compare_p = subparsers.add_parser("compare", help="Compare multiple tokens")
    compare_p.add_argument(
        "--tokens", "-t", required=True, help="Comma-separated tokens"
    )

    # --- tokens ---
    subparsers.add_parser("tokens", help="List known tokens")

    # --- status ---
    subparsers.add_parser("status", help="Check API status")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    try:
        if args.command == "info":
            result = get_full_token_info(args.token)

        elif args.command == "trust":
            result = get_trust_score(args.token)

            # Добавляем человекочитаемую оценку
            score = result.get("trust_score")
            if score is not None:
                if score >= 80:
                    result["assessment"] = "✅ HIGH TRUST - Generally safe"
                elif score >= 50:
                    result["assessment"] = "⚠️ MEDIUM TRUST - Proceed with caution"
                elif score >= 20:
                    result["assessment"] = "🔴 LOW TRUST - High risk"
                else:
                    result["assessment"] = "🚨 VERY LOW TRUST - Likely scam"

        elif args.command == "history":
            result = analyze_price_history(args.token, args.days)

        elif args.command == "pools":
            result = analyze_pools(args.token)

        elif args.command == "compare":
            tokens = [t.strip() for t in args.tokens.split(",")]
            result = compare_tokens_detailed(tokens)

        elif args.command == "tokens":
            result = {
                "success": True,
                "known_tokens": [
                    {"symbol": k, "address": v} for k, v in sorted(KNOWN_TOKENS.items())
                ],
                "count": len(KNOWN_TOKENS),
            }

        elif args.command == "status":
            dyor_key = get_dyor_api_key()
            result = {
                "success": True,
                "dyor_api": {
                    "configured": bool(dyor_key),
                    "status": "ready" if dyor_key else "not configured",
                },
                "tonapi": {"status": "always available (fallback)"},
                "note": "Run 'python dyor.py config --key YOUR_KEY' to enable full DYOR features",
            }

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
