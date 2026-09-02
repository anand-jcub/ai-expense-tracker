"""Chat loop: local intent, then Gemini tools, confirm-before-write."""

from __future__ import annotations

import re
from typing import Any

from expense_tracker.db import connect

from . import pending as pending_store
from .local_intent import try_local
from .provider import generate, has_key
from .tools import execute_pending, gemini_declarations, run_tool

SYSTEM = """You are a concise, accurate personal finance assistant for this user's local expense tracker.
Currency is Indian rupees. Always write ₹ or INR, never $.

TRANSACTION DIRECTIONS (CRITICAL):
- **Debits / you_sent / sent**: Money the user paid OUT or sent to a person/merchant.
- **Credits / they_sent / received**: Money deposited IN or sent to the user by a person/merchant.
- NEVER describe debits as money received or credits as money sent.

TOOL USAGE:
1. Use list_pending_reviews when user asks "what needs review", "review statement", "review transactions", "review uncategorized", or asks to review for a specific date range/period.
   - Pass start_date and end_date if specified (e.g. "Review pending transactions from 2026-08-01 to 2026-08-31").
   - For pending items, call propose_categorize_transaction with the suggested or requested category to generate interactive confirmation cards for the user.
2. Use propose_edit_classification when user wants to change, fix, or recategorize an existing or auto-classified transaction:
   - "change yesterday's Swiggy to Dining out" -> query='Swiggy', new_category='Dining out'
   - "make the Shell on Aug 19 Shared with Highnes" -> query='Shell', date='2026-08-19', new_expense_type='Shared', shared_with='Highnes'
   - "remember this for Uber" -> learn=True
3. Use find_person_transactions for ANY transfer/payment questions involving a person/contact:
   - "how much did Highnes send me" -> direction='received'
   - "when did I send/pay Highnes 50k" -> direction='sent', exact_amount=50000
   - "transfers with Highnes on July" -> direction='both', start_date='2026-07-01', end_date='2026-07-31'
4. Use ask_books or search_transactions for category spending, merchant searches, auto-debits, loans, EMIs:
   - "loans I paid in July" -> text='loan', start_date='2026-07-01', end_date='2026-07-31'
   - "auto debits in July" -> text='auto', start_date='2026-07-01', end_date='2026-07-31'
   - "debits by clix and branch" -> text='clix' or 'branch'
   - "business transactions" or "business category" -> search specifically for category='Business' or text='Business' with exclude_business=False.
5. Use get_balance_for_person for a single net khata balance (who owes whom).
6. propose_add_manual, propose_categorize_transaction, and propose_edit_classification only propose — user must confirm. Never invent numbers.
7. Use Recent conversation for follow-ups. After tools, reply in 1-3 short, accurate sentences or bullet points."""



def run_chat(db_path, username: str, message: str, history: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    text = (message or "").strip()
    if not text:
        return {"reply": "Ask about a person, this month’s spend, or add an amount.", "cards": [], "source": "empty"}

    with connect(db_path) as conn:
        # If a Gemini key exists, always use Gemini — it handles natural language
        # better than rigid local rules, and local rules were meant only as a
        # no-key fallback, not as a gatekeeper.
        if has_key(username):
            try:
                return _gemini_round(conn, username, text, history or [])
            except Exception as exc:
                msg = str(exc)
                if "thought_signature" in msg.lower() or "HTTP 400" in msg:
                    try:
                        return _gemini_round(conn, username, text, [])
                    except Exception as exc2:
                        exc = exc2
                logger = __import__("logging").getLogger(__name__)
                logger.exception("Gemini ask failed")
                detail = str(exc).strip().split("\n")[0][:180]
                # Gemini failed — fall back to local rules so the user still gets
                # something useful rather than a bare error.
                local = try_local(conn, username, stitch_followup(text, history or []))
                if local:
                    local.setdefault("model", "local-fallback")
                    local["gemini_error"] = detail or str(exc)[:200]
                    return local
                return {
                    "reply": (
                        f"Gemini failed ({detail}). Person-balance and this-month spend questions still work."
                        if detail
                        else "Gemini failed. Person-balance and this-month spend questions still work."
                    ),
                    "cards": [],
                    "source": "gemini-error",
                    "error": str(exc)[:200],
                    "model": "gemini",
                }

        # No Gemini key — use local rules, with a helpful prompt to set one up.
        local = try_local(conn, username, stitch_followup(text, history or []))
        if local:
            local.setdefault("model", "local")
            return local
        return {
            "reply": (
                "Save a Gemini API key under More on the desktop app to enable full Ask. "
                "I can still answer “how much does X owe me?” and “what did I spend on food this month.”"
            ),
            "cards": [],
            "source": "local-missing-key",
            "model": "local",
        }


def confirm_action(db_path, username: str, token: str) -> dict[str, Any]:
    item = pending_store.take((token or "").strip(), username)
    if not item:
        return {"ok": False, "error": "Confirmation expired or already used."}
    with connect(db_path) as conn:
        result = execute_pending(conn, username, item)
    if result.get("ok"):
        result["reply"] = "Saved."
        from expense_tracker.cloud_sync import trigger_cloud_sync_bg

        trigger_cloud_sync_bg(username)
    return result


_FOLLOW = re.compile(
    r"^(and |what about|how about|also |last (month|week)|that|those|the same)\b",
    re.I,
)


def stitch_followup(message: str, history: list[dict[str, Any]]) -> str:
    text = (message or "").strip()
    short = len(text.split()) <= 4
    if not text or (not _FOLLOW.match(text) and not short):
        return text
    prev = ""
    for turn in reversed(history or []):
        role = str(turn.get("role") or "")
        if role in {"user", "User"}:
            prev = str(turn.get("text") or "").strip()
            if prev:
                break
    if not prev or prev == text:
        return text
    return f"{prev} — {text}"


def format_thread(history: list[dict[str, Any]], current: str) -> str:
    lines: list[str] = []
    for turn in (history or [])[-6:]:
        role = "User" if str(turn.get("role") or "") in {"user", "User"} else "Assistant"
        part = str(turn.get("text") or "").strip()
        if part:
            lines.append(f"{role}: {part[:400]}")
    blob = "\n".join(lines)
    if len(blob) > 3500:
        blob = blob[-3500:]
    if not blob:
        return current
    return f"Recent conversation:\n{blob}\n\nCurrent question: {current}"


def _gemini_round(conn, username: str, message: str, history: list[dict[str, Any]]) -> dict[str, Any]:
    # Plain-text thread only. Native Gemini functionCall history 400s (thought_signature).
    contents: list[dict[str, Any]] = [
        {"role": "user", "parts": [{"text": format_thread(history, message)}]}
    ]

    cards: list[dict[str, Any]] = []
    last_text = ""
    last_tool_summaries: list[str] = []
    used_model = ""
    for _ in range(4):
        try:
            result = generate(contents, gemini_declarations(), SYSTEM, username=username)
        except Exception as exc:
            if last_tool_summaries:
                return {
                    "reply": " ".join(last_tool_summaries)[:500],
                    "cards": cards,
                    "source": "tools-after-gemini-error",
                    "error": str(exc)[:200],
                    "model": used_model or "gemini",
                }
            raise
        used_model = result.get("model") or used_model
        calls = result.get("function_calls") or []
        last_text = result.get("text") or last_text
        if not calls:
            break
        user_parts = []
        new_summaries: list[str] = []
        for part in calls:
            fc = part.get("functionCall") or part
            name = fc.get("name") or ""
            args = fc.get("args") or {}
            if not isinstance(args, dict):
                args = {}
            tool_out = run_tool(conn, username, name, args)
            if tool_out.get("needs_confirm"):
                cards.append(
                    {
                        "type": "confirmation",
                        "title": tool_out.get("title") or "Confirm",
                        "message": tool_out.get("message") or "",
                        "confirm_token": tool_out.get("confirm_token"),
                        "preview": tool_out.get("preview"),
                    }
                )
            if tool_out.get("answer"):
                new_summaries.append(str(tool_out["answer"]))
            elif tool_out.get("message"):
                new_summaries.append(str(tool_out["message"]))
            user_parts.append(
                {
                    "functionResponse": {
                        "name": name,
                        "response": tool_out,
                    }
                }
            )
        # Replay Gemini parts unchanged so thought_signature stays on functionCall.
        if new_summaries:
            last_tool_summaries = new_summaries
        contents.append({"role": "model", "parts": result.get("raw_parts") or calls})
        contents.append({"role": "user", "parts": user_parts})

    if not last_text:
        if cards:
            last_text = cards[0].get("message") or "Confirm this change?"
        elif last_tool_summaries:
            last_text = " ".join(last_tool_summaries)[:500]
        else:
            last_text = last_tool_summaries[0] if last_tool_summaries else "I could not complete that. Try a shorter question."
    return {
        "reply": last_text,
        "cards": cards,
        "source": "gemini",
        "model": used_model or "gemini",
    }
