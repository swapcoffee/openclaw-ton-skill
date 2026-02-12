"""
Pytest configuration and shared fixtures for openclaw-ton-skill tests.
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# =============================================================================
# Test Data
# =============================================================================

# Valid TON mnemonic (24 words) - FOR TESTING ONLY, DO NOT USE IN PRODUCTION
VALID_MNEMONIC_24 = (
    "abandon abandon abandon abandon abandon abandon "
    "abandon abandon abandon abandon abandon abandon "
    "abandon abandon abandon abandon abandon abandon "
    "abandon abandon abandon abandon abandon about"
)

# Valid TON mnemonic (12 words) - FOR TESTING ONLY
VALID_MNEMONIC_12 = (
    "abandon abandon abandon abandon abandon abandon "
    "abandon abandon abandon abandon abandon about"
)

# Invalid mnemonic (random words)
INVALID_MNEMONIC = (
    "apple banana cherry dog elephant frog "
    "grape house igloo jungle kite lemon "
    "mango night orange pear queen river "
    "snake tree umbrella violet water xray"
)

# Valid TON addresses (testnet)
VALID_ADDRESS_1 = "EQDtFpEwcFAEcRe5mLVh2N6C0x-_hJEM7W61_JLnSF74p4q2"
VALID_ADDRESS_2 = "EQBvW8Z5huBkMJYdnfAEM5JqTNkuWX3diqYENkWsIL0XggGG"

# Invalid addresses
INVALID_ADDRESS = "not-a-valid-address"
ETH_ADDRESS = "0x742d35Cc6634C0532925a3b844Bc9e7595f8fE2d"


# =============================================================================
# Fixtures - Temporary Directories
# =============================================================================


@pytest.fixture
def temp_wallet_dir():
    """Create a temporary directory for wallet storage."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def temp_skill_dir(tmp_path):
    """Create a temporary skill directory structure."""
    skill_dir = tmp_path / "ton-skill"
    skill_dir.mkdir(parents=True, exist_ok=True)
    return skill_dir


# =============================================================================
# Fixtures - Mock TonAPI
# =============================================================================


@pytest.fixture
def mock_tonapi():
    """Mock TonAPI responses."""
    with patch("requests.Session.request") as mock_request:
        # Default successful balance response
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "balance": 1000000000,  # 1 TON in nanoTON
            "status": "active",
            "is_wallet": True,
        }
        mock_request.return_value = mock_response
        yield mock_request


@pytest.fixture
def mock_tonapi_error():
    """Mock TonAPI error responses."""
    with patch("requests.Session.request") as mock_request:
        mock_response = MagicMock()
        mock_response.ok = False
        mock_response.status_code = 500
        mock_response.json.return_value = {"error": "Internal Server Error"}
        mock_response.reason = "Internal Server Error"
        mock_request.return_value = mock_response
        yield mock_request


@pytest.fixture
def mock_tonapi_timeout():
    """Mock TonAPI timeout."""
    import requests

    with patch("requests.Session.request") as mock_request:
        mock_request.side_effect = requests.exceptions.Timeout("Connection timed out")
        yield mock_request


# =============================================================================
# Fixtures - Sample Data
# =============================================================================


@pytest.fixture
def sample_wallet_data():
    """Sample wallet data structure."""
    return {
        "address": VALID_ADDRESS_1,
        "label": "test-wallet",
        "created_at": "2024-01-01T00:00:00Z",
        "version": "v4r2",
    }


@pytest.fixture
def sample_jetton_balance():
    """Sample jetton balance response from TonAPI."""
    return {
        "balances": [
            {
                "balance": "1000000000",  # 1000 USDT (6 decimals)
                "jetton": {
                    "address": "EQCxE6mUtQJKFnGfaROTKOt1lZbDiiX1kCixRv7Nw2Id_sDs",
                    "name": "Tether USD",
                    "symbol": "USDT",
                    "decimals": 6,
                    "verification": "whitelist",
                    "price": {"prices": {"USD": "1.0"}},
                },
            },
            {
                "balance": "5000000000000",  # 5000 NOT (9 decimals)
                "jetton": {
                    "address": "EQAvlWFDxGF2lXm67y4yzC17wYKD9A0guwPkMs1gOsM__NOT",
                    "name": "Notcoin",
                    "symbol": "NOT",
                    "decimals": 9,
                    "verification": "whitelist",
                    "price": {"prices": {"USD": "0.01"}},
                },
            },
        ]
    }


@pytest.fixture
def sample_transaction_history():
    """Sample transaction history response."""
    return {
        "events": [
            {
                "event_id": "abc123",
                "timestamp": 1704067200,
                "actions": [
                    {
                        "type": "TonTransfer",
                        "status": "ok",
                        "TonTransfer": {
                            "sender": {"address": VALID_ADDRESS_1},
                            "recipient": {"address": VALID_ADDRESS_2},
                            "amount": 500000000,  # 0.5 TON
                        },
                    }
                ],
            }
        ]
    }


@pytest.fixture
def sample_account_info():
    """Sample account info response from TonAPI."""
    return {
        "address": VALID_ADDRESS_1,
        "balance": 5000000000,  # 5 TON
        "status": "active",
        "last_activity": 1704067200,
        "interfaces": ["wallet_v4r2"],
        "name": None,
        "is_wallet": True,
    }


# =============================================================================
# Fixtures - Mock Config
# =============================================================================


@pytest.fixture
def mock_config(tmp_path, monkeypatch):
    """Mock configuration for tests."""
    temp_skill_dir = tmp_path / "ton-skill"
    temp_config_file = temp_skill_dir / "config.json"
    temp_wallets_file = temp_skill_dir / "wallets.enc"

    # Create directory
    temp_skill_dir.mkdir(parents=True, exist_ok=True)

    # Create default config
    default_config = {
        "tonapi_key": "test_api_key",
        "swap_coffee_key": "",
        "dyor_key": "",
        "default_wallet": "",
        "network": "mainnet",
        "limits": {"max_transfer_ton": 100, "require_confirmation": True},
    }
    temp_config_file.write_text(json.dumps(default_config))

    # Patch module-level variables
    import utils

    monkeypatch.setattr(utils, "SKILL_DIR", temp_skill_dir)
    monkeypatch.setattr(utils, "CONFIG_FILE", temp_config_file)
    monkeypatch.setattr(utils, "WALLETS_FILE", temp_wallets_file)

    return {
        "skill_dir": temp_skill_dir,
        "config_file": temp_config_file,
        "wallets_file": temp_wallets_file,
        "config": default_config,
    }


# =============================================================================
# Security Test Helpers
# =============================================================================


@pytest.fixture
def capture_logs(caplog):
    """Fixture to capture and check logs for sensitive data."""
    import logging

    caplog.set_level(logging.DEBUG)
    return caplog


def assert_no_secrets_in_string(
    text: str, mnemonic: str = None, private_key: str = None
):
    """Assert that sensitive data is not present in a string."""
    if mnemonic:
        # Check full mnemonic
        assert mnemonic.lower() not in text.lower(), "Mnemonic found in text!"
        # Check individual words (at least 3 consecutive)
        words = mnemonic.lower().split()
        for i in range(len(words) - 2):
            phrase = " ".join(words[i : i + 3])
            assert phrase not in text.lower(), f"Mnemonic words found: {phrase}"

    if private_key:
        assert private_key not in text, "Private key found in text!"


# =============================================================================
# Test Categories (markers)
# =============================================================================


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line("markers", "security: Security-related tests (critical)")
    config.addinivalue_line("markers", "slow: Slow tests (skip with -m 'not slow')")
    config.addinivalue_line(
        "markers", "integration: Integration tests requiring network"
    )
    config.addinivalue_line("markers", "wallet: Wallet module tests")
    config.addinivalue_line("markers", "transfer: Transfer module tests")
    config.addinivalue_line("markers", "swap: Swap module tests")
    config.addinivalue_line("markers", "utils: Utils module tests")


# =============================================================================
# Pytest Hooks
# =============================================================================


def pytest_collection_modifyitems(config, items):
    """Modify test collection to add markers based on test location."""
    for item in items:
        # Add markers based on test file
        if "test_wallet" in str(item.fspath):
            item.add_marker(pytest.mark.wallet)
        elif "test_utils" in str(item.fspath):
            item.add_marker(pytest.mark.utils)

        # Add security marker to security-named tests
        if "security" in item.name.lower() or "sec" in item.name.lower():
            item.add_marker(pytest.mark.security)
