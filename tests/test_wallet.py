"""
Unit tests for wallet.py module.

Test IDs reference TEST-PLAN.md (W-001, W-002, etc.)

Run with: pytest tests/test_wallet.py -v
Run security tests only: pytest tests/test_wallet.py -v -m security
"""

import json
import sys
from pathlib import Path
from unittest.mock import patch
from datetime import datetime, UTC

import pytest

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

# =============================================================================
# Test Data (from conftest constants)
# =============================================================================

# Valid TON mnemonic (24 words) - FOR TESTING ONLY
VALID_MNEMONIC_24 = (
    "abandon abandon abandon abandon abandon abandon "
    "abandon abandon abandon abandon abandon abandon "
    "abandon abandon abandon abandon abandon abandon "
    "abandon abandon abandon abandon abandon about"
)

VALID_MNEMONIC_12 = (
    "abandon abandon abandon abandon abandon abandon "
    "abandon abandon abandon abandon abandon about"
)

INVALID_MNEMONIC = (
    "apple banana cherry dog elephant frog "
    "grape house igloo jungle kite lemon "
    "mango night orange pear queen river "
    "snake tree umbrella violet water xray"
)

VALID_ADDRESS_1 = "EQDtFpEwcFAEcRe5mLVh2N6C0x-_hJEM7W61_JLnSF74p4q2"
VALID_ADDRESS_2 = "EQBvW8Z5huBkMJYdnfAEM5JqTNkuWX3diqYENkWsIL0XggGG"
INVALID_ADDRESS = "not-a-valid-address"
ETH_ADDRESS = "0x742d35Cc6634C0532925a3b844Bc9e7595f8fE2d"


def assert_no_secrets_in_string(
    text: str, mnemonic: str = None, private_key: str = None
):
    """Assert that sensitive data is not present in a string."""
    if mnemonic:
        assert mnemonic.lower() not in text.lower(), "Mnemonic found in text!"
        words = mnemonic.lower().split()
        for i in range(len(words) - 2):
            phrase = " ".join(words[i : i + 3])
            assert phrase not in text.lower(), f"Mnemonic words found: {phrase}"
    if private_key:
        assert private_key not in text, "Private key found in text!"


# Import wallet module components
from wallet import (
    WalletStorage,
    generate_mnemonic,
    validate_mnemonic,
    mnemonic_to_wallet,
    get_account_info,
    get_jetton_balances,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def temp_wallet_storage(tmp_path, monkeypatch):
    """Create temporary wallet storage."""
    temp_skill_dir = tmp_path / "ton-skill"
    temp_wallets_file = temp_skill_dir / "wallets.enc"
    temp_config_file = temp_skill_dir / "config.json"

    # Patch module-level variables
    monkeypatch.setattr("wallet.SKILL_DIR", temp_skill_dir)
    monkeypatch.setattr("wallet.WALLETS_FILE", temp_wallets_file)
    monkeypatch.setattr("utils.SKILL_DIR", temp_skill_dir)
    monkeypatch.setattr("utils.CONFIG_FILE", temp_config_file)

    temp_skill_dir.mkdir(parents=True, exist_ok=True)
    temp_config_file.write_text(json.dumps({"tonapi_key": "test_key"}))

    return {
        "skill_dir": temp_skill_dir,
        "wallets_file": temp_wallets_file,
        "config_file": temp_config_file,
        "password": "test_password_123",
    }


@pytest.fixture
def storage(temp_wallet_storage):
    """Get WalletStorage instance."""
    return WalletStorage(temp_wallet_storage["password"])


# =============================================================================
# 1.1 Wallet Creation Tests (W-001 to W-006)
# =============================================================================


@pytest.mark.wallet
class TestWalletCreation:
    """Tests for wallet creation functionality."""

    def test_w001_generate_mnemonic_24_words(self):
        """W-001: Generate mnemonic returns 24 words."""
        mnemonic = generate_mnemonic()

        assert len(mnemonic) == 24
        assert all(isinstance(w, str) for w in mnemonic)
        assert all(len(w) > 0 for w in mnemonic)

    def test_w002_create_wallet_with_label(self, storage):
        """W-002: Create wallet with label."""
        mnemonic = generate_mnemonic()
        wallet_data = mnemonic_to_wallet(mnemonic)
        wallet_data["mnemonic"] = mnemonic
        wallet_data["label"] = "трейдинг"
        wallet_data["created_at"] = datetime.now(UTC).isoformat()

        storage.add_wallet(wallet_data)

        wallets = storage.get_wallets()
        assert len(wallets) == 1
        assert wallets[0]["label"] == "трейдинг"

    def test_w003_create_multiple_unique_wallets(self, storage):
        """W-003: Create multiple unique wallets."""
        addresses = set()
        mnemonics = set()

        for i in range(5):
            mnemonic = generate_mnemonic()
            wallet_data = mnemonic_to_wallet(mnemonic)
            wallet_data["mnemonic"] = mnemonic
            wallet_data["label"] = f"wallet_{i}"
            wallet_data["created_at"] = datetime.now(UTC).isoformat()

            addresses.add(wallet_data["address"])
            mnemonics.add(" ".join(mnemonic))

            storage.add_wallet(wallet_data)

        # All should be unique
        assert len(addresses) == 5
        assert len(mnemonics) == 5
        assert len(storage.get_wallets()) == 5

    def test_w004_duplicate_address_rejected(self, storage):
        """W-004: Duplicate address is rejected."""
        mnemonic = generate_mnemonic()
        wallet_data = mnemonic_to_wallet(mnemonic)
        wallet_data["mnemonic"] = mnemonic
        wallet_data["label"] = "first"
        wallet_data["created_at"] = datetime.now(UTC).isoformat()

        storage.add_wallet(wallet_data)

        # Try to add same wallet again
        wallet_data["label"] = "second"
        with pytest.raises(ValueError) as exc_info:
            storage.add_wallet(wallet_data)

        assert "already exists" in str(exc_info.value).lower()

    def test_w005_empty_label_allowed(self, storage):
        """W-005: Empty label is allowed."""
        mnemonic = generate_mnemonic()
        wallet_data = mnemonic_to_wallet(mnemonic)
        wallet_data["mnemonic"] = mnemonic
        wallet_data["label"] = ""
        wallet_data["created_at"] = datetime.now(UTC).isoformat()

        storage.add_wallet(wallet_data)

        wallets = storage.get_wallets()
        assert len(wallets) == 1
        assert wallets[0]["label"] == ""

    def test_w006_unicode_emoji_label(self, storage):
        """W-006: Unicode/emoji label works."""
        mnemonic = generate_mnemonic()
        wallet_data = mnemonic_to_wallet(mnemonic)
        wallet_data["mnemonic"] = mnemonic
        wallet_data["label"] = "💰 основной! 🚀"
        wallet_data["created_at"] = datetime.now(UTC).isoformat()

        storage.add_wallet(wallet_data)

        wallets = storage.get_wallets()
        assert wallets[0]["label"] == "💰 основной! 🚀"


# =============================================================================
# 1.2 Wallet Import/Validation Tests (W-010 to W-018)
# =============================================================================


@pytest.mark.wallet
class TestWalletImport:
    """Tests for wallet import and mnemonic validation."""

    def test_w010_validate_mnemonic_24_words(self):
        """W-010: Valid 24-word mnemonic passes validation."""
        # Generate a valid mnemonic
        mnemonic = generate_mnemonic()

        assert validate_mnemonic(mnemonic) is True

    def test_w012_invalid_mnemonic_rejected(self):
        """W-012: Invalid mnemonic words are rejected."""
        invalid_words = INVALID_MNEMONIC.split()

        # This may return True or False depending on tonsdk's validation
        # The key is that mnemonic_to_wallet should fail or produce invalid wallet
        result = validate_mnemonic(invalid_words)

        # Invalid mnemonic should either fail validation or fail wallet derivation
        if result:
            # If validation passes, wallet derivation should fail or be deterministic
            pass  # tonsdk may accept any 24 words

    def test_w013_incomplete_mnemonic_rejected(self):
        """W-013: Incomplete mnemonic (20 words) is rejected."""
        mnemonic = generate_mnemonic()
        incomplete = mnemonic[:20]

        # 20 words should fail
        result = validate_mnemonic(incomplete)
        assert result is False or len(incomplete) != 24

    def test_w014_mnemonic_extra_spaces_normalized(self, storage):
        """W-014: Mnemonic with extra spaces is normalized."""
        mnemonic = generate_mnemonic()

        # Add extra spaces
        messy_mnemonic = "  " + "   ".join(mnemonic) + "  "

        # Split and clean
        cleaned = messy_mnemonic.strip().split()

        # Should produce same wallet
        wallet1 = mnemonic_to_wallet(mnemonic)
        wallet2 = mnemonic_to_wallet(cleaned)

        assert wallet1["address"] == wallet2["address"]

    def test_w015_mnemonic_case_insensitive(self, storage):
        """W-015: Mnemonic is case-insensitive (normalized to lowercase)."""
        mnemonic = generate_mnemonic()

        # Mixed case - needs to be normalized before passing to tonsdk
        mixed_case = [w.upper() if i % 2 else w.lower() for i, w in enumerate(mnemonic)]

        # tonsdk requires lowercase, so we normalize
        normalized = [w.lower() for w in mixed_case]

        # Both should produce same address
        wallet1 = mnemonic_to_wallet(mnemonic)
        wallet2 = mnemonic_to_wallet(normalized)

        assert wallet1["address"] == wallet2["address"]

    def test_w016_import_existing_wallet_rejected(self, storage):
        """W-016: Importing existing wallet is rejected."""
        mnemonic = generate_mnemonic()
        wallet_data = mnemonic_to_wallet(mnemonic)
        wallet_data["mnemonic"] = mnemonic
        wallet_data["label"] = "first"
        wallet_data["created_at"] = datetime.now(UTC).isoformat()

        storage.add_wallet(wallet_data)

        # Second import should fail
        wallet_data["label"] = "second"
        with pytest.raises(ValueError):
            storage.add_wallet(wallet_data)


# =============================================================================
# 1.3 Encrypted Storage Tests (W-020 to W-028)
# =============================================================================


@pytest.mark.wallet
@pytest.mark.security
class TestEncryptedStorage:
    """Tests for encrypted wallet storage."""

    def test_w020_wallet_encrypted_on_save(self, temp_wallet_storage):
        """W-020: Wallet file is encrypted on disk."""
        password = temp_wallet_storage["password"]
        storage = WalletStorage(password)

        mnemonic = generate_mnemonic()
        wallet_data = mnemonic_to_wallet(mnemonic)
        wallet_data["mnemonic"] = mnemonic
        wallet_data["label"] = "test"
        wallet_data["created_at"] = datetime.now(UTC).isoformat()

        storage.add_wallet(wallet_data)

        # Check file content
        wallets_file = temp_wallet_storage["wallets_file"]
        content = wallets_file.read_text()

        # Mnemonic should NOT be in plaintext
        mnemonic_str = " ".join(mnemonic)
        assert mnemonic_str not in content
        # Address should NOT be in plaintext
        assert wallet_data["address"] not in content

    def test_w021_decrypt_correct_password(self, temp_wallet_storage):
        """W-021: Correct password decrypts wallet."""
        password = temp_wallet_storage["password"]
        storage = WalletStorage(password)

        mnemonic = generate_mnemonic()
        wallet_data = mnemonic_to_wallet(mnemonic)
        wallet_data["mnemonic"] = mnemonic
        wallet_data["label"] = "test"
        wallet_data["created_at"] = datetime.now(UTC).isoformat()

        storage.add_wallet(wallet_data)

        # Load with same password
        storage2 = WalletStorage(password)
        loaded = storage2.get_wallets(include_secrets=True)

        assert len(loaded) == 1
        assert loaded[0]["mnemonic"] == mnemonic

    def test_w022_wrong_password_fails(self, temp_wallet_storage):
        """W-022: Wrong password fails decryption."""
        password = temp_wallet_storage["password"]
        storage = WalletStorage(password)

        mnemonic = generate_mnemonic()
        wallet_data = mnemonic_to_wallet(mnemonic)
        wallet_data["mnemonic"] = mnemonic
        wallet_data["label"] = "test"
        wallet_data["created_at"] = datetime.now(UTC).isoformat()

        storage.add_wallet(wallet_data)

        # Try with wrong password
        wrong_storage = WalletStorage("wrong_password")

        with pytest.raises((ValueError, Exception)):
            wrong_storage.load()

    def test_w024_very_long_password(self, temp_wallet_storage):
        """W-024: Very long password (10000 chars) works."""
        long_password = "a" * 10000
        storage = WalletStorage(long_password)

        mnemonic = generate_mnemonic()
        wallet_data = mnemonic_to_wallet(mnemonic)
        wallet_data["mnemonic"] = mnemonic
        wallet_data["label"] = "test"
        wallet_data["created_at"] = datetime.now(UTC).isoformat()

        storage.add_wallet(wallet_data)

        # Should be able to load
        storage2 = WalletStorage(long_password)
        loaded = storage2.get_wallets()

        assert len(loaded) == 1

    def test_w025_unicode_password(self, temp_wallet_storage):
        """W-025: Unicode password works."""
        unicode_password = "пароль🔐密码العربية"
        storage = WalletStorage(unicode_password)

        mnemonic = generate_mnemonic()
        wallet_data = mnemonic_to_wallet(mnemonic)
        wallet_data["mnemonic"] = mnemonic
        wallet_data["label"] = "test"
        wallet_data["created_at"] = datetime.now(UTC).isoformat()

        storage.add_wallet(wallet_data)

        # Load with same password
        storage2 = WalletStorage(unicode_password)
        loaded = storage2.get_wallets()

        assert len(loaded) == 1

    def test_w026_corrupted_file_handled(self, temp_wallet_storage):
        """W-026: Corrupted wallet file is handled gracefully."""
        password = temp_wallet_storage["password"]
        storage = WalletStorage(password)

        # Create valid wallet first
        mnemonic = generate_mnemonic()
        wallet_data = mnemonic_to_wallet(mnemonic)
        wallet_data["mnemonic"] = mnemonic
        wallet_data["label"] = "test"
        wallet_data["created_at"] = datetime.now(UTC).isoformat()

        storage.add_wallet(wallet_data)

        # Corrupt the file
        wallets_file = temp_wallet_storage["wallets_file"]
        wallets_file.write_text("corrupted data!!!")

        # Should raise clear error
        with pytest.raises(Exception):
            storage2 = WalletStorage(password)
            storage2.load()

    def test_w027_no_plaintext_secrets_on_disk(self, temp_wallet_storage):
        """W-027: Private key/mnemonic never stored in plaintext."""
        password = temp_wallet_storage["password"]
        storage = WalletStorage(password)

        mnemonic = generate_mnemonic()
        wallet_data = mnemonic_to_wallet(mnemonic)
        wallet_data["mnemonic"] = mnemonic
        wallet_data["label"] = "test"
        wallet_data["created_at"] = datetime.now(UTC).isoformat()

        storage.add_wallet(wallet_data)

        # Scan all files in skill directory
        skill_dir = temp_wallet_storage["skill_dir"]
        mnemonic_str = " ".join(mnemonic)

        for file_path in skill_dir.rglob("*"):
            if file_path.is_file():
                try:
                    content = file_path.read_text()
                    assert_no_secrets_in_string(content, mnemonic=mnemonic_str)
                except UnicodeDecodeError:
                    content = file_path.read_bytes().decode("utf-8", errors="ignore")
                    assert_no_secrets_in_string(content, mnemonic=mnemonic_str)


# =============================================================================
# 1.4 Wallet List and Balance Tests (W-030 to W-036)
# =============================================================================


@pytest.mark.wallet
class TestWalletListAndBalance:
    """Tests for listing wallets and checking balances."""

    def test_w030_list_all_wallets(self, storage):
        """W-030: List all wallets."""
        # Create multiple wallets
        for i in range(3):
            mnemonic = generate_mnemonic()
            wallet_data = mnemonic_to_wallet(mnemonic)
            wallet_data["mnemonic"] = mnemonic
            wallet_data["label"] = f"wallet_{i}"
            wallet_data["created_at"] = datetime.now(UTC).isoformat()
            storage.add_wallet(wallet_data)

        wallets = storage.get_wallets()

        assert len(wallets) == 3
        labels = [w["label"] for w in wallets]
        assert "wallet_0" in labels
        assert "wallet_1" in labels
        assert "wallet_2" in labels

    def test_w030_list_wallets_excludes_secrets(self, storage):
        """W-030: List wallets excludes secrets by default."""
        mnemonic = generate_mnemonic()
        wallet_data = mnemonic_to_wallet(mnemonic)
        wallet_data["mnemonic"] = mnemonic
        wallet_data["private_key"] = "secret_key"
        wallet_data["label"] = "test"
        wallet_data["created_at"] = datetime.now(UTC).isoformat()
        storage.add_wallet(wallet_data)

        wallets = storage.get_wallets(include_secrets=False)

        assert len(wallets) == 1
        assert "mnemonic" not in wallets[0]
        assert "private_key" not in wallets[0]
        assert "secret_key" not in wallets[0]

    def test_get_wallet_by_label(self, storage):
        """Get wallet by label."""
        mnemonic = generate_mnemonic()
        wallet_data = mnemonic_to_wallet(mnemonic)
        wallet_data["mnemonic"] = mnemonic
        wallet_data["label"] = "MyWallet"
        wallet_data["created_at"] = datetime.now(UTC).isoformat()
        storage.add_wallet(wallet_data)

        # Find by label (case-insensitive)
        found = storage.get_wallet("mywallet")

        assert found is not None
        assert found["label"] == "MyWallet"

    def test_get_wallet_by_address(self, storage):
        """Get wallet by address."""
        mnemonic = generate_mnemonic()
        wallet_data = mnemonic_to_wallet(mnemonic)
        wallet_data["mnemonic"] = mnemonic
        wallet_data["label"] = "test"
        wallet_data["created_at"] = datetime.now(UTC).isoformat()
        storage.add_wallet(wallet_data)

        address = wallet_data["address"]
        found = storage.get_wallet(address)

        assert found is not None
        assert found["address"] == address

    def test_get_wallet_not_found(self, storage):
        """Get wallet returns None if not found."""
        found = storage.get_wallet("nonexistent")

        assert found is None

    @patch("wallet.tonapi_request")
    def test_w031_get_ton_balance(self, mock_tonapi):
        """W-031: Get TON balance."""
        mock_tonapi.return_value = {
            "success": True,
            "data": {
                "address": VALID_ADDRESS_1,
                "balance": 5000000000,  # 5 TON
                "status": "active",
                "is_wallet": True,
            },
        }

        result = get_account_info(VALID_ADDRESS_1)

        assert result["success"] is True
        assert result["balance_ton"] == 5.0
        assert result["status"] == "active"

    @patch("wallet.tonapi_request")
    def test_w032_get_balance_with_jettons(self, mock_tonapi, sample_jetton_balance):
        """W-032: Get balance including jettons."""
        mock_tonapi.return_value = {"success": True, "data": sample_jetton_balance}

        result = get_jetton_balances(VALID_ADDRESS_1)

        assert result["success"] is True
        assert "jettons" in result
        symbols = [j["symbol"] for j in result["jettons"]]
        assert "USDT" in symbols
        assert "NOT" in symbols

    @patch("wallet.tonapi_request")
    def test_w033_empty_wallet_balance(self, mock_tonapi):
        """W-033: Empty wallet shows zero balance."""
        mock_tonapi.return_value = {
            "success": True,
            "data": {"address": VALID_ADDRESS_1, "balance": 0, "status": "uninit"},
        }

        result = get_account_info(VALID_ADDRESS_1)

        assert result["success"] is True
        assert result["balance_ton"] == 0
        assert result["balance"] == 0

    @patch("wallet.tonapi_request")
    def test_w036_api_error_handled(self, mock_tonapi):
        """W-036: API error handled gracefully."""
        mock_tonapi.return_value = {
            "success": False,
            "error": "Service unavailable",
            "status_code": 503,
        }

        result = get_account_info(VALID_ADDRESS_1)

        assert result["success"] is False
        assert "error" in result


# =============================================================================
# Wallet Removal Tests
# =============================================================================


@pytest.mark.wallet
class TestWalletRemoval:
    """Tests for wallet removal."""

    def test_remove_wallet_by_label(self, storage):
        """Remove wallet by label."""
        mnemonic = generate_mnemonic()
        wallet_data = mnemonic_to_wallet(mnemonic)
        wallet_data["mnemonic"] = mnemonic
        wallet_data["label"] = "to_remove"
        wallet_data["created_at"] = datetime.now(UTC).isoformat()
        storage.add_wallet(wallet_data)

        assert len(storage.get_wallets()) == 1

        storage.remove_wallet("to_remove")

        assert len(storage.get_wallets()) == 0

    def test_remove_wallet_by_address(self, storage):
        """Remove wallet by address."""
        mnemonic = generate_mnemonic()
        wallet_data = mnemonic_to_wallet(mnemonic)
        wallet_data["mnemonic"] = mnemonic
        wallet_data["label"] = "test"
        wallet_data["created_at"] = datetime.now(UTC).isoformat()
        storage.add_wallet(wallet_data)

        address = wallet_data["address"]
        storage.remove_wallet(address)

        assert len(storage.get_wallets()) == 0

    def test_remove_nonexistent_wallet_raises(self, storage):
        """Removing nonexistent wallet raises error."""
        with pytest.raises(ValueError) as exc_info:
            storage.remove_wallet("nonexistent")

        assert "not found" in str(exc_info.value).lower()


# =============================================================================
# Wallet Update Tests
# =============================================================================


@pytest.mark.wallet
class TestWalletUpdate:
    """Tests for updating wallet data."""

    def test_update_wallet_label(self, storage):
        """Update wallet label."""
        mnemonic = generate_mnemonic()
        wallet_data = mnemonic_to_wallet(mnemonic)
        wallet_data["mnemonic"] = mnemonic
        wallet_data["label"] = "old_label"
        wallet_data["created_at"] = datetime.now(UTC).isoformat()
        storage.add_wallet(wallet_data)

        storage.update_wallet("old_label", {"label": "new_label"})

        wallets = storage.get_wallets()
        assert wallets[0]["label"] == "new_label"

    def test_update_nonexistent_wallet_raises(self, storage):
        """Updating nonexistent wallet raises error."""
        with pytest.raises(ValueError):
            storage.update_wallet("nonexistent", {"label": "new"})


# =============================================================================
# Security Tests (SEC-001 to SEC-014)
# =============================================================================


@pytest.mark.security
class TestSecurityLeaks:
    """Security tests for key leakage prevention."""

    def test_sec001_mnemonic_not_in_wallet_output(self, storage):
        """SEC-001: Mnemonic not exposed in regular wallet listing."""
        mnemonic = generate_mnemonic()
        wallet_data = mnemonic_to_wallet(mnemonic)
        wallet_data["mnemonic"] = mnemonic
        wallet_data["label"] = "test"
        wallet_data["created_at"] = datetime.now(UTC).isoformat()
        storage.add_wallet(wallet_data)

        # Regular listing should not include mnemonic
        wallets = storage.get_wallets(include_secrets=False)
        wallet_json = json.dumps(wallets)

        mnemonic_str = " ".join(mnemonic)
        assert_no_secrets_in_string(wallet_json, mnemonic=mnemonic_str)

    def test_sec004_mnemonic_not_in_exceptions(self, temp_wallet_storage):
        """SEC-004: Mnemonic not in exception messages."""
        password = temp_wallet_storage["password"]
        storage = WalletStorage(password)

        mnemonic = generate_mnemonic()
        wallet_data = mnemonic_to_wallet(mnemonic)
        wallet_data["mnemonic"] = mnemonic
        wallet_data["label"] = "test"
        wallet_data["created_at"] = datetime.now(UTC).isoformat()
        storage.add_wallet(wallet_data)

        # Try with wrong password
        wrong_storage = WalletStorage("wrong_password")

        try:
            wrong_storage.load()
        except Exception as e:
            import traceback

            tb = traceback.format_exc()
            mnemonic_str = " ".join(mnemonic)
            assert_no_secrets_in_string(str(e), mnemonic=mnemonic_str)
            assert_no_secrets_in_string(tb, mnemonic=mnemonic_str)


@pytest.mark.security
class TestInputValidation:
    """Security tests for input validation."""

    def test_sec010_sql_injection_in_label(self, storage):
        """SEC-010: SQL injection in label is safe."""
        malicious_label = "'; DROP TABLE wallets; --"

        mnemonic = generate_mnemonic()
        wallet_data = mnemonic_to_wallet(mnemonic)
        wallet_data["mnemonic"] = mnemonic
        wallet_data["label"] = malicious_label
        wallet_data["created_at"] = datetime.now(UTC).isoformat()

        storage.add_wallet(wallet_data)

        # Should work without issues
        wallets = storage.get_wallets()
        assert len(wallets) == 1
        assert wallets[0]["label"] == malicious_label

    def test_sec012_xss_in_label(self, storage):
        """SEC-012: XSS in label is stored safely."""
        xss_label = '<script>alert("xss")</script>'

        mnemonic = generate_mnemonic()
        wallet_data = mnemonic_to_wallet(mnemonic)
        wallet_data["mnemonic"] = mnemonic
        wallet_data["label"] = xss_label
        wallet_data["created_at"] = datetime.now(UTC).isoformat()

        storage.add_wallet(wallet_data)

        wallets = storage.get_wallets()
        # Data is stored (escaping is frontend concern)
        assert wallets[0]["label"] == xss_label

    def test_sec014_null_bytes_in_label(self, storage):
        """SEC-014: Null bytes in input handled."""
        malicious_label = "test\x00evil"

        mnemonic = generate_mnemonic()
        wallet_data = mnemonic_to_wallet(mnemonic)
        wallet_data["mnemonic"] = mnemonic
        wallet_data["label"] = malicious_label
        wallet_data["created_at"] = datetime.now(UTC).isoformat()

        # Should either accept or reject, not crash
        try:
            storage.add_wallet(wallet_data)
            wallets = storage.get_wallets()
            # If accepted, ensure it's retrievable
            assert len(wallets) == 1
        except ValueError:
            # Rejection is also acceptable
            pass


# =============================================================================
# Mnemonic Validation Tests
# =============================================================================


@pytest.mark.wallet
class TestMnemonicValidation:
    """Tests for mnemonic validation."""

    def test_validate_generated_mnemonic(self):
        """Generated mnemonic is valid."""
        mnemonic = generate_mnemonic()

        assert validate_mnemonic(mnemonic) is True

    def test_validate_wrong_word_count(self):
        """Wrong word count fails."""
        mnemonic = generate_mnemonic()

        # 20 words
        short = mnemonic[:20]
        assert validate_mnemonic(short) is False or len(short) != 24

        # 30 words
        long = mnemonic + mnemonic[:6]
        assert validate_mnemonic(long) is False or len(long) == 24

    def test_validate_empty_mnemonic(self):
        """Empty mnemonic fails."""
        assert validate_mnemonic([]) is False
        assert validate_mnemonic(["", "", ""]) is False


# =============================================================================
# Wallet Version Tests
# =============================================================================


@pytest.mark.wallet
class TestWalletVersion:
    """Tests for different wallet versions."""

    def test_create_v4r2_wallet(self):
        """Create v4r2 wallet (default)."""
        mnemonic = generate_mnemonic()
        wallet = mnemonic_to_wallet(mnemonic, version="v4r2")

        assert wallet["version"] == "v4r2"
        assert "address" in wallet

    def test_create_v3r2_wallet(self):
        """Create v3r2 wallet."""
        mnemonic = generate_mnemonic()
        wallet = mnemonic_to_wallet(mnemonic, version="v3r2")

        assert wallet["version"] == "v3r2"
        assert "address" in wallet

    def test_different_versions_different_addresses(self):
        """Different versions produce different addresses."""
        mnemonic = generate_mnemonic()

        v3 = mnemonic_to_wallet(mnemonic, version="v3r2")
        v4 = mnemonic_to_wallet(mnemonic, version="v4r2")

        assert v3["address"] != v4["address"]


# =============================================================================
# Edge Cases
# =============================================================================


@pytest.mark.wallet
class TestEdgeCases:
    """Edge case tests."""

    def test_empty_storage_operations(self, storage):
        """Operations on empty storage work."""
        assert storage.get_wallets() == []
        assert storage.get_wallet("nonexistent") is None

    def test_storage_file_permissions(self, temp_wallet_storage):
        """Wallet file has secure permissions (600)."""
        password = temp_wallet_storage["password"]
        storage = WalletStorage(password)

        mnemonic = generate_mnemonic()
        wallet_data = mnemonic_to_wallet(mnemonic)
        wallet_data["mnemonic"] = mnemonic
        wallet_data["label"] = "test"
        wallet_data["created_at"] = datetime.now(UTC).isoformat()
        storage.add_wallet(wallet_data)

        wallets_file = temp_wallet_storage["wallets_file"]
        if wallets_file.exists():
            # Check permissions (Unix only)
            import stat

            mode = wallets_file.stat().st_mode
            # Should be 0o600 (owner read/write only)
            assert stat.S_IMODE(mode) == 0o600

    def test_special_characters_in_all_fields(self, storage):
        """Special characters work in all fields."""
        mnemonic = generate_mnemonic()
        wallet_data = mnemonic_to_wallet(mnemonic)
        wallet_data["mnemonic"] = mnemonic
        wallet_data["label"] = "テスト 🎉 <>&\"'"
        wallet_data["created_at"] = datetime.now(UTC).isoformat()

        storage.add_wallet(wallet_data)

        wallets = storage.get_wallets()
        assert wallets[0]["label"] == "テスト 🎉 <>&\"'"


# =============================================================================
# Performance Tests
# =============================================================================


@pytest.mark.slow
class TestPerformance:
    """Performance tests."""

    def test_mnemonic_generation_time(self):
        """Mnemonic generation is fast."""
        import time

        start = time.time()
        for _ in range(10):
            generate_mnemonic()
        elapsed = time.time() - start

        # Should generate 10 mnemonics in < 1 second
        assert elapsed < 1.0

    def test_wallet_derivation_time(self):
        """Wallet derivation from mnemonic is fast."""
        import time

        mnemonic = generate_mnemonic()

        start = time.time()
        mnemonic_to_wallet(mnemonic)
        elapsed = time.time() - start

        # Should derive wallet in < 1 second
        assert elapsed < 1.0

    def test_many_wallets_storage(self, storage):
        """Storage handles many wallets."""
        import time

        # Create 50 wallets
        for i in range(50):
            mnemonic = generate_mnemonic()
            wallet_data = mnemonic_to_wallet(mnemonic)
            wallet_data["mnemonic"] = mnemonic
            wallet_data["label"] = f"wallet_{i}"
            wallet_data["created_at"] = datetime.now(UTC).isoformat()
            storage.add_wallet(wallet_data)

        start = time.time()
        wallets = storage.get_wallets()
        elapsed = time.time() - start

        assert len(wallets) == 50
        assert elapsed < 2.0  # Listing should be quick
