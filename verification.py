"""
verification.py
───────────────
Identity verification logic.

Rules (from spec):
  • Full name must match EXACTLY (case-sensitive, no fuzzy matching)
  • Plus at least ONE secondary factor: DOB | Aadhaar last 4 | Pincode

IMPORTANT: account_data is never logged or echoed back to the user.
"""

import re
from datetime import datetime
from typing import Optional, Tuple

from validators import extract_dob, extract_pincode, extract_aadhaar_last4


# ─── Core Verification ────────────────────────────────────────────────────────

def verify_identity(
    account_data: dict,
    provided_name: str,
    secondary_type: str,
    secondary_value: str,
) -> bool:
    """
    Returns True only if:
      1. provided_name matches account full_name EXACTLY (str equality)
      2. The secondary factor also matches exactly

    No case folding, no stripping, no fuzzy matching.
    """
    if not provided_name:
        return False

    if account_data.get("full_name") != provided_name:
        return False

    return _check_secondary(account_data, secondary_type, secondary_value)


def _check_secondary(account_data: dict, sec_type: str, sec_value: str) -> bool:
    """Strict exact-match for each secondary factor type."""
    if sec_type == "dob":
        return account_data.get("dob") == sec_value
    if sec_type == "aadhaar":
        return account_data.get("aadhaar_last4") == sec_value
    if sec_type == "pincode":
        return account_data.get("pincode") == sec_value
    return False


# ─── Secondary Factor Detection ───────────────────────────────────────────────

def detect_secondary(text: str) -> Optional[Tuple[str, str]]:
    """
    Detect which secondary verification factor the user has provided and
    return a (type, value) tuple, or None if none found.

    Priority order:
      1. DOB (YYYY-MM-DD) — unambiguous format
      2. Pincode (6 digits) — longer, checked before 4-digit Aadhaar
      3. Aadhaar last 4 (4 digits)

    This ordering avoids misclassifying a 4-digit run inside a longer number.
    """
    # 1. DOB  ── YYYY-MM-DD is uniquely formatted, highest priority
    dob = extract_dob(text)
    if dob:
        return ("dob", dob)

    # 2. Pincode  ── 6 consecutive digits not part of a longer number
    pincode = extract_pincode(text)
    if pincode:
        return ("pincode", pincode)

    # 3. Aadhaar last 4  ── exactly 4 digits standing alone
    aadhaar = extract_aadhaar_last4(text)
    if aadhaar:
        return ("aadhaar", aadhaar)

    return None