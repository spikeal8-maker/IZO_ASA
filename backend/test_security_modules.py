"""Direct contracts for extracted token and password security helpers."""

from __future__ import annotations

import hashlib
import hmac

import pytest

from app.security.passwords import (
    PASSWORD_ALGORITHM,
    hash_password,
    password_hash_needs_rehash,
    validate_password_policy,
    verify_password,
)
from app.security.tokens import (
    generate_bot_login_token,
    generate_secure_token,
    hash_token,
    validate_session_crypto_config,
)


def test_token_generation_is_opaque_and_unique():
    session_tokens = {generate_secure_token() for _ in range(5)}
    bot_tokens = {generate_bot_login_token() for _ in range(5)}
    assert len(session_tokens) == 5
    assert len(bot_tokens) == 5
    assert all(len(value) >= 60 for value in session_tokens)
    assert all(20 <= len(value) <= 40 for value in bot_tokens)


def test_token_hash_uses_hmac_when_secret_is_configured():
    raw = "raw-session-token"
    secret = "test-hmac-secret"
    expected = hmac.new(secret.encode(), raw.encode(), hashlib.sha256).hexdigest()
    assert hash_token(raw, hmac_secret=secret) == expected
    assert hash_token(raw) == hashlib.sha256(raw.encode()).hexdigest()
    assert hash_token(raw, hmac_secret=secret) != hash_token(raw)


def test_production_requires_session_hmac_secret():
    with pytest.raises(RuntimeError, match="SESSION_HMAC_SECRET"):
        validate_session_crypto_config(app_env="production", hmac_secret="")
    validate_session_crypto_config(app_env="production", hmac_secret="configured")
    validate_session_crypto_config(app_env="development", hmac_secret="")


def test_password_policy_and_argon2_round_trip():
    assert PASSWORD_ALGORITHM == "argon2id"
    assert validate_password_policy("short") == ["password_too_short"]
    assert validate_password_policy("correct horse battery") == []
    password_hash = hash_password("correct horse battery")
    assert password_hash.startswith("$argon2id$")
    assert verify_password("correct horse battery", password_hash) is True
    assert verify_password("wrong password", password_hash) is False
    assert verify_password("correct horse battery", "malformed") is False
    assert isinstance(password_hash_needs_rehash(password_hash), bool)
