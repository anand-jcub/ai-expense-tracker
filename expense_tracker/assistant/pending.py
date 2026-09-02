"""Single-use confirmation tokens for money writes (FC-08)."""

from __future__ import annotations

import secrets
import threading
import time
from typing import Any

_LOCK = threading.Lock()
_PENDING: dict[str, dict[str, Any]] = {}
_TTL_SEC = 10 * 60


def issue(username: str, action: str, payload: dict[str, Any]) -> str:
    token = secrets.token_urlsafe(18)
    with _LOCK:
        _PENDING[token] = {
            "username": username,
            "action": action,
            "payload": payload,
            "expires": time.time() + _TTL_SEC,
        }
    return token


def take(token: str, username: str) -> dict[str, Any] | None:
    """Pop a token if it belongs to username and is unexpired."""
    now = time.time()
    with _LOCK:
        _expire_unlocked(now)
        item = _PENDING.pop(token, None)
    if not item:
        return None
    if item.get("username") != username:
        return None
    return item


def peek(token: str, username: str) -> dict[str, Any] | None:
    now = time.time()
    with _LOCK:
        _expire_unlocked(now)
        item = _PENDING.get(token)
    if not item or item.get("username") != username:
        return None
    return item


def _expire_unlocked(now: float) -> None:
    dead = [k for k, v in _PENDING.items() if float(v.get("expires") or 0) < now]
    for k in dead:
        _PENDING.pop(k, None)
