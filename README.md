# Payment Collection Agent

An LLM-powered conversational agent that collects overdue payments via natural language dialogue. The agent runs locally through [Ollama](https://ollama.com), uses structured tool calls to drive a strict payment workflow, and never exposes sensitive customer data to the model.

---

## Architecture Overview

```
User Input
    │
    ▼
agent.py  (Agent)
    │  builds message history + system state
    │  dispatches to Ollama (local LLM)
    │
    ├──► tool_schemas.py   — Ollama-compatible function definitions
    ├──► tool_executor.py  — Thin dispatch layer (no business logic)
    │        ├── tools.py          — External API calls (lookup, payment)
    │        ├── validators.py     — Pure-Python input validation (Luhn, CVV, DOB…)
    │        └── verification.py  — Identity comparison logic
    │
    └──► SessionState      — Sensitive fields (DOB, Aadhaar, pincode) stored
                             in Python only — NEVER sent to the LLM
```

### Key design principles

| Principle                        | Implementation                                                                   |
| -------------------------------- | -------------------------------------------------------------------------------- |
| No sensitive data in LLM context | `SessionState` stores account fields; model only receives `verified: true/false` |
| No business logic in Python      | All decisions (retries, ordering, what to ask) are made by the LLM               |
| Strict tool sequencing           | System prompt + `_next_step_hint()` enforces a 13-step workflow                  |
| Stateless tool executor          | `ToolExecutor` is a pure function-call bridge                                    |
| Local inference                  | Ollama — no data leaves the machine                                              |

---

## Payment Workflow

The agent enforces a strict, non-skippable 13-step sequence:

```
 1  Greet → ask for Account ID
 2  call lookup_account
 3  Ask for registered full name
 4  Ask for secondary factor  (DOB / Aadhaar last 4 / pincode)
 5  call verify_identity
     ↳ failure × 3 → call lock_session, stop
 6  If balance = 0 → call complete_session (zero_balance), stop
 7  Ask payment amount → call validate_amount
 8  Ask card number   → call validate_card_number
 9  Ask CVV           → call validate_cvv
10  Ask expiry date   → call validate_expiry
11  Ask cardholder name
12  call process_payment
13  call complete_session (payment_success)
```

---

## Project Structure

```
.
├── agent.py            # Core agent: Ollama loop, state, message builder
├── tool_schemas.py     # 9 Ollama function definitions
├── tool_executor.py    # Dispatch layer + SessionState dataclass
├── tools.py            # HTTP wrappers: lookup_account, process_payment
├── validators.py       # Luhn check, CVV, expiry, amount, DOB extraction
├── verification.py     # Exact-match identity comparison
├── cli.py              # Interactive terminal runner
├── eval.py             # Evaluation harness (unittest-based)
└── requirements.txt    # Python dependencies
```

---

## Setup

### Prerequisites

- Python 3.10+
- [Ollama](https://ollama.com) installed and running

### 1 — Install Ollama and pull a model

```bash
# Install Ollama (Linux/macOS)
curl -fsSL https://ollama.com/install.sh | sh

# Pull a supported model (choose one)
ollama pull qwen3:4b        # recommended — best tool-call accuracy
ollama pull qwen3:1.7b      # lighter, faster
ollama pull llama3:3b       # alternative
```

### 2 — Install Python dependencies

```bash
pip install -r requirements.txt
```

> **GPU note:** `requirements.txt` targets CUDA 11.8 (`cu118`). For CPU-only, replace the PyTorch index URL with the default `https://download.pytorch.org/whl/cpu`.

### 3 — Configure the model (optional)

Edit `agent.py` to switch models:

```python
MODEL_NAME = "qwen3:4b"   # change to qwen3:1.7b or llama3:3b
```

---

## Running

### Interactive CLI

```bash
python cli.py
```

Type `quit` or `exit` to end the session.

### Evaluation harness

```bash
python eval.py
```

The harness mocks the external API, runs scripted conversation scenarios, and reports pass/fail per test case.

---

## Tool Reference

| Tool                   | Purpose                       | Called when                     |
| ---------------------- | ----------------------------- | ------------------------------- |
| `lookup_account`       | Fetch account by ID           | User provides account ID        |
| `verify_identity`      | Name + secondary factor check | Both name and factor collected  |
| `process_payment`      | Submit card payment to API    | All card fields validated       |
| `validate_card_number` | Luhn check (13–19 digits)     | User provides card number       |
| `validate_cvv`         | 3-digit (4 for Amex) check    | User provides CVV               |
| `validate_expiry`      | Month/year validity check     | User provides expiry date       |
| `validate_amount`      | Positive, ≤ balance, ≤ 2dp    | User states payment amount      |
| `lock_session`         | Permanent session lock        | 3 failed verify attempts        |
| `complete_session`     | Mark session done             | Payment success or zero balance |

---

## Test Accounts

| Account | Name                          | DOB        | Aadhaar (last 4) | PIN    | Balance   |
| ------- | ----------------------------- | ---------- | ---------------- | ------ | --------- |
| ACC1001 | Nithin Jain                   | 1990-05-14 | 4321             | 400001 | ₹1,250.75 |
| ACC1002 | Rajarajeswari Balasubramaniam | 1985-11-23 | 9876             | 400002 | ₹540.00   |
| ACC1003 | Priya Agarwal                 | 1992-08-10 | 2468             | 400003 | ₹0.00     |
| ACC1004 | Rahul Mehta                   | 1988-02-29 | 1357             | 400004 | ₹3,200.50 |

---

## External API

| Endpoint               | Method | Purpose                                                    |
| ---------------------- | ------ | ---------------------------------------------------------- |
| `/api/lookup-account`  | POST   | Returns account fields; raises `APIError` on 404           |
| `/api/process-payment` | POST   | Returns `transaction_id` on 200; application errors on 422 |

Base URL: `https://se-payment-verification-api.service.external.usea2.aws.prodigaltech.com`

---

## Security Notes

- Sensitive fields (`dob`, `aadhaar_last4`, `pincode`, `full_name`) are stored in `SessionState` (Python memory) and **never included in any LLM message**.
- The model receives only `{"verified": true/false}` from `verify_identity`.
- The agent is explicitly instructed: _NEVER expose DOB, Aadhaar, or pincode to the user_.
- Identity comparison is exact-match (case-sensitive, no fuzzy matching).

---

## Known Limitations

- `num_ctx: 4096` on `qwen3:4b` constrains long conversations — the history window trims to 8 messages and avoids orphaning `role: tool` entries.
- Small models (1.7b, 3b) occasionally hallucinate tool arguments (e.g., inventing DOB values or placeholder card numbers).
- Natural-language date formats (e.g., "14th May 1990") require the model to perform DOB conversion before calling `verify_identity`; smaller models sometimes skip this.
