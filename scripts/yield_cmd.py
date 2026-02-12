#!/usr/bin/env python3
"""
OpenClaw TON Skill — Yield/DeFi CLI

Работа с пулами ликвидности через swap.coffee:
- Список пулов с сортировкой по APY/TVL
- Детали пула
- Рекомендации по выбору пула
- Добавление/вывод ликвидности
- Позиции пользователя

Документация: https://docs.swap.coffee/technical-guides/aggregator-api/yield-internals
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

from utils import api_request, tonapi_request, load_config, is_valid_address


def _make_url_safe(address: str) -> str:
    """Конвертирует адрес в URL-safe формат (заменяет +/ на -_)."""
    return address.replace("+", "-").replace("/", "_")

# TON SDK
try:
    from tonsdk.contract.wallet import Wallets, WalletVersionEnum
    from tonsdk.utils import to_nano, from_nano
    from tonsdk.boc import Cell

    TONSDK_AVAILABLE = True
except ImportError:
    TONSDK_AVAILABLE = False


# =============================================================================
# Constants
# =============================================================================

SWAP_COFFEE_API = "https://backend.swap.coffee"
SWAP_COFFEE_API_V2 = "https://backend.swap.coffee/v2"

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
STABLE_TOKENS = ["USDT", "USDC", "DAI", "TUSD"]


# =============================================================================
# Swap.coffee API
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
    version: str = "v2",
) -> dict:
    """
    Запрос к swap.coffee API.
    """
    base_url = SWAP_COFFEE_API_V2 if version == "v2" else SWAP_COFFEE_API
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
    sort_by: str = "apy",
    min_tvl: Optional[float] = None,
    token: Optional[str] = None,
    limit: int = 50,
) -> dict:
    """
    Получает список yield пулов.

    Args:
        sort_by: Сортировка (apy, tvl, volume)
        min_tvl: Минимальный TVL
        token: Фильтр по токену
        limit: Максимум результатов

    Returns:
        dict с пулами
    """
    # Пробуем swap.coffee yield API
    params = {"sort": sort_by, "limit": limit}
    if min_tvl:
        params["min_tvl"] = min_tvl
    if token:
        params["token"] = token

    result = swap_coffee_request("/yield/pools", params=params)

    if result["success"]:
        pools = result["data"]
        if isinstance(pools, dict):
            pools = pools.get("pools", [])

        # Нормализуем данные
        normalized = []
        for pool in pools:
            normalized.append(_normalize_pool(pool))

        # Сортируем
        if sort_by == "apy":
            normalized.sort(key=lambda x: x.get("apy", 0) or 0, reverse=True)
        elif sort_by == "tvl":
            normalized.sort(key=lambda x: x.get("tvl", 0) or 0, reverse=True)
        elif sort_by == "volume":
            normalized.sort(key=lambda x: x.get("volume_24h", 0) or 0, reverse=True)

        return {
            "success": True,
            "source": "swap.coffee",
            "pools_count": len(normalized),
            "pools": normalized[:limit],
        }

    # Fallback: получаем данные из TonAPI и DEX API
    return _get_pools_fallback(sort_by, min_tvl, token, limit)


def _normalize_pool(pool: dict) -> dict:
    """Нормализует данные пула."""
    # Обработка DeDust формата
    assets = pool.get("assets", [])
    token0_data = {}
    token1_data = {}

    if len(assets) >= 2:
        for i, asset in enumerate(assets[:2]):
            metadata = asset.get("metadata", {}) or {}
            token_info = {
                "symbol": metadata.get("symbol"),
                "address": asset.get("address")
                if asset.get("type") == "jetton"
                else "native",
                "name": metadata.get("name"),
                "decimals": metadata.get("decimals", 9),
            }
            if i == 0:
                token0_data = token_info
            else:
                token1_data = token_info

    # Попытка получить reserve из разных форматов
    reserves = pool.get("reserves", [])
    if reserves and len(reserves) >= 2:
        token0_data["reserve"] = reserves[0]
        token1_data["reserve"] = reserves[1]

    # Формируем pair name
    t0_sym = token0_data.get("symbol") or pool.get("token0_symbol") or "?"
    t1_sym = token1_data.get("symbol") or pool.get("token1_symbol") or "?"
    pair_name = pool.get("pair") or pool.get("name") or f"{t0_sym}/{t1_sym}"

    # TVL calculation (если есть reserves и это TON pair)
    tvl = pool.get("tvl") or pool.get("liquidity")
    if not tvl and reserves and len(reserves) >= 2:
        # Если один из токенов TON, оцениваем TVL
        if token0_data.get("address") == "native":
            ton_reserve = int(reserves[0]) / 1e9  # Convert from nano
            tvl = ton_reserve * 2  # Rough estimate (TON * 2 for pair value)
        elif token1_data.get("address") == "native":
            ton_reserve = int(reserves[1]) / 1e9
            tvl = ton_reserve * 2

    # DEX detection
    dex = pool.get("dex") or pool.get("dex_name")
    if not dex:
        # Detect by pool structure
        if "tradeFee" in pool:
            dex = "DeDust"
        elif "fee" in pool:
            dex = "STON.fi"
        else:
            dex = "unknown"

    return {
        "id": pool.get("id") or pool.get("address"),
        "address": pool.get("address") or pool.get("pool_address"),
        "dex": dex,
        "pair": pair_name,
        "type": pool.get("type", "volatile"),
        "token0": {
            "symbol": token0_data.get("symbol") or pool.get("token0_symbol"),
            "address": token0_data.get("address") or pool.get("token0_address"),
            "reserve": token0_data.get("reserve") or pool.get("token0_reserve"),
            "name": token0_data.get("name"),
        },
        "token1": {
            "symbol": token1_data.get("symbol") or pool.get("token1_symbol"),
            "address": token1_data.get("address") or pool.get("token1_address"),
            "reserve": token1_data.get("reserve") or pool.get("token1_reserve"),
            "name": token1_data.get("name"),
        },
        "tvl": tvl,
        "tvl_estimated": tvl is not None and "tvl" not in pool,
        "apy": pool.get("apy") or pool.get("apr"),
        "apr_breakdown": pool.get("apr_breakdown", {}),
        "volume_24h": pool.get("volume_24h"),
        "volume_7d": pool.get("volume_7d"),
        "fee_tier": pool.get("fee") or pool.get("fee_tier") or pool.get("tradeFee"),
        "il_risk": _estimate_il_risk(
            {
                "token0_symbol": token0_data.get("symbol"),
                "token1_symbol": token1_data.get("symbol"),
            }
        ),
        "total_supply": pool.get("totalSupply"),
        "created_at": pool.get("created_at"),
        "raw_data": pool,
    }


def _estimate_il_risk(pool: dict) -> float:
    """Оценивает риск impermanent loss."""
    token0 = (pool.get("token0_symbol") or "").upper()
    token1 = (pool.get("token1_symbol") or "").upper()

    # Stable/stable пары — минимальный IL
    if token0 in STABLE_TOKENS and token1 in STABLE_TOKENS:
        return 0.01

    # Stable/volatile — средний IL
    if token0 in STABLE_TOKENS or token1 in STABLE_TOKENS:
        return 0.10

    # Volatile/volatile — высокий IL
    return 0.25


def _get_pools_fallback(
    sort_by: str, min_tvl: Optional[float], token: Optional[str], limit: int
) -> dict:
    """Fallback для получения пулов."""
    # Пробуем DeDust API
    result = api_request("https://api.dedust.io/v2/pools")

    if result["success"]:
        pools = result["data"]
        if isinstance(pools, list):
            normalized = [_normalize_pool(p) for p in pools]

            # Фильтруем
            if min_tvl:
                normalized = [p for p in normalized if (p.get("tvl") or 0) >= min_tvl]
            if token:
                token_upper = token.upper()
                normalized = [
                    p
                    for p in normalized
                    if token_upper in (p.get("token0", {}).get("symbol", "").upper())
                    or token_upper in (p.get("token1", {}).get("symbol", "").upper())
                ]

            # Сортируем
            if sort_by == "apy":
                normalized.sort(key=lambda x: x.get("apy", 0) or 0, reverse=True)
            elif sort_by == "tvl":
                normalized.sort(key=lambda x: x.get("tvl", 0) or 0, reverse=True)

            return {
                "success": True,
                "source": "dedust",
                "pools_count": len(normalized),
                "pools": normalized[:limit],
            }

    return {
        "success": False,
        "error": "Failed to fetch pools from any source",
        "note": "Configure swap.coffee API key for better data",
    }


def get_pool_details(pool_id: str) -> dict:
    """
    Получает детальную информацию о пуле.

    Args:
        pool_id: ID или адрес пула

    Returns:
        dict с деталями
    """
    # Пробуем swap.coffee
    result = swap_coffee_request(f"/yield/pool/{pool_id}")

    if result["success"]:
        pool = result["data"]
        normalized = _normalize_pool(pool)

        # Дополнительные данные
        normalized["details"] = {
            "fee_earned_24h": pool.get("fee_earned_24h"),
            "fee_earned_7d": pool.get("fee_earned_7d"),
            "lp_token_address": pool.get("lp_token_address"),
            "lp_token_supply": pool.get("lp_token_supply"),
            "price_ratio": pool.get("price_ratio"),
            "rewards": pool.get("rewards", []),
        }

        return {"success": True, "source": "swap.coffee", "pool": normalized}

    # Fallback: TonAPI pool info
    result = tonapi_request(f"/accounts/{pool_id}")

    if result["success"]:
        data = result["data"]
        return {
            "success": True,
            "source": "tonapi",
            "pool": {
                "address": pool_id,
                "balance": data.get("balance"),
                "status": data.get("status"),
                "interfaces": data.get("interfaces", []),
                "raw_data": data,
            },
            "note": "Limited data from TonAPI. Configure swap.coffee API for full details.",
        }

    return {"success": False, "error": f"Pool not found: {pool_id}"}


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
        sort_by="apy", min_tvl=risk_profile["min_tvl"], token=token, limit=100
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
            t0 = pool.get("token0", {}).get("symbol", "").upper()
            t1 = pool.get("token1", {}).get("symbol", "").upper()
            if t0 not in STABLE_TOKENS and t1 not in STABLE_TOKENS:
                continue

        # Рассчитываем score
        apy = pool.get("apy", 0) or 0
        tvl = pool.get("tvl", 0) or 0
        il_risk = pool.get("il_risk", 0.25)

        # Score: высокий APY + высокий TVL - высокий IL
        score = (apy * 0.4) + (min(tvl / 10_000_000, 1) * 30) - (il_risk * 100)

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
# Wallet Operations
# =============================================================================


def get_wallet_from_storage(identifier: str, password: str) -> Optional[dict]:
    """Получает кошелёк из хранилища."""
    try:
        from wallet import WalletStorage

        storage = WalletStorage(password)
        return storage.get_wallet(identifier, include_secrets=True)
    except Exception:
        return None


def create_wallet_instance(wallet_data: dict):
    """Создаёт инстанс кошелька для подписания."""
    if not TONSDK_AVAILABLE:
        raise RuntimeError("tonsdk not available")

    mnemonic = wallet_data.get("mnemonic")
    if not mnemonic:
        raise ValueError("Wallet has no mnemonic")

    version_map = {
        "v3r2": WalletVersionEnum.v3r2,
        "v4r2": WalletVersionEnum.v4r2,
    }

    version = wallet_data.get("version", "v4r2")
    wallet_version = version_map.get(version.lower(), WalletVersionEnum.v4r2)

    _, _, _, wallet = Wallets.from_mnemonics(mnemonic, wallet_version, workchain=0)

    return wallet


def get_seqno(address: str) -> int:
    """Получает seqno кошелька."""
    result = tonapi_request(f"/wallet/{address}/seqno")
    if result["success"]:
        return result["data"].get("seqno", 0)
    return 0


def emulate_transaction(boc_b64: str) -> dict:
    """Эмулирует транзакцию."""
    result = tonapi_request(
        "/wallet/emulate", method="POST", json_data={"boc": boc_b64}
    )

    if not result["success"]:
        return {"success": False, "error": result.get("error")}

    data = result["data"]
    event = data.get("event", data)
    extra = event.get("extra", 0)
    fee = abs(extra) if extra < 0 else 0

    return {
        "success": True,
        "fee_nano": fee,
        "fee_ton": fee / 1e9,
        "actions": event.get("actions", []),
    }


def send_transaction(boc_b64: str) -> dict:
    """Отправляет транзакцию."""
    result = tonapi_request(
        "/blockchain/message", method="POST", json_data={"boc": boc_b64}
    )

    if not result["success"]:
        return {"success": False, "error": result.get("error")}

    return {"success": True, "data": result.get("data")}


# =============================================================================
# Deposit / Withdraw
# =============================================================================


def deposit_liquidity(
    pool_id: str,
    amount: float,
    wallet_label: str,
    password: str,
    token: str = "TON",
    confirm: bool = False,
) -> dict:
    """
    Добавляет ликвидность в пул.

    Args:
        pool_id: ID пула
        amount: Сумма
        wallet_label: Лейбл кошелька
        password: Пароль
        token: Токен для депозита
        confirm: Выполнить транзакцию

    Returns:
        dict с результатом
    """
    if not TONSDK_AVAILABLE:
        return {"success": False, "error": "tonsdk not installed"}

    # Получаем кошелёк
    wallet_data = get_wallet_from_storage(wallet_label, password)
    if not wallet_data:
        return {"success": False, "error": f"Wallet not found: {wallet_label}"}

    sender_address = wallet_data["address"]

    # Получаем детали пула
    pool_result = get_pool_details(pool_id)
    if not pool_result["success"]:
        return pool_result

    pool = pool_result["pool"]

    # Строим транзакцию через swap.coffee
    result = swap_coffee_request(
        "/yield/deposit",
        method="POST",
        json_data={
            "pool_address": pool_id,
            "sender_address": sender_address,
            "amount": str(int(amount * 1e9)),  # В нано
            "token": token,
        },
    )

    if not result["success"]:
        return {
            "success": False,
            "error": result.get("error", "Failed to build deposit transaction"),
            "note": "Deposit may not be supported for this pool via API",
        }

    tx_data = result["data"]
    transactions = tx_data.get("transactions", [tx_data])

    # Подписываем
    wallet = create_wallet_instance(wallet_data)
    seqno = get_seqno(sender_address)

    signed_txs = []
    total_fee = 0

    for i, tx in enumerate(transactions):
        to_addr = tx.get("to") or tx.get("address")
        amount_nano = int(tx.get("value", tx.get("amount", 0)))
        payload_b64 = tx.get("payload") or tx.get("body")

        # Создаём payload Cell
        payload = None
        if payload_b64:
            try:
                payload_bytes = base64.b64decode(payload_b64)
                payload = Cell.one_from_boc(payload_bytes)
            except:
                pass

        # Transfer message
        query = wallet.create_transfer_message(
            to_addr=to_addr, amount=amount_nano, payload=payload, seqno=seqno + i
        )

        boc = query["message"].to_boc(False)
        boc_b64 = base64.b64encode(boc).decode("ascii")

        # Эмулируем
        emulation = emulate_transaction(boc_b64)

        signed_txs.append(
            {
                "index": i,
                "to": to_addr,
                "amount_nano": amount_nano,
                "amount_ton": amount_nano / 1e9,
                "boc": boc_b64,
                "emulation": emulation,
            }
        )

        if emulation["success"]:
            total_fee += emulation.get("fee_nano", 0)

    response = {
        "action": "deposit",
        "pool": pool.get("pair") or pool_id,
        "pool_address": pool_id,
        "wallet": sender_address,
        "amount": amount,
        "token": token,
        "transactions": signed_txs,
        "total_fee_ton": total_fee / 1e9,
        "expected_lp_tokens": tx_data.get("expected_lp_tokens"),
        "price_impact": tx_data.get("price_impact"),
    }

    if confirm:
        sent_count = 0
        errors = []

        for tx in signed_txs:
            send_result = send_transaction(tx["boc"])
            if send_result["success"]:
                sent_count += 1
            else:
                errors.append(send_result.get("error"))

        response["sent_count"] = sent_count
        response["total_transactions"] = len(signed_txs)

        if sent_count == len(signed_txs):
            response["success"] = True
            response["message"] = "Deposit executed successfully"
        else:
            response["success"] = False
            response["error"] = "Failed to send some transactions"
            response["errors"] = errors
    else:
        response["success"] = True
        response["confirmed"] = False
        response["message"] = "Deposit simulated. Use --confirm to execute."

    return response


def withdraw_liquidity(
    pool_id: str,
    wallet_label: str,
    password: str,
    percentage: float = 100,
    confirm: bool = False,
) -> dict:
    """
    Выводит ликвидность из пула.

    Args:
        pool_id: ID пула
        wallet_label: Лейбл кошелька
        password: Пароль
        percentage: Процент для вывода (1-100)
        confirm: Выполнить транзакцию

    Returns:
        dict с результатом
    """
    if not TONSDK_AVAILABLE:
        return {"success": False, "error": "tonsdk not installed"}

    # Получаем кошелёк
    wallet_data = get_wallet_from_storage(wallet_label, password)
    if not wallet_data:
        return {"success": False, "error": f"Wallet not found: {wallet_label}"}

    sender_address = wallet_data["address"]

    # Строим транзакцию через swap.coffee
    result = swap_coffee_request(
        "/yield/withdraw",
        method="POST",
        json_data={
            "pool_address": pool_id,
            "sender_address": sender_address,
            "percentage": percentage,
        },
    )

    if not result["success"]:
        return {
            "success": False,
            "error": result.get("error", "Failed to build withdraw transaction"),
        }

    tx_data = result["data"]
    transactions = tx_data.get("transactions", [tx_data])

    # Подписываем (аналогично deposit)
    wallet = create_wallet_instance(wallet_data)
    seqno = get_seqno(sender_address)

    signed_txs = []
    total_fee = 0

    for i, tx in enumerate(transactions):
        to_addr = tx.get("to") or tx.get("address")
        amount_nano = int(tx.get("value", tx.get("amount", 0)))
        payload_b64 = tx.get("payload") or tx.get("body")

        payload = None
        if payload_b64:
            try:
                payload_bytes = base64.b64decode(payload_b64)
                payload = Cell.one_from_boc(payload_bytes)
            except:
                pass

        query = wallet.create_transfer_message(
            to_addr=to_addr, amount=amount_nano, payload=payload, seqno=seqno + i
        )

        boc = query["message"].to_boc(False)
        boc_b64 = base64.b64encode(boc).decode("ascii")

        emulation = emulate_transaction(boc_b64)

        signed_txs.append(
            {
                "index": i,
                "to": to_addr,
                "amount_nano": amount_nano,
                "boc": boc_b64,
                "emulation": emulation,
            }
        )

        if emulation["success"]:
            total_fee += emulation.get("fee_nano", 0)

    response = {
        "action": "withdraw",
        "pool_address": pool_id,
        "wallet": sender_address,
        "percentage": percentage,
        "transactions": signed_txs,
        "total_fee_ton": total_fee / 1e9,
        "expected_token0": tx_data.get("expected_token0"),
        "expected_token1": tx_data.get("expected_token1"),
    }

    if confirm:
        sent_count = 0
        errors = []

        for tx in signed_txs:
            send_result = send_transaction(tx["boc"])
            if send_result["success"]:
                sent_count += 1
            else:
                errors.append(send_result.get("error"))

        response["sent_count"] = sent_count
        response["total_transactions"] = len(signed_txs)

        if sent_count == len(signed_txs):
            response["success"] = True
            response["message"] = "Withdrawal executed successfully"
        else:
            response["success"] = False
            response["error"] = "Failed to send some transactions"
            response["errors"] = errors
    else:
        response["success"] = True
        response["confirmed"] = False
        response["message"] = "Withdrawal simulated. Use --confirm to execute."

    return response


# =============================================================================
# Positions
# =============================================================================


def get_positions(wallet: str, password: Optional[str] = None) -> dict:
    """
    Получает LP позиции кошелька.

    Args:
        wallet: Адрес или лейбл кошелька
        password: Пароль (если лейбл)

    Returns:
        dict с позициями
    """
    # Резолвим адрес
    wallet_address = wallet
    if not is_valid_address(wallet) and password:
        wallet_data = get_wallet_from_storage(wallet, password)
        if wallet_data:
            wallet_address = wallet_data["address"]

    # Пробуем swap.coffee
    result = swap_coffee_request("/yield/positions", params={"wallet": wallet_address})

    if result["success"]:
        positions = result["data"]
        if isinstance(positions, dict):
            positions = positions.get("positions", [])

        # Вычисляем total value
        total_value = sum(p.get("value_usd", 0) or 0 for p in positions)
        total_pnl = sum(p.get("pnl_usd", 0) or 0 for p in positions)

        return {
            "success": True,
            "source": "swap.coffee",
            "wallet": wallet_address,
            "positions_count": len(positions),
            "total_value_usd": total_value,
            "total_pnl_usd": total_pnl,
            "positions": positions,
        }

    # Fallback: ищем LP токены через TonAPI
    result = tonapi_request(f"/accounts/{wallet_address}/jettons")

    if not result["success"]:
        return {"success": False, "error": "Failed to fetch positions"}

    jettons = result["data"].get("balances", [])

    # Фильтруем LP токены (эвристика: имя содержит LP, Pool, или известные DEX)
    lp_keywords = ["LP", "Pool", "DeDust", "STON.fi", "Megaton"]
    lp_positions = []

    for j in jettons:
        name = j.get("jetton", {}).get("name", "")
        symbol = j.get("jetton", {}).get("symbol", "")

        if any(
            kw.lower() in name.lower() or kw.lower() in symbol.lower()
            for kw in lp_keywords
        ):
            lp_positions.append(
                {
                    "token_address": j.get("jetton", {}).get("address"),
                    "name": name,
                    "symbol": symbol,
                    "balance": j.get("balance"),
                    "value_usd": None,  # Unknown without price data
                    "note": "Detected as LP token by name pattern",
                }
            )

    return {
        "success": True,
        "source": "tonapi",
        "wallet": wallet_address,
        "positions_count": len(lp_positions),
        "positions": lp_positions,
        "note": "Limited data from TonAPI. Configure swap.coffee API for full details.",
    }


# =============================================================================
# CLI
# =============================================================================


def main():
    parser = argparse.ArgumentParser(
        description="Yield/DeFi operations via swap.coffee",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Список пулов
  %(prog)s pools --sort apy
  %(prog)s pools --sort tvl --min-tvl 1000000
  %(prog)s pools --token TON
  
  # Детали пула
  %(prog)s pool --id EQD...abc
  
  # Рекомендации
  %(prog)s recommend --risk low
  %(prog)s recommend --token TON --risk medium
  
  # Добавить ликвидность (эмуляция)
  %(prog)s deposit --pool EQD...abc --amount 100 --wallet trading
  
  # Добавить ликвидность (выполнить)
  %(prog)s deposit --pool EQD...abc --amount 100 --wallet trading --confirm
  
  # Вывести ликвидность
  %(prog)s withdraw --pool EQD...abc --wallet trading --confirm
  
  # Позиции
  %(prog)s positions --wallet trading

Risk levels: low, medium, high
""",
    )

    parser.add_argument(
        "--password", "-p", help="Wallet password (or WALLET_PASSWORD env)"
    )

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # --- pools ---
    pools_p = subparsers.add_parser("pools", help="List yield pools")
    pools_p.add_argument(
        "--sort", "-s", default="apy", choices=["apy", "tvl", "volume"], help="Sort by"
    )
    pools_p.add_argument("--min-tvl", type=float, help="Minimum TVL filter")
    pools_p.add_argument("--token", "-t", help="Filter by token")
    pools_p.add_argument("--limit", "-l", type=int, default=20, help="Max results")

    # --- pool ---
    pool_p = subparsers.add_parser("pool", help="Pool details")
    pool_p.add_argument("--id", "-i", required=True, help="Pool ID or address")

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
    rec_p.add_argument("--amount", "-a", type=float, help="Investment amount")

    # --- deposit ---
    dep_p = subparsers.add_parser("deposit", help="Add liquidity to pool")
    dep_p.add_argument("--pool", required=True, help="Pool ID or address")
    dep_p.add_argument(
        "--amount", "-a", type=float, required=True, help="Amount to deposit"
    )
    dep_p.add_argument("--wallet", "-w", required=True, help="Wallet label or address")
    dep_p.add_argument("--token", "-t", default="TON", help="Token to deposit")
    dep_p.add_argument("--confirm", action="store_true", help="Execute transaction")

    # --- withdraw ---
    with_p = subparsers.add_parser("withdraw", help="Remove liquidity from pool")
    with_p.add_argument("--pool", required=True, help="Pool ID or address")
    with_p.add_argument("--wallet", "-w", required=True, help="Wallet label or address")
    with_p.add_argument(
        "--percentage",
        type=float,
        default=100,
        help="Percentage to withdraw (default: 100)",
    )
    with_p.add_argument("--confirm", action="store_true", help="Execute transaction")

    # --- positions ---
    pos_p = subparsers.add_parser("positions", help="View LP positions")
    pos_p.add_argument("--wallet", "-w", required=True, help="Wallet label or address")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    try:
        password = getattr(args, "password", None) or os.environ.get("WALLET_PASSWORD")

        if args.command == "pools":
            result = get_yield_pools(
                sort_by=args.sort,
                min_tvl=args.min_tvl,
                token=args.token,
                limit=args.limit,
            )

        elif args.command == "pool":
            result = get_pool_details(args.id)

        elif args.command == "recommend":
            result = recommend_pools(
                token=args.token, risk=args.risk, amount=getattr(args, "amount", None)
            )

        elif args.command == "deposit":
            if not password:
                if sys.stdin.isatty():
                    password = getpass.getpass("Wallet password: ")
                else:
                    print(json.dumps({"error": "Password required for deposit"}))
                    sys.exit(1)

            result = deposit_liquidity(
                pool_id=args.pool,
                amount=args.amount,
                wallet_label=args.wallet,
                password=password,
                token=args.token,
                confirm=args.confirm,
            )

        elif args.command == "withdraw":
            if not password:
                if sys.stdin.isatty():
                    password = getpass.getpass("Wallet password: ")
                else:
                    print(json.dumps({"error": "Password required for withdraw"}))
                    sys.exit(1)

            result = withdraw_liquidity(
                pool_id=args.pool,
                wallet_label=args.wallet,
                password=password,
                percentage=args.percentage,
                confirm=args.confirm,
            )

        elif args.command == "positions":
            result = get_positions(args.wallet, password)

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
