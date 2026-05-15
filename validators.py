"""
validators.py
─────────────
Pure-Python input validation. No LLM, no API calls, no decisions.
Called exclusively by tool_executor.py as the implementation behind
validate_* tool calls that the agent requests.
"""

import re
from datetime import datetime
from typing import Optional, Tuple, Union


# ─── Card Helpers ─────────────────────────────────────────────────────────────

def luhn_check(card_number: str) -> bool:
    """Luhn algorithm (mod-10 check) for card number validity."""
    digits = [int(d) for d in card_number if d.isdigit()]
    if not digits:
        return False
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def is_amex(card_number: str) -> bool:
    """American Express cards start with 34 or 37."""
    clean = re.sub(r"\D", "", card_number)
    return clean.startswith(("34", "37"))


def validate_card_number(card_number: str) -> Tuple[bool, str]:
    """
    Validate card number: digits only, length 13–19, passes Luhn.
    Returns (True, cleaned_digits) or (False, error_message).
    """
    clean = re.sub(r"[\s\-]", "", card_number)

    if not clean.isdigit():
        return False, "Card number must contain digits only."

    if not (13 <= len(clean) <= 19):
        return False, f"Card number length {len(clean)} is invalid (expected 13–19 digits)."

    if not luhn_check(clean):
        return False, "Card number is invalid (fails Luhn checksum)."

    return True, clean


def validate_cvv(cvv: str, card_number: str = "") -> Tuple[bool, str]:
    """
    Validate CVV: 3 digits for standard cards, 4 for Amex.
    """
    clean = re.sub(r"\D", "", cvv)
    expected_length = 4 if is_amex(card_number) else 3

    if len(clean) != expected_length:
        return (
            False,
            f"CVV must be {expected_length} digit(s) "
            f"({'Amex detected' if expected_length == 4 else 'standard card'}).",
        )

    return True, clean


def validate_expiry(
    month: Union[int, str], year: Union[int, str]
) -> Tuple[bool, Union[Tuple[int, int], str]]:
    """
    Validate expiry month/year. Handles 2-digit years.
    """
    try:
        month = int(month)
        year = int(year)
    except (ValueError, TypeError):
        return False, "Expiry month and year must be integers."

    if year < 100:
        year += 2000

    if not (1 <= month <= 12):
        return False, "Expiry month must be between 1 and 12."

    now = datetime.now()
    if year < now.year or (year == now.year and month < now.month):
        return False, "This card has expired."

    return True, (month, year)


def validate_amount(amount_str: str, balance: float) -> Tuple[bool, Union[float, str]]:
    """
    Validate payment amount: positive, max 2 decimal places, not exceeding balance.
    """
    cleaned = (
        str(amount_str)
        .replace("₹", "")
        .replace("Rs", "")
        .replace("rs", "")
        .replace(",", "")
        .strip()
    )

    try:
        amount = float(cleaned)
    except (ValueError, TypeError):
        return False, "Amount must be a valid number."

    if amount <= 0:
        return False, "Amount must be greater than zero."

    if "." in cleaned:
        decimal_part = cleaned.split(".")[1]
        if len(decimal_part) > 2:
            return False, "Amount must have at most 2 decimal places."

    amount = round(amount, 2)

    if amount > balance:
        return (
            False,
            f"Amount ₹{amount:,.2f} exceeds your outstanding balance of ₹{balance:,.2f}.",
        )

    return True, amount


# ─── Regex Extractors (used by verification.py only) ─────────────────────────

def extract_dob(text: str) -> Optional[str]:
    """Extract date of birth in YYYY-MM-DD format."""
    match = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", text)
    if match:
        return match.group(1)
    return None


def extract_pincode(text: str) -> Optional[str]:
    """Extract a 6-digit Indian pincode."""
    match = re.search(r"\b(\d{6})\b", text)
    return match.group(1) if match else None


def extract_aadhaar_last4(text: str) -> Optional[str]:
    """Extract the last 4 digits of Aadhaar (standalone 4-digit number)."""
    match = re.search(r"(?<!\d)(\d{4})(?!\d)", text)
    return match.group(1) if match else None
