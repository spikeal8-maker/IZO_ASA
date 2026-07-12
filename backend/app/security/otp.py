"""Email OTP primitives, cleanup and abuse controls without FastAPI imports."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any


@dataclass(frozen=True)
class OtpRuntime:
    connect: Callable[[], sqlite3.Connection]
    get_client_ip: Callable[[Any | None], str | None]
    record_security_event: Callable[..., None]
    record_product_event: Callable[..., None]


@dataclass(frozen=True)
class OtpRateLimits:
    request_cooldown_seconds: int
    max_requests_per_email_window: int
    email_window_seconds: int
    max_requests_per_ip_window: int
    ip_window_seconds: int
    max_active_challenges_per_email: int


class OtpAccessError(RuntimeError):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def generate_otp_code(length: int) -> str:
    return "".join(secrets.choice("0123456789") for _ in range(max(1, length)))


def hash_otp(code: str, *, hmac_secret: str = "") -> str:
    payload = f"otp:{code}".encode()
    if hmac_secret:
        return hmac.new(hmac_secret.encode(), payload, hashlib.sha256).hexdigest()
    return hashlib.sha256(payload).hexdigest()


def validate_email_otp_config(
    *, app_env: str, debug_return_code: bool, provider_configured: bool
) -> None:
    if app_env.lower() != "production":
        return
    if debug_return_code:
        raise RuntimeError("EMAIL_OTP_DEBUG_RETURN_CODE must be disabled in production.")
    if not provider_configured:
        raise RuntimeError("No email provider configured for production email OTP.")


def send_email_otp(
    destination: str,
    code: str,
    *,
    app_env: str,
    provider_configured: bool,
    mock_outbox: list[dict[str, str]],
) -> None:
    """Preserve the existing mock delivery contract without retaining raw OTP."""
    del code
    if app_env.lower() == "production" and provider_configured:
        raise RuntimeError("Email provider integration not implemented.")
    mock_outbox.append({"to": destination, "sent_at": datetime.now(timezone.utc).isoformat()})


def cleanup_expired_otp_challenges(
    connect: Callable[[], sqlite3.Connection],
    *,
    retention_seconds: int,
    now: str | None = None,
) -> int:
    now_dt = datetime.now(timezone.utc)
    now_iso = now or now_dt.isoformat()
    cutoff = (now_dt - timedelta(seconds=retention_seconds)).isoformat()
    with connect() as conn:
        cursor = conn.execute(
            "DELETE FROM auth_otp_challenges "
            "WHERE created_at < ? AND (consumed_at IS NOT NULL OR expires_at < ?)",
            (cutoff, now_iso),
        )
        return cursor.rowcount


def _email_hash(email_normalized: str) -> str:
    return hashlib.sha256(email_normalized.encode()).hexdigest()


def _raise_rate_limit(
    runtime: OtpRuntime,
    reason: str,
    window_seconds: int,
    email_normalized: str,
    request: Any,
    anonymous_id: str | None,
    installation_id: str | None,
    platform: str | None,
) -> None:
    with runtime.connect() as conn:
        runtime.record_security_event(
            conn,
            "otp_request_rate_limited",
            internal_user_id=None,
            request=request,
            details={
                "reason": reason,
                "email_hash": _email_hash(email_normalized),
                "window_seconds": window_seconds,
            },
        )
    try:
        runtime.record_product_event(
            "login_rate_limited",
            anonymous_id=anonymous_id,
            installation_id=installation_id,
            platform=platform,
            properties={"provider": "web_email", "reason": reason},
        )
    except Exception as exc:  # pragma: no cover - defensive compatibility
        print(f"email-otp: login_rate_limited event log error: {type(exc).__name__}")
    raise OtpAccessError(429, "Too many requests")


def enforce_email_otp_rate_limits(
    runtime: OtpRuntime,
    limits: OtpRateLimits,
    email_normalized: str,
    request: Any,
    anonymous_id: str | None,
    installation_id: str | None,
    platform: str | None,
) -> None:
    now_dt = datetime.now(timezone.utc)
    now_iso = now_dt.isoformat()
    ip_address = runtime.get_client_ip(request)
    cooldown_cutoff = (now_dt - timedelta(seconds=limits.request_cooldown_seconds)).isoformat()
    email_cutoff = (now_dt - timedelta(seconds=limits.email_window_seconds)).isoformat()
    ip_cutoff = (now_dt - timedelta(seconds=limits.ip_window_seconds)).isoformat()

    with runtime.connect() as conn:
        cooldown_hits = conn.execute(
            "SELECT COUNT(*) AS c FROM auth_otp_challenges "
            "WHERE destination = ? AND created_at > ?",
            (email_normalized, cooldown_cutoff),
        ).fetchone()["c"]
        email_window_count = conn.execute(
            "SELECT COUNT(*) AS c FROM auth_otp_challenges "
            "WHERE destination = ? AND created_at > ?",
            (email_normalized, email_cutoff),
        ).fetchone()["c"]
        ip_window_count = (
            conn.execute(
                "SELECT COUNT(*) AS c FROM auth_otp_challenges "
                "WHERE ip_address = ? AND created_at > ?",
                (ip_address, ip_cutoff),
            ).fetchone()["c"]
            if ip_address
            else 0
        )
        active_count = conn.execute(
            "SELECT COUNT(*) AS c FROM auth_otp_challenges "
            "WHERE destination = ? AND consumed_at IS NULL AND expires_at > ?",
            (email_normalized, now_iso),
        ).fetchone()["c"]

    failures = (
        (
            limits.request_cooldown_seconds > 0 and cooldown_hits > 0,
            "cooldown",
            limits.request_cooldown_seconds,
        ),
        (
            email_window_count >= limits.max_requests_per_email_window,
            "email_window",
            limits.email_window_seconds,
        ),
        (
            bool(ip_address) and ip_window_count >= limits.max_requests_per_ip_window,
            "ip_window",
            limits.ip_window_seconds,
        ),
        (
            active_count >= limits.max_active_challenges_per_email,
            "max_active_challenges",
            limits.email_window_seconds,
        ),
    )
    for failed, reason, window_seconds in failures:
        if failed:
            _raise_rate_limit(
                runtime,
                reason,
                window_seconds,
                email_normalized,
                request,
                anonymous_id,
                installation_id,
                platform,
            )
