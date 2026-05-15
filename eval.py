"""
eval.py
───────
Enhanced evaluation harness with natural language inputs and clear logging.

Test accounts (from assignment)
──────────────────────────────────────────
  ACC1001  Nithin Jain                   DOB 1990-05-14  Aadhaar 4321  PIN 400001  ₹1,250.75
  ACC1002  Rajarajeswari Balasubramaniam  DOB 1985-11-23  Aadhaar 9876  PIN 400002  ₹540.00
  ACC1003  Priya Agarwal                 DOB 1992-08-10  Aadhaar 2468  PIN 400003  ₹0.00
  ACC1004  Rahul Mehta                   DOB 1988-02-29  Aadhaar 1357  PIN 400004  ₹3,200.50
"""

import sys
import time
import unittest
from typing import Dict, List, Tuple
from unittest.mock import patch
from datetime import datetime

from agent import Agent
from tools import APIError


# ══════════════════════════════════════════════════════════════════════════════
# ANSI Color Codes for Beautiful Logs
# ══════════════════════════════════════════════════════════════════════════════

class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'
    RESET = '\033[0m'
    DIM = '\033[2m'


# ══════════════════════════════════════════════════════════════════════════════
# Test Data
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
    "dob": "1988-02-29",
    "aadhaar_last4": "1357",
    "pincode": "400004",
    "balance": 3200.50,
}

PAY_SUCCESS = {"success": True, "transaction_id": "txn_1762510325322_l1fl4oy"}
PAY_INVALID_CARD = {"success": False, "error_code": "invalid_card"}
PAY_INVALID_CVV = {"success": False, "error_code": "invalid_cvv"}
PAY_INVALID_EXPIRY = {"success": False, "error_code": "invalid_expiry"}
PAY_INSUFFICIENT = {"success": False, "error_code": "insufficient_balance"}


# ══════════════════════════════════════════════════════════════════════════════
# Enhanced Test Runner with Beautiful Logs
# ══════════════════════════════════════════════════════════════════════════════

class ConversationLogger:
    """Logs conversations with clear formatting and colors."""
    
    def __init__(self, test_name: str):
        self.test_name = test_name
        self.turn_count = 0
        print(f"\n{Colors.BOLD}{Colors.CYAN}{'═' * 80}{Colors.RESET}")
        print(f"{Colors.BOLD}{Colors.CYAN}▶ TEST: {test_name}{Colors.RESET}")
        print(f"{Colors.CYAN}{'═' * 80}{Colors.RESET}\n")
    
    def log_user_input(self, text: str, description: str = ""):
        self.turn_count += 1
        print(f"{Colors.BOLD}{Colors.BLUE}[Turn {self.turn_count}] User:{Colors.RESET}")
        if description:
            print(f"{Colors.DIM}  Context: {description}{Colors.RESET}")
        print(f"{Colors.BLUE}  💬 \"{text}\"{Colors.RESET}\n")
    
    def log_agent_response(self, text: str):
        print(f"{Colors.BOLD}{Colors.GREEN}[Turn {self.turn_count}] Agent:{Colors.RESET}")
        print(f"{Colors.GREEN}  🤖 {text}{Colors.RESET}\n")
        print(f"{Colors.DIM}{'─' * 80}{Colors.RESET}\n")
    
    def log_error(self, message: str):
        print(f"{Colors.RED}  ❌ ERROR: {message}{Colors.RESET}\n")
    
    def log_success(self, message: str):
        print(f"{Colors.GREEN}  ✓ {message}{Colors.RESET}\n")


class EnhancedTestCase(unittest.TestCase):
    """Base class with enhanced logging and natural language helpers."""
    
    def setUp(self):
        self.agent = None
        self.responses = []
        self.logger = None
    
    def start_conversation(self, test_name: str):
        """Initialize agent and logger."""
        self.agent = Agent()
        self.logger = ConversationLogger(test_name)
        # Initial greeting
        self.send("Hi there!", "User initiates conversation")
    
    def send(self, user_input: str, description: str = ""):
        """Send user input with logging."""
        if not self.agent:
            raise RuntimeError("Call start_conversation() first")
        
        self.logger.log_user_input(user_input, description)
        result = self.agent.next(user_input)
        response = result["message"]
        self.logger.log_agent_response(response)
        self.responses.append(response)
        return response
    
    def assert_contains(self, *keywords: str, error_msg: str = ""):
        """Assert that any response contains at least one keyword."""
        joined = " ".join(self.responses).lower()
        found = any(k.lower() in joined for k in keywords)
        if not found:
            self.logger.log_error(f"Expected keywords not found: {keywords}")
            self.logger.log_error(f"Last response: {self.responses[-1][:200]}")
        self.assertTrue(found, error_msg or f"Expected one of {keywords} in responses")
    
    def assert_not_contains(self, *keywords: str, error_msg: str = ""):
        """Assert that responses don't contain keywords."""
        joined = " ".join(self.responses).lower()
        found_words = [k for k in keywords if k.lower() in joined]
        if found_words:
            self.logger.log_error(f"Forbidden keywords found: {found_words}")
        self.assertFalse(found_words, error_msg or f"Should not contain {keywords}")
    
    def assert_no_sensitive_leak(self):
        """Check for sensitive data exposure."""
        sensitive_patterns = [
            "your dob is", "your date of birth is",
            "your aadhaar", "aadhaar on file",
            "your pincode is", "registered pincode is"
        ]
        joined = " ".join(self.responses).lower()
        leaked = [p for p in sensitive_patterns if p in joined]
        if leaked:
            self.logger.log_error(f"Sensitive data leaked: {leaked}")
        self.assertFalse(leaked, f"Sensitive data exposed: {leaked}")


# ══════════════════════════════════════════════════════════════════════════════
# GROUP A: Successful Payment Flows
# ══════════════════════════════════════════════════════════════════════════════

class TestA_SuccessfulFlow(EnhancedTestCase):
    """Natural language success scenarios."""
    
    @patch("tools.process_payment", return_value=PAY_SUCCESS)
    @patch("tools.lookup_account", return_value=ACC1001)
    def test_A1_happy_path_natural_inputs(self, _lu, _pay):
        """A1: Natural conversational inputs - happy path."""
        self.start_conversation("A1: Happy Path with Natural Language")
        
        self.send("yeah my account is ACC1001", "Account ID in natural sentence")
        self.send("my name is Nithin Jain", "Name in conversational form")
        self.send("I was born on 14th May 1990", "DOB in spoken format")
        self.send("I want to pay a thousand rupees", "Amount in words")
        self.send("the card number is 4532 0151 1283 0366", "Card with spaces")
        self.send("CVV is one two three", "CVV spoken")
        self.send("expires December 2027", "Natural expiry format")
        self.send("name on card is Nithin Jain", "Cardholder name")
        
        self.assert_contains("txn_", "successful", "success", "transaction")
        self.assert_no_sensitive_leak()
    
    @patch("tools.process_payment", return_value=PAY_SUCCESS)
    @patch("tools.lookup_account", return_value=ACC1001)
    def test_A2_messy_account_id(self, _lu, _pay):
        """A2: Account ID with extra text and spacing."""
        self.start_conversation("A2: Messy Account ID Input")
        
        self.send("it's ACC 1001 I think", "Account with spaces and uncertainty")
        self.send("Nithin Jain")
        self.send("DOB is 1990-05-14")
        self.send("just pay 500 for now", "Partial payment request")
        self.send("4532015112830366, CVV 123, exp 12/27, name Nithin Jain", 
                  "All card details at once")
        
        self.assert_contains("txn_", "success")
    
    @patch("tools.process_payment", return_value=PAY_SUCCESS)
    @patch("tools.lookup_account", return_value=ACC1002)
    def test_A3_long_indian_name(self, _lu, _pay):
        """A3: Long name handling (assignment example)."""
        self.start_conversation("A3: Long Indian Name")
        
        self.send("account id: acc1002", "Lowercase account ID")
        self.send("you can call me Raja but my full name is Rajarajeswari Balasubramaniam",
                  "Long name with nickname")
        self.send("my Aadhaar ends with 9876", "Aadhaar last 4 in natural form")
        self.send("just clear the full amount", "Request full balance payment")
        self.send("card: 4532015112830366, cvv: 123, expiry: 12/2027, name: Rajarajeswari Balasubramaniam",
                  "All card details formatted")
        
        self.assert_contains("txn_", "success")
    
    @patch("tools.process_payment", return_value=PAY_SUCCESS)
    @patch("tools.lookup_account", return_value=ACC1001)
    def test_A4_card_details_incremental(self, _lu, _pay):
        """A4: Card details provided one field at a time."""
        self.start_conversation("A4: Incremental Card Details")
        
        self.send("ACC1001")
        self.send("Nithin Jain")
        self.send("pincode is 4 0 0 0 0 1", "Pincode with spaces")
        self.send("pay 1000")
        self.send("card number is 4532 0151 1283 0366", "Card with spaces")
        time.sleep(0.1)
        self.send("CVV is 123", "CVV next turn")
        time.sleep(0.1)
        self.send("it expires in 12/27", "Expiry with 2-digit year")
        time.sleep(0.1)
        self.send("cardholder name: Nithin Jain", "Name last")
        
        self.assert_contains("txn_", "success")
    
    @patch("tools.lookup_account", return_value=ACC1003)
    def test_A5_zero_balance_no_payment(self, _lu):
        """A5: Zero balance account - should not ask for payment."""
        self.start_conversation("A5: Zero Balance Account")
        
        self.send("ACC1003")
        self.send("Priya Agarwal")
        self.send("last 4 of my Aadhaar is 2468", "Aadhaar verification")
        
        self.assert_contains("no outstanding", "zero", "₹0", "nothing to pay")
        self.assert_not_contains("card number", "cvv", "expiry",
                                error_msg="Should not ask for card on zero balance")


# ══════════════════════════════════════════════════════════════════════════════
# GROUP B: Verification Failures
# ══════════════════════════════════════════════════════════════════════════════

class TestB_VerificationFailure(EnhancedTestCase):
    """Identity verification strictness tests."""
    
    @patch("tools.lookup_account", return_value=ACC1001)
    def test_B1_wrong_name_rejected(self, _lu):
        """B1: Incorrect name must block verification."""
        self.start_conversation("B1: Wrong Name Rejection")
        
        self.send("ACC1001")
        self.send("my name is John Doe", "Wrong name")
        self.send("1990-05-14", "Correct DOB but wrong name")
        
        self.assert_not_contains("verified", "balance", "outstanding",
                                error_msg="Should not verify with wrong name")
    
    @patch("tools.lookup_account", return_value=ACC1001)
    def test_B2_wrong_secondary_factor(self, _lu):
        """B2: Correct name but wrong DOB/Aadhaar/PIN."""
        self.start_conversation("B2: Wrong Secondary Factor")
        
        self.send("ACC1001")
        self.send("Nithin Jain", "Correct name")
        self.send("I was born on 1st January 1999", "Wrong DOB")
        
        self.assert_not_contains("verified", "balance")
    
    @patch("tools.lookup_account", return_value=ACC1001)
    def test_B3_session_locks_after_three_attempts(self, _lu):
        """B3: Must lock session after 3 failed verification attempts."""
        self.start_conversation("B3: Session Lock After 3 Failures")
        
        self.send("ACC1001")
        self.send("Nithin Jain")
        self.send("2000-01-01", "Wrong attempt #1")
        self.send("1999-06-15", "Wrong attempt #2")
        self.send("1998-03-20", "Wrong attempt #3")
        
        # Try one more input - should be locked
        locked_response = self.send("1990-05-14", "Correct DOB but session should be locked")
        
        self.assertTrue(
            "locked" in locked_response.lower() or self.agent._session.is_locked,
            "Session should be locked after 3 failures"
        )
    
    @patch("tools.lookup_account", return_value=ACC1001)
    def test_B4_case_sensitive_name_matching(self, _lu):
        """B4: Name matching must be case-sensitive."""
        self.start_conversation("B4: Case-Sensitive Name Matching")
        
        self.send("ACC1001")
        self.send("nithin jain", "Lowercase name - should fail")
        self.send("1990-05-14")
        
        self.assert_not_contains("verified", "balance",
                                error_msg="Case-insensitive match should not work")


# ══════════════════════════════════════════════════════════════════════════════
# GROUP C: Payment Failures
# ══════════════════════════════════════════════════════════════════════════════

class TestC_PaymentFailure(EnhancedTestCase):
    """Payment error handling tests."""
    
    @patch("tools.process_payment", return_value=PAY_INVALID_CARD)
    @patch("tools.lookup_account", return_value=ACC1001)
    def test_C1_invalid_card_retry(self, _lu, _pay):
        """C1: Invalid card should prompt for retry."""
        self.start_conversation("C1: Invalid Card Handling")
        
        self.send("ACC1001")
        self.send("Nithin Jain")
        self.send("1990-05-14")
        self.send("1000")
        self.send("1234567890123456", "Invalid card (fails Luhn)")
        self.send("123")
        self.send("12/2027")
        self.send("Nithin Jain")
        
        self.assert_contains("invalid", "card", "incorrect",
                           error_msg="Should notify about invalid card")
    
    @patch("tools.lookup_account", return_value=ACC1001)
    def test_C2_amount_exceeds_balance(self, _lu):
        """C2: Amount > balance should be rejected."""
        self.start_conversation("C2: Excessive Amount Rejection")
        
        self.send("ACC1001")
        self.send("Nithin Jain")
        self.send("1990-05-14")
        self.send("I need to pay 99999 rupees", "Way over balance")
        
        self.assert_contains("exceeds", "balance", "too much",
                           error_msg="Should reject amount > balance")


# ══════════════════════════════════════════════════════════════════════════════
# GROUP D: Edge Cases
# ══════════════════════════════════════════════════════════════════════════════

class TestD_EdgeCases(EnhancedTestCase):
    """Edge case handling."""
    
    @patch("tools.process_payment", return_value=PAY_SUCCESS)
    @patch("tools.lookup_account", return_value=ACC1004)
    def test_D1_leap_year_dob(self, _lu, _pay):
        """D1: Leap year DOB (Feb 29, 1988)."""
        self.start_conversation("D1: Leap Year DOB")
        
        self.send("ACC1004")
        self.send("Rahul Mehta")
        self.send("I was born on February 29, 1988", "Leap year date")
        self.send("pay 1000")
        self.send("4532015112830366, 123, 12/2027, Rahul Mehta")
        
        self.assert_contains("txn_", "success")
    
    @patch("tools.process_payment", return_value=PAY_SUCCESS)
    @patch("tools.lookup_account", return_value=ACC1001)
    def test_D2_two_digit_year_expiry(self, _lu, _pay):
        """D2: Card expiry with 2-digit year (12/27)."""
        self.start_conversation("D2: Two-Digit Year Expiry")
        
        self.send("ACC1001")
        self.send("Nithin Jain")
        self.send("1990-05-14")
        self.send("500")
        self.send("card 4532015112830366, cvv 123, exp 12/27, name Nithin Jain",
                  "Expiry with 2-digit year")
        
        self.assert_contains("txn_", "success")
    
    @patch("tools.process_payment", return_value=PAY_SUCCESS)
    @patch("tools.lookup_account", return_value=ACC1001)
    def test_D3_rupee_symbol_in_amount(self, _lu, _pay):
        """D3: Amount with ₹ symbol."""
        self.start_conversation("D3: Rupee Symbol in Amount")
        
        self.send("ACC1001")
        self.send("Nithin Jain")
        self.send("1990-05-14")
        self.send("₹1,000.00", "Amount with symbol and comma")
        self.send("4532015112830366, 123, 12/2027, Nithin Jain")
        
        self.assert_contains("txn_", "success")


# ══════════════════════════════════════════════════════════════════════════════
# Test Runner with Enhanced Reporting
# ══════════════════════════════════════════════════════════════════════════════

class ColoredTextTestResult(unittest.TextTestResult):
    """Test result with colored output."""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.test_times = {}
        self.current_test_start = None
    
    def startTest(self, test):
        super().startTest(test)
        self.current_test_start = time.time()
    
    def stopTest(self, test):
        super().stopTest(test)
        if self.current_test_start:
            elapsed = time.time() - self.current_test_start
            self.test_times[test.id()] = elapsed
    
    def addSuccess(self, test):
        super().addSuccess(test)
        print(f"{Colors.GREEN}✓ PASS{Colors.RESET} {test.id()}")
    
    def addError(self, test, err):
        super().addError(test, err)
        print(f"{Colors.RED}✗ ERROR{Colors.RESET} {test.id()}")
        print(f"{Colors.RED}{self._exc_info_to_string(err, test)}{Colors.RESET}")
    
    def addFailure(self, test, err):
        super().addFailure(test, err)
        print(f"{Colors.YELLOW}✗ FAIL{Colors.RESET} {test.id()}")
        print(f"{Colors.YELLOW}{self._exc_info_to_string(err, test)}{Colors.RESET}")


class ColoredTextTestRunner(unittest.TextTestRunner):
    """Test runner with colored output."""
    resultclass = ColoredTextTestResult


def print_summary_report(result):
    """Print beautiful summary report."""
    total = result.testsRun
    passed = total - len(result.failures) - len(result.errors)
    failed = len(result.failures)
    errors = len(result.errors)
    pass_rate = (passed / total * 100) if total > 0 else 0
    
    print(f"\n{Colors.BOLD}{Colors.CYAN}{'═' * 80}{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.CYAN}FINAL SUMMARY{Colors.RESET}")
    print(f"{Colors.CYAN}{'═' * 80}{Colors.RESET}\n")
    
    print(f"{Colors.BOLD}Total Tests:{Colors.RESET}     {total}")
    print(f"{Colors.GREEN}✓ Passed:{Colors.RESET}        {passed}")
    print(f"{Colors.YELLOW}✗ Failed:{Colors.RESET}        {failed}")
    print(f"{Colors.RED}✗ Errors:{Colors.RESET}        {errors}")
    print(f"{Colors.BOLD}Pass Rate:{Colors.RESET}       {pass_rate:.1f}%\n")
    
    # Group breakdown
    groups = {
        'A': ('Successful Flow', []),
        'B': ('Verification Failure', []),
        'C': ('Payment Failure', []),
        'D': ('Edge Cases', [])
    }
    
    for test_id in result.test_times.keys():
        for group_key in groups:
            if f'Test{group_key}_' in test_id:
                groups[group_key][1].append(test_id)
    
    print(f"{Colors.BOLD}Results by Group:{Colors.RESET}\n")
    for group_key, (group_name, tests) in groups.items():
        if tests:
            group_passed = sum(1 for t in tests if t not in 
                             [f.id() for f in result.failures + result.errors])
            total_group = len(tests)
            pct = group_passed / total_group * 100 if total_group > 0 else 0
            status_color = Colors.GREEN if pct == 100 else Colors.YELLOW if pct >= 50 else Colors.RED
            print(f"  {Colors.BOLD}Group {group_key} — {group_name}:{Colors.RESET}")
            print(f"    {status_color}{group_passed}/{total_group} passed ({pct:.0f}%){Colors.RESET}")
    
    print(f"\n{Colors.CYAN}{'═' * 80}{Colors.RESET}\n")


if __name__ == "__main__":
    print(f"\n{Colors.BOLD}{Colors.HEADER}{'═' * 80}")
    print(f"  PAYMENT COLLECTION AGENT — EVALUATION SUITE")
    print(f"  Enhanced with Natural Language Inputs & Clear Logging")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'═' * 80}{Colors.RESET}\n")
    
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # Load all test groups
    suite.addTests(loader.loadTestsFromTestCase(TestA_SuccessfulFlow))
    suite.addTests(loader.loadTestsFromTestCase(TestB_VerificationFailure))
    suite.addTests(loader.loadTestsFromTestCase(TestC_PaymentFailure))
    suite.addTests(loader.loadTestsFromTestCase(TestD_EdgeCases))
    
    runner = ColoredTextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    print_summary_report(result)
    
    sys.exit(0 if result.wasSuccessful() else 1)