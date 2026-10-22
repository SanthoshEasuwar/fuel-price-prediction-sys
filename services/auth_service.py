"""Session authentication and local SQLite account storage.

This is intended for a single-instance project/demo deployment. Passwords
are never stored in plain text; only salted PBKDF2 hashes are persisted.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import streamlit as st


PROJECT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = PROJECT_DIR / "Data" / "users.sqlite3"
PASSWORD_ITERATIONS = 600_000
EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
SESSION_KEY = "fuel_price_authenticated_user"


def database_path() -> Path:
    """Allow tests or local deployments to select a separate account database."""
    return Path(os.getenv("FUEL_AUTH_DB_PATH", str(DEFAULT_DB_PATH)))


def _connect() -> sqlite3.Connection:
    path = database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=10)
    connection.row_factory = sqlite3.Row
    return connection


@contextmanager
def _database():
    connection = _connect()
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def _initialize_database() -> None:
    with _database() as connection:
        connection.execute(
            """CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            )"""
        )


def _hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS)
    return "pbkdf2_sha256${}${}${}".format(
        PASSWORD_ITERATIONS,
        base64.b64encode(salt).decode("ascii"),
        base64.b64encode(digest).decode("ascii"),
    )


def _verify_password(password: str, stored_hash: str) -> bool:
    try:
        algorithm, iterations, salt_b64, digest_b64 = stored_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        expected = base64.b64decode(digest_b64, validate=True)
        actual = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            base64.b64decode(salt_b64, validate=True),
            int(iterations),
        )
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def register_user(email: str, password: str) -> dict[str, Any]:
    """Create an account, returning its public fields (never its password)."""
    normalized_email = email.strip().casefold()
    if len(normalized_email) > 254 or not EMAIL_PATTERN.fullmatch(normalized_email):
        raise ValueError("Enter a valid email address.")
    if len(password) < 12:
        raise ValueError("Use a password with at least 12 characters.")
    if len(password) > 256:
        raise ValueError("Password must be 256 characters or fewer.")

    _initialize_database()
    try:
        with _database() as connection:
            cursor = connection.execute(
                "INSERT INTO users (email, password_hash, created_at) VALUES (?, ?, ?)",
                (
                    normalized_email,
                    _hash_password(password),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            return {"id": cursor.lastrowid, "email": normalized_email}
    except sqlite3.IntegrityError as exc:
        raise ValueError("An account with that email already exists.") from exc


def authenticate_user(email: str, password: str) -> dict[str, Any] | None:
    """Return a user's public fields when credentials match."""
    normalized_email = email.strip().casefold()
    _initialize_database()
    with _database() as connection:
        row = connection.execute(
            "SELECT id, email, password_hash FROM users WHERE email = ?",
            (normalized_email,),
        ).fetchone()
    if row is None or not _verify_password(password, row["password_hash"]):
        return None
    return {"id": row["id"], "email": row["email"]}


def current_user() -> dict[str, Any] | None:
    user = st.session_state.get(SESSION_KEY)
    return user if isinstance(user, dict) and user.get("id") and user.get("email") else None


def logout() -> None:
    st.session_state.pop(SESSION_KEY, None)


def render_login_signup() -> None:
    """Render the public login and signup interface."""
    st.markdown("<div class='fuel-eyebrow'>Daily prices · historical trends · tomorrow's estimate</div>", unsafe_allow_html=True)
    hero_column, form_column = st.columns([1.1, 0.9], gap="large", vertical_alignment="center")
    with hero_column:
        st.markdown(
            "<div class='fuel-auth-hero'>"
            "<div class='hero-mark'>FP</div>"
            "<div class='hero-kicker'>Fuel market analytics</div>"
            "<h1>Clearer insight<br>at every litre.</h1>"
            "<p>Track published petrol and diesel prices, explore city trends, "
            "and review a transparent next-day baseline.</p>"
            "<div class='fuel-auth-points'><span>4 metro cities</span>"
            "<span>Historical analysis</span><span>Source-aware updates</span></div>"
            "</div>",
            unsafe_allow_html=True,
        )
    with form_column:
        st.subheader("Access your dashboard")
        st.caption("Sign in to continue, or create a project account.")
        login_tab, signup_tab = st.tabs(["Log in", "Sign up"])
        with login_tab:
            with st.form("fuel_login_form"):
                email = st.text_input("Email address", key="login_email", autocomplete="email")
                password = st.text_input(
                    "Password", type="password", key="login_password", autocomplete="current-password"
                )
                submitted = st.form_submit_button("Log in", type="primary", width="stretch")
            if submitted:
                user = authenticate_user(email, password)
                if user:
                    st.session_state[SESSION_KEY] = user
                    st.rerun()
                st.error("Email or password is incorrect.")

        with signup_tab:
            with st.form("fuel_signup_form"):
                email = st.text_input("Email address", key="signup_email", autocomplete="email")
                password = st.text_input(
                    "Password", type="password", key="signup_password", autocomplete="new-password"
                )
                confirm_password = st.text_input(
                    "Confirm password", type="password", key="signup_confirm", autocomplete="new-password"
                )
                submitted = st.form_submit_button("Create account", type="primary", width="stretch")
            if submitted:
                if password != confirm_password:
                    st.error("The passwords do not match.")
                else:
                    try:
                        user = register_user(email, password)
                    except ValueError as exc:
                        st.error(str(exc))
                    else:
                        st.session_state[SESSION_KEY] = user
                        st.success("Account created. You are now signed in.")
                        st.rerun()
        st.caption("Passwords are stored as salted hashes. Sign-in lasts for this browser session.")


def require_user() -> dict[str, Any]:
    """Stop a protected page from rendering for an unauthenticated session."""
    user = current_user()
    if not user:
        st.warning("Please log in to access this page.")
        render_login_signup()
        st.stop()
    return user


def render_account_sidebar(page_key: str) -> None:
    if not current_user():
        return
    st.sidebar.divider()
    if st.sidebar.button("Log out", key=f"logout_{page_key}", width="stretch"):
        logout()
        st.rerun()


def render_account_page() -> None:
    """Show account status and provide the login/signup forms."""
    user = current_user()
    if user:
        st.sidebar.divider()
        if st.sidebar.button("Log out", key="logout_account", width="stretch"):
            logout()
            st.rerun()
        st.title("Your Account")
        st.success(f"Signed in as {user['email']}.")
        st.info("Choose Overview from the page navigation to return to the dashboard.")
        if st.button("Log out", type="secondary"):
            logout()
            st.rerun()
        return
    render_login_signup()
