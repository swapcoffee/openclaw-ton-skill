#!/usr/bin/env python3
"""
OpenClaw TON Skill — User-Friendly Error Messages

Converts technical API errors into user-friendly messages with actionable suggestions.
"""

from typing import Optional, Dict, Any


# =============================================================================
# Error Message Mapping
# =============================================================================

ERROR_PATTERNS = {
    # DNS/Address resolution errors
    "not resolved": {
        "message": "Domain not found or has no wallet address",
        "reasons": [
            "Domain doesn't exist or expired",
            "No wallet address linked to this domain",
            "Network connectivity issue",
        ],
        "suggestion": "Try using the full wallet address instead",
    },
    "can't unmarshal null": {
        "message": "Domain not found",
        "reasons": [
            "Domain doesn't exist",
            "Domain expired",
            "No wallet configured for this domain",
        ],
        "suggestion": "Verify the domain name or use wallet address directly",
    },
    "invalid address": {
        "message": "Invalid TON address format",
        "reasons": [
            "Address format is incorrect",
            "Missing or invalid checksum",
            "Wrong address type",
        ],
        "suggestion": "Check the address format (should be base64url encoded)",
    },
    
    # API errors
    "not found": {
        "message": "Resource not found",
        "reasons": [
            "The requested resource doesn't exist",
            "API endpoint may have changed",
            "Resource was removed",
        ],
        "suggestion": "Check if the resource ID is correct",
    },
    "404": {
        "message": "API endpoint not available",
        "reasons": [
            "Endpoint may have been removed",
            "API version changed",
            "Feature not available yet",
        ],
        "suggestion": "Check API documentation for current endpoints",
    },
    "timeout": {
        "message": "Request timeout",
        "reasons": [
            "Network connection is slow",
            "API server is overloaded",
            "Request took too long",
        ],
        "suggestion": "Try again in a few moments",
    },
    "connection error": {
        "message": "Connection error",
        "reasons": [
            "No internet connection",
            "API server is down",
            "Network firewall blocking request",
        ],
        "suggestion": "Check your internet connection and try again",
    },
    
    # Wallet errors
    "insufficient balance": {
        "message": "Insufficient balance",
        "reasons": [
            "Not enough TON for transaction fee",
            "Not enough tokens for the operation",
            "Balance is less than required amount",
        ],
        "suggestion": "Check your balance and ensure you have enough for fees",
    },
    "wallet not found": {
        "message": "Wallet not found",
        "reasons": [
            "Wallet label doesn't exist",
            "Wallet address is incorrect",
            "Wallet not imported",
        ],
        "suggestion": "List wallets with 'wallet.py list' or use correct address",
    },
    "invalid password": {
        "message": "Invalid password",
        "reasons": [
            "Password is incorrect",
            "Password doesn't match wallet encryption",
        ],
        "suggestion": "Check your password and try again",
    },
    
    # Transaction errors
    "transaction failed": {
        "message": "Transaction failed",
        "reasons": [
            "Insufficient balance",
            "Invalid transaction parameters",
            "Smart contract rejected transaction",
        ],
        "suggestion": "Check transaction details and try again",
    },
    "seqno mismatch": {
        "message": "Transaction sequence number mismatch",
        "reasons": [
            "Another transaction was sent first",
            "Wallet state changed",
        ],
        "suggestion": "Wait a moment and try again",
    },
}


# =============================================================================
# Error Formatting Functions
# =============================================================================

def format_error(
    error: Any,
    error_type: Optional[str] = None,
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Convert technical error into user-friendly format.
    
    Args:
        error: Error message (string, dict, or exception)
        error_type: Type of error (e.g., "dns", "api", "wallet")
        context: Additional context (e.g., {"domain": "example.ton"})
    
    Returns:
        dict with formatted error message
    """
    # Extract error message
    error_msg = _extract_error_message(error)
    error_lower = error_msg.lower()
    
    # Find matching pattern
    matched_pattern = None
    for pattern, info in ERROR_PATTERNS.items():
        if pattern in error_lower:
            matched_pattern = info
            break
    
    # Build response
    result = {
        "success": False,
        "error": matched_pattern["message"] if matched_pattern else error_msg,
    }
    
    # Add reasons if pattern matched
    if matched_pattern:
        result["reasons"] = matched_pattern.get("reasons", [])
        result["suggestion"] = matched_pattern.get("suggestion", "")
    
    # Add context-specific information
    if context:
        if "domain" in context:
            result["domain"] = context["domain"]
            result["error"] = result["error"].replace("Domain", f'Domain "{context["domain"]}"')
        if "address" in context:
            result["address"] = context["address"]
        if "wallet" in context:
            result["wallet"] = context["wallet"]
    
    # Add technical details for debugging (if needed)
    if error_type == "api" and isinstance(error, dict):
        if "status_code" in error:
            result["status_code"] = error["status_code"]
        if "raw_error" not in result:
            result["raw_error"] = error_msg
    
    return result


def _extract_error_message(error: Any) -> str:
    """Extract error message from various error types."""
    if isinstance(error, str):
        return error
    elif isinstance(error, dict):
        return error.get("error", str(error))
    elif isinstance(error, Exception):
        return str(error)
    else:
        return str(error)


def format_dns_error(error: Any, domain: Optional[str] = None) -> Dict[str, Any]:
    """Format DNS resolution error."""
    return format_error(error, error_type="dns", context={"domain": domain} if domain else None)


def format_api_error(error: Any, endpoint: Optional[str] = None) -> Dict[str, Any]:
    """Format API error."""
    context = {"endpoint": endpoint} if endpoint else None
    result = format_error(error, error_type="api", context=context)
    if endpoint:
        result["endpoint"] = endpoint
    return result


def format_wallet_error(error: Any, wallet: Optional[str] = None) -> Dict[str, Any]:
    """Format wallet-related error."""
    return format_error(error, error_type="wallet", context={"wallet": wallet} if wallet else None)


def format_transaction_error(error: Any, tx_hash: Optional[str] = None) -> Dict[str, Any]:
    """Format transaction error."""
    context = {"tx_hash": tx_hash} if tx_hash else None
    result = format_error(error, error_type="transaction", context=context)
    if tx_hash:
        result["tx_hash"] = tx_hash
    return result


# =============================================================================
# Helper Functions
# =============================================================================

def is_api_unavailable_error(error: Any) -> bool:
    """Check if error indicates API endpoint is unavailable."""
    error_msg = _extract_error_message(error).lower()
    return (
        "404" in error_msg or
        "not found" in error_msg or
        "endpoint" in error_msg and "not available" in error_msg
    )


def get_error_suggestion(error: Any) -> Optional[str]:
    """Get suggestion for error if available."""
    error_msg = _extract_error_message(error).lower()
    for pattern, info in ERROR_PATTERNS.items():
        if pattern in error_msg:
            return info.get("suggestion")
    return None
