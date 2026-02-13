#!/usr/bin/env python3
"""
OpenClaw TON Skill — Переводы TON и жетонов

- Отправка TON (address / .ton домен)
- Отправка жетонов (Jetton transfer)
- Эмуляция транзакции перед отправкой
- Подписание и отправка через TonAPI
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

from utils import tonapi_request, normalize_address, raw_to_friendly  # noqa: E402
from dns import resolve_address  # noqa: E402
from wallet import WalletStorage, get_jetton_balances  # noqa: E402


def _make_url_safe(address: str) -> str:
    """Конвертирует адрес в URL-safe формат (заменяет +/ на -_)."""
    return address.replace("+", "-").replace("/", "_")


# TON SDK
try:
    from tonsdk.contract.wallet import Wallets, WalletVersionEnum
    from tonsdk.utils import to_nano, from_nano, bytes_to_b64str, b64str_to_bytes  # noqa: F401
    from tonsdk.boc import Cell  # noqa: F401

    TONSDK_AVAILABLE = True
except ImportError:
    TONSDK_AVAILABLE = False


# =============================================================================
# Constants
# =============================================================================

# Jetton Transfer opcode
JETTON_TRANSFER_OPCODE = 0x0F8A7EA5

# TON DNS root contract (для резолва)
TON_DNS_ROOT = "EQC3dNlesgVD8YbAazcauIrXBPfiVhMMr5YYk2in0Mtsz0Bz"


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


# =============================================================================
# Transaction Building
# =============================================================================


def get_account_status(address: str) -> str:
    """
    Получает статус аккаунта (active, uninit, nonexist).

    Args:
        address: Адрес аккаунта

    Returns:
        Статус: "active", "uninit", "nonexist", или "unknown"
    """
    addr = _make_url_safe(address)
    result = tonapi_request(f"/accounts/{addr}")

    if result["success"]:
        return result["data"].get("status", "unknown")

    # Если ошибка 404 - аккаунт не существует
    if result.get("status_code") == 404:
        return "nonexist"

    return "unknown"


def build_ton_transfer(
    wallet,
    to_address: str,
    amount_nano: int,
    comment: Optional[str] = None,
    seqno: int = 0,
    bounce: bool = True,
) -> bytes:
    """
    Строит транзакцию перевода TON.

    Args:
        wallet: Инстанс кошелька (tonsdk)
        to_address: Адрес получателя (friendly)
        amount_nano: Сумма в нано-TON
        comment: Комментарий к переводу
        seqno: Sequence number кошелька
        bounce: Bounce флаг (False для неинициализированных кошельков)

    Returns:
        bytes BOC (подписанная транзакция)
    """
    from tonsdk.utils import Address

    # Создаём payload с комментарием если есть
    payload = None
    if comment:
        # Комментарий — это Cell с opcode 0 и строкой
        from tonsdk.boc import Cell

        payload = Cell()
        payload.bits.write_uint(0, 32)  # opcode для комментария
        payload.bits.write_string(comment)

    # Конвертируем адрес с правильным bounce флагом
    # Для неинициализированных кошельков bounce должен быть False
    recipient_addr = Address(to_address)

    # Если bounce=False, конвертируем в non-bounceable формат
    if not bounce:
        # Получаем raw адрес и конвертируем в non-bounceable friendly
        raw_addr = f"{recipient_addr.wc}:{recipient_addr.hash_part.hex()}"
        to_address = raw_to_friendly(raw_addr, bounceable=False)

    # Создаём transfer
    query = wallet.create_transfer_message(
        to_addr=to_address, amount=amount_nano, payload=payload, seqno=seqno
    )

    # Возвращаем BOC
    return query["message"].to_boc(False)


def build_jetton_transfer(
    wallet,
    jetton_wallet_address: str,
    to_address: str,
    amount: int,
    forward_amount: int = 1,
    comment: Optional[str] = None,
    seqno: int = 0,
) -> bytes:
    """
    Строит транзакцию перевода Jetton.

    Args:
        wallet: Инстанс кошелька (tonsdk)
        jetton_wallet_address: Адрес жетон-кошелька отправителя
        to_address: Адрес получателя (кому отправить)
        amount: Количество жетонов (в минимальных единицах)
        forward_amount: Сколько TON форвардить получателю
        comment: Комментарий
        seqno: Sequence number

    Returns:
        bytes BOC
    """
    from tonsdk.boc import Cell
    from tonsdk.utils import Address

    # Строим payload для jetton transfer
    # https://github.com/ton-blockchain/TEPs/blob/master/text/0074-jettons-standard.md

    payload = Cell()
    payload.bits.write_uint(JETTON_TRANSFER_OPCODE, 32)  # op
    payload.bits.write_uint(0, 64)  # query_id
    payload.bits.write_coins(amount)  # amount of jettons
    payload.bits.write_address(Address(to_address))  # destination
    payload.bits.write_address(
        Address(wallet.address.to_string())
    )  # response_destination (excess back to sender)
    payload.bits.write_bit(0)  # custom_payload = null
    payload.bits.write_coins(forward_amount)  # forward_ton_amount

    # forward_payload (комментарий)
    if comment:
        forward_payload = Cell()
        forward_payload.bits.write_uint(0, 32)  # text comment opcode
        forward_payload.bits.write_string(comment)
        payload.bits.write_bit(1)  # forward_payload in ref
        payload.refs.append(forward_payload)
    else:
        payload.bits.write_bit(0)  # forward_payload in-place (empty)

    # Создаём транзакцию на jetton wallet
    # Нужно отправить ~0.05 TON для покрытия комиссии
    query = wallet.create_transfer_message(
        to_addr=jetton_wallet_address,
        amount=to_nano(0.05, "ton"),  # 0.05 TON для газа
        payload=payload,
        seqno=seqno,
    )

    return query["message"].to_boc(False)


# =============================================================================
# Get Seqno
# =============================================================================


def get_seqno(address: str) -> int:
    """Получает текущий seqno кошелька."""
    addr = _make_url_safe(address)
    result = tonapi_request(f"/wallet/{addr}/seqno")

    if result["success"]:
        return result["data"].get("seqno", 0)

    # Если кошелёк не развёрнут — seqno = 0
    return 0


# =============================================================================
# Get Jetton Wallet Address
# =============================================================================


def get_jetton_wallet_address(owner_address: str, jetton_master: str) -> Optional[str]:
    """
    Получает адрес jetton-кошелька для владельца.

    Args:
        owner_address: Адрес владельца
        jetton_master: Адрес мастер-контракта жетона

    Returns:
        Адрес jetton-кошелька или None
    """
    # Нормализуем адреса
    try:
        owner = normalize_address(owner_address, "friendly")
        master = normalize_address(jetton_master, "friendly")
    except Exception:
        owner = owner_address
        master = jetton_master

    result = tonapi_request(f"/jettons/{master}/holders", params={"limit": 1000})

    # Альтернативный подход — через account jettons
    result = tonapi_request(f"/accounts/{owner}/jettons/{master}")

    if result["success"]:
        return result["data"].get("wallet_address", {}).get("address")

    # Fallback: ищем в списке жетонов аккаунта
    jettons = get_jetton_balances(owner)
    if jettons["success"]:
        for j in jettons.get("jettons", []):
            if normalize_address(
                j.get("jetton_address", ""), "raw"
            ) == normalize_address(master, "raw"):
                # Нужно получить wallet address через другой endpoint
                pass

    return None


# =============================================================================
# Emulation
# =============================================================================


def emulate_transfer(boc_b64: str, wallet_address: str) -> dict:
    """
    Эмулирует транзакцию через TonAPI.

    Args:
        boc_b64: BOC в base64
        wallet_address: Адрес кошелька

    Returns:
        dict с результатом эмуляции (комиссия, изменения балансов)
    """
    # TonAPI /v2/wallet/emulate
    result = tonapi_request(
        "/wallet/emulate", method="POST", json_data={"boc": boc_b64}
    )

    if not result["success"]:
        # Пробуем альтернативный endpoint
        result = tonapi_request(
            "/v2/events/emulate", method="POST", json_data={"boc": boc_b64}
        )

    if not result["success"]:
        return {"success": False, "error": result.get("error", "Emulation failed")}

    data = result["data"]

    # Парсим результат
    event = data.get("event", data)
    actions = event.get("actions", [])

    # Считаем комиссии
    extra = event.get("extra", 0)
    fee = abs(extra) if extra < 0 else 0

    # Собираем изменения балансов
    balance_changes = []

    for action in actions:
        action_type = action.get("type")
        status = action.get("status", "ok")

        if action_type == "TonTransfer":
            ton_transfer = action.get("TonTransfer", {})
            balance_changes.append(
                {
                    "type": "ton_transfer",
                    "status": status,
                    "sender": ton_transfer.get("sender", {}).get("address"),
                    "recipient": ton_transfer.get("recipient", {}).get("address"),
                    "amount": ton_transfer.get("amount", 0),
                    "amount_ton": int(ton_transfer.get("amount", 0)) / 1e9,
                    "comment": ton_transfer.get("comment"),
                }
            )

        elif action_type == "JettonTransfer":
            jetton_transfer = action.get("JettonTransfer", {})
            jetton = jetton_transfer.get("jetton", {})
            decimals = jetton.get("decimals", 9)
            amount = int(jetton_transfer.get("amount", 0))

            balance_changes.append(
                {
                    "type": "jetton_transfer",
                    "status": status,
                    "sender": jetton_transfer.get("sender", {}).get("address"),
                    "recipient": jetton_transfer.get("recipient", {}).get("address"),
                    "amount": amount,
                    "amount_human": amount / (10**decimals),
                    "jetton_symbol": jetton.get("symbol"),
                    "jetton_name": jetton.get("name"),
                    "jetton_address": jetton.get("address"),
                }
            )

    return {
        "success": True,
        "fee_nano": fee,
        "fee_ton": fee / 1e9,
        "actions": balance_changes,
        "actions_count": len(actions),
        "risk": event.get("risk", {}),
        "raw_response": data,
    }


# =============================================================================
# Send Transaction
# =============================================================================


def send_transaction(boc_b64: str) -> dict:
    """
    Отправляет подписанную транзакцию в сеть.

    Args:
        boc_b64: BOC в base64

    Returns:
        dict с результатом (hash транзакции или ошибка)
    """
    result = tonapi_request(
        "/blockchain/message", method="POST", json_data={"boc": boc_b64}
    )

    if not result["success"]:
        return {
            "success": False,
            "error": result.get("error", "Failed to send transaction"),
        }

    return {
        "success": True,
        "message": "Transaction sent",
        "raw_response": result.get("data"),
    }


# =============================================================================
# High-Level Transfer Functions
# =============================================================================


def transfer_ton(
    from_wallet: str,
    to_address: str,
    amount_ton: float,
    *,
    password: str,
    comment: Optional[str] = None,
    confirm: bool = False,
) -> dict:
    """
    Переводит TON с одного кошелька на другой.

    Args:
        from_wallet: Лейбл или адрес кошелька-отправителя
        to_address: Адрес или .ton домен получателя
        amount_ton: Сумма в TON
        comment: Комментарий
        password: Пароль от хранилища
        confirm: Выполнить перевод (иначе только эмуляция)

    Returns:
        dict с результатом эмуляции или отправки
    """
    if not TONSDK_AVAILABLE:
        return {"success": False, "error": "tonsdk not installed"}

    # Валидация суммы
    if amount_ton is None or amount_ton <= 0:
        return {"success": False, "error": "Amount must be positive"}

    # 1. Резолвим адрес получателя
    resolved = resolve_address(to_address)
    if not resolved["success"]:
        return {
            "success": False,
            "error": f"Cannot resolve recipient: {resolved.get('error')}",
        }
    recipient = resolved["address"]

    # 2. Получаем кошелёк отправителя
    wallet_data = get_wallet_from_storage(from_wallet, password)
    if not wallet_data:
        return {"success": False, "error": f"Wallet not found: {from_wallet}"}

    wallet = create_wallet_instance(wallet_data)
    sender_address = wallet_data["address"]

    # 3. Получаем seqno
    seqno = get_seqno(sender_address)

    # 4. Проверяем статус получателя для определения bounce
    recipient_status = get_account_status(recipient)
    # Для неинициализированных или несуществующих аккаунтов используем bounce=False
    bounce = recipient_status not in ("uninit", "nonexist")

    # 5. Строим транзакцию
    amount_nano = int(amount_ton * 1e9)
    boc = build_ton_transfer(
        wallet=wallet,
        to_address=recipient,
        amount_nano=amount_nano,
        comment=comment,
        seqno=seqno,
        bounce=bounce,
    )
    boc_b64 = base64.b64encode(boc).decode("ascii")

    # 6. Эмулируем
    emulation = emulate_transfer(boc_b64, sender_address)

    result = {
        "action": "transfer_ton",
        "from": sender_address,
        "to": recipient,
        "to_input": to_address,
        "is_domain": resolved.get("is_domain", False),
        "amount_ton": amount_ton,
        "amount_nano": amount_nano,
        "comment": comment,
        "recipient_status": recipient_status,
        "bounce": bounce,
        "emulation": emulation,
    }

    if not emulation["success"]:
        result["success"] = False
        result["error"] = emulation.get("error", "Emulation failed")
        return result

    result["fee_ton"] = emulation["fee_ton"]
    result["total_cost_ton"] = amount_ton + emulation["fee_ton"]

    # 7. Если --confirm — отправляем
    if confirm:
        send_result = send_transaction(boc_b64)
        result["sent"] = send_result["success"]
        if send_result["success"]:
            result["success"] = True
            result["message"] = "Transaction sent successfully"
        else:
            result["success"] = False
            result["error"] = send_result.get("error", "Failed to send")
    else:
        result["success"] = True
        result["confirmed"] = False
        result["message"] = "Emulation successful. Use --confirm to send."

    return result


def transfer_jetton(
    from_wallet: str,
    to_address: str,
    jetton: str,
    amount: float,
    *,
    password: str,
    comment: Optional[str] = None,
    confirm: bool = False,
) -> dict:
    """
    Переводит жетоны (Jetton) на другой адрес.

    Args:
        from_wallet: Лейбл или адрес кошелька-отправителя
        to_address: Адрес или .ton домен получателя
        jetton: Символ или адрес жетона
        amount: Количество жетонов (человекочитаемое)
        comment: Комментарий
        password: Пароль
        confirm: Подтвердить отправку

    Returns:
        dict с результатом
    """
    if not TONSDK_AVAILABLE:
        return {"success": False, "error": "tonsdk not installed"}

    # Валидация суммы
    if amount is None or amount <= 0:
        return {"success": False, "error": "Amount must be positive"}

    # Валидация jetton
    if not jetton or not jetton.strip():
        return {"success": False, "error": "Jetton symbol or address is required"}

    # 1. Резолвим получателя
    resolved = resolve_address(to_address)
    if not resolved["success"]:
        return {
            "success": False,
            "error": f"Cannot resolve recipient: {resolved.get('error')}",
        }
    recipient = resolved["address"]

    # 2. Получаем кошелёк
    wallet_data = get_wallet_from_storage(from_wallet, password)
    if not wallet_data:
        return {"success": False, "error": f"Wallet not found: {from_wallet}"}

    wallet = create_wallet_instance(wallet_data)
    sender_address = wallet_data["address"]

    # 3. Находим jetton wallet и информацию о жетоне
    jettons = get_jetton_balances(sender_address)
    if not jettons["success"]:
        return {"success": False, "error": "Failed to get jetton balances"}

    # Нормализация символа (USD₮ → USDT и т.п.)
    def normalize_symbol(s):
        return s.upper().replace("₮", "T").replace("₿", "B").strip()

    target_jetton = None
    jetton_normalized = normalize_symbol(jetton)
    for j in jettons.get("jettons", []):
        # Ищем по символу или адресу
        if normalize_symbol(j.get("symbol", "")) == jetton_normalized:
            target_jetton = j
            break
        if j.get("jetton_address") == jetton:
            target_jetton = j
            break
        try:
            if normalize_address(
                j.get("jetton_address", ""), "raw"
            ) == normalize_address(jetton, "raw"):
                target_jetton = j
                break
        except Exception:
            pass

    if not target_jetton:
        return {"success": False, "error": f"Jetton not found in wallet: {jetton}"}

    # Получаем jetton wallet address
    jetton_master = target_jetton["jetton_address"]
    decimals = target_jetton.get("decimals", 9)

    # TonAPI endpoint для получения jetton wallet
    sender_safe = _make_url_safe(sender_address)
    master_safe = _make_url_safe(jetton_master)
    jw_result = tonapi_request(f"/accounts/{sender_safe}/jettons/{master_safe}")
    if not jw_result["success"]:
        return {"success": False, "error": "Failed to get jetton wallet address"}

    jetton_wallet_address = jw_result["data"].get("wallet_address", {}).get("address")
    if not jetton_wallet_address:
        return {"success": False, "error": "Jetton wallet not found"}

    # 4. Конвертируем amount
    amount_raw = int(amount * (10**decimals))

    # Проверяем баланс
    balance_raw = int(target_jetton.get("balance", 0))
    if amount_raw > balance_raw:
        return {
            "success": False,
            "error": f"Insufficient jetton balance. Have: {target_jetton['balance_human']}, need: {amount}",
        }

    # 5. Получаем seqno
    seqno = get_seqno(sender_address)

    # 6. Строим транзакцию
    boc = build_jetton_transfer(
        wallet=wallet,
        jetton_wallet_address=raw_to_friendly(jetton_wallet_address)
        if ":" in jetton_wallet_address
        else jetton_wallet_address,
        to_address=recipient,
        amount=amount_raw,
        forward_amount=1,  # 1 нано-TON для уведомления
        comment=comment,
        seqno=seqno,
    )
    boc_b64 = base64.b64encode(boc).decode("ascii")

    # 7. Эмулируем
    emulation = emulate_transfer(boc_b64, sender_address)

    result = {
        "action": "transfer_jetton",
        "from": sender_address,
        "to": recipient,
        "to_input": to_address,
        "jetton_symbol": target_jetton.get("symbol"),
        "jetton_name": target_jetton.get("name"),
        "jetton_address": jetton_master,
        "amount": amount,
        "amount_raw": amount_raw,
        "decimals": decimals,
        "comment": comment,
        "emulation": emulation,
    }

    if not emulation["success"]:
        result["success"] = False
        result["error"] = emulation.get("error", "Emulation failed")
        return result

    result["fee_ton"] = emulation.get("fee_ton", 0.05)

    # 8. Отправляем если confirm
    if confirm:
        send_result = send_transaction(boc_b64)
        result["sent"] = send_result["success"]
        if send_result["success"]:
            result["success"] = True
            result["message"] = "Jetton transfer sent successfully"
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
        description="TON and Jetton transfers",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Эмуляция перевода TON (без отправки)
  %(prog)s ton --from trading --to wallet.ton --amount 5
  
  # Перевод TON с подтверждением
  %(prog)s ton --from trading --to UQBvW8... --amount 5 --confirm
  
  # Перевод с комментарием
  %(prog)s ton --from main --to UQBvW8... --amount 1 --comment "Thanks!" --confirm
  
  # Эмуляция перевода USDT
  %(prog)s jetton --from trading --to wallet.ton --jetton USDT --amount 100
  
  # Перевод USDT с подтверждением
  %(prog)s jetton --from trading --to UQBvW8... --jetton USDT --amount 100 --confirm
""",
    )

    parser.add_argument(
        "--password", "-p", help="Wallet password (or WALLET_PASSWORD env)"
    )

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # --- ton ---
    ton_p = subparsers.add_parser("ton", help="Transfer TON")
    ton_p.add_argument(
        "--from",
        "-f",
        dest="from_wallet",
        required=True,
        help="Sender wallet (label or address)",
    )
    ton_p.add_argument(
        "--to", "-t", required=True, help="Recipient (address or .ton domain)"
    )
    ton_p.add_argument(
        "--amount", "-a", type=float, required=True, help="Amount in TON"
    )
    ton_p.add_argument("--comment", "-c", help="Transfer comment")
    ton_p.add_argument(
        "--confirm",
        action="store_true",
        help="Confirm and send (otherwise just emulate)",
    )

    # --- jetton ---
    jetton_p = subparsers.add_parser("jetton", help="Transfer Jetton")
    jetton_p.add_argument(
        "--from", "-f", dest="from_wallet", required=True, help="Sender wallet"
    )
    jetton_p.add_argument(
        "--to", "-t", required=True, help="Recipient (address or .ton domain)"
    )
    jetton_p.add_argument(
        "--jetton", "-j", required=True, help="Jetton symbol or address"
    )
    jetton_p.add_argument("--amount", "-a", type=float, required=True, help="Amount")
    jetton_p.add_argument("--comment", "-c", help="Transfer comment")
    jetton_p.add_argument("--confirm", action="store_true", help="Confirm and send")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    # Проверяем зависимости
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

    # Получаем пароль
    password = args.password or os.environ.get("WALLET_PASSWORD")
    if not password:
        if sys.stdin.isatty():
            password = getpass.getpass("Wallet password: ")
        else:
            print(
                json.dumps(
                    {
                        "error": "Password required. Use --password or WALLET_PASSWORD env"
                    }
                )
            )
            return sys.exit(1)

    try:
        if args.command == "ton":
            result = transfer_ton(
                from_wallet=args.from_wallet,
                to_address=args.to,
                amount_ton=args.amount,
                comment=args.comment,
                password=password,
                confirm=args.confirm,
            )

        elif args.command == "jetton":
            result = transfer_jetton(
                from_wallet=args.from_wallet,
                to_address=args.to,
                jetton=args.jetton,
                amount=args.amount,
                comment=args.comment,
                password=password,
                confirm=args.confirm,
            )

        else:
            result = {"error": f"Unknown command: {args.command}"}

        print(json.dumps(result, indent=2, ensure_ascii=False))

        # Exit code based on success
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
