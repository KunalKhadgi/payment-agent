"""
eval.py
───────
Evaluation harness for the payment collection agent.

Test accounts (from assignment doc)
────────────────────────────────────
  ACC1001  Nithin Jain                   DOB 1990-05-14  Aadhaar 4321  PIN 400001  ₹1,250.75
  ACC1002  Rajarajeswari Balasubramaniam  DOB 1985-11-23  Aadhaar 9876  PIN 400002  ₹540.00
  ACC1003  Priya Agarwal                 DOB 1992-08-10  Aadhaar 2468  PIN 400003  ₹0.00
  ACC1004  Rahul Mehta                   DOB 1988-02-29  Aadhaar 1357  PIN 400004  ₹3,200.50

NOTE: patch targets are tool_executor._lookup_account / tool_executor._process_payment
because that's where the names are imported and used.
"""

import sys
import time
import traceback
import unittest
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from unittest.mock import patch

from agent import Agent
from tools import APIError


# ══════════════════════════════════════════════════════════════════════════════
# ANSI colours
# ══════════════════════════════════════════════════════════════════════════════

class C:
    HEADER  = "\033[95m"
    BLUE    = "\033[94m"
    CYAN    = "\033[96m"
    GREEN   = "\033[92m"
    YELLOW  = "\033[93m"
    RED     = "\033[91m"
    BOLD    = "\033[1m"
    DIM     = "\033[2m"
    RESET   = "\033[0m"


# ══════════════════════════════════════════════════════════════════════════════
# Test accounts — exact values from assignment doc
# ══════════════════════════════════════════════════════════════════════════════

ACC1001 = {
    "account_id": "ACC1001",
    "full_name": "Nithin Jain",
    "dob": "1990-05-14",
    "aadhaar_last4": "4321",
    "pincode": "400001",
    "balance": 1250.75,
}

ACC1002 = {
    "account_id": "ACC1002",
    "full_name": "Rajarajeswari Balasubramaniam",
    "dob": "1985-11-23",
    "aadhaar_last4": "9876",
    "pincode": "400002",
    "balance": 540.00,
}

ACC1003 = {
    "account_id": "ACC1003",
    "full_name": "Priya Agarwal",
    "dob": "1992-08-10",
    "aadhaar_last4": "2468",
    "pincode": "400003",
    "balance": 0.00,
}

ACC1004 = {
    "account_id": "ACC1004",
    "full_name": "Rahul Mehta",
    "dob": "1988-02-29",   # intentional leap-year edge case
    "aadhaar_last4": "1357",
    "pincode": "400004",
    "balance": 3200.50,
}

PAY_SUCCESS        = {"success": True,  "transaction_id": "txn_1762510325322_l1fl4oy"}
PAY_INVALID_CARD   = {"success": False, "error_code": "invalid_card"}
PAY_INVALID_CVV    = {"success": False, "error_code": "invalid_cvv"}
PAY_INVALID_EXPIRY = {"success": False, "error_code": "invalid_expiry"}
PAY_INSUFFICIENT   = {"success": False, "error_code": "insufficient_balance"}


# ══════════════════════════════════════════════════════════════════════════════
# Conversation logger
# ══════════════════════════════════════════════════════════════════════════════

class ConversationLogger:
    """Pretty-prints each turn of the conversation."""

    def __init__(self, test_name: str):
        self.test_name = test_name
        self.turn_count = 0
        print(f"\n{C.BOLD}{C.CYAN}{'═' * 72}{C.RESET}")
        print(f"{C.BOLD}{C.CYAN}▶ {test_name}{C.RESET}")
        print(f"{C.CYAN}{'═' * 72}{C.RESET}\n")

    def log_user_input(self, text: str, description: str = "") -> None:
        self.turn_count += 1
        label = f"  Context: {description}" if description else ""
        print(f"{C.BOLD}{C.BLUE}[Turn {self.turn_count}] User:{C.RESET}")
        if label:
            print(f"{C.DIM}{label}{C.RESET}")
        print(f"{C.BLUE}  💬 \"{text}\"{C.RESET}\n")

    def log_agent_response(self, text: str) -> None:
        print(f"{C.BOLD}{C.GREEN}[Turn {self.turn_count}] Agent:{C.RESET}")
        print(f"{C.GREEN}  🤖 {text}{C.RESET}\n")
        print(f"{C.DIM}{'─' * 72}{C.RESET}\n")

    def log_error(self, message: str) -> None:
        print(f"{C.RED}  ❌ {message}{C.RESET}\n")

    def log_success(self, message: str) -> None:
        print(f"{C.GREEN}  ✓ {message}{C.RESET}\n")


# ══════════════════════════════════════════════════════════════════════════════
# Enhanced base test case
# ══════════════════════════════════════════════════════════════════════════════

SENSITIVE_LEAK_PATTERNS = [
    "your dob is", "your date of birth is",
    "your aadhaar", "aadhaar on file",
    "your pincode is", "registered pincode is",
]


class AgentTestCase(unittest.TestCase):
    """
    Base class: initialises agent + logger via start_conversation(),
    exposes send() for scripted turns, and helper assertions.
    """

    def setUp(self) -> None:
        self.agent: Optional[Agent] = None
        self.logger: Optional[ConversationLogger] = None
        self.responses: List[str] = []

    def start_conversation(self, test_name: str) -> None:
        """Create a fresh agent, attach logger, and send the opening greeting."""
        self.agent = Agent()
        self.logger = ConversationLogger(test_name)
        self._do_send("Hi there!", "User opens conversation")

    def send(self, user_input: str, description: str = "") -> str:
        """Public helper used in tests — calls _do_send."""
        return self._do_send(user_input, description)

    def _do_send(self, user_input: str, description: str = "") -> str:
        assert self.agent is not None, "Call start_conversation() before send()"
        assert self.logger is not None
        self.logger.log_user_input(user_input, description)
        result = self.agent.next(user_input)
        response: str = result["message"]
        self.logger.log_agent_response(response)
        self.responses.append(response)
        return response

    # ── Assertion helpers ─────────────────────────────────────────────────────

    def assert_contains(self, *keywords: str, msg: str = "") -> None:
        joined = " ".join(self.responses).lower()
        found = any(k.lower() in joined for k in keywords)
        if not found and self.logger:
            self.logger.log_error(f"Expected one of {keywords}. Last: {self.responses[-1][:160]}")
        self.assertTrue(found, msg or f"Expected one of {keywords} in responses")

    def assert_not_contains(self, *keywords: str, msg: str = "") -> None:
        joined = " ".join(self.responses).lower()
        bad = [k for k in keywords if k.lower() in joined]
        if bad and self.logger:
            self.logger.log_error(f"Forbidden keyword(s) found: {bad}")
        self.assertFalse(bad, msg or f"Should not contain {keywords}")

    def assert_no_sensitive_leak(self) -> None:
        joined = " ".join(self.responses).lower()
        leaked = [p for p in SENSITIVE_LEAK_PATTERNS if p in joined]
        if leaked and self.logger:
            self.logger.log_error(f"Sensitive data leaked: {leaked}")
        self.assertFalse(leaked, f"Sensitive data exposed: {leaked}")


# ══════════════════════════════════════════════════════════════════════════════
# GROUP A — Successful Flow
# ══════════════════════════════════════════════════════════════════════════════

class TestA_SuccessfulFlow(AgentTestCase):
    """Group A: End-to-end successful payment flows."""

    @patch("tool_executor._process_payment", return_value=PAY_SUCCESS)
    @patch("tool_executor._lookup_account", return_value=ACC1001)
    def test_A1_happy_path_natural_inputs(self, _lu, _pay):
        """A1: Natural conversational inputs throughout the full flow."""
        self.start_conversation("A1: Happy Path — Natural Language")

        self.send("yeah my account number is ACC1001 I think",
                  "Doc example: account ID in natural sentence")
        self.send("my name is Nithin Jain", "Name in conversational form")
        self.send("I was born on 14th May 1990", "Doc example: DOB in spoken format")
        self.send("I want to pay a thousand rupees", "Doc example: amount in words")
        self.send("the card number is 4532 0151 1283 0366", "Doc example: card with spaces")
        self.send("CVV is one two three", "Doc example: CVV spoken as words")
        self.send("expires December 2027", "Doc example: natural expiry format")
        self.send("name on card is Nithin Jain")

        self.assert_contains("txn_", "successful", "success", "transaction")
        self.assert_no_sensitive_leak()

    @patch("tool_executor._process_payment", return_value=PAY_SUCCESS)
    @patch("tool_executor._lookup_account", return_value=ACC1001)
    def test_A2_partial_payment_allowed(self, _lu, _pay):
        """A2: Partial payment (amount < balance) is explicitly allowed by the doc."""
        self.start_conversation("A2: Partial Payment")

        self.send("ACC1001")
        self.send("Nithin Jain")
        self.send("1990-05-14")
        self.send("can I do 500 for now?", "Doc example: partial payment phrasing")
        self.send("4532015112830366, CVV 123, exp 12/27, name Nithin Jain")

        self.assert_contains("txn_", "success")

    @patch("tool_executor._process_payment", return_value=PAY_SUCCESS)
    @patch("tool_executor._lookup_account", return_value=ACC1002)
    def test_A3_long_indian_name(self, _lu, _pay):
        """A3: Doc example — 'you can call me Raja but my full name is Rajarajeswari Balasubramaniam'."""
        self.start_conversation("A3: Long Indian Name (ACC1002)")

        self.send("account id: acc1002", "Lowercase account ID")
        self.send("you can call me Raja but my full name is Rajarajeswari Balasubramaniam",
                  "Doc example verbatim")
        self.send("my Aadhaar ends with 9876",
                  "Doc example: 'Aadhaar ends with 9876, shall I give pincode instead?'")
        self.send("just clear the full amount", "Doc example: full balance request")
        self.send("card: 4532015112830366, cvv: 123, expiry: 12/2027, "
                  "name: Rajarajeswari Balasubramaniam")

        self.assert_contains("txn_", "success")

    @patch("tool_executor._process_payment", return_value=PAY_SUCCESS)
    @patch("tool_executor._lookup_account", return_value=ACC1001)
    def test_A4_card_details_incremental_turns(self, _lu, _pay):
        """A4: Card fields provided one per turn — agent must accumulate without re-asking."""
        self.start_conversation("A4: Incremental Card Details")

        self.send("ACC1001")
        self.send("Nithin Jain")
        self.send("pincode? it's 4 0 0 0 0 1", "Doc example: spaced pincode")
        self.send("pay 1000")
        self.send("card number is 4532 0151 1283 0366")
        self.send("CVV is 123")
        self.send("it expires in 12/27", "2-digit year")
        self.send("cardholder name: Nithin Jain")

        self.assert_contains("txn_", "success")

    @patch("tool_executor._process_payment", return_value=PAY_SUCCESS)
    @patch("tool_executor._lookup_account", return_value=ACC1001)
    def test_A5_name_given_before_asked(self, _lu, _pay):
        """A5: Name volunteered with account ID — agent must NOT re-ask for it."""
        self.start_conversation("A5: Name Provided Before Asked")

        self.send("Hi, my account is ACC1001 and my name is Nithin Jain",
                  "Both account ID and name in one message")
        r_secondary = self.send("DOB is May 14th 1990")
        r_amount    = self.send("pay the full balance")
        r_card      = self.send("4532015112830366, 123, 12/2027, Nithin Jain")

        name_reasked = sum(
            1 for r in [r_secondary, r_amount, r_card]
            if "full name" in r.lower() or "what is your name" in r.lower()
        )
        self.assertEqual(name_reasked, 0, "Agent re-asked for name that was already given!")
        self.assert_contains("txn_", "success")

    @patch("tool_executor._lookup_account", return_value=ACC1003)
    def test_A6_zero_balance_skips_payment(self, _lu):
        """A6: ACC1003 Priya Agarwal (₹0) — agent must close without asking for card."""
        self.start_conversation("A6: Zero Balance Account (ACC1003)")

        self.send("ACC1003")
        self.send("Priya Agarwal")
        self.send("last 4 of my Aadhaar is 2468")

        self.assert_contains("no outstanding", "zero", "₹0", "0.00", "nothing to pay",
                              "all clear", "no balance",
                              msg="Expected zero-balance message")
        self.assert_not_contains("card number", "cvv", "expiry",
                                 msg="Should NOT ask for card on zero-balance account")

    @patch("tool_executor._process_payment", return_value=PAY_SUCCESS)
    @patch("tool_executor._lookup_account", return_value=ACC1001)
    def test_A7_rupee_symbol_amount(self, _lu, _pay):
        """A7: Amount entered as '₹1,000.00' — symbol and comma must be stripped."""
        self.start_conversation("A7: ₹ Symbol in Amount")

        self.send("ACC1001")
        self.send("Nithin Jain")
        self.send("1990-05-14")
        self.send("₹1,000.00", "Amount with rupee symbol and comma")
        self.send("4532015112830366, 123, 12/2027, Nithin Jain")

        self.assert_contains("txn_", "success")


# ══════════════════════════════════════════════════════════════════════════════
# GROUP B — Verification Failure
# ══════════════════════════════════════════════════════════════════════════════

class TestB_VerificationFailure(AgentTestCase):
    """Group B: Identity verification must be strict and fail gracefully."""

    @patch("tool_executor._lookup_account", return_value=ACC1001)
    def test_B1_wrong_name_rejected(self, _lu):
        """B1: Wrong name — must not proceed to balance or payment."""
        self.start_conversation("B1: Wrong Name Rejected")

        self.send("ACC1001")
        self.send("my name is John Doe", "Completely wrong name")
        self.send("1990-05-14", "Correct DOB, but name still wrong")

        self.assert_not_contains("verified", "balance is", "outstanding balance",
                                  msg="Should not verify with wrong name")

    @patch("tool_executor._lookup_account", return_value=ACC1001)
    def test_B2_correct_name_wrong_secondary(self, _lu):
        """B2: Correct name + wrong secondary factor — verification must fail."""
        self.start_conversation("B2: Correct Name, Wrong Secondary Factor")

        self.send("ACC1001")
        self.send("Nithin Jain", "Correct name")
        self.send("I was born on 1st January 1999", "Wrong DOB")

        self.assert_not_contains("verified", "outstanding balance",
                                  msg="Should not verify with wrong DOB")

    @patch("tool_executor._lookup_account", return_value=ACC1001)
    def test_B3_lock_after_three_failures(self, _lu):
        """B3: Session must lock after exactly 3 failed verification attempts."""
        self.start_conversation("B3: Session Lock After 3 Failures")

        self.send("ACC1001")
        self.send("Nithin Jain")
        self.send("2000-01-01", "Wrong attempt #1")
        self.send("1999-06-15", "Wrong attempt #2")
        self.send("1998-03-20", "Wrong attempt #3")
        r_post = self.send("1990-05-14", "Real DOB after lock — must be rejected")

        locked = (
            self.agent._session.is_locked  # type: ignore[union-attr]
            or any(k in r_post.lower() for k in ("locked", "exceeded", "support", "contact", "maximum"))
        )
        self.assertTrue(locked, f"Session should be locked. Last response: {r_post}")

    @patch("tool_executor._lookup_account", return_value=ACC1001)
    def test_B4_locked_session_rejects_all_input(self, _lu):
        """B4: After lock, every subsequent turn must return locked/support message."""
        self.start_conversation("B4: Locked Session Stays Locked")

        self.send("ACC1001")
        self.send("Nithin Jain")
        self.send("2000-01-01")
        self.send("1999-06-15")
        self.send("1998-03-20")   # 3rd failure → lock

        r = self.send("okay my real DOB is 1990-05-14", "Correct DOB after lock")

        self.assertTrue(
            "locked" in r.lower() or "support" in r.lower()
            or self.agent._session.is_locked,  # type: ignore[union-attr]
            f"Expected locked message. Got: {r}"
        )

    @patch("tool_executor._lookup_account", return_value=ACC1001)
    def test_B5_case_sensitive_name_matching(self, _lu):
        """B5: Doc requirement — matching is strict, no case-insensitive workarounds."""
        self.start_conversation("B5: Case-Sensitive Name (nithin jain != Nithin Jain)")

        self.send("ACC1001")
        self.send("nithin jain", "All lowercase — must fail strict match")
        self.send("1990-05-14")

        self.assert_not_contains("verified", "outstanding balance",
                                  msg="Case-insensitive name match must NOT be accepted")

    @patch("tool_executor._lookup_account", return_value=ACC1001)
    def test_B6_failure_shows_retry_guidance(self, _lu):
        """B6: On first failure, agent must give clear guidance and allow retry."""
        self.start_conversation("B6: Retry Guidance on First Failure")

        self.send("ACC1001")
        self.send("Nithin Jain")
        r = self.send("1999-01-01", "First wrong attempt")

        has_guidance = any(k in r.lower() for k in (
            "attempt", "try", "remaining", "again", "incorrect",
            "match", "doesn't match", "not match", "wrong"
        ))
        self.assertTrue(has_guidance, f"Expected retry guidance. Got: {r}")

    @patch("tool_executor._lookup_account", return_value=ACC1001)
    def test_B7_no_sensitive_data_on_failure(self, _lu):
        """B7: Verification failure must NEVER reveal DOB, Aadhaar, or pincode."""
        self.start_conversation("B7: No Sensitive Data on Failure")

        self.send("ACC1001")
        self.send("Nithin Jain")
        self.send("1999-01-01", "Wrong DOB")

        self.assert_no_sensitive_leak()

    @patch("tool_executor._process_payment", return_value=PAY_SUCCESS)
    @patch("tool_executor._lookup_account", return_value=ACC1002)
    def test_B8_pincode_as_secondary_factor(self, _lu, _pay):
        """B8: Pincode accepted as secondary factor (any one of DOB/Aadhaar/PIN is enough)."""
        self.start_conversation("B8: Pincode as Secondary Factor (ACC1002)")

        self.send("ACC1002")
        self.send("Rajarajeswari Balasubramaniam")
        self.send("my pincode is 400002", "Pincode instead of DOB/Aadhaar")
        self.send("540")
        self.send("4532015112830366, 123, 12/2027, Rajarajeswari Balasubramaniam")

        self.assert_contains("txn_", "success",
                              msg="Pincode secondary factor should lead to successful payment")


# ══════════════════════════════════════════════════════════════════════════════
# GROUP C — Payment Failure
# ══════════════════════════════════════════════════════════════════════════════

class TestC_PaymentFailure(AgentTestCase):
    """Group C: Payment API errors and client-side validation."""

    @patch("tool_executor._process_payment", return_value=PAY_INVALID_CARD)
    @patch("tool_executor._lookup_account", return_value=ACC1001)
    def test_C1_api_invalid_card_error(self, _lu, _pay):
        """C1: API returns invalid_card — agent must ask user to re-enter card details."""
        self.start_conversation("C1: API invalid_card Error")

        self.send("ACC1001")
        self.send("Nithin Jain")
        self.send("1990-05-14")
        self.send("500")
        self.send("4532015112830366, 123, 12/2027, Nithin Jain")

        self.assert_contains("invalid", "card", "re-enter", "again", "incorrect",
                              msg="Should notify about invalid card")
        self.assert_not_contains("txn_", "transaction id",
                                  msg="Must NOT show transaction ID on failure")

    @patch("tool_executor._process_payment", return_value=PAY_INVALID_CVV)
    @patch("tool_executor._lookup_account", return_value=ACC1001)
    def test_C2_api_invalid_cvv_error(self, _lu, _pay):
        """C2: API returns invalid_cvv — agent clearly communicates CVV issue."""
        self.start_conversation("C2: API invalid_cvv Error")

        self.send("ACC1001")
        self.send("Nithin Jain")
        self.send("400001")
        self.send("500")
        self.send("4532015112830366, 123, 12/2027, Nithin Jain")

        self.assert_contains("cvv", "invalid", "security", "code", "card",
                              msg="Should report CVV issue clearly")

    @patch("tool_executor._process_payment", return_value=PAY_INVALID_EXPIRY)
    @patch("tool_executor._lookup_account", return_value=ACC1001)
    def test_C3_api_invalid_expiry_error(self, _lu, _pay):
        """C3: API returns invalid_expiry — agent communicates expiry issue."""
        self.start_conversation("C3: API invalid_expiry Error")

        self.send("ACC1001")
        self.send("Nithin Jain")
        self.send("4321")
        self.send("500")
        self.send("4532015112830366, 123, 12/2027, Nithin Jain")

        self.assert_contains("expir", "invalid", "card", "date",
                              msg="Should report expiry issue")

    @patch("tool_executor._lookup_account",
           side_effect=APIError("Not found", 404, "account_not_found"))
    def test_C4_account_not_found(self, _lu):
        """C4: 404 from lookup API — agent tells user account was not found."""
        self.start_conversation("C4: Account Not Found (404)")

        self.send("ACC9999")

        self.assert_contains("not found", "doesn't exist", "no account",
                              "couldn't find", "does not exist",
                              msg="Expected not-found message")

    @patch("tool_executor._lookup_account",
           side_effect=APIError("Timeout", 0, "timeout"))
    def test_C5_network_timeout_on_lookup(self, _lu):
        """C5: Network timeout — agent asks user to try again."""
        self.start_conversation("C5: Network Timeout on Lookup")

        self.send("ACC1001")

        self.assert_contains("try again", "network", "trouble", "connection",
                              "moment", "timeout",
                              msg="Expected retry-prompt message")

    @patch("tool_executor._lookup_account", return_value=ACC1001)
    def test_C6_luhn_fail_blocks_payment_api(self, _lu):
        """C6: Luhn-invalid card caught by validate_card_number — process_payment never called."""
        with patch("tool_executor._process_payment") as mock_pay:
            self.start_conversation("C6: Luhn Failure Blocks API")

            self.send("ACC1001")
            self.send("Nithin Jain")
            self.send("1990-05-14")
            self.send("500")
            self.send("1234567890123456, 123, 12/2027, Nithin Jain",
                      "Card number fails Luhn checksum")

            mock_pay.assert_not_called()

        self.assert_contains("invalid", "card number", "incorrect",
                              msg="Expected Luhn rejection message")

    @patch("tool_executor._lookup_account", return_value=ACC1001)
    def test_C7_expired_card_blocks_payment_api(self, _lu):
        """C7: Expired card caught by validate_expiry — process_payment never called."""
        with patch("tool_executor._process_payment") as mock_pay:
            self.start_conversation("C7: Expired Card Blocks API")

            self.send("ACC1001")
            self.send("Nithin Jain")
            self.send("400001")
            self.send("500")
            self.send("4532015112830366, 123, expires 01/2020, Nithin Jain",
                      "Card expired in Jan 2020")

            mock_pay.assert_not_called()

        self.assert_contains("expired", "expiry", "invalid",
                              msg="Expected expired card message")

    @patch("tool_executor._lookup_account", return_value=ACC1001)
    def test_C8_amount_exceeds_balance_blocked(self, _lu):
        """C8: Amount > balance caught by validate_amount — process_payment never called."""
        with patch("tool_executor._process_payment") as mock_pay:
            self.start_conversation("C8: Amount Exceeds Balance")

            self.send("ACC1001")
            self.send("Nithin Jain")
            self.send("1990-05-14")
            self.send("I need to pay 99999 rupees", "Way over ₹1,250.75 balance")

            mock_pay.assert_not_called()

        self.assert_contains("exceed", "balance", "too much", "amount", "lower", "1250",
                              msg="Expected over-balance rejection")

    @patch("tool_executor._lookup_account", return_value=ACC1001)
    def test_C9_payment_failure_then_retry_success(self, _lu):
        """C9: Card error on first attempt → user re-enters → second attempt succeeds."""
        with patch("tool_executor._process_payment",
                   side_effect=[PAY_INVALID_CARD, PAY_SUCCESS]):
            self.start_conversation("C9: Retry After Payment Failure")

            self.send("ACC1001")
            self.send("Nithin Jain")
            self.send("1990-05-14")
            self.send("500")
            self.send("4532015112830366, 123, 12/2027, Nithin Jain",
                      "First attempt — will return invalid_card")
            r = self.send("let me retry: 4532015112830366, 123, 12/2027, Nithin Jain",
                          "Second attempt — will succeed")

        self.assertTrue(
            any(k in r.lower() for k in ("txn_", "success", "transaction")),
            f"Expected success on retry. Got: {r}"
        )

    @patch("tool_executor._lookup_account", return_value=ACC1001)
    def test_C10_no_payment_before_verification(self, _lu):
        """C10: process_payment must NOT be called before identity is verified."""
        with patch("tool_executor._process_payment") as mock_pay:
            self.start_conversation("C10: No Payment Before Verification")

            self.send("ACC1001")
            # Skip verification — jump straight to card details
            self.send("4532015112830366, 123, 12/2027, Nithin Jain",
                      "Card details without verifying identity first")

            mock_pay.assert_not_called()


# ══════════════════════════════════════════════════════════════════════════════
# GROUP D — Edge Cases
# ══════════════════════════════════════════════════════════════════════════════

class TestD_EdgeCases(AgentTestCase):
    """Group D: Edge cases explicitly mentioned in the assignment doc."""

    @patch("tool_executor._process_payment", return_value=PAY_SUCCESS)
    @patch("tool_executor._lookup_account", return_value=ACC1004)
    def test_D1_leap_year_dob_accepted(self, _lu, _pay):
        """D1: ACC1004 Rahul Mehta — DOB 1988-02-29 is a valid leap year date."""
        self.start_conversation("D1: Leap Year DOB 1988-02-29 (ACC1004)")

        self.send("ACC1004")
        self.send("Rahul Mehta")
        self.send("I was born on February 29, 1988", "Valid leap year date")
        self.send("pay 1000")
        self.send("4532015112830366, 123, 12/2027, Rahul Mehta")

        self.assert_contains("txn_", "success")

    @patch("tool_executor._lookup_account", return_value=ACC1004)
    def test_D2_near_leap_year_dob_rejected(self, _lu):
        """D2: 1988-02-28 is NOT Rahul Mehta's DOB — off-by-one must fail."""
        self.start_conversation("D2: Off-By-One Leap Year DOB Rejected")

        self.send("ACC1004")
        self.send("Rahul Mehta")
        self.send("1988-02-28", "Off by one day — must not match")

        self.assert_not_contains("verified", "balance is", "outstanding balance",
                                  msg="Off-by-one leap year DOB should NOT verify")

    @patch("tool_executor._process_payment", return_value=PAY_SUCCESS)
    @patch("tool_executor._lookup_account", return_value=ACC1001)
    def test_D3_natural_language_dob_formats(self, _lu, _pay):
        """D3: DOB as '14th May 1990' or 'DOB is May 14, 90' — doc examples."""
        self.start_conversation("D3: Natural Language DOB")

        self.send("ACC1001")
        self.send("Nithin Jain")
        self.send("DOB is May 14, 90", "Doc example: short year format")
        self.send("500")
        self.send("4532015112830366, 123, 12/2027, Nithin Jain")

        self.assert_contains("txn_", "success",
                              msg="Natural language DOB format should be accepted")

    @patch("tool_executor._process_payment", return_value=PAY_SUCCESS)
    @patch("tool_executor._lookup_account", return_value=ACC1001)
    def test_D4_full_balance_natural_language(self, _lu, _pay):
        """D4: 'just clear the full amount' — agent must infer full balance."""
        self.start_conversation("D4: Full Balance in Natural Language")

        self.send("ACC1001")
        self.send("Nithin Jain")
        self.send("1990-05-14")
        self.send("just clear the full amount", "Doc example verbatim")
        self.send("4532015112830366, 123, 12/2027, Nithin Jain")

        self.assert_contains("txn_", "success", "1250",
                              msg="Full balance payment should succeed")

    @patch("tool_executor._process_payment", return_value=PAY_SUCCESS)
    @patch("tool_executor._lookup_account", return_value=ACC1001)
    def test_D5_spaced_card_number(self, _lu, _pay):
        """D5: '4532 0151 1283 0366' (with spaces) — doc example."""
        self.start_conversation("D5: Spaced Card Number")

        self.send("ACC1001")
        self.send("Nithin Jain")
        self.send("400001")
        self.send("500")
        self.send("the card number is 4532 0151 1283 0366, CVV is 123, "
                  "expires 12/2027, Nithin Jain",
                  "Doc example: card with spaces")

        self.assert_contains("txn_", "success")

    @patch("tool_executor._process_payment", return_value=PAY_SUCCESS)
    @patch("tool_executor._lookup_account", return_value=ACC1001)
    def test_D6_two_digit_expiry_year(self, _lu, _pay):
        """D6: '12/27' must normalise to 2027 — doc example."""
        self.start_conversation("D6: Two-Digit Expiry Year")

        self.send("ACC1001")
        self.send("Nithin Jain")
        self.send("4321")
        self.send("500")
        self.send("4532015112830366, 123, expires 12/27, Nithin Jain",
                  "Doc example: 2-digit year")

        self.assert_contains("txn_", "success")

    @patch("tool_executor._process_payment", return_value=PAY_SUCCESS)
    @patch("tool_executor._lookup_account", return_value=ACC1001)
    def test_D7_spaced_pincode(self, _lu, _pay):
        """D7: 'it's 4 0 0 0 0 1' — doc example of pincode with spaces."""
        self.start_conversation("D7: Spaced Pincode")

        self.send("ACC1001")
        self.send("Nithin Jain")
        self.send("pincode? it's 4 0 0 0 0 1", "Doc example verbatim")
        self.send("500")
        self.send("4532015112830366, 123, 12/2027, Nithin Jain")

        self.assert_contains("txn_", "success")

    @patch("tool_executor._lookup_account", return_value=ACC1001)
    def test_D8_no_reask_for_already_given_info(self, _lu):
        """D8: Context retention — agent must NOT re-ask for info it already has."""
        self.start_conversation("D8: No Re-ask for Already Given Info")

        self.send("Hi, I'm Nithin Jain and my account is ACC1001",
                  "Name + account ID in one message")
        r = self.send("4321", "Secondary factor — agent should not re-ask name")

        name_reasked = (
            "full name" in r.lower() or
            "what is your name" in r.lower() or
            "your name" in r.lower()
        )
        self.assertFalse(name_reasked, f"Agent re-asked for name. Got: {r}")

    @patch("tool_executor._lookup_account", return_value=ACC1001)
    def test_D9_empty_input_handled_gracefully(self, _lu):
        """D9: Whitespace-only input must not crash the agent."""
        self.start_conversation("D9: Empty Input Gracefully Handled")

        self.send("ACC1001")
        r = self.send("   ", "Whitespace-only input")

        self.assertIsInstance(r, str)
        self.assertGreater(len(r.strip()), 0, "Response must not be empty")

    @patch("tool_executor._process_payment", return_value=PAY_SUCCESS)
    @patch("tool_executor._lookup_account", return_value=ACC1001)
    def test_D10_cvv_spoken_as_words(self, _lu, _pay):
        """D10: 'CVV is one two three' — doc example of spoken CVV digits."""
        self.start_conversation("D10: CVV Spoken as Words")

        self.send("ACC1001")
        self.send("Nithin Jain")
        self.send("1990-05-14")
        self.send("500")
        self.send("CVV is one two three, card 4532015112830366, "
                  "expires 12/2027, Nithin Jain",
                  "Doc example: CVV as spoken words")

        self.assert_contains("txn_", "success")


# ══════════════════════════════════════════════════════════════════════════════
# Custom result class — timing only, no method overrides
# ══════════════════════════════════════════════════════════════════════════════

class TimedResult(unittest.TestResult):
    """TestResult that records per-test wall-clock time."""

    def __init__(self) -> None:
        super().__init__()
        self._starts: Dict[str, float] = {}
        self.times:   Dict[str, float] = {}

    def startTest(self, test: unittest.TestCase) -> None:
        super().startTest(test)
        self._starts[test.id()] = time.time()

    def stopTest(self, test: unittest.TestCase) -> None:
        super().stopTest(test)
        self.times[test.id()] = time.time() - self._starts.get(test.id(), time.time())


# ══════════════════════════════════════════════════════════════════════════════
# Runner + summary
# ══════════════════════════════════════════════════════════════════════════════

GROUPS: List[Tuple[str, type]] = [
    ("A — Successful Flow",      TestA_SuccessfulFlow),
    ("B — Verification Failure", TestB_VerificationFailure),
    ("C — Payment Failure",      TestC_PaymentFailure),
    ("D — Edge Cases",           TestD_EdgeCases),
]


def run_eval(verbose: bool = False) -> Tuple[int, int]:
    total_run = total_pass = total_fail = total_error = 0
    summaries: List[Tuple[str, int, int, float]] = []

    print(f"\n{C.BOLD}{C.HEADER}{'═' * 72}")
    print(f"  PAYMENT COLLECTION AGENT — EVALUATION SUITE")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'═' * 72}{C.RESET}\n")

    for group_name, group_class in GROUPS:
        loader = unittest.TestLoader()
        suite  = loader.loadTestsFromTestCase(group_class)
        result = TimedResult()

        t0 = time.time()
        suite.run(result)
        elapsed = time.time() - t0

        run    = result.testsRun
        fails  = len(result.failures)
        errs   = len(result.errors)
        passed = run - fails - errs

        total_run   += run
        total_pass  += passed
        total_fail  += fails
        total_error += errs

        icon  = f"{C.GREEN}✓{C.RESET}" if (fails + errs) == 0 else f"{C.RED}✗{C.RESET}"
        color = C.GREEN if (fails + errs) == 0 else C.YELLOW if passed > 0 else C.RED

        print(f"\n  {icon} {C.BOLD}{group_name}{C.RESET}")
        print(f"    {color}Passed: {passed}/{run}{C.RESET}   "
              f"Failures: {fails}   Errors: {errs}   Time: {elapsed:.1f}s")

        if verbose or (fails + errs) > 0:
            for test_case, tb in result.failures:
                name   = test_case.id().split(".")[-1]
                reason = tb.split("AssertionError:")[-1].strip().split("\n")[0]
                print(f"    {C.YELLOW}✗ FAIL  {name}{C.RESET}")
                print(f"           {reason[:110]}")
            for test_case, tb in result.errors:
                name   = test_case.id().split(".")[-1]
                reason = tb.strip().split("\n")[-1]
                print(f"    {C.RED}✗ ERROR {name}{C.RESET}")
                print(f"           {reason[:110]}")

        summaries.append((group_name, passed, run, elapsed))

    # ── Overall metrics ───────────────────────────────────────────────────────
    pass_rate     = (total_pass / total_run * 100) if total_run else 0
    total_elapsed = sum(s[3] for s in summaries)

    print(f"\n{C.BOLD}{C.CYAN}{'═' * 72}{C.RESET}")
    print(f"{C.BOLD}  METRICS SUMMARY{C.RESET}")
    print(f"{C.CYAN}{'═' * 72}{C.RESET}\n")

    rate_color = C.GREEN if pass_rate == 100 else C.YELLOW if pass_rate >= 60 else C.RED
    print(f"  Overall pass rate     : {rate_color}{C.BOLD}{total_pass}/{total_run} ({pass_rate:.1f}%){C.RESET}")
    print(f"  Total failures        : {total_fail}")
    print(f"  Total errors          : {total_error}")
    print(f"  Total wall time       : {total_elapsed:.1f}s\n")

    print(f"  {C.BOLD}Results by group:{C.RESET}")
    for name, passed, run, elapsed in summaries:
        pct   = int(passed / run * 100) if run else 0
        bar   = f"{C.GREEN}" + "█" * passed + f"{C.DIM}" + "░" * (run - passed) + f"{C.RESET}"
        color = C.GREEN if pct == 100 else C.YELLOW if pct >= 50 else C.RED
        print(f"    {name:<32} [{bar}]  {color}{passed}/{run} ({pct}%){C.RESET}  {elapsed:.1f}s")

    print(f"\n  {C.BOLD}Metric definitions:{C.RESET}")
    print(f"    {C.DIM}Tool call correctness{C.RESET}  — process_payment not called before verify / card validated")
    print(f"    {C.DIM}Sensitive data safety{C.RESET}  — no DOB/Aadhaar/pincode phrasing in agent responses")
    print(f"    {C.DIM}Context retention    {C.RESET}  — agent does not re-ask for already-given information")
    print(f"    {C.DIM}Failure handling     {C.RESET}  — every error produces a clear, actionable user message")
    print(f"\n{C.CYAN}{'═' * 72}{C.RESET}\n")

    return total_pass, total_run


if __name__ == "__main__":
    verbose = "--verbose" in sys.argv or "-v" in sys.argv
    passed, total = run_eval(verbose=verbose)
    sys.exit(0 if passed == total else 1)
