#!/usr/bin/env python3
"""
OpenClaw TON Skill — DNS (.ton домены)

- Резолв .ton доменов в адреса
- Информация о домене
"""

import sys
import json
import argparse
from pathlib import Path

# Локальный импорт
script_dir = Path(__file__).parent
sys.path.insert(0, str(script_dir))

from utils import tonapi_request, is_valid_address, raw_to_friendly, normalize_address  # noqa: E402


# =============================================================================
# DNS Resolution
# =============================================================================


def _format_dns_error(error) -> str:
    """Форматирует ошибку DNS в читаемый вид."""
    if isinstance(error, dict):
        inner_error = error.get("error", "")
        if "not resolved" in str(inner_error):
            return "Domain not found or has no wallet address"
        if "entity not found" in str(inner_error):
            return "Domain does not exist"
        return str(inner_error) if inner_error else "Unknown DNS error"
    return str(error)


def resolve_domain(domain: str) -> dict:
    """
    Резолвит .ton домен в адрес.

    Args:
        domain: Домен (с или без .ton суффикса)

    Returns:
        dict с wallet адресом и информацией о домене
    """
    # Нормализуем домен
    domain_clean = domain.lower().strip()
    if not domain_clean.endswith(".ton"):
        domain_clean += ".ton"

    # Убираем .ton для API
    # domain_name = domain_clean[:-4]

    # TonAPI DNS resolve
    result = tonapi_request(f"/dns/{domain_clean}/resolve")

    if not result["success"]:
        return {
            "success": False,
            "domain": domain_clean,
            "error": _format_dns_error(result.get("error", "Failed to resolve domain")),
        }

    data = result["data"]

    # Ищем wallet адрес
    wallet_address = None

    # Проверяем разные форматы ответа
    if "wallet" in data:
        wallet_info = data["wallet"]
        if isinstance(wallet_info, dict):
            wallet_address = wallet_info.get("address")
        else:
            wallet_address = wallet_info

    # Fallback: ищем в sites (некоторые домены имеют site но не wallet)
    sites = data.get("sites", [])

    return {
        "success": True,
        "domain": domain_clean,
        "wallet": wallet_address,
        "wallet_friendly": raw_to_friendly(wallet_address)
        if wallet_address and ":" in wallet_address
        else wallet_address,
        "sites": sites,
        "raw_response": data,
    }


def get_domain_info(domain: str) -> dict:
    """
    Получает полную информацию о .ton домене.

    Args:
        domain: Домен (с или без .ton суффикса)

    Returns:
        dict с информацией о домене (владелец, NFT адрес, expiry и т.д.)
    """
    # Нормализуем домен
    domain_clean = domain.lower().strip()
    if not domain_clean.endswith(".ton"):
        domain_clean += ".ton"

    # TonAPI DNS info
    result = tonapi_request(f"/dns/{domain_clean}")

    if not result["success"]:
        return {
            "success": False,
            "domain": domain_clean,
            "error": result.get("error", "Failed to get domain info"),
        }

    data = result["data"]

    # Парсим ответ
    nft_item = data.get("item", {})
    owner = nft_item.get("owner", {}).get("address")
    collection = nft_item.get("collection", {})

    return {
        "success": True,
        "domain": domain_clean,
        "owner": owner,
        "owner_friendly": raw_to_friendly(owner) if owner and ":" in owner else owner,
        "nft_address": nft_item.get("address"),
        "collection_name": collection.get("name", "TON DNS"),
        "collection_address": collection.get("address"),
        "expiring_at": data.get("expiring_at"),
        "raw_response": data,
    }


def is_ton_domain(address_or_domain: str) -> bool:
    """
    Проверяет, является ли строка .ton доменом.

    ВАЖНО: Возвращает True ТОЛЬКО для строк, явно заканчивающихся на .ton
    Не делает предположений о коротких именах — они могут быть лейблами кошельков.
    """
    clean = address_or_domain.strip()

    # Если это валидный TON адрес — точно не домен
    if is_valid_address(clean):
        return False

    # Если содержит ":" — это raw адрес, не домен
    if ":" in clean:
        return False

    clean_lower = clean.lower()

    # Только явное окончание .ton считается доменом
    # Короткие имена типа "skill-test" НЕ являются доменами — это могут быть лейблы кошельков
    if clean_lower.endswith(".ton"):
        return True

    return False


def resolve_address(address_or_domain: str) -> dict:
    """
    Универсальная функция: если .ton домен — резолвит, иначе возвращает как есть.

    Args:
        address_or_domain: Адрес или .ton домен

    Returns:
        dict с resolved адресом
    """
    if is_ton_domain(address_or_domain):
        result = resolve_domain(address_or_domain)
        if result["success"] and result.get("wallet"):
            return {
                "success": True,
                "input": address_or_domain,
                "is_domain": True,
                "domain": result["domain"],
                "address": result["wallet_friendly"] or result["wallet"],
                "address_raw": normalize_address(result["wallet"], "raw")
                if result["wallet"]
                else None,
            }
        else:
            return {
                "success": False,
                "input": address_or_domain,
                "is_domain": True,
                "error": result.get("error", "Domain has no wallet address"),
            }
    else:
        # Это адрес — валидируем
        if is_valid_address(address_or_domain):
            try:
                raw = normalize_address(address_or_domain, "raw")
                friendly = normalize_address(address_or_domain, "friendly")
                return {
                    "success": True,
                    "input": address_or_domain,
                    "is_domain": False,
                    "address": friendly,
                    "address_raw": raw,
                }
            except Exception as e:
                return {
                    "success": False,
                    "input": address_or_domain,
                    "is_domain": False,
                    "error": str(e),
                }
        else:
            return {
                "success": False,
                "input": address_or_domain,
                "is_domain": False,
                "error": "Invalid address format",
            }


# =============================================================================
# CLI
# =============================================================================


def main():
    parser = argparse.ArgumentParser(
        description="TON DNS (.ton domains) resolver",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s resolve wallet.ton
  %(prog)s resolve foundation
  %(prog)s info wallet.ton
  %(prog)s check wallet.ton
  %(prog)s check UQBvW8Z5huBkMJYdnfAEM5JqTNLuuFKuHT6P3HXGL0Zo...
""",
    )

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # --- resolve ---
    resolve_p = subparsers.add_parser("resolve", help="Resolve .ton domain to address")
    resolve_p.add_argument("domain", help="Domain name (with or without .ton)")

    # --- info ---
    info_p = subparsers.add_parser("info", help="Get domain info (owner, expiry, etc.)")
    info_p.add_argument("domain", help="Domain name (with or without .ton)")

    # --- check ---
    check_p = subparsers.add_parser(
        "check", help="Check if input is domain and resolve if needed"
    )
    check_p.add_argument("input", help="Address or domain")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    try:
        if args.command == "resolve":
            result = resolve_domain(args.domain)
        elif args.command == "info":
            result = get_domain_info(args.domain)
        elif args.command == "check":
            result = resolve_address(args.input)
        else:
            result = {"error": f"Unknown command: {args.command}"}

        print(json.dumps(result, indent=2, ensure_ascii=False))

    except Exception as e:
        print(json.dumps({"error": str(e)}, indent=2))
        return sys.exit(1)


if __name__ == "__main__":
    main()
