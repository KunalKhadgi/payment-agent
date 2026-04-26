# Payment Collection AI Agent

A production-ready conversational agent that handles end-to-end payment collection: account lookup → identity verification → card payment processing.

---

## Setup

### 1. Install dependencies

```bash
cd payment-agent
pip install -r requirements.txt
```

### 2. Configure environment

Install Ollama from ollama.com, then pull the model:

```bash
ollama pull llama3.2:3b
```

No API key required — runs fully locally.

### 3. Run interactively

```bash
python cli.py
```

### 4. Run evaluation suite

```bash
python eval.py           # summary output
python eval.py --verbose # includes per-turn agent message previews
```

---

## Architecture

```
User
 │  next(user_input)
 ▼
Agent (agent.py)               ← Python FSM controls flow
 ├── State Machine             ← decides what step is active
 ├── LLM (Gemini 2.0 Flash)   ← NLU only: name detection + card extraction
 ├── validators.py             ← Luhn, CVV, expiry, amount validation
 ├── verification.py           ← strict identity check (no LLM involved)
 └── tools.py                  ← API calls (lookup-account + process-payment)
```

**Key principle**: The LLM never decides what step to execute next — the Python FSM does. LLM is used only where regex is insufficient: detecting whether a full name is present in free text, and extracting multi-field card details from natural language.

### State Machine

```
AWAIT_ACCOUNT_ID
    ↓ (account found)
AWAIT_NAME
    ↓ (name stored)
AWAIT_SECONDARY
    ↓ (verified)              ↓ (max retries exceeded)
AWAIT_AMOUNT               LOCKED
    ↓ (amount stored)
AWAIT_CARD
    ↓ (payment success)       ↓ (terminal error)
COMPLETED                  COMPLETED
```

---

## Sample Conversations

### 1 — Successful end-to-end payment

```
Agent: Hello! Welcome to the payment service.
       Please share your Account ID to get started (e.g. ACC1001).

You:   My account is ACC1001

Agent: Account found. To verify your identity, could you please tell me your
       full name as registered on the account?

You:   Nithin Jain

Agent: Thank you, Nithin Jain.
       To complete identity verification, please share one of:
         • Date of birth (YYYY-MM-DD)
         • Last 4 digits of your Aadhaar
         • Your registered pincode

You:   DOB is 1990-05-14

Agent: ✅ Identity verified successfully!
       Your outstanding balance is ₹1,250.75.
       How much would you like to pay today?

You:   1250.75

Agent: Got it — ₹1,250.75.
       Please provide your card details:
         • Card number
         • CVV
         • Expiry date (MM/YYYY)
         • Cardholder name

You:   Card: 4532015112830366, CVV: 123, Expiry: 12/2027, Name: Nithin Jain

Agent: ✅ Payment successful!
         Transaction ID : txn_1762510325322_l1fl4oy
         Amount paid    : ₹1,250.75
       Thank you for using our payment service. Have a great day!
```

### 2 — Verification failure (exhausted retries)

```
You:   Nithin Jain
Agent: Thank you. Please share your DOB, Aadhaar last 4, or pincode.

You:   2000-01-01
Agent: ❌ Details don't match. You have 2 attempts remaining.

You:   2001-01-01
Agent: ❌ Details don't match. You have 1 attempt remaining.

You:   2002-01-01
Agent: ❌ Verification failed. Maximum attempts exceeded.
       This session has been locked. Please contact customer support.
```

### 3 — Payment failure (expired card)

```
You:   4532015112830366, cvv 123, expiry 01/2020, name Nithin Jain

Agent: There are issues with some card details:
         • Expiry: This card has expired.
       Please provide a valid card.
```

### 4 — Edge case: zero balance account (ACC1003)

```
Agent: ✅ Identity verified successfully!
       Your account currently has no outstanding balance —
       there is nothing to pay. Your account is all clear!
       Thank you for reaching out. Have a great day!
```

---

## Design Decisions

| Decision                    | Choice                                | Rationale                                                                  |
| --------------------------- | ------------------------------------- | -------------------------------------------------------------------------- |
| State control               | Python FSM                            | Deterministic, testable — LLM cannot skip or reorder steps                 |
| LLM usage                   | Name detection + card extraction only | Everything else is rule-based; LLM used where regex genuinely fails        |
| LLM role in name extraction | Detection only (true/false)           | Prevents LLM from corrupting long names like Rajarajeswari Balasubramaniam |
| Name stored verbatim        | Raw user input, not LLM output        | Ensures strict case-sensitive match works correctly per spec               |
| Sensitive data              | Never passed to LLM                   | `account_data` (DOB, Aadhaar, pincode) lives in Python only                |
| Verification matching       | Strict string equality                | Spec requirement — no fuzzy matching, no case folding                      |
| Max retries                 | 3                                     | Balances security vs usability                                             |
| Card collection             | Multi-turn accumulation               | Better UX — user can provide fields gradually across turns                 |
| LLM provider                | Ollama + llama3.2:3b                  | Runs locally, no API key, no quota limits, free                            |

---

## Evaluation Results

```
Results: 10/11 passed

Dimension breakdown:
  Verification gating    2/2  ✅
  Happy path             2/2  ✅
  Edge cases             3/4  ⚠️
  Payment failures       2/2  ✅
```

The one failing edge case (T11 — multi-turn card collection) is non-deterministic: the LLM occasionally returns the string `"null"` instead of JSON `null` for fields not present in a turn. Mitigated with a post-parse normalization step; passes on most runs.

---

## What I Would Improve with More Time

1. **Mocked API layer** — deterministic tests with no live API calls or LLM dependency
2. **Regex fallback for card extraction** — eliminate LLM dependency for card fields entirely
3. **Rate limiting and session timeout** — required for any production deployment
4. **Structured logging** with card data redacted for audit trails
5. **Async support** for multi-user throughput
6. **Retry with backoff** on LLM quota errors instead of silent failure

---

## Assumptions & Design Notes

> Per the assignment: _"If anything is unclear, document your assumptions."_

**A1 — Name matching is byte-exact.**
The spec says "strict — no fuzzy matching, no case-insensitive workarounds." This was implemented as Python `==` string equality. A user typing `nithin jain` fails verification against `Nithin Jain`. This is intentional and correct per spec.

**A2 — LLM used only for name presence detection, not name extraction.**
Early versions passed the LLM-extracted name string directly into verification. This caused silent corruption of long names (e.g. Rajarajeswari Balasubramaniam was mangled). The fix: LLM only answers whether a name is present (`true/false`); the actual name string is always taken verbatim from user input after stripping common prefixes like "my name is", "I am", etc.

**A3 — Retry counter increments only on secondary factor failure, not name failure.**
The spec defines retries for verification attempts. A user providing the wrong secondary factor consumes a retry; providing no secondary factor at all (unrecognised input) prompts them to try again without consuming a retry.

**A4 — Partial payments are allowed without re-verification.**
The spec explicitly allows `amount < balance`. Once verified, the user can pay any positive amount up to their balance without re-entering identity details.

**A5 — Card data is not persisted beyond the API call.**
Raw card fields exist only in the `CardDetails` dataclass in memory for the duration of the session. They are cleared on card error and not logged anywhere.

**A6 — `1988-02-29` (ACC1004) is treated as a valid date.**
1988 is a leap year. Python's `datetime.strptime` accepts this correctly. The agent verifies it as-is against the stored DOB. An invalid leap date like `1998-02-29` (1998 not a leap year) is extracted but will simply not match, failing verification normally.

**A7 — API base URL.**
The assignment spec lists the base URL as ending in `/openapi/`. The actual live API responds at the root without the `/openapi` prefix. Corrected in `tools.py`.

**A8 — Cardholder name on payment API is not validated against account name.**
The spec explicitly states: _"cardholder_name is accepted as-is and not validated against the account holder's name."_ The agent passes whatever name the user provides for the card.

**A9 — Zero balance accounts are closed gracefully without entering payment flow.**
The spec does not define this case explicitly. The agent detects `balance == 0.0` after verification and ends the session cleanly rather than asking for payment details.

**A10 — LLM provider substitution.**
The original implementation used Claude (Anthropic). Anthropic API keys require billing setup. Switched to Ollama running llama3.2:3b locally. Requires no API key, has no quota limits, and runs fully offline. Only the LLM client in agent.py changed — all business logic remains identical.
