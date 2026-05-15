"""
tool_schemas.py
───────────────
Ollama-compatible tool schemas exposed to the agent.

The agent decides WHEN and HOW to call each tool. Python only executes
the results — no FSM, no rule-based routing.

Tool categories
───────────────
  ACCOUNT    : lookup_account
  IDENTITY   : verify_identity
  PAYMENT    : process_payment
  VALIDATION : validate_card_number, validate_cvv, validate_expiry, validate_amount
  SESSION    : lock_session, complete_session
"""

TOOLS = [
    # ── Account ───────────────────────────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "lookup_account",
            "description": (
                "Look up a customer account by account ID (format: ACC followed by digits, "
                "e.g. ACC1001). Call this as soon as the user provides any string that looks "
                "like an account ID. Returns account status and outstanding balance. "
                "Sensitive fields (dob, aadhaar_last4, pincode, full_name) are returned "
                "for internal verification use only — NEVER repeat them to the user."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "account_id": {
                        "type": "string",
                        "description": "The account ID exactly as provided by the user (e.g. ACC1001).",
                    }
                },
                "required": ["account_id"],
            },
        },
    },

    # ── Identity ──────────────────────────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "verify_identity",
            "description": (
                "Verify a customer's identity using their full name plus one secondary factor. "
                "Call this once the user has provided: (1) their full name AND (2) one of: "
                "date of birth (YYYY-MM-DD), Aadhaar last 4 digits, or registered pincode. "
                "Returns verified=true/false. On failure, track attempt count — after 3 "
                "total failures, call lock_session. NEVER reveal what the correct values are."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "account_id": {
                        "type": "string",
                        "description": "The account ID that was successfully looked up.",
                    },
                    "provided_name": {
                        "type": "string",
                        "description": "Full name exactly as stated by the user. Case-sensitive.",
                    },
                    "secondary_type": {
                        "type": "string",
                        "enum": ["dob", "aadhaar", "pincode"],
                        "description": (
                            "Which secondary factor the user provided: "
                            "'dob' for date of birth (YYYY-MM-DD), "
                            "'aadhaar' for last 4 digits of Aadhaar, "
                            "'pincode' for 6-digit registered pincode."
                        ),
                    },
                    "secondary_value": {
                        "type": "string",
                        "description": (
                            "The value for the secondary factor exactly as extracted from "
                            "user input. DOB format: YYYY-MM-DD. Aadhaar: 4 digits. Pincode: 6 digits."
                        ),
                    },
                },
                "required": ["account_id", "provided_name", "secondary_type", "secondary_value"],
            },
        },
    },

    # ── Payment ───────────────────────────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "process_payment",
            "description": (
                "Process a card payment for the customer. Call this only after: "
                "(1) identity is verified, (2) amount is confirmed, (3) all card fields "
                "have been validated individually. Requires all 5 card fields. "
                "Returns transaction_id on success or an error_code on failure. "
                "On card errors (invalid_card, invalid_cvv, invalid_expiry), ask the "
                "user to re-enter card details. On amount errors, re-ask for amount."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "account_id": {
                        "type": "string",
                        "description": "The verified account ID.",
                    },
                    "amount": {
                        "type": "number",
                        "description": "Payment amount in INR (positive, max 2 decimal places, must not exceed balance).",
                    },
                    "card_number": {
                        "type": "string",
                        "description": "Card number — digits only, no spaces or dashes.",
                    },
                    "cvv": {
                        "type": "string",
                        "description": "CVV — 3 digits for standard cards, 4 digits for Amex.",
                    },
                    "expiry_month": {
                        "type": "integer",
                        "description": "Card expiry month (1–12).",
                    },
                    "expiry_year": {
                        "type": "integer",
                        "description": "Card expiry year (4-digit, e.g. 2027).",
                    },
                    "cardholder_name": {
                        "type": "string",
                        "description": "Name on the card exactly as provided by the user.",
                    },
                },
                "required": [
                    "account_id", "amount",
                    "card_number", "cvv", "expiry_month", "expiry_year", "cardholder_name",
                ],
            },
        },
    },

    # ── Validation ────────────────────────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "validate_card_number",
            "description": (
                "Validate a card number using Luhn algorithm and length check (13–19 digits). "
                "Call this as soon as the user provides a card number. "
                "Returns valid=true/false and an error message if invalid. "
                "Only call process_payment after this returns valid=true."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "card_number": {
                        "type": "string",
                        "description": "Card number as provided (may include spaces/dashes — they will be stripped).",
                    }
                },
                "required": ["card_number"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "validate_cvv",
            "description": (
                "Validate a CVV code. Standard cards require 3 digits; Amex requires 4. "
                "Provide the card_number so Amex can be detected automatically. "
                "Call this as soon as the user provides a CVV. "
                "Returns valid=true/false."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "cvv": {
                        "type": "string",
                        "description": "CVV as provided by the user.",
                    },
                    "card_number": {
                        "type": "string",
                        "description": "The card number (used for Amex detection). Pass empty string if not yet known.",
                    },
                },
                "required": ["cvv", "card_number"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "validate_expiry",
            "description": (
                "Validate a card expiry date. Month must be 1–12, year must be current or future. "
                "Handles 2-digit years by adding 2000. "
                "Call this as soon as the user provides an expiry date. "
                "Returns valid=true/false."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "expiry_month": {
                        "type": "integer",
                        "description": "Expiry month (1–12).",
                    },
                    "expiry_year": {
                        "type": "integer",
                        "description": "Expiry year (2 or 4 digits).",
                    },
                },
                "required": ["expiry_month", "expiry_year"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "validate_amount",
            "description": (
                "Validate a payment amount against the account balance. "
                "Amount must be positive, max 2 decimal places, and not exceed balance. "
                "Call this as soon as the user states how much they want to pay. "
                "Returns valid=true/false and the cleaned numeric amount on success."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "amount_str": {
                        "type": "string",
                        "description": "Amount as stated by user (may include ₹, commas, etc.).",
                    },
                    "balance": {
                        "type": "number",
                        "description": "The account's outstanding balance in INR.",
                    },
                },
                "required": ["amount_str", "balance"],
            },
        },
    },

    # ── Session Control ───────────────────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "lock_session",
            "description": (
                "Lock the session permanently after too many failed identity verification "
                "attempts (maximum 3). Call this when verify_identity has returned "
                "verified=false for the 3rd time. After locking, no further actions are "
                "possible and the user must contact support."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {
                        "type": "string",
                        "description": "Reason for locking (e.g. 'exceeded_verification_attempts').",
                    }
                },
                "required": ["reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "complete_session",
            "description": (
                "Mark the session as complete. Call this after a successful payment, "
                "or when the account has zero balance and no payment is needed. "
                "After completing, no further payment actions are possible."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {
                        "type": "string",
                        "enum": ["payment_success", "zero_balance"],
                        "description": "Why the session is being completed.",
                    }
                },
                "required": ["reason"],
            },
        },
    },
]
