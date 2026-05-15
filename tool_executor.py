"""
tool_executor.py
────────────────
Executes tool calls dispatched by the agent.

Design principle
────────────────
This module contains ZERO business logic or decisions.
It only:
  1. Receives a tool name + arguments from the agent
  2. Calls the appropriate function
  3. Returns a structured result dict back to the agent

All decisions (retries, state transitions, what to ask next) belong to the
agent via the LLM. Python here is just a function-call bridge.

Session state
─────────────
A SessionState object is passed through so tool_executor can read sensitive
account data (for verify_identity) without ever exposing it to the LLM.
The LLM receives only the tool result (verified: true/false), never the
raw account fields.
"""

import json
from dataclasses import dataclass
from typing import Any, Dict, Optional

from tools import APIError, lookup_account as _lookup_account, process_payment as _process_payment
from validators import (
    validate_card_number as _validate_card_number,
    validate_cvv as _validate_cvv,
    validate_expiry as _validate_expiry,
    validate_amount as _validate_amount,
)
from verification import verify_identity as _verify_identity


# ─── Session State ────────────────────────────────────────────────────────────

@dataclass
class SessionState:
    """
    Holds the only Python-managed data: sensitive account fields that must
    never be sent to the LLM, and session-level flags.
    """
    account_data: Optional[Dict[str, Any]] = None   # SENSITIVE — never sent to LLM
    is_locked: bool = False
    is_complete: bool = False


# ─── Executor ────────────────────────────────────────────────────────────────

class ToolExecutor:
    """
    Thin dispatch layer between Ollama tool calls and actual implementations.
    """

    def __init__(self, session: SessionState):
        self._session = session

    def execute(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        """
        Execute a named tool with the given arguments.
        Returns a JSON string that gets injected as a tool result message.
        """
        handlers = {
            "lookup_account":       self._lookup_account,
            "verify_identity":      self._verify_identity,
            "process_payment":      self._process_payment,
            "validate_card_number": self._validate_card_number,
            "validate_cvv":         self._validate_cvv,
            "validate_expiry":      self._validate_expiry,
            "validate_amount":      self._validate_amount,
            "lock_session":         self._lock_session,
            "complete_session":     self._complete_session,
        }

        handler = handlers.get(tool_name)
        if not handler:
            return json.dumps({"error": f"Unknown tool: {tool_name}"})

        try:
            return handler(arguments)
        except Exception as exc:
            return json.dumps({"error": f"Tool execution error: {exc}"})

    # ── Account ──────────────────────────────────────────────────────────────

    def _lookup_account(self, args: Dict) -> str:
        account_id = args.get("account_id")
        if not account_id:
            return json.dumps({"success": False, "error": "No account ID provided."})
        account_id = str(account_id).strip().upper()
        try:
            data = _lookup_account(account_id)
        except APIError as e:
            return json.dumps({
                "success": False,
                "error_code": e.error_code,
                "status_code": e.status_code,
                "message": str(e),
            })

        # Store sensitive data locally — never returned to LLM
        self._session.account_data = data

        # Return only non-sensitive fields to the agent
        return json.dumps({
            "success": True,
            "account_id": data.get("account_id"),
            # "account_holder": data.get("full_name", "on file"),
            "balance": data.get("balance"),
            "status": data.get("status", "active"),
        })

    # ── Identity ─────────────────────────────────────────────────────────────

    def _verify_identity(self, args: Dict) -> str:
        if not self._session.account_data:
            return json.dumps({
                "verified": False,
                "error": "No account loaded. Call lookup_account first.",
            })

        # Debug — remove once verify_identity returns correct results
        print(f"[DEBUG verify] stored full_name  : {repr(self._session.account_data.get('full_name'))}")
        print(f"[DEBUG verify] provided_name     : {repr(args.get('provided_name'))}")
        print(f"[DEBUG verify] name match         : {self._session.account_data.get('full_name') == args.get('provided_name')}")
        print(f"[DEBUG verify] secondary_type     : {repr(args.get('secondary_type'))}")
        print(f"[DEBUG verify] secondary_value    : {repr(args.get('secondary_value'))}")
        print(f"[DEBUG verify] stored dob         : {repr(self._session.account_data.get('dob'))}")
        print(f"[DEBUG verify] dob match          : {self._session.account_data.get('dob') == args.get('secondary_value')}")

        if not args.get("provided_name") or not args.get("secondary_value"):
            return json.dumps({
                "verified": False,
                "error": "Missing required fields. Provide both full name and secondary factor.",
            })

        verified = _verify_identity(
            self._session.account_data,
            args["provided_name"],
            args["secondary_type"],
            args["secondary_value"],
        )
        return json.dumps({"verified": verified})

    # ── Payment ───────────────────────────────────────────────────────────────

    def _process_payment(self, args: Dict) -> str:
        payment_method = {
            "type": "card",
            "card": {
                "cardholder_name": args["cardholder_name"],
                "card_number": args["card_number"],
                "cvv": args["cvv"],
                "expiry_month": int(args["expiry_month"]),
                "expiry_year": int(args["expiry_year"]),
            },
        }
        try:
            result = _process_payment(
                args["account_id"],
                float(args["amount"]),
                payment_method,
            )
        except APIError as e:
            return json.dumps({
                "success": False,
                "error_code": e.error_code,
                "message": str(e),
            })

        return json.dumps(result)

    # ── Validation ────────────────────────────────────────────────────────────

    def _validate_card_number(self, args: Dict) -> str:
        ok, result = _validate_card_number(args["card_number"])
        if ok:
            return json.dumps({"valid": True, "cleaned": result})
        return json.dumps({"valid": False, "error": result})

    def _validate_cvv(self, args: Dict) -> str:
        ok, result = _validate_cvv(args["cvv"], args.get("card_number", ""))
        if ok:
            return json.dumps({"valid": True, "cleaned": result})
        return json.dumps({"valid": False, "error": result})

    def _validate_expiry(self, args: Dict) -> str:
        ok, result = _validate_expiry(args["expiry_month"], args["expiry_year"])
        if ok:
            m, y = result
            return json.dumps({"valid": True, "month": m, "year": y})
        return json.dumps({"valid": False, "error": result})

    def _validate_amount(self, args: Dict) -> str:
        # Fall back to session balance if model omits it (happens after history trim)
        if "balance" not in args or args["balance"] is None:
            if self._session.account_data:
                balance = float(self._session.account_data.get("balance", 0))
            else:
                return json.dumps({"valid": False, "error": "No account loaded."})
        else:
            balance = float(args["balance"])

        ok, result = _validate_amount(args["amount_str"], balance)
        if ok:
            return json.dumps({"valid": True, "amount": float(result)})
        return json.dumps({"valid": False, "error": result})

    # ── Session Control ───────────────────────────────────────────────────────

    def _lock_session(self, args: Dict) -> str:
        self._session.is_locked = True
        return json.dumps({"locked": True, "reason": args.get("reason", "")})

    def _complete_session(self, args: Dict) -> str:
        self._session.is_complete = True
        return json.dumps({"complete": True, "reason": args.get("reason", "")})
