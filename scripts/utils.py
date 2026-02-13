#!/usr/bin/env python3
"""
OpenClaw TON Skill — Общие утилиты

- AES-256 шифрование/дешифрование
- Конфиг менеджер
- Форматирование адресов TON
- HTTP клиент с retry
"""

import os
import sys
import json
import base64
import hashlib
import argparse
from pathlib import Path
from typing import Any, Optional, Union

# Зависимости
try:
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
except ImportError:
    print(
        json.dumps(
            {"error": "Missing dependency: requests", "install": "pip install requests"}
        )
    )
    sys.exit(1)
    raise SystemExit

try:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives import padding
    from cryptography.hazmat.backends import default_backend
except ImportError:
    print(
        json.dumps(
            {
                "error": "Missing dependency: cryptography",
                "install": "pip install cryptography",
            }
        )
    )
    sys.exit(1)
    raise SystemExit


# =============================================================================
# Константы
# =============================================================================

SKILL_DIR = Path.home() / ".openclaw" / "ton-skill"
CONFIG_FILE = SKILL_DIR / "config.json"
WALLETS_FILE = SKILL_DIR / "wallets.enc"

# TonAPI
TONAPI_BASE = "https://tonapi.io/v2"


# =============================================================================
# Шифрование/Дешифрование (AES-256-CBC)
# =============================================================================


def derive_key(password: str, salt: bytes) -> bytes:
    """Деривация ключа из пароля через PBKDF2-like (SHA256 iterations)."""
    key = password.encode("utf-8") + salt
    for _ in range(100000):  # 100k iterations
        key = hashlib.sha256(key).digest()
    return key  # 32 bytes = 256 bits


def encrypt_data(data: bytes, password: str) -> bytes:
    """
    Шифрует данные AES-256-CBC.
    Формат: salt(16) + iv(16) + encrypted_data
    """
    salt = os.urandom(16)
    iv = os.urandom(16)
    key = derive_key(password, salt)

    # Padding PKCS7
    padder = padding.PKCS7(128).padder()
    padded_data = padder.update(data) + padder.finalize()

    # Encrypt
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
    encryptor = cipher.encryptor()
    encrypted = encryptor.update(padded_data) + encryptor.finalize()

    return salt + iv + encrypted


def decrypt_data(encrypted_data: bytes, password: str) -> bytes:
    """
    Дешифрует данные AES-256-CBC.
    Ожидает формат: salt(16) + iv(16) + encrypted_data
    """
    if len(encrypted_data) < 33:
        raise ValueError("Invalid encrypted data")

    salt = encrypted_data[:16]
    iv = encrypted_data[16:32]
    ciphertext = encrypted_data[32:]

    key = derive_key(password, salt)

    # Decrypt
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
    decryptor = cipher.decryptor()
    padded_data = decryptor.update(ciphertext) + decryptor.finalize()

    # Unpadding
    unpadder = padding.PKCS7(128).unpadder()
    data = unpadder.update(padded_data) + unpadder.finalize()

    return data


def encrypt_json(data: dict, password: str) -> str:
    """Шифрует JSON и возвращает base64."""
    json_bytes = json.dumps(data, ensure_ascii=False).encode("utf-8")
    encrypted = encrypt_data(json_bytes, password)
    return base64.b64encode(encrypted).decode("ascii")


def decrypt_json(encrypted_b64: str, password: str) -> dict:
    """Дешифрует base64 в JSON."""
    encrypted = base64.b64decode(encrypted_b64)
    decrypted = decrypt_data(encrypted, password)
    return json.loads(decrypted.decode("utf-8"))


# =============================================================================
# Конфиг менеджер
# =============================================================================

DEFAULT_CONFIG = {
    "tonapi_key": "",
    "swap_coffee_key": "",
    "dyor_key": "",
    "default_wallet": "",
    "network": "mainnet",
    "limits": {"max_transfer_ton": 100, "require_confirmation": True},
}


def ensure_skill_dir() -> Path:
    """Создаёт директорию скилла если не существует."""
    SKILL_DIR.mkdir(parents=True, exist_ok=True)
    return SKILL_DIR


def load_config() -> dict:
    """Загружает конфигурацию из файла."""
    ensure_skill_dir()
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r") as f:
                config = json.load(f)
            # Merge с дефолтами (для новых полей)
            merged = DEFAULT_CONFIG.copy()
            merged.update(config)
            return merged
        except Exception:
            return DEFAULT_CONFIG.copy()
    return DEFAULT_CONFIG.copy()


def save_config(config: dict) -> bool:
    """Сохраняет конфигурацию в файл."""
    ensure_skill_dir()
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        return True
    except Exception:
        return False


def get_config_value(key: str, default: Any = None) -> Any:
    """Получает значение из конфига по ключу (поддерживает dot notation: limits.max_transfer_ton)."""
    config = load_config()
    keys = key.split(".")
    value = config
    for k in keys:
        if isinstance(value, dict) and k in value:
            value = value[k]
        else:
            return default
    return value


def set_config_value(key: str, value: Any) -> bool:
    """Устанавливает значение в конфиге (поддерживает dot notation)."""
    config = load_config()
    keys = key.split(".")
    target = config
    for k in keys[:-1]:
        if k not in target:
            target[k] = {}
        target = target[k]
    target[keys[-1]] = value
    return save_config(config)


# =============================================================================
# Форматирование адресов TON
# =============================================================================


# CRC16-CCITT для адресов TON
def _crc16(data: bytes) -> int:
    """CRC16-CCITT (XMODEM)."""
    crc = 0
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = (crc << 1) ^ 0x1021
            else:
                crc <<= 1
            crc &= 0xFFFF
    return crc


def raw_to_friendly(
    raw_address: str, bounceable: bool = True, testnet: bool = False
) -> str:
    """
    Конвертирует raw адрес (0:abc123...) в user-friendly формат.

    Args:
        raw_address: Адрес в формате "workchain:hex_hash"
        bounceable: Bounceable (True) или non-bounceable (False)
        testnet: Testnet (True) или mainnet (False)

    Returns:
        User-friendly адрес (base64url)
    """
    try:
        parts = raw_address.split(":")
        if len(parts) != 2:
            raise ValueError(f"Invalid raw address format: {raw_address}")

        workchain = int(parts[0])
        hash_hex = parts[1]

        # Убираем 0x если есть
        if hash_hex.startswith("0x"):
            hash_hex = hash_hex[2:]

        hash_bytes = bytes.fromhex(hash_hex)
        if len(hash_bytes) != 32:
            raise ValueError(f"Hash must be 32 bytes, got {len(hash_bytes)}")

        # Tag: 0x11 для bounceable, 0x51 для non-bounceable
        # Testnet добавляет 0x80
        tag = 0x11 if bounceable else 0x51
        if testnet:
            tag |= 0x80

        # Workchain как signed byte
        wc_byte = workchain.to_bytes(1, "big", signed=True)

        # Формируем данные для CRC: tag + workchain + hash
        data = bytes([tag]) + wc_byte + hash_bytes

        # CRC16
        crc = _crc16(data)
        crc_bytes = crc.to_bytes(2, "big")

        # Результат: data + crc
        result = data + crc_bytes

        # Base64url encode
        return base64.urlsafe_b64encode(result).decode("ascii").rstrip("=")

    except Exception as e:
        raise ValueError(f"Failed to convert raw address: {e}")


def friendly_to_raw(friendly_address: str) -> str:
    """
    Конвертирует user-friendly адрес в raw формат (0:abc123...).

    Args:
        friendly_address: User-friendly адрес (base64 или base64url)

    Returns:
        Raw адрес в формате "workchain:hex_hash"
    """
    try:
        # Нормализуем base64url в base64
        addr = friendly_address.replace("-", "+").replace("_", "/")

        # Добавляем padding если нужно
        padding_needed = 4 - (len(addr) % 4)
        if padding_needed != 4:
            addr += "=" * padding_needed

        data = base64.b64decode(addr)

        if len(data) != 36:
            raise ValueError(f"Invalid address length: {len(data)}, expected 36")

        # Проверяем CRC
        payload = data[:-2]
        crc_received = int.from_bytes(data[-2:], "big")
        crc_calculated = _crc16(payload)

        if crc_received != crc_calculated:
            raise ValueError("Invalid CRC checksum")

        # Парсим
        # tag = data[0]
        workchain = int.from_bytes(data[1:2], "big", signed=True)
        hash_bytes = data[2:34]

        return f"{workchain}:{hash_bytes.hex()}"

    except Exception as e:
        raise ValueError(f"Failed to convert friendly address: {e}")


def is_valid_address(address: str) -> bool:
    """Проверяет валидность TON адреса (raw или friendly)."""
    try:
        if ":" in address:
            # Raw формат
            parts = address.split(":")
            if len(parts) != 2:
                return False
            int(parts[0])  # workchain
            bytes.fromhex(parts[1].replace("0x", ""))
            return True
        else:
            # Friendly формат
            friendly_to_raw(address)
            return True
    except Exception:
        return False


def normalize_address(address: str, to_format: str = "friendly") -> str:
    """
    Нормализует адрес к указанному формату.

    Args:
        address: Любой валидный TON адрес
        to_format: "friendly" или "raw"

    Returns:
        Адрес в запрошенном формате
    """
    if ":" in address:
        # Raw →
        if to_format == "raw":
            return address
        else:
            return raw_to_friendly(address)
    else:
        # Friendly →
        if to_format == "raw":
            return friendly_to_raw(address)
        else:
            return address


# =============================================================================
# HTTP клиент с retry
# =============================================================================


def create_http_session(
    retries: int = 3,
    backoff_factor: float = 0.5,
    status_forcelist: tuple = (500, 502, 503, 504),
    timeout: int = 30,
) -> requests.Session:
    """
    Создаёт HTTP сессию с автоматическими retry.

    Args:
        retries: Количество повторных попыток
        backoff_factor: Фактор задержки между попытками
        status_forcelist: HTTP коды для retry
        timeout: Таймаут по умолчанию

    Returns:
        Настроенная requests.Session
    """
    session = requests.Session()

    retry_strategy = Retry(
        total=retries,
        backoff_factor=backoff_factor,
        status_forcelist=status_forcelist,
        allowed_methods=["HEAD", "GET", "POST", "PUT", "DELETE", "OPTIONS", "TRACE"],
    )

    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("https://", adapter)
    session.mount("http://", adapter)

    # Default timeout через hook
    session.request = lambda method, url, **kwargs: requests.Session.request(  # ty: ignore[invalid-assignment]
        session, method, url, timeout=kwargs.pop("timeout", timeout), **kwargs
    )

    return session


def api_request(
    url: str,
    method: str = "GET",
    headers: Optional[dict] = None,
    params: Optional[dict] = None,
    json_data: Optional[Union[dict, list]] = None,
    api_key: Optional[str] = None,
    api_key_header: str = "Authorization",
    api_key_prefix: str = "Bearer ",
    timeout: int = 30,
    retries: int = 3,
) -> dict:
    """
    Универсальный API запрос с retry и обработкой ошибок.

    Args:
        url: URL запроса
        method: HTTP метод
        headers: Дополнительные заголовки
        params: Query параметры
        json_data: JSON body
        api_key: API ключ (если есть)
        api_key_header: Заголовок для API ключа
        api_key_prefix: Префикс для API ключа
        timeout: Таймаут
        retries: Количество retry

    Returns:
        dict с ключами: success, data/error, status_code
    """
    session = create_http_session(retries=retries, timeout=timeout)

    req_headers = {"Accept": "application/json"}
    if headers:
        req_headers.update(headers)
    if api_key:
        req_headers[api_key_header] = f"{api_key_prefix}{api_key}"

    try:
        response = session.request(
            method=method.upper(),
            url=url,
            headers=req_headers,
            params=params,
            json=json_data,
            timeout=timeout,
        )

        # Пытаемся распарсить JSON
        try:
            data = response.json()
        except Exception:
            data = response.text

        if response.ok:
            return {"success": True, "data": data, "status_code": response.status_code}
        else:
            return {
                "success": False,
                "error": data if data else response.reason,
                "status_code": response.status_code,
            }

    except requests.exceptions.Timeout:
        return {"success": False, "error": "Request timeout", "status_code": None}
    except requests.exceptions.ConnectionError:
        return {"success": False, "error": "Connection error", "status_code": None}
    except Exception as e:
        return {"success": False, "error": str(e), "status_code": None}


# =============================================================================
# swap.coffee API helpers
# =============================================================================


def get_swap_coffee_key() -> Optional[str]:
    """Get swap.coffee API key from config or environment."""
    import os

    config = load_config()
    return config.get("swap_coffee_key") or os.environ.get("SWAP_COFFEE_KEY")


def swap_coffee_request(
    endpoint: str,
    method: str = "GET",
    params: Optional[dict] = None,
    json_data: Optional[dict] = None,
    version: str = "v1",
    timeout: int = 30,
    retries: int = 3,
) -> dict:
    """
    Request to swap.coffee API with automatic X-Api-Key header.

    Args:
        endpoint: API endpoint (e.g., "/route")
        method: HTTP method
        params: Query parameters
        json_data: JSON body
        version: API version ("v1", "v2", or "" for base)
        timeout: Request timeout in seconds
        retries: Number of retry attempts

    Returns:
        dict with keys: success, data/error, status_code

    Examples:
        >>> swap_coffee_request("/route", method="POST", json_data={...}, version="v1")
        >>> swap_coffee_request("/route/transactions", method="POST", json_data={...}, version="v2")
    """
    # Determine base URL based on version
    if version == "v2":
        base_url = "https://backend.swap.coffee/v2"
    elif version == "v1":
        base_url = "https://backend.swap.coffee/v1"
    else:
        base_url = "https://backend.swap.coffee"

    url = f"{base_url}{endpoint}"

    # Build headers with X-Api-Key
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    api_key = get_swap_coffee_key()
    if api_key:
        headers["X-Api-Key"] = api_key

    return api_request(
        url=url,
        method=method,
        headers=headers,
        params=params,
        json_data=json_data,
        timeout=timeout,
        retries=retries,
    )


def tokens_api_request(
    endpoint: str,
    method: str = "GET",
    params: Optional[dict] = None,
    json_data: Optional[Union[dict, list]] = None,
    timeout: int = 30,
    retries: int = 3,
) -> dict:
    """
    Request to swap.coffee Tokens API (tokens.swap.coffee).

    The Tokens API provides token metadata, market stats, and search.
    Uses X-Api-Key header if swap_coffee_key is configured.

    Args:
        endpoint: API endpoint (e.g., "/api/v3/jettons")
        method: HTTP method
        params: Query parameters
        json_data: JSON body
        timeout: Request timeout in seconds
        retries: Number of retry attempts

    Returns:
        dict with keys: success, data/error, status_code

    Examples:
        >>> tokens_api_request("/api/v3/jettons", params={"search": "USDT"})
        >>> tokens_api_request("/api/v3/jettons/{address}")
    """
    base_url = "https://tokens.swap.coffee"
    url = f"{base_url}{endpoint}"

    headers = {
        "Accept": "application/json",
    }

    # Add X-Api-Key if configured
    api_key = get_swap_coffee_key()
    if api_key:
        headers["X-Api-Key"] = api_key

    return api_request(
        url=url,
        method=method,
        headers=headers,
        params=params,
        json_data=json_data,
        timeout=timeout,
        retries=retries,
    )


# =============================================================================
# TonAPI helpers
# =============================================================================


def tonapi_request(
    endpoint: str,
    method: str = "GET",
    params: Optional[dict] = None,
    json_data: Optional[dict] = None,
) -> dict:
    """
    Запрос к TonAPI с использованием ключа из конфига.

    Args:
        endpoint: Endpoint (без base URL), например "/accounts/{account}"
        method: HTTP метод
        params: Query параметры
        json_data: JSON body

    Returns:
        Результат api_request
    """
    config = load_config()
    api_key = config.get("tonapi_key", "")

    url = f"{TONAPI_BASE}{endpoint}"

    return api_request(
        url=url,
        method=method,
        params=params,
        json_data=json_data,
        api_key=api_key if api_key else None,
        api_key_header="Authorization",
        api_key_prefix="Bearer ",
    )


# =============================================================================
# CLI
# =============================================================================


def main():
    parser = argparse.ArgumentParser(description="TON Skill Utilities")
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # --- config ---
    config_parser = subparsers.add_parser("config", help="Configuration management")
    config_sub = config_parser.add_subparsers(dest="config_cmd")

    config_get = config_sub.add_parser("get", help="Get config value")
    config_get.add_argument("key", help="Config key (dot notation)")

    config_set = config_sub.add_parser("set", help="Set config value")
    config_set.add_argument("key", help="Config key")
    config_set.add_argument("value", help="Value to set")

    config_sub.add_parser("show", help="Show all config")

    # --- address ---
    addr_parser = subparsers.add_parser("address", help="Address formatting")
    addr_sub = addr_parser.add_subparsers(dest="addr_cmd")

    addr_to_raw = addr_sub.add_parser("to-raw", help="Convert to raw format")
    addr_to_raw.add_argument("address", help="User-friendly address")

    addr_to_friendly = addr_sub.add_parser(
        "to-friendly", help="Convert to user-friendly format"
    )
    addr_to_friendly.add_argument("address", help="Raw address")
    addr_to_friendly.add_argument("--bounceable", action="store_true", default=True)
    addr_to_friendly.add_argument("--testnet", action="store_true", default=False)

    addr_validate = addr_sub.add_parser("validate", help="Validate address")
    addr_validate.add_argument("address", help="Address to validate")

    # --- encrypt ---
    enc_parser = subparsers.add_parser("encrypt", help="Encrypt data")
    enc_parser.add_argument("--data", "-d", required=True, help="Data to encrypt")
    enc_parser.add_argument("--password", "-p", required=True, help="Password")

    dec_parser = subparsers.add_parser("decrypt", help="Decrypt data")
    dec_parser.add_argument(
        "--data", "-d", required=True, help="Encrypted data (base64)"
    )
    dec_parser.add_argument("--password", "-p", required=True, help="Password")

    args = parser.parse_args()

    result = {}

    if args.command == "config":
        if args.config_cmd == "get":
            value = get_config_value(args.key)
            result = {"key": args.key, "value": value}
        elif args.config_cmd == "set":
            # Try to parse value as JSON
            try:
                value = json.loads(args.value)
            except Exception:
                value = args.value
            success = set_config_value(args.key, value)
            result = {"success": success, "key": args.key, "value": value}
        elif args.config_cmd == "show":
            result = load_config()
        else:
            result = {"error": "Unknown config command"}

    elif args.command == "address":
        if args.addr_cmd == "to-raw":
            try:
                raw = friendly_to_raw(args.address)
                result = {"raw": raw, "friendly": args.address}
            except Exception as e:
                result = {"error": str(e)}
        elif args.addr_cmd == "to-friendly":
            try:
                friendly = raw_to_friendly(args.address, args.bounceable, args.testnet)
                result = {"raw": args.address, "friendly": friendly}
            except Exception as e:
                result = {"error": str(e)}
        elif args.addr_cmd == "validate":
            valid = is_valid_address(args.address)
            result = {"address": args.address, "valid": valid}
        else:
            result = {"error": "Unknown address command"}

    elif args.command == "encrypt":
        encrypted = encrypt_json({"data": args.data}, args.password)
        result = {"encrypted": encrypted}

    elif args.command == "decrypt":
        try:
            decrypted = decrypt_json(args.data, args.password)
            result = decrypted
        except Exception as e:
            result = {"error": f"Decryption failed: {e}"}

    else:
        parser.print_help()
        return

    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
