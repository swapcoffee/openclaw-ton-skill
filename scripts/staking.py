#!/usr/bin/env python3
"""
OpenClaw TON Skill — Staking Operations via swap.coffee API

Features:
- List all staking pools/protocols
- Get user staking positions
- Build stake transaction
- Build extend stake transaction
- Build unstake/close transaction
- Get staking points/rewards

Supported protocols: tonstakers, stakee, bemo, bemo_v2, hipo, kton

API Endpoints (v1):
- GET /v1/yield/pools?protocols=... — list staking pools
- GET /v1/yield/pool/{pool}/{user} — user position
- POST /v1/yield/pool/{pool}/{user} — build stake/unstake tx
- GET /v1/staking/points/{wallet} — get staking points

Documentation: https://docs.swap.coffee/technical-guides/aggregator-api/yield-internals
"""

import os
import sys
import json
import base64
import argparse
import getpass
from pathlib import Path
from typing import Optional, List

# Локальный импорт
script_dir = Path(__file__).parent
sys.path.insert(0, str(script_dir))

from utils import api_request, tonapi_request, load_config, is_valid_address  # noqa: E402

# TON SDK
try:
    from tonsdk.contract.wallet import Wallets, WalletVersionEnum
    from tonsdk.boc import Cell

    TONSDK_AVAILABLE = True
except ImportError:
    TONSDK_AVAILABLE = False


# =============================================================================
# Constants
# =============================================================================

SWAP_COFFEE_API = "https://backend.swap.coffee"

# Staking protocols
STAKING_PROTOCOLS = ["tonstakers", "stakee", "bemo", "bemo_v2", "hipo", "kton"]


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
    """Запрос к swap.coffee API."""
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
    """Конвертирует адрес в URL-safe формат."""
    return address.replace("+", "-").replace("/", "_")


# =============================================================================
# Wallet Storage
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
    addr_safe = _make_url_safe(address)
    result = tonapi_request(f"/wallet/{addr_safe}/seqno")
    if result["success"]:
        return result["data"].get("seqno", 0)
    return 0


# =============================================================================
# Staking Pools
# =============================================================================


def list_staking_pools(
    protocol: Optional[str] = None, sort_by: str = "apr", limit: int = 20
) -> dict:
    """
    Получает список пулов стейкинга.

    Args:
        protocol: Фильтр по протоколу (tonstakers, stakee, bemo, etc.)
        sort_by: Сортировка (apr, tvl)
        limit: Количество результатов

    Returns:
        dict со списком пулов
    """
    # Use yield pools API with staking protocols filter
    protocols = [protocol] if protocol else STAKING_PROTOCOLS

    params = {
        "page": 1,
        "size": min(limit, 100),
        "order": sort_by,
        "descending_order": True,
        "trusted": True,
        "blockchains": "ton",
        "providers": protocols,
    }

    result = swap_coffee_request("/yield/pools", params=params)

    if not result["success"]:
        return {
            "success": False,
            "error": result.get("error", "Failed to get staking pools"),
        }

    data = result["data"]
    if isinstance(data, list) and len(data) > 0:
        data = data[0]

    pools = data.get("pools", []) if isinstance(data, dict) else []
    total_count = data.get("total_count", 0) if isinstance(data, dict) else 0

    # Normalize pools
    normalized = []
    for pool in pools:
        protocol_name = pool.get("protocol", "unknown")

        # Only include actual staking protocols
        if protocol_name not in STAKING_PROTOCOLS:
            continue

        stats = pool.get("pool_statistics", {}) or {}
        tokens = pool.get("tokens", [])

        # Parse tokens
        token_info = []
        for t in tokens:
            addr_info = t.get("address", {})
            metadata = t.get("metadata", {}) or {}
            token_info.append(
                {
                    "address": addr_info.get("address")
                    if isinstance(addr_info, dict)
                    else addr_info,
                    "symbol": metadata.get("symbol", "?"),
                    "name": metadata.get("name"),
                    "decimals": metadata.get("decimals", 9),
                }
            )

        normalized.append(
            {
                "address": pool.get("address"),
                "protocol": protocol_name,
                "is_trusted": pool.get("is_trusted", False),
                "tokens": token_info,
                "base_token": token_info[0] if token_info else None,
                "liquid_token": token_info[1] if len(token_info) > 1 else None,
                "tvl_usd": stats.get("tvl_usd", 0),
                "apr": stats.get("apr", 0),
                "lp_apr": stats.get("lp_apr", 0),
                "boost_apr": stats.get("boost_apr", 0),
            }
        )

    return {
        "success": True,
        "total_count": total_count,
        "pools_count": len(normalized),
        "protocols": protocols,
        "pools": normalized,
    }


def get_pool_details(pool_address: str) -> dict:
    """
    Получает детали пула стейкинга.

    Args:
        pool_address: Адрес пула

    Returns:
        dict с деталями пула
    """
    addr_safe = _make_url_safe(pool_address)
    result = swap_coffee_request(f"/yield/pool/{addr_safe}")

    if not result["success"]:
        return {
            "success": False,
            "error": result.get("error", "Pool not found"),
            "pool_address": pool_address,
        }

    data = result["data"]

    return {
        "success": True,
        "pool_address": pool_address,
        "pool": data.get("pool"),
        "statistics": data.get("pool_statistics"),
        "raw_response": data,
    }


# =============================================================================
# User Positions
# =============================================================================


def get_user_position(pool_address: str, wallet_address: str) -> dict:
    """
    Получает позицию пользователя в пуле.

    Args:
        pool_address: Адрес пула
        wallet_address: Адрес кошелька пользователя

    Returns:
        dict с позицией пользователя
    """
    pool_safe = _make_url_safe(pool_address)
    wallet_safe = _make_url_safe(wallet_address)

    result = swap_coffee_request(f"/yield/pool/{pool_safe}/{wallet_safe}")

    if not result["success"]:
        if result.get("status_code") == 404:
            return {
                "success": True,
                "pool_address": pool_address,
                "wallet_address": wallet_address,
                "has_position": False,
                "position": None,
                "message": "No position in this pool",
            }
        return {
            "success": False,
            "error": result.get("error", "Failed to get position"),
        }

    data = result["data"]

    return {
        "success": True,
        "pool_address": pool_address,
        "wallet_address": wallet_address,
        "has_position": True,
        "position": data.get("position") or data,
        "raw_response": data,
    }


def get_all_positions(wallet_address: str) -> dict:
    """
    Получает все стейкинг позиции пользователя.

    Args:
        wallet_address: Адрес кошелька

    Returns:
        dict со всеми позициями
    """
    # First get all staking pools
    pools_result = list_staking_pools(limit=100)
    if not pools_result["success"]:
        return pools_result

    pools = pools_result.get("pools", [])
    positions = []

    for pool in pools:
        pool_addr = pool.get("address")
        if not pool_addr:
            continue

        pos_result = get_user_position(pool_addr, wallet_address)
        if pos_result.get("success") and pos_result.get("has_position"):
            positions.append({"pool": pool, "position": pos_result.get("position")})

    return {
        "success": True,
        "wallet_address": wallet_address,
        "positions_count": len(positions),
        "positions": positions,
    }


# =============================================================================
# Staking Points / Rewards
# =============================================================================


def get_staking_points(wallet_address: str) -> dict:
    """
    Получает стейкинг поинты пользователя.

    Args:
        wallet_address: Адрес кошелька

    Returns:
        dict с поинтами
    """
    addr_safe = _make_url_safe(wallet_address)

    result = swap_coffee_request(f"/staking/points/{addr_safe}")

    if not result["success"]:
        if result.get("status_code") == 404:
            return {
                "success": True,
                "wallet_address": wallet_address,
                "points": 0,
                "message": "No points found",
            }
        return {"success": False, "error": result.get("error", "Failed to get points")}

    data = result["data"]

    return {
        "success": True,
        "wallet_address": wallet_address,
        "points": data.get("points", 0),
        "rewards": data.get("rewards"),
        "raw_response": data,
    }


# =============================================================================
# Staking Transactions
# =============================================================================


def build_stake_tx(
    pool_address: str,
    wallet_address: str,
    amount: float,
) -> dict:
    """
    Строит транзакцию для стейкинга.

    Args:
        pool_address: Адрес пула
        wallet_address: Адрес кошелька
        amount: Сумма для стейкинга (в TON, не наноТОН)

    Returns:
        dict с транзакцией
    """
    pool_safe = _make_url_safe(pool_address)
    wallet_safe = _make_url_safe(wallet_address)

    # Конвертируем в наноТОН для API
    amount_nano = int(amount * 1e9)

    # Правильный формат API: request_data с yieldTypeResolver
    result = swap_coffee_request(
        f"/yield/pool/{pool_safe}/{wallet_safe}",
        method="POST",
        json_data={
            "request_data": {
                "yieldTypeResolver": "liquid_staking_stake",
                "amount": str(amount_nano),
            }
        },
    )

    if not result["success"]:
        return {
            "success": False,
            "error": result.get("error", "Failed to build stake transaction"),
        }

    data = result["data"]

    # API возвращает массив транзакций
    transactions = data if isinstance(data, list) else data.get("transactions", [data])

    # Преобразуем формат ответа для execute_staking_tx
    normalized_txs = []
    for tx in transactions:
        msg = tx.get("message", {})
        normalized_txs.append(
            {
                "address": msg.get("address"),
                "value": msg.get("value"),
                "cell": msg.get("payload_cell"),
            }
        )

    return {
        "success": True,
        "action": "stake",
        "pool_address": pool_address,
        "wallet_address": wallet_address,
        "amount": amount,
        "transactions": normalized_txs,
        "query_id": transactions[0].get("query_id") if transactions else None,
        "raw_response": data,
    }


def build_unstake_tx(
    pool_address: str,
    wallet_address: str,
    amount: Optional[float] = None,
    close_position: bool = False,
) -> dict:
    """
    Строит транзакцию для анстейкинга.

    Args:
        pool_address: Адрес пула
        wallet_address: Адрес кошелька
        amount: Сумма для вывода в TON (None = всё)
        close_position: Закрыть позицию полностью

    Returns:
        dict с транзакцией
    """
    pool_safe = _make_url_safe(pool_address)
    wallet_safe = _make_url_safe(wallet_address)

    # Правильный формат API: request_data с yieldTypeResolver
    request_data = {
        "yieldTypeResolver": "liquid_staking_unstake",
    }

    if close_position:
        request_data["close_position"] = True
    elif amount:
        # Конвертируем в наноТОН
        amount_nano = int(amount * 1e9)
        request_data["amount"] = str(amount_nano)

    result = swap_coffee_request(
        f"/yield/pool/{pool_safe}/{wallet_safe}",
        method="POST",
        json_data={"request_data": request_data},
    )

    if not result["success"]:
        return {
            "success": False,
            "error": result.get("error", "Failed to build unstake transaction"),
        }

    data = result["data"]

    # API возвращает массив транзакций
    transactions = data if isinstance(data, list) else data.get("transactions", [data])

    # Преобразуем формат ответа для execute_staking_tx
    normalized_txs = []
    for tx in transactions:
        msg = tx.get("message", {})
        normalized_txs.append(
            {
                "address": msg.get("address"),
                "value": msg.get("value"),
                "cell": msg.get("payload_cell"),
            }
        )

    return {
        "success": True,
        "action": "unstake",
        "pool_address": pool_address,
        "wallet_address": wallet_address,
        "amount": amount,
        "close_position": close_position,
        "transactions": normalized_txs,
        "query_id": transactions[0].get("query_id") if transactions else None,
        "raw_response": data,
    }


def build_extend_stake_tx(
    pool_address: str,
    wallet_address: str,
    extend_days: int,
) -> dict:
    """
    Строит транзакцию для продления стейкинга.

    Args:
        pool_address: Адрес пула
        wallet_address: Адрес кошелька
        extend_days: На сколько дней продлить

    Returns:
        dict с транзакцией
    """
    pool_safe = _make_url_safe(pool_address)
    wallet_safe = _make_url_safe(wallet_address)

    result = swap_coffee_request(
        f"/yield/pool/{pool_safe}/{wallet_safe}",
        method="POST",
        json_data={
            "action": "extend",
            "extend_seconds": extend_days * 86400,
        },
    )

    if not result["success"]:
        return {
            "success": False,
            "error": result.get("error", "Failed to build extend transaction"),
        }

    data = result["data"]

    return {
        "success": True,
        "action": "extend",
        "pool_address": pool_address,
        "wallet_address": wallet_address,
        "extend_days": extend_days,
        "transactions": data.get("transactions", []),
        "query_id": data.get("query_id"),
        "raw_response": data,
    }


# =============================================================================
# Transaction Execution
# =============================================================================


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


def execute_staking_tx(
    wallet_label: str, transactions: List[dict], password: str, confirm: bool = False
) -> dict:
    """
    Выполняет транзакции стейкинга.

    Args:
        wallet_label: Лейбл кошелька
        transactions: Список транзакций от API
        password: Пароль кошелька
        confirm: Подтверждение выполнения

    Returns:
        dict с результатом
    """
    if not TONSDK_AVAILABLE:
        return {"success": False, "error": "tonsdk not installed"}

    wallet_data = get_wallet_from_storage(wallet_label, password)
    if not wallet_data:
        return {"success": False, "error": f"Wallet not found: {wallet_label}"}

    sender_address = wallet_data["address"]
    wallet = create_wallet_instance(wallet_data)
    seqno = get_seqno(sender_address)

    signed_txs = []
    total_fee = 0

    for i, tx in enumerate(transactions):
        to_addr = tx.get("address")
        amount = int(tx.get("value", "0"))
        cell_b64 = tx.get("cell")
        send_mode = tx.get("send_mode", 3)

        if not to_addr:
            continue

        payload = None
        if cell_b64:
            try:
                cell_bytes = base64.b64decode(cell_b64)
                payload = Cell.one_from_boc(cell_bytes)
            except Exception as e:
                return {"success": False, "error": f"Failed to decode cell: {e}"}

        try:
            query = wallet.create_transfer_message(
                to_addr=to_addr,
                amount=amount,
                payload=payload,
                seqno=seqno + i,
                send_mode=send_mode,
            )
        except Exception as e:
            return {"success": False, "error": f"Failed to create transfer: {e}"}

        boc = query["message"].to_boc(False)
        boc_b64 = base64.b64encode(boc).decode("ascii")

        emulation = emulate_transaction(boc_b64)

        signed_txs.append(
            {
                "index": i,
                "to": to_addr,
                "amount_nano": amount,
                "amount_ton": amount / 1e9,
                "boc": boc_b64,
                "emulation": emulation,
            }
        )

        if emulation["success"]:
            total_fee += emulation.get("fee_nano", 0)

    result = {
        "wallet": sender_address,
        "transactions": signed_txs,
        "total_fee_nano": total_fee,
        "total_fee_ton": total_fee / 1e9,
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

        result["sent_count"] = sent_count
        result["total_transactions"] = len(signed_txs)

        if sent_count == len(signed_txs):
            result["success"] = True
            result["message"] = "Transaction executed successfully"
        else:
            result["success"] = False
            result["error"] = "Failed to send transactions"
            result["errors"] = errors
    else:
        result["success"] = True
        result["confirmed"] = False
        result["message"] = "Transaction simulated. Use --confirm to execute."

    return result


# =============================================================================
# CLI
# =============================================================================


def main():
    parser = argparse.ArgumentParser(
        description="Staking operations via swap.coffee API",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # List staking pools
  %(prog)s pools
  
  # List pools by protocol
  %(prog)s pools --protocol tonstakers
  
  # Get pool details
  %(prog)s pool --address EQCkWxfyhAkim3g2DjKQQg8T5P4g-Q1-K_jErGcDJZ4i-vqR
  
  # Get user position in pool
  %(prog)s position --pool EQCkWx... --wallet UQBvW8...
  
  # Get all positions for wallet
  %(prog)s positions --wallet UQBvW8...
  
  # Get staking points
  %(prog)s points --wallet UQBvW8...
  
  # Stake TON (simulation)
  %(prog)s stake --pool EQCkWx... --wallet main --amount 10
  
  # Stake TON (execute)
  %(prog)s stake --pool EQCkWx... --wallet main --amount 10 --confirm
  
  # Unstake partial amount
  %(prog)s unstake --pool EQCkWx... --wallet main --amount 5 --confirm
  
  # Close entire position
  %(prog)s unstake --pool EQCkWx... --wallet main --close --confirm

Supported protocols: tonstakers, stakee, bemo, bemo_v2, hipo, kton
""",
    )

    parser.add_argument(
        "--password", "-p", help="Wallet password (or WALLET_PASSWORD env)"
    )

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # --- pools ---
    pools_p = subparsers.add_parser("pools", help="List staking pools")
    pools_p.add_argument(
        "--protocol", choices=STAKING_PROTOCOLS, help="Filter by protocol"
    )
    pools_p.add_argument(
        "--sort", default="apr", choices=["apr", "tvl"], help="Sort by field"
    )
    pools_p.add_argument(
        "--limit", "-n", type=int, default=20, help="Number of results"
    )

    # --- pool ---
    pool_p = subparsers.add_parser("pool", help="Get pool details")
    pool_p.add_argument("--address", "-a", required=True, help="Pool address")

    # --- position ---
    pos_p = subparsers.add_parser("position", help="Get user position in pool")
    pos_p.add_argument("--pool", required=True, help="Pool address")
    pos_p.add_argument("--wallet", "-w", required=True, help="Wallet address")

    # --- positions ---
    positions_p = subparsers.add_parser(
        "positions", help="Get all positions for wallet"
    )
    positions_p.add_argument("--wallet", "-w", required=True, help="Wallet address")

    # --- points ---
    points_p = subparsers.add_parser("points", help="Get staking points/rewards")
    points_p.add_argument("--wallet", "-w", required=True, help="Wallet address")

    # --- stake ---
    stake_p = subparsers.add_parser("stake", help="Stake tokens")
    stake_p.add_argument("--pool", required=True, help="Pool address")
    stake_p.add_argument("--wallet", "-w", required=True, help="Wallet label")
    stake_p.add_argument(
        "--amount", "-a", type=float, required=True, help="Amount to stake"
    )
    stake_p.add_argument("--confirm", action="store_true", help="Confirm execution")

    # --- unstake ---
    unstake_p = subparsers.add_parser("unstake", help="Unstake tokens")
    unstake_p.add_argument("--pool", required=True, help="Pool address")
    unstake_p.add_argument("--wallet", "-w", required=True, help="Wallet label")
    unstake_p.add_argument("--amount", "-a", type=float, help="Amount to unstake")
    unstake_p.add_argument("--close", action="store_true", help="Close entire position")
    unstake_p.add_argument("--confirm", action="store_true", help="Confirm execution")

    # --- extend ---
    extend_p = subparsers.add_parser("extend", help="Extend staking period")
    extend_p.add_argument("--pool", required=True, help="Pool address")
    extend_p.add_argument("--wallet", "-w", required=True, help="Wallet label")
    extend_p.add_argument(
        "--days", "-d", type=int, required=True, help="Days to extend"
    )
    extend_p.add_argument("--confirm", action="store_true", help="Confirm execution")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    try:
        password = args.password or os.environ.get("WALLET_PASSWORD")

        if args.command == "pools":
            result = list_staking_pools(
                protocol=args.protocol, sort_by=args.sort, limit=args.limit
            )

        elif args.command == "pool":
            result = get_pool_details(args.address)

        elif args.command == "position":
            # Resolve wallet address
            wallet_addr = args.wallet
            if not is_valid_address(wallet_addr) and password:
                wallet_data = get_wallet_from_storage(wallet_addr, password)
                if wallet_data:
                    wallet_addr = wallet_data["address"]

            result = get_user_position(args.pool, wallet_addr)

        elif args.command == "positions":
            wallet_addr = args.wallet
            if not is_valid_address(wallet_addr) and password:
                wallet_data = get_wallet_from_storage(wallet_addr, password)
                if wallet_data:
                    wallet_addr = wallet_data["address"]

            result = get_all_positions(wallet_addr)

        elif args.command == "points":
            wallet_addr = args.wallet
            if not is_valid_address(wallet_addr) and password:
                wallet_data = get_wallet_from_storage(wallet_addr, password)
                if wallet_data:
                    wallet_addr = wallet_data["address"]

            result = get_staking_points(wallet_addr)

        elif args.command == "stake":
            if not password:
                if sys.stdin.isatty():
                    password = getpass.getpass("Wallet password: ")
                else:
                    print(json.dumps({"error": "Password required"}))
                    return sys.exit(1)

            wallet_data = get_wallet_from_storage(args.wallet, password)
            if not wallet_data:
                print(json.dumps({"error": f"Wallet not found: {args.wallet}"}))
                return sys.exit(1)

            tx_result = build_stake_tx(
                pool_address=args.pool,
                wallet_address=wallet_data["address"],
                amount=args.amount,
            )

            if not tx_result["success"]:
                result = tx_result
            elif tx_result.get("transactions"):
                result = execute_staking_tx(
                    wallet_label=args.wallet,
                    transactions=tx_result["transactions"],
                    password=password,
                    confirm=args.confirm,
                )
                result["action"] = "stake"
                result["pool_address"] = args.pool
                result["amount"] = args.amount
            else:
                result = tx_result

        elif args.command == "unstake":
            if not password:
                if sys.stdin.isatty():
                    password = getpass.getpass("Wallet password: ")
                else:
                    print(json.dumps({"error": "Password required"}))
                    return sys.exit(1)

            wallet_data = get_wallet_from_storage(args.wallet, password)
            if not wallet_data:
                print(json.dumps({"error": f"Wallet not found: {args.wallet}"}))
                return sys.exit(1)

            tx_result = build_unstake_tx(
                pool_address=args.pool,
                wallet_address=wallet_data["address"],
                amount=args.amount,
                close_position=args.close,
            )

            if not tx_result["success"]:
                result = tx_result
            elif tx_result.get("transactions"):
                result = execute_staking_tx(
                    wallet_label=args.wallet,
                    transactions=tx_result["transactions"],
                    password=password,
                    confirm=args.confirm,
                )
                result["action"] = "unstake"
                result["pool_address"] = args.pool
                result["amount"] = args.amount
                result["close_position"] = args.close
            else:
                result = tx_result

        elif args.command == "extend":
            if not password:
                if sys.stdin.isatty():
                    password = getpass.getpass("Wallet password: ")
                else:
                    print(json.dumps({"error": "Password required"}))
                    return sys.exit(1)

            wallet_data = get_wallet_from_storage(args.wallet, password)
            if not wallet_data:
                print(json.dumps({"error": f"Wallet not found: {args.wallet}"}))
                return sys.exit(1)

            tx_result = build_extend_stake_tx(
                pool_address=args.pool,
                wallet_address=wallet_data["address"],
                extend_days=args.days,
            )

            if not tx_result["success"]:
                result = tx_result
            elif tx_result.get("transactions"):
                result = execute_staking_tx(
                    wallet_label=args.wallet,
                    transactions=tx_result["transactions"],
                    password=password,
                    confirm=args.confirm,
                )
                result["action"] = "extend"
                result["pool_address"] = args.pool
                result["extend_days"] = args.days
            else:
                result = tx_result

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
