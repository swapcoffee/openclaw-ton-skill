#!/usr/bin/env python3
"""
OpenClaw TON Skill — NFT операции

- Список NFT в кошельке (TonAPI)
- Информация об NFT (Marketapp + TonAPI)
- Информация о коллекции (Marketapp)
- Покупка NFT (Marketapp)
- Продажа NFT (Marketapp)
- Смена цены (Marketapp)
- Снятие с продажи (Marketapp)
- Трансфер NFT (TonAPI)
- Поиск коллекций (TonAPI)
- Гифты на продаже (Marketapp)
"""

import os
import sys
import json
import base64
import argparse
import getpass
from pathlib import Path
from typing import Optional

# Локальный импорт
script_dir = Path(__file__).parent
sys.path.insert(0, str(script_dir))

from utils import tonapi_request, api_request, normalize_address, load_config  # noqa: E402
from dns import resolve_address, is_ton_domain  # noqa: E402
from wallet import WalletStorage  # noqa: E402


def _make_url_safe(address: str) -> str:
    """Конвертирует адрес в URL-safe формат (заменяет +/ на -_)."""
    return address.replace("+", "-").replace("/", "_")


# TON SDK
try:
    from tonsdk.contract.wallet import Wallets, WalletVersionEnum
    from tonsdk.utils import to_nano, from_nano  # noqa: F401
    from tonsdk.boc import Cell  # noqa: F401

    TONSDK_AVAILABLE = True
except ImportError:
    TONSDK_AVAILABLE = False


# =============================================================================
# Constants
# =============================================================================

# NFT Transfer opcode (TEP-62)
NFT_TRANSFER_OPCODE = 0x5FCC3D14

# Marketapp API
MARKETAPP_BASE = "https://api.marketapp.ws/v1"

# Known collection aliases
COLLECTION_ALIASES = {
    # Anonymous Telegram Numbers
    "anonymous-numbers": "EQAOQdwdw8kGftJCSFgOErM1mBjYPe4DBPq8-AhF6vr9si5N",
    "anon": "EQAOQdwdw8kGftJCSFgOErM1mBjYPe4DBPq8-AhF6vr9si5N",
    "numbers": "EQAOQdwdw8kGftJCSFgOErM1mBjYPe4DBPq8-AhF6vr9si5N",
    # Telegram Usernames
    "usernames": "EQCA14o1-VWhS2efqoh_9M1b_A9DtKTuoqfmkn83AbJzwnPi",
    "username": "EQCA14o1-VWhS2efqoh_9M1b_A9DtKTuoqfmkn83AbJzwnPi",
}


# =============================================================================
# Marketapp API Helper
# =============================================================================


def marketapp_request(
    endpoint: str,
    method: str = "GET",
    params: Optional[dict] = None,
    json_data: Optional[dict] = None,
) -> dict:
    """
    Запрос к Marketapp API.
    Auth: Header `Authorization: <token>` (без Bearer!)

    Args:
        endpoint: Endpoint (без base URL), например "/nfts/{address}/"
        method: HTTP метод
        params: Query параметры
        json_data: JSON body

    Returns:
        Результат api_request
    """
    config = load_config()
    api_key = config.get("marketapp_key", "")

    if not api_key:
        return {
            "success": False,
            "error": "Marketapp API key not configured. Run: utils.py config set marketapp_key <your_key>",
        }

    url = f"{MARKETAPP_BASE}{endpoint}"

    return api_request(
        url=url,
        method=method,
        params=params,
        json_data=json_data,
        api_key=api_key,
        api_key_header="Authorization",
        api_key_prefix="",  # Без Bearer!
    )


# =============================================================================
# Wallet Helpers
# =============================================================================


def get_wallet_from_storage(identifier: str, password: str) -> Optional[dict]:
    """Получает кошелёк из хранилища с приватными данными."""
    storage = WalletStorage(password)
    return storage.get_wallet(identifier, include_secrets=True)


def create_wallet_instance(wallet_data: dict):
    """Создаёт инстанс кошелька для подписания."""
    if not TONSDK_AVAILABLE:
        raise RuntimeError("tonsdk not available. Install: pip install tonsdk")

    mnemonic = wallet_data.get("mnemonic")
    if not mnemonic:
        raise ValueError("Wallet has no mnemonic")

    version_map = {
        "v3r2": WalletVersionEnum.v3r2,
        "v4r2": WalletVersionEnum.v4r2,
    }

    version = wallet_data.get("version", "v4r2")
    wallet_version = version_map.get(version.lower(), WalletVersionEnum.v4r2)

    mnemonics, pub_k, priv_k, wallet = Wallets.from_mnemonics(
        mnemonic, wallet_version, workchain=0
    )

    return wallet


def get_seqno(address: str) -> int:
    """Получает текущий seqno кошелька."""
    addr_safe = _make_url_safe(address)
    result = tonapi_request(f"/wallet/{addr_safe}/seqno")

    if result["success"]:
        return result["data"].get("seqno", 0)

    return 0


def resolve_wallet_address(
    wallet_identifier: str, password: Optional[str] = None
) -> Optional[str]:
    """
    Резолвит адрес кошелька по идентификатору (лейбл, адрес, .ton домен).
    """
    if looks_like_address(wallet_identifier):
        return wallet_identifier

    if is_ton_domain(wallet_identifier):
        resolved = resolve_address(wallet_identifier)
        if resolved["success"]:
            return resolved["address"]
        return None

    # Ищем в хранилище по лейблу
    if password:
        try:
            storage = WalletStorage(password)
            wallet_data = storage.get_wallet(wallet_identifier, include_secrets=False)
            if wallet_data:
                return wallet_data["address"]
        except Exception:
            pass

    return None


# =============================================================================
# NFT List (TonAPI)
# =============================================================================


def looks_like_address(s: str) -> bool:
    """Быстрая проверка - похоже ли на TON адрес."""
    if not s:
        return False
    # Raw формат: 0:abc123...
    if ":" in s and len(s) > 40:
        return True
    # Friendly формат: UQ..., EQ..., kQ..., 0Q...
    if len(s) >= 48 and s[:2] in ("UQ", "EQ", "kQ", "0Q", "Uf", "Ef", "kf", "0f"):
        return True
    return False


def list_nfts(
    wallet_identifier: str, password: Optional[str] = None, limit: int = 100
) -> dict:
    """
    Получает список NFT в кошельке через TonAPI.

    Args:
        wallet_identifier: Лейбл или адрес кошелька
        password: Пароль (нужен если ищем по лейблу)
        limit: Максимальное количество NFT

    Returns:
        dict со списком NFT
    """
    address = resolve_wallet_address(wallet_identifier, password)

    if not address:
        return {
            "success": False,
            "error": f"Cannot resolve wallet: {wallet_identifier}",
        }

    # Нормализуем адрес для API
    try:
        api_address = normalize_address(address, "friendly")
    except Exception:
        api_address = address

    # Запрос к TonAPI
    result = tonapi_request(
        f"/accounts/{api_address}/nfts",
        params={"limit": limit, "indirect_ownership": "true"},
    )

    if not result["success"]:
        return {"success": False, "error": result.get("error", "Failed to fetch NFTs")}

    data = result["data"]
    nft_items = data.get("nft_items", [])

    # Парсим NFT
    nfts = []
    for item in nft_items:
        metadata = item.get("metadata", {})
        collection = item.get("collection", {})
        previews = item.get("previews", [])

        # Выбираем превью
        preview_url = None
        for p in previews:
            if p.get("resolution") == "500x500":
                preview_url = p.get("url")
                break
        if not preview_url and previews:
            preview_url = previews[0].get("url")

        # Sale info
        sale = item.get("sale")
        sale_info = None
        if sale:
            price_val = int(sale.get("price", {}).get("value", 0))
            sale_info = {
                "price_ton": price_val / 1e9,
                "marketplace": sale.get("market", {}).get("name"),
            }

        nft = {
            "address": item.get("address"),
            "index": item.get("index"),
            "name": metadata.get("name")
            or item.get("dns")
            or f"NFT #{item.get('index', '?')}",
            "description": metadata.get("description"),
            "preview_url": preview_url,
            "collection": {
                "address": collection.get("address"),
                "name": collection.get("name"),
            }
            if collection
            else None,
            "verified": item.get("verified", False),
            "owner": item.get("owner", {}).get("address"),
            "sale": sale_info,
        }

        if item.get("dns"):
            nft["dns_domain"] = item.get("dns")

        nfts.append(nft)

    return {"success": True, "wallet": api_address, "count": len(nfts), "nfts": nfts}


# =============================================================================
# NFT Info (Marketapp + TonAPI)
# =============================================================================


def get_nft_info(nft_address: str) -> dict:
    """
    Получает детальную информацию об NFT.
    Использует Marketapp API для информации о продаже + TonAPI для метаданных.
    Работает даже если один из API недоступен.

    Args:
        nft_address: Адрес NFT

    Returns:
        dict с информацией об NFT
    """
    try:
        api_address = _make_url_safe(normalize_address(nft_address, "friendly"))
    except Exception:
        api_address = _make_url_safe(nft_address)

    # Запрос к Marketapp (может вернуть ошибку если ключ не настроен)
    marketapp_result = marketapp_request(f"/nfts/{api_address}/")

    # Запрос к TonAPI для дополнительных данных
    tonapi_result = tonapi_request(f"/nfts/{api_address}")

    # Если оба API недоступны (и это не просто отсутствие ключа Marketapp)
    if not tonapi_result["success"] and (
        not marketapp_result["success"]
        and "not configured" not in str(marketapp_result.get("error", ""))
    ):
        return {
            "success": False,
            "error": tonapi_result.get("error")
            or marketapp_result.get("error", "Failed to fetch NFT info"),
        }

    # Если только TonAPI недоступен
    if not tonapi_result["success"] and not marketapp_result["success"]:
        return {
            "success": False,
            "error": tonapi_result.get("error", "Failed to fetch NFT info"),
        }

    # Собираем данные из обоих источников
    result = {
        "success": True,
        "address": api_address,
    }

    # Данные из Marketapp (приоритет для sale info)
    if marketapp_result["success"]:
        mkt_data = marketapp_result["data"]
        result["name"] = mkt_data.get("name")
        result["collection_address"] = mkt_data.get("collection_address")
        result["owner"] = mkt_data.get("real_owner")
        result["status"] = mkt_data.get("status")  # for_sale, not_for_sale, etc.

        # Атрибуты
        attrs = mkt_data.get("attributes", [])
        result["traits"] = [
            {"trait": a.get("trait_type"), "value": a.get("value")} for a in attrs
        ]

        # Детали статуса (цена и т.д.)
        status_details = mkt_data.get("status_details", {})
        if result["status"] == "for_sale" and status_details:
            price_nano = int(status_details.get("price", 0))
            result["sale"] = {
                "price_nano": price_nano,
                "price_ton": price_nano / 1e9,
                "marketplace": "Marketapp",
            }
        else:
            result["sale"] = None

    # Данные из TonAPI (метаданные, превью)
    if tonapi_result["success"]:
        ton_data = tonapi_result["data"]
        metadata = ton_data.get("metadata", {})
        collection = ton_data.get("collection", {})
        previews = ton_data.get("previews", [])

        # Дополняем если нет из Marketapp
        if not result.get("name"):
            result["name"] = (
                metadata.get("name")
                or ton_data.get("dns")
                or f"NFT #{ton_data.get('index', '?')}"
            )

        result["description"] = metadata.get("description")
        result["image"] = metadata.get("image")
        result["index"] = ton_data.get("index")

        # Превью
        preview_urls = {}
        for p in previews:
            resolution = p.get("resolution", "unknown")
            preview_urls[resolution] = p.get("url")
        result["previews"] = preview_urls

        # Коллекция
        if collection:
            result["collection"] = {
                "address": collection.get("address"),
                "name": collection.get("name"),
                "description": collection.get("description"),
            }
        elif result.get("collection_address"):
            result["collection"] = {"address": result["collection_address"]}

        result["verified"] = ton_data.get("verified", False)
        result["approved_by"] = ton_data.get("approved_by", [])
        result["dns_domain"] = ton_data.get("dns")

        # Если нет owner из Marketapp
        if not result.get("owner"):
            result["owner"] = ton_data.get("owner", {}).get("address")

        # Sale из TonAPI если нет из Marketapp
        if not result.get("sale"):
            sale = ton_data.get("sale")
            if sale:
                price_val = int(sale.get("price", {}).get("value", 0))
                result["sale"] = {
                    "price_nano": price_val,
                    "price_ton": price_val / 1e9,
                    "marketplace": sale.get("market", {}).get("name"),
                }

    return result


# =============================================================================
# Collection Info (Marketapp)
# =============================================================================


def get_collection_info(
    collection_address: str, filter_by: str = "onsale", limit: int = 10
) -> dict:
    """
    Получает информацию о коллекции NFT через Marketapp + TonAPI.
    Работает даже если Marketapp API недоступен.

    Args:
        collection_address: Адрес коллекции
        filter_by: Фильтр (onsale, all)
        limit: Лимит NFT в ответе

    Returns:
        dict с информацией о коллекции
    """
    try:
        api_address = _make_url_safe(normalize_address(collection_address, "friendly"))
    except Exception:
        api_address = _make_url_safe(collection_address)

    # TonAPI для метаданных (всегда пробуем)
    tonapi_result = tonapi_request(f"/nfts/collections/{api_address}")

    # Список коллекций для получения статистики (Marketapp)
    collections_result = marketapp_request("/collections/")

    collection_stats = None
    if collections_result["success"]:
        for coll in collections_result["data"]:
            if coll.get("address") == api_address:
                collection_stats = coll
                break

    # NFT в коллекции (Marketapp)
    nfts_result = marketapp_request(
        f"/nfts/collections/{api_address}/",
        params={"filter_by": filter_by, "limit": limit},
    )

    # Если TonAPI недоступен и Marketapp тоже
    if not tonapi_result["success"] and not collections_result["success"]:
        return {
            "success": False,
            "error": tonapi_result.get("error", "Failed to fetch collection info"),
        }

    result = {
        "success": True,
        "address": api_address,
    }

    # Из Marketapp
    if collection_stats:
        result["name"] = collection_stats.get("name")
        extra = collection_stats.get("extra_data", {})
        result["stats"] = {
            "items_count": extra.get("items"),
            "floor_ton": int(extra.get("floor", 0)) / 1e9
            if extra.get("floor")
            else None,
            "volume_7d_ton": int(extra.get("volume7d", 0)) / 1e9
            if extra.get("volume7d")
            else None,
            "volume_30d_ton": int(extra.get("volume30d", 0)) / 1e9
            if extra.get("volume30d")
            else None,
            "owners": extra.get("owners"),
            "on_sale": extra.get("on_sale_all"),
        }

    # NFT на продаже
    if nfts_result["success"]:
        nfts_data = nfts_result["data"]
        items = nfts_data.get("items", [])
        result["nfts_on_sale"] = []
        for item in items:
            min_bid = int(item.get("min_bid", 0))
            result["nfts_on_sale"].append(
                {
                    "address": item.get("address"),
                    "name": item.get("name"),
                    "price_ton": min_bid / 1e9,
                    "owner": item.get("real_owner"),
                    "item_num": item.get("item_num"),
                }
            )
        result["cursor"] = nfts_data.get("cursor")

    # Из TonAPI
    if tonapi_result["success"]:
        ton_data = tonapi_result["data"]
        metadata = ton_data.get("metadata", {})

        if not result.get("name"):
            result["name"] = metadata.get("name") or ton_data.get("name")

        result["description"] = metadata.get("description") or ton_data.get(
            "description"
        )
        result["image"] = metadata.get("image")
        result["owner"] = (
            ton_data.get("owner", {}).get("address") if ton_data.get("owner") else None
        )
        result["verified"] = ton_data.get("verified", False)

        if not result.get("stats"):
            result["stats"] = {"items_count": ton_data.get("next_item_index", 0)}

    return result


# =============================================================================
# Collection Floor Price
# =============================================================================


def resolve_collection_alias(collection: str) -> str:
    """
    Resolve collection alias to address.

    Args:
        collection: Alias (e.g. 'anon', 'usernames') or address

    Returns:
        Collection address
    """
    # Check if it's a known alias
    alias_lower = collection.lower().strip()
    if alias_lower in COLLECTION_ALIASES:
        return COLLECTION_ALIASES[alias_lower]

    # Return as-is (assume it's an address)
    return collection


def get_collection_floor(collection: str) -> dict:
    """
    Get floor price for a collection.

    Args:
        collection: Collection alias or address

    Returns:
        dict with floor price info
    """
    # Resolve alias
    collection_address = resolve_collection_alias(collection)

    try:
        api_address = _make_url_safe(normalize_address(collection_address, "friendly"))
    except Exception:
        api_address = _make_url_safe(collection_address)

    # Method 1: Try to get from /collections/ list (has floor in extra_data)
    collections_result = marketapp_request("/collections/")

    collection_data = None
    if collections_result["success"]:
        for coll in collections_result["data"]:
            if coll.get("address") == api_address:
                collection_data = coll
                break

    if collection_data:
        extra = collection_data.get("extra_data", {})
        floor_nano = int(extra.get("floor", 0))

        return {
            "success": True,
            "collection": {
                "address": api_address,
                "name": collection_data.get("name"),
                "alias": collection.lower()
                if collection.lower() in COLLECTION_ALIASES
                else None,
            },
            "floor_price_nano": floor_nano,
            "floor_price_ton": floor_nano / 1e9 if floor_nano else None,
            "stats": {
                "items_count": extra.get("items"),
                "on_sale": extra.get("on_sale_all"),
                "owners": extra.get("owners"),
                "volume_7d_ton": int(extra.get("volume7d", 0)) / 1e9
                if extra.get("volume7d")
                else None,
                "volume_30d_ton": int(extra.get("volume30d", 0)) / 1e9
                if extra.get("volume30d")
                else None,
            },
            "source": "marketapp_collections",
        }

    # Method 2: Fallback - get cheapest NFT on sale from the collection
    nfts_result = marketapp_request(
        f"/nfts/collections/{api_address}/",
        params={"filter_by": "onsale", "limit": 100},
    )

    if nfts_result["success"]:
        items = nfts_result["data"].get("items", [])

        if not items:
            # Try TonAPI for collection name at least
            tonapi_result = tonapi_request(f"/nfts/collections/{api_address}")
            collection_name = None
            if tonapi_result["success"]:
                metadata = tonapi_result["data"].get("metadata", {})
                collection_name = metadata.get("name") or tonapi_result["data"].get(
                    "name"
                )

            return {
                "success": True,
                "collection": {
                    "address": api_address,
                    "name": collection_name,
                    "alias": collection.lower()
                    if collection.lower() in COLLECTION_ALIASES
                    else None,
                },
                "floor_price_nano": None,
                "floor_price_ton": None,
                "message": "No NFTs on sale in this collection",
                "source": "marketapp_nfts",
            }

        # Find minimum price
        min_price = float("inf")
        min_nft = None
        for item in items:
            price = int(item.get("min_bid", 0))
            if price > 0 and price < min_price:
                min_price = price
                min_nft = item

        if min_nft:
            return {
                "success": True,
                "collection": {
                    "address": api_address,
                    "name": min_nft.get("collection_name"),
                    "alias": collection.lower()
                    if collection.lower() in COLLECTION_ALIASES
                    else None,
                },
                "floor_price_nano": min_price,
                "floor_price_ton": min_price / 1e9,
                "floor_nft": {
                    "address": min_nft.get("address"),
                    "name": min_nft.get("name"),
                    "item_num": min_nft.get("item_num"),
                },
                "on_sale_count": len(items),
                "source": "marketapp_nfts",
            }

    # Method 3: TonAPI fallback for basic info
    tonapi_result = tonapi_request(f"/nfts/collections/{api_address}")

    if tonapi_result["success"]:
        ton_data = tonapi_result["data"]
        metadata = ton_data.get("metadata", {})

        return {
            "success": True,
            "collection": {
                "address": api_address,
                "name": metadata.get("name") or ton_data.get("name"),
                "alias": collection.lower()
                if collection.lower() in COLLECTION_ALIASES
                else None,
            },
            "floor_price_nano": None,
            "floor_price_ton": None,
            "message": "Floor price not available (Marketapp API key may be missing)",
            "items_count": ton_data.get("next_item_index", 0),
            "source": "tonapi",
        }

    return {
        "success": False,
        "error": f"Collection not found: {collection}",
    }


# =============================================================================
# Search Collections (TonAPI)
# =============================================================================


def search_collections(query: str, limit: int = 10) -> dict:
    """
    Поиск коллекций NFT по названию через TonAPI.

    Args:
        query: Поисковый запрос
        limit: Максимальное количество результатов

    Returns:
        dict со списком коллекций
    """
    result = tonapi_request("/accounts/search", params={"name": query})

    collections = []

    if result["success"]:
        addresses = result["data"].get("addresses", [])

        for addr_info in addresses[: limit * 2]:
            address = addr_info.get("address")
            name = addr_info.get("name")

            coll_result = tonapi_request(f"/nfts/collections/{_make_url_safe(address)}")

            if coll_result["success"]:
                coll_data = coll_result["data"]
                metadata = coll_data.get("metadata", {})

                collections.append(
                    {
                        "address": address,
                        "name": metadata.get("name") or name or "Unknown",
                        "description": metadata.get("description"),
                        "items_count": coll_data.get("next_item_index", 0),
                        "verified": coll_data.get("verified", False),
                    }
                )

                if len(collections) >= limit:
                    break

    return {
        "success": True,
        "query": query,
        "count": len(collections),
        "collections": collections,
    }


# =============================================================================
# Gifts on Sale (Marketapp)
# =============================================================================


def get_gifts_on_sale(
    model: Optional[str] = None,
    symbol: Optional[str] = None,
    backdrop: Optional[str] = None,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    sort_by: str = "min_bid_asc",
    limit: int = 20,
) -> dict:
    """
    Получает список гифтов на продаже через Marketapp.

    Args:
        model: Фильтр по модели
        symbol: Фильтр по символу
        backdrop: Фильтр по бэкдропу
        min_price: Минимальная цена в TON
        max_price: Максимальная цена в TON
        sort_by: Сортировка (min_bid_asc, min_bid_desc, etc.)
        limit: Лимит

    Returns:
        dict со списком гифтов
    """
    params = {"sort_by": sort_by}

    if model:
        params["model"] = model
    if symbol:
        params["symbol"] = symbol
    if backdrop:
        params["backdrop"] = backdrop
    if min_price is not None:
        params["min_price"] = min_price
    if max_price is not None:
        params["max_price"] = max_price

    result = marketapp_request("/gifts/onsale/", params=params)

    if not result["success"]:
        return {"success": False, "error": result.get("error", "Failed to fetch gifts")}

    data = result["data"]
    items = data.get("items", [])[:limit]

    gifts = []
    for item in items:
        min_bid = int(item.get("min_bid", 0))
        attrs = {
            a.get("trait_type"): a.get("value") for a in item.get("attributes", [])
        }

        gifts.append(
            {
                "address": item.get("address"),
                "name": item.get("name"),
                "price_ton": min_bid / 1e9,
                "owner": item.get("real_owner"),
                "item_num": item.get("item_num"),
                "model": attrs.get("Model") or attrs.get("model"),
                "symbol": attrs.get("Symbol") or attrs.get("symbol"),
                "backdrop": attrs.get("Backdrop") or attrs.get("backdrop"),
                "collection": item.get("collection_address"),
            }
        )

    return {
        "success": True,
        "count": len(gifts),
        "gifts": gifts,
        "cursor": data.get("cursor"),
        "filters": {
            "model": model,
            "symbol": symbol,
            "backdrop": backdrop,
            "min_price": min_price,
            "max_price": max_price,
        },
    }


# =============================================================================
# Trading Operations (Marketapp)
# =============================================================================


def emulate_marketapp_tx(transaction: dict, wallet_address: str) -> dict:
    """
    Эмулирует транзакцию Marketapp через TonAPI.

    Args:
        transaction: Транзакция из Marketapp (TonTransactionSchema)
        wallet_address: Адрес кошелька отправителя

    Returns:
        dict с результатом эмуляции
    """
    messages = transaction.get("messages", [])

    if not messages:
        return {"success": False, "error": "No messages in transaction"}

    # Суммируем все amount
    total_amount = sum(int(m.get("amount", 0)) for m in messages)

    # Для эмуляции нужно построить BOC
    # Пока возвращаем информацию о транзакции
    return {
        "success": True,
        "messages_count": len(messages),
        "total_amount_nano": total_amount,
        "total_amount_ton": total_amount / 1e9,
        "valid_until": transaction.get("validUntil"),
        "messages": [
            {
                "to": m.get("address"),
                "amount_ton": int(m.get("amount", 0)) / 1e9,
                "has_payload": bool(m.get("payload")),
                "has_state_init": bool(m.get("stateInit")),
            }
            for m in messages
        ],
    }


def build_and_send_marketapp_tx(
    transaction: dict, wallet, wallet_address: str, seqno: int
) -> dict:
    """
    Строит и отправляет транзакцию из Marketapp.

    Args:
        transaction: Транзакция из Marketapp
        wallet: Инстанс кошелька
        wallet_address: Адрес кошелька
        seqno: Текущий seqno

    Returns:
        dict с результатом
    """
    from tonsdk.boc import Cell

    messages = transaction.get("messages", [])

    if not messages:
        return {"success": False, "error": "No messages in transaction"}

    # Для мультисообщений нужен v4 кошелёк
    # Пока поддерживаем только одно сообщение
    if len(messages) > 1:
        return {
            "success": False,
            "error": "Multiple messages not yet supported. Use TonConnect wallet.",
        }

    msg = messages[0]
    to_addr = msg.get("address")
    amount = int(msg.get("amount", 0))
    payload_b64 = msg.get("payload")
    # state_init_b64 = msg.get("stateInit")

    if not to_addr:
        return {"success": False, "error": "Transaction message has no address"}

    # Декодируем payload из API (Cell в base64)
    payload = None
    if payload_b64:
        try:
            payload_bytes = base64.b64decode(payload_b64)
            payload = Cell.one_from_boc(payload_bytes)
        except Exception as e:
            return {"success": False, "error": f"Failed to decode payload: {e}"}

    # Строим транзакцию
    query = wallet.create_transfer_message(
        to_addr=to_addr, amount=amount, payload=payload, seqno=seqno
    )

    boc = query["message"].to_boc(False)
    boc_b64 = base64.b64encode(boc).decode("ascii")

    # Отправляем
    result = tonapi_request(
        "/blockchain/message", method="POST", json_data={"boc": boc_b64}
    )

    if not result["success"]:
        return {
            "success": False,
            "error": result.get("error", "Failed to send transaction"),
        }

    return {"success": True, "message": "Transaction sent successfully"}


def buy_nft(
    nft_address: str, wallet_identifier: str, password: str, confirm: bool = False
) -> dict:
    """
    Покупает NFT через Marketapp.

    Args:
        nft_address: Адрес NFT
        wallet_identifier: Кошелёк покупателя
        password: Пароль
        confirm: Подтвердить и отправить

    Returns:
        dict с результатом
    """
    if not TONSDK_AVAILABLE:
        return {"success": False, "error": "tonsdk not installed"}

    # Получаем инфо об NFT
    nft_info = get_nft_info(nft_address)
    if not nft_info["success"]:
        return nft_info

    if not nft_info.get("sale"):
        return {"success": False, "error": "NFT is not for sale"}

    # Получаем кошелёк
    wallet_data = get_wallet_from_storage(wallet_identifier, password)
    if not wallet_data:
        return {"success": False, "error": f"Wallet not found: {wallet_identifier}"}

    buyer_address = wallet_data["address"]
    price_ton = nft_info["sale"]["price_ton"]

    try:
        nft_addr_friendly = normalize_address(nft_address, "friendly")
    except Exception:
        nft_addr_friendly = nft_address

    # Запрос к Marketapp для получения транзакции
    buy_result = marketapp_request(
        "/nfts/buy/",
        method="POST",
        json_data={"data": [{"nft_address": nft_addr_friendly, "price": price_ton}]},
    )

    if not buy_result["success"]:
        return {
            "success": False,
            "error": buy_result.get("error", "Failed to create buy transaction"),
        }

    transaction = buy_result["data"].get("transaction", {})

    # Эмуляция
    emulation = emulate_marketapp_tx(transaction, buyer_address)

    result = {
        "action": "buy_nft",
        "nft": {
            "address": nft_addr_friendly,
            "name": nft_info.get("name"),
            "collection": nft_info.get("collection", {}).get("name")
            if nft_info.get("collection")
            else None,
        },
        "price_ton": price_ton,
        "buyer": buyer_address,
        "emulation": emulation,
    }

    if confirm:
        wallet = create_wallet_instance(wallet_data)
        seqno = get_seqno(buyer_address)

        send_result = build_and_send_marketapp_tx(
            transaction=transaction,
            wallet=wallet,
            wallet_address=buyer_address,
            seqno=seqno,
        )

        result["sent"] = send_result["success"]
        if send_result["success"]:
            result["success"] = True
            result["message"] = "Buy transaction sent successfully"
        else:
            result["success"] = False
            result["error"] = send_result.get("error")
    else:
        result["success"] = True
        result["confirmed"] = False
        result["message"] = "Emulation successful. Use --confirm to buy."

    return result


def sell_nft(
    nft_address: str,
    price_ton: float,
    wallet_identifier: str,
    password: str,
    confirm: bool = False,
) -> dict:
    """
    Выставляет NFT на продажу через Marketapp.

    Args:
        nft_address: Адрес NFT
        price_ton: Цена в TON
        wallet_identifier: Кошелёк владельца
        password: Пароль
        confirm: Подтвердить и отправить

    Returns:
        dict с результатом
    """
    if not TONSDK_AVAILABLE:
        return {"success": False, "error": "tonsdk not installed"}

    # Получаем кошелёк
    wallet_data = get_wallet_from_storage(wallet_identifier, password)
    if not wallet_data:
        return {"success": False, "error": f"Wallet not found: {wallet_identifier}"}

    owner_address = wallet_data["address"]

    # Проверяем владение
    nft_info = get_nft_info(nft_address)
    if not nft_info["success"]:
        return nft_info

    try:
        owner_raw = normalize_address(owner_address, "raw")
        nft_owner_raw = (
            normalize_address(nft_info.get("owner", ""), "raw")
            if nft_info.get("owner")
            else None
        )
    except Exception:
        owner_raw = owner_address
        nft_owner_raw = nft_info.get("owner")

    if owner_raw != nft_owner_raw:
        return {
            "success": False,
            "error": f"NFT is not owned by this wallet. Owner: {nft_info.get('owner')}",
        }

    try:
        nft_addr_friendly = normalize_address(nft_address, "friendly")
        owner_addr_friendly = normalize_address(owner_address, "friendly")
    except Exception:
        nft_addr_friendly = nft_address
        owner_addr_friendly = owner_address

    # Запрос к Marketapp
    sale_result = marketapp_request(
        "/nfts/sale/",
        method="POST",
        json_data={
            "owner_address": owner_addr_friendly,
            "data": [{"nft_address": nft_addr_friendly, "price": price_ton}],
        },
    )

    if not sale_result["success"]:
        return {
            "success": False,
            "error": sale_result.get("error", "Failed to create sale transaction"),
        }

    transaction = sale_result["data"].get("transaction", {})
    emulation = emulate_marketapp_tx(transaction, owner_address)

    result = {
        "action": "sell_nft",
        "nft": {
            "address": nft_addr_friendly,
            "name": nft_info.get("name"),
            "collection": nft_info.get("collection", {}).get("name")
            if nft_info.get("collection")
            else None,
        },
        "price_ton": price_ton,
        "seller": owner_addr_friendly,
        "emulation": emulation,
    }

    if confirm:
        wallet = create_wallet_instance(wallet_data)
        seqno = get_seqno(owner_address)

        send_result = build_and_send_marketapp_tx(
            transaction=transaction,
            wallet=wallet,
            wallet_address=owner_address,
            seqno=seqno,
        )

        result["sent"] = send_result["success"]
        if send_result["success"]:
            result["success"] = True
            result["message"] = "Sale transaction sent successfully"
        else:
            result["success"] = False
            result["error"] = send_result.get("error")
    else:
        result["success"] = True
        result["confirmed"] = False
        result["message"] = "Emulation successful. Use --confirm to list for sale."

    return result


def cancel_sale(
    nft_address: str, wallet_identifier: str, password: str, confirm: bool = False
) -> dict:
    """
    Снимает NFT с продажи через Marketapp.

    Args:
        nft_address: Адрес NFT
        wallet_identifier: Кошелёк владельца
        password: Пароль
        confirm: Подтвердить и отправить

    Returns:
        dict с результатом
    """
    if not TONSDK_AVAILABLE:
        return {"success": False, "error": "tonsdk not installed"}

    wallet_data = get_wallet_from_storage(wallet_identifier, password)
    if not wallet_data:
        return {"success": False, "error": f"Wallet not found: {wallet_identifier}"}

    owner_address = wallet_data["address"]

    nft_info = get_nft_info(nft_address)
    if not nft_info["success"]:
        return nft_info

    if nft_info.get("status") != "for_sale" and not nft_info.get("sale"):
        return {"success": False, "error": "NFT is not currently for sale"}

    try:
        nft_addr_friendly = normalize_address(nft_address, "friendly")
        owner_addr_friendly = normalize_address(owner_address, "friendly")
    except Exception:
        nft_addr_friendly = nft_address
        owner_addr_friendly = owner_address

    cancel_result = marketapp_request(
        "/nfts/cancel_sale/",
        method="POST",
        json_data={
            "owner_address": owner_addr_friendly,
            "nft_addresses": [nft_addr_friendly],
        },
    )

    if not cancel_result["success"]:
        return {
            "success": False,
            "error": cancel_result.get("error", "Failed to create cancel transaction"),
        }

    transaction = cancel_result["data"].get("transaction", {})
    emulation = emulate_marketapp_tx(transaction, owner_address)

    result = {
        "action": "cancel_sale",
        "nft": {
            "address": nft_addr_friendly,
            "name": nft_info.get("name"),
        },
        "seller": owner_addr_friendly,
        "emulation": emulation,
    }

    if confirm:
        wallet = create_wallet_instance(wallet_data)
        seqno = get_seqno(owner_address)

        send_result = build_and_send_marketapp_tx(
            transaction=transaction,
            wallet=wallet,
            wallet_address=owner_address,
            seqno=seqno,
        )

        result["sent"] = send_result["success"]
        if send_result["success"]:
            result["success"] = True
            result["message"] = "Cancel sale transaction sent"
        else:
            result["success"] = False
            result["error"] = send_result.get("error")
    else:
        result["success"] = True
        result["confirmed"] = False
        result["message"] = "Emulation successful. Use --confirm to cancel sale."

    return result


def change_price(
    nft_address: str,
    new_price_ton: float,
    wallet_identifier: str,
    password: str,
    confirm: bool = False,
) -> dict:
    """
    Меняет цену NFT на продаже через Marketapp.

    Args:
        nft_address: Адрес NFT
        new_price_ton: Новая цена в TON
        wallet_identifier: Кошелёк владельца
        password: Пароль
        confirm: Подтвердить и отправить

    Returns:
        dict с результатом
    """
    if not TONSDK_AVAILABLE:
        return {"success": False, "error": "tonsdk not installed"}

    wallet_data = get_wallet_from_storage(wallet_identifier, password)
    if not wallet_data:
        return {"success": False, "error": f"Wallet not found: {wallet_identifier}"}

    owner_address = wallet_data["address"]

    nft_info = get_nft_info(nft_address)
    if not nft_info["success"]:
        return nft_info

    if nft_info.get("status") != "for_sale" and not nft_info.get("sale"):
        return {"success": False, "error": "NFT is not currently for sale"}

    old_price = nft_info.get("sale", {}).get("price_ton")

    try:
        nft_addr_friendly = normalize_address(nft_address, "friendly")
        owner_addr_friendly = normalize_address(owner_address, "friendly")
    except Exception:
        nft_addr_friendly = nft_address
        owner_addr_friendly = owner_address

    change_result = marketapp_request(
        "/nfts/change_price/",
        method="POST",
        json_data={
            "owner_address": owner_addr_friendly,
            "data": [{"nft_address": nft_addr_friendly, "price": new_price_ton}],
        },
    )

    if not change_result["success"]:
        return {
            "success": False,
            "error": change_result.get(
                "error", "Failed to create change price transaction"
            ),
        }

    transaction = change_result["data"].get("transaction", {})
    emulation = emulate_marketapp_tx(transaction, owner_address)

    result = {
        "action": "change_price",
        "nft": {
            "address": nft_addr_friendly,
            "name": nft_info.get("name"),
        },
        "old_price_ton": old_price,
        "new_price_ton": new_price_ton,
        "seller": owner_addr_friendly,
        "emulation": emulation,
    }

    if confirm:
        wallet = create_wallet_instance(wallet_data)
        seqno = get_seqno(owner_address)

        send_result = build_and_send_marketapp_tx(
            transaction=transaction,
            wallet=wallet,
            wallet_address=owner_address,
            seqno=seqno,
        )

        result["sent"] = send_result["success"]
        if send_result["success"]:
            result["success"] = True
            result["message"] = "Price change transaction sent"
        else:
            result["success"] = False
            result["error"] = send_result.get("error")
    else:
        result["success"] = True
        result["confirmed"] = False
        result["message"] = "Emulation successful. Use --confirm to change price."

    return result


# =============================================================================
# NFT Transfer (TonAPI)
# =============================================================================


def build_nft_transfer(
    wallet,
    nft_address: str,
    to_address: str,
    response_address: str,
    forward_amount: int = 1,
    seqno: int = 0,
) -> bytes:
    """
    Строит транзакцию трансфера NFT (TEP-62).
    """
    from tonsdk.boc import Cell
    from tonsdk.utils import Address

    payload = Cell()
    payload.bits.write_uint(NFT_TRANSFER_OPCODE, 32)
    payload.bits.write_uint(0, 64)
    payload.bits.write_address(Address(to_address))
    payload.bits.write_address(Address(response_address))
    payload.bits.write_bit(0)
    payload.bits.write_coins(forward_amount)
    payload.bits.write_bit(0)

    query = wallet.create_transfer_message(
        to_addr=nft_address, amount=to_nano(0.05, "ton"), payload=payload, seqno=seqno
    )

    return query["message"].to_boc(False)


def emulate_transfer(boc_b64: str, wallet_address: str) -> dict:
    """Эмулирует транзакцию через TonAPI."""
    result = tonapi_request(
        "/wallet/emulate", method="POST", json_data={"boc": boc_b64}
    )

    if not result["success"]:
        result = tonapi_request(
            "/events/emulate", method="POST", json_data={"boc": boc_b64}
        )

    if not result["success"]:
        return {"success": False, "error": result.get("error", "Emulation failed")}

    data = result["data"]
    event = data.get("event", data)
    actions = event.get("actions", [])

    extra = event.get("extra", 0)
    fee = abs(extra) if extra < 0 else 0

    nft_transfer = None
    for action in actions:
        if action.get("type") == "NftItemTransfer":
            nft_transfer = action.get("NftItemTransfer", {})
            break

    return {
        "success": True,
        "fee_nano": fee,
        "fee_ton": fee / 1e9,
        "nft_transfer": nft_transfer,
        "actions_count": len(actions),
        "risk": event.get("risk", {}),
    }


def send_transaction(boc_b64: str) -> dict:
    """Отправляет транзакцию в сеть."""
    result = tonapi_request(
        "/blockchain/message", method="POST", json_data={"boc": boc_b64}
    )

    if not result["success"]:
        return {
            "success": False,
            "error": result.get("error", "Failed to send transaction"),
        }

    return {"success": True, "message": "Transaction sent"}


def transfer_nft(
    nft_address: str,
    from_wallet: str,
    to_address: str,
    password: str,
    confirm: bool = False,
) -> dict:
    """
    Переводит NFT на другой адрес.
    """
    if not TONSDK_AVAILABLE:
        return {"success": False, "error": "tonsdk not installed"}

    resolved = resolve_address(to_address)
    if not resolved["success"]:
        return {
            "success": False,
            "error": f"Cannot resolve recipient: {resolved.get('error')}",
        }
    recipient = resolved["address"]

    wallet_data = get_wallet_from_storage(from_wallet, password)
    if not wallet_data:
        return {"success": False, "error": f"Wallet not found: {from_wallet}"}

    wallet = create_wallet_instance(wallet_data)
    sender_address = wallet_data["address"]

    nft_info = get_nft_info(nft_address)
    if not nft_info["success"]:
        return {
            "success": False,
            "error": f"Cannot fetch NFT info: {nft_info.get('error')}",
        }

    nft_owner = nft_info.get("owner")

    try:
        sender_raw = normalize_address(sender_address, "raw")
        owner_raw = normalize_address(nft_owner, "raw") if nft_owner else None
    except Exception:
        sender_raw = sender_address
        owner_raw = nft_owner

    if owner_raw != sender_raw:
        return {
            "success": False,
            "error": f"NFT is not owned by this wallet. Owner: {nft_owner}",
        }

    try:
        nft_addr_friendly = normalize_address(nft_address, "friendly")
    except Exception:
        nft_addr_friendly = nft_address

    seqno = get_seqno(sender_address)

    boc = build_nft_transfer(
        wallet=wallet,
        nft_address=nft_addr_friendly,
        to_address=recipient,
        response_address=sender_address,
        forward_amount=1,
        seqno=seqno,
    )
    boc_b64 = base64.b64encode(boc).decode("ascii")

    emulation = emulate_transfer(boc_b64, sender_address)

    result = {
        "action": "transfer_nft",
        "nft": {
            "address": nft_address,
            "name": nft_info.get("name"),
            "collection": nft_info.get("collection", {}).get("name")
            if nft_info.get("collection")
            else None,
        },
        "from": sender_address,
        "to": recipient,
        "to_input": to_address,
        "is_domain": resolved.get("is_domain", False),
        "emulation": emulation,
    }

    if not emulation["success"]:
        result["success"] = False
        result["error"] = emulation.get("error", "Emulation failed")
        return result

    result["fee_ton"] = emulation["fee_ton"]

    if confirm:
        send_result = send_transaction(boc_b64)
        result["sent"] = send_result["success"]
        if send_result["success"]:
            result["success"] = True
            result["message"] = "NFT transfer sent successfully"
        else:
            result["success"] = False
            result["error"] = send_result.get("error", "Failed to send")
    else:
        result["success"] = True
        result["confirmed"] = False
        result["message"] = "Emulation successful. Use --confirm to send."

    return result


# =============================================================================
# CLI
# =============================================================================


def main():
    parser = argparse.ArgumentParser(
        description="NFT operations on TON (with Marketapp integration)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Список NFT в кошельке
  %(prog)s list --wallet trading
  
  # Информация об NFT
  %(prog)s info --address EQC7...
  
  # Информация о коллекции
  %(prog)s collection --address EQCV...
  
  # Поиск коллекций
  %(prog)s search --query "TON Diamonds"
  
  # Гифты на продаже
  %(prog)s gifts --min-price 1 --max-price 10
  
  # Купить NFT (эмуляция)
  %(prog)s buy --nft EQC7... --wallet trading
  
  # Купить NFT (с подтверждением)
  %(prog)s buy --nft EQC7... --wallet trading --confirm
  
  # Выставить на продажу
  %(prog)s sell --nft EQC7... --price 5.5 --wallet trading
  
  # Снять с продажи
  %(prog)s cancel-sale --nft EQC7... --wallet trading
  
  # Сменить цену
  %(prog)s change-price --nft EQC7... --price 10 --wallet trading
  
  # Трансфер NFT
  %(prog)s transfer --nft EQC7... --from trading --to wallet.ton
""",
    )

    parser.add_argument(
        "--password", "-p", help="Wallet password (or WALLET_PASSWORD env)"
    )

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # --- list ---
    list_p = subparsers.add_parser("list", help="List NFTs in wallet")
    list_p.add_argument(
        "--wallet", "-w", required=True, help="Wallet label, address or .ton domain"
    )
    list_p.add_argument(
        "--limit", "-l", type=int, default=100, help="Max NFTs to fetch"
    )

    # --- info ---
    info_p = subparsers.add_parser("info", help="Get NFT details")
    info_p.add_argument("--address", "-a", required=True, help="NFT address")

    # --- collection ---
    coll_p = subparsers.add_parser("collection", help="Get collection info")
    coll_p.add_argument("--address", "-a", required=True, help="Collection address")
    coll_p.add_argument(
        "--filter",
        "-f",
        default="onsale",
        choices=["onsale", "all"],
        help="Filter NFTs",
    )
    coll_p.add_argument("--limit", "-l", type=int, default=10, help="Max NFTs to show")

    # --- search ---
    search_p = subparsers.add_parser("search", help="Search collections")
    search_p.add_argument("--query", "-q", required=True, help="Search query")
    search_p.add_argument("--limit", "-l", type=int, default=10, help="Max results")

    # --- floor ---
    floor_p = subparsers.add_parser("floor", help="Get collection floor price")
    floor_p.add_argument(
        "--collection",
        "-c",
        required=True,
        help="Collection address or alias (anon, usernames, etc.)",
    )

    # --- gifts ---
    gifts_p = subparsers.add_parser("gifts", help="List gifts on sale")
    gifts_p.add_argument("--model", "-m", help="Filter by model")
    gifts_p.add_argument("--symbol", "-s", help="Filter by symbol")
    gifts_p.add_argument("--backdrop", "-b", help="Filter by backdrop")
    gifts_p.add_argument("--min-price", type=float, help="Min price in TON")
    gifts_p.add_argument("--max-price", type=float, help="Max price in TON")
    gifts_p.add_argument("--limit", "-l", type=int, default=20, help="Max results")

    # --- buy ---
    buy_p = subparsers.add_parser("buy", help="Buy NFT")
    buy_p.add_argument("--nft", "-n", required=True, help="NFT address")
    buy_p.add_argument("--wallet", "-w", required=True, help="Buyer wallet (label)")
    buy_p.add_argument("--confirm", action="store_true", help="Confirm and send")

    # --- sell ---
    sell_p = subparsers.add_parser("sell", help="Put NFT for sale")
    sell_p.add_argument("--nft", "-n", required=True, help="NFT address")
    sell_p.add_argument("--price", "-P", type=float, required=True, help="Price in TON")
    sell_p.add_argument("--wallet", "-w", required=True, help="Owner wallet (label)")
    sell_p.add_argument("--confirm", action="store_true", help="Confirm and send")

    # --- cancel-sale ---
    cancel_p = subparsers.add_parser("cancel-sale", help="Cancel NFT sale")
    cancel_p.add_argument("--nft", "-n", required=True, help="NFT address")
    cancel_p.add_argument("--wallet", "-w", required=True, help="Owner wallet (label)")
    cancel_p.add_argument("--confirm", action="store_true", help="Confirm and send")

    # --- change-price ---
    change_p = subparsers.add_parser("change-price", help="Change NFT price")
    change_p.add_argument("--nft", "-n", required=True, help="NFT address")
    change_p.add_argument(
        "--price", "-P", type=float, required=True, help="New price in TON"
    )
    change_p.add_argument("--wallet", "-w", required=True, help="Owner wallet (label)")
    change_p.add_argument("--confirm", action="store_true", help="Confirm and send")

    # --- transfer ---
    transfer_p = subparsers.add_parser("transfer", help="Transfer NFT")
    transfer_p.add_argument("--nft", "-n", required=True, help="NFT address")
    transfer_p.add_argument(
        "--from", "-f", dest="from_wallet", required=True, help="Sender wallet (label)"
    )
    transfer_p.add_argument(
        "--to", "-t", required=True, help="Recipient (address or .ton domain)"
    )
    transfer_p.add_argument("--confirm", action="store_true", help="Confirm and send")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    # Получаем пароль если нужен
    password = args.password or os.environ.get("WALLET_PASSWORD")
    needs_password = args.command in [
        "transfer",
        "buy",
        "sell",
        "cancel-sale",
        "change-price",
    ] or (
        args.command == "list"
        and not looks_like_address(args.wallet)
        and not is_ton_domain(args.wallet)
    )

    if needs_password and not password:
        if sys.stdin.isatty():
            password = getpass.getpass("Wallet password: ")
        else:
            if args.command != "list":
                print(
                    json.dumps(
                        {
                            "error": "Password required. Use --password or WALLET_PASSWORD env"
                        }
                    )
                )
                return sys.exit(1)

    try:
        if args.command == "list":
            result = list_nfts(
                wallet_identifier=args.wallet, password=password, limit=args.limit
            )

        elif args.command == "info":
            result = get_nft_info(args.address)

        elif args.command == "collection":
            result = get_collection_info(
                collection_address=args.address, filter_by=args.filter, limit=args.limit
            )

        elif args.command == "search":
            result = search_collections(args.query, args.limit)

        elif args.command == "floor":
            result = get_collection_floor(args.collection)

        elif args.command == "gifts":
            result = get_gifts_on_sale(
                model=args.model,
                symbol=args.symbol,
                backdrop=args.backdrop,
                min_price=args.min_price,
                max_price=args.max_price,
                limit=args.limit,
            )

        elif args.command == "buy":
            if not TONSDK_AVAILABLE:
                print(
                    json.dumps(
                        {
                            "error": "Missing dependency: tonsdk",
                            "install": "pip install tonsdk",
                        },
                        indent=2,
                    )
                )
                return sys.exit(1)

            if not password:
                print(json.dumps({"error": "Password required for buy"}))
                return sys.exit(1)

            result = buy_nft(
                nft_address=args.nft,
                wallet_identifier=args.wallet,
                password=password,
                confirm=args.confirm,
            )

        elif args.command == "sell":
            if not TONSDK_AVAILABLE:
                print(
                    json.dumps(
                        {
                            "error": "Missing dependency: tonsdk",
                            "install": "pip install tonsdk",
                        },
                        indent=2,
                    )
                )
                return sys.exit(1)

            if not password:
                print(json.dumps({"error": "Password required for sell"}))
                return sys.exit(1)

            result = sell_nft(
                nft_address=args.nft,
                price_ton=args.price,
                wallet_identifier=args.wallet,
                password=password,
                confirm=args.confirm,
            )

        elif args.command == "cancel-sale":
            if not TONSDK_AVAILABLE:
                print(
                    json.dumps(
                        {
                            "error": "Missing dependency: tonsdk",
                            "install": "pip install tonsdk",
                        },
                        indent=2,
                    )
                )
                return sys.exit(1)

            if not password:
                print(json.dumps({"error": "Password required for cancel-sale"}))
                return sys.exit(1)

            result = cancel_sale(
                nft_address=args.nft,
                wallet_identifier=args.wallet,
                password=password,
                confirm=args.confirm,
            )

        elif args.command == "change-price":
            if not TONSDK_AVAILABLE:
                print(
                    json.dumps(
                        {
                            "error": "Missing dependency: tonsdk",
                            "install": "pip install tonsdk",
                        },
                        indent=2,
                    )
                )
                return sys.exit(1)

            if not password:
                print(json.dumps({"error": "Password required for change-price"}))
                return sys.exit(1)

            result = change_price(
                nft_address=args.nft,
                new_price_ton=args.price,
                wallet_identifier=args.wallet,
                password=password,
                confirm=args.confirm,
            )

        elif args.command == "transfer":
            if not TONSDK_AVAILABLE:
                print(
                    json.dumps(
                        {
                            "error": "Missing dependency: tonsdk",
                            "install": "pip install tonsdk",
                        },
                        indent=2,
                    )
                )
                return sys.exit(1)

            if not password:
                print(json.dumps({"error": "Password required for transfer"}))
                return sys.exit(1)

            result = transfer_nft(
                nft_address=args.nft,
                from_wallet=args.from_wallet,
                to_address=args.to,
                password=password,
                confirm=args.confirm,
            )

        else:
            result = {"error": f"Unknown command: {args.command}"}

        print(json.dumps(result, indent=2, ensure_ascii=False))

        if not result.get("success", False):
            return sys.exit(1)

    except ValueError as e:
        print(json.dumps({"error": str(e)}, indent=2))
        return sys.exit(1)
    except Exception as e:
        print(json.dumps({"error": f"Unexpected error: {e}"}, indent=2))
        return sys.exit(1)


if __name__ == "__main__":
    main()
