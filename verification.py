"""
verification.py
───────────────
Identity verification logic. Pure comparison — no decisions, no LLM.
Called only by tool_executor.py as the implementation of verify_identity tool.

Rules:
  • Full name must match EXACTLY (case-sensitive, exact string equality)
  • Plus at least ONE secondary factor: DOB | Aadhaar last 4 | Pincode

IMPORTANT: account_data is never logged or echoed back to the user.
"""

from validators import extract_dob, extract_pincode, extract_aadhaar_last4


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
    sec_type = sec_type.lower().strip()
    if sec_type == "dob":
        return account_data.get("dob") == sec_value
    if sec_type in ("aadhaar", "aadhaar_last4"):
        return account_data.get("aadhaar_last4") == sec_value
    if sec_type == "pincode":
        return account_data.get("pincode") == sec_value
    return False
