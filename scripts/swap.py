#!/usr/bin/env python3
"""
OpenClaw TON Skill — Свапы через swap.coffee

- Получение котировки (routing API)
- Эмуляция свапа
- Исполнение свапа
- Статус транзакции

Документация: https://docs.swap.coffee/technical-guides/aggregator-api/introduction
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

from utils import api_request, tonapi_request, load_config, is_valid_address  # noqa: E402
from wallet import WalletStorage  # noqa: E402
from tokens import resolve_token_by_symbol  # noqa: E402


def _make_url_safe(address: str) -> str:
    """Конвертирует адрес в URL-safe формат (заменяет +/ на -_)."""
    return address.replace("+", "-").replace("/", "_")


# TON SDK
try:
    from tonsdk.contract.wallet import Wallets, WalletVersionEnum
    from tonsdk.utils import to_nano, from_nano  # noqa: F401
    from tonsdk.boc import Cell

    TONSDK_AVAILABLE = True
except ImportError:
    TONSDK_AVAILABLE = False


# =============================================================================
# Constants
# =============================================================================

SWAP_COFFEE_API = "https://backend.swap.coffee"
SWAP_COFFEE_API_V1 = "https://backend.swap.coffee/v1"
SWAP_COFFEE_API_V2 = "https://backend.swap.coffee/v2"

# Transaction status polling
TX_STATUS_POLL_INTERVAL = 5  # seconds between polls

# Известные токены (symbol -> master address)
KNOWN_TOKENS = {
    "TON": "native",
    "USDT": "EQCxE6mUtQJKFnGfaROTKOt1lZbDiiX1kCixRv7Nw2Id_sDs",
    "USDC": "EQC61IQRl0_la95t27xhIpjxZt32vl1QQVF2UgTNuvD18W-4",
    "NOT": "EQAvlWFDxGF2lXm67y4yzC17wYKD9A0guwPkMs1gOsM__NOT",
    "STON": "EQA2kCVNwVsil2EM2mB0SkXytxCqQjS4mttjDpnXmwG9T6bO",
    "DUST": "EQBlqsm144Dq6SjbPI4jjZvA1hqTIP3CvHovbIfW_t-SCALE",
    "JETTON": "EQCxE6mUtQJKFnGfaROTKOt1lZbDiiX1kCixRv7Nw2Id_sDs",  # Example
}


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
    version: str = "v1",
) -> dict:
    """
    Запрос к swap.coffee API.

    Args:
        endpoint: Endpoint (например "/route")
        method: HTTP метод
        params: Query параметры
        json_data: JSON body
        version: Версия API ("v1" или "v2")

    Returns:
        dict с результатом
    """
    if version == "v2":
        base_url = SWAP_COFFEE_API_V2
    elif version == "v1":
        base_url = SWAP_COFFEE_API_V1
    else:
        base_url = SWAP_COFFEE_API

    api_key = get_swap_coffee_key()

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["X-Api-Key"] = api_key

    return api_request(
        url=f"{base_url}{endpoint}",
        method=method,
        headers=headers if headers else None,
        params=params,
        json_data=json_data,
    )


def resolve_token_address(token: str) -> str:
    """
    Резолвит токен в адрес мастер-контракта.

    Args:
        token: Символ токена (TON, USDT) или адрес

    Returns:
        Адрес или "native" для TON
    """
    token_upper = token.upper()

    # Проверяем известные токены
    if token_upper in KNOWN_TOKENS:
        return KNOWN_TOKENS[token_upper]

    # Если похоже на адрес — возвращаем как есть
    if is_valid_address(token) or ":" in token:
        return token

    # Пробуем найти через swap.coffee Tokens API
    try:
        resolved = resolve_token_by_symbol(token)
        if resolved and resolved.get("address"):
            return resolved["address"]
    except Exception:
        pass

    return token


def get_token_info(token_address: str) -> dict:
    """Получает информацию о токене."""
    if token_address == "native":
        return {"address": "native", "symbol": "TON", "name": "Toncoin", "decimals": 9}

    # Запрос к TonAPI
    addr_safe = _make_url_safe(token_address)
    result = tonapi_request(f"/jettons/{addr_safe}")
    if result["success"]:
        data = result["data"]
        return {
            "address": token_address,
            "symbol": data.get("metadata", {}).get("symbol", "???"),
            "name": data.get("metadata", {}).get("name", "Unknown"),
            "decimals": data.get("metadata", {}).get("decimals", 9),
            "image": data.get("metadata", {}).get("image"),
        }

    return {"address": token_address, "symbol": "???", "name": "Unknown", "decimals": 9}


# =============================================================================
# Quote / Route
# =============================================================================


def _normalize_symbol(symbol: str) -> str:
    """Нормализует символ жетона (USD₮ → USDT, ₿TC → BTC)."""
    if not symbol:
        return symbol
    return symbol.replace("₮", "T").replace("₿", "B").replace("₴", "S")


def get_swap_quote(
    input_token: str,
    output_token: str,
    input_amount: float,
    sender_address: str,
    slippage: float = 0.5,
) -> dict:
    """
    Получает котировку свапа.

    Args:
        input_token: Символ или адрес входного токена
        output_token: Символ или адрес выходного токена
        input_amount: Количество входного токена (человекочитаемое)
        sender_address: Адрес кошелька
        slippage: Допустимое проскальзывание в %

    Returns:
        dict с котировкой (маршрут, ожидаемый выход, комиссии)
    """
    # Валидация входных параметров
    if not input_token or not input_token.strip():
        return {"success": False, "error": "Input token is required"}
    if not output_token or not output_token.strip():
        return {"success": False, "error": "Output token is required"}
    if input_amount is None or input_amount <= 0:
        return {"success": False, "error": "Amount must be positive"}
    if slippage < 0 or slippage > 100:
        return {"success": False, "error": "Slippage must be between 0 and 100%"}

    # Резолвим токены
    input_addr = resolve_token_address(input_token)
    output_addr = resolve_token_address(output_token)

    # Получаем decimals для токенов (для отображения)
    input_info = get_token_info(input_addr)
    output_info = get_token_info(output_addr)

    input_decimals = int(input_info.get("decimals", 9))
    output_decimals = int(output_info.get("decimals", 9))

    # Формируем токены в формате swap.coffee API
    # API ожидает: {"blockchain": "ton", "address": "native"} или {"blockchain": "ton", "address": "<jetton_address>"}
    input_token_obj = {"blockchain": "ton", "address": input_addr}
    output_token_obj = {"blockchain": "ton", "address": output_addr}

    # Запрос к swap.coffee API v1
    # POST /v1/route с JSON body
    # input_amount в токенах (не nano!), как float
    request_body = {
        "input_token": input_token_obj,
        "output_token": output_token_obj,
        "input_amount": input_amount,  # В токенах, не в nano!
        "max_splits": 4,  # Для v4 кошельков
        "max_length": 4,  # До 2 промежуточных токенов
    }

    result = swap_coffee_request(
        "/route", method="POST", json_data=request_body, version="v1"
    )

    if not result["success"]:
        return {
            "success": False,
            "error": result.get("error", "Failed to get quote"),
            "input_token": input_token,
            "output_token": output_token,
        }

    data = result["data"]

    # Парсим ответ swap.coffee v1 API
    # Ответ содержит: input_amount, output_amount (в токенах), paths, price_impact и т.д.
    output_amount = float(data.get("output_amount", 0))
    input_usd = float(data.get("input_usd", 0))
    output_usd = float(data.get("output_usd", 0))
    price_impact = data.get("price_impact", 0)
    recommended_gas = data.get("recommended_gas", 0.15)

    # Конвертируем в raw для совместимости
    input_amount_raw = int(input_amount * (10**input_decimals))
    output_amount_raw = int(output_amount * (10**output_decimals))

    # Минимальный выход с учётом slippage
    min_output = output_amount * (1 - slippage / 100)
    min_output_raw = int(min_output * (10**output_decimals))

    # Вычисляем эффективную цену
    if input_amount > 0:
        price = output_amount / input_amount
    else:
        price = 0

    # Маршрут
    paths = data.get("paths", [])
    route_info = []
    for path in paths:
        route_info.append(
            {
                "dex": path.get("dex", "unknown"),
                "pool": path.get("pool_address"),
                "input": path.get("input_token", {}).get("address", {}).get("address"),
                "output": path.get("output_token", {})
                .get("address", {})
                .get("address"),
                "input_amount": path.get("swap", {}).get("input_amount"),
                "output_amount": path.get("swap", {}).get("output_amount"),
            }
        )

    return {
        "success": True,
        "input_token": {
            "symbol": _normalize_symbol(input_info["symbol"]),
            "address": input_addr,
            "amount": input_amount,
            "amount_raw": input_amount_raw,
            "usd": input_usd,
        },
        "output_token": {
            "symbol": _normalize_symbol(output_info["symbol"]),
            "address": output_addr,
            "amount": output_amount,
            "amount_raw": output_amount_raw,
            "min_amount": min_output,
            "min_amount_raw": min_output_raw,
            "usd": output_usd,
        },
        "price": price,
        "price_impact": price_impact,
        "slippage": slippage,
        "route": route_info,
        "route_count": len(route_info),
        "recommended_gas": recommended_gas,
        "savings_usd": data.get("savings", 0),
        "raw_response": data,
    }


# =============================================================================
# Build Swap Transactions
# =============================================================================


def build_swap_transactions(
    input_token: str,
    output_token: str,
    input_amount: float,
    sender_address: str,
    slippage: float = 0.5,
) -> dict:
    """
    Строит транзакции для выполнения свапа.

    Args:
        input_token: Символ или адрес входного токена
        output_token: Символ или адрес выходного токена
        input_amount: Количество входного токена
        sender_address: Адрес кошелька
        slippage: Допустимое проскальзывание в %

    Returns:
        dict с транзакциями (BOC) для подписания
    """
    # Резолвим токены
    input_addr = resolve_token_address(input_token)
    output_addr = resolve_token_address(output_token)

    # input_info = get_token_info(input_addr)
    # input_decimals = int(input_info.get("decimals", 9))
    # input_amount_raw = int(input_amount * (10**input_decimals))

    # Сначала получаем маршрут через v1
    route_result = swap_coffee_request(
        "/route",
        method="POST",
        json_data={
            "input_token": {"blockchain": "ton", "address": input_addr},
            "output_token": {"blockchain": "ton", "address": output_addr},
            "input_amount": input_amount,
            "max_length": 3,
        },
        version="v1",
    )

    if not route_result["success"]:
        return {
            "success": False,
            "error": route_result.get("error", "Failed to get route"),
        }

    # Запрос на построение транзакций через v2
    result = swap_coffee_request(
        "/route/transactions",
        method="POST",
        json_data={
            "sender_address": sender_address,
            "slippage": slippage / 100,
            "paths": route_result["data"].get("paths", []),
        },
        version="v2",
    )

    if not result["success"]:
        return {
            "success": False,
            "error": result.get("error", "Failed to build transactions"),
        }

    data = result["data"]

    # Парсим транзакции
    transactions = data.get("transactions", [])

    return {
        "success": True,
        "transactions": transactions,
        "transactions_count": len(transactions),
        "raw_response": data,
    }


# =============================================================================
# Execute Swap
# =============================================================================


def get_wallet_from_storage(identifier: str, password: str) -> Optional[dict]:
    """Получает кошелёк из хранилища."""
    storage = WalletStorage(password)
    return storage.get_wallet(identifier, include_secrets=True)


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
    addr_safe = _make_url_safe(address)

    # Пробуем /v2/wallet/{address}/seqno
    result = tonapi_request(f"/wallet/{addr_safe}/seqno")
    if result["success"]:
        return result["data"].get("seqno", 0)

    # Fallback: через get method
    result = tonapi_request(f"/blockchain/accounts/{addr_safe}/methods/seqno")
    if result["success"]:
        decoded = result["data"].get("decoded", {})
        # Может вернуть как {"seqno": N} или просто число
        if isinstance(decoded, dict):
            return decoded.get("seqno", 0)
        elif isinstance(decoded, int):
            return decoded
        # Также смотрим в stack
        stack = result["data"].get("stack", [])
        if stack and len(stack) > 0:
            first = stack[0]
            if isinstance(first, dict) and first.get("type") == "num":
                return int(first.get("num", "0"), 16)

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


def execute_swap(
    from_wallet: str,
    input_token: str,
    output_token: str,
    input_amount: float,
    slippage: float = 0.5,
    *,
    password: str,
    confirm: bool = False,
    referral_address: Optional[str] = None,
    referral_fee_percent: float = 0.0,
    wait_for_completion: bool = False,
) -> dict:
    """
    Выполняет свап токенов.

    Args:
        from_wallet: Лейбл или адрес кошелька
        input_token: Символ или адрес входного токена
        output_token: Символ или адрес выходного токена
        input_amount: Количество для свапа
        slippage: Проскальзывание в %
        password: Пароль
        confirm: Подтвердить выполнение
        referral_address: Адрес реферала для комиссии
        referral_fee_percent: Процент реферальной комиссии (0-1%)
        wait_for_completion: Ожидать завершения транзакции

    Returns:
        dict с результатом (эмуляция или выполнение)
    """
    if not TONSDK_AVAILABLE:
        return {"success": False, "error": "tonsdk not installed"}

    # Валидация входных параметров
    if not input_token or not input_token.strip():
        return {"success": False, "error": "Input token is required"}
    if not output_token or not output_token.strip():
        return {"success": False, "error": "Output token is required"}
    if input_amount is None or input_amount <= 0:
        return {"success": False, "error": "Amount must be positive"}
    if slippage < 0 or slippage > 100:
        return {"success": False, "error": "Slippage must be between 0 and 100%"}

    # 1. Получаем кошелёк
    wallet_data = get_wallet_from_storage(from_wallet, password)
    if not wallet_data:
        return {"success": False, "error": f"Wallet not found: {from_wallet}"}

    sender_address = wallet_data["address"]

    # 2. Получаем котировку
    quote = get_swap_quote(
        input_token=input_token,
        output_token=output_token,
        input_amount=input_amount,
        sender_address=sender_address,
        slippage=slippage,
    )

    if not quote["success"]:
        return quote

    # 3. Строим транзакции
    tx_result = build_swap_transactions(
        input_token=input_token,
        output_token=output_token,
        input_amount=input_amount,
        sender_address=sender_address,
        slippage=slippage,
    )

    if not tx_result["success"]:
        return tx_result

    transactions = tx_result.get("transactions", [])

    if not transactions:
        return {"success": False, "error": "No transactions returned by API"}

    # 4. Подписываем транзакции
    # swap.coffee API возвращает транзакции с полями:
    # - address: куда отправить (адрес контракта swap.coffee)
    # - value: сколько TON приложить (в nano, строка)
    # - cell: готовый BOC payload (base64)
    # - send_mode: режим отправки (обычно 3)
    #
    # Нужно создать transfer message от нашего кошелька на address с value TON и cell как payload body

    wallet = create_wallet_instance(wallet_data)
    seqno = get_seqno(sender_address)

    signed_txs = []
    total_fee = 0

    for i, tx in enumerate(transactions):
        # Парсим поля из swap.coffee API response
        to_addr = tx.get("address")  # Куда отправить
        amount_str = tx.get("value", "0")  # В nano, как строка
        amount = int(amount_str)
        cell_b64 = tx.get("cell")  # Готовый BOC payload (base64)
        send_mode = tx.get("send_mode", 3)

        if not to_addr:
            return {"success": False, "error": f"Transaction {i} has no address"}

        # Декодируем cell из base64 в Cell объект
        payload = None
        if cell_b64:
            try:
                cell_bytes = base64.b64decode(cell_b64)
                payload = Cell.one_from_boc(cell_bytes)
            except Exception as e:
                return {
                    "success": False,
                    "error": f"Failed to decode cell for tx {i}: {e}",
                }

        # Создаём transfer message
        # to_addr может быть в raw format "0:abc...", tonsdk работает с этим
        try:
            query = wallet.create_transfer_message(
                to_addr=to_addr,
                amount=amount,
                payload=payload,
                seqno=seqno + i,  # Увеличиваем seqno для каждой транзакции
                send_mode=send_mode,
            )
        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to create transfer for tx {i}: {e}",
            }

        boc = query["message"].to_boc(False)
        boc_b64 = base64.b64encode(boc).decode("ascii")

        # Эмулируем
        emulation = emulate_transaction(boc_b64)

        signed_txs.append(
            {
                "index": i,
                "to": to_addr,
                "amount_nano": amount,
                "amount_ton": amount / 1e9,
                "boc": boc_b64,
                "send_mode": send_mode,
                "emulation": emulation,
            }
        )

        if emulation["success"]:
            total_fee += emulation.get("fee_nano", 0)

    result = {
        "action": "swap",
        "wallet": sender_address,
        "quote": {
            "input": quote["input_token"],
            "output": quote["output_token"],
            "price": quote["price"],
            "price_impact": quote.get("price_impact"),
            "route_count": quote["route_count"],
        },
        "transactions": signed_txs,
        "total_fee_nano": total_fee,
        "total_fee_ton": total_fee / 1e9,
        "slippage": slippage,
    }

    # 5. Отправляем если confirm
    if confirm:
        sent_count = 0
        errors = []
        tx_hashes = []

        for tx in signed_txs:
            send_result = send_transaction(tx["boc"])
            if send_result["success"]:
                sent_count += 1
                # Try to extract tx hash from response
                raw_resp = send_result.get("raw_response", {})
                if isinstance(raw_resp, dict):
                    tx_hash = raw_resp.get("hash") or raw_resp.get("message_hash")
                    if tx_hash:
                        tx_hashes.append(tx_hash)
            else:
                errors.append(send_result.get("error"))

        result["sent_count"] = sent_count
        result["total_transactions"] = len(signed_txs)
        result["tx_hashes"] = tx_hashes

        if sent_count == len(signed_txs):
            result["success"] = True
            result["message"] = "Swap executed successfully"

            # Wait for completion if requested
            if wait_for_completion and tx_hashes:
                result["waiting_for_completion"] = True
                completion_result = wait_for_swap_completion(
                    tx_hashes, max_wait_seconds=60, verbose=False
                )
                result["completion"] = completion_result

                if completion_result.get("success"):
                    result["message"] = (
                        f"Swap completed! {completion_result['completed']}/{completion_result['total']} transactions confirmed"
                    )
                else:
                    result["message"] = (
                        f"Swap sent but verification incomplete: {completion_result.get('failed', 0)} failed, {completion_result.get('timed_out', 0)} timed out"
                    )

        elif sent_count > 0:
            result["success"] = True
            result["message"] = (
                f"Partially executed: {sent_count}/{len(signed_txs)} transactions sent"
            )
            result["errors"] = errors
        else:
            result["success"] = False
            result["error"] = "Failed to send transactions"
            result["errors"] = errors
    else:
        result["success"] = True
        result["confirmed"] = False
        result["message"] = "Swap simulated. Use --confirm to execute."

    return result


# =============================================================================
# Swap Status
# =============================================================================


def get_swap_status(tx_hash: str) -> dict:
    """
    Получает статус транзакции свапа.

    Args:
        tx_hash: Хэш транзакции

    Returns:
        dict со статусом
    """
    # Пробуем swap.coffee API
    result = swap_coffee_request(f"/route/status/{tx_hash}")

    if result["success"]:
        return {"success": True, "source": "swap.coffee", "status": result["data"]}

    # Fallback на TonAPI
    result = tonapi_request(f"/blockchain/transactions/{tx_hash}")

    if result["success"]:
        data = result["data"]
        return {
            "success": True,
            "source": "tonapi",
            "hash": tx_hash,
            "status": "completed" if data.get("success") else "failed",
            "lt": data.get("lt"),
            "utime": data.get("utime"),
            "fee": data.get("total_fees"),
            "raw_response": data,
        }

    return {"success": False, "error": "Transaction not found"}


def poll_transaction_status(
    tx_hash: str,
    max_polls: int = 12,
    poll_interval: int = 5,
) -> dict:
    """
    Опрашивает статус транзакции до завершения или достижения max_polls.

    Args:
        tx_hash: Хэш транзакции
        max_polls: Максимальное количество опросов
        poll_interval: Интервал между опросами в секундах

    Returns:
        dict со статусом
    """
    import time

    for poll_num in range(max_polls):
        status = get_swap_status(tx_hash)

        if status.get("success"):
            # Check if transaction is completed
            tx_status = status.get("status", {})
            if isinstance(tx_status, dict):
                state = tx_status.get("state")
                if state in ("completed", "finalized", "success"):
                    return {
                        "success": True,
                        "completed": True,
                        "poll_num": poll_num + 1,
                        "status": status,
                    }
            elif isinstance(tx_status, str):
                if tx_status in ("completed", "finalized", "success"):
                    return {
                        "success": True,
                        "completed": True,
                        "poll_num": poll_num + 1,
                        "status": status,
                    }

        if poll_num < max_polls - 1:
            time.sleep(poll_interval)

    return {
        "success": False,
        "completed": False,
        "timed_out": True,
        "max_polls": max_polls,
        "message": f"Transaction not confirmed after {max_polls * poll_interval} seconds",
    }


def wait_for_swap_completion(
    tx_hashes: list,
    max_wait_seconds: int = 60,
    verbose: bool = True,
) -> dict:
    """
    Ожидает завершения нескольких транзакций.

    Args:
        tx_hashes: Список хэшей транзакций
        max_wait_seconds: Максимальное время ожидания
        verbose: Выводить прогресс

    Returns:
        dict с результатами
    """

    poll_interval = TX_STATUS_POLL_INTERVAL
    max_polls = max_wait_seconds // poll_interval

    results = []
    completed = 0
    failed = 0
    timed_out = 0

    for tx_hash in tx_hashes:
        result = poll_transaction_status(
            tx_hash, max_polls=max_polls, poll_interval=poll_interval
        )

        if result.get("completed"):
            completed += 1
            if verbose:
                print(f"✓ Transaction {tx_hash[:8]}... confirmed")
        elif result.get("timed_out"):
            timed_out += 1
            if verbose:
                print(f"✗ Transaction {tx_hash[:8]}... timed out")
        else:
            failed += 1
            if verbose:
                print(f"✗ Transaction {tx_hash[:8]}... failed")

        results.append(result)

    return {
        "success": completed == len(tx_hashes),
        "total": len(tx_hashes),
        "completed": completed,
        "failed": failed,
        "timed_out": timed_out,
        "results": results,
    }


# =============================================================================
# CLI
# =============================================================================


def main():
    parser = argparse.ArgumentParser(
        description="Token swaps via swap.coffee",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Получить котировку
  %(prog)s quote --from TON --to USDT --amount 10 --wallet UQBvW8...
  
  # Эмуляция свапа (без выполнения)
  %(prog)s execute --wallet trading --from TON --to USDT --amount 10
  
  # Выполнить свап
  %(prog)s execute --wallet trading --from TON --to USDT --amount 10 --confirm
  
  # Свап с указанием slippage
  %(prog)s execute --wallet main --from USDT --to TON --amount 100 --slippage 1.0 --confirm
  
  # Свап с ожиданием подтверждения
  %(prog)s execute --wallet main --from TON --to USDT --amount 5 --confirm --wait
  
  # Свап с реферальной комиссией
  %(prog)s execute --wallet main --from TON --to USDT --amount 10 --confirm \\
      --referral UQBvW8Z5... --referral-fee 0.5
  
  # Проверить статус транзакции
  %(prog)s status --hash abc123...
  
  # Опросить статус до завершения (макс 60 сек)
  %(prog)s poll --hash abc123... --timeout 60
  
  # Список известных токенов
  %(prog)s tokens

Known tokens: TON, USDT, USDC, NOT, STON, DUST, DOGS, CATS, MAJOR, and more.
Use token symbols or full jetton master addresses.
""",
    )

    parser.add_argument(
        "--password", "-p", help="Wallet password (or WALLET_PASSWORD env)"
    )

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # --- quote ---
    quote_p = subparsers.add_parser("quote", help="Get swap quote")
    quote_p.add_argument(
        "--from",
        "-f",
        dest="input_token",
        required=True,
        help="Input token (symbol or address)",
    )
    quote_p.add_argument(
        "--to",
        "-t",
        dest="output_token",
        required=True,
        help="Output token (symbol or address)",
    )
    quote_p.add_argument(
        "--amount", "-a", type=float, required=True, help="Input amount"
    )
    quote_p.add_argument(
        "--wallet", "-w", required=True, help="Wallet address for quote"
    )
    quote_p.add_argument(
        "--slippage",
        "-s",
        type=float,
        default=0.5,
        help="Slippage tolerance %% (default: 0.5)",
    )

    # --- execute ---
    exec_p = subparsers.add_parser("execute", help="Execute swap")
    exec_p.add_argument("--wallet", "-w", required=True, help="Wallet label or address")
    exec_p.add_argument(
        "--from", "-f", dest="input_token", required=True, help="Input token"
    )
    exec_p.add_argument(
        "--to", "-t", dest="output_token", required=True, help="Output token"
    )
    exec_p.add_argument(
        "--amount", "-a", type=float, required=True, help="Input amount"
    )
    exec_p.add_argument(
        "--slippage", "-s", type=float, default=0.5, help="Slippage %% (default: 0.5)"
    )
    exec_p.add_argument(
        "--confirm", action="store_true", help="Confirm and execute swap"
    )
    exec_p.add_argument(
        "--dry-run",
        action="store_true",
        help="Alias for simulation mode (do not execute on-chain)",
    )
    exec_p.add_argument(
        "--referral",
        "-r",
        dest="referral_address",
        help="Referral address to receive swap fee (optional)",
    )
    exec_p.add_argument(
        "--referral-fee",
        type=float,
        default=0.0,
        help="Referral fee percent (0-1%%, default: 0)",
    )
    exec_p.add_argument(
        "--wait",
        action="store_true",
        help="Wait for transaction completion (with --confirm)",
    )

    # --- poll ---
    poll_p = subparsers.add_parser(
        "poll", help="Poll transaction status until completion"
    )
    poll_p.add_argument("--hash", "-x", required=True, help="Transaction hash")
    poll_p.add_argument(
        "--timeout", type=int, default=60, help="Max wait time in seconds (default: 60)"
    )

    # --- status ---
    status_p = subparsers.add_parser("status", help="Get swap/transaction status")
    status_p.add_argument("--hash", "-x", required=True, help="Transaction hash")

    # --- tokens ---
    subparsers.add_parser("tokens", help="List known tokens")

    # --- smart (smart routing) ---
    smart_p = subparsers.add_parser(
        "smart", help="Get optimized route via smart routing"
    )
    smart_p.add_argument(
        "--from", "-f", dest="input_token", required=True, help="Input token"
    )
    smart_p.add_argument(
        "--to", "-t", dest="output_token", required=True, help="Output token"
    )
    smart_p.add_argument(
        "--amount", "-a", type=float, required=True, help="Input amount"
    )
    smart_p.add_argument("--wallet", "-w", required=True, help="Wallet address")
    smart_p.add_argument(
        "--slippage", "-s", type=float, default=0.5, help="Slippage %% (default: 0.5)"
    )
    smart_p.add_argument(
        "--max-splits", type=int, default=4, help="Max route splits (default: 4)"
    )
    smart_p.add_argument(
        "--max-length", type=int, default=4, help="Max swap chain length (default: 4)"
    )

    # --- multi (multi-swap) ---
    multi_p = subparsers.add_parser(
        "multi", help="Multi-swap: multiple swaps in one transaction"
    )
    multi_p.add_argument(
        "--swaps",
        required=True,
        help='JSON array of swaps: [{"input_token":"TON","output_token":"USDT","input_amount":10},...]',
    )
    multi_p.add_argument("--wallet", "-w", required=True, help="Wallet address")
    multi_p.add_argument(
        "--slippage", "-s", type=float, default=0.5, help="Slippage %% (default: 0.5)"
    )
    multi_p.add_argument(
        "--build", action="store_true", help="Build transactions for signing"
    )

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    # Safety: forbid contradictory flags
    if getattr(args, "dry_run", False) and getattr(args, "confirm", False):
        print(json.dumps({"error": "Use either --confirm or --dry-run, not both."}))
        sys.exit(1)

    # If --dry-run is set, force simulation
    if getattr(args, "dry_run", False):
        args.confirm = False

    try:
        if args.command == "quote":
            # Для quote не нужен пароль если передан полный адрес
            wallet_addr = args.wallet
            if not is_valid_address(wallet_addr):
                # Может быть лейбл — нужен пароль
                password = args.password or os.environ.get("WALLET_PASSWORD")
                if password:
                    wallet_data = get_wallet_from_storage(wallet_addr, password)
                    if wallet_data:
                        wallet_addr = wallet_data["address"]

            result = get_swap_quote(
                input_token=args.input_token,
                output_token=args.output_token,
                input_amount=args.amount,
                sender_address=wallet_addr,
                slippage=args.slippage,
            )

        elif args.command == "execute":
            if not TONSDK_AVAILABLE:
                print(
                    json.dumps(
                        {
                            "error": "tonsdk not installed",
                            "install": "pip install tonsdk",
                        },
                        indent=2,
                    )
                )
                return sys.exit(1)

            password = args.password or os.environ.get("WALLET_PASSWORD")
            if not password:
                if sys.stdin.isatty():
                    password = getpass.getpass("Wallet password: ")
                else:
                    print(json.dumps({"error": "Password required"}))
                    return sys.exit(1)

            result = execute_swap(
                from_wallet=args.wallet,
                input_token=args.input_token,
                output_token=args.output_token,
                input_amount=args.amount,
                slippage=args.slippage,
                password=password,
                confirm=args.confirm,
                referral_address=getattr(args, "referral_address", None),
                referral_fee_percent=getattr(args, "referral_fee", 0.0),
                wait_for_completion=getattr(args, "wait", False),
            )

        elif args.command == "status":
            result = get_swap_status(args.hash)

        elif args.command == "poll":
            max_polls = args.timeout // TX_STATUS_POLL_INTERVAL
            result = poll_transaction_status(
                args.hash,
                max_polls=max_polls,
                poll_interval=TX_STATUS_POLL_INTERVAL,
            )

        elif args.command == "tokens":
            result = {
                "success": True,
                "tokens": [
                    {"symbol": k, "address": v} for k, v in KNOWN_TOKENS.items()
                ],
            }

        elif args.command == "smart":
            # Smart routing - get optimized route with custom splits/length
            password = args.password or os.environ.get("WALLET_PASSWORD")
            wallet_addr = args.wallet
            if not is_valid_address(wallet_addr):
                if password:
                    wallet_data = get_wallet_from_storage(wallet_addr, password)
                    if wallet_data:
                        wallet_addr = wallet_data["address"]

            # Resolve tokens
            input_token = args.input_token.upper()
            output_token = args.output_token.upper()

            input_addr = KNOWN_TOKENS.get(input_token, input_token)
            output_addr = KNOWN_TOKENS.get(output_token, output_token)

            # # Get token info for decimals
            # input_info = (
            #     resolve_token_by_symbol(input_token)
            #     if input_addr == "native" or input_token in KNOWN_TOKENS
            #     else {"decimals": 9}
            # )
            # output_info = (
            #     resolve_token_by_symbol(output_token)
            #     if output_addr == "native" or output_token in KNOWN_TOKENS
            #     else {"decimals": 9}
            # )

            # if input_addr == "native":
            #     input_info = {"decimals": 9, "symbol": "TON"}
            # if output_addr == "native":
            #     output_info = {"decimals": 9, "symbol": "TON"}

            # Build request with custom routing params
            request_body = {
                "input_token": {"blockchain": "ton", "address": input_addr},
                "output_token": {"blockchain": "ton", "address": output_addr},
                "input_amount": args.amount,
                "max_splits": args.max_splits,
                "max_length": args.max_length,
            }

            route_result = swap_coffee_request(
                "/route", method="POST", json_data=request_body, version="v1"
            )

            if not route_result["success"]:
                result = {
                    "success": False,
                    "error": route_result.get("error", "Failed to get smart route"),
                }
            else:
                data = route_result["data"]
                output_amount = float(data.get("output_amount", 0))
                min_output = output_amount * (1 - args.slippage / 100)

                paths = data.get("paths", [])
                route_info = []
                for path in paths:
                    route_info.append(
                        {
                            "dex": path.get("dex", "unknown"),
                            "pool": path.get("pool_address"),
                            "input_amount": path.get("swap", {}).get("input_amount"),
                            "output_amount": path.get("swap", {}).get("output_amount"),
                        }
                    )

                result = {
                    "success": True,
                    "action": "smart_route",
                    "input": {
                        "symbol": input_token,
                        "amount": args.amount,
                        "usd": data.get("input_usd", 0),
                    },
                    "output": {
                        "symbol": output_token,
                        "amount": output_amount,
                        "min_amount": min_output,
                        "usd": data.get("output_usd", 0),
                    },
                    "price_impact": data.get("price_impact", 0),
                    "recommended_gas": data.get("recommended_gas", 0.15),
                    "routing": {
                        "max_splits": args.max_splits,
                        "max_length": args.max_length,
                        "actual_splits": len(paths),
                    },
                    "paths": route_info,
                }

        elif args.command == "multi":
            # Multi-swap - multiple swaps in one go (just build transactions)
            try:
                swaps = json.loads(args.swaps)
            except json.JSONDecodeError as e:
                result = {"success": False, "error": f"Invalid JSON in --swaps: {e}"}
            else:
                password = args.password or os.environ.get("WALLET_PASSWORD")
                wallet_addr = args.wallet
                if not is_valid_address(wallet_addr):
                    if password:
                        wallet_data = get_wallet_from_storage(wallet_addr, password)
                        if wallet_data:
                            wallet_addr = wallet_data["address"]

                multi_results = []
                for i, swap_def in enumerate(swaps):
                    input_token = swap_def.get("input_token", "").upper()
                    output_token = swap_def.get("output_token", "").upper()
                    input_amount = float(swap_def.get("input_amount", 0))

                    quote = get_swap_quote(
                        input_token=input_token,
                        output_token=output_token,
                        input_amount=input_amount,
                        sender_address=wallet_addr,
                        slippage=args.slippage,
                    )

                    multi_results.append(
                        {
                            "index": i,
                            "input": input_token,
                            "output": output_token,
                            "amount": input_amount,
                            "quote": quote
                            if quote.get("success")
                            else {"error": quote.get("error")},
                        }
                    )

                result = {
                    "success": True,
                    "action": "multi_swap_quote",
                    "wallet": wallet_addr,
                    "swaps": multi_results,
                    "note": "Use execute command for each swap to perform them",
                }

        else:
            result = {"error": f"Unknown command: {args.command}"}

        print(json.dumps(result, indent=2, ensure_ascii=False))

        if not result.get("success", False):
            return sys.exit(1)

    except Exception as e:
        print(json.dumps({"error": str(e)}, indent=2))
        return sys.exit(1)


if __name__ == "__main__":
    main()
