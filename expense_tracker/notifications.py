"""PWA Web Push notifications service.

Manages VAPID keys, push subscriptions in users.db, and dispatches
standards-based Web Push notifications when statement review is required.
"""

from __future__ import annotations

import base64
import json
import logging
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from py_vapid import Vapid
from pywebpush import WebPushException, webpush

from .auth import DATA_DIR, get_auth_connection

logger = logging.getLogger(__name__)

VAPID_PRIVATE_PATH = DATA_DIR / "vapid_private.pem"
DEFAULT_VAPID_CLAIMS_SUB = "mailto:admin@expense-tracker.local"

_lock = threading.Lock()
_cached_vapid: Vapid | None = None


def init_notifications_db(conn: sqlite3.Connection | None = None) -> None:
    """Ensure the push_subscriptions table exists in users.db."""
    should_close = False
    if conn is None:
        conn = get_auth_connection()
        should_close = True
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS push_subscriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                endpoint TEXT UNIQUE NOT NULL,
                p256dh TEXT NOT NULL,
                auth TEXT NOT NULL,
                user_agent TEXT,
                created_at TEXT NOT NULL,
                last_used_at TEXT,
                FOREIGN KEY (username) REFERENCES users(username) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_push_subs_user ON push_subscriptions(username);
            """
        )
        conn.commit()
    finally:
        if should_close:
            conn.close()


def get_or_create_vapid() -> Vapid:
    """Load or generate persistent VAPID keys."""
    global _cached_vapid
    with _lock:
        if _cached_vapid is not None:
            return _cached_vapid

        DATA_DIR.mkdir(parents=True, exist_ok=True)
        if VAPID_PRIVATE_PATH.is_file():
            try:
                v = Vapid.from_file(str(VAPID_PRIVATE_PATH))
                _cached_vapid = v
                return v
            except Exception:
                logger.warning("Failed to load existing VAPID key; generating a fresh one.")

        v = Vapid()
        v.generate_keys()
        v.save_key(str(VAPID_PRIVATE_PATH))
        _cached_vapid = v
        return v


def get_vapid_public_key() -> str:
    """Return URL-safe base64 uncompressed point (65 bytes) for PushManager applicationServerKey."""
    v = get_or_create_vapid()
    raw_pub = v.public_key.public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
    return base64.urlsafe_b64encode(raw_pub).decode("utf-8").rstrip("=")


def save_subscription(username: str, sub_dict: dict[str, Any], user_agent: str = "") -> dict[str, Any]:
    """Store or update a push subscription for username."""
    username = (username or "").strip().lower()
    if not username:
        raise ValueError("username required")

    endpoint = (sub_dict.get("endpoint") or "").strip()
    keys = sub_dict.get("keys") or {}
    p256dh = (keys.get("p256dh") or "").strip()
    auth = (keys.get("auth") or "").strip()

    if not endpoint or not p256dh or not auth:
        raise ValueError("Invalid subscription: endpoint, keys.p256dh, and keys.auth are required")

    init_notifications_db()
    conn = get_auth_connection()
    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        conn.execute(
            """
            INSERT INTO push_subscriptions (username, endpoint, p256dh, auth, user_agent, created_at, last_used_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(endpoint) DO UPDATE SET
                username = excluded.username,
                p256dh = excluded.p256dh,
                auth = excluded.auth,
                user_agent = excluded.user_agent,
                last_used_at = excluded.last_used_at
            """,
            (username, endpoint, p256dh, auth, user_agent or "", now_iso, now_iso),
        )
        conn.commit()
        return {"ok": True, "endpoint": endpoint}
    finally:
        conn.close()


def remove_subscription(endpoint: str) -> bool:
    """Remove a subscription by endpoint."""
    endpoint = (endpoint or "").strip()
    if not endpoint:
        return False
    init_notifications_db()
    conn = get_auth_connection()
    try:
        cur = conn.execute("DELETE FROM push_subscriptions WHERE endpoint = ?", (endpoint,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def get_user_subscriptions(username: str) -> list[dict[str, Any]]:
    """Retrieve all push subscriptions for a user."""
    username = (username or "").strip().lower()
    if not username:
        return []
    init_notifications_db()
    conn = get_auth_connection()
    try:
        rows = conn.execute(
            "SELECT id, username, endpoint, p256dh, auth, user_agent FROM push_subscriptions WHERE username = ?",
            (username,),
        ).fetchall()
        return [
            {
                "id": r["id"],
                "username": r["username"],
                "endpoint": r["endpoint"],
                "keys": {"p256dh": r["p256dh"], "auth": r["auth"]},
                "user_agent": r["user_agent"],
            }
            for r in rows
        ]
    finally:
        conn.close()


def send_push_to_subscription(
    sub_info: dict[str, Any],
    payload: dict[str, Any],
    vapid: Vapid | None = None,
) -> bool:
    """Send a Web Push message to a single subscription.

    Prunes subscription automatically if push service responds with 404 or 410 (Gone).
    """
    if vapid is None:
        vapid = get_or_create_vapid()

    json_payload = json.dumps(payload, ensure_ascii=False)
    endpoint = sub_info.get("endpoint", "")
    subscription_data = {
        "endpoint": endpoint,
        "keys": {
            "p256dh": sub_info.get("keys", {}).get("p256dh"),
            "auth": sub_info.get("keys", {}).get("auth"),
        },
    }

    try:
        webpush(
            subscription_info=subscription_data,
            data=json_payload,
            vapid_private_key=vapid,
            vapid_claims={"sub": DEFAULT_VAPID_CLAIMS_SUB},
            content_encoding="aes128gcm",
            ttl=86400,
            timeout=10,
        )
        return True
    except WebPushException as exc:
        status_code = getattr(exc.response, "status_code", None) if hasattr(exc, "response") else None
        if status_code in (404, 410):
            logger.info("Push subscription expired or gone (%s); removing %s", status_code, endpoint)
            remove_subscription(endpoint)
        else:
            logger.warning("WebPush failed for endpoint %s: %s", endpoint, exc)
        return False
    except Exception as exc:
        logger.warning("Unexpected error sending web push to %s: %s", endpoint, exc)
        return False


def send_push_notification_to_user(
    username: str,
    title: str,
    body: str,
    url: str = "/app/",
    tag: str = "statement-review",
    data: dict[str, Any] | None = None,
) -> int:
    """Send push notification to all devices registered for a user.

    Returns the count of successfully delivered notifications.
    """
    subs = get_user_subscriptions(username)
    if not subs:
        logger.debug("No push subscriptions for user %s", username)
        return 0

    vapid = get_or_create_vapid()
    payload = {
        "title": title,
        "body": body,
        "icon": "/app/icon-192.png",
        "badge": "/app/icon-192.png",
        "tag": tag,
        "data": {
            "url": url,
            **(data or {}),
        },
    }

    success_count = 0
    for sub in subs:
        if send_push_to_subscription(sub, payload, vapid=vapid):
            success_count += 1
    return success_count


def trigger_statement_review_notification_bg(
    username: str,
    filename: str,
    pending_count: int,
    inserted_count: int,
    start_date: str | None = None,
    end_date: str | None = None,
) -> None:
    """Non-blocking background thread to notify user that newly imported statement has pending review items."""
    if pending_count <= 0:
        return

    def _worker() -> None:
        try:
            name = filename or "statement.pdf"
            if pending_count == 1:
                body = f"1 new transaction from {name} needs your review."
            else:
                body = f"{pending_count} new transactions from {name} need your review."

            url = "/app/?screen=ask&review=1"
            data = {
                "url": url,
                "filename": name,
                "pending": pending_count,
                "inserted": inserted_count,
                "start": start_date,
                "end": end_date,
            }
            sent = send_push_notification_to_user(
                username=username,
                title="Review Required",
                body=body,
                url=url,
                tag="statement-review",
                data=data,
            )
            logger.info(
                "Dispatched statement review push to %s (%d device(s) delivered)",
                username,
                sent,
            )
        except Exception:
            logger.exception("Failed to dispatch review push notification for %s", username)

    t = threading.Thread(target=_worker, name=f"push-review-{username}", daemon=False)
    t.start()
    return t

