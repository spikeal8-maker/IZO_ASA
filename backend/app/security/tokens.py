"""Opaque token generation and at-rest token hashing policy."""

from __future__ import annotations

import hashlib
import hmac
import secrets


def generate_secure_token() -> str:
    """Generate a high-entropy opaque session or refresh token."""
    return secrets.token_urlsafe(48)


def generate_bot_login_token() -> str:
    """Generate an opaque token small enough for bot callback payloads."""
    return secrets.token_urlsafe(18)


def hash_token(raw_token: str, *, hmac_secret: str = "") -> str:
    """Hash a raw token deterministically without logging or storing the raw value."""
    if hmac_secret:
        return hmac.new(hmac_secret.encode(), raw_token.encode(), hashlib.sha256).hexdigest()
    return hashlib.sha256(raw_token.encode()).hexdigest()


def validate_session_crypto_config(*, app_env: str, hmac_secret: str) -> None:
    """Reject unkeyed token hashing in production-like application mode."""
    if app_env.lower() == "production" and not hmac_secret:
        raise RuntimeError(
            "SESSION_HMAC_SECRET is required when APP_ENV=production; "
            "refusing to fall back to unkeyed session-token hashing."
        )
