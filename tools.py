"""
tools.py
────────
Thin wrappers around the two external API endpoints.

Both functions raise APIError on any non-happy-path response so the
caller (agent.py) always deals with a single exception type.
"""

import requests
from typing import Any, Dict


BASE_URL = (
    "https://se-payment-verification-api.service.external.usea2.aws.prodigaltech.com"
)
TIMEOUT_SECONDS = 12


# ─── Custom Exception ─────────────────────────────────────────────────────────

class APIError(Exception):
    """
    Raised for any API-level failure.

    Attributes
    ----------
    message     : Human-readable description
    status_code : HTTP status (0 for network errors)
    error_code  : Machine-readable code from API response, e.g. "account_not_found"
    """

    def __init__(self, message: str, status_code: int = 0, error_code: str = "unknown"):
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code

    def __repr__(self) -> str:
        return f"APIError(status={self.status_code}, code={self.error_code}, msg={str(self)})"


# ─── API Calls ────────────────────────────────────────────────────────────────

def lookup_account(account_id: str) -> Dict[str, Any]:
    """
    POST /api/lookup-account

    Returns the full account dict on 200.
    Raises APIError on 404 (account_not_found) or any other failure.

    NOTE: The returned dict contains sensitive fields (dob, aadhaar_last4,
    pincode).  The caller must NEVER expose these directly to the user.
    """
    try:
        resp = requests.post(
            f"{BASE_URL}/api/lookup-account",
            json={"account_id": account_id},
            timeout=TIMEOUT_SECONDS,
        )
    except requests.Timeout:
        raise APIError("Request timed out.", 0, "timeout")
    except requests.ConnectionError as exc:
        raise APIError(f"Network error: {exc}", 0, "network_error")
    except requests.RequestException as exc:
        raise APIError(f"Unexpected request error: {exc}", 0, "request_error")

    if resp.status_code == 200:
        return resp.json()

    # Try to parse a structured error body
    try:
        body = resp.json()
        error_code = body.get("error_code", "unknown")
        message = body.get("message", "Unknown error from lookup API.")
    except Exception:
        error_code = "unknown"
        message = f"Lookup API returned HTTP {resp.status_code}."

    raise APIError(message, resp.status_code, error_code)


def process_payment(
    account_id: str,
    amount: float,
    payment_method: Dict[str, Any],
) -> Dict[str, Any]:
    """
    POST /api/process-payment

    Returns the response dict for BOTH success (200) and application-level
    failure (422) — the caller inspects result["success"] and "error_code".

    Raises APIError only for network / unexpected HTTP errors.

    payment_method expected shape:
    {
        "type": "card",
        "card": {
            "cardholder_name": str,
            "card_number": str,   # digits only
            "cvv": str,
            "expiry_month": int,
            "expiry_year": int,
        }
    }
    """
    payload = {
        "account_id": account_id,
        "amount": amount,
        "payment_method": payment_method,
    }

    try:
        resp = requests.post(
            f"{BASE_URL}/api/process-payment",
            json=payload,
            timeout=TIMEOUT_SECONDS,
        )
    except requests.Timeout:
        raise APIError("Payment request timed out.", 0, "timeout")
    except requests.ConnectionError as exc:
        raise APIError(f"Network error: {exc}", 0, "network_error")
    except requests.RequestException as exc:
        raise APIError(f"Unexpected request error: {exc}", 0, "request_error")

    # 200 = success, 422 = application-level failure — both are valid responses
    if resp.status_code in (200, 422):
        return resp.json()

    raise APIError(
        f"Payment API returned unexpected HTTP {resp.status_code}.",
        resp.status_code,
        "unexpected_http",
    )