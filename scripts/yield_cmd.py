#!/usr/bin/env python3
"""
OpenClaw TON Skill — Yield/DeFi CLI

Работа с пулами ликвидности через swap.coffee v1 API:
- 2000 пулов из 16 протоколов
- Детали пула (TVL, APR, объёмы)
- Рекомендации по выбору пула

Протоколы: tonstakers, stakee, bemo, bemo_v2, hipo, kton, stonfi, stonfi_v2,
           dedust, tonco, evaa, storm_trade, torch_finance, dao_lama_vault, bidask, coffee

Примечание: API не поддерживает серверные фильтры — все фильтры применяются клиентски.
Депозит/вывод ликвидности требует прямого взаимодействия с контрактами DEX.

Документация: https://docs.swap.coffee/technical-guides/aggregator-api/yield-internals
"""

import os
import sys
import json
import time
import argparse
from pathlib import Path
from typing import Optional, List, Dict

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
    "tonstakers", "stakee", "bemo", "bemo_v2", "hipo", "kton",
    "stonfi", "stonfi_v2", "dedust", "tonco", "evaa", "storm_trade",
    "torch_finance", "dao_lama_vault", "bidask", "coffee"
]

# Риск-профили
RISK_PROFILES = {
    "low": {
        "min_tvl": 1_000_000,
        "max_il_risk": 0.05,
        "stable_pairs_only": True,
    },
    "medium": {
        "min_tvl": 100_000,
        "max_il_risk": 0.15,
        "stable_pairs_only": False,
    },
    "high": {
        "min_tvl": 10_000,
        "max_il_risk": 1.0,
        "stable_pairs_only": False,
    },
}

# Stable tokens
STABLE_TOKENS = ["USDT", "USDC", "DAI", "TUSD", "jUSDT", "jUSDC"]

# Cache settings
CACHE_FILE = Path.home() / ".openclaw" / "ton-skill" / "yield_pools_cache.json"
CACHE_TTL_SECONDS = 300  # 5 minutes


# =============================================================================
# Cache
# =============================================================================


def _load_cache() -> Optional[Dict]:
    """Загружает кэш пулов если он свежий."""
    if not CACHE_FILE.exists():
        return None
    
    try:
        with open(CACHE_FILE, "r") as f:
            cache = json.load(f)
        
        cached_at = cache.get("cached_at", 0)
        if time.time() - cached_at > CACHE_TTL_SECONDS:
            return None  # Cache expired
        
        return cache
    except Exception:
        return None


def _save_cache(pools: List[Dict], total_count: int) -> None:
    """Сохраняет пулы в кэш."""
    try:
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        cache = {
            "cached_at": time.time(),
            "total_count": total_count,
            "pools": pools,
        }
        with open(CACHE_FILE, "w") as f:
            json.dump(cache, f)
    except Exception:
        pass  # Ignore cache write errors


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


def _fetch_all_pools() -> tuple[List[Dict], int]:
    """
    Загружает все 2000 пулов (20 страниц по 100).
    Использует кэш если доступен.
    
    Returns:
        (pools, total_count)
    """
    # Check cache first
    cache = _load_cache()
    if cache:
        return cache["pools"], cache["total_count"]
    
    all_pools = []
    total_count = 2000
    
    # Fetch all 20 pages (limit=100, max per page)
    for page in range(1, 21):
        result = swap_coffee_request("/yield/pools", params={"page": page, "limit": 100})
        
        if not result["success"]:
            break
        
        data = result["data"]
        if isinstance(data, list) and len(data) > 0:
            data = data[0]
        
        total_count = data.get("total_count", 2000) if isinstance(data, dict) else 2000
        pools = data.get("pools", []) if isinstance(data, dict) else []
        
        if not pools:
            break
        
        all_pools.extend(pools)
    
    # Save to cache
    if all_pools:
        _save_cache(all_pools, total_count)
    
    return all_pools, total_count


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


def _filter_pools(
    pools: List[Dict],
    protocol: Optional[str] = None,
    token: Optional[str] = None,
    min_tvl: Optional[float] = None,
    trusted_only: bool = False,
) -> List[Dict]:
    """Применяет клиентские фильтры к пулам."""
    filtered = []
    
    for pool in pools:
        # Фильтр по протоколу
        if protocol:
            if pool.get("protocol", "").lower() != protocol.lower():
                continue
        
        # Фильтр по trusted
        if trusted_only:
            if not pool.get("is_trusted", False):
                continue
        
        # Фильтр по минимальному TVL
        if min_tvl:
            pool_tvl = pool.get("tvl_usd", 0) or 0
            if pool_tvl < min_tvl:
                continue
        
        # Фильтр по токену
        if token:
            token_upper = token.upper()
            tokens = pool.get("tokens", [])
            token_symbols = [t.get("symbol", "").upper() for t in tokens]
            if token_upper not in token_symbols:
                continue
        
        filtered.append(pool)
    
    return filtered


def _sort_pools(pools: List[Dict], sort_by: str) -> List[Dict]:
    """Сортирует пулы."""
    if sort_by == "apr":
        return sorted(pools, key=lambda x: x.get("apr", 0) or 0, reverse=True)
    elif sort_by == "tvl":
        return sorted(pools, key=lambda x: x.get("tvl_usd", 0) or 0, reverse=True)
    elif sort_by == "volume":
        return sorted(pools, key=lambda x: x.get("volume_usd", 0) or 0, reverse=True)
    return pools


def get_yield_pools(
    sort_by: str = "apr",
    min_tvl: Optional[float] = None,
    token: Optional[str] = None,
    protocol: Optional[str] = None,
    trusted_only: bool = False,
    limit: int = 20,
    page: int = 1,
    fetch_all: bool = False,
) -> dict:
    """
    Получает список yield пулов.

    API не поддерживает серверные фильтры — все фильтры клиентские.
    Для фильтрации/рекомендаций загружаются все 2000 пулов (с кэшированием).

    Args:
        sort_by: Сортировка (apr, tvl, volume)
        min_tvl: Минимальный TVL (client-side filter)
        token: Фильтр по токену (client-side filter)
        protocol: Фильтр по протоколу (client-side filter)
        trusted_only: Только trusted пулы (client-side filter)
        limit: Результатов на странице
        page: Номер страницы (1-indexed)
        fetch_all: Вернуть все результаты без пагинации

    Returns:
        dict с пулами
    """
    # Если есть фильтры или fetch_all — загружаем все пулы
    need_full_fetch = fetch_all or min_tvl or token or protocol or trusted_only
    
    if need_full_fetch:
        raw_pools, total_count = _fetch_all_pools()
        
        # Нормализуем
        normalized = [_normalize_pool(p) for p in raw_pools]
        
        # Фильтруем
        filtered = _filter_pools(
            normalized,
            protocol=protocol,
            token=token,
            min_tvl=min_tvl,
            trusted_only=trusted_only,
        )
        
        # Сортируем
        sorted_pools = _sort_pools(filtered, sort_by)
        
        # Пагинация
        if fetch_all:
            result_pools = sorted_pools
            result_page = "all"
        else:
            start = (page - 1) * limit
            end = start + limit
            result_pools = sorted_pools[start:end]
            result_page = page
        
        return {
            "success": True,
            "source": "swap.coffee",
            "total_count": total_count,
            "filtered_count": len(filtered),
            "page": result_page,
            "limit": limit,
            "pools_count": len(result_pools),
            "pools": result_pools,
        }
    
    # Без фильтров — просто загружаем одну страницу
    # API всегда возвращает до 100 записей, поэтому запрашиваем max(limit, 100)
    # и затем обрезаем до нужного limit
    fetch_limit = min(limit, 100)
    result = swap_coffee_request("/yield/pools", params={"page": page, "limit": fetch_limit})
    
    if not result["success"]:
        return _get_pools_fallback(sort_by, min_tvl, token, limit)
    
    data = result["data"]
    if isinstance(data, list) and len(data) > 0:
        data = data[0]
    
    total_count = data.get("total_count", 0) if isinstance(data, dict) else 0
    pools = data.get("pools", []) if isinstance(data, dict) else []
    
    # Нормализуем и сортируем
    normalized = [_normalize_pool(p) for p in pools]
    sorted_pools = _sort_pools(normalized, sort_by)
    
    # Apply limit
    result_pools = sorted_pools[:limit]
    
    return {
        "success": True,
        "source": "swap.coffee",
        "total_count": total_count,
        "page": page,
        "limit": limit,
        "pools_count": len(result_pools),
        "pools": result_pools,
    }


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
                
                normalized.append(norm)

            # Фильтруем и сортируем
            filtered = _filter_pools(normalized, min_tvl=min_tvl, token=token)
            sorted_pools = _sort_pools(filtered, sort_by)

            return {
                "success": True,
                "source": "dedust",
                "pools_count": len(sorted_pools),
                "pools": sorted_pools[:limit],
            }

    return {
        "success": False,
        "error": "Failed to fetch pools from any source",
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
    token: Optional[str] = None,
    risk: str = "medium",
    amount: Optional[float] = None,
) -> dict:
    """
    Рекомендует пулы на основе критериев.
    
    Загружает все 2000 пулов для полного анализа.

    Args:
        token: Предпочтительный токен
        risk: Уровень риска (low, medium, high)
        amount: Сумма для инвестирования

    Returns:
        dict с рекомендациями
    """
    risk_profile = RISK_PROFILES.get(risk, RISK_PROFILES["medium"])

    # Загружаем все пулы
    raw_pools, total_count = _fetch_all_pools()
    normalized = [_normalize_pool(p) for p in raw_pools]

    # Фильтруем по risk profile
    recommended = []

    for pool in normalized:
        # TVL filter
        tvl = pool.get("tvl_usd", 0) or 0
        if tvl < risk_profile["min_tvl"]:
            continue
        
        # IL риск
        if pool.get("il_risk", 1) > risk_profile["max_il_risk"]:
            continue

        # Stable pairs only
        if risk_profile["stable_pairs_only"]:
            tokens = pool.get("tokens", [])
            symbols = [t.get("symbol", "").upper() for t in tokens]
            if not any(s in STABLE_TOKENS for s in symbols):
                continue
        
        # Token filter
        if token:
            token_upper = token.upper()
            tokens = pool.get("tokens", [])
            symbols = [t.get("symbol", "").upper() for t in tokens]
            if token_upper not in symbols:
                continue

        # Рассчитываем score
        apr = pool.get("apr", 0) or 0
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
        "total_analyzed": len(normalized),
        "total_matching": len(recommended),
        "recommendations": top,
        "top_recommendation": top[0] if top else None,
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

    # Фильтруем LP токены (эвристика)
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
                "value_usd": None,
                "note": "Detected as LP token by name pattern",
            })

    return {
        "success": True,
        "source": "tonapi",
        "wallet": wallet,
        "positions_count": len(lp_positions),
        "positions": lp_positions,
        "note": "LP tokens detected by name pattern.",
    }


# =============================================================================
# Deposit / Withdraw (Not supported via API)
# =============================================================================


def deposit_liquidity(*args, **kwargs) -> dict:
    """Депозит не поддерживается через API."""
    return {
        "success": False,
        "error": "Deposit not supported via swap.coffee yield API",
        "note": "API is read-only. Use DEX-specific SDKs for deposits.",
    }


def withdraw_liquidity(*args, **kwargs) -> dict:
    """Вывод не поддерживается через API."""
    return {
        "success": False,
        "error": "Withdraw not supported via swap.coffee yield API",
        "note": "API is read-only. Use DEX-specific SDKs for withdrawals.",
    }


# =============================================================================
# CLI
# =============================================================================


def main():
    parser = argparse.ArgumentParser(
        description="Yield/DeFi pools via swap.coffee v1 API",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # List pools (page 1, sorted by APR)
  %(prog)s pools
  %(prog)s pools --sort tvl --limit 50
  
  # Pagination
  %(prog)s pools --page 2 --limit 100
  %(prog)s pools --all  # all 2000 pools
  
  # Filters (client-side, fetches all pools)
  %(prog)s pools --protocol stonfi
  %(prog)s pools --token TON
  %(prog)s pools --min-tvl 1000000
  %(prog)s pools --trusted-only
  %(prog)s pools --protocol dedust --token USDT --min-tvl 100000
  
  # Pool details
  %(prog)s pool --id EQD...abc
  
  # Recommendations (fetches all pools for analysis)
  %(prog)s recommend --risk low
  %(prog)s recommend --token TON --risk medium
  
  # LP positions
  %(prog)s positions --wallet EQD...xyz

Protocols (16): tonstakers, stakee, bemo, bemo_v2, hipo, kton, stonfi,
                stonfi_v2, dedust, tonco, evaa, storm_trade, torch_finance,
                dao_lama_vault, bidask, coffee

Total: 2000 pools | Max per page: 100 | Cache: 5 min

Note: Server-side filters don't work — all filtering is client-side.
      Deposit/withdraw require direct DEX contract interaction.
""",
    )

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # --- pools ---
    pools_p = subparsers.add_parser("pools", help="List yield pools")
    pools_p.add_argument(
        "--sort", "-s", default="apr", choices=["apr", "tvl", "volume"], help="Sort by"
    )
    pools_p.add_argument("--min-tvl", type=float, help="Minimum TVL USD (client-side)")
    pools_p.add_argument("--token", "-t", help="Filter by token symbol (client-side)")
    pools_p.add_argument(
        "--protocol", "-P",
        choices=SUPPORTED_PROTOCOLS,
        help="Filter by protocol (client-side)"
    )
    pools_p.add_argument("--trusted-only", action="store_true", help="Only trusted pools")
    pools_p.add_argument("--limit", "-l", type=int, default=20, help="Results per page (max 100)")
    pools_p.add_argument("--page", "-p", type=int, default=1, help="Page number (1-indexed)")
    pools_p.add_argument("--all", "-a", action="store_true", help="Fetch all 2000 pools")

    # --- pool ---
    pool_p = subparsers.add_parser("pool", help="Pool details")
    pool_p.add_argument("--id", "-i", required=True, help="Pool address")

    # --- recommend ---
    rec_p = subparsers.add_parser("recommend", help="Get pool recommendations")
    rec_p.add_argument("--token", "-t", help="Preferred token")
    rec_p.add_argument(
        "--risk", "-r", default="medium",
        choices=["low", "medium", "high"],
        help="Risk level",
    )
    rec_p.add_argument("--amount", "-a", type=float, help="Investment amount (info only)")

    # --- deposit (not supported) ---
    dep_p = subparsers.add_parser("deposit", help="NOT SUPPORTED via API")
    dep_p.add_argument("--pool", help="Pool address")
    dep_p.add_argument("--amount", "-a", type=float, help="Amount")
    dep_p.add_argument("--wallet", "-w", help="Wallet")
    dep_p.add_argument("--token", "-t", help="Token")
    dep_p.add_argument("--confirm", action="store_true")

    # --- withdraw (not supported) ---
    with_p = subparsers.add_parser("withdraw", help="NOT SUPPORTED via API")
    with_p.add_argument("--pool", help="Pool address")
    with_p.add_argument("--wallet", "-w", help="Wallet")
    with_p.add_argument("--percentage", type=float, help="Percentage")
    with_p.add_argument("--confirm", action="store_true")

    # --- positions ---
    pos_p = subparsers.add_parser("positions", help="View LP positions (via TonAPI)")
    pos_p.add_argument("--wallet", "-w", required=True, help="Wallet address")

    # --- protocols ---
    subparsers.add_parser("protocols", help="List supported protocols")

    # --- cache ---
    cache_p = subparsers.add_parser("cache", help="Cache management")
    cache_p.add_argument("--clear", action="store_true", help="Clear pools cache")
    cache_p.add_argument("--status", action="store_true", help="Show cache status")

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
                trusted_only=args.trusted_only,
                limit=args.limit,
                page=args.page,
                fetch_all=getattr(args, "all", False),
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
                "count": len(SUPPORTED_PROTOCOLS),
                "protocols": SUPPORTED_PROTOCOLS,
            }

        elif args.command == "cache":
            if args.clear:
                if CACHE_FILE.exists():
                    CACHE_FILE.unlink()
                    result = {"success": True, "message": "Cache cleared"}
                else:
                    result = {"success": True, "message": "Cache was empty"}
            else:
                cache = _load_cache()
                if cache:
                    age = int(time.time() - cache["cached_at"])
                    result = {
                        "success": True,
                        "cached": True,
                        "pools_count": len(cache["pools"]),
                        "age_seconds": age,
                        "expires_in": CACHE_TTL_SECONDS - age,
                    }
                else:
                    result = {"success": True, "cached": False}

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
