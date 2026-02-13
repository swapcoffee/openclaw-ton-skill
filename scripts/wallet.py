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
import time
import multiprocessing as mp
from multiprocessing.synchronize import Event
from multiprocessing.sharedctypes import Synchronized
from multiprocessing.queues import Queue
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime, UTC

# Локальный импорт
script_dir = Path(__file__).parent
sys.path.insert(0, str(script_dir))

from utils import (  # noqa: E402
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
    from tonutils.wallet import WalletV4R2  # noqa: F401
    from tonutils.utils import Address  # noqa: F401
    import nacl.signing  # noqa: F401

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
            except Exception:
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
    except Exception:
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
    except Exception:
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
# Vanity Address Generation
# =============================================================================

# Global flag for graceful shutdown
_vanity_stop_event = None


def _vanity_worker(
    worker_id: int,
    pattern: str,
    match_mode: str,
    case_sensitive: bool,
    result_queue: Queue,
    counter: Synchronized,
    stop_event: Event,
    version: str = "v4r2",
) -> None:
    """
    Worker process for vanity address generation.

    Args:
        worker_id: Worker ID for logging
        pattern: Pattern to search for
        match_mode: 'prefix', 'contains', or 'suffix'
        case_sensitive: Whether to match case exactly
        result_queue: Queue to put results
        counter: Shared counter for attempts
        stop_event: Event to signal stop
        version: Wallet version
    """
    # Re-import in worker process
    try:
        from tonsdk.contract.wallet import Wallets, WalletVersionEnum
        from tonsdk.crypto import mnemonic_new
    except ImportError:
        result_queue.put({"error": "tonsdk not available in worker"})
        return

    version_map = {
        "v3r2": WalletVersionEnum.v3r2,
        "v4r2": WalletVersionEnum.v4r2,
    }
    wallet_version = version_map.get(version.lower(), WalletVersionEnum.v4r2)

    # Prepare pattern for matching
    if not case_sensitive:
        pattern_match = pattern.lower()
    else:
        pattern_match = pattern

    while not stop_event.is_set():
        try:
            # Generate random mnemonic
            mnemonic = mnemonic_new(24)

            # Create wallet
            _, pub_k, priv_k, wallet = Wallets.from_mnemonics(
                mnemonic, wallet_version, workchain=0
            )

            # Get address (user-friendly format, bounceable)
            # This is the base64url format
            address = wallet.address.to_string(True, True, True)

            # Update counter
            with counter.get_lock():
                counter.value += 1

            # Prepare address for matching
            if not case_sensitive:
                address_match = address.lower()
            else:
                address_match = address

            # Check pattern based on mode
            # Address format: EQ... (starts with EQ for workchain 0)
            # For prefix matching, we skip the "EQ" part
            matched = False

            if match_mode == "prefix":
                # Check if address (after EQ) starts with pattern
                # Address is like "EQBx..." so we check from position 2
                addr_body = address_match[2:]  # Skip "EQ"
                matched = addr_body.startswith(pattern_match)
            elif match_mode == "suffix":
                matched = address_match.endswith(pattern_match)
            elif match_mode == "contains":
                matched = pattern_match in address_match

            if matched:
                # Found it!
                result_queue.put(
                    {
                        "success": True,
                        "mnemonic": mnemonic,
                        "address": address,
                        "address_raw": wallet.address.to_string(True, True, False),
                        "public_key": pub_k.hex(),
                        "private_key": priv_k.hex(),
                        "version": version,
                        "worker_id": worker_id,
                    }
                )
                stop_event.set()
                return

        except Exception:
            # Log error but continue
            pass


def _estimate_vanity_difficulty(
    pattern: str, match_mode: str, case_sensitive: bool
) -> dict:
    """
    Estimate difficulty of finding a vanity address.

    Base64url alphabet: A-Z, a-z, 0-9, -, _ (64 chars)
    For case-insensitive: effectively ~36 chars (letters collapse)

    Returns:
        dict with estimated_attempts, difficulty description
    """
    pattern_len = len(pattern)

    if case_sensitive:
        # Full base64url alphabet
        chars = 64
    else:
        # Case-insensitive: A-Z = a-z (26), 0-9 (10), -, _ (2) = ~38
        # But base64 has both cases, so effective search space is still 64
        # but we match more addresses (2x for each letter)
        # So for N letters: 64^N / 2^(letters_count)
        letter_count = sum(1 for c in pattern if c.isalpha())
        chars = 64
        # Effective difficulty is reduced by 2^letters
        # multiplier = 2**letter_count

    if match_mode == "prefix":
        # Each position has 1/64 chance
        base_attempts = chars**pattern_len
    elif match_mode == "suffix":
        # Same as prefix
        base_attempts = chars**pattern_len
    elif match_mode == "contains":
        # Address is ~48 chars, pattern can appear anywhere
        # Rough estimate: ~45 possible positions
        # So probability ~= 45 / 64^N
        address_len = 48
        positions = address_len - pattern_len + 1
        base_attempts = (chars**pattern_len) / max(1, positions)
    else:
        base_attempts = chars**pattern_len

    # Adjust for case-insensitive
    if not case_sensitive:
        letter_count = sum(1 for c in pattern if c.isalpha())
        base_attempts = base_attempts / (2**letter_count)

    estimated_attempts = int(base_attempts)

    # Estimate time based on ~50k attempts/sec/core
    # With 8 cores: ~400k/sec
    attempts_per_sec = 50000 * mp.cpu_count()
    estimated_seconds = estimated_attempts / attempts_per_sec

    # Determine difficulty
    if estimated_attempts < 1000:
        difficulty = "trivial"
    elif estimated_attempts < 100_000:
        difficulty = "easy"
    elif estimated_attempts < 10_000_000:
        difficulty = "medium"
    elif estimated_attempts < 1_000_000_000:
        difficulty = "hard"
    else:
        difficulty = "extreme"

    return {
        "pattern_length": pattern_len,
        "estimated_attempts": estimated_attempts,
        "difficulty": difficulty,
        "estimated_seconds": estimated_seconds,
        "estimated_time_human": _format_duration(estimated_seconds),
        "warning": estimated_seconds > 3600,  # Warn if > 1 hour
    }


def _format_duration(seconds: float) -> str:
    """Format duration in human-readable form."""
    if seconds < 1:
        return "< 1 second"
    elif seconds < 60:
        return f"{int(seconds)} seconds"
    elif seconds < 3600:
        minutes = int(seconds / 60)
        return f"{minutes} minute{'s' if minutes > 1 else ''}"
    elif seconds < 86400:
        hours = seconds / 3600
        return f"{hours:.1f} hours"
    else:
        days = seconds / 86400
        return f"{days:.1f} days"


def generate_vanity_address(
    pattern: str,
    match_mode: str = "contains",
    case_sensitive: bool = False,
    threads: int | None = None,
    timeout: int = 3600,
    version: str = "v4r2",
    progress_callback=None,
) -> dict:
    """
    Generate a vanity TON wallet address.

    Args:
        pattern: Pattern to search for in the address
        match_mode: 'prefix', 'contains', or 'suffix'
        case_sensitive: Whether to match case exactly
        threads: Number of worker processes (default: CPU count)
        timeout: Maximum seconds to search
        version: Wallet version (v3r2, v4r2)
        progress_callback: Optional callback(attempts, elapsed, rate) for progress

    Returns:
        dict with wallet data or error
    """
    if threads is None:
        threads = mp.cpu_count()

    # Validate pattern
    valid_chars = set(
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
    )
    if not all(c in valid_chars for c in pattern):
        return {
            "success": False,
            "error": "Invalid pattern. Use only base64url characters: A-Za-z0-9-_",
        }

    if len(pattern) > 20:
        return {"success": False, "error": "Pattern too long. Maximum 20 characters."}

    # Estimate difficulty
    # estimate = _estimate_vanity_difficulty(pattern, match_mode, case_sensitive)

    # Create shared objects
    result_queue = mp.Queue()
    counter = mp.Value("i", 0)
    stop_event = mp.Event()

    # Start workers
    workers = []
    for i in range(threads):
        p = mp.Process(
            target=_vanity_worker,
            args=(
                i,
                pattern,
                match_mode,
                case_sensitive,
                result_queue,
                counter,
                stop_event,
                version,
            ),
        )
        p.start()
        workers.append(p)

    # Monitor progress
    start_time = time.time()
    last_count = 0
    last_time = start_time

    try:
        while True:
            elapsed = time.time() - start_time

            # Check timeout
            if elapsed >= timeout:
                stop_event.set()
                # Wait for workers to finish
                for p in workers:
                    p.join(timeout=1)
                    if p.is_alive():
                        p.terminate()
                return {
                    "success": False,
                    "error": f"Timeout after {timeout} seconds",
                    "attempts": counter.value,
                    "elapsed_seconds": elapsed,
                }

            # Check if found
            try:
                result = result_queue.get_nowait()
                if result.get("error"):
                    return {"success": False, "error": result["error"]}

                # Stop all workers
                stop_event.set()
                for p in workers:
                    p.join(timeout=1)
                    if p.is_alive():
                        p.terminate()

                result["attempts"] = counter.value
                result["elapsed_seconds"] = elapsed
                result["rate"] = counter.value / max(0.1, elapsed)
                return result

            except Exception:
                pass

            # Progress update
            if progress_callback and time.time() - last_time >= 1.0:
                current_count = counter.value
                current_time = time.time()
                rate = (current_count - last_count) / (current_time - last_time)
                progress_callback(current_count, elapsed, rate)
                last_count = current_count
                last_time = current_time

            time.sleep(0.1)

    except KeyboardInterrupt:
        stop_event.set()
        for p in workers:
            p.join(timeout=1)
            if p.is_alive():
                p.terminate()
        return {
            "success": False,
            "error": "Cancelled by user",
            "attempts": counter.value,
            "elapsed_seconds": time.time() - start_time,
        }


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
    wallet_data["created_at"] = datetime.now(UTC).isoformat()

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
    wallet_data["created_at"] = datetime.now(UTC).isoformat()
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


def cmd_create_vanity(args, password: str) -> dict:
    """Creates a vanity wallet address with a custom pattern."""
    import sys

    storage = WalletStorage(password)

    # Determine match mode and pattern
    if args.prefix:
        pattern = args.prefix
        match_mode = "prefix"
    elif args.suffix:
        pattern = args.suffix
        match_mode = "suffix"
    elif args.contains:
        pattern = args.contains
        match_mode = "contains"
    else:
        return {
            "success": False,
            "error": "Specify --prefix, --suffix, or --contains pattern",
        }

    # Validate pattern
    valid_chars = set(
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
    )
    if not all(c in valid_chars for c in pattern):
        return {
            "success": False,
            "error": "Invalid pattern. Use only base64url characters: A-Za-z0-9-_",
        }

    # Estimate difficulty first
    estimate = _estimate_vanity_difficulty(pattern, match_mode, args.case_sensitive)

    # Show estimate
    print(
        json.dumps(
            {
                "action": "estimate",
                "pattern": pattern,
                "match_mode": match_mode,
                "case_sensitive": args.case_sensitive,
                "difficulty": estimate["difficulty"],
                "estimated_attempts": estimate["estimated_attempts"],
                "estimated_time": estimate["estimated_time_human"],
                "threads": args.threads or mp.cpu_count(),
                "timeout_seconds": args.timeout,
            },
            indent=2,
        ),
        file=sys.stderr,
    )

    # Warn if very difficult
    if estimate["warning"]:
        print(
            f"\n⚠️  WARNING: Expected search time > 1 hour ({estimate['estimated_time_human']})",
            file=sys.stderr,
        )
        print(
            "    Consider a shorter pattern or use --timeout to limit search time.\n",
            file=sys.stderr,
        )

    # Progress callback
    last_update = [0]

    def progress(attempts, elapsed, rate):
        if time.time() - last_update[0] >= 2.0:  # Update every 2 seconds
            eta = (estimate["estimated_attempts"] - attempts) / max(1, rate)
            print(
                f"\r🔍 Attempts: {attempts:,} | Rate: {rate:,.0f}/s | Elapsed: {_format_duration(elapsed)} | ETA: {_format_duration(eta)}   ",
                end="",
                file=sys.stderr,
                flush=True,
            )
            last_update[0] = time.time()

    print("\n🔍 Searching for vanity address...\n", file=sys.stderr)

    # Generate vanity address
    result = generate_vanity_address(
        pattern=pattern,
        match_mode=match_mode,
        case_sensitive=args.case_sensitive,
        threads=args.threads,
        timeout=args.timeout,
        version=args.version,
        progress_callback=progress,
    )

    print("\n", file=sys.stderr)  # New line after progress

    if not result.get("success"):
        return result

    # Found! Save the wallet
    wallet_data = {
        "address": result["address"],
        "address_raw": result["address_raw"],
        "public_key": result["public_key"],
        "private_key": result["private_key"],
        "mnemonic": result["mnemonic"],
        "version": result["version"],
        "label": args.label or f"vanity_{pattern[:8]}",
        "created_at": datetime.now(UTC).isoformat(),
        "vanity": {
            "pattern": pattern,
            "match_mode": match_mode,
            "case_sensitive": args.case_sensitive,
            "attempts": result["attempts"],
            "elapsed_seconds": result["elapsed_seconds"],
        },
    }

    try:
        storage.add_wallet(wallet_data)
    except ValueError as e:
        # Wallet already exists (unlikely but possible)
        return {
            "success": False,
            "error": f"Failed to save wallet: {e}",
            "address": result["address"],
            "mnemonic": result["mnemonic"],
        }

    return {
        "success": True,
        "action": "created_vanity",
        "wallet": {
            "address": result["address"],
            "label": wallet_data["label"],
            "version": result["version"],
        },
        "vanity": {
            "pattern": pattern,
            "match_mode": match_mode,
            "attempts": result["attempts"],
            "elapsed_seconds": round(result["elapsed_seconds"], 2),
            "rate": round(result["rate"], 0),
        },
        "mnemonic": result["mnemonic"],
        "warning": "⚠️ SAVE THE MNEMONIC! It's shown only once.",
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
  %(prog)s create-vanity --prefix "CAFE" --label "cafe-wallet"
  %(prog)s create-vanity --contains "TON" --label "ton-wallet"
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

    # --- create-vanity ---
    vanity_p = subparsers.add_parser(
        "create-vanity",
        help="Create wallet with vanity address (custom pattern)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --prefix "CAFE" --label "cafe-wallet"
  %(prog)s --contains "TON" --label "ton-wallet"
  %(prog)s --suffix "777" --label "lucky"
  %(prog)s --prefix "ABC" --case-sensitive --threads 4

Pattern matching:
  --prefix   Address starts with EQ + pattern (e.g., EQ + "CAFE" = "EQCAFE...")
  --contains Pattern appears anywhere in the address
  --suffix   Address ends with the pattern

Note: Base64url alphabet only (A-Za-z0-9-_). Longer patterns = much longer search time.
      3 chars ≈ seconds, 4 chars ≈ minutes, 5+ chars ≈ hours
""",
    )
    vanity_group = vanity_p.add_mutually_exclusive_group(required=True)
    vanity_group.add_argument("--prefix", help="Address starts with EQ + pattern")
    vanity_group.add_argument("--contains", help="Address contains pattern anywhere")
    vanity_group.add_argument("--suffix", help="Address ends with pattern")
    vanity_p.add_argument("--label", "-l", help="Wallet label")
    vanity_p.add_argument(
        "--case-sensitive",
        action="store_true",
        help="Match exact case (slower, default: case-insensitive)",
    )
    vanity_p.add_argument(
        "--threads",
        "-t",
        type=int,
        default=None,
        help=f"Number of worker threads (default: CPU count = {mp.cpu_count()})",
    )
    vanity_p.add_argument(
        "--timeout",
        type=int,
        default=3600,
        help="Max seconds to search (default: 3600 = 1 hour)",
    )
    vanity_p.add_argument(
        "--version",
        "-v",
        default="v4r2",
        choices=["v3r2", "v4r2"],
        help="Wallet version (default: v4r2)",
    )

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
            return sys.exit(1)

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
            "create-vanity": cmd_create_vanity,
        }

        result = commands[args.command](args, password)
        print(json.dumps(result, indent=2, ensure_ascii=False))

    except ValueError as e:
        print(json.dumps({"error": str(e)}, indent=2))
        return sys.exit(1)
    except Exception as e:
        print(json.dumps({"error": f"Unexpected error: {e}"}, indent=2))
        return sys.exit(1)


if __name__ == "__main__":
    main()
