"""Tests for src.wa_agent.auth."""

import pytest
import hashlib
import base64
import time
import hmac as hmac_lib

from src.wa_agent.auth import (
    admin_login_ready,
    sign_admin_session,
    make_admin_session_cookie,
    clear_admin_session_cookie,
    parse_cookies,
    is_admin_authenticated,
    verify_admin_password,
)


def test_admin_login_ready_all_present():
    assert admin_login_ready("salt", "hash", "secret") is True


def test_admin_login_ready_missing_salt():
    assert admin_login_ready(None, "hash", "secret") is False


def test_admin_login_ready_missing_hash():
    assert admin_login_ready("salt", None, "secret") is False


def test_admin_login_ready_missing_secret():
    assert admin_login_ready("salt", "hash", None) is False


def test_admin_login_ready_all_missing():
    assert admin_login_ready(None, None, None) is False


def test_sign_admin_session():
    sig = sign_admin_session(1234567890, "test_secret")
    assert len(sig) == 64


def test_sign_admin_session_deterministic():
    sig1 = sign_admin_session(999, "mysecret")
    sig2 = sign_admin_session(999, "mysecret")
    assert sig1 == sig2


def test_sign_admin_session_different_secrets():
    sig1 = sign_admin_session(999, "secret1")
    sig2 = sign_admin_session(999, "secret2")
    assert sig1 != sig2


def test_make_admin_session_cookie():
    cookie = make_admin_session_cookie(3600, "test_secret")
    assert "susu_admin_session=" in cookie
    assert "Max-Age=3600" in cookie


def test_clear_admin_session_cookie():
    cookie = clear_admin_session_cookie()
    assert cookie == "susu_admin_session=; Max-Age=0; Path=/; HttpOnly; SameSite=Lax"


def test_clear_admin_session_cookie_custom_name():
    cookie = clear_admin_session_cookie("custom_cookie")
    assert cookie == "custom_cookie=; Max-Age=0; Path=/; HttpOnly; SameSite=Lax"


def test_parse_cookies_basic():
    cookies = parse_cookies("foo=bar; baz=qux")
    assert cookies["foo"] == "bar"
    assert cookies["baz"] == "qux"


def test_parse_cookies_empty():
    assert parse_cookies("") == {}
    assert parse_cookies(None) == {}


def test_parse_cookies_with_spaces():
    cookies = parse_cookies("  foo = bar ;  baz = qux ")
    assert cookies["foo"] == "bar"
    assert cookies["baz"] == "qux"


def test_is_admin_authenticated_missing_env():
    assert is_admin_authenticated(
        "foo=bar", None, None, "secret"
    ) is False


def test_is_admin_authenticated_valid_token():
    secret = "test_secret_12345"
    ttl = 3600
    expires_at = int(time.time()) + ttl
    sig = sign_admin_session(expires_at, secret)
    token = base64.urlsafe_b64encode(f"{expires_at}:{sig}".encode()).decode()
    cookie = f"susu_admin_session={token}"
    assert is_admin_authenticated(
        cookie, "salt_b64", "hash_b64", secret
    ) is True


def test_is_admin_authenticated_expired_token():
    secret = "test_secret_12345"
    expires_at = int(time.time()) - 1
    sig = sign_admin_session(expires_at, secret)
    token = base64.urlsafe_b64encode(f"{expires_at}:{sig}".encode()).decode()
    cookie = f"susu_admin_session={token}"
    assert is_admin_authenticated(
        cookie, "salt_b64", "hash_b64", secret
    ) is False


def test_is_admin_authenticated_bad_cookie():
    assert is_admin_authenticated(
        "susu_admin_session=invalid", "salt_b64", "hash_b64", "secret"
    ) is False


def test_verify_admin_password_correct():
    password = "Dingding0616"
    salt = base64.b64decode("dGVzdHNhbHQ=")
    expected_hash = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 210000, dklen=32)
    salt_b64 = base64.b64encode(salt).decode()
    hash_b64 = base64.b64encode(expected_hash).decode()
    assert verify_admin_password(password, salt_b64, hash_b64) is True


def test_verify_admin_password_incorrect():
    salt = base64.b64decode("dGVzdHNhbHQ=")
    wrong_hash = hashlib.pbkdf2_hmac("sha256", b"wrongpassword", salt, 210000, dklen=32)
    salt_b64 = base64.b64encode(salt).decode()
    hash_b64 = base64.b64encode(wrong_hash).decode()
    assert verify_admin_password("Dingding0616", salt_b64, hash_b64) is False


def test_verify_admin_password_empty_salt():
    assert verify_admin_password("pass", None, "hash_b64") is False


def test_verify_admin_password_empty_hash():
    assert verify_admin_password("pass", "salt_b64", None) is False


def test_verify_admin_password_custom_iterations():
    password = "testpass"
    salt = base64.b64decode("dGVzdHNhbHQ=")
    expected_hash = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 100000, dklen=32)
    salt_b64 = base64.b64encode(salt).decode()
    hash_b64 = base64.b64encode(expected_hash).decode()
    assert verify_admin_password(password, salt_b64, hash_b64, iterations=100000) is True
    assert verify_admin_password(password, salt_b64, hash_b64, iterations=99999) is False
