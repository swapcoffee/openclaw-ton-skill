#!/usr/bin/env python3
"""
OpenClaw TON Skill — Yield/DeFi CLI

Работа с пулами ликвидности через swap.coffee v1 API:
- 2000 пулов из 16 протоколов
- Детали пула (TVL, APR, объёмы)
- Рекомендации по выбору пула
- Депозит/вывод ликвидности (DEX пулы: stonfi_v2, dedust, tonco)

Протоколы: tonstakers, stakee, bemo, bemo_v2, hipo, kton, stonfi, stonfi_v2,
           dedust, tonco, evaa, storm_trade, torch_finance, dao_lama_vault, bidask, coffee

API Endpoints:
- GET /v1/yield/pools — список пулов
- GET /v1/yield/pool/{address} — детали пула
- GET /v1/yield/pool/{pool}/{user} — позиция пользователя
- POST /v1/yield/pool/{pool}/{user} — депозит/вывод (создаёт транзакции для TonConnect)
- GET /v1/yield/result?query_id=... — статус транзакции

Документация: https://docs.swap.coffee/technical-guides/aggregator-api/yield-internals
"""

import sys
import json
import time
import argparse
from pathlib import Path
from typing import Optional, List, Dict

# Локальный импорт
script_dir = Path(__file__).parent
sys.path.insert(0, str(script_dir))

from utils import api_request, tonapi_request, load_config, is_valid_address  # noqa: E402


def _make_url_safe(address: str) -> str:
    """Конвертирует адрес в URL-safe формат (заменяет +/ на -_)."""
    return address.replace("+", "-").replace("/", "_")


# =============================================================================
# Constants
# =============================================================================

SWAP_COFFEE_API = "https://backend.swap.coffee"

# Поддерживаемые провайдеры (DEX/протоколы)
SUPPORTED_PROVIDERS = [
    "tonstakers",
    "stakee",
    "bemo",
    "bemo_v2",
    "hipo",
    "kton",
    "stonfi",
    "stonfi_v2",
    "dedust",
    "tonco",
    "evaa",
    "storm_trade",
    "torch_finance",
    "dao_lama_vault",
    "bidask",
    "coffee",
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


def _fetch_all_pools(
    providers: Optional[List[str]] = None,
    trusted: bool = True,
    search_text: Optional[str] = None,
) -> tuple:
    """
    Загружает все пулы с серверной фильтрацией.
    Использует кэш если доступен (только для запросов без фильтров).

    Args:
        providers: Фильтр по провайдерам (stonfi, dedust, tonco, etc.)
        trusted: True = 2,000 pools (default), False = 85,971+ pools
        search_text: Поиск по адресу пула или тикерам токенов

    Returns:
        (pools, total_count)
    """
    # Check cache first (only for default trusted requests without filters)
    if not providers and trusted and not search_text:
        cache = _load_cache()
        if cache:
            return cache["pools"], cache["total_count"]

    all_pools = []
    total_count = 0
    page = 1

    while True:
        # Build params according to official API docs
        params = {
            "page": page,
            "size": 100,  # max per page
            "order": "tvl",  # valid values: tvl, apr, volume
            "descending_order": True,
            "trusted": trusted,
            "blockchains": "ton",
        }

        # Server-side filters
        if providers:
            params["providers"] = providers
        if search_text:
            params["search_text"] = search_text

        result = swap_coffee_request("/yield/pools", params=params)

        if not result["success"]:
            break

        data = result["data"]
        if isinstance(data, list) and len(data) > 0:
            data = data[0]

        total_count = data.get("total_count", 0) if isinstance(data, dict) else 0
        pools = data.get("pools", []) if isinstance(data, dict) else []

        if not pools:
            break

        all_pools.extend(pools)

        # Check if we need more pages
        if len(all_pools) >= total_count or len(pools) < 100:
            break

        page += 1

        # Safety limit
        if page > 50:
            break

    # Save to cache (only for unfiltered requests)
    if all_pools and not providers and trusted is None and not search_text:
        _save_cache(all_pools, total_count)

    return all_pools, total_count


def _normalize_pool(pool: dict, fallback_address: Optional[str] = None) -> dict:
    """
    Нормализует данные пула из v1 API.

    Поддерживает разные форматы ответа:
    - Из списка пулов (pools list)
    - Single pool response (pool details)

    Формат v1 API:
    {
        address: str,
        protocol: str,
        is_trusted: bool,
        tokens: [{
            address: {blockchain: str, address: str} | str,
            metadata: {name, symbol, decimals, listed, verification, image_url}
        }],
        pool_statistics: {...},
        pool: {amm_type: str}  # дополнительная инфа о пуле
    }

    Args:
        pool: Данные пула из API
        fallback_address: Адрес пула для использования если не найден в ответе
    """
    # Основные данные на верхнем уровне
    address = pool.get("address") or fallback_address
    protocol = pool.get("protocol", "unknown")
    is_trusted = pool.get("is_trusted", False)

    # Дополнительная инфа о пуле (если есть)
    pool_extra = pool.get("pool", {})
    if isinstance(pool_extra, dict):
        pool_type = pool_extra.get("@type") or pool_extra.get("amm_type") or "dex_pool"
    else:
        pool_type = "dex_pool"

    # Парсим токены - поддерживаем разные форматы
    tokens = []
    tokens_raw = pool.get("tokens", [])
    token_symbols = []

    for t in tokens_raw:
        if not isinstance(t, dict):
            continue

        # Адрес токена может быть в разных форматах
        addr_info = t.get("address")
        metadata = t.get("metadata", {}) or {}

        # Обработка разных форматов address
        token_addr = None
        if isinstance(addr_info, dict):
            token_addr = addr_info.get("address")
        elif isinstance(addr_info, str):
            token_addr = addr_info
        elif addr_info is None:
            # Попробуем найти адрес в других полях
            token_addr = t.get("token_address") or t.get("jetton_address")

        # Символ токена
        symbol = metadata.get("symbol") or t.get("symbol") or "?"

        # Если нет символа, попробуем извлечь из других полей
        if symbol == "?":
            name = metadata.get("name") or t.get("name")
            if name:
                symbol = name.upper()[:6]  # Используем имя как fallback

        tokens.append(
            {
                "address": token_addr,
                "symbol": symbol,
                "name": metadata.get("name") or t.get("name"),
                "decimals": metadata.get("decimals") or t.get("decimals", 9),
                "verification": metadata.get("verification") or t.get("verification"),
                "image_url": metadata.get("image_url") or t.get("image_url"),
            }
        )
        token_symbols.append(symbol)

    # Парсим статистику - может быть на верхнем уровне или в pool_statistics
    stats = pool.get("pool_statistics", {}) or {}
    if not stats:
        # Попробуем найти статистику на верхнем уровне
        stats = {
            k: v
            for k, v in pool.items()
            if k.startswith(("tvl", "volume", "fee", "apr"))
        }

    tvl_usd = stats.get("tvl_usd") or stats.get("tvl") or 0
    volume_usd = (
        stats.get("volume_usd") or stats.get("volume_24h") or stats.get("volume") or 0
    )
    fee_usd = stats.get("fee_usd") or stats.get("fee") or 0
    apr = stats.get("apr") or stats.get("apy") or 0
    lp_apr = stats.get("lp_apr") or 0
    boost_apr = stats.get("boost_apr") or 0

    # Формируем название пары
    pair_name = "/".join(token_symbols) if token_symbols else "Unknown"

    # IL риск
    il_risk = _estimate_il_risk(token_symbols)

    return {
        "address": address,
        "pool_type": pool_type,
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
    token: Optional[str] = None,
    min_tvl: Optional[float] = None,
) -> List[Dict]:
    """Применяет клиентские фильтры к пулам (токен, min_tvl)."""
    filtered = []

    for pool in pools:
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


def _sort_pools(pools: List[Dict], sort_by: str, descending: bool = True) -> List[Dict]:
    """Сортирует пулы."""
    if sort_by == "apr":
        return sorted(pools, key=lambda x: x.get("apr", 0) or 0, reverse=descending)
    elif sort_by == "tvl":
        return sorted(pools, key=lambda x: x.get("tvl_usd", 0) or 0, reverse=descending)
    elif sort_by == "volume":
        return sorted(
            pools, key=lambda x: x.get("volume_usd", 0) or 0, reverse=descending
        )
    return pools


def get_yield_pools(
    sort_by: str = "tvl",
    min_tvl: Optional[float] = None,
    token: Optional[str] = None,
    provider: Optional[str] = None,
    providers: Optional[List[str]] = None,
    trusted: bool = True,
    include_untrusted: bool = False,
    search_text: Optional[str] = None,
    size: int = 20,
    page: int = 1,
    fetch_all: bool = False,
) -> dict:
    """
    Получает список yield пулов.

    Server-side filters (API parameters):
        - providers: Список провайдеров (stonfi, dedust, tonco, etc.)
        - trusted: true = 2,000 pools (default), false = 85,971+ pools
        - search_text: Поиск по адресу пула или тикерам токенов
        - size: Количество результатов (max 100)
        - page: Номер страницы
        - order: Поле сортировки (tvl по умолчанию)
        - descending_order: Направление сортировки

    Client-side filters (post-processing):
        - token: Фильтр по конкретному токену (загружает все пулы!)
        - min_tvl: Минимальный TVL (загружает все пулы!)

    Args:
        sort_by: Сортировка (apr, tvl, volume) — default tvl
        min_tvl: Минимальный TVL (client-side filter, triggers full fetch)
        token: Фильтр по токену (client-side, triggers full fetch)
        provider: Фильтр по провайдеру (server-side)
        providers: Список провайдеров (server-side)
        trusted: Только trusted пулы (default True = 2000 pools)
        include_untrusted: Включить все 85K+ пулов (sets trusted=false)
        search_text: Поиск по адресу/тикеру (server-side)
        size: Результатов на странице (max 100)
        page: Номер страницы (1-indexed)
        fetch_all: Вернуть все результаты без пагинации

    Returns:
        dict с пулами
    """
    # Normalize provider/providers
    if provider and not providers:
        providers = [provider]

    # Handle trusted flag
    # Default: trusted=True (2000 pools)
    # --all-pools flag sets include_untrusted=True → trusted=False (85K+ pools)
    if include_untrusted:
        trusted = False

    # Map sort_by to API order field (valid: tvl, apr, volume)
    order = sort_by  # API accepts tvl, apr, volume directly

    # Если нужно загружать все или есть client-side фильтры
    need_full_fetch = fetch_all or min_tvl or token

    if need_full_fetch:
        raw_pools, total_count = _fetch_all_pools(
            providers=providers,
            trusted=trusted,
            search_text=search_text,
        )

        # Нормализуем
        normalized = [_normalize_pool(p) for p in raw_pools]

        # Client-side фильтры
        filtered = _filter_pools(
            normalized,
            token=token,
            min_tvl=min_tvl,
        )

        # Сортируем
        sorted_pools = _sort_pools(filtered, sort_by)

        # Пагинация
        if fetch_all:
            result_pools = sorted_pools
            result_page = "all"
        else:
            start = (page - 1) * size
            end = start + size
            result_pools = sorted_pools[start:end]
            result_page = page

        return {
            "success": True,
            "source": "swap.coffee",
            "total_count": total_count,
            "filtered_count": len(filtered),
            "trusted_only": trusted,
            "page": result_page,
            "size": size,
            "pools_count": len(result_pools),
            "pools": result_pools,
        }

    # Без client-side фильтров — используем server-side pagination
    params = {
        "page": page,
        "size": min(size, 100),
        "order": order,
        "descending_order": True,
        "trusted": trusted,
        "blockchains": "ton",
    }

    if providers:
        params["providers"] = providers
    if search_text:
        params["search_text"] = search_text

    result = swap_coffee_request("/yield/pools", params=params)

    if not result["success"]:
        return _get_pools_fallback(sort_by, min_tvl, token, size)

    data = result["data"]
    if isinstance(data, list) and len(data) > 0:
        data = data[0]

    total_count = data.get("total_count", 0) if isinstance(data, dict) else 0
    pools = data.get("pools", []) if isinstance(data, dict) else []

    # Нормализуем
    normalized = [_normalize_pool(p) for p in pools]

    return {
        "success": True,
        "source": "swap.coffee",
        "total_count": total_count,
        "trusted_only": trusted,
        "page": page,
        "size": size,
        "pools_count": len(normalized),
        "pools": normalized,
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
                    tokens.append(
                        {
                            "address": asset.get("address")
                            if asset.get("type") == "jetton"
                            else "native",
                            "symbol": symbol,
                            "name": metadata.get("name"),
                            "decimals": metadata.get("decimals", 9),
                        }
                    )

                tvl = p.get("tvl") or p.get("liquidity") or 0

                norm = {
                    "address": p.get("address"),
                    "pool_type": "dex_pool",
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
        # Передаем pool_address как fallback на случай если API не вернул address
        normalized = _normalize_pool(pool, fallback_address=pool_address)

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

    Загружает все пулы для полного анализа.

    Args:
        token: Предпочтительный токен
        risk: Уровень риска (low, medium, high)
        amount: Сумма для инвестирования

    Returns:
        dict с рекомендациями
    """
    risk_profile = RISK_PROFILES.get(risk, RISK_PROFILES["medium"])

    # Загружаем все пулы (trusted only for recommendations)
    raw_pools, total_count = _fetch_all_pools(trusted=True)
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
                balance_float = int(balance) / (10**decimals)
            except Exception:
                balance_float = 0

            lp_positions.append(
                {
                    "token_address": jetton_info.get("address"),
                    "name": name,
                    "symbol": symbol,
                    "balance": balance,
                    "balance_formatted": balance_float,
                    "decimals": decimals,
                    "value_usd": None,
                    "note": "Detected as LP token by name pattern",
                }
            )

    return {
        "success": True,
        "source": "tonapi",
        "wallet": wallet,
        "positions_count": len(lp_positions),
        "positions": lp_positions,
        "note": "LP tokens detected by name pattern.",
    }


# =============================================================================
# User Position in Pool (via swap.coffee)
# =============================================================================


def get_user_position(pool_address: str, user_address: str) -> dict:
    """
    Получает информацию о позиции пользователя в конкретном пуле.

    GET /v1/yield/pool/{pool_address}/{user_address}

    Returns: user_lp_amount, user_lp_wallet, boosts info, etc.

    Args:
        pool_address: Адрес пула
        user_address: Адрес кошелька пользователя

    Returns:
        dict с информацией о позиции
    """
    if not is_valid_address(pool_address):
        return {"success": False, "error": f"Invalid pool address: {pool_address}"}
    if not is_valid_address(user_address):
        return {"success": False, "error": f"Invalid user address: {user_address}"}

    pool_safe = _make_url_safe(pool_address)
    user_safe = _make_url_safe(user_address)

    result = swap_coffee_request(f"/yield/pool/{pool_safe}/{user_safe}")

    if result["success"]:
        data = result["data"]
        return {
            "success": True,
            "pool_address": pool_address,
            "user_address": user_address,
            "user_lp_amount": data.get("user_lp_amount"),
            "user_lp_wallet": data.get("user_lp_wallet"),
            "boosts": data.get("boosts", []),
            "raw_data": data,
        }

    return {
        "success": False,
        "error": result.get("error", "Failed to get user position"),
        "status_code": result.get("status_code"),
    }


# =============================================================================
# Transaction Status Check
# =============================================================================


def check_tx_status(query_id: str) -> dict:
    """
    Проверяет статус транзакции по query_id.

    GET /v1/yield/result?query_id=123456

    Returns: pending/success/failed

    Args:
        query_id: ID из ответа deposit/withdraw операции

    Returns:
        dict со статусом транзакции
    """
    result = swap_coffee_request("/yield/result", params={"query_id": query_id})

    if result["success"]:
        return {
            "success": True,
            "query_id": query_id,
            "status": result["data"],
        }

    return {
        "success": False,
        "error": result.get("error", "Failed to check status"),
        "status_code": result.get("status_code"),
    }


# =============================================================================
# Deposit / Withdraw via swap.coffee API
# =============================================================================


def deposit_liquidity(
    pool_address: str,
    user_address: str,
    asset_1_amount: str,
    asset_2_amount: str,
    min_lp_amount: Optional[str] = None,
) -> dict:
    """
    Создаёт транзакции для депозита ликвидности в DEX пул.

    Поддерживаемые DEX: stonfi_v2, dedust, tonco

    Body format:
    {
        "request_data": {
            "yieldTypeResolver": "dex_provide_liquidity",
            "user_wallet": "...",
            "asset_1_amount": "...",
            "asset_2_amount": "...",
            "min_lp_amount": "..." (optional)
        }
    }

    Response: Array of {query_id, message: {payload_cell, address, value}}
    """
    if not is_valid_address(pool_address):
        return {"success": False, "error": f"Invalid pool address: {pool_address}"}
    if not is_valid_address(user_address):
        return {"success": False, "error": f"Invalid user address: {user_address}"}

    pool_safe = _make_url_safe(pool_address)
    user_safe = _make_url_safe(user_address)

    url = f"/yield/pool/{pool_safe}/{user_safe}"

    # Body format: yieldTypeResolver discriminator inside request_data
    request_data = {
        "yieldTypeResolver": "dex_provide_liquidity",
        "user_wallet": user_address,
        "asset_1_amount": str(asset_1_amount),
        "asset_2_amount": str(asset_2_amount),
    }

    if min_lp_amount:
        request_data["min_lp_amount"] = str(min_lp_amount)

    body = {"request_data": request_data}

    result = swap_coffee_request(url, method="POST", json_data=body)

    if result["success"]:
        transactions = result["data"]

        # Extract query_ids from response
        query_ids = []
        if isinstance(transactions, list):
            for tx in transactions:
                if "query_id" in tx:
                    query_ids.append(tx["query_id"])

        return {
            "success": True,
            "operation": "deposit",
            "pool_address": pool_address,
            "user_address": user_address,
            "asset_1_amount": asset_1_amount,
            "asset_2_amount": asset_2_amount,
            "query_ids": query_ids,
            "transactions_count": len(transactions)
            if isinstance(transactions, list)
            else 1,
            "transactions": transactions,
            "note": "Send these transactions via TonConnect. Check status with: tx-status --query-id <id>",
        }

    error = result.get("error", "Unknown error")
    error_msg = (
        error.get("error", str(error)) if isinstance(error, dict) else str(error)
    )

    # Provide helpful error messages
    if "Unsupported dex" in str(error_msg):
        return {
            "success": False,
            "error": error_msg,
            "note": "This pool type doesn't support deposits via API. "
            "Use stonfi_v2, dedust, or tonco pools.",
        }
    elif "outdated" in str(error_msg).lower():
        return {
            "success": False,
            "error": error_msg,
            "note": "This DEX version is outdated. Try a newer pool (e.g., stonfi_v2).",
        }

    return {
        "success": False,
        "error": error_msg,
        "status_code": result.get("status_code"),
    }


def withdraw_liquidity(
    pool_address: str,
    user_address: str,
    lp_amount: str,
) -> dict:
    """
    Создаёт транзакцию для вывода ликвидности из DEX пула.

    Body format:
    {
        "request_data": {
            "yieldTypeResolver": "dex_withdraw_liquidity",
            "user_address": "...",
            "lp_amount": "..."
        }
    }
    """
    if not is_valid_address(pool_address):
        return {"success": False, "error": f"Invalid pool address: {pool_address}"}
    if not is_valid_address(user_address):
        return {"success": False, "error": f"Invalid user address: {user_address}"}

    pool_safe = _make_url_safe(pool_address)
    user_safe = _make_url_safe(user_address)

    url = f"/yield/pool/{pool_safe}/{user_safe}"

    body = {
        "request_data": {
            "yieldTypeResolver": "dex_withdraw_liquidity",
            "user_address": user_address,
            "lp_amount": str(lp_amount),
        }
    }

    result = swap_coffee_request(url, method="POST", json_data=body)

    if result["success"]:
        transactions = result["data"]

        # Extract query_ids
        query_ids = []
        if isinstance(transactions, list):
            for tx in transactions:
                if "query_id" in tx:
                    query_ids.append(tx["query_id"])

        return {
            "success": True,
            "operation": "withdraw",
            "pool_address": pool_address,
            "user_address": user_address,
            "lp_amount": lp_amount,
            "query_ids": query_ids,
            "transactions_count": len(transactions)
            if isinstance(transactions, list)
            else 1,
            "transactions": transactions,
            "note": "Send this transaction via TonConnect. Check status with: tx-status --query-id <id>",
        }

    error = result.get("error", "Unknown error")
    error_msg = (
        error.get("error", str(error)) if isinstance(error, dict) else str(error)
    )

    return {
        "success": False,
        "error": error_msg,
        "status_code": result.get("status_code"),
    }


def stonfi_lock_staking(
    pool_address: str,
    user_address: str,
    lp_amount: str,
    minter_address: str,
) -> dict:
    """
    Создаёт транзакцию для стейкинга LP токенов в STON.fi farm.

    Body format:
    {
        "request_data": {
            "yieldTypeResolver": "dex_stonfi_lock_staking",
            "lp_amount": "...",
            "minter_address": "..."
        }
    }
    """
    if not is_valid_address(pool_address):
        return {"success": False, "error": f"Invalid pool address: {pool_address}"}
    if not is_valid_address(user_address):
        return {"success": False, "error": f"Invalid user address: {user_address}"}

    pool_safe = _make_url_safe(pool_address)
    user_safe = _make_url_safe(user_address)

    url = f"/yield/pool/{pool_safe}/{user_safe}"

    body = {
        "request_data": {
            "yieldTypeResolver": "dex_stonfi_lock_staking",
            "lp_amount": str(lp_amount),
            "minter_address": minter_address,
        }
    }

    result = swap_coffee_request(url, method="POST", json_data=body)

    if result["success"]:
        transactions = result["data"]
        query_ids = [
            tx.get("query_id")
            for tx in transactions
            if isinstance(transactions, list) and "query_id" in tx
        ]

        return {
            "success": True,
            "operation": "stonfi_lock_staking",
            "pool_address": pool_address,
            "user_address": user_address,
            "lp_amount": lp_amount,
            "minter_address": minter_address,
            "query_ids": query_ids,
            "transactions": transactions,
        }

    return {
        "success": False,
        "error": result.get("error", "Unknown error"),
        "status_code": result.get("status_code"),
    }


def stonfi_withdraw_staking(
    pool_address: str,
    user_address: str,
    position_address: str,
) -> dict:
    """
    Создаёт транзакцию для вывода LP токенов из STON.fi farm.

    Body format:
    {
        "request_data": {
            "yieldTypeResolver": "dex_stonfi_withdraw_staking",
            "position_address": "..."
        }
    }
    """
    if not is_valid_address(pool_address):
        return {"success": False, "error": f"Invalid pool address: {pool_address}"}
    if not is_valid_address(user_address):
        return {"success": False, "error": f"Invalid user address: {user_address}"}

    pool_safe = _make_url_safe(pool_address)
    user_safe = _make_url_safe(user_address)

    url = f"/yield/pool/{pool_safe}/{user_safe}"

    body = {
        "request_data": {
            "yieldTypeResolver": "dex_stonfi_withdraw_staking",
            "position_address": position_address,
        }
    }

    result = swap_coffee_request(url, method="POST", json_data=body)

    if result["success"]:
        transactions = result["data"]
        query_ids = [
            tx.get("query_id")
            for tx in transactions
            if isinstance(transactions, list) and "query_id" in tx
        ]

        return {
            "success": True,
            "operation": "stonfi_withdraw_staking",
            "pool_address": pool_address,
            "user_address": user_address,
            "position_address": position_address,
            "query_ids": query_ids,
            "transactions": transactions,
        }

    return {
        "success": False,
        "error": result.get("error", "Unknown error"),
        "status_code": result.get("status_code"),
    }


def stake_liquidity(
    pool_address: str,
    user_address: str,
    amount: str,
) -> dict:
    """
    Создаёт транзакцию для стейкинга в liquid staking пул.

    Поддерживаемые протоколы: tonstakers, bemo, bemo_v2, hipo, kton, stakee

    Body format:
    {
        "request_data": {
            "yieldTypeResolver": "liquid_staking_stake",
            "amount": "..."
        }
    }
    """
    if not is_valid_address(pool_address):
        return {"success": False, "error": f"Invalid pool address: {pool_address}"}
    if not is_valid_address(user_address):
        return {"success": False, "error": f"Invalid user address: {user_address}"}

    pool_safe = _make_url_safe(pool_address)
    user_safe = _make_url_safe(user_address)

    url = f"/yield/pool/{pool_safe}/{user_safe}"

    body = {
        "request_data": {
            "yieldTypeResolver": "liquid_staking_stake",
            "amount": str(amount),
        }
    }

    result = swap_coffee_request(url, method="POST", json_data=body)

    if result["success"]:
        transactions = result["data"]
        query_ids = [
            tx.get("query_id")
            for tx in transactions
            if isinstance(transactions, list) and "query_id" in tx
        ]

        return {
            "success": True,
            "operation": "stake",
            "pool_address": pool_address,
            "user_address": user_address,
            "amount": amount,
            "query_ids": query_ids,
            "transactions_count": len(transactions)
            if isinstance(transactions, list)
            else 1,
            "transactions": transactions,
            "note": "Send this transaction via TonConnect to stake",
        }

    error = result.get("error", "Unknown error")
    error_msg = (
        error.get("error", str(error)) if isinstance(error, dict) else str(error)
    )

    return {
        "success": False,
        "error": error_msg,
        "status_code": result.get("status_code"),
    }


def unstake_liquidity(
    pool_address: str,
    user_address: str,
    amount: str,
) -> dict:
    """
    Создаёт транзакцию для анстейкинга из liquid staking пула.

    Body format:
    {
        "request_data": {
            "yieldTypeResolver": "liquid_staking_unstake",
            "amount": "..."
        }
    }
    """
    if not is_valid_address(pool_address):
        return {"success": False, "error": f"Invalid pool address: {pool_address}"}
    if not is_valid_address(user_address):
        return {"success": False, "error": f"Invalid user address: {user_address}"}

    pool_safe = _make_url_safe(pool_address)
    user_safe = _make_url_safe(user_address)

    url = f"/yield/pool/{pool_safe}/{user_safe}"

    body = {
        "request_data": {
            "yieldTypeResolver": "liquid_staking_unstake",
            "amount": str(amount),
        }
    }

    result = swap_coffee_request(url, method="POST", json_data=body)

    if result["success"]:
        transactions = result["data"]
        query_ids = [
            tx.get("query_id")
            for tx in transactions
            if isinstance(transactions, list) and "query_id" in tx
        ]

        return {
            "success": True,
            "operation": "unstake",
            "pool_address": pool_address,
            "user_address": user_address,
            "amount": amount,
            "query_ids": query_ids,
            "transactions_count": len(transactions)
            if isinstance(transactions, list)
            else 1,
            "transactions": transactions,
            "note": "Send this transaction via TonConnect to unstake",
        }

    error = result.get("error", "Unknown error")
    error_msg = (
        error.get("error", str(error)) if isinstance(error, dict) else str(error)
    )

    return {
        "success": False,
        "error": error_msg,
        "status_code": result.get("status_code"),
    }


def lending_deposit(
    pool_address: str,
    user_address: str,
    amount: str,
) -> dict:
    """
    Создаёт транзакцию для депозита в lending протокол.

    Поддерживаемые протоколы: evaa

    Body format:
    {
        "request_data": {
            "yieldTypeResolver": "lending_deposit",
            "amount": "..."
        }
    }
    """
    if not is_valid_address(pool_address):
        return {"success": False, "error": f"Invalid pool address: {pool_address}"}
    if not is_valid_address(user_address):
        return {"success": False, "error": f"Invalid user address: {user_address}"}

    pool_safe = _make_url_safe(pool_address)
    user_safe = _make_url_safe(user_address)

    url = f"/yield/pool/{pool_safe}/{user_safe}"

    body = {
        "request_data": {
            "yieldTypeResolver": "lending_deposit",
            "amount": str(amount),
        }
    }

    result = swap_coffee_request(url, method="POST", json_data=body)

    if result["success"]:
        transactions = result["data"]
        query_ids = [
            tx.get("query_id")
            for tx in transactions
            if isinstance(transactions, list) and "query_id" in tx
        ]

        return {
            "success": True,
            "operation": "lending_deposit",
            "pool_address": pool_address,
            "user_address": user_address,
            "amount": amount,
            "query_ids": query_ids,
            "transactions_count": len(transactions)
            if isinstance(transactions, list)
            else 1,
            "transactions": transactions,
            "note": "Send this transaction via TonConnect to deposit to lending",
        }

    error = result.get("error", "Unknown error")
    error_msg = (
        error.get("error", str(error)) if isinstance(error, dict) else str(error)
    )

    return {
        "success": False,
        "error": error_msg,
        "status_code": result.get("status_code"),
    }


def lending_withdraw(
    pool_address: str,
    user_address: str,
    amount: str,
) -> dict:
    """
    Создаёт транзакцию для вывода из lending протокола.

    Body format:
    {
        "request_data": {
            "yieldTypeResolver": "lending_withdraw",
            "amount": "..."
        }
    }
    """
    if not is_valid_address(pool_address):
        return {"success": False, "error": f"Invalid pool address: {pool_address}"}
    if not is_valid_address(user_address):
        return {"success": False, "error": f"Invalid user address: {user_address}"}

    pool_safe = _make_url_safe(pool_address)
    user_safe = _make_url_safe(user_address)

    url = f"/yield/pool/{pool_safe}/{user_safe}"

    body = {
        "request_data": {
            "yieldTypeResolver": "lending_withdraw",
            "amount": str(amount),
        }
    }

    result = swap_coffee_request(url, method="POST", json_data=body)

    if result["success"]:
        transactions = result["data"]
        query_ids = [
            tx.get("query_id")
            for tx in transactions
            if isinstance(transactions, list) and "query_id" in tx
        ]

        return {
            "success": True,
            "operation": "lending_withdraw",
            "pool_address": pool_address,
            "user_address": user_address,
            "amount": amount,
            "query_ids": query_ids,
            "transactions_count": len(transactions)
            if isinstance(transactions, list)
            else 1,
            "transactions": transactions,
            "note": "Send this transaction via TonConnect to withdraw from lending",
        }

    error = result.get("error", "Unknown error")
    error_msg = (
        error.get("error", str(error)) if isinstance(error, dict) else str(error)
    )

    return {
        "success": False,
        "error": error_msg,
        "status_code": result.get("status_code"),
    }


# =============================================================================
# Generic Yield Interact
# =============================================================================


def yield_interact(
    pool_address: str,
    user_address: str,
    yield_type_resolver: str,
    params: Optional[Dict] = None,
) -> dict:
    """
    Универсальный эндпоинт для взаимодействия с yield протоколами.

    POST /v1/yield/interact

    Позволяет выполнять любые операции с yield через единый интерфейс.

    Поддерживаемые yieldTypeResolver:
    - dex_provide_liquidity — депозит в DEX пул
    - dex_withdraw_liquidity — вывод из DEX пула
    - dex_stonfi_lock_staking — стейкинг LP в STON.fi farm
    - dex_stonfi_withdraw_staking — вывод LP из STON.fi farm
    - liquid_staking_stake — стейкинг в liquid staking
    - liquid_staking_unstake — вывод из liquid staking
    - lending_deposit — депозит в lending
    - lending_withdraw — вывод из lending

    Args:
        pool_address: Адрес пула/протокола
        user_address: Адрес пользователя
        yield_type_resolver: Тип операции (см. выше)
        params: Дополнительные параметры операции

    Returns:
        dict с транзакциями для подписания

    Examples:
        # Deposit to DEX
        yield_interact(pool, user, "dex_provide_liquidity", {
            "asset_1_amount": "1000000000",
            "asset_2_amount": "1000000000"
        })

        # Stake to liquid staking
        yield_interact(pool, user, "liquid_staking_stake", {
            "amount": "1000000000"
        })
    """
    if not is_valid_address(pool_address):
        return {"success": False, "error": f"Invalid pool address: {pool_address}"}
    if not is_valid_address(user_address):
        return {"success": False, "error": f"Invalid user address: {user_address}"}

    # Формируем body запроса
    request_data = {
        "yieldTypeResolver": yield_type_resolver,
        "user_wallet": user_address,
    }

    # Добавляем дополнительные параметры
    if params:
        request_data.update(params)

    body = {
        "pool_address": pool_address,
        "user_address": user_address,
        "request_data": request_data,
    }

    result = swap_coffee_request("/yield/interact", method="POST", json_data=body)

    if result["success"]:
        data = result["data"]
        transactions = data if isinstance(data, list) else [data]

        # Извлекаем query_ids
        query_ids = []
        for tx in transactions:
            if isinstance(tx, dict) and "query_id" in tx:
                query_ids.append(tx["query_id"])

        return {
            "success": True,
            "operation": yield_type_resolver,
            "pool_address": pool_address,
            "user_address": user_address,
            "params": params,
            "query_ids": query_ids,
            "transactions_count": len(transactions),
            "transactions": transactions,
            "note": "Send these transactions via TonConnect. Check status with: tx-status --query-id <id>",
        }

    error = result.get("error", "Unknown error")
    error_msg = (
        error.get("error", str(error)) if isinstance(error, dict) else str(error)
    )

    # Подсказки для частых ошибок
    hints = {}
    if "Unsupported" in str(error_msg):
        hints["hint"] = "This pool/protocol may not support this operation type."
    elif "Invalid" in str(error_msg):
        hints["hint"] = "Check pool address and parameters format."

    return {
        "success": False,
        "error": error_msg,
        "status_code": result.get("status_code"),
        "operation": yield_type_resolver,
        **hints,
    }


def get_yield_types() -> dict:
    """
    Возвращает список поддерживаемых yield операций.

    Returns:
        dict со списком операций
    """
    yield_types = {
        "dex_provide_liquidity": {
            "description": "Deposit liquidity into DEX pool",
            "protocols": ["stonfi_v2", "dedust", "tonco"],
            "required_params": ["asset_1_amount", "asset_2_amount"],
            "optional_params": ["min_lp_amount"],
        },
        "dex_withdraw_liquidity": {
            "description": "Withdraw liquidity from DEX pool",
            "protocols": ["stonfi_v2", "dedust", "tonco"],
            "required_params": ["lp_amount"],
        },
        "dex_stonfi_lock_staking": {
            "description": "Lock LP tokens in STON.fi farm",
            "protocols": ["stonfi_v2"],
            "required_params": ["lp_amount", "minter_address"],
        },
        "dex_stonfi_withdraw_staking": {
            "description": "Withdraw LP tokens from STON.fi farm",
            "protocols": ["stonfi_v2"],
            "required_params": ["position_address"],
        },
        "liquid_staking_stake": {
            "description": "Stake to liquid staking pool",
            "protocols": ["tonstakers", "bemo", "bemo_v2", "hipo", "kton", "stakee"],
            "required_params": ["amount"],
        },
        "liquid_staking_unstake": {
            "description": "Unstake from liquid staking pool",
            "protocols": ["tonstakers", "bemo", "bemo_v2", "hipo", "kton", "stakee"],
            "required_params": ["amount"],
        },
        "lending_deposit": {
            "description": "Deposit to lending protocol",
            "protocols": ["evaa"],
            "required_params": ["amount"],
        },
        "lending_withdraw": {
            "description": "Withdraw from lending protocol",
            "protocols": ["evaa"],
            "required_params": ["amount"],
        },
    }

    return {
        "success": True,
        "yield_types_count": len(yield_types),
        "yield_types": yield_types,
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
  # List pools with server-side filtering
  %(prog)s pools --provider dedust --size 5
  %(prog)s pools --provider stonfi --trusted --size 10
  %(prog)s pools --search "USDT" --size 20
  
  # Client-side filtering (requires loading all pools)
  %(prog)s pools --token USDT --min-tvl 100000
  
  # DEX liquidity (stonfi_v2, dedust, tonco)
  %(prog)s deposit --pool EQA-X... --wallet EQAT... --amount1 1e9 --amount2 1e9
  %(prog)s withdraw --pool EQA-X... --wallet EQAT... --lp-amount 1000000000
  
  # STON.fi farm staking
  %(prog)s stonfi-lock --pool EQA-X... --wallet EQAT... --lp-amount 1e9 --minter EQM...
  %(prog)s stonfi-withdraw --pool EQA-X... --wallet EQAT... --position EQP...
  
  # Liquid staking (tonstakers, bemo, hipo, etc.)
  %(prog)s stake --pool EQCkW... --wallet EQAT... --amount 1000000000
  %(prog)s unstake --pool EQCkW... --wallet EQAT... --amount 1000000000
  
  # Lending (evaa)
  %(prog)s lend-deposit --pool EQC8r... --wallet EQAT... --amount 1000000000
  %(prog)s lend-withdraw --pool EQC8r... --wallet EQAT... --amount 1000000000
  
  # Check position & status
  %(prog)s position --pool EQA-X... --wallet EQAT...
  %(prog)s tx-status --query-id 1697643564986267

Pool list API parameters (server-side):
  --provider / --providers: stonfi, dedust, tonco, tonstakers, etc.
  --trusted: Only trusted pools
  --search: Search by pool address or token tickers
  --size: Results per page (max 100)
  --page: Page number

Operations by pool type:
  DEX pools:           deposit, withdraw (stonfi_v2, dedust, tonco)
  STON.fi farms:       stonfi-lock, stonfi-withdraw
  Liquid staking:      stake, unstake (tonstakers, bemo, bemo_v2, hipo, kton, stakee)
  Lending:             lend-deposit, lend-withdraw (evaa)
""",
    )

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # --- pools ---
    pools_p = subparsers.add_parser("pools", help="List yield pools")
    pools_p.add_argument(
        "--sort",
        "-s",
        default="tvl",
        choices=["apr", "tvl", "volume"],
        help="Sort by (default: tvl)",
    )
    pools_p.add_argument(
        "--min-tvl", type=float, help="Minimum TVL USD (client-side, loads all pools)"
    )
    pools_p.add_argument(
        "--token", "-t", help="Filter by token symbol (client-side, loads all pools)"
    )
    pools_p.add_argument(
        "--provider",
        "-P",
        choices=SUPPORTED_PROVIDERS,
        help="Filter by provider (server-side)",
    )
    pools_p.add_argument(
        "--providers",
        nargs="+",
        choices=SUPPORTED_PROVIDERS,
        help="Filter by multiple providers (server-side)",
    )
    pools_p.add_argument(
        "--all-pools",
        action="store_true",
        help="Include ALL 85K+ pools (default: only 2K trusted pools)",
    )
    pools_p.add_argument(
        "--search", help="Search by pool address or token tickers (server-side)"
    )
    pools_p.add_argument(
        "--size", type=int, default=20, help="Results per page (max 100)"
    )
    pools_p.add_argument(
        "--page", "-p", type=int, default=1, help="Page number (1-indexed)"
    )
    pools_p.add_argument(
        "--all", "-a", action="store_true", help="Fetch all matching pools (paginated)"
    )

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
    rec_p.add_argument(
        "--amount", "-a", type=float, help="Investment amount (info only)"
    )

    # --- position (user position in pool) ---
    pos_p = subparsers.add_parser(
        "position", help="Get user position in a specific pool"
    )
    pos_p.add_argument("--pool", "-p", required=True, help="Pool address")
    pos_p.add_argument("--wallet", "-w", required=True, help="User wallet address")

    # --- tx-status ---
    txs_p = subparsers.add_parser("tx-status", help="Check transaction status")
    txs_p.add_argument(
        "--query-id", "-q", required=True, help="Query ID from deposit/withdraw"
    )

    # --- deposit ---
    dep_p = subparsers.add_parser("deposit", help="Deposit liquidity into DEX pool")
    dep_p.add_argument("--pool", "-p", required=True, help="Pool address")
    dep_p.add_argument("--wallet", "-w", required=True, help="Sender wallet address")
    dep_p.add_argument(
        "--amount1",
        "-a1",
        required=True,
        help="Amount of first token (nanotons/min units)",
    )
    dep_p.add_argument(
        "--amount2",
        "-a2",
        required=True,
        help="Amount of second token (nanotons/min units)",
    )
    dep_p.add_argument("--min-lp", help="Minimum LP tokens to receive (optional)")

    # --- withdraw ---
    with_p = subparsers.add_parser("withdraw", help="Withdraw liquidity from DEX pool")
    with_p.add_argument("--pool", "-p", required=True, help="Pool address")
    with_p.add_argument("--wallet", "-w", required=True, help="User wallet address")
    with_p.add_argument(
        "--lp-amount", "-l", required=True, help="LP tokens to burn (min units)"
    )

    # --- stonfi-lock (STON.fi farm staking) ---
    sl_p = subparsers.add_parser("stonfi-lock", help="Lock LP tokens in STON.fi farm")
    sl_p.add_argument("--pool", "-p", required=True, help="Pool address")
    sl_p.add_argument("--wallet", "-w", required=True, help="User wallet address")
    sl_p.add_argument("--lp-amount", "-l", required=True, help="LP tokens to lock")
    sl_p.add_argument("--minter", "-m", required=True, help="Farm minter address")

    # --- stonfi-withdraw (STON.fi farm unstaking) ---
    sw_p = subparsers.add_parser(
        "stonfi-withdraw", help="Withdraw LP tokens from STON.fi farm"
    )
    sw_p.add_argument("--pool", "-p", required=True, help="Pool address")
    sw_p.add_argument("--wallet", "-w", required=True, help="User wallet address")
    sw_p.add_argument("--position", required=True, help="Farm position address")

    # --- stake (liquid staking) ---
    stake_p = subparsers.add_parser(
        "stake", help="Stake to liquid staking pool (tonstakers, bemo, etc.)"
    )
    stake_p.add_argument("--pool", "-p", required=True, help="Pool address")
    stake_p.add_argument("--wallet", "-w", required=True, help="User wallet address")
    stake_p.add_argument(
        "--amount", "-a", required=True, help="Amount to stake (min units)"
    )

    # --- unstake (liquid staking) ---
    unstake_p = subparsers.add_parser(
        "unstake", help="Unstake from liquid staking pool"
    )
    unstake_p.add_argument("--pool", "-p", required=True, help="Pool address")
    unstake_p.add_argument("--wallet", "-w", required=True, help="User wallet address")
    unstake_p.add_argument(
        "--amount", "-a", required=True, help="Amount to unstake (min units)"
    )

    # --- lend-deposit (lending) ---
    lend_dep_p = subparsers.add_parser(
        "lend-deposit", help="Deposit to lending protocol (evaa)"
    )
    lend_dep_p.add_argument("--pool", "-p", required=True, help="Pool address")
    lend_dep_p.add_argument("--wallet", "-w", required=True, help="User wallet address")
    lend_dep_p.add_argument(
        "--amount", "-a", required=True, help="Amount to deposit (min units)"
    )

    # --- lend-withdraw (lending) ---
    lend_with_p = subparsers.add_parser(
        "lend-withdraw", help="Withdraw from lending protocol"
    )
    lend_with_p.add_argument("--pool", "-p", required=True, help="Pool address")
    lend_with_p.add_argument(
        "--wallet", "-w", required=True, help="User wallet address"
    )
    lend_with_p.add_argument(
        "--amount", "-a", required=True, help="Amount to withdraw (min units)"
    )

    # --- positions (legacy - TonAPI) ---
    positions_p = subparsers.add_parser(
        "positions", help="View LP positions via TonAPI (legacy)"
    )
    positions_p.add_argument("--wallet", "-w", required=True, help="Wallet address")

    # --- providers ---
    subparsers.add_parser("providers", help="List supported providers")

    # --- interact (generic yield interact) ---
    int_p = subparsers.add_parser("interact", help="Generic yield interact endpoint")
    int_p.add_argument("--pool", "-p", required=True, help="Pool address")
    int_p.add_argument("--wallet", "-w", required=True, help="User wallet address")
    int_p.add_argument(
        "--type",
        "-t",
        required=True,
        dest="yield_type",
        help="Yield type resolver (dex_provide_liquidity, liquid_staking_stake, etc.)",
    )
    int_p.add_argument(
        "--params", help='JSON object with operation params: {"amount": "1000000000"}'
    )

    # --- yield-types ---
    subparsers.add_parser("yield-types", help="List supported yield operation types")

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
                provider=args.provider,
                providers=args.providers,
                include_untrusted=getattr(args, "all_pools", False),
                search_text=args.search,
                size=args.size,
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

        elif args.command == "position":
            result = get_user_position(
                pool_address=args.pool,
                user_address=args.wallet,
            )

        elif args.command == "tx-status":
            result = check_tx_status(args.query_id)

        elif args.command == "deposit":
            result = deposit_liquidity(
                pool_address=args.pool,
                user_address=args.wallet,
                asset_1_amount=args.amount1,
                asset_2_amount=args.amount2,
                min_lp_amount=getattr(args, "min_lp", None),
            )

        elif args.command == "withdraw":
            result = withdraw_liquidity(
                pool_address=args.pool,
                user_address=args.wallet,
                lp_amount=args.lp_amount,
            )

        elif args.command == "stonfi-lock":
            result = stonfi_lock_staking(
                pool_address=args.pool,
                user_address=args.wallet,
                lp_amount=args.lp_amount,
                minter_address=args.minter,
            )

        elif args.command == "stonfi-withdraw":
            result = stonfi_withdraw_staking(
                pool_address=args.pool,
                user_address=args.wallet,
                position_address=args.position,
            )

        elif args.command == "stake":
            result = stake_liquidity(
                pool_address=args.pool,
                user_address=args.wallet,
                amount=args.amount,
            )

        elif args.command == "unstake":
            result = unstake_liquidity(
                pool_address=args.pool,
                user_address=args.wallet,
                amount=args.amount,
            )

        elif args.command == "lend-deposit":
            result = lending_deposit(
                pool_address=args.pool,
                user_address=args.wallet,
                amount=args.amount,
            )

        elif args.command == "lend-withdraw":
            result = lending_withdraw(
                pool_address=args.pool,
                user_address=args.wallet,
                amount=args.amount,
            )

        elif args.command == "positions":
            result = get_positions(args.wallet)

        elif args.command == "providers":
            result = {
                "success": True,
                "count": len(SUPPORTED_PROVIDERS),
                "providers": SUPPORTED_PROVIDERS,
            }

        elif args.command == "interact":
            # Парсим params если указаны
            params = None
            if hasattr(args, "params") and args.params:
                try:
                    params = json.loads(args.params)
                except json.JSONDecodeError as e:
                    result = {
                        "success": False,
                        "error": f"Invalid JSON in --params: {e}",
                    }
                    print(json.dumps(result, indent=2, ensure_ascii=False))
                    return sys.exit(1)

            result = yield_interact(
                pool_address=args.pool,
                user_address=args.wallet,
                yield_type_resolver=args.yield_type,
                params=params,
            )

        elif args.command == "yield-types":
            result = get_yield_types()

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
            return sys.exit(1)

    except Exception as e:
        print(json.dumps({"error": str(e)}, indent=2))
        return sys.exit(1)


if __name__ == "__main__":
    main()
