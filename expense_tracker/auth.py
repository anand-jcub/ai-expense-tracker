"""User registration, authentication, and session management using a local SQLite database."""

from __future__ import annotations

import hashlib
import logging
import os
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

APP_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = APP_ROOT / "data"
USERS_DB_PATH = DATA_DIR / "users.db"

def utc_now() -> datetime:
    return datetime.now(timezone.utc)

def format_iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")

def parse_iso(dt_str: str) -> datetime:
    if dt_str.endswith("Z"):
        dt_str = dt_str[:-1] + "+00:00"
    return datetime.fromisoformat(dt_str)

def get_auth_connection() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(USERS_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("pragma foreign_keys = on")
    return conn

def init_auth_db() -> None:
    conn = get_auth_connection()
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                username TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                FOREIGN KEY (username) REFERENCES users(username) ON DELETE CASCADE
            );
            """
        )
        conn.commit()
    finally:
        conn.close()

def hash_password(password: str) -> str:
    """Hash password using PBKDF2 with SHA-256 and a random salt."""
    salt = os.urandom(16)
    key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100000)
    return salt.hex() + ":" + key.hex()

def verify_password(stored: str, password: str) -> bool:
    """Verify a password against its stored PBKDF2 hash."""
    try:
        salt_hex, key_hex = stored.split(":")
        salt = bytes.fromhex(salt_hex)
        key = bytes.fromhex(key_hex)
        new_key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100000)
        return new_key == key
    except Exception as exc:
        logger.error("Error verifying password hash: %s", exc)
        return False

def register_user(username: str, password: str) -> tuple[bool, str]:
    """Register a new user. Returns (success, message)."""
    username = username.strip().lower()
    if not username:
        return False, "Username cannot be empty."
    if len(username) < 3:
        return False, "Username must be at least 3 characters."
    if not password or len(password) < 6:
        return False, "Password must be at least 6 characters."

    init_auth_db()
    hashed = hash_password(password)
    now_str = format_iso(utc_now())

    conn = get_auth_connection()
    try:
        conn.execute(
            "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
            (username, hashed, now_str),
        )
        conn.commit()
        return True, "User registered successfully."
    except sqlite3.IntegrityError:
        return False, "Username already exists."
    except Exception as exc:
        logger.exception("Error during user registration")
        return False, f"Unexpected database error: {exc}"
    finally:
        conn.close()

def authenticate_user(username: str, password: str) -> str | None:
    """Authenticate user and return a session ID if successful, or None."""
    username = username.strip().lower()
    init_auth_db()

    conn = get_auth_connection()
    try:
        row = conn.execute(
            "SELECT password_hash FROM users WHERE LOWER(username) = ?",
            (username,),
        ).fetchone()
        if not row:
            return None

        if not verify_password(row["password_hash"], password):
            return None

        # Create session
        session_id = uuid.uuid4().hex
        expires_at = utc_now() + timedelta(days=30)
        expires_str = format_iso(expires_at)

        conn.execute(
            "INSERT INTO sessions (session_id, username, expires_at) VALUES (?, ?, ?)",
            (session_id, username, expires_str),
        )
        conn.commit()
        return session_id
    except Exception as exc:
        logger.exception("Error during authentication")
        return None
    finally:
        conn.close()

def verify_session(session_id: str | None) -> str | None:
    """Verify session ID and return username if valid, or None."""
    if not session_id:
        return None
    init_auth_db()

    conn = get_auth_connection()
    try:
        row = conn.execute(
            "SELECT username, expires_at FROM sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        if not row:
            return None

        expires_at = parse_iso(row["expires_at"])
        if utc_now() > expires_at:
            # Session expired, clean it up
            conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
            conn.commit()
            return None

        return row["username"]
    except Exception as exc:
        logger.exception("Error verifying session")
        return None
    finally:
        conn.close()

def delete_session(session_id: str | None) -> None:
    """Delete session ID on logout."""
    if not session_id:
        return
    init_auth_db()
    conn = get_auth_connection()
    try:
        conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
        conn.commit()
    except Exception as exc:
        logger.exception("Error deleting session")
    finally:
        conn.close()


def get_all_usernames() -> list[str]:
    """Retrieve list of all registered usernames, ordered alphabetically."""
    init_auth_db()
    conn = get_auth_connection()
    try:
        rows = conn.execute("SELECT username FROM users ORDER BY username ASC").fetchall()
        return [row["username"] for row in rows]
    except Exception as exc:
        logger.error("Error retrieving registered usernames: %s", exc)
        return []
    finally:
        conn.close()
