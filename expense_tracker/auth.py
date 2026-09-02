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


def _resolve_data_dir() -> Path:
    raw = (os.environ.get("DATA_DIR") or "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return (APP_ROOT / "data").resolve()


DATA_DIR = _resolve_data_dir()
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

            CREATE TABLE IF NOT EXISTS api_tokens (
                token_id TEXT PRIMARY KEY,
                token_hash TEXT NOT NULL UNIQUE,
                username TEXT NOT NULL,
                label TEXT,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                revoked_at TEXT,
                FOREIGN KEY (username) REFERENCES users(username) ON DELETE CASCADE
            );
            """
        )
        conn.commit()
        _ensure_statement_password_column(conn)
    finally:
        conn.close()


def _ensure_statement_password_column(conn: sqlite3.Connection) -> None:
    cols = {row[1] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
    changed = False
    if "statement_pdf_password" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN statement_pdf_password TEXT")
        changed = True
    if "gmail_address" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN gmail_address TEXT")
        changed = True
    if "gmail_app_password" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN gmail_app_password TEXT")
        changed = True
    if "gemini_api_key" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN gemini_api_key TEXT")
        changed = True
    if changed:
        conn.commit()


def get_statement_password(username: str) -> str | None:
    """PDF unlock password saved in the tool for this user (not the login password)."""
    username = (username or "").strip().lower()
    if not username:
        return None
    init_auth_db()
    conn = get_auth_connection()
    try:
        _ensure_statement_password_column(conn)
        row = conn.execute(
            "SELECT statement_pdf_password FROM users WHERE LOWER(username) = ?",
            (username,),
        ).fetchone()
        if not row:
            return None
        pw = (row["statement_pdf_password"] or "").strip()
        return pw or None
    finally:
        conn.close()


def set_statement_password(username: str, password: str) -> None:
    """Remember the statement PDF password after a successful unlock."""
    username = (username or "").strip().lower()
    password = (password or "").strip()
    if not username or not password:
        return
    init_auth_db()
    conn = get_auth_connection()
    try:
        _ensure_statement_password_column(conn)
        conn.execute(
            "UPDATE users SET statement_pdf_password = ? WHERE LOWER(username) = ?",
            (password, username),
        )
        conn.commit()
    finally:
        conn.close()


def get_gmail_imap(username: str) -> tuple[str | None, str | None]:
    username = (username or "").strip().lower()
    if not username:
        return None, None
    init_auth_db()
    conn = get_auth_connection()
    try:
        _ensure_statement_password_column(conn)
        row = conn.execute(
            "SELECT gmail_address, gmail_app_password FROM users WHERE LOWER(username) = ?",
            (username,),
        ).fetchone()
        if not row:
            return None, None
        addr = (row["gmail_address"] or "").strip()
        pw = (row["gmail_app_password"] or "").strip()
        return (addr or None, pw or None)
    finally:
        conn.close()


def set_gmail_imap(username: str, address: str, app_password: str) -> None:
    username = (username or "").strip().lower()
    address = (address or "").strip()
    app_password = (app_password or "").strip().replace(" ", "")
    if not username or not address or not app_password:
        return
    init_auth_db()
    conn = get_auth_connection()
    try:
        _ensure_statement_password_column(conn)
        conn.execute(
            "UPDATE users SET gmail_address = ?, gmail_app_password = ? WHERE LOWER(username) = ?",
            (address, app_password, username),
        )
        conn.commit()
    finally:
        conn.close()


def get_gemini_api_key(username: str) -> str | None:
    """Per-user Gemini key saved in the desktop app. Never log this."""
    username = (username or "").strip().lower()
    if not username:
        return None
    init_auth_db()
    conn = get_auth_connection()
    try:
        _ensure_statement_password_column(conn)
        row = conn.execute(
            "SELECT gemini_api_key FROM users WHERE LOWER(username) = ?",
            (username,),
        ).fetchone()
        if not row:
            return None
        key = (row["gemini_api_key"] or "").strip()
        return key or None
    finally:
        conn.close()


def set_gemini_api_key(username: str, api_key: str) -> None:
    username = (username or "").strip().lower()
    api_key = (api_key or "").strip()
    if not username:
        return
    init_auth_db()
    conn = get_auth_connection()
    try:
        _ensure_statement_password_column(conn)
        conn.execute(
            "UPDATE users SET gemini_api_key = ? WHERE LOWER(username) = ?",
            (api_key or None, username),
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


def _hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def create_api_token(
    username: str,
    password: str,
    *,
    label: str | None = None,
    days_valid: int = 90,
) -> tuple[str | None, str]:
    """Create a long-lived API token for MCP / mobile. Returns (token, message).

    The raw token is shown once; only a SHA-256 hash is stored.
    """
    username = username.strip().lower()
    init_auth_db()
    conn = get_auth_connection()
    try:
        row = conn.execute(
            "SELECT password_hash FROM users WHERE LOWER(username) = ?",
            (username,),
        ).fetchone()
        if not row or not verify_password(row["password_hash"], password):
            return None, "Invalid username or password."

        raw = "exp_" + uuid.uuid4().hex + uuid.uuid4().hex[:16]
        token_id = uuid.uuid4().hex
        now = utc_now()
        expires = now + timedelta(days=max(1, int(days_valid)))
        conn.execute(
            """
            INSERT INTO api_tokens (token_id, token_hash, username, label, created_at, expires_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                token_id,
                _hash_token(raw),
                username,
                (label or "api").strip()[:80],
                format_iso(now),
                format_iso(expires),
            ),
        )
        conn.commit()
        return raw, "Token created."
    except Exception as exc:
        logger.exception("Error creating API token")
        return None, f"Failed to create token: {exc}"
    finally:
        conn.close()


def issue_local_api_token(username: str, *, label: str = "cloud-hub", days_valid: int = 365) -> str | None:
    """Mint a Bearer token on this machine (no password). For cloud_sync only."""
    username = (username or "").strip().lower()
    if not username:
        return None
    init_auth_db()
    conn = get_auth_connection()
    try:
        row = conn.execute(
            "SELECT username FROM users WHERE LOWER(username) = ?",
            (username,),
        ).fetchone()
        if not row:
            return None
        raw = "exp_" + uuid.uuid4().hex + uuid.uuid4().hex[:16]
        now = utc_now()
        conn.execute(
            """
            INSERT INTO api_tokens (token_id, token_hash, username, label, created_at, expires_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                uuid.uuid4().hex,
                _hash_token(raw),
                username,
                (label or "cloud-hub").strip()[:80],
                format_iso(now),
                format_iso(now + timedelta(days=max(1, int(days_valid)))),
            ),
        )
        conn.commit()
        return raw
    except Exception:
        logger.exception("issue_local_api_token failed")
        return None
    finally:
        conn.close()


def verify_api_token(raw_token: str | None) -> str | None:
    """Return username if Bearer token is valid and not revoked/expired."""
    if not raw_token:
        return None
    raw_token = raw_token.strip()
    if not raw_token:
        return None
    init_auth_db()
    th = _hash_token(raw_token)
    conn = get_auth_connection()
    try:
        row = conn.execute(
            """
            SELECT username, expires_at, revoked_at
            FROM api_tokens
            WHERE token_hash = ?
            """,
            (th,),
        ).fetchone()
        if not row:
            return None
        if row["revoked_at"]:
            return None
        expires_at = parse_iso(row["expires_at"])
        if utc_now() > expires_at:
            return None
        return row["username"]
    except Exception:
        logger.exception("Error verifying API token")
        return None
    finally:
        conn.close()


def revoke_api_token(username: str, raw_token: str) -> bool:
    """Revoke a token owned by username. Returns True if a row was updated."""
    username = username.strip().lower()
    init_auth_db()
    th = _hash_token(raw_token.strip())
    conn = get_auth_connection()
    try:
        cur = conn.execute(
            """
            UPDATE api_tokens
            SET revoked_at = ?
            WHERE token_hash = ? AND LOWER(username) = ? AND revoked_at IS NULL
            """,
            (format_iso(utc_now()), th, username),
        )
        conn.commit()
        return cur.rowcount > 0
    except Exception:
        logger.exception("Error revoking API token")
        return False
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
