"""Session-based auth and API key management."""
from __future__ import annotations
import secrets
from functools import wraps

from flask import redirect, session
from werkzeug.security import check_password_hash, generate_password_hash

from . import store


def create_user(username: str, password: str) -> str:
    """Create a user; return their API key."""
    store.init_db()
    api_key = secrets.token_hex(32)
    pw_hash = generate_password_hash(password)
    with store._connect() as conn:
        conn.execute(
            "INSERT INTO users (username, password_hash, api_key) VALUES (?, ?, ?)",
            (username, pw_hash, api_key),
        )
    return api_key


def check_login(username: str, password: str) -> bool:
    store.init_db()
    with store._connect() as conn:
        row = conn.execute(
            "SELECT password_hash FROM users WHERE username = ?", (username,)
        ).fetchone()
    if not row:
        return False
    return check_password_hash(row["password_hash"], password)


def has_users() -> bool:
    store.init_db()
    with store._connect() as conn:
        count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    return count > 0


def verify_api_key(key: str) -> str | None:
    """Return the username if the API key is valid, else None."""
    store.init_db()
    with store._connect() as conn:
        row = conn.execute(
            "SELECT username FROM users WHERE api_key = ?", (key,)
        ).fetchone()
    return row["username"] if row else None


def require_login(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not has_users():
            return redirect("/setup")
        if not session.get("user"):
            return redirect("/login")
        return f(*args, **kwargs)
    return decorated
