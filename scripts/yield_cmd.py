#!/usr/bin/env python3
"""
OpenClaw TON Skill — Yield/DeFi CLI

Работа с пулами ликвидности через swap.coffee v1 API:
- Список 2000+ пулов из 16 протоколов
- Детали пула (TVL, APR, объёмы)
- Рекомендации по выбору пула

Протоколы: stonfi, stonfi_v2, dedust, tonco, evaa, tonstakers, stakee, bemo,
           bemo_v2, hipo, kton, storm_trade, torch_finance, dao_lama_vault, bidask, coffee

Примечание: Депозит/вывод ликвидности требует прямого взаимодействия с контрактами DEX
и не поддерживается через API (read-only aggregator).

Документация: https://docs.swap.coffee/technical-guides/aggregator-api/yield-internals
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

from utils import api_request, tonapi_request, load_config, is_valid_address


def _make_url_safe(address: str) -> str:
    """Конвертирует адрес в URL-safe формат (заменяет +/ на -_)."""
    return address.replace("+", "-").replace("/", "_")


# =============================================================================
# Constants
# =============================================================================

SWAP_COFFEE_API = "https://backend.swap.coffee"

# Поддерживаемые протоколы (16)
SUPPORTED_PROTOCOLS = [
    "stonfi", "stonfi_v2", "dedust", "tonco", "evaa", "tonstakers",
    "stakee", "bemo", "bemo_v2", "hipo", "kton", "storm_trade",
    "torch_finance", "dao_lama_vault", "bidask", "coffee"
]

# Риск-профили
RISK_PROFILES = {
    "low": {
        "min_tvl": 1_000_000,
        "max_il_risk": 0.05,
        "stable_pairs_only": True,
        "min_age_days": 30,
    },
    "medium": {
        "min_tvl": 100_000,
        "max_il_risk": 0.15,
        "stable_pairs_only": False,
        "min_age_days": 7,
    },
    "high": {
        "min_tvl": 10_000,
        "max_il_risk": 1.0,
        "stable_pairs_only": False,
        "min_age_days": 1,
    },
}

# Stable tokens
STABLE_TOKENS = ["USDT", "USDC", "DAI", "TUSD", "jUSDT", "jUSDC"]


# =============================================================================
# Swap.coffee API v1
# =============================================================================


def get_swap_coffee_key() -> Optional[str]:
    """Получает API ключ swap.coffee из конфига."""
    config = load_config()
    return config.get("swap_coffee_key") or None


def swap_coffee_request(
    endpoint: str,
    method: str = "GET",
    params: Optional[dict] = None,
    json_data: Optional[dict] = None,
) -> dict:
    """
    Запрос к swap.coffee API v1.
    Yield API работает только на v1.
    """
    base_url = f"{SWAP_COFFEE_API}/v1"
    api_key = get_swap_coffee_key()

    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    return api_request(
        url=f"{base_url}{endpoint}",
        method=method,
        headers=headers,
        params=params,
        json_data=json_data,
    )


# =============================================================================
# Pool Data
# =============================================================================


def get_yield_pools(
    sort_by: str = "apr",
    min_tvl: Optional[float] = None,
    token: Optional[str] = None,
    protocol: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """
    Получает список yield пулов.

    Args:
        sort_by: Сортировка (apr, tvl, volume)
        min_tvl: Минимальный TVL
        token: Фильтр по токену
        protocol: Фильтр по протоколу (stonfi, dedust, etc.)
        limit: Максимум результатов
        offset: Смещение для пагинации

    Returns:
        dict с пулами
    """
    params = {"limit": limit, "offset": offset}
    
    # API поддерживает sort параметр
    if sort_by:
        params["sort"] = sort_by

    result = swap_coffee_request("/yield/pools", params=params)

    if result["success"]:
        data = result["data"]
        
        # Ответ может быть: [{total_count: N, pools: [...]}] или {total_count: N, pools: [...]}
        if isinstance(data, list) and len(data) > 0:
            data = data[0]  # API возвращает список с одним элементом
        
        total_count = data.get("total_count", 0) if isinstance(data, dict) else 0
        pools = data.get("pools", []) if isinstance(data, dict) else []
        
        if not isinstance(pools, list):
            pools = []

        # Нормализуем данные
        normalized = []
        for pool in pools:
            norm_pool = _normalize_pool(pool)
            
            # Фильтр по протоколу
            if protocol:
                if norm_pool.get("protocol", "").lower() != protocol.lower():
                    continue
            
            # Фильтр по минимальному TVL
            if min_tvl:
                pool_tvl = norm_pool.get("tvl_usd", 0) or 0
                if pool_tvl < min_tvl:
                    continue
            
            # Фильтр по токену
            if token:
                token_upper = token.upper()
                tokens = norm_pool.get("tokens", [])
                token_symbols = [t.get("symbol", "").upper() for t in tokens]
                if token_upper not in token_symbols:
                    continue
            
            normalized.append(norm_pool)

        # Сортируем локально если был фильтр
        if sort_by == "apr":
            normalized.sort(key=lambda x: x.get("apr", 0) or 0, reverse=True)
        elif sort_by == "tvl":
            normalized.sort(key=lambda x: x.get("tvl_usd", 0) or 0, reverse=True)
        elif sort_by == "volume":
            normalized.sort(key=lambda x: x.get("volume_usd", 0) or 0, reverse=True)

        return {
            "success": True,
            "source": "swap.coffee",
            "total_count": total_count,
            "pools_count": len(normalized),
            "protocols": SUPPORTED_PROTOCOLS,
            "pools": normalized[:limit],
        }

    # Fallback: получаем данные из DeDust API
    return _get_pools_fallback(sort_by, min_tvl, token, limit)


def _normalize_pool(pool: dict) -> dict:
    """
    Нормализует данные пула из v1 API.
    
    Формат v1 API:
    {
        address: str,
        protocol: str,
        is_trusted: bool,
        tokens: [{
            address: {blockchain: str, address: str},
            metadata: {name, symbol, decimals, listed, verification, image_url}
        }],
        pool_statistics: {
            address: str,
            tvl_usd: float,
            volume_usd: float,
            fee_usd: float,
            apr: float,
            lp_apr: float,
            boost_apr: float
        }
    }
    """
    address = pool.get("address")
    protocol = pool.get("protocol", "unknown")
    is_trusted = pool.get("is_trusted", False)
    
    # Парсим токены
    tokens = []
    tokens_raw = pool.get("tokens", [])
    token_symbols = []
    
    for t in tokens_raw:
        addr_info = t.get("address", {})
        metadata = t.get("metadata", {}) or {}
        
        token_addr = addr_info.get("address") if isinstance(addr_info, dict) else addr_info
        symbol = metadata.get("symbol", "?")
        
        tokens.append({
            "address": token_addr,
            "symbol": symbol,
            "name": metadata.get("name"),
            "decimals": metadata.get("decimals", 9),
            "verification": metadata.get("verification"),
            "image_url": metadata.get("image_url"),
        })
        token_symbols.append(symbol)
    
    # Парсим статистику
    stats = pool.get("pool_statistics", {}) or {}
    tvl_usd = stats.get("tvl_usd", 0) or 0
    volume_usd = stats.get("volume_usd", 0) or 0
    fee_usd = stats.get("fee_usd", 0) or 0
    apr = stats.get("apr", 0) or 0
    lp_apr = stats.get("lp_apr", 0) or 0
    boost_apr = stats.get("boost_apr", 0) or 0
    
    # Формируем название пары
    pair_name = "/".join(token_symbols) if token_symbols else "Unknown"
    
    # IL риск
    il_risk = _estimate_il_risk(token_symbols)
    
    return {
        "address": address,
        "protocol": protocol,
        "is_trusted": is_trusted,
        "pair": pair_name,
        "tokens": tokens,
        "tvl_usd": tvl_usd,
        "volume_usd": volume_usd,
        "fee_usd": fee_usd,
        "apr": apr,
        "lp_apr": lp_apr,
        "boost_apr": boost_apr,
        "il_risk": il_risk,
    }


def _estimate_il_risk(token_symbols: List[str]) -> float:
    """Оценивает риск impermanent loss."""
    symbols_upper = [s.upper() for s in token_symbols]
    
    # Stable/stable пары — минимальный IL
    stable_count = sum(1 for s in symbols_upper if s in STABLE_TOKENS)
    
    if stable_count >= 2:
        return 0.01
    
    # Stable/volatile — средний IL
    if stable_count == 1:
        return 0.10
    
    # Volatile/volatile — высокий IL
    return 0.25


def _get_pools_fallback(
    sort_by: str, min_tvl: Optional[float], token: Optional[str], limit: int
) -> dict:
    """Fallback для получения пулов через DeDust API."""
    result = api_request("https://api.dedust.io/v2/pools")

    if result["success"]:
        pools = result["data"]
        if isinstance(pools, list):
            normalized = []
            for p in pools:
                # Конвертируем DeDust формат
                assets = p.get("assets", [])
                token_symbols = []
                tokens = []
                
                for asset in assets[:2]:
                    metadata = asset.get("metadata", {}) or {}
                    symbol = metadata.get("symbol", "?")
                    token_symbols.append(symbol)
                    tokens.append({
                        "address": asset.get("address") if asset.get("type") == "jetton" else "native",
                        "symbol": symbol,
                        "name": metadata.get("name"),
                        "decimals": metadata.get("decimals", 9),
                    })
                
                tvl = p.get("tvl") or p.get("liquidity") or 0
                
                norm = {
                    "address": p.get("address"),
                    "protocol": "dedust",
                    "is_trusted": True,
                    "pair": "/".join(token_symbols),
                    "tokens": tokens,
                    "tvl_usd": tvl,
                    "volume_usd": p.get("volume_24h", 0),
                    "fee_usd": 0,
                    "apr": p.get("apy") or p.get("apr") or 0,
                    "lp_apr": 0,
                    "boost_apr": 0,
                    "il_risk": _estimate_il_risk(token_symbols),
                }
                
                # Фильтры
                if min_tvl and norm["tvl_usd"] < min_tvl:
                    continue
                if token:
                    token_upper = token.upper()
                    if token_upper not in [s.upper() for s in token_symbols]:
                        continue
                
                normalized.append(norm)

            # Сортируем
            if sort_by == "apr":
                normalized.sort(key=lambda x: x.get("apr", 0) or 0, reverse=True)
            elif sort_by == "tvl":
                normalized.sort(key=lambda x: x.get("tvl_usd", 0) or 0, reverse=True)

            return {
                "success": True,
                "source": "dedust",
                "pools_count": len(normalized),
                "pools": normalized[:limit],
            }

    return {
        "success": False,
        "error": "Failed to fetch pools from any source",
        "note": "swap.coffee API may be unavailable",
    }


def get_pool_details(pool_address: str) -> dict:
    """
    Получает детальную информацию о пуле.

    Args:
        pool_address: Адрес пула

    Returns:
        dict с деталями
    """
    # URL-safe адрес
    addr_safe = _make_url_safe(pool_address)
    
    result = swap_coffee_request(f"/yield/pool/{addr_safe}")

    if result["success"]:
        pool = result["data"]
        normalized = _normalize_pool(pool)
        
        return {
            "success": True,
            "source": "swap.coffee",
            "pool": normalized,
        }

    # Fallback: TonAPI pool info
    result = tonapi_request(f"/accounts/{addr_safe}")

    if result["success"]:
        data = result["data"]
        return {
            "success": True,
            "source": "tonapi",
            "pool": {
                "address": pool_address,
                "balance": data.get("balance"),
                "status": data.get("status"),
                "interfaces": data.get("interfaces", []),
            },
            "note": "Limited data from TonAPI. Use swap.coffee for full pool details.",
        }

    return {"success": False, "error": f"Pool not found: {pool_address}"}


# =============================================================================
# Recommendations
# =============================================================================


def recommend_pools(
    token: Optional[str] = None, risk: str = "medium", amount: Optional[float] = None
) -> dict:
    """
    Рекомендует пулы на основе критериев.

    Args:
        token: Предпочтительный токен
        risk: Уровень риска (low, medium, high)
        amount: Сумма для инвестирования

    Returns:
        dict с рекомендациями
    """
    risk_profile = RISK_PROFILES.get(risk, RISK_PROFILES["medium"])

    # Получаем пулы
    pools_result = get_yield_pools(
        sort_by="apr",
        min_tvl=risk_profile["min_tvl"],
        token=token,
        limit=100,
    )

    if not pools_result["success"]:
        return pools_result

    pools = pools_result["pools"]

    # Фильтруем по risk profile
    recommended = []

    for pool in pools:
        # IL риск
        if pool.get("il_risk", 1) > risk_profile["max_il_risk"]:
            continue

        # Stable pairs only
        if risk_profile["stable_pairs_only"]:
            tokens = pool.get("tokens", [])
            symbols = [t.get("symbol", "").upper() for t in tokens]
            if not any(s in STABLE_TOKENS for s in symbols):
                continue

        # Рассчитываем score
        apr = pool.get("apr", 0) or 0
        tvl = pool.get("tvl_usd", 0) or 0
        il_risk = pool.get("il_risk", 0.25)
        is_trusted = pool.get("is_trusted", False)

        # Score: высокий APR + высокий TVL - высокий IL + бонус за trusted
        score = (apr * 0.4) + (min(tvl / 10_000_000, 1) * 30) - (il_risk * 100)
        if is_trusted:
            score += 10

        pool["recommendation_score"] = round(score, 2)
        recommended.append(pool)

    # Сортируем по score
    recommended.sort(key=lambda x: x.get("recommendation_score", 0), reverse=True)

    # Топ-5
    top = recommended[:5]

    return {
        "success": True,
        "risk_profile": risk,
        "risk_parameters": risk_profile,
        "token_filter": token,
        "total_matching": len(recommended),
        "recommendations": top,
        "top_recommendation": top[0] if top else None,
        "note": f"Found {len(recommended)} pools matching {risk} risk profile",
    }


# =============================================================================
# Positions (TonAPI fallback only)
# =============================================================================


def get_positions(wallet: str) -> dict:
    """
    Получает LP позиции кошелька.
    
    Примечание: swap.coffee yield API не имеет эндпоинта для позиций,
    используется TonAPI fallback для поиска LP токенов.

    Args:
        wallet: Адрес кошелька

    Returns:
        dict с позициями
    """
    if not is_valid_address(wallet):
        return {"success": False, "error": f"Invalid wallet address: {wallet}"}

    wallet_safe = _make_url_safe(wallet)
    
    # Ищем LP токены через TonAPI
    result = tonapi_request(f"/accounts/{wallet_safe}/jettons")

    if not result["success"]:
        return {"success": False, "error": "Failed to fetch jettons"}

    jettons = result["data"].get("balances", [])

    # Фильтруем LP токены (эвристика: имя содержит LP, Pool, или известные DEX)
    lp_keywords = ["LP", "Pool", "DeDust", "STON.fi", "Megaton", "TONCO"]
    lp_positions = []

    for j in jettons:
        jetton_info = j.get("jetton", {})
        name = jetton_info.get("name", "")
        symbol = jetton_info.get("symbol", "")

        if any(
            kw.lower() in name.lower() or kw.lower() in symbol.lower()
            for kw in lp_keywords
        ):
            balance = j.get("balance", "0")
            decimals = jetton_info.get("decimals", 9)
            
            try:
                balance_float = int(balance) / (10 ** decimals)
            except:
                balance_float = 0
            
            lp_positions.append({
                "token_address": jetton_info.get("address"),
                "name": name,
                "symbol": symbol,
                "balance": balance,
                "balance_formatted": balance_float,
                "decimals": decimals,
                "value_usd": None,  # Unknown without price data
                "note": "Detected as LP token by name pattern",
            })

    return {
        "success": True,
        "source": "tonapi",
        "wallet": wallet,
        "positions_count": len(lp_positions),
        "positions": lp_positions,
        "note": "LP tokens detected by name pattern. Value estimation requires pool data.",
    }


# =============================================================================
# Deposit / Withdraw (Not supported via API)
# =============================================================================


def deposit_liquidity(*args, **kwargs) -> dict:
    """
    Депозит ликвидности в пул.
    
    ⚠️ НЕ ПОДДЕРЖИВАЕТСЯ через swap.coffee API.
    Требуется прямое взаимодействие с контрактами DEX.
    """
    return {
        "success": False,
        "error": "Deposit not supported via swap.coffee yield API",
        "note": "swap.coffee yield API is a read-only aggregator. "
                "Deposit requires direct interaction with DEX smart contracts "
                "(STON.fi, DeDust, TONCO, etc.).",
        "suggestion": "Use DEX-specific SDKs or the swap.py script for adding liquidity.",
    }


def withdraw_liquidity(*args, **kwargs) -> dict:
    """
    Вывод ликвидности из пула.
    
    ⚠️ НЕ ПОДДЕРЖИВАЕТСЯ через swap.coffee API.
    Требуется прямое взаимодействие с контрактами DEX.
    """
    return {
        "success": False,
        "error": "Withdraw not supported via swap.coffee yield API",
        "note": "swap.coffee yield API is a read-only aggregator. "
                "Withdraw requires direct interaction with DEX smart contracts "
                "(STON.fi, DeDust, TONCO, etc.).",
        "suggestion": "Use DEX-specific SDKs or burn LP tokens directly.",
    }


# =============================================================================
# CLI
# =============================================================================


def main():
    parser = argparse.ArgumentParser(
        description="Yield/DeFi operations via swap.coffee v1 API (read-only aggregator)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Список пулов
  %(prog)s pools --sort apr
  %(prog)s pools --sort tvl --min-tvl 1000000
  %(prog)s pools --token TON --limit 10
  %(prog)s pools --protocol stonfi
  %(prog)s pools --protocol dedust --sort apr
  
  # Детали пула
  %(prog)s pool --id EQD...abc
  
  # Рекомендации
  %(prog)s recommend --risk low
  %(prog)s recommend --token TON --risk medium
  
  # Позиции (через TonAPI)
  %(prog)s positions --wallet EQD...xyz

Supported protocols (16):
  stonfi, stonfi_v2, dedust, tonco, evaa, tonstakers, stakee, bemo,
  bemo_v2, hipo, kton, storm_trade, torch_finance, dao_lama_vault, bidask, coffee

Risk levels: low, medium, high

Note: Deposit/withdraw not supported via API — requires direct DEX contract interaction.
""",
    )

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # --- pools ---
    pools_p = subparsers.add_parser("pools", help="List yield pools (2000+ pools from 16 protocols)")
    pools_p.add_argument(
        "--sort", "-s", default="apr", choices=["apr", "tvl", "volume"], help="Sort by"
    )
    pools_p.add_argument("--min-tvl", type=float, help="Minimum TVL (USD) filter")
    pools_p.add_argument("--token", "-t", help="Filter by token symbol")
    pools_p.add_argument(
        "--protocol", "-P",
        choices=SUPPORTED_PROTOCOLS,
        help="Filter by protocol"
    )
    pools_p.add_argument("--limit", "-l", type=int, default=20, help="Max results")
    pools_p.add_argument("--offset", type=int, default=0, help="Offset for pagination")

    # --- pool ---
    pool_p = subparsers.add_parser("pool", help="Pool details")
    pool_p.add_argument("--id", "-i", required=True, help="Pool address")

    # --- recommend ---
    rec_p = subparsers.add_parser("recommend", help="Get pool recommendations")
    rec_p.add_argument("--token", "-t", help="Preferred token")
    rec_p.add_argument(
        "--risk",
        "-r",
        default="medium",
        choices=["low", "medium", "high"],
        help="Risk level",
    )
    rec_p.add_argument("--amount", "-a", type=float, help="Investment amount (informational)")

    # --- deposit (not supported) ---
    dep_p = subparsers.add_parser("deposit", help="⚠️ NOT SUPPORTED — requires direct DEX interaction")
    dep_p.add_argument("--pool", help="Pool address")
    dep_p.add_argument("--amount", "-a", type=float, help="Amount")
    dep_p.add_argument("--wallet", "-w", help="Wallet")
    dep_p.add_argument("--token", "-t", help="Token")
    dep_p.add_argument("--confirm", action="store_true", help="Confirm")

    # --- withdraw (not supported) ---
    with_p = subparsers.add_parser("withdraw", help="⚠️ NOT SUPPORTED — requires direct DEX interaction")
    with_p.add_argument("--pool", help="Pool address")
    with_p.add_argument("--wallet", "-w", help="Wallet")
    with_p.add_argument("--percentage", type=float, help="Percentage")
    with_p.add_argument("--confirm", action="store_true", help="Confirm")

    # --- positions ---
    pos_p = subparsers.add_parser("positions", help="View LP positions (via TonAPI)")
    pos_p.add_argument("--wallet", "-w", required=True, help="Wallet address")

    # --- protocols ---
    proto_p = subparsers.add_parser("protocols", help="List supported protocols")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    try:
        if args.command == "pools":
            result = get_yield_pools(
                sort_by=args.sort,
                min_tvl=args.min_tvl,
                token=args.token,
                protocol=args.protocol,
                limit=args.limit,
                offset=args.offset,
            )

        elif args.command == "pool":
            result = get_pool_details(args.id)

        elif args.command == "recommend":
            result = recommend_pools(
                token=args.token,
                risk=args.risk,
                amount=getattr(args, "amount", None),
            )

        elif args.command == "deposit":
            result = deposit_liquidity()

        elif args.command == "withdraw":
            result = withdraw_liquidity()

        elif args.command == "positions":
            result = get_positions(args.wallet)

        elif args.command == "protocols":
            result = {
                "success": True,
                "protocols_count": len(SUPPORTED_PROTOCOLS),
                "protocols": SUPPORTED_PROTOCOLS,
                "note": "swap.coffee aggregates pools from all these protocols",
            }

        else:
            result = {"error": f"Unknown command: {args.command}"}

        print(json.dumps(result, indent=2, ensure_ascii=False))

        if not result.get("success", True):
            sys.exit(1)

    except Exception as e:
        print(json.dumps({"error": str(e)}, indent=2))
        sys.exit(1)


if __name__ == "__main__":
    main()
