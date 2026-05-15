"""
agent.py
────────
Pure agent-based payment collection agent backed by Ollama (llama.cpp).

Setup
─────
1. Install Ollama:  https://ollama.com
2. Pull the model:  ollama pull qwen3:4b
3. Ollama runs as a background service automatically.
"""

import json
import re
import requests
from typing import Dict, List, Optional

from tool_schemas import TOOLS
from tool_executor import SessionState, ToolExecutor


# ─── Config ───────────────────────────────────────────────────────────────────

OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL_NAME = "qwen3:4b"


# ─── System Prompt ────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are a payment collection agent. Guide the customer step by step.

## STRICT SEQUENCE — never skip, never reorder:
STEP 1 — Greet and ask for Account ID
STEP 2 — Call lookup_account as soon as user gives an account ID
STEP 3 — Ask for full name (exactly as registered)
STEP 4 — Ask for one secondary factor: date of birth, Aadhaar last 4 digits, or pincode
STEP 5 — Call verify_identity with name + secondary factor
         • Failure: inform user, ask again. After 3 failures → call lock_session, stop.
         • Success: tell user their balance
STEP 6 — If balance is 0 → call complete_session reason="zero_balance", stop
STEP 7 — Ask how much they want to pay → call validate_amount
STEP 8 — Ask for card number → call validate_card_number
STEP 9 — Ask for CVV → call validate_cvv
STEP 10 — Ask for expiry date → call validate_expiry
STEP 11 — Ask for cardholder name (no validation needed)
STEP 12 — Call process_payment (only after steps 7-11 all complete)
STEP 13 — On success → call complete_session reason="payment_success"

## CRITICAL RULES:
- NEVER call any tool until you have ALL required values from the user
- NEVER guess, invent, or assume any value — always ask if missing
- NEVER call verify_identity without both name AND secondary factor from user
- NEVER call validate_amount before identity is verified
- NEVER call process_payment before all card fields are collected and validated
- NEVER expose DOB, Aadhaar, or pincode to the user
- On greeting ("Hi", "Hello") — respond with greeting and ask for Account ID, NO tool calls

## DOB CONVERSION — always convert to YYYY-MM-DD:
- "14th May 1990" → "1990-05-14"
- "May 14, 1990" → "1990-05-14"
- "14/05/1990" → "1990-05-14"
- "May 14, 90" → "1990-05-14"

## RESPONSE STYLE — be brief:
- After lookup: "Account found. Please provide your full name."
- After name: "Thank you. Please provide your date of birth (YYYY-MM-DD), Aadhaar last 4, or pincode."
- After verify success: "Identity verified. Your balance is ₹X. How much would you like to pay?"
- Collecting card: ask for ONE missing field at a time, never assume any value.
"""


# ─── Agent ────────────────────────────────────────────────────────────────────

class Agent:
    MAX_TOOL_ROUNDS = 8

    def __init__(self):
        self._session = SessionState()
        self._executor = ToolExecutor(self._session)
        self._history: List[Dict] = []
        self._tool_call_cache: Dict[str, str] = {}

        try:
            requests.get("http://localhost:11434", timeout=3)
            print(f"[INFO] Ollama running. Model: {MODEL_NAME}")
        except requests.exceptions.ConnectionError:
            raise RuntimeError("Ollama is not running. Install from https://ollama.com")

    # ─── Public Interface ─────────────────────────────────────────────────────

    def next(self, user_input: str) -> Dict[str, str]:
        if self._session.is_locked:
            return {"message": "Session locked due to failed verification. Please contact support."}

        if self._session.is_complete:
            return {"message": "Session complete. Thank you for using our payment service!"}

        text = str(user_input).strip()
        if not text:
            return {"message": "I didn't catch that. Could you please repeat?"}

        self._history.append({"role": "user", "content": text})
        response_text = self._run_agent_loop()
        return {"message": response_text}

    # ─── Agentic Loop ─────────────────────────────────────────────────────────

    def _run_agent_loop(self) -> str:
        messages = self._build_messages()
        empty_count = 0

        # Extract card number from last user message if present
        last_user_msg = next((m for m in reversed(self._history) if m["role"] == "user"), None)
        extracted_card = None
        if last_user_msg:
            extracted_card = self._extract_card_number(last_user_msg["content"])
            if extracted_card:
                # Add hint to system about extracted card
                messages[0]["content"] += f"\n\n[EXTRACTED CARD NUMBER: {extracted_card}]"

        for _ in range(self.MAX_TOOL_ROUNDS):
            response = self._call_ollama(messages)
            response_text = response["content"] or ""
            tool_calls = response["tool_calls"]
            
            print(f"[DEBUG] Model output: {response_text[:300]}")
            print(f"[DEBUG] Parsed {len(tool_calls)} tool call(s)")

            if not tool_calls:
                content = response_text.strip()
                if content:
                    self._history.append({"role": "assistant", "content": content})
                    return content
                # Empty — nudge once then give up
                empty_count += 1
                if empty_count >= 2:
                    break
                messages.append({
                    "role": "user",
                    "content": "Please respond to the customer."
                })
                continue

            # Execute tool calls
            self._history.append({
                "role": "assistant",
                "content": response_text,
                "tool_calls": tool_calls,
            })
            messages.append({"role": "assistant", "content": response_text, "tool_calls": tool_calls})

            for tc in tool_calls:
                fn           = tc.get("function", {})
                tool_name    = fn.get("name", "")
                raw_args     = fn.get("arguments", {})
                # Ollama sets an "id" on each tool call; must be echoed back
                tool_call_id = tc.get("id", "")

                if isinstance(raw_args, str):
                    try:
                        arguments = json.loads(raw_args)
                    except json.JSONDecodeError:
                        arguments = {}
                else:
                    arguments = raw_args

                cache_key = f"{tool_name}:{json.dumps(arguments, sort_keys=True)}"

                if cache_key in self._tool_call_cache:
                    result = self._tool_call_cache[cache_key]
                    print(f"[CACHED] {tool_name}")
                else:
                    print(f"[TOOL]   {tool_name}({json.dumps(arguments, ensure_ascii=False)})")
                    result = self._executor.execute(tool_name, arguments)
                    self._tool_call_cache[cache_key] = result

                print(f"[RESULT] {result}")
                # Include tool_call_id so Ollama can match result to the call
                tool_msg = {"role": "tool", "content": result}
                if tool_call_id:
                    tool_msg["tool_call_id"] = tool_call_id
                messages.append(tool_msg)
                self._history.append({"role": "tool", "content": result})

        fallback = "I'm having trouble processing your request. Please try again."
        self._history.append({"role": "assistant", "content": fallback})
        return fallback

    # ─── Ollama API Call ──────────────────────────────────────────────────────

    def _call_ollama(self, messages: List[Dict]) -> Dict:
        """Call Ollama API and return the full message object."""
        payload = {
            "model": MODEL_NAME,
            "messages": messages,
            "tools": TOOLS,  # ← CRITICAL FIX: Pass tools to Ollama
            "stream": False,
            "options": {
                "temperature": 0,
                "num_predict": 400,
                "repeat_penalty": 1.0,
                "num_ctx": 4096,
                "top_k": 1,
            },
        }
        try:
            resp = requests.post(OLLAMA_URL, json=payload, timeout=180)
            resp.raise_for_status()

            raw = resp.text.strip()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                lines = [l for l in raw.splitlines() if l.strip()]
                data = json.loads(lines[-1])

            message = data.get("message", {})
            content = message.get("content", "")
            
            # Strip thinking blocks from content
            content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()

            tool_calls = message.get("tool_calls", [])
            # When the model only emits tool calls, content may be empty after
            # stripping <think> blocks.  Sending content="" alongside tool_calls
            # confuses some Ollama builds — use None to signal "no text".
            return {
                "content": content if content else None,
                "tool_calls": tool_calls,
            }

        except requests.exceptions.Timeout:
            return {"content": "Request timed out. Please try again.", "tool_calls": []}
        except requests.exceptions.RequestException as e:
            return {"content": f"Connection error: {e}", "tool_calls": []}

    # ─── Message Builder ──────────────────────────────────────────────────────

    def _build_messages(self) -> List[Dict]:
        state = self._summarize_state()
        next_step = self._next_step_hint(state)

        system_content = SYSTEM_PROMPT
        system_content += "\n### Current Session State:\n"
        system_content += json.dumps(state, indent=2)
        system_content += f"\n\n### YOUR NEXT ACTION: {next_step}\n"
        system_content += "\nNow respond to the last user message.\n"

        # Send last 6 messages for context
        recent = self._history[-6:]
        cleaned = []
        for m in recent:
            c = re.sub(r"<think>.*?</think>", "", m.get("content", ""), flags=re.DOTALL).strip()
            cleaned.append({**m, "content": c})

        return [{"role": "system", "content": system_content}] + cleaned

    def _next_step_hint(self, state: Dict) -> str:
        """Tell the model exactly what to do next."""
        if not state["account_id"]:
            return "Greet the customer and ask for their Account ID. Do NOT call any tool yet."
        if not state["name_provided"]:
            return "Account found. Ask for customer's full name. Do NOT call any tool yet."
        if not state["identity_verified"] and state["verification_attempts"] == 0:
            return "Ask for secondary factor (DOB/Aadhaar last 4/pincode), then call verify_identity."
        if not state["identity_verified"]:
            return f"Verification failed ({state['verification_attempts']} attempts). Ask for secondary factor again, then call verify_identity."
        if state["balance"] == 0:
            return "Balance is zero. Call complete_session with reason=zero_balance."
        if not state["amount_validated"]:
            return f"Identity verified. Balance is ₹{state['balance']}. Ask how much to pay, then call validate_amount."
        if not state["card"]["number"]:
            return "Ask for card number, then call validate_card_number."
        if not state["card"]["cvv"]:
            return "Ask for CVV, then call validate_cvv."
        if not state["card"]["expiry_month"]:
            return "Ask for card expiry date, then call validate_expiry."
        if not state["card"]["cardholder_name"]:
            return "Ask for the name printed on the card. No tool call needed."
        if not state["payment_done"]:
            return "All details collected. Call process_payment now."
        return "Payment done. Call complete_session with reason=payment_success."

    # ─── State Summarizer ─────────────────────────────────────────────────────

    def _summarize_state(self) -> Dict:
        state = {
            "account_id": None,
            "balance": None,
            "name_provided": False,
            "identity_verified": False,
            "verification_attempts": 0,
            "amount_validated": None,
            "card": {
                "number": None,
                "cvv": None,
                "expiry_month": None,
                "expiry_year": None,
                "cardholder_name": None,
            },
            "payment_done": False,
            "transaction_id": None,
            "session_locked": False,
            "session_complete": False,
        }

        for msg in self._history:
            content = msg.get("content", "")
            role    = msg.get("role", "")

            if role == "user":
                lower = content.lower()
                # name_provided: user message after account lookup,
                # not an account ID, not a number-only secondary factor,
                # at least 2 words (first + last name)
                if state["account_id"] and not state["identity_verified"]:
                    if not re.search(r"ACC\d+", content, re.IGNORECASE):
                        if not re.search(r"\d{4}-\d{2}-\d{2}", content):
                            if not re.search(r"^\s*\d{4,6}\s*$", content):
                                if len(content.split()) >= 2:
                                    state["name_provided"] = True

                # cardholder name after identity verified
                if state["identity_verified"]:
                    for pattern in ("name on card is ", "cardholder name: ", "name is "):
                        if pattern in lower:
                            idx = lower.index(pattern) + len(pattern)
                            state["card"]["cardholder_name"] = content[idx:].split(",")[0].strip()
                            break

            elif role == "tool":
                try:
                    data = json.loads(content)
                except json.JSONDecodeError:
                    continue

                # lookup_account
                if "account_id" in data and "balance" in data:
                    state["account_id"] = data["account_id"]
                    state["balance"]    = data["balance"]

                # verify_identity
                if "verified" in data:
                    state["verification_attempts"] += 1
                    if data["verified"]:
                        state["identity_verified"] = True

                # validate_amount — has "amount" but NOT "cleaned" key
                if "valid" in data and "amount" in data and "cleaned" not in data and data.get("valid"):
                    state["amount_validated"] = data["amount"]

                # validate_card_number — "cleaned" with length >= 13
                if "valid" in data and "cleaned" in data and data.get("valid"):
                    cleaned_val = data["cleaned"]
                    if len(cleaned_val) >= 13:
                        state["card"]["number"] = cleaned_val
                    elif len(cleaned_val) in (3, 4):
                        state["card"]["cvv"] = cleaned_val

                # validate_expiry
                if "valid" in data and "month" in data and "year" in data and data.get("valid"):
                    state["card"]["expiry_month"] = data["month"]
                    state["card"]["expiry_year"]  = data["year"]

                # process_payment
                if "transaction_id" in data:
                    state["payment_done"]   = True
                    state["transaction_id"] = data["transaction_id"]

                # lock_session
                if data.get("locked"):
                    state["session_locked"] = True

                # complete_session
                if data.get("complete"):
                    state["session_complete"] = True

        return state

    # ─── Tool Call Parser ─────────────────────────────────────────────────────

    def _parse_tool_calls(self, response_text: str) -> List[Dict]:
        tool_calls = []
        for line in response_text.split("\n"):
            line = line.strip()
            if line.startswith("TOOL_CALL:"):
                try:
                    tool_data = json.loads(line[len("TOOL_CALL:"):].strip())
                    tool_calls.append({
                        "function": {
                            "name":      tool_data.get("name", ""),
                            "arguments": tool_data.get("arguments", {}),
                        }
                    })
                except json.JSONDecodeError:
                    print(f"[WARN] Failed to parse tool call: {line}")
        return tool_calls
    
    def _extract_card_number(self, user_input: str) -> Optional[str]:
        """Extract card number from user input using regex."""
        import re
        # Match 13-19 digits with optional spaces/dashes
        pattern = r'\b(\d[\s\-]?){12,18}\d\b'
        matches = re.findall(pattern, user_input)
        
        if matches:
            # Take the longest match (most likely the card number)
            card = max([''.join(m) for m in matches], key=len)
            # Remove spaces and dashes
            card = re.sub(r'[\s\-]', '', card)
            return card if 13 <= len(card) <= 19 else None
        return None
