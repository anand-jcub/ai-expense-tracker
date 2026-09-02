"""Gemini generateContent + function calling. Key stays on the server."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

MODEL_CHAIN = (
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-3.6-flash",
)
DEFAULT_MODEL = MODEL_CHAIN[0]
API_ROOT = "https://generativelanguage.googleapis.com/v1beta/models"

_last_good: str | None = None
_exhausted: set[str] = set()


def api_key(username: str | None = None) -> str:
    if username:
        try:
            from expense_tracker.auth import get_gemini_api_key

            saved = (get_gemini_api_key(username) or "").strip()
            if saved:
                return saved
        except Exception:
            pass
    return (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or "").strip()


def has_key(username: str | None = None) -> bool:
    return bool(api_key(username))


def live_model(name: str | None) -> str:
    n = (name or "").strip()
    if n in MODEL_CHAIN:
        return n
    if not n or "gemini-1.5" in n or "gemini-2.0" in n:
        return DEFAULT_MODEL
    return n


def _is_failover(exc: BaseException) -> bool:
    s = str(exc).lower()
    return any(
        token in s
        for token in (
            "429",
            "resource_exhausted",
            "quota",
            "rate limit",
            "404",
            "no longer available",
            "not found",
            "503",
            "unavailable",
            "overloaded",
            "timed out",
            "timeout",
            "400",
            "invalid argument",
            "thought_signature",
        )
    )


def _model_order(preferred: str | None) -> list[str]:
    chain = list(MODEL_CHAIN)
    start = _last_good if _last_good in chain else None
    if preferred and preferred in chain:
        start = preferred
    if start:
        i = chain.index(start)
        chain = chain[i:] + chain[:i]
    return [m for m in chain if m not in _exhausted] or list(MODEL_CHAIN)


def generate(
    contents: list[dict[str, Any]],
    declarations: list[dict[str, Any]],
    system: str,
    model: str | None = None,
    username: str | None = None,
) -> dict[str, Any]:
    global _last_good
    key = api_key(username)
    if not key:
        raise RuntimeError("GEMINI_API_KEY is not set")
    preferred = live_model(model or os.environ.get("GEMINI_MODEL"))
    last_err: Exception | None = None
    for name in _model_order(preferred):
        for with_thinking in (True, False):
            try:
                result = _call(name, key, contents, declarations, system, with_thinking)
                _last_good = name
                _exhausted.discard(name)
                result["model"] = name
                return result
            except Exception as exc:
                last_err = exc
                if with_thinking:
                    continue
                if _is_failover(exc):
                    _exhausted.add(name)
                    break
                raise
    raise last_err or RuntimeError("Gemini request failed")


def _payload(
    contents: list[dict[str, Any]],
    declarations: list[dict[str, Any]],
    system: str,
    with_thinking: bool,
) -> dict[str, Any]:
    gen: dict[str, Any] = {
        "temperature": 0.2,
        "maxOutputTokens": 1024,
    }
    if with_thinking:
        gen["thinkingConfig"] = {"thinkingBudget": 0}
    return {
        "system_instruction": {"parts": [{"text": system}]},
        "contents": contents,
        "tools": [{"function_declarations": declarations}],
        "generationConfig": gen,
    }


def _parse(raw: str, model: str) -> dict[str, Any]:
    data = json.loads(raw)
    if data.get("error"):
        err = data["error"]
        raise RuntimeError(f"Gemini HTTP {err.get('code')}: {err.get('message')}")
    cand = (data.get("candidates") or [{}])[0]
    parts = ((cand.get("content") or {}).get("parts")) or []
    calls = []
    texts = []
    for part in parts:
        if not isinstance(part, dict):
            continue
        if part.get("functionCall"):
            calls.append(part)
        elif isinstance(part.get("text"), str) and part["text"].strip():
            texts.append(part["text"].strip())
    return {
        "model": model,
        "function_calls": calls,
        "raw_parts": parts,
        "text": "\n".join(texts).strip(),
        "finish_reason": cand.get("finishReason"),
    }


def _call(
    model: str,
    key: str,
    contents: list[dict[str, Any]],
    declarations: list[dict[str, Any]],
    system: str,
    with_thinking: bool,
) -> dict[str, Any]:
    body = _payload(contents, declarations, system, with_thinking)
    curl = shutil.which("curl.exe") or shutil.which("curl")
    if curl:
        return _parse(_curl_post(curl, model, key, body), model)
    return _parse(_urllib_post(model, key, body), model)


def _curl_post(curl: str, model: str, key: str, body: dict[str, Any]) -> str:
    url = f"{API_ROOT}/{urllib.parse.quote(model, safe='')}:generateContent"
    tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
    try:
        json.dump(body, tmp)
        tmp.close()
        kwargs: dict[str, Any] = {
            "capture_output": True,
            "text": True,
            "encoding": "utf-8",
            "errors": "replace",
            "timeout": 22,
        }
        if os.name == "nt":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        result = subprocess.run(
            [
                curl,
                "-sS",
                "--max-time",
                "20",
                "-H",
                "Content-Type: application/json",
                "-H",
                f"x-goog-api-key: {key}",
                "--data-binary",
                f"@{tmp.name}",
                url,
            ],
            **kwargs,
        )
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass
    if result.returncode != 0:
        err = (result.stderr or result.stdout or "curl failed").strip()[:300]
        raise RuntimeError(f"Gemini curl failed: {err}")
    return result.stdout or "{}"


def _urllib_post(model: str, key: str, body: dict[str, Any]) -> str:
    url = f"{API_ROOT}/{model}:generateContent"
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": key,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:400]
        raise RuntimeError(f"Gemini HTTP {exc.code}: {detail}") from exc
