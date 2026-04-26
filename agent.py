"""
agent.py
────────
Production-ready payment collection agent.

Architecture
────────────
• Python FSM controls ALL state transitions — the LLM never decides what
  step comes next.
• LLM (Claude) is used only for two NLU tasks where regex is insufficient:
    1. Extracting a person's full name from free text
    2. Extracting card details (5 fields) from a natural-language message
• All business logic (verification, validation, API calls) lives in
  validators.py / verification.py / tools.py.
• account_data (containing DOB, Aadhaar, pincode) is NEVER passed to the
  LLM and NEVER included in any message shown to the user.

State machine
─────────────
AWAIT_ACCOUNT_ID
    ↓  (account found)
AWAIT_NAME
    ↓  (name stored)
AWAIT_SECONDARY
    ↓  (verified)           ↓ (max retries)
AWAIT_AMOUNT            LOCKED
    ↓  (amount stored)
AWAIT_CARD
    ↓  (payment success)    ↓ (terminal error)
COMPLETED               COMPLETED
"""

import json
import os
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional, Tuple

from google import genai
import ollama

from dotenv import load_dotenv

from tools import APIError, lookup_account, process_payment
from validators import (
    extract_account_id,
    extract_amount_str,
    validate_amount,
    validate_card_number,
    validate_cvv,
    validate_expiry,
)
from verification import detect_secondary, verify_identity

load_dotenv()

MAX_VERIFY_RETRIES = 3  # user gets 3 total attempts before session lock


# ─── State Enum ───────────────────────────────────────────────────────────────

class State(str, Enum):
    AWAIT_ACCOUNT_ID = "await_account_id"
    AWAIT_NAME = "await_name"
    AWAIT_SECONDARY = "await_secondary"
    AWAIT_AMOUNT = "await_amount"
    AWAIT_CARD = "await_card"
    COMPLETED = "completed"
    LOCKED = "locked"


# ─── Card Details Accumulator ─────────────────────────────────────────────────

@dataclass
class CardDetails:
    """
    Accumulates card fields across one or more user turns.
    Fields stay None until successfully extracted AND validated.
    """
    card_number: Optional[str] = None
    cvv: Optional[str] = None
    expiry_month: Optional[int] = None
    expiry_year: Optional[int] = None
    cardholder_name: Optional[str] = None

    def missing_fields(self) -> list:
        missing = []
        if not self.card_number:
            missing.append("card number")
        if not self.cvv:
            missing.append("CVV")
        if not self.expiry_month or not self.expiry_year:
            missing.append("expiry date (MM/YYYY)")
        if not self.cardholder_name:
            missing.append("cardholder name")
        return missing

    def is_complete(self) -> bool:
        return len(self.missing_fields()) == 0

    def to_payment_method(self) -> Dict[str, Any]:
        return {
            "type": "card",
            "card": {
                "cardholder_name": self.cardholder_name,
                "card_number": self.card_number,
                "cvv": self.cvv,
                "expiry_month": self.expiry_month,
                "expiry_year": self.expiry_year,
            },
        }


# ─── Agent ────────────────────────────────────────────────────────────────────

class Agent:
    """
    Conversational payment collection agent.

    Usage
    -----
    agent = Agent()
    result = agent.next("Hi")          # {"message": "..."}
    result = agent.next("ACC1001")     # {"message": "..."}
    """

    def __init__(self):
        self._client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

        # ── Conversation state ──
        self._state = State.AWAIT_ACCOUNT_ID

        # ── Collected data ──
        self._account_id: Optional[str] = None
        self._account_data: Optional[Dict] = None   # SENSITIVE — never passed to LLM
        self._provided_name: Optional[str] = None
        self._card = CardDetails()
        self._payment_amount: Optional[float] = None

        # ── Retry counters ──
        self._verify_attempts: int = 0
        self._card_retry_attempts: int = 0

    # ─── Public Interface ─────────────────────────────────────────────────────

    def next(self, user_input: str) -> Dict[str, str]:
        """
        Process one turn of the conversation.

        Args:
            user_input: The user's message as a plain string.

        Returns:
            {"message": str}  — the agent's response to display.
        """
        if not isinstance(user_input, str):
            user_input = str(user_input)

        text = user_input.strip()

        if not text:
            return {"message": "I didn't catch that. Could you please repeat?"}

        dispatch = {
            State.AWAIT_ACCOUNT_ID: self._handle_account_id,
            State.AWAIT_NAME: self._handle_name,
            State.AWAIT_SECONDARY: self._handle_secondary,
            State.AWAIT_AMOUNT: self._handle_amount,
            State.AWAIT_CARD: self._handle_card,
            State.COMPLETED: self._handle_completed,
            State.LOCKED: self._handle_locked,
        }

        handler = dispatch.get(self._state)
        if not handler:
            return {"message": "Something went wrong. Please try again."}

        message = handler(text)
        return {"message": message}

    # ─── State Handlers ───────────────────────────────────────────────────────

    def _handle_account_id(self, text: str) -> str:
        """
        Extract account ID from input and call lookup API.
        Also looks for a name in the same message to avoid re-asking later.
        """
        # Generic greeting with no account ID yet
        account_id = extract_account_id(text)
        if not account_id:
            return (
                "Hello! Welcome to the payment service.\n"
                "Please share your Account ID to get started "
                "(e.g. ACC1001)."
            )

        self._account_id = account_id

        # ── Call lookup API ──
        try:
            self._account_data = lookup_account(account_id)
        except APIError as e:
            self._account_id = None
            if e.status_code == 404:
                return (
                    f"I couldn't find an account with ID '{account_id}'. "
                    "Please double-check and try again."
                )
            return (
                "I'm having trouble reaching our system right now. "
                "Please try again in a moment."
            )

        # ── Check if user also gave their name in this turn ──
        name = self._extract_name_llm(text)
        if name:
            self._provided_name = name
            self._state = State.AWAIT_SECONDARY
            return (
                f"Account found. I've noted your name as '{name}'.\n\n"
                "To complete identity verification, please share one of:\n"
                "  • Date of birth (YYYY-MM-DD)\n"
                "  • Last 4 digits of your Aadhaar\n"
                "  • Your registered pincode"
            )

        self._state = State.AWAIT_NAME
        return (
            "Account found. To verify your identity, "
            "could you please tell me your full name as registered on the account?"
        )

    def _handle_name(self, text: str) -> str:
        """Extract full name and advance to secondary verification."""
        name = self._extract_name_llm(text)

        if not name:
            return (
                "I couldn't make out a full name from that. "
                "Please provide your full name exactly as it appears on the account."
            )

        self._provided_name = name
        self._state = State.AWAIT_SECONDARY
        return (
            f"Thank you, {name}.\n\n"
            "To complete identity verification, please share one of:\n"
            "  • Date of birth (YYYY-MM-DD)\n"
            "  • Last 4 digits of your Aadhaar\n"
            "  • Your registered pincode"
        )

    def _handle_secondary(self, text: str) -> str:
        """
        Detect secondary factor, run strict verification,
        handle retries up to MAX_VERIFY_RETRIES.
        """
        result = detect_secondary(text)

        if not result:
            return (
                "I couldn't identify a valid verification factor. Please provide:\n"
                "  • Date of birth (format: YYYY-MM-DD), or\n"
                "  • Last 4 digits of your Aadhaar, or\n"
                "  • Your registered pincode"
            )

        sec_type, sec_value = result

        assert self._account_data is not None, "Missing account_data in secondary verification"
        assert self._provided_name is not None, "Missing provided_name in secondary verification"

        verified = verify_identity(
            self._account_data,
            self._provided_name,
            sec_type,
            sec_value,
        )

        if verified:
            return self._on_verified()

        # ── Verification failed ──
        self._verify_attempts += 1
        remaining = MAX_VERIFY_RETRIES - self._verify_attempts

        if remaining <= 0:
            self._state = State.LOCKED
            return (
                "❌ Verification failed. You have exceeded the maximum number of attempts.\n\n"
                "For security reasons, this session has been locked. "
                "Please contact our customer support team for assistance."
            )

        attempt_word = "attempt" if remaining == 1 else "attempts"
        return (
            f"❌ The details you provided don't match our records.\n"
            f"You have {remaining} {attempt_word} remaining.\n\n"
            "Please try again with your date of birth (YYYY-MM-DD), "
            "Aadhaar last 4 digits, or registered pincode."
        )

    def _on_verified(self) -> str:
        """Called once verification passes."""
        assert self._account_data is not None, "Missing account_data in verified flow"
        balance = self._account_data["balance"]

        if balance == 0.0:
            self._state = State.COMPLETED
            return (
                "✅ Identity verified successfully!\n\n"
                "Your account currently has no outstanding balance — "
                "there is nothing to pay. Your account is all clear!\n\n"
                "Thank you for reaching out. Have a great day!"
            )

        self._state = State.AWAIT_AMOUNT
        return (
            f"✅ Identity verified successfully!\n\n"
            f"Your outstanding balance is ₹{balance:,.2f}.\n\n"
            "How much would you like to pay today? "
            "You may pay the full amount or a partial amount."
        )

    def _handle_amount(self, text: str) -> str:
        """Parse and validate payment amount, then ask for card details."""
        assert self._account_data is not None, "Missing account_data in amount flow"
        amount_str = extract_amount_str(text)

        if not amount_str:
            balance = self._account_data["balance"]
            return (
                f"I couldn't find a valid amount. "
                f"Please enter the amount you'd like to pay "
                f"(up to ₹{balance:,.2f})."
            )

        ok, result = validate_amount(amount_str, self._account_data["balance"])
        if not ok:
            return f"Invalid amount — {result}\nPlease enter a valid payment amount."

        self._payment_amount = float(result)
        self._state = State.AWAIT_CARD

        return (
            f"Got it — ₹{self._payment_amount:,.2f}.\n\n"
            "Please provide your card details:\n"
            "  • Card number\n"
            "  • CVV\n"
            "  • Expiry date (MM/YYYY)\n"
            "  • Cardholder name\n\n"
            "You can share all of them in one message or one at a time."
        )

    def _handle_card(self, text: str) -> str:
        """
        Extract card fields from the user's message.
        Accumulates fields across turns. Validates each field immediately.
        Processes payment only when all 5 fields are valid.
        """
        extracted = self._extract_card_details_llm(text)

        validation_errors = []

        # ── Card number ──
        if extracted.get("card_number"):
            raw = re.sub(r"[\s\-]", "", str(extracted["card_number"]))
            ok, result = validate_card_number(raw)
            if ok:
                self._card.card_number = result
            else:
                validation_errors.append(f"Card number: {result}")

        # ── CVV ──
        if extracted.get("cvv"):
            # Use already-stored card number for Amex detection if available
            ref_card = self._card.card_number or extracted.get("card_number", "")
            ok, result = validate_cvv(str(extracted["cvv"]), ref_card)
            if ok:
                self._card.cvv = result
            else:
                validation_errors.append(f"CVV: {result}")

        # ── Expiry ──
        if extracted.get("expiry_month") and extracted.get("expiry_year"):
            ok, result = validate_expiry(
                extracted["expiry_month"], extracted["expiry_year"]
            )
            if ok:
                m, y = result
                self._card.expiry_month, self._card.expiry_year = int(m), int(y)
            else:
                validation_errors.append(f"Expiry: {result}")

        # ── Cardholder name ──
        if extracted.get("cardholder_name"):
            self._card.cardholder_name = str(extracted["cardholder_name"]).strip()

        # ── Report validation errors ──
        if validation_errors:
            err_lines = "\n".join(f"  • {e}" for e in validation_errors)
            missing = self._card.missing_fields()
            response = f"There are issues with some card details:\n{err_lines}\n\n"
            if missing:
                response += f"Still needed: {', '.join(missing)}.\nPlease correct and provide the remaining details."
            else:
                response += "Please correct the above and try again."
            return response

        # ── Check completeness ──
        missing = self._card.missing_fields()
        if missing:
            provided = [
                f for f in ["card number", "CVV", "expiry date (MM/YYYY)", "cardholder name"]
                if f not in missing
            ]
            ack = f"Got it — received {', '.join(provided)}." if provided else ""
            return (
                (ack + "\n\n" if ack else "")
                + f"Still need: {', '.join(missing)}. Please provide the remaining details."
            )

        # ── All fields valid — process payment ──
        return self._process_payment()

    def _process_payment(self) -> str:
        """Call process-payment API and handle all response cases."""
        try:
            result = process_payment(
                self._account_id or "",
                self._payment_amount or 0.0,
                self._card.to_payment_method(),
            )
        except APIError as e:
            return self._format_payment_error(e.error_code)

        if result.get("success"):
            txn_id = result.get("transaction_id", "N/A")
            self._state = State.COMPLETED
            return (
                f"✅ Payment successful!\n\n"
                f"  Transaction ID : {txn_id}\n"
                f"  Amount paid    : ₹{self._payment_amount:,.2f}\n\n"
                "Please save your transaction ID for your records.\n"
                "Thank you for using our payment service. Have a great day!"
            )

        # Application-level failure (HTTP 422)
        return self._format_payment_error(result.get("error_code", "unknown"))

    def _format_payment_error(self, error_code: str) -> str:
        """
        Map API error codes to user-friendly messages.
        Retryable errors reset the relevant fields; terminal errors close the session.
        """
        assert self._account_data is not None, "Missing account_data in payment error flow"
        retryable_card_errors = {"invalid_card", "invalid_cvv", "invalid_expiry"}

        messages = {
            "insufficient_balance": (
                f"❌ The payment amount exceeds your outstanding balance of "
                f"₹{self._account_data['balance']:,.2f}.\n"
                "Please enter a lower amount.",
                "amount",   # which part to reset
            ),
            "invalid_amount": (
                "❌ The payment amount is invalid (must be positive with at most 2 decimal places).\n"
                "Please re-enter the amount.",
                "amount",
            ),
            "invalid_card": (
                "❌ The card number is invalid. Please check and re-enter your card details.",
                "card",
            ),
            "invalid_cvv": (
                "❌ The CVV is incorrect. Please check the security code on your card.",
                "card",
            ),
            "invalid_expiry": (
                "❌ The card expiry date is invalid or the card has expired.\n"
                "Please use a valid card.",
                "card",
            ),
            "timeout": (
                "❌ The request timed out. Please try again.",
                "retry",
            ),
            "network_error": (
                "❌ A network error occurred. Please check your connection and try again.",
                "retry",
            ),
        }

        msg, reset_target = messages.get(
            error_code,
            ("❌ An unexpected error occurred. Please try again.", "retry"),
        )

        if reset_target == "card":
            self._card = CardDetails()
            self._state = State.AWAIT_CARD
            return msg + "\n\nPlease provide your card details again."

        if reset_target == "amount":
            self._payment_amount = None
            self._state = State.AWAIT_AMOUNT
            return msg

        # "retry" — stay in current state
        return msg

    def _handle_completed(self, text: str) -> str:
        return (
            "This session has already concluded. "
            "Thank you for using our payment service!"
        )

    def _handle_locked(self, text: str) -> str:
        return (
            "This session is locked due to too many failed verification attempts. "
            "Please contact our customer support team for assistance."
        )

    # ─── LLM Helpers ─────────────────────────────────────────────────────────

    def _extract_name_llm(self, text: str) -> Optional[str]:
        """
        Use Claude to extract a full person name from free text.
        Returns None if no name is found or on any error.

        Why LLM here: names are extremely varied — regex cannot reliably
        extract "Rajarajeswari Balasubramaniam" from "my name is Rajarajeswari
        Balasubramaniam and my account is ACC1002".
        """
        if re.match(r"(?i)^ACC\d+$", text.strip()):
            return None

        print(f"[DEBUG] _extract_name_llm called with: {repr(text)}")  # ADD AS FIRST LINE
        print(f"[DEBUG] client type: {type(self._client)}")  
        system = (
            "You are a name-extraction assistant. "
            "Given a user message, extract the person's full name if one is present. "
            "Rules:\n"
            "  - Return ONLY a JSON object: {\"name\": \"<full name>\"} or {\"name\": null}\n"
            "  - Do NOT include titles (Mr, Mrs, Dr)\n"
            "  - Preserve exact casing and spacing as stated by the user\n"
            "  - If multiple names appear, return the one most likely to be the account holder\n"
            "  - Return ONLY valid JSON. No explanation, no markdown."
        )
        try:
            resp = ollama.chat(
                model="llama3.2:3b",
                messages=[{"role": "user", "content": system + "\n\nUser message: " + text}],
            )
            # Debugging: log the raw response to see what the LLM is returning
            print(f"[DEBUG card] raw response: {repr(resp['message']['content'])}")
            raw = (resp.get("message", {}).get("content", "") or "{}").strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            data = json.loads(raw)
            name = data.get("name")
            if not name or name == "null":
                return None
            # Find where the LLM-extracted name appears in the original text (case-insensitive)
            # and return it with the user's exact casing
            idx = text.lower().find(name.lower())
            if idx != -1:
                return text[idx: idx + len(name)]
            # Fallback: return as-is if not found in input
            return name
        except Exception as e:
            print(f"[DEBUG ERROR] {type(e).__name__}: {e}")
            return None

    def _extract_card_details_llm(self, text: str) -> Dict[str, Any]:
        """
        Use Claude to extract card payment fields from a natural-language message.
        Returns a dict with keys: card_number, cvv, expiry_month, expiry_year,
        cardholder_name (any can be null/missing).

        Why LLM here: users say things like "card is 4532 0151 1283 0366, expires
        Dec 2027, cvv 123, name John Smith" — multi-field, freeform.
        """
        system = (
            "You are a card-detail extraction assistant. "
            "Extract payment card fields from the user message.\n"
            "Return ONLY a JSON object with these keys (use null for any that are absent):\n"
            "  card_number   : string of digits only (strip spaces and dashes)\n"
            "  cvv           : string of 3–4 digits\n"
            "  expiry_month  : integer 1–12\n"
            "  expiry_year   : integer (full 4-digit year, e.g. 2027)\n"
            "  cardholder_name : full name string\n"
            "Return ONLY valid JSON. No explanation, no markdown."
        )
        try:
            resp = ollama.chat(
                model="llama3.2:3b",
                messages=[{"role": "user", "content": system + "\n\nUser message: " + text}],
            )
            # Debugging: log the raw response to see what the LLM is returning
            print(f"[DEBUG card] raw response: {repr(resp['message']['content'])}")
            raw = (resp.get("message", {}).get("content", "") or "{}").strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            data = json.loads(raw)
            # Normalize keys — LLM sometimes adds leading/trailing spaces
            return {
                k.strip(): (None if v == "null" else v)
                for k, v in data.items()
            }
        except Exception:
            return {}