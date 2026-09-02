from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from expense_tracker import auth, db, web
from expense_tracker.auth import (
    authenticate_user,
    create_api_token,
    delete_session,
    hash_password,
    init_auth_db,
    register_user,
    revoke_api_token,
    verify_api_token,
    verify_password,
    verify_session,
)


class AuthTests(unittest.TestCase):
    def setUp(self) -> None:
        # Create a temporary directory for test databases
        self.test_dir = tempfile.TemporaryDirectory()
        self.test_dir_path = Path(self.test_dir.name)
        
        # Patch the USERS_DB_PATH and DATA_DIR constants to use our temporary folder
        self.patcher1 = patch("expense_tracker.auth.USERS_DB_PATH", self.test_dir_path / "test_users.db")
        self.patcher2 = patch("expense_tracker.auth.DATA_DIR", self.test_dir_path)
        self.patcher3 = patch("expense_tracker.db.DATA_DIR", self.test_dir_path)
        self.patcher4 = patch("expense_tracker.db.DB_PATH", self.test_dir_path / "test_expenses.db")
        
        self.patcher1.start()
        self.patcher2.start()
        self.patcher3.start()
        self.patcher4.start()
        
        # Reset request context database path
        if hasattr(db, "request_context") and hasattr(db.request_context, "db_path"):
            del db.request_context.db_path

    def tearDown(self) -> None:
        self.patcher1.stop()
        self.patcher2.stop()
        self.patcher3.stop()
        self.patcher4.stop()
        
        # Explicitly clear connection cache/thread context
        if hasattr(db, "request_context") and hasattr(db.request_context, "db_path"):
            del db.request_context.db_path
            
        self.test_dir.cleanup()

    def test_password_hashing(self) -> None:
        password = "secretpassword"
        hashed = hash_password(password)
        self.assertNotEqual(password, hashed)
        self.assertTrue(verify_password(hashed, password))
        self.assertFalse(verify_password(hashed, "wrongpassword"))

    def test_user_registration(self) -> None:
        # Successful registration
        success, msg = register_user("alice", "password123")
        self.assertTrue(success)
        self.assertEqual(msg, "User registered successfully.")
        
        # Duplicate registration fails
        success, msg = register_user("alice", "password456")
        self.assertFalse(success)
        self.assertEqual(msg, "Username already exists.")
        
        # Username too short
        success, msg = register_user("bo", "password")
        self.assertFalse(success)
        
        # Password too short
        success, msg = register_user("charlie", "123")
        self.assertFalse(success)

    def test_authenticate_user(self) -> None:
        register_user("bob", "bobpassword")
        
        # Invalid login
        session_id = authenticate_user("bob", "wrongpass")
        self.assertIsNone(session_id)
        
        # Valid login
        session_id = authenticate_user("bob", "bobpassword")
        self.assertIsNotNone(session_id)
        self.assertEqual(len(session_id), 32)  # UUID hex length

    def test_session_verification_and_deletion(self) -> None:
        register_user("alice", "alicepassword")
        session_id = authenticate_user("alice", "alicepassword")
        
        # Verify active session
        username = verify_session(session_id)
        self.assertEqual(username, "alice")
        
        # Verify invalid session ID
        self.assertIsNone(verify_session("invalidsessionid"))
        
        # Delete session
        delete_session(session_id)
        self.assertIsNone(verify_session(session_id))

    def test_statement_password_persist(self) -> None:
        register_user("alice", "alicepassword")
        self.assertIsNone(auth.get_statement_password("alice"))
        auth.set_statement_password("alice", "sbi-dob")
        self.assertEqual(auth.get_statement_password("alice"), "sbi-dob")
        self.assertIsNone(auth.get_statement_password("nobody"))

    def test_gemini_api_key_persist(self) -> None:
        register_user("alice", "alicepassword")
        self.assertIsNone(auth.get_gemini_api_key("alice"))
        auth.set_gemini_api_key("alice", "  AIza-test  ")
        self.assertEqual(auth.get_gemini_api_key("alice"), "AIza-test")
        from expense_tracker.assistant.provider import api_key, has_key

        self.assertTrue(has_key("alice"))
        self.assertEqual(api_key("alice"), "AIza-test")
        self.assertFalse(has_key("nobody"))

    def test_dynamic_db_connection_isolation(self) -> None:
        # Register two users
        register_user("alice", "alicepass")
        register_user("bob", "bobpass")
        
        # Connect to Alice's dynamic DB
        db.request_context.db_path = self.test_dir_path / "expenses_alice.db"
        conn_alice = db.connect()
        try:
            conn_alice.execute(
                "insert into imports (source_filename, file_sha256, imported_at) values (?, ?, ?)",
                ("alice_statement.pdf", "hash_alice", "2026-07-08T12:00:00Z")
            )
            conn_alice.commit()
        finally:
            conn_alice.close()
            
        # Connect to Bob's dynamic DB
        db.request_context.db_path = self.test_dir_path / "expenses_bob.db"
        conn_bob = db.connect()
        try:
            conn_bob.execute(
                "insert into imports (source_filename, file_sha256, imported_at) values (?, ?, ?)",
                ("bob_statement.pdf", "hash_bob", "2026-07-08T12:00:00Z")
            )
            conn_bob.commit()
        finally:
            conn_bob.close()
            
        # Verify Alice's imports table has only Alice's row
        db.request_context.db_path = self.test_dir_path / "expenses_alice.db"
        conn_alice = db.connect()
        try:
            rows = conn_alice.execute("select source_filename from imports").fetchall()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["source_filename"], "alice_statement.pdf")
        finally:
            conn_alice.close()
            
        # Verify Bob's imports table has only Bob's row
        db.request_context.db_path = self.test_dir_path / "expenses_bob.db"
        conn_bob = db.connect()
        try:
            rows = conn_bob.execute("select source_filename from imports").fetchall()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["source_filename"], "bob_statement.pdf")
        finally:
            conn_bob.close()

    def test_api_token_create_verify_revoke(self) -> None:
        register_user("tokuser", "tokpass1")
        token, msg = create_api_token("tokuser", "tokpass1", label="test")
        self.assertIsNotNone(token)
        self.assertTrue(str(token).startswith("exp_"))
        self.assertEqual(verify_api_token(token), "tokuser")
        self.assertIsNone(verify_api_token("exp_notreal"))
        self.assertTrue(revoke_api_token("tokuser", token))
        self.assertIsNone(verify_api_token(token))

    def test_handler_authentication_flow(self) -> None:
        # Test get_session_username and check_authentication inside Handler mock
        register_user("alice", "alicepass")
        session_id = authenticate_user("alice", "alicepass")
        
        # Mock HTTPServer Handler instance
        mock_handler = MagicMock()
        mock_handler.headers = {"Cookie": f"session_id={session_id}"}
        mock_handler.path = "/"
        mock_handler.get_session_username = lambda: web.ExpenseHandler.get_session_username(mock_handler)
        
        # Test cookie retrieval
        username = web.ExpenseHandler.get_session_username(mock_handler)
        self.assertEqual(username, "alice")
        
        # Test authenticating dynamic routing context
        is_authenticated = web.ExpenseHandler.check_authentication(mock_handler)
        self.assertTrue(is_authenticated)
        self.assertEqual(db.request_context.db_path, db.DATA_DIR / "expenses_alice.db")
        self.assertEqual(mock_handler.current_user, "alice")

    def test_safe_next(self) -> None:
        self.assertEqual(web.ExpenseHandler._safe_next("/app/"), "/app/")
        self.assertEqual(web.ExpenseHandler._safe_next("/"), "/")
        self.assertEqual(web.ExpenseHandler._safe_next("https://evil.example/"), "")
        self.assertEqual(web.ExpenseHandler._safe_next("//evil"), "")
        self.assertEqual(web.ExpenseHandler._safe_next("/login"), "")


if __name__ == "__main__":
    unittest.main()
