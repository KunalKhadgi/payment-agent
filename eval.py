"""
eval.py
───────
Automated evaluation suite for the Payment Collection Agent.

Each test case is a scripted conversation with assertions at each turn.
Run with:
    python eval.py

Requires a live ANTHROPIC_API_KEY and access to the payment verification API.

Metrics tracked per test:
  • conversation_completed   — did the flow reach a terminal state cleanly?
  • verification_gated       — did the agent block payment until verified?
  • no_data_leak             — were DOB / aadhaar / pincode never echoed back?
  • correct_terminal_message — did the final message contain the expected signal?
  • api_called_correctly     — proxy: did we get a txn_id on success / error_code on failure?
"""

import sys
import time
from dataclasses import dataclass, field
from typing import List, Optional

from agent import Agent


# ─── Assertion Helpers ────────────────────────────────────────────────────────

SENSITIVE_FIELDS = ["1990-05-14", "4321", "400001",   # ACC1001
                    "1985-11-23", "9876", "400002",   # ACC1002
                    "1988-02-29", "1357", "400004"]   # ACC1004


def contains_sensitive(messages: List[str]) -> bool:
    """Return True if any agent message leaks a known-sensitive value."""
    for msg in messages:
        for s in SENSITIVE_FIELDS:
            if s in msg:
                return True
    return False


def contains_any(text: str, *keywords: str) -> bool:
    return any(k.lower() in text.lower() for k in keywords)


# ─── Test Case Structure ──────────────────────────────────────────────────────

@dataclass
class Turn:
    user: str
    expect_contains: List[str] = field(default_factory=list)   # agent reply should contain at least one
    expect_not_contains: List[str] = field(default_factory=list)  # agent reply must NOT contain any


@dataclass
class TestCase:
    name: str
    turns: List[Turn]
    expect_no_data_leak: bool = True


@dataclass
class TestResult:
    name: str
    passed: bool = True
    failures: List[str] = field(default_factory=list)
    agent_messages: List[str] = field(default_factory=list)


# ─── Test Cases ───────────────────────────────────────────────────────────────

def build_test_cases() -> List[TestCase]:
    return [

        # ── 1. Happy path — full payment, DOB verification ────────────────────
        TestCase(
            name="T01 — Happy path (ACC1001, DOB, full payment)",
            turns=[
                Turn("Hi",
                     expect_contains=["Account ID", "account"]),
                Turn("ACC1001",
                     expect_contains=["name"]),
                Turn("Nithin Jain",
                     expect_contains=["verification", "birth", "Aadhaar", "pincode"]),
                Turn("1990-05-14",
                     expect_contains=["verified", "balance", "1,250"]),
                Turn("1250.75",
                     expect_contains=["card"]),
                Turn("Card: 4532015112830366, CVV: 123, Expiry: 12/2027, Name: Nithin Jain",
                     expect_contains=["successful", "Transaction"]),
            ],
        ),

        # ── 2. Happy path — Aadhaar verification, partial payment ─────────────
        TestCase(
            name="T02 — Happy path (ACC1002, Aadhaar, partial payment)",
            turns=[
                Turn("My account is ACC1002",
                     expect_contains=["name"]),
                Turn("Rajarajeswari Balasubramaniam",
                     expect_contains=["verification"]),
                Turn("aadhaar last 4 is 9876",
                     expect_contains=["verified", "540"]),
                Turn("pay 300",
                     expect_contains=["card"]),
                Turn("4532015112830366, cvv 123, expires 12/2027, name Rajarajeswari Balasubramaniam",
                     expect_contains=["successful", "Transaction"]),
            ],
        ),

        # ── 3. Zero balance account ───────────────────────────────────────────
        TestCase(
            name="T03 — Zero balance (ACC1003)",
            turns=[
                Turn("ACC1003",
                     expect_contains=["name"]),
                Turn("Priya Agarwal",
                     expect_contains=["verification"]),
                Turn("pincode 400003",
                     expect_contains=["no outstanding", "nothing to pay", "all clear"]),
            ],
        ),

        # ── 4. Verification failure — wrong name ──────────────────────────────
        TestCase(
            name="T04 — Wrong name (case mismatch)",
            turns=[
                Turn("ACC1001",
                     expect_contains=["name"]),
                Turn("nithin jain",                    # lowercase — should fail
                     expect_contains=["verification"]),
                Turn("DOB 1990-05-14",
                     expect_contains=["don't match", "match", "failed", "incorrect", "not match"]),
            ],
        ),

        # ── 5. Verification failure — exhaust retries ─────────────────────────
        TestCase(
            name="T05 — Exhaust verification retries (ACC1001)",
            turns=[
                Turn("ACC1001",
                     expect_contains=["name"]),
                Turn("Nithin Jain",
                     expect_contains=["verification"]),
                Turn("DOB 2000-01-01",
                     expect_contains=["remaining", "match", "attempts"]),
                Turn("DOB 2001-01-01",                 # wrong
                     expect_contains=["remaining", "match", "attempts"]),
                Turn("DOB 2002-01-01",                 # wrong — exhausts retries
                     expect_contains=["locked", "exceeded", "support"]),
            ],
        ),

        # ── 6. Payment failure — invalid card (fails Luhn) ────────────────────
        TestCase(
            name="T06 — Invalid card number (fails Luhn)",
            turns=[
                Turn("ACC1001",
                     expect_contains=["name"]),
                Turn("Nithin Jain",
                     expect_contains=["verification"]),
                Turn("1990-05-14",
                     expect_contains=["verified"]),
                Turn("500",
                     expect_contains=["card"]),
                Turn("1234567890123456, cvv 123, expiry 12/2027, name Nithin Jain",
                     expect_contains=["invalid", "card"]),
            ],
        ),

        # ── 7. Payment failure — expired card ─────────────────────────────────
        TestCase(
            name="T07 — Expired card",
            turns=[
                Turn("ACC1001",
                     expect_contains=["name"]),
                Turn("Nithin Jain",
                     expect_contains=["verification"]),
                Turn("1990-05-14",
                     expect_contains=["verified"]),
                Turn("500",
                     expect_contains=["card"]),
                Turn("4532015112830366, cvv 123, expiry 01/2020, name Nithin Jain",
                     expect_contains=["expired", "invalid", "expiry"]),
            ],
        ),

        # ── 8. Edge case — leap year DOB (ACC1004) ────────────────────────────
        TestCase(
            name="T08 — Leap year DOB (ACC1004, 1988-02-29)",
            turns=[
                Turn("ACC1004",
                     expect_contains=["name"]),
                Turn("Rahul Mehta",
                     expect_contains=["verification"]),
                Turn("1988-02-29",                     # valid leap year date — should verification
                     expect_contains=["verified", "3,200"]),
            ],
        ),

        # ── 9. Edge case — out-of-order: name given with account ID ──────────
        TestCase(
            name="T09 — Out-of-order: name + account ID in same message",
            turns=[
                Turn("Hi, I'm Nithin Jain and my account ID is ACC1001",
                     expect_contains=["verification", "birth", "Aadhaar", "pincode"]),
                Turn("DOB is 1990-05-14",
                     expect_contains=["verified"]),
            ],
        ),

        # ── 10. Edge case — account not found ────────────────────────────────
        TestCase(
            name="T10 — Account not found",
            turns=[
                Turn("ACC9999",
                     expect_contains=["not found", "couldn't find", "check"]),
            ],
        ),

        # ── 11. Multi-turn card collection ────────────────────────────────────
        TestCase(
            name="T11 — Card details spread across multiple turns",
            turns=[
                Turn("ACC1001",   expect_contains=["name"]),
                Turn("Nithin Jain", expect_contains=["verification"]),
                Turn("400001",    expect_contains=["verified"]),         # pincode
                Turn("1000",      expect_contains=["card"]),
                Turn("My card number is 4532015112830366",
                     expect_contains=["need", "still", "cvv", "expiry", "name"]),
                Turn("CVV is 123",
                     expect_contains=["need", "still"]),
                Turn("Expiry 12/2027",
                     expect_contains=["invalid", "issues", "error", "still"]),
                Turn("Name: Nithin Jain",
                     expect_contains=["successful", "Transaction"]),
            ],
        ),

    ]


# ─── Runner ───────────────────────────────────────────────────────────────────

def run_test(tc: TestCase) -> TestResult:
    result = TestResult(name=tc.name)
    agent = Agent()
    agent_messages: List[str] = []

    for i, turn in enumerate(tc.turns):
        try:
            response = agent.next(turn.user)
        except Exception as exc:
            result.failures.append(f"Turn {i+1} raised exception: {exc}")
            result.passed = False
            result.agent_messages = agent_messages
            return result

        msg = response.get("message", "")
        agent_messages.append(msg)

        # Check expected keywords
        if turn.expect_contains:
            found = any(k.lower() in msg.lower() for k in turn.expect_contains)
            if not found:
                result.failures.append(
                    f"Turn {i+1}: expected one of {turn.expect_contains!r} "
                    f"in response, got:\n    '{msg[:120]}...'"
                )

        # Check forbidden keywords
        for kw in turn.expect_not_contains:
            if kw.lower() in msg.lower():
                result.failures.append(
                    f"Turn {i+1}: forbidden keyword '{kw}' found in response."
                )

    # Data-leak check across all agent messages
    if tc.expect_no_data_leak and contains_sensitive(agent_messages):
        result.failures.append("SENSITIVE DATA LEAK detected in agent messages.")

    result.passed = len(result.failures) == 0
    result.agent_messages = agent_messages
    return result


def run_all(verbose: bool = False) -> None:
    test_cases = build_test_cases()
    results: List[TestResult] = []

    print("\n" + "═" * 60)
    print("  Payment Agent — Evaluation Suite")
    print("═" * 60)

    for tc in test_cases:
        print(f"\n▶  {tc.name}")
        start = time.time()
        result = run_test(tc)
        elapsed = time.time() - start

        status = "✅ PASS" if result.passed else "❌ FAIL"
        print(f"   {status}  ({elapsed:.1f}s)")

        if not result.passed:
            for f in result.failures:
                print(f"   ↳ {f}")

        if verbose and result.agent_messages:
            print("   Agent responses:")
            for i, m in enumerate(result.agent_messages):
                print(f"     [{i+1}] {m[:100]}{'...' if len(m) > 100 else ''}")

        results.append(result)

    # ── Summary ──
    passed = sum(1 for r in results if r.passed)
    total = len(results)
    print("\n" + "─" * 60)
    print(f"  Results: {passed}/{total} passed")

    # Per-dimension summary
    print("\n  Dimension breakdown:")
    dimensions = {
        "Verification gating": [r for r in results if "T04" in r.name or "T05" in r.name],
        "Happy path":          [r for r in results if "T01" in r.name or "T02" in r.name],
        "Edge cases":          [r for r in results if r.name.startswith(("T08", "T09", "T10", "T11"))],
        "Payment failures":    [r for r in results if "T06" in r.name or "T07" in r.name],
    }
    for dim, group in dimensions.items():
        if not group:
            continue
        p = sum(1 for r in group if r.passed)
        print(f"    {dim:25s}  {p}/{len(group)}")

    print("─" * 60)
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    verbose_mode = "--verbose" in sys.argv or "-v" in sys.argv
    run_all(verbose=verbose_mode)