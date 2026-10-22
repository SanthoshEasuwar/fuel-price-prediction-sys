import os
import sqlite3
import unittest
from pathlib import Path

from services.auth_service import authenticate_user, register_user


class AuthServiceTests(unittest.TestCase):
    def setUp(self):
        self.db_dir = Path("Data/cache/.auth_test")
        self.db_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.db_dir / "users.sqlite3"
        self.db_path.unlink(missing_ok=True)
        self.previous_path = os.environ.get("FUEL_AUTH_DB_PATH")
        os.environ["FUEL_AUTH_DB_PATH"] = str(self.db_path.resolve())

    def tearDown(self):
        if self.previous_path is None:
            os.environ.pop("FUEL_AUTH_DB_PATH", None)
        else:
            os.environ["FUEL_AUTH_DB_PATH"] = self.previous_path
        self.db_path.unlink(missing_ok=True)
        Path(str(self.db_path) + "-wal").unlink(missing_ok=True)
        Path(str(self.db_path) + "-shm").unlink(missing_ok=True)
        try:
            self.db_dir.rmdir()
            self.db_dir.parent.rmdir()
        except OSError:
            pass

    def test_register_and_login_use_salted_hashes(self):
        user = register_user("Fuel.User@example.com", "a-long-demo-password")
        self.assertEqual(user["email"], "fuel.user@example.com")
        self.assertEqual(authenticate_user("FUEL.USER@example.com", "a-long-demo-password")["id"], user["id"])
        self.assertIsNone(authenticate_user("fuel.user@example.com", "wrong-password"))

        connection = sqlite3.connect(self.db_path)
        try:
            stored_hash = connection.execute("SELECT password_hash FROM users").fetchone()[0]
        finally:
            connection.close()
        self.assertNotIn("a-long-demo-password", stored_hash)
        self.assertTrue(stored_hash.startswith("pbkdf2_sha256$"))

    def test_duplicate_email_and_short_password_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "at least 12"):
            register_user("student@example.com", "short")
        register_user("student@example.com", "a-long-demo-password")
        with self.assertRaisesRegex(ValueError, "already exists"):
            register_user("STUDENT@example.com", "another-long-password")


if __name__ == "__main__":
    unittest.main()
