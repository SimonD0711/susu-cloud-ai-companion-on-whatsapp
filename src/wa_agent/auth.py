"""Admin authentication utilities for Susu Agent admin services."""

from __future__ import annotations

import base64
import hashlib
import hmac
import time
from typing import Optional

ADMIN_SESSION_COOKIE = "susu_admin_session"
ADMIN_SESSION_TTL = 7 * 24 * 3600


def admin_login_ready(
    password_salt_b64: Optional[str],
    password_hash_b64: Optional[str],
    session_secret: Optional[str],
) -> bool:
    """Check if all required auth environment variables are configured."""
    return bool(password_salt_b64 and password_hash_b64 and session_secret)


def sign_admin_session(expires_at: int, session_secret: str) -> str:
    """Create HMAC signature for a session cookie."""
    message = f"admin|{expires_at}".encode("utf-8")
    return hmac.new(
        session_secret.encode("utf-8"), message, hashlib.sha256
    ).hexdigest()


def make_admin_session_cookie(
    ttl: int,
    session_secret: str,
    cookie_name: str = ADMIN_SESSION_COOKIE,
) -> str:
    """Create an admin session cookie string."""
    expires_at = int(time.time()) + ttl
    signature = sign_admin_session(expires_at, session_secret)
    token = base64.urlsafe_b64encode(
        f"{expires_at}:{signature}".encode("utf-8")
    ).decode("ascii")
    return f"{cookie_name}={token}; Max-Age={ttl}; Path=/; HttpOnly; SameSite=Lax"


def clear_admin_session_cookie(cookie_name: str = ADMIN_SESSION_COOKIE) -> str:
    """Create a cookie header that clears the admin session."""
    return f"{cookie_name}=; Max-Age=0; Path=/; HttpOnly; SameSite=Lax"


def parse_cookies(cookie_header: str) -> dict[str, str]:
    """Parse a Cookie header string into a dict."""
    cookies = {}
    if not cookie_header:
        return cookies
    for item in cookie_header.split(";"):
        item = item.strip()
        if "=" in item:
            key, value = item.split("=", 1)
            cookies[key.strip()] = value.strip()
    return cookies


def is_admin_authenticated(
    handler_cookie_header: str,
    password_salt_b64: Optional[str],
    password_hash_b64: Optional[str],
    session_secret: str,
    cookie_name: str = ADMIN_SESSION_COOKIE,
    ttl: int = ADMIN_SESSION_TTL,
) -> bool:
    """Verify if a request is authenticated via session cookie."""
    if not admin_login_ready(password_salt_b64, password_hash_b64, session_secret):
        return False
    cookies = parse_cookies(handler_cookie_header)
    token = cookies.get(cookie_name)
    if not token:
        return False
    try:
        decoded = base64.urlsafe_b64decode(token.encode("ascii")).decode("utf-8")
        expires_at_raw, signature = decoded.split(":", 1)
        expires_at = int(expires_at_raw)
    except Exception:
        return False
    if expires_at < int(time.time()):
        return False
    return hmac.compare_digest(signature, sign_admin_session(expires_at, session_secret))


def verify_admin_password(
    password: str,
    password_salt_b64: str,
    password_hash_b64: str,
    iterations: int = 210000,
) -> bool:
    """
    Verify a password against the stored PBKDF2 hash.
    
    Args:
        password: Plain text password to verify.
        password_salt_b64: Base64-encoded salt.
        password_hash_b64: Base64-encoded expected hash.
        iterations: PBKDF2 iteration count (default 210000).
    
    Returns:
        True if password matches, False otherwise.
    """
    if not password_salt_b64 or not password_hash_b64:
        return False
    try:
        salt = base64.b64decode(password_salt_b64)
        expected = base64.b64decode(password_hash_b64)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations, dklen=32)
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False
