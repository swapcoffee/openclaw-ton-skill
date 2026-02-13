#!/usr/bin/env python3
"""
OpenClaw TON Skill — Shared Constants and Utilities

Centralized configuration for:
- Known tokens (symbol -> address mapping)
- DEX names and identifiers
- API base URLs
- Common error messages
- Formatting utilities
"""

from typing import Optional

# =============================================================================
# Known Tokens (symbol -> master contract address)
# =============================================================================

KNOWN_TOKENS = {
    # Native
    "TON": "native",
    # Stablecoins
    "USDT": "EQCxE6mUtQJKFnGfaROTKOt1lZbDiiX1kCixRv7Nw2Id_sDs",
    "USDC": "EQC61IQRl0_la95t27xhIpjxZt32vl1QQVF2UgTNuvD18W-4",
    "USDD": "EQB6VBdgxH7-xfK4NMcR2T6cS5B5lNB1wvkXLLdvQVBzHN3e",
    # Popular tokens
    "NOT": "EQAvlWFDxGF2lXm67y4yzC17wYKD9A0guwPkMs1gOsM__NOT",
    "STON": "EQA2kCVNwVsil2EM2mB0SkXytxCqQjS4mttjDpnXmwG9T6bO",
    "DUST": "EQBlqsm144Dq6SjbPI4jjZvA1hqTIP3CvHovbIfW_t-SCALE",
    "GRAM": "EQC47093oX5Xhb0xuk2lCr2RhS8rj-vul61u4W2UH5ORmG_O",
    "BOLT": "EQD0vdSA_NedR9uvbgN9EikRX-suesDxGeFg69XQMavfLqIw",
    "DOGS": "EQCvxJy4eG8hyHBFsZ7eePxrRsUQSFE_jpptRAYBmcG_DOGS",
    "CATS": "EQDcBkGHmc-gPJl3-UtjW6bNXvb6wj3TEqPrK_h8ffjj1Wr5",
    "MAJOR": "EQCupm9RXC8RM8c2wbWWKJCxF9YqxOaB3z0SxdXH7v-NjKqy",
    "KINGY": "EQC-tdRjjoYMz3MXKW4pj95bNZgvRyWwZ23Jix3ph7guvHxJ",
    # DeFi tokens
    "STONFI": "EQDNhy-nxYFgUqzfUzl3fy4uAPTgG51IkA7-0A-MR9bJSZLt",
    "DEDUST": "EQBlqsm144Dq6SjbPI4jjZvA1hqTIP3CvHovbIfW_t-SCALE",
    # Note: Megaton Finance is a DEX, not a token. Removed incorrect placeholder.
    # If MEGA token exists, add correct address here.
    # Wrapped
    "WTON": "EQCajaUU1XXSAjTD-xOV7pE49fGtg4q8kF3ELCOJtGvQFQ2C",
    "JTON": "EQBynBO23ywHy_CgarY9NK9FTz0yDsG82PtcbSTQgGoXwiuA",
    # Meme coins
    "REDO": "EQASLOvJXMUhqKu8yVTJkjnKeOxL3-sJkp8Lb-3iOkf-tYZX",
    "PUNK": "EQA8R2R0JMRXQzYKy_fNFbzgTbJHvzLQZI3k8Fh8dJcSo9BK",
}

# Reverse mapping (address -> symbol) for quick lookups
ADDRESS_TO_SYMBOL = {
    addr: symbol for symbol, addr in KNOWN_TOKENS.items() if addr != "native"
}


# =============================================================================
# DEX Names and Identifiers
# =============================================================================

DEX_NAMES = {
    "stonfi": "STON.fi",
    "dedust": "DeDust",
    "megaton": "Megaton Finance",
    "tonswap": "TON Swap",
    "coffeeswap": "swap.coffee",
    "gaspump": "GasPump",
    "tonco": "TONCO",
}

# DEX router addresses
DEX_ROUTERS = {
    "stonfi": "EQB3ncyBUTjZUA5EnFKR5_EnOMI9V1tTEAAPaiU71gc4TiUt",
    "stonfi_v2": "EQBwDJmKhIJERxFBZxGpVQx9QK7rALfNpXfCr-q7qAx1sCRT",
    "dedust": "EQBfBWT7X2BHg9tXAxzhz2aKiNTU1tpt5NsiK0uSDW_YAJ67",
}


# =============================================================================
# API URLs
# =============================================================================

# TonAPI
TONAPI_BASE_URL = "https://tonapi.io/v2"

# swap.coffee
SWAP_COFFEE_BASE_URL = "https://backend.swap.coffee"
SWAP_COFFEE_API_V1 = "https://backend.swap.coffee/v1"
SWAP_COFFEE_API_V2 = "https://backend.swap.coffee/v2"
TOKENS_API_BASE_URL = "https://tokens.swap.coffee"

# DYOR.io
DYOR_API_BASE_URL = "https://dyor.io/api/v1"

# TonCenter (alternative RPC)
TONCENTER_API_URL = "https://toncenter.com/api/v2"


# =============================================================================
# Verification Levels
# =============================================================================

VERIFICATION_LEVELS = ["WHITELISTED", "COMMUNITY", "UNKNOWN", "BLACKLISTED"]

TRUST_LEVEL_MAP = {
    "WHITELISTED": {"score": 90, "level": "high", "emoji": "✅"},
    "COMMUNITY": {"score": 70, "level": "medium", "emoji": "⚠️"},
    "UNKNOWN": {"score": 40, "level": "low", "emoji": "❓"},
    "BLACKLISTED": {"score": 5, "level": "scam", "emoji": "🚨"},
}


# =============================================================================
# Error Messages
# =============================================================================

ERROR_MESSAGES = {
    "missing_password": "Password required. Use --password or WALLET_PASSWORD env",
    "wallet_not_found": "Wallet not found: {}",
    "invalid_address": "Invalid TON address format: {}",
    "insufficient_balance": "Insufficient balance. Have: {}, need: {}",
    "api_timeout": "API request timeout",
    "api_connection": "Connection error. Check network connectivity",
    "missing_api_key": "{} API key not configured. Set it in config",
    "tonsdk_missing": "tonsdk not installed. Run: pip install tonsdk",
}


# =============================================================================
# Formatting Utilities
# =============================================================================


def format_price(price: Optional[float]) -> str:
    """Format price for display with appropriate precision."""
    if price is None:
        return "N/A"
    if price < 0.000001:
        return f"${price:.10f}"
    elif price < 0.0001:
        return f"${price:.8f}"
    elif price < 1:
        return f"${price:.6f}"
    elif price < 100:
        return f"${price:.4f}"
    else:
        return f"${price:,.2f}"


def format_large_number(num: Optional[float], prefix: str = "$") -> str:
    """Format large numbers (1.5M, 2.3B, etc.)."""
    if num is None:
        return "N/A"

    num = float(num)
    sign = "-" if num < 0 else ""
    num = abs(num)

    if num >= 1_000_000_000:
        return f"{sign}{prefix}{num / 1_000_000_000:.2f}B"
    elif num >= 1_000_000:
        return f"{sign}{prefix}{num / 1_000_000:.2f}M"
    elif num >= 1_000:
        return f"{sign}{prefix}{num / 1_000:.2f}K"
    else:
        return f"{sign}{prefix}{num:,.2f}"


def format_number(num: Optional[int]) -> str:
    """Format integer with thousand separators."""
    if num is None:
        return "N/A"
    return f"{int(num):,}"


def format_percent(pct: Optional[float], include_sign: bool = True) -> str:
    """Format percentage with optional sign."""
    if pct is None:
        return "N/A"
    sign = "+" if include_sign and pct > 0 else ""
    return f"{sign}{pct:.2f}%"


def format_ton_amount(nano: int) -> str:
    """Convert nanoTON to TON with proper formatting."""
    ton = nano / 1e9
    if ton < 0.001:
        return f"{ton:.9f} TON"
    elif ton < 1:
        return f"{ton:.6f} TON"
    elif ton < 1000:
        return f"{ton:.4f} TON"
    else:
        return f"{ton:,.2f} TON"


def truncate_address(address: str, start: int = 6, end: int = 4) -> str:
    """Truncate address for display: UQBvW8...Zo"""
    if len(address) <= start + end + 3:
        return address
    return f"{address[:start]}...{address[-end:]}"


# =============================================================================
# Token Resolution
# =============================================================================


def resolve_token_symbol(token: str) -> str:
    """
    Resolve token symbol or address to master contract address.

    Args:
        token: Token symbol (e.g., "USDT") or address

    Returns:
        Master contract address or "native" for TON
    """
    token_upper = token.upper().strip()

    # Check known tokens first
    if token_upper in KNOWN_TOKENS:
        return KNOWN_TOKENS[token_upper]

    # If it looks like an address, return as-is
    if ":" in token or len(token) > 40:
        return token

    # Unknown symbol - return as-is and let API handle it
    return token


def get_token_symbol(address: str) -> Optional[str]:
    """
    Get token symbol from address if known.

    Args:
        address: Token master contract address

    Returns:
        Token symbol or None
    """
    if address == "native":
        return "TON"
    return ADDRESS_TO_SYMBOL.get(address)


# =============================================================================
# CLI Help Text
# =============================================================================

COMMON_EPILOG = """
Environment variables:
  WALLET_PASSWORD    Password for encrypted wallet storage
  TONAPI_KEY         TonAPI API key (optional, increases rate limits)
  SWAP_COFFEE_KEY    swap.coffee API key (optional)
  DYOR_API_KEY       DYOR.io API key (optional, enables advanced analytics)

Configuration:
  Config file: ~/.openclaw/ton-skill/config.json
  Set API keys: python utils.py config set <key> <value>
  
Known tokens: TON, USDT, USDC, NOT, STON, DUST, DOGS, CATS, MAJOR, and more.
Use token symbol or full jetton master address.

For more information: https://github.com/openclaw/openclaw-ton-skill
"""


# =============================================================================
# Module exports
# =============================================================================

__all__ = [
    # Tokens
    "KNOWN_TOKENS",
    "ADDRESS_TO_SYMBOL",
    "resolve_token_symbol",
    "get_token_symbol",
    # DEX
    "DEX_NAMES",
    "DEX_ROUTERS",
    # APIs
    "TONAPI_BASE_URL",
    "SWAP_COFFEE_BASE_URL",
    "SWAP_COFFEE_API_V1",
    "SWAP_COFFEE_API_V2",
    "TOKENS_API_BASE_URL",
    "DYOR_API_BASE_URL",
    "TONCENTER_API_URL",
    # Verification
    "VERIFICATION_LEVELS",
    "TRUST_LEVEL_MAP",
    # Errors
    "ERROR_MESSAGES",
    # Formatting
    "format_price",
    "format_large_number",
    "format_number",
    "format_percent",
    "format_ton_amount",
    "truncate_address",
    # Help
    "COMMON_EPILOG",
]
