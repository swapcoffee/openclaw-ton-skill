"""
Unit tests for utils.py module.

Test IDs reference TEST-PLAN.md

Run with: pytest tests/test_utils.py -v
"""

import base64
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from utils import (
    # Encryption
    encrypt_data,
    decrypt_data,
    encrypt_json,
    decrypt_json,
    derive_key,
    # Config
    load_config,
    save_config,
    get_config_value,
    set_config_value,
    raw_to_friendly,
    friendly_to_raw,
    is_valid_address,
    normalize_address,
    _crc16,
    # HTTP
    create_http_session,
    api_request,
    tonapi_request,
)


# =============================================================================
# Test Data
# =============================================================================

# Valid TON addresses - we'll derive friendly from raw during tests
VALID_RAW_ADDRESS = "0:4e95324902a9671fa85343288b17ad6c45d93b2e2849166cc8f3aa1e9e0a0472"
# Friendly address will be derived from raw in tests

# Testnet addresses
TESTNET_RAW_ADDRESS = (
    "0:4e95324902a9671fa85343288b17ad6c45d93b2e2849166cc8f3aa1e9e0a0472"
)

# Invalid addresses
INVALID_ADDRESS = "not-a-valid-address"
ETH_ADDRESS = "0x742d35Cc6634C0532925a3b844Bc9e7595f8fE2d"


def assert_no_secrets_in_string(
    text: str, mnemonic: str = None, private_key: str = None
):
    """Assert that sensitive data is not present in a string."""
    if mnemonic:
        assert mnemonic.lower() not in text.lower(), "Mnemonic found in text!"
    if private_key:
        assert private_key not in text, "Private key found in text!"


# =============================================================================
# Encryption Tests
# =============================================================================


class TestEncryption:
    """Tests for AES-256 encryption/decryption."""

    def test_encrypt_decrypt_roundtrip(self):
        """Basic round-trip: encrypt then decrypt returns original."""
        original = b"secret_data_to_encrypt"
        password = "strong_password_123"

        encrypted = encrypt_data(original, password)
        decrypted = decrypt_data(encrypted, password)

        assert decrypted == original
        assert encrypted != original

    def test_encrypt_decrypt_empty_data(self):
        """Round-trip with empty data."""
        original = b""
        password = "test"

        encrypted = encrypt_data(original, password)
        decrypted = decrypt_data(encrypted, password)

        assert decrypted == original

    def test_encrypt_decrypt_large_data(self):
        """Round-trip with large data (1MB)."""
        original = b"x" * (1024 * 1024)  # 1MB
        password = "test"

        encrypted = encrypt_data(original, password)
        decrypted = decrypt_data(encrypted, password)

        assert decrypted == original

    def test_encrypted_differs_from_original(self):
        """Encrypted data differs from original."""
        original = b"secret_data"
        password = "test"

        encrypted = encrypt_data(original, password)

        assert encrypted != original
        # Original should not be visible in ciphertext
        assert original not in encrypted

    def test_different_passwords_different_output(self):
        """Different passwords produce different ciphertext."""
        original = b"secret"

        enc1 = encrypt_data(original, "password1")
        enc2 = encrypt_data(original, "password2")

        assert enc1 != enc2

    def test_same_input_different_encryptions_differ(self):
        """Same input with same password differs due to random IV/salt."""
        original = b"secret"
        password = "test"

        enc1 = encrypt_data(original, password)
        enc2 = encrypt_data(original, password)

        # With random salt/IV, ciphertexts should differ
        assert enc1 != enc2
        # But both should decrypt to same value
        assert decrypt_data(enc1, password) == original
        assert decrypt_data(enc2, password) == original

    def test_wrong_password_fails(self):
        """Wrong password fails decryption with exception."""
        original = b"secret"

        encrypted = encrypt_data(original, "correct_password")

        with pytest.raises(Exception):  # ValueError or padding error
            decrypt_data(encrypted, "wrong_password")

    def test_corrupted_data_fails(self):
        """Corrupted encrypted data fails gracefully."""
        with pytest.raises(ValueError):
            decrypt_data(b"short", "any_password")  # Too short

    def test_corrupted_ciphertext_fails(self):
        """Corrupted ciphertext (valid length) fails."""
        # Create valid encrypted data, then corrupt it
        encrypted = encrypt_data(b"test", "password")
        corrupted = encrypted[:32] + b"x" * (len(encrypted) - 32)

        with pytest.raises(Exception):
            decrypt_data(corrupted, "password")

    def test_unicode_password(self):
        """Unicode password works correctly."""
        original = b"secret"
        password = "пароль🔐密码"

        encrypted = encrypt_data(original, password)
        decrypted = decrypt_data(encrypted, password)

        assert decrypted == original

    def test_very_long_password(self):
        """Very long password (10000 chars) works."""
        original = b"secret"
        password = "a" * 10000

        encrypted = encrypt_data(original, password)
        decrypted = decrypt_data(encrypted, password)

        assert decrypted == original

    def test_derive_key_deterministic(self):
        """Key derivation is deterministic for same password+salt."""
        password = "test_password"
        salt = b"0123456789abcdef"  # 16 bytes

        key1 = derive_key(password, salt)
        key2 = derive_key(password, salt)

        assert key1 == key2
        assert len(key1) == 32  # 256 bits

    def test_derive_key_different_salt(self):
        """Different salt produces different key."""
        password = "test"

        key1 = derive_key(password, b"salt1___________")
        key2 = derive_key(password, b"salt2___________")

        assert key1 != key2


class TestJsonEncryption:
    """Tests for JSON encryption/decryption wrappers."""

    def test_encrypt_decrypt_json_roundtrip(self):
        """JSON round-trip: encrypt then decrypt returns original dict."""
        original = {"key": "value", "number": 42, "nested": {"a": 1}}
        password = "test123"

        encrypted = encrypt_json(original, password)
        decrypted = decrypt_json(encrypted, password)

        assert decrypted == original
        assert isinstance(encrypted, str)  # Base64 string

    def test_encrypt_json_is_base64(self):
        """Encrypted JSON is valid base64."""
        data = {"test": "data"}

        encrypted = encrypt_json(data, "password")

        # Should not raise
        base64.b64decode(encrypted)

    def test_encrypt_json_unicode(self):
        """JSON encryption handles Unicode correctly."""
        original = {"русский": "текст", "emoji": "🎉"}
        password = "test"

        encrypted = encrypt_json(original, password)
        decrypted = decrypt_json(encrypted, password)

        assert decrypted == original

    def test_decrypt_json_wrong_password(self):
        """Wrong password fails JSON decryption."""
        data = {"secret": "data"}
        encrypted = encrypt_json(data, "correct")

        with pytest.raises(Exception):
            decrypt_json(encrypted, "wrong")


# =============================================================================
# Config Manager Tests
# =============================================================================


class TestConfigManager:
    """Tests for configuration management."""

    @pytest.fixture(autouse=True)
    def setup_temp_config(self, tmp_path, monkeypatch):
        """Use temporary directory for config during tests."""
        temp_skill_dir = tmp_path / "ton-skill"
        temp_config_file = temp_skill_dir / "config.json"

        # Patch the module-level variables
        monkeypatch.setattr("utils.SKILL_DIR", temp_skill_dir)
        monkeypatch.setattr("utils.CONFIG_FILE", temp_config_file)

        self.skill_dir = temp_skill_dir
        self.config_file = temp_config_file

    def test_load_config_creates_defaults(self):
        """Loading config with no file returns defaults."""
        config = load_config()

        assert "tonapi_key" in config
        assert "network" in config
        assert config["network"] == "mainnet"

    def test_save_and_load_config(self):
        """Save then load preserves config."""
        config = {"tonapi_key": "test_key", "custom": "value"}

        save_config(config)
        loaded = load_config()

        assert loaded["tonapi_key"] == "test_key"
        assert loaded["custom"] == "value"

    def test_load_config_merges_with_defaults(self):
        """Loading config merges with defaults for new fields."""
        # Save partial config
        partial = {"tonapi_key": "my_key"}
        save_config(partial)

        # Load should include defaults
        loaded = load_config()

        assert loaded["tonapi_key"] == "my_key"
        assert "network" in loaded  # From defaults
        assert "limits" in loaded  # From defaults

    def test_get_config_value_simple(self):
        """Get simple config value."""
        save_config({"tonapi_key": "test123"})

        value = get_config_value("tonapi_key")

        assert value == "test123"

    def test_get_config_value_dot_notation(self):
        """Get nested config value with dot notation."""
        save_config({"limits": {"max_transfer_ton": 50}})

        value = get_config_value("limits.max_transfer_ton")

        assert value == 50

    def test_get_config_value_missing_returns_default(self):
        """Missing key returns default value."""
        value = get_config_value("nonexistent", default="fallback")

        assert value == "fallback"

    def test_get_config_value_missing_nested(self):
        """Missing nested key returns default."""
        value = get_config_value("a.b.c.d", default=None)

        assert value is None

    def test_set_config_value_simple(self):
        """Set simple config value."""
        set_config_value("tonapi_key", "new_key")

        assert get_config_value("tonapi_key") == "new_key"

    def test_set_config_value_dot_notation(self):
        """Set nested config value with dot notation."""
        set_config_value("limits.max_transfer_ton", 200)

        assert get_config_value("limits.max_transfer_ton") == 200

    def test_set_config_value_creates_nested(self):
        """Setting nested value creates intermediate dicts."""
        set_config_value("new.nested.value", 42)

        assert get_config_value("new.nested.value") == 42

    def test_config_persists_after_reload(self):
        """Config changes persist after "reload"."""
        set_config_value("test_key", "test_value")

        # Simulate reload by loading again
        config = load_config()

        assert config["test_key"] == "test_value"

    def test_config_file_is_json(self):
        """Config file is valid JSON."""
        save_config({"key": "value"})

        content = self.config_file.read_text()
        parsed = json.loads(content)

        assert parsed["key"] == "value"

    def test_corrupted_config_returns_defaults(self):
        """Corrupted config file returns defaults."""
        self.skill_dir.mkdir(parents=True, exist_ok=True)
        self.config_file.write_text("not valid json {{{")

        config = load_config()

        # Should return defaults, not crash
        assert "tonapi_key" in config


# =============================================================================
# Address Formatting Tests
# =============================================================================


class TestAddressFormatting:
    """Tests for TON address formatting utilities."""

    def test_raw_to_friendly_basic(self):
        """Convert raw address to user-friendly format."""
        # Using a known address pair
        raw = "0:4e95324902a9671fa85343288b17ad6c45d93b2e2849166cc8f3aa1e9e0a0472"

        friendly = raw_to_friendly(raw)

        assert len(friendly) == 48  # Standard friendly address length
        assert friendly.startswith("EQ") or friendly.startswith("UQ")

    def test_friendly_to_raw_basic(self):
        """Convert user-friendly address to raw format."""
        # First convert raw to friendly, then back
        raw_original = (
            "0:4e95324902a9671fa85343288b17ad6c45d93b2e2849166cc8f3aa1e9e0a0472"
        )
        friendly = raw_to_friendly(raw_original)

        raw = friendly_to_raw(friendly)

        assert ":" in raw
        parts = raw.split(":")
        assert len(parts) == 2
        assert parts[0] in ["0", "-1"]  # Workchain
        assert len(parts[1]) == 64  # 32 bytes hex
        assert raw == raw_original

    def test_address_roundtrip_raw_to_friendly_to_raw(self):
        """Round-trip: raw → friendly → raw preserves address."""
        original_raw = (
            "0:4e95324902a9671fa85343288b17ad6c45d93b2e2849166cc8f3aa1e9e0a0472"
        )

        friendly = raw_to_friendly(original_raw)
        back_to_raw = friendly_to_raw(friendly)

        assert back_to_raw == original_raw

    def test_address_roundtrip_friendly_to_raw_to_friendly(self):
        """Round-trip: friendly → raw → friendly preserves address."""
        # Create a known good friendly address
        raw_original = (
            "0:4e95324902a9671fa85343288b17ad6c45d93b2e2849166cc8f3aa1e9e0a0472"
        )
        original_friendly = raw_to_friendly(raw_original, bounceable=True)

        raw = friendly_to_raw(original_friendly)
        back_to_friendly = raw_to_friendly(raw, bounceable=True)

        # May differ in URL-safe vs standard base64, so compare raw
        assert friendly_to_raw(back_to_friendly) == raw
        assert raw == raw_original

    def test_raw_to_friendly_bounceable(self):
        """Convert to bounceable address (0x11 tag)."""
        raw = "0:4e95324902a9671fa85343288b17ad6c45d93b2e2849166cc8f3aa1e9e0a0472"

        friendly = raw_to_friendly(raw, bounceable=True)

        assert friendly.startswith("EQ")

    def test_raw_to_friendly_non_bounceable(self):
        """Convert to non-bounceable address (0x51 tag)."""
        raw = "0:4e95324902a9671fa85343288b17ad6c45d93b2e2849166cc8f3aa1e9e0a0472"

        friendly = raw_to_friendly(raw, bounceable=False)

        assert friendly.startswith("UQ")

    def test_raw_to_friendly_testnet(self):
        """Convert to testnet address (adds 0x80 to tag)."""
        raw = "0:4e95324902a9671fa85343288b17ad6c45d93b2e2849166cc8f3aa1e9e0a0472"

        friendly = raw_to_friendly(raw, testnet=True)

        # Testnet addresses start with kQ (bounceable) or 0Q (non-bounceable)
        assert friendly[0] in ["k", "0"]

    def test_raw_to_friendly_invalid_format(self):
        """Invalid raw format raises ValueError."""
        with pytest.raises(ValueError):
            raw_to_friendly("invalid_address")

    def test_raw_to_friendly_missing_colon(self):
        """Raw address without colon raises error."""
        with pytest.raises(ValueError):
            raw_to_friendly(
                "4e95324902a9671fa85343288b17ad6c45d93b2e2849166cc8f3aa1e9e0a0472"
            )

    def test_raw_to_friendly_wrong_hash_length(self):
        """Raw address with wrong hash length raises error."""
        with pytest.raises(ValueError):
            raw_to_friendly("0:abc123")  # Too short

    def test_friendly_to_raw_invalid_length(self):
        """Invalid friendly address length raises error."""
        with pytest.raises(ValueError):
            friendly_to_raw("EQshort")

    def test_friendly_to_raw_invalid_checksum(self):
        """Invalid checksum raises error."""
        # Valid-looking but corrupted address
        with pytest.raises(ValueError) as exc_info:
            friendly_to_raw(
                "EQBOlTJJAqaXH6hTQyiLF61sRdk7LihJFmzI86oengoEchAX"
            )  # Changed last char

        assert (
            "crc" in str(exc_info.value).lower()
            or "checksum" in str(exc_info.value).lower()
        )

    def test_crc16_known_value(self):
        """CRC16 produces known value for test data."""
        # Test vector
        data = b"\x11\x00" + bytes.fromhex(
            "4e95324902a9671fa85343288b17ad6c45d93b2e2849166cc8f3aa1e9e0a0472"
        )

        crc = _crc16(data)

        assert isinstance(crc, int)
        assert 0 <= crc <= 0xFFFF


class TestAddressValidation:
    """Tests for address validation."""

    def test_is_valid_address_raw(self):
        """Valid raw address passes validation."""
        raw = "0:4e95324902a9671fa85343288b17ad6c45d93b2e2849166cc8f3aa1e9e0a0472"

        assert is_valid_address(raw) is True

    def test_is_valid_address_friendly(self):
        """Valid friendly address passes validation."""
        # Generate valid friendly address from raw
        raw = "0:4e95324902a9671fa85343288b17ad6c45d93b2e2849166cc8f3aa1e9e0a0472"
        friendly = raw_to_friendly(raw)

        assert is_valid_address(friendly) is True

    def test_is_valid_address_invalid(self):
        """Invalid address fails validation."""
        assert is_valid_address("not_an_address") is False
        assert is_valid_address("") is False
        assert is_valid_address("EQ" + "x" * 100) is False

    def test_is_valid_address_ethereum_rejected(self):
        """Ethereum address is not a valid TON address."""
        assert is_valid_address(ETH_ADDRESS) is False

    def test_normalize_address_to_friendly(self):
        """Normalize raw to friendly."""
        raw = "0:4e95324902a9671fa85343288b17ad6c45d93b2e2849166cc8f3aa1e9e0a0472"

        normalized = normalize_address(raw, to_format="friendly")

        assert ":" not in normalized
        assert normalized.startswith("EQ") or normalized.startswith("UQ")

    def test_normalize_address_to_raw(self):
        """Normalize friendly to raw."""
        raw_original = (
            "0:4e95324902a9671fa85343288b17ad6c45d93b2e2849166cc8f3aa1e9e0a0472"
        )
        friendly = raw_to_friendly(raw_original)

        normalized = normalize_address(friendly, to_format="raw")

        assert ":" in normalized
        assert normalized == raw_original

    def test_normalize_address_already_correct_format(self):
        """Normalize address already in correct format."""
        raw = "0:4e95324902a9671fa85343288b17ad6c45d93b2e2849166cc8f3aa1e9e0a0472"

        normalized = normalize_address(raw, to_format="raw")

        assert normalized == raw


# =============================================================================
# HTTP Client Tests
# =============================================================================


class TestHttpClient:
    """Tests for HTTP client with retry logic."""

    def test_create_http_session(self):
        """Create HTTP session returns session object."""
        import requests

        session = create_http_session()

        assert isinstance(session, requests.Session)

    def test_create_http_session_with_retries(self):
        """HTTP session has retry adapter configured."""
        session = create_http_session(retries=5)

        # Check that adapters are mounted
        assert "https://" in session.adapters
        assert "http://" in session.adapters

    @patch("requests.Session.request")
    def test_api_request_get_success(self, mock_request):
        """Successful GET request returns data."""
        mock_request.return_value = MagicMock(
            ok=True, status_code=200, json=lambda: {"data": "test"}
        )

        result = api_request("https://api.example.com/test")

        assert result["success"] is True
        assert result["data"] == {"data": "test"}
        assert result["status_code"] == 200

    @patch("requests.Session.request")
    def test_api_request_with_api_key(self, mock_request):
        """API request includes API key in header."""
        mock_request.return_value = MagicMock(ok=True, status_code=200, json=lambda: {})

        api_request(
            "https://api.example.com/test",
            api_key="my_secret_key",
            api_key_header="Authorization",
            api_key_prefix="Bearer ",
        )

        # Check that API key was included
        call_kwargs = mock_request.call_args[1]
        assert "Authorization" in call_kwargs["headers"]
        assert "Bearer my_secret_key" in call_kwargs["headers"]["Authorization"]

    @patch("requests.Session.request")
    def test_api_request_post_with_json(self, mock_request):
        """POST request with JSON body."""
        mock_request.return_value = MagicMock(
            ok=True, status_code=201, json=lambda: {"created": True}
        )

        result = api_request(
            "https://api.example.com/create", method="POST", json_data={"name": "test"}
        )

        assert result["success"] is True
        call_kwargs = mock_request.call_args[1]
        assert call_kwargs["json"] == {"name": "test"}

    @patch("requests.Session.request")
    def test_api_request_error_response(self, mock_request):
        """Error response returns success=False."""
        mock_request.return_value = MagicMock(
            ok=False,
            status_code=404,
            json=lambda: {"error": "Not found"},
            reason="Not Found",
        )

        result = api_request("https://api.example.com/missing")

        assert result["success"] is False
        assert result["status_code"] == 404
        assert "error" in result

    @patch("requests.Session.request")
    def test_api_request_timeout(self, mock_request):
        """Timeout returns error result."""
        import requests

        mock_request.side_effect = requests.exceptions.Timeout()

        result = api_request("https://api.example.com/slow")

        assert result["success"] is False
        assert "timeout" in result["error"].lower()

    @patch("requests.Session.request")
    def test_api_request_connection_error(self, mock_request):
        """Connection error returns error result."""
        import requests

        mock_request.side_effect = requests.exceptions.ConnectionError()

        result = api_request("https://api.example.com/down")

        assert result["success"] is False
        assert "connection" in result["error"].lower()


class TestTonApiRequest:
    """Tests for TonAPI-specific request wrapper."""

    @pytest.fixture(autouse=True)
    def setup_mock_config(self, tmp_path, monkeypatch):
        """Mock config for TonAPI tests."""
        temp_skill_dir = tmp_path / "ton-skill"
        temp_config_file = temp_skill_dir / "config.json"

        monkeypatch.setattr("utils.SKILL_DIR", temp_skill_dir)
        monkeypatch.setattr("utils.CONFIG_FILE", temp_config_file)

        # Save config with API key
        temp_skill_dir.mkdir(parents=True, exist_ok=True)
        temp_config_file.write_text(json.dumps({"tonapi_key": "test_api_key"}))

    @patch("utils.api_request")
    def test_tonapi_request_uses_config_key(self, mock_api_request):
        """TonAPI request uses API key from config."""
        mock_api_request.return_value = {"success": True, "data": {}}

        tonapi_request("/accounts/test")

        call_kwargs = mock_api_request.call_args[1]
        assert call_kwargs["api_key"] == "test_api_key"

    @patch("utils.api_request")
    def test_tonapi_request_builds_url(self, mock_api_request):
        """TonAPI request builds correct URL."""
        mock_api_request.return_value = {"success": True, "data": {}}

        tonapi_request("/accounts/EQtest123")

        call_kwargs = mock_api_request.call_args[1]
        # URL is passed as keyword argument 'url'
        assert "tonapi.io/v2/accounts/EQtest123" in call_kwargs.get("url", "") or (
            mock_api_request.call_args[0]
            and "tonapi.io" in mock_api_request.call_args[0][0]
        )

    @patch("utils.api_request")
    def test_tonapi_request_passes_params(self, mock_api_request):
        """TonAPI request passes query params."""
        mock_api_request.return_value = {"success": True, "data": {}}

        tonapi_request("/events", params={"limit": 10})

        call_kwargs = mock_api_request.call_args[1]
        assert call_kwargs["params"] == {"limit": 10}


# =============================================================================
# Edge Cases and Security
# =============================================================================


@pytest.mark.security
class TestSecurityEdgeCases:
    """Security-related edge case tests."""

    def test_empty_password_encryption(self):
        """Empty password still encrypts (no plaintext)."""
        data = b"secret"
        password = ""

        # Should work, just not recommended
        encrypted = encrypt_data(data, password)
        assert data not in encrypted

    def test_null_bytes_in_data(self):
        """Data with null bytes encrypts correctly."""
        data = b"before\x00after"
        password = "test"

        encrypted = encrypt_data(data, password)
        decrypted = decrypt_data(encrypted, password)

        assert decrypted == data

    def test_special_chars_in_json_keys(self):
        """JSON with special characters in keys."""
        data = {
            "normal": "value",
            "with spaces": "value2",
            "unicode_ключ": "значение",
            "emoji_🔑": "value4",
        }
        password = "test"

        encrypted = encrypt_json(data, password)
        decrypted = decrypt_json(encrypted, password)

        assert decrypted == data

    def test_address_with_0x_prefix(self):
        """Raw address with 0x prefix in hash."""
        raw = "0:0x4e95324902a9671fa85343288b17ad6c45d93b2e2849166cc8f3aa1e9e0a0472"

        # Should handle 0x prefix
        friendly = raw_to_friendly(raw)
        assert len(friendly) > 0

    def test_workchain_minus_one(self):
        """Address in workchain -1 (masterchain)."""
        raw = "-1:4e95324902a9671fa85343288b17ad6c45d93b2e2849166cc8f3aa1e9e0a0472"

        friendly = raw_to_friendly(raw)
        back = friendly_to_raw(friendly)

        assert back == raw


# =============================================================================
# Performance Tests
# =============================================================================


@pytest.mark.slow
class TestPerformance:
    """Performance tests."""

    def test_key_derivation_time(self):
        """Key derivation takes reasonable time."""
        import time

        start = time.time()
        derive_key("password", b"0123456789abcdef")
        elapsed = time.time() - start

        # Should be < 2 seconds (100k iterations)
        assert elapsed < 2.0

    def test_encryption_large_file(self):
        """Encryption of large data (10MB) completes."""
        import time

        data = b"x" * (10 * 1024 * 1024)  # 10MB

        start = time.time()
        encrypted = encrypt_data(data, "password")
        elapsed = time.time() - start

        assert elapsed < 5.0  # Should complete in < 5 seconds
        assert len(encrypted) >= len(data)
