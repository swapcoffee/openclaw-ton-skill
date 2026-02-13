#!/usr/bin/env python3
"""
OpenClaw TON Skill — DCA & Limit Orders via swap.coffee Strategies API

=============================================================================
SWAP.COFFEE STRATEGIES API (v1)
=============================================================================

Architecture:
- Each user gets a Strategies Wallet (smart contract on-chain)
- User sends funds + messages to this contract to create/cancel orders
- Backend executes orders off-chain and initiates transactions on the wallet

API Endpoints (from official SDK):
- GET  /v1/strategies/{address}/wallet                   — Check if strategies wallet exists
- POST /v1/strategies/{address}/wallet                   — Create strategies wallet (one-time)
- GET  /v1/strategies/eligibility/user/{address}         — Check if user is eligible
- GET  /v1/strategies/eligibility/from-tokens?type=X     — Get eligible from-tokens
- GET  /v1/strategies/eligibility/to-tokens/{from}?type=X — Get eligible to-tokens for from-token
- POST /v1/strategies/{address}/order                    — Create order (returns tx to sign)
- GET  /v1/strategies/{address}/orders                   — List orders
- GET  /v1/strategies/{address}/order?id=X               — Get order details
- DELETE /v1/strategies/{address}/order?id=X              — Cancel order (returns tx to sign)

Authentication:
Most endpoints require `x-verify` header containing a TonConnect proof signature.
This proves wallet ownership without requiring the user to connect via TonConnect.

=============================================================================
"""

import os
import sys
import json
import time
import base64
import struct
import hashlib
import argparse
import getpass
import secrets
from pathlib import Path
from typing import Optional, Tuple

# Local imports
script_dir = Path(__file__).parent
sys.path.insert(0, str(script_dir))

from utils import (  # noqa: E402
    api_request,
    tonapi_request,
    load_config,
    friendly_to_raw,
)

# TON SDK
try:
    from tonsdk.contract.wallet import Wallets, WalletVersionEnum
    from tonsdk.boc import Cell
    from tonsdk.utils import Address  # noqa: F401

    TONSDK_AVAILABLE = True
except ImportError:
    TONSDK_AVAILABLE = False

# NaCl for Ed25519 signatures
try:
    import nacl.signing
    import nacl.encoding

    NACL_AVAILABLE = True
except ImportError:
    NACL_AVAILABLE = False


# =============================================================================
# Constants
# =============================================================================

SWAP_COFFEE_API = "https://backend.swap.coffee"
STRATEGIES_API_V1 = f"{SWAP_COFFEE_API}/v1/strategies"

# Order types
ORDER_TYPES = ["limit", "dca"]

# Order statuses
ORDER_STATUSES = ["active", "completed", "cancelled", "pending"]

# X-Verify domain for swap.coffee
XVERIFY_DOMAIN = "swap.coffee"


# =============================================================================
# X-Verify (TonConnect Proof) Generation
# =============================================================================


def generate_ton_proof(
    wallet_address: str,
    private_key: bytes,
    payload: str = "",
    domain: str = XVERIFY_DOMAIN,
) -> dict:
    """
    Generate TonConnect ton_proof for wallet verification.

    The proof follows TonConnect specification:
    https://docs.ton.org/v3/guidelines/ton-connect/verifying-signed-in-users

    swap.coffee API expects ApiTonProof format:
    - timestamp: number
    - domain_len: number
    - domain_val: string
    - payload: string
    - signature: string (base64)

    Args:
        wallet_address: User's wallet address (friendly or raw format)
        private_key: 32-byte Ed25519 private key (seed)
        payload: Optional payload string (nonce)
        domain: Domain name for the proof (default: swap.coffee)

    Returns:
        dict with proof structure for x-verify header
    """
    if not NACL_AVAILABLE:
        raise RuntimeError("nacl not installed. Run: pip install pynacl")

    # Normalize address to raw format for signing
    if ":" not in wallet_address:
        raw_addr = friendly_to_raw(wallet_address)
    else:
        raw_addr = wallet_address

    # Parse workchain and hash from raw address
    workchain_str, hash_hex = raw_addr.split(":")
    workchain = int(workchain_str)
    addr_hash = bytes.fromhex(hash_hex)

    # Current timestamp
    timestamp = int(time.time())

    # Domain length in bytes
    domain_bytes = domain.encode("utf-8")
    domain_len = len(domain_bytes)

    # Payload bytes
    payload_bytes = payload.encode("utf-8") if payload else b""

    # Build the message to sign:
    # message = utf8_encode("ton-proof-item-v2/") ++
    #           Address (workchain:4BE + hash:32BE) ++
    #           AppDomain (length:4LE + value) ++
    #           Timestamp (8LE) ++
    #           Payload

    message_parts = [
        b"ton-proof-item-v2/",
        struct.pack(">i", workchain),  # 4 bytes, big-endian (signed)
        addr_hash,  # 32 bytes
        struct.pack("<I", domain_len),  # 4 bytes, little-endian
        domain_bytes,
        struct.pack("<Q", timestamp),  # 8 bytes, little-endian
        payload_bytes,
    ]
    message = b"".join(message_parts)

    # Hash the message
    msg_hash = hashlib.sha256(message).digest()

    # Build full message: 0xffff || "ton-connect" || sha256(message)
    full_message = b"\xff\xff" + b"ton-connect" + msg_hash

    # Hash full message
    full_hash = hashlib.sha256(full_message).digest()

    # Sign with Ed25519
    signing_key = nacl.signing.SigningKey(private_key[:32])
    signature = signing_key.sign(full_hash).signature

    # Build proof structure matching swap.coffee ApiTonProof format
    proof = {
        "timestamp": timestamp,
        "domain_len": domain_len,
        "domain_val": domain,
        "payload": payload,
        "signature": base64.b64encode(signature).decode("ascii"),
    }

    return proof


def generate_xverify_header(
    wallet_address: str,
    private_key: bytes,
    public_key: bytes,
    state_init_b64: Optional[str] = None,
    payload: Optional[str] = None,
) -> str:
    """
    Generate x-verify header value for swap.coffee API.

    Format matches ApiProofValidationRequest:
    - public_key: hex string
    - wallet_state_init: base64 string
    - proof: ApiTonProof

    Args:
        wallet_address: User's wallet address
        private_key: 32-byte Ed25519 private key
        public_key: 32-byte Ed25519 public key
        state_init_b64: Optional base64-encoded stateInit
        payload: Optional payload/nonce (if None, generates random)

    Returns:
        JSON string to use as x-verify header value
    """
    # Generate random payload if not provided (required by swap.coffee)
    if payload is None:
        payload = secrets.token_hex(32)

    proof = generate_ton_proof(wallet_address, private_key, payload)

    # Format matching ApiProofValidationRequest
    xverify = {
        "public_key": public_key.hex(),
        "wallet_state_init": state_init_b64 or "",
        "proof": proof,
    }

    return json.dumps(xverify, separators=(",", ":"))


# =============================================================================
# Wallet Key Extraction
# =============================================================================


def get_wallet_keys(wallet_data: dict) -> Tuple[bytes, bytes, str]:
    """
    Extract private key, public key, and stateInit from wallet data.

    Args:
        wallet_data: Wallet dict with mnemonic

    Returns:
        Tuple of (private_key, public_key, state_init_b64)
    """
    if not TONSDK_AVAILABLE:
        raise RuntimeError("tonsdk not installed. Run: pip install tonsdk")

    mnemonic = wallet_data.get("mnemonic")
    if not mnemonic:
        raise ValueError("Wallet has no mnemonic")

    if isinstance(mnemonic, str):
        mnemonic = mnemonic.split()

    version_map = {
        "v3r2": WalletVersionEnum.v3r2,
        "v4r2": WalletVersionEnum.v4r2,
    }

    version = wallet_data.get("version", "v4r2")
    wallet_version = version_map.get(version.lower(), WalletVersionEnum.v4r2)

    # Generate wallet from mnemonic
    _mnemonics, public_key, private_key, wallet = Wallets.from_mnemonics(
        mnemonic, wallet_version, workchain=0
    )

    # Get stateInit
    state_init = wallet.create_state_init()["state_init"]
    state_init_b64 = base64.b64encode(state_init.to_boc(False)).decode("ascii")

    return private_key, public_key, state_init_b64


# =============================================================================
# API Helpers
# =============================================================================


def _make_url_safe(address: str) -> str:
    """Convert address to URL-safe format."""
    return address.replace("+", "-").replace("/", "_")


def get_swap_coffee_key() -> Optional[str]:
    """Get swap.coffee API key from config."""
    config = load_config()
    return config.get("swap_coffee_key") or os.environ.get("SWAP_COFFEE_KEY")


def strategy_request(
    endpoint: str,
    method: str = "GET",
    params: Optional[dict] = None,
    json_data: Optional[dict] = None,
    xverify: Optional[str] = None,
    wallet_address: Optional[str] = None,
) -> dict:
    """
    Make request to swap.coffee Strategy API.

    Args:
        endpoint: API endpoint (e.g., "/wallets")
        method: HTTP method
        params: Query parameters
        json_data: JSON body
        xverify: x-verify header value (TonConnect proof)
        wallet_address: Wallet address header

    Returns:
        dict with success, data/error, status_code
    """
    url = f"{STRATEGIES_API_V1}{endpoint}"
    api_key = get_swap_coffee_key()

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    if api_key:
        headers["X-Api-Key"] = api_key

    if xverify:
        headers["x-verify"] = xverify

    if wallet_address:
        headers["wallet_address"] = wallet_address

    return api_request(
        url=url,
        method=method,
        headers=headers,
        params=params,
        json_data=json_data,
    )


# =============================================================================
# Wallet Storage
# =============================================================================


def get_wallet_from_storage(identifier: str, password: str) -> Optional[dict]:
    """Get wallet from encrypted storage."""
    try:
        from wallet import WalletStorage

        storage = WalletStorage(password)
        return storage.get_wallet(identifier, include_secrets=True)
    except Exception:
        return None


def create_wallet_instance(wallet_data: dict):
    """Create wallet instance for signing."""
    if not TONSDK_AVAILABLE:
        raise RuntimeError("tonsdk not installed")

    mnemonic = wallet_data.get("mnemonic")
    if not mnemonic:
        raise ValueError("Wallet has no mnemonic")

    if isinstance(mnemonic, str):
        mnemonic = mnemonic.split()

    version_map = {
        "v3r2": WalletVersionEnum.v3r2,
        "v4r2": WalletVersionEnum.v4r2,
    }

    version = wallet_data.get("version", "v4r2")
    wallet_version = version_map.get(version.lower(), WalletVersionEnum.v4r2)

    _, _, _, wallet = Wallets.from_mnemonics(mnemonic, wallet_version, workchain=0)
    return wallet


def get_seqno(address: str) -> int:
    """Get wallet seqno."""
    addr_safe = _make_url_safe(address)
    result = tonapi_request(f"/wallet/{addr_safe}/seqno")
    if result["success"]:
        return result["data"].get("seqno", 0)
    return 0


# =============================================================================
# Strategy Wallet Operations
# =============================================================================


def check_strategy_wallet(wallet_address: str, xverify: Optional[str] = None) -> dict:
    """
    Check if strategies wallet exists for the user.

    GET /v1/strategies/{address}/wallet

    Args:
        wallet_address: User's wallet address
        xverify: x-verify header (TonConnect proof) - required

    Returns:
        dict with wallet status
    """
    addr_safe = _make_url_safe(wallet_address)

    result = strategy_request(f"/{addr_safe}/wallet", xverify=xverify)

    if not result["success"]:
        if result.get("status_code") == 404:
            return {
                "success": True,
                "has_wallet": False,
                "wallet_address": wallet_address,
                "message": "⚠️ Strategies wallet NOT deployed. Use 'create-wallet' first.",
                "next_step": "Run: strategies.py create-wallet --wallet <name> --confirm",
            }
        return {
            "success": False,
            "error": result.get("error", "Failed to check strategies wallet"),
            "wallet_address": wallet_address,
            "note": "x-verify header may be required for this endpoint",
        }

    data = result["data"]

    return {
        "success": True,
        "has_wallet": True,
        "wallet_address": wallet_address,
        "strategies_wallet": data,
        "message": "✅ Strategies wallet exists. Ready to create orders.",
    }


def create_strategy_wallet(wallet_address: str, xverify: str) -> dict:
    """
    Create strategies wallet (one-time deployment).

    POST /v1/strategies/{address}/wallet

    Args:
        wallet_address: User's wallet address
        xverify: x-verify header (required)

    Returns:
        dict with transaction to sign and send
    """
    addr_safe = _make_url_safe(wallet_address)

    result = strategy_request(
        f"/{addr_safe}/wallet",
        method="POST",
        xverify=xverify,
    )

    if not result["success"]:
        return {
            "success": False,
            "error": result.get("error", "Failed to create strategies wallet"),
            "wallet_address": wallet_address,
        }

    data = result["data"]

    return {
        "success": True,
        "wallet_address": wallet_address,
        "transaction": {
            "address": data.get("address"),
            "value": data.get("value"),
            "payload_cell": data.get("payload_cell"),
            "state_init": data.get("state_init"),
        },
        "message": "Sign and send this transaction to deploy your strategies wallet.",
    }


def check_eligibility(wallet_address: str, xverify: Optional[str] = None) -> dict:
    """
    Check if wallet is eligible for strategies.

    GET /v1/strategies/eligibility/user/{address}

    Args:
        wallet_address: User's wallet address
        xverify: x-verify header (required)

    Returns:
        dict with eligibility info
    """
    addr_safe = _make_url_safe(wallet_address)

    result = strategy_request(f"/eligibility/user/{addr_safe}", xverify=xverify)

    if not result["success"]:
        if result.get("status_code") == 404:
            # Endpoint may not exist, assume eligible
            return {
                "success": True,
                "wallet_address": wallet_address,
                "eligible": True,
                "message": "Eligibility check not available, assuming eligible",
            }
        return {
            "success": False,
            "error": result.get("error", "Failed to check eligibility"),
        }

    data = result["data"]
    eligible = data.get("eligible", True) if isinstance(data, dict) else True

    return {
        "success": True,
        "wallet_address": wallet_address,
        "eligible": eligible,
        "reason": data.get("reason") if isinstance(data, dict) else None,
        "message": "✅ Eligible for strategies" if eligible else "❌ Not eligible",
    }


def get_from_tokens(order_type: str = "limit") -> dict:
    """
    Get eligible from-tokens for strategies.

    GET /v1/strategy/from-tokens?type=limit|dca

    Args:
        order_type: Order type (limit or dca)

    Returns:
        dict with list of eligible tokens
    """
    if order_type not in ORDER_TYPES:
        return {"success": False, "error": f"Invalid type. Must be: {ORDER_TYPES}"}

    result = strategy_request("/eligibility/from-tokens", params={"type": order_type})

    if not result["success"]:
        return {
            "success": False,
            "error": result.get("error", "Failed to get from-tokens"),
        }

    data = result["data"]
    tokens = data if isinstance(data, list) else data.get("tokens", [])

    return {
        "success": True,
        "order_type": order_type,
        "tokens": tokens,
        "count": len(tokens),
    }


def get_to_tokens(order_type: str = "limit", from_token: str = "native") -> dict:
    """
    Get eligible to-tokens for a given from-token.

    GET /v1/strategies/eligibility/to-tokens/{from_token}?type=X

    Args:
        order_type: Order type (limit or dca)
        from_token: From token address ("native" for TON)

    Returns:
        dict with list of eligible tokens
    """
    if order_type not in ORDER_TYPES:
        return {"success": False, "error": f"Invalid type. Must be: {ORDER_TYPES}"}

    from_safe = _make_url_safe(from_token)
    result = strategy_request(
        f"/eligibility/to-tokens/{from_safe}", params={"type": order_type}
    )

    if not result["success"]:
        return {
            "success": False,
            "error": result.get("error", "Failed to get to-tokens"),
        }

    data = result["data"]
    tokens = data if isinstance(data, list) else data.get("tokens", [])

    return {
        "success": True,
        "order_type": order_type,
        "from_token": from_token,
        "tokens": tokens,
        "count": len(tokens),
    }


# =============================================================================
# Order Operations
# =============================================================================


def list_orders(
    wallet_address: str,
    xverify: str,
    order_type: Optional[str] = None,
    include_finished: bool = False,
) -> dict:
    """
    List strategy orders for wallet.

    GET /v1/strategies/{address}/orders

    Args:
        wallet_address: User's wallet address
        xverify: x-verify header
        order_type: Filter by type (limit, dca)
        include_finished: Include completed/cancelled orders

    Returns:
        dict with list of orders
    """
    addr_safe = _make_url_safe(wallet_address)
    params = {}
    if order_type:
        params["type"] = order_type
    if include_finished:
        params["include_finished"] = "true"

    result = strategy_request(
        f"/{addr_safe}/orders", params=params if params else None, xverify=xverify
    )

    if not result["success"]:
        if result.get("status_code") == 404:
            return {
                "success": True,
                "wallet_address": wallet_address,
                "orders": [],
                "count": 0,
                "message": "No orders found",
            }
        return {"success": False, "error": result.get("error", "Failed to list orders")}

    data = result["data"]
    orders = data if isinstance(data, list) else data.get("orders", [])

    return {
        "success": True,
        "wallet_address": wallet_address,
        "orders": orders,
        "count": len(orders),
        "filters": {"type": order_type, "include_finished": include_finished},
    }


def get_order(order_id: str, wallet_address: str, xverify: str) -> dict:
    """
    Get order details.

    GET /v1/strategies/{address}/order?id=X

    Args:
        order_id: Order ID
        wallet_address: User's wallet address
        xverify: x-verify header (required)

    Returns:
        dict with order details
    """
    addr_safe = _make_url_safe(wallet_address)

    result = strategy_request(
        f"/{addr_safe}/order", params={"id": order_id}, xverify=xverify
    )

    if not result["success"]:
        return {
            "success": False,
            "error": result.get("error", "Order not found"),
            "order_id": order_id,
        }

    return {"success": True, "order_id": order_id, "order": result["data"]}


def create_order(
    wallet_address: str,
    xverify: str,
    order_type: str,
    token_from: str,
    token_to: str,
    input_amount: str,
    max_suborders: int = 1,
    max_invocations: int = 1,
    slippage: float = 0.01,
    settings: Optional[dict] = None,
) -> dict:
    """
    Create a strategy order.

    POST /v1/strategies/{address}/order

    Args:
        wallet_address: User's wallet address
        xverify: x-verify header
        order_type: "limit" or "dca"
        token_from: From token address ("native" for TON)
        token_to: To token address
        input_amount: Amount in nano-units (string)
        max_suborders: Max suborders (default 1)
        max_invocations: Max invocations (default 1)
        slippage: Slippage as decimal (0.0-1.0, e.g. 0.01=1%, 0.05=5%)
        settings: Order-specific settings:
            - For limit: {"min_output_amount": "VALUE"}
            - For DCA: {"delay": 3600, "price_range_from": 0.0, "price_range_to": 0.0}

    Returns:
        dict with transaction to sign and send
    """
    if order_type not in ORDER_TYPES:
        return {"success": False, "error": f"Invalid type. Must be: {ORDER_TYPES}"}

    addr_safe = _make_url_safe(wallet_address)

    order_data = {
        "type": order_type,
        "token_from": {
            "blockchain": "ton",
            "address": token_from,
        },
        "token_to": {
            "blockchain": "ton",
            "address": token_to,
        },
        "input_amount": str(input_amount),
        "max_suborders": max_suborders,
        "max_invocations": max_invocations,
        "slippage": slippage,
        "settings": settings or {},
    }

    result = strategy_request(
        f"/{addr_safe}/order",
        method="POST",
        json_data=order_data,
        xverify=xverify,
    )

    if not result["success"]:
        return {
            "success": False,
            "error": result.get("error", "Failed to create order"),
            "order_type": order_type,
        }

    data = result["data"]

    return {
        "success": True,
        "order_type": order_type,
        "transaction": {
            "address": data.get("address"),
            "value": data.get("value"),
            "payload_cell": data.get("payload_cell"),
        },
        "order_preview": {
            "token_from": token_from,
            "token_to": token_to,
            "input_amount": input_amount,
            "settings": settings,
        },
        "message": "Sign and send this transaction to create the order.",
    }


def cancel_order(
    order_id: str,
    wallet_address: str,
    xverify: str,
) -> dict:
    """
    Cancel a strategy order.

    DELETE /v1/strategies/{address}/order?id=X  (or /v1/strategies/cancel/by-id/{id})

    Args:
        order_id: Order ID to cancel
        wallet_address: User's wallet address
        xverify: x-verify header

    Returns:
        dict with transaction to sign and send
    """
    addr_safe = _make_url_safe(wallet_address)

    result = strategy_request(
        f"/{addr_safe}/order",
        method="DELETE",
        params={"id": order_id},
        xverify=xverify,
        wallet_address=wallet_address,
    )

    if not result["success"]:
        return {
            "success": False,
            "error": result.get("error", "Failed to cancel order"),
            "order_id": order_id,
        }

    data = result["data"]

    return {
        "success": True,
        "order_id": order_id,
        "transaction": {
            "address": data.get("address"),
            "value": data.get("value"),
            "payload_cell": data.get("payload_cell"),
        },
        "message": "Sign and send this transaction to cancel the order.",
    }


# =============================================================================
# Transaction Execution
# =============================================================================


def emulate_transaction(boc_b64: str) -> dict:
    """Emulate transaction before sending."""
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
    """Send transaction to blockchain."""
    result = tonapi_request(
        "/blockchain/message", method="POST", json_data={"boc": boc_b64}
    )

    if not result["success"]:
        return {"success": False, "error": result.get("error")}

    return {"success": True, "data": result.get("data")}


def execute_strategy_tx(
    wallet_data: dict,
    transaction: dict,
    confirm: bool = False,
) -> dict:
    """
    Execute a strategy transaction (create wallet, create order, cancel order).

    Args:
        wallet_data: Wallet dict with mnemonic
        transaction: Transaction dict from API (address, value, payload_cell)
        confirm: Actually send (True) or just emulate (False)

    Returns:
        dict with execution result
    """
    if not TONSDK_AVAILABLE:
        return {"success": False, "error": "tonsdk not installed"}

    sender_address = wallet_data["address"]
    wallet = create_wallet_instance(wallet_data)
    seqno = get_seqno(sender_address)

    to_addr = transaction.get("address")
    amount = int(transaction.get("value", "0"))
    payload_b64 = transaction.get("payload_cell")
    state_init_b64 = transaction.get("state_init")

    if not to_addr:
        return {"success": False, "error": "Missing transaction address"}

    # Decode payload cell
    payload = None
    if payload_b64:
        try:
            cell_bytes = base64.b64decode(payload_b64)
            payload = Cell.one_from_boc(cell_bytes)
        except Exception as e:
            return {"success": False, "error": f"Failed to decode payload: {e}"}

    # Decode state_init if present
    state_init = None
    if state_init_b64:
        try:
            si_bytes = base64.b64decode(state_init_b64)
            state_init = Cell.one_from_boc(si_bytes)
        except Exception as e:
            return {"success": False, "error": f"Failed to decode state_init: {e}"}

    # Create transfer message
    try:
        query = wallet.create_transfer_message(
            to_addr=to_addr,
            amount=amount,
            payload=payload,
            seqno=seqno,
            state_init=state_init,
        )
    except Exception as e:
        return {"success": False, "error": f"Failed to create transfer: {e}"}

    boc = query["message"].to_boc(False)
    boc_b64 = base64.b64encode(boc).decode("ascii")

    # Emulate
    emulation = emulate_transaction(boc_b64)

    result = {
        "wallet": sender_address,
        "to": to_addr,
        "amount_nano": amount,
        "amount_ton": amount / 1e9,
        "emulation": emulation,
        "boc": boc_b64,
    }

    if confirm:
        send_result = send_transaction(boc_b64)
        result["sent"] = send_result["success"]
        if send_result["success"]:
            result["success"] = True
            result["message"] = "✅ Transaction sent successfully"
        else:
            result["success"] = False
            result["error"] = send_result.get("error", "Failed to send")
    else:
        result["success"] = True
        result["confirmed"] = False
        result["message"] = "Transaction simulated. Use --confirm to execute."

    return result


# =============================================================================
# CLI Helpers
# =============================================================================


def resolve_wallet_and_xverify(
    wallet_label: str,
    password: str,
) -> Tuple[Optional[dict], Optional[str]]:
    """
    Resolve wallet data and generate x-verify header.

    Args:
        wallet_label: Wallet label or address
        password: Wallet password

    Returns:
        Tuple of (wallet_data, xverify_header)
    """
    wallet_data = get_wallet_from_storage(wallet_label, password)
    if not wallet_data:
        return None, None

    try:
        private_key, public_key, state_init = get_wallet_keys(wallet_data)
        xverify = generate_xverify_header(
            wallet_data["address"],
            private_key,
            public_key,
            state_init,
        )
        return wallet_data, xverify
    except Exception:
        return wallet_data, None


def resolve_token(token: str) -> str:
    """Resolve token symbol or address."""
    # Common token symbols
    TOKENS = {
        "TON": "native",
        "USDT": "EQCxE6mUtQJKFnGfaROTKOt1lZbDiiX1kCixRv7Nw2Id_sDs",
        "USDC": "EQC61IQRl0_la95t27xhIpjxZt32vl1QQVF2UgTNuvD18W-4",
        "NOT": "EQAvlWFDxGF2lXm67y4yzC17wYKD9A0guwPkMs1gOsM__NOT",
        "DOGS": "EQCvxJy4eG8hyHBFsZ7eePxrRsUQSFE_jpptRAYBmcG_DOGS",
        "DUST": "EQBlqsm144Dq6SjbPI4jjZvA1hqTIP3CvHovbIfW_t-SCALE",
    }

    upper = token.upper().strip()
    if upper in TOKENS:
        return TOKENS[upper]

    return token


# =============================================================================
# CLI
# =============================================================================


def main():
    parser = argparse.ArgumentParser(
        description="DCA & Limit Orders via swap.coffee Strategies API",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
================================================================================
WORKFLOW
================================================================================
1. Check if strategies wallet exists:
   %(prog)s check --wallet main

2. Create strategies wallet (one-time):
   %(prog)s create-wallet --wallet main --confirm

3. Check eligible tokens:
   %(prog)s from-tokens --type limit
   %(prog)s to-tokens --type limit --from native

4. Create order:
   %(prog)s create-order --wallet main --type limit \\
       --from TON --to USDT --amount 10 \\
       --min-output 50000000 --confirm

5. List orders:
   %(prog)s list-orders --wallet main

6. Cancel order:
   %(prog)s cancel-order --wallet main --order-id <ID> --confirm

================================================================================

Examples:
  # Check strategies wallet status
  %(prog)s check --address UQBvW8...
  %(prog)s check --wallet main
  
  # Check eligibility
  %(prog)s eligible --address UQBvW8...
  
  # Get eligible tokens
  %(prog)s from-tokens --type limit
  %(prog)s to-tokens --type limit --from native
  %(prog)s to-tokens --type dca --from TON
  
  # Create strategies wallet (one-time)
  %(prog)s create-wallet --wallet main --confirm
  
  # Create limit order (buy USDT when price is good)
  %(prog)s create-order --wallet main --type limit \\
      --from TON --to USDT --amount 10 \\
      --min-output 50000000000 --slippage 0.01 --confirm
  
  # Create DCA order (buy USDT every hour)
  %(prog)s create-order --wallet main --type dca \\
      --from TON --to USDT --amount 100 \\
      --delay 3600 --invocations 10 --confirm
  
  # List orders
  %(prog)s list-orders --wallet main
  %(prog)s list-orders --wallet main --status active
  
  # Get order details
  %(prog)s get-order --wallet main --order-id abc123
  
  # Cancel order
  %(prog)s cancel-order --wallet main --order-id abc123 --confirm

Order Types:
  limit - Execute when target price/output is reached
  dca   - Dollar Cost Averaging (periodic purchases)

Limit Order Settings:
  --min-output   Minimum output amount in nano-units

DCA Order Settings:
  --delay        Delay between purchases in seconds (e.g., 3600 = 1 hour)
  --invocations  Number of purchases to make
""",
    )

    parser.add_argument(
        "--password", "-p", help="Wallet password (or WALLET_PASSWORD env)"
    )

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # --- check ---
    check_p = subparsers.add_parser("check", help="Check if strategies wallet exists")
    check_grp = check_p.add_mutually_exclusive_group(required=True)
    check_grp.add_argument("--address", "-a", help="Wallet address")
    check_grp.add_argument("--wallet", "-w", help="Wallet label")

    # --- eligible ---
    elig_p = subparsers.add_parser("eligible", help="Check if wallet is eligible")
    elig_grp = elig_p.add_mutually_exclusive_group(required=True)
    elig_grp.add_argument("--address", "-a", help="Wallet address")
    elig_grp.add_argument("--wallet", "-w", help="Wallet label")

    # --- from-tokens ---
    ft_p = subparsers.add_parser("from-tokens", help="Get eligible from-tokens")
    ft_p.add_argument(
        "--type", "-t", choices=ORDER_TYPES, default="limit", help="Order type"
    )

    # --- to-tokens ---
    tt_p = subparsers.add_parser("to-tokens", help="Get eligible to-tokens")
    tt_p.add_argument(
        "--type", "-t", choices=ORDER_TYPES, default="limit", help="Order type"
    )
    tt_p.add_argument(
        "--from", "-f", dest="from_token", default="native", help="From token"
    )

    # --- create-wallet ---
    cw_p = subparsers.add_parser(
        "create-wallet", help="Create strategies wallet (one-time)"
    )
    cw_p.add_argument("--wallet", "-w", required=True, help="Wallet label")
    cw_p.add_argument("--confirm", action="store_true", help="Confirm execution")

    # --- list-orders ---
    lo_p = subparsers.add_parser("list-orders", help="List strategy orders")
    lo_p.add_argument("--wallet", "-w", required=True, help="Wallet label")
    lo_p.add_argument(
        "--type", "-t", choices=ORDER_TYPES, help="Filter by type (limit, dca)"
    )
    lo_p.add_argument(
        "--include-finished",
        action="store_true",
        help="Include completed/cancelled orders",
    )

    # --- get-order ---
    go_p = subparsers.add_parser("get-order", help="Get order details")
    go_p.add_argument("--wallet", "-w", required=True, help="Wallet label")
    go_p.add_argument("--order-id", "-o", required=True, help="Order ID")

    # --- create-order ---
    co_p = subparsers.add_parser("create-order", help="Create strategy order")
    co_p.add_argument("--wallet", "-w", required=True, help="Wallet label")
    co_p.add_argument(
        "--type", "-t", choices=ORDER_TYPES, required=True, help="Order type"
    )
    co_p.add_argument(
        "--from", "-f", dest="from_token", required=True, help="From token"
    )
    co_p.add_argument("--to", dest="to_token", required=True, help="To token")
    co_p.add_argument(
        "--amount", "-a", required=True, help="Input amount (TON/token units)"
    )
    co_p.add_argument(
        "--slippage",
        type=float,
        default=0.01,
        help="Slippage (0.0-1.0, e.g. 0.01=1%%, 0.05=5%%). Default: 0.01",
    )
    co_p.add_argument(
        "--suborders", type=int, default=1, help="Max suborders (default: 1)"
    )
    # Limit order settings
    co_p.add_argument(
        "--min-output", help="Minimum output amount (nano-units) for limit orders"
    )
    # DCA settings
    co_p.add_argument(
        "--delay", type=int, help="Delay between purchases in seconds (for DCA)"
    )
    co_p.add_argument("--invocations", type=int, help="Number of invocations (for DCA)")
    co_p.add_argument("--price-from", type=float, help="Price range from (for DCA)")
    co_p.add_argument("--price-to", type=float, help="Price range to (for DCA)")
    co_p.add_argument("--confirm", action="store_true", help="Confirm execution")

    # --- cancel-order ---
    cancel_p = subparsers.add_parser("cancel-order", help="Cancel strategy order")
    cancel_p.add_argument("--wallet", "-w", required=True, help="Wallet label")
    cancel_p.add_argument("--order-id", "-o", required=True, help="Order ID")
    cancel_p.add_argument("--confirm", action="store_true", help="Confirm execution")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    try:
        password = args.password or os.environ.get("WALLET_PASSWORD")

        # Commands that don't need wallet auth
        if args.command == "from-tokens":
            result = get_from_tokens(args.type)

        elif args.command == "to-tokens":
            from_token = resolve_token(args.from_token)
            result = get_to_tokens(args.type, from_token)

        # Commands that may need wallet auth
        elif args.command == "check":
            wallet_addr = args.address
            xverify = None

            if args.wallet:
                if not password:
                    if sys.stdin.isatty():
                        password = getpass.getpass("Wallet password: ")
                    else:
                        print(json.dumps({"error": "Password required"}))
                        return sys.exit(1)

                wallet_data, xverify = resolve_wallet_and_xverify(args.wallet, password)
                if wallet_data:
                    wallet_addr = wallet_data["address"]
                else:
                    print(json.dumps({"error": f"Wallet not found: {args.wallet}"}))
                    return sys.exit(1)

            result = check_strategy_wallet(wallet_addr, xverify)

        # Commands that require wallet auth
        elif args.command in (
            "eligible",
            "create-wallet",
            "list-orders",
            "get-order",
            "create-order",
            "cancel-order",
        ):
            if not password:
                if sys.stdin.isatty():
                    password = getpass.getpass("Wallet password: ")
                else:
                    print(json.dumps({"error": "Password required"}))
                    return sys.exit(1)

            wallet_data, xverify = resolve_wallet_and_xverify(args.wallet, password)
            if not wallet_data:
                print(json.dumps({"error": f"Wallet not found: {args.wallet}"}))
                return sys.exit(1)

            if not xverify:
                print(
                    json.dumps(
                        {
                            "error": "Failed to generate x-verify. Check wallet has mnemonic.",
                            "note": "pynacl library required: pip install pynacl",
                        }
                    )
                )
                return sys.exit(1)

            if args.command == "eligible":
                result = check_eligibility(wallet_data["address"], xverify)

            elif args.command == "create-wallet":
                tx_result = create_strategy_wallet(wallet_data["address"], xverify)
                if not tx_result["success"]:
                    result = tx_result
                elif tx_result.get("transaction", {}).get("address"):
                    result = execute_strategy_tx(
                        wallet_data,
                        tx_result["transaction"],
                        confirm=args.confirm,
                    )
                    result["operation"] = "create_strategies_wallet"
                else:
                    result = tx_result

            elif args.command == "list-orders":
                result = list_orders(
                    wallet_data["address"],
                    xverify,
                    order_type=getattr(args, "type", None),
                    include_finished=getattr(args, "include_finished", False),
                )

            elif args.command == "get-order":
                result = get_order(args.order_id, wallet_data["address"], xverify)

            elif args.command == "create-order":
                from_token = resolve_token(args.from_token)
                to_token = resolve_token(args.to_token)

                # Convert amount to nano-units
                try:
                    amount_float = float(args.amount)
                    # Assume TON or standard jetton (9 decimals)
                    input_amount = str(int(amount_float * 1e9))
                except ValueError:
                    input_amount = args.amount

                # Build settings
                settings = {}
                if args.type == "limit":
                    if args.min_output:
                        settings["min_output_amount"] = str(args.min_output)
                    else:
                        print(
                            json.dumps(
                                {"error": "--min-output required for limit orders"}
                            )
                        )
                        return sys.exit(1)
                elif args.type == "dca":
                    settings["delay"] = args.delay or 3600
                    settings["price_range_from"] = args.price_from or 0.0
                    settings["price_range_to"] = args.price_to or 0.0

                max_invocations = args.invocations or 1

                tx_result = create_order(
                    wallet_data["address"],
                    xverify,
                    args.type,
                    from_token,
                    to_token,
                    input_amount,
                    max_suborders=args.suborders,
                    max_invocations=max_invocations,
                    slippage=args.slippage,
                    settings=settings,
                )

                if not tx_result["success"]:
                    result = tx_result
                elif tx_result.get("transaction", {}).get("address"):
                    result = execute_strategy_tx(
                        wallet_data,
                        tx_result["transaction"],
                        confirm=args.confirm,
                    )
                    result["operation"] = f"create_{args.type}_order"
                    result["order_preview"] = tx_result.get("order_preview")
                else:
                    result = tx_result

            elif args.command == "cancel-order":
                tx_result = cancel_order(args.order_id, wallet_data["address"], xverify)
                if not tx_result["success"]:
                    result = tx_result
                elif tx_result.get("transaction", {}).get("address"):
                    result = execute_strategy_tx(
                        wallet_data,
                        tx_result["transaction"],
                        confirm=args.confirm,
                    )
                    result["operation"] = "cancel_order"
                    result["order_id"] = args.order_id
                else:
                    result = tx_result

        else:
            result = {"error": f"Unknown command: {args.command}"}

        print(json.dumps(result, indent=2, ensure_ascii=False))

        if not result.get("success", False):
            return sys.exit(1)

    except KeyboardInterrupt:
        print(json.dumps({"error": "Interrupted"}))
        return sys.exit(1)
    except Exception as e:
        print(json.dumps({"error": str(e)}, indent=2))
        return sys.exit(1)


if __name__ == "__main__":
    main()
