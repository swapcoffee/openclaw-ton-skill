#!/usr/bin/env python3
"""
OpenClaw TON Skill — Управление кошельками

- Создание кошельков (24-word mnemonic)
- Импорт кошельков по мнемонике
- Список кошельков с лейблами
- Получение балансов через TonAPI
- Шифрованное хранение
"""

import os
import sys
import json
import argparse
import getpass
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime

# Локальный импорт
script_dir = Path(__file__).parent
sys.path.insert(0, str(script_dir))

from utils import (
    encrypt_json,
    decrypt_json,
    ensure_skill_dir,
    tonapi_request,
    normalize_address,
    is_valid_address,
    raw_to_friendly,
    SKILL_DIR,  # noqa: F401 - used by tests via monkeypatch
    WALLETS_FILE,
)

# TON SDK для генерации кошельков
try:
    from tonsdk.contract.wallet import Wallets, WalletVersionEnum
    from tonsdk.crypto import mnemonic_new, mnemonic_is_valid

    TONSDK_AVAILABLE = True
except ImportError:
    TONSDK_AVAILABLE = False

# Альтернатива - tonutils
try:
    from tonutils.wallet import WalletV4R2
    from tonutils.utils import Address
    import nacl.signing

    TONUTILS_AVAILABLE = True
except ImportError:
    TONUTILS_AVAILABLE = False


# =============================================================================
# Wallet Storage
# =============================================================================


class WalletStorage:
    """Управление зашифрованным хранилищем кошельков."""

    def __init__(self, password: str):
        self.password = password
        self.wallets_file = WALLETS_FILE
        ensure_skill_dir()

    def load(self) -> Dict[str, Any]:
        """Загружает и дешифрует хранилище кошельков."""
        if not self.wallets_file.exists():
            return {"wallets": [], "version": 1}

        try:
            with open(self.wallets_file, "r") as f:
                encrypted = f.read().strip()
            return decrypt_json(encrypted, self.password)
        except Exception as e:
            raise ValueError(f"Failed to decrypt wallets: {e}")

    def save(self, data: Dict[str, Any]) -> bool:
        """Шифрует и сохраняет хранилище кошельков."""
        try:
            encrypted = encrypt_json(data, self.password)
            with open(self.wallets_file, "w") as f:
                f.write(encrypted)
            # Устанавливаем права только для владельца
            os.chmod(self.wallets_file, 0o600)
            return True
        except Exception as e:
            raise ValueError(f"Failed to save wallets: {e}")

    def add_wallet(self, wallet_data: dict) -> bool:
        """Добавляет кошелёк в хранилище."""
        storage = self.load()

        # Проверяем дубликаты по адресу
        for w in storage["wallets"]:
            if w.get("address") == wallet_data.get("address"):
                raise ValueError(f"Wallet already exists: {wallet_data['address']}")

        storage["wallets"].append(wallet_data)
        return self.save(storage)

    def get_wallets(self, include_secrets: bool = False) -> List[dict]:
        """Возвращает список кошельков."""
        storage = self.load()
        wallets = storage.get("wallets", [])

        if not include_secrets:
            # Убираем приватные данные
            return [
                {
                    k: v
                    for k, v in w.items()
                    if k not in ("mnemonic", "private_key", "secret_key")
                }
                for w in wallets
            ]
        return wallets

    def get_wallet(
        self, identifier: str, include_secrets: bool = False
    ) -> Optional[dict]:
        """
        Ищет кошелёк по адресу или лейблу.

        Args:
            identifier: Адрес или лейбл кошелька
            include_secrets: Включать ли приватные данные
        """
        wallets = self.get_wallets(include_secrets=include_secrets)

        for w in wallets:
            # Поиск по лейблу (case-insensitive)
            if w.get("label", "").lower() == identifier.lower():
                return w

            # Поиск по адресу (любой формат)
            wallet_addr = w.get("address", "")
            if wallet_addr == identifier:
                return w

            # Сравниваем в raw формате
            try:
                wallet_raw = normalize_address(wallet_addr, "raw")
                search_raw = normalize_address(identifier, "raw")
                if wallet_raw == search_raw:
                    return w
            except:
                pass

        return None

    def update_wallet(self, identifier: str, updates: dict) -> bool:
        """Обновляет данные кошелька."""
        storage = self.load()

        for i, w in enumerate(storage["wallets"]):
            if (
                w.get("label", "").lower() == identifier.lower()
                or w.get("address") == identifier
            ):
                storage["wallets"][i].update(updates)
                return self.save(storage)

        raise ValueError(f"Wallet not found: {identifier}")

    def remove_wallet(self, identifier: str) -> bool:
        """Удаляет кошелёк."""
        storage = self.load()

        for i, w in enumerate(storage["wallets"]):
            if (
                w.get("label", "").lower() == identifier.lower()
                or w.get("address") == identifier
            ):
                del storage["wallets"][i]
                return self.save(storage)

        raise ValueError(f"Wallet not found: {identifier}")


# =============================================================================
# Wallet Generation
# =============================================================================


def generate_mnemonic() -> List[str]:
    """Генерирует новую мнемонику (24 слова)."""
    if TONSDK_AVAILABLE:
        return mnemonic_new(24)
    else:
        raise RuntimeError("No TON SDK available. Install: pip install tonsdk")


def validate_mnemonic(mnemonic: List[str]) -> bool:
    """Проверяет валидность мнемоники."""
    if TONSDK_AVAILABLE:
        return mnemonic_is_valid(mnemonic)
    return len(mnemonic) == 24  # Базовая проверка


def mnemonic_to_wallet(mnemonic: List[str], version: str = "v4r2") -> dict:
    """
    Создаёт кошелёк из мнемоники.

    Args:
        mnemonic: Список из 24 слов
        version: Версия кошелька (v3r2, v4r2)

    Returns:
        dict с address, public_key, private_key
    """
    if not TONSDK_AVAILABLE:
        raise RuntimeError("tonsdk not available. Install: pip install tonsdk")

    version_map = {
        "v3r2": WalletVersionEnum.v3r2,
        "v4r2": WalletVersionEnum.v4r2,
    }

    wallet_version = version_map.get(version.lower(), WalletVersionEnum.v4r2)

    mnemonics, pub_k, priv_k, wallet = Wallets.from_mnemonics(
        mnemonic, wallet_version, workchain=0
    )

    # Получаем адрес
    address_raw = wallet.address.to_string(True, True, False)  # raw format
    address_friendly = wallet.address.to_string(True, True, True)  # user-friendly

    return {
        "address": address_friendly,
        "address_raw": address_raw,
        "public_key": pub_k.hex(),
        "private_key": priv_k.hex(),
        "version": version.lower(),
    }


# =============================================================================
# TonAPI Integration
# =============================================================================


def _make_url_safe(address: str) -> str:
    """Конвертирует адрес в URL-safe формат (заменяет +/ на -_)."""
    return address.replace("+", "-").replace("/", "_")


def _normalize_symbol(symbol: str) -> str:
    """Нормализует символ жетона (USD₮ → USDT, ₿TC → BTC)."""
    if not symbol:
        return symbol
    return symbol.replace("₮", "T").replace("₿", "B").replace("₴", "S")


def get_account_info(address: str) -> dict:
    """
    Получает информацию об аккаунте через TonAPI.

    Returns:
        dict с balance, status, и другими данными
    """
    # TonAPI требует URL-safe адреса (- и _ вместо + и /)
    try:
        if ":" in address:
            addr = raw_to_friendly(address)
        else:
            addr = _make_url_safe(address)
    except:
        addr = _make_url_safe(address)

    result = tonapi_request(f"/accounts/{addr}")

    if result["success"]:
        data = result["data"]
        return {
            "success": True,
            "address": data.get("address", address),
            "balance": int(data.get("balance", 0)),
            "balance_ton": int(data.get("balance", 0)) / 1e9,
            "status": data.get("status", "unknown"),
            "last_activity": data.get("last_activity"),
            "interfaces": data.get("interfaces", []),
            "name": data.get("name"),
            "is_wallet": data.get("is_wallet", False),
        }
    else:
        return {
            "success": False,
            "error": result.get("error", "Unknown error"),
            "address": address,
        }


def get_jetton_balances(address: str) -> dict:
    """
    Получает балансы жетонов (Jettons) для аккаунта.

    Returns:
        dict со списком жетонов и их балансов
    """
    # TonAPI требует URL-safe адреса (- и _ вместо + и /)
    try:
        if ":" in address:
            addr = raw_to_friendly(address)
        else:
            addr = _make_url_safe(address)
    except:
        addr = _make_url_safe(address)

    result = tonapi_request(f"/accounts/{addr}/jettons")

    if result["success"]:
        balances = result["data"].get("balances", [])
        jettons = []

        for item in balances:
            jetton = item.get("jetton", {})
            raw_symbol = jetton.get("symbol", "???")
            jettons.append(
                {
                    "symbol": _normalize_symbol(raw_symbol),
                    "symbol_raw": raw_symbol,
                    "name": jetton.get("name", "Unknown"),
                    "balance": item.get("balance", "0"),
                    "decimals": jetton.get("decimals", 9),
                    "balance_human": float(item.get("balance", 0))
                    / (10 ** jetton.get("decimals", 9)),
                    "price_usd": jetton.get("price", {}).get("prices", {}).get("USD"),
                    "jetton_address": jetton.get("address"),
                    "verified": jetton.get("verification") == "whitelist",
                }
            )

        return {
            "success": True,
            "address": address,
            "jettons": jettons,
            "count": len(jettons),
        }
    else:
        return {
            "success": False,
            "error": result.get("error", "Unknown error"),
            "address": address,
        }


def get_full_balance(address: str) -> dict:
    """
    Получает полный баланс: TON + все жетоны.

    Returns:
        dict с TON балансом и списком жетонов
    """
    account = get_account_info(address)
    jettons = get_jetton_balances(address)

    if not account["success"]:
        return account

    result = {
        "success": True,
        "address": address,
        "ton": {"balance": account["balance_ton"], "balance_nano": account["balance"]},
        "jettons": jettons.get("jettons", []) if jettons["success"] else [],
        "status": account["status"],
    }

    # Считаем общую стоимость в USD (если есть цены)
    total_usd = 0

    # TODO: добавить цену TON
    for j in result["jettons"]:
        if j.get("price_usd") and j.get("balance_human"):
            total_usd += float(j["price_usd"]) * float(j["balance_human"])

    result["total_usd"] = total_usd

    return result


# =============================================================================
# CLI Commands
# =============================================================================


def cmd_create(args, password: str) -> dict:
    """Создаёт новый кошелёк."""
    storage = WalletStorage(password)

    # Генерируем мнемонику
    mnemonic = generate_mnemonic()

    # Создаём кошелёк
    wallet_data = mnemonic_to_wallet(mnemonic, args.version)

    # Добавляем метаданные
    wallet_data["mnemonic"] = mnemonic
    wallet_data["label"] = args.label or f"wallet_{len(storage.get_wallets()) + 1}"
    wallet_data["created_at"] = datetime.utcnow().isoformat()

    # Сохраняем
    storage.add_wallet(wallet_data)

    # Возвращаем (без приватных данных для вывода)
    return {
        "success": True,
        "action": "created",
        "wallet": {
            "address": wallet_data["address"],
            "label": wallet_data["label"],
            "version": wallet_data["version"],
        },
        "mnemonic": mnemonic,  # ВАЖНО: показываем только при создании!
        "warning": "⚠️ СОХРАНИ МНЕМОНИКУ! Она показывается только один раз.",
    }


def cmd_import(args, password: str) -> dict:
    """Импортирует кошелёк по мнемонике."""
    storage = WalletStorage(password)

    # Парсим мнемонику
    mnemonic = args.mnemonic.strip().split()

    if len(mnemonic) != 24:
        return {
            "success": False,
            "error": f"Мнемоника должна быть 24 слова, получено {len(mnemonic)}",
        }

    if not validate_mnemonic(mnemonic):
        return {"success": False, "error": "Невалидная мнемоника"}

    # Создаём кошелёк
    wallet_data = mnemonic_to_wallet(mnemonic, args.version)

    # Добавляем метаданные
    wallet_data["mnemonic"] = mnemonic
    wallet_data["label"] = args.label or f"imported_{len(storage.get_wallets()) + 1}"
    wallet_data["created_at"] = datetime.utcnow().isoformat()
    wallet_data["imported"] = True

    # Сохраняем
    try:
        storage.add_wallet(wallet_data)
    except ValueError as e:
        return {"success": False, "error": str(e)}

    return {
        "success": True,
        "action": "imported",
        "wallet": {
            "address": wallet_data["address"],
            "label": wallet_data["label"],
            "version": wallet_data["version"],
        },
    }


def cmd_list(args, password: str) -> dict:
    """Список всех кошельков с балансами."""
    storage = WalletStorage(password)
    wallets = storage.get_wallets(include_secrets=False)

    result_wallets = []

    for w in wallets:
        wallet_info = {
            "label": w.get("label", ""),
            "address": w.get("address", ""),
            "version": w.get("version", "v4r2"),
            "created_at": w.get("created_at"),
        }

        # Получаем баланс если нужно
        if args.balances:
            balance = get_account_info(w["address"])
            if balance["success"]:
                wallet_info["balance_ton"] = balance["balance_ton"]
                wallet_info["status"] = balance["status"]
            else:
                wallet_info["balance_ton"] = None
                wallet_info["balance_error"] = balance.get("error")

        result_wallets.append(wallet_info)

    return {"success": True, "count": len(result_wallets), "wallets": result_wallets}


def cmd_balance(args, password: str) -> dict:
    """Получает баланс кошелька."""
    storage = WalletStorage(password)

    # Ищем кошелёк
    wallet = storage.get_wallet(args.wallet)

    if not wallet:
        # Может это просто адрес (не из хранилища)?
        if is_valid_address(args.wallet):
            address = args.wallet
        else:
            return {"success": False, "error": f"Кошелёк не найден: {args.wallet}"}
    else:
        address = wallet["address"]

    # Получаем баланс
    if args.full:
        return get_full_balance(address)
    else:
        return get_account_info(address)


def cmd_remove(args, password: str) -> dict:
    """Удаляет кошелёк из хранилища."""
    storage = WalletStorage(password)

    # Проверяем что кошелёк существует
    wallet = storage.get_wallet(args.wallet)
    if not wallet:
        return {"success": False, "error": f"Кошелёк не найден: {args.wallet}"}

    storage.remove_wallet(args.wallet)

    return {"success": True, "action": "removed", "wallet": wallet["address"]}


def cmd_label(args, password: str) -> dict:
    """Изменяет лейбл кошелька."""
    storage = WalletStorage(password)

    wallet = storage.get_wallet(args.wallet)
    if not wallet:
        return {"success": False, "error": f"Кошелёк не найден: {args.wallet}"}

    old_label = wallet.get("label", "")
    storage.update_wallet(args.wallet, {"label": args.new_label})

    return {
        "success": True,
        "action": "renamed",
        "address": wallet["address"],
        "old_label": old_label,
        "new_label": args.new_label,
    }


def cmd_export(args, password: str) -> dict:
    """Экспортирует мнемонику кошелька."""
    storage = WalletStorage(password)

    # Нужны приватные данные
    wallet = storage.get_wallet(args.wallet, include_secrets=True)
    if not wallet:
        return {"success": False, "error": f"Кошелёк не найден: {args.wallet}"}

    return {
        "success": True,
        "address": wallet["address"],
        "label": wallet.get("label", ""),
        "mnemonic": wallet.get("mnemonic", []),
        "warning": "⚠️ НИКОГДА не передавай мнемонику третьим лицам!",
    }


# =============================================================================
# Main
# =============================================================================


def main():
    parser = argparse.ArgumentParser(
        description="TON Wallet Management",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s create --label "trading"
  %(prog)s import --mnemonic "word1 word2 ..." --label "imported"
  %(prog)s list --balances
  %(prog)s balance trading
  %(prog)s balance --full trading
""",
    )

    parser.add_argument(
        "--password", "-p", help="Encryption password (or use WALLET_PASSWORD env)"
    )

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # --- create ---
    create_p = subparsers.add_parser("create", help="Create new wallet")
    create_p.add_argument("--label", "-l", help="Wallet label/name")
    create_p.add_argument(
        "--version",
        "-v",
        default="v4r2",
        choices=["v3r2", "v4r2"],
        help="Wallet version",
    )

    # --- import ---
    import_p = subparsers.add_parser("import", help="Import wallet from mnemonic")
    import_p.add_argument(
        "--mnemonic", "-m", required=True, help="24-word mnemonic (space-separated)"
    )
    import_p.add_argument("--label", "-l", help="Wallet label")
    import_p.add_argument(
        "--version",
        "-v",
        default="v4r2",
        choices=["v3r2", "v4r2"],
        help="Wallet version",
    )

    # --- list ---
    list_p = subparsers.add_parser("list", help="List all wallets")
    list_p.add_argument(
        "--balances", "-b", action="store_true", help="Include balances (slower)"
    )

    # --- balance ---
    balance_p = subparsers.add_parser("balance", help="Get wallet balance")
    balance_p.add_argument("wallet", help="Wallet label or address")
    balance_p.add_argument("--full", "-f", action="store_true", help="Include jettons")

    # --- remove ---
    remove_p = subparsers.add_parser("remove", help="Remove wallet from storage")
    remove_p.add_argument("wallet", help="Wallet label or address")

    # --- label ---
    label_p = subparsers.add_parser("label", help="Change wallet label")
    label_p.add_argument("wallet", help="Current wallet label or address")
    label_p.add_argument("new_label", help="New label")

    # --- export ---
    export_p = subparsers.add_parser("export", help="Export wallet mnemonic (DANGER!)")
    export_p.add_argument("wallet", help="Wallet label or address")

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
        sys.exit(1)

    # Получаем пароль
    password = args.password or os.environ.get("WALLET_PASSWORD")

    if not password:
        # Запрашиваем интерактивно если терминал
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
            sys.exit(1)

    # Выполняем команду
    try:
        commands = {
            "create": cmd_create,
            "import": cmd_import,
            "list": cmd_list,
            "balance": cmd_balance,
            "remove": cmd_remove,
            "label": cmd_label,
            "export": cmd_export,
        }

        result = commands[args.command](args, password)
        print(json.dumps(result, indent=2, ensure_ascii=False))

    except ValueError as e:
        print(json.dumps({"error": str(e)}, indent=2))
        sys.exit(1)
    except Exception as e:
        print(json.dumps({"error": f"Unexpected error: {e}"}, indent=2))
        sys.exit(1)


if __name__ == "__main__":
    main()
