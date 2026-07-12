"""Direct contracts for extracted OTP and event services."""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.security.events import (
    EventRuntime,
    record_login_attempt,
    record_product_event,
    record_security_event,
    record_session_event,
)
from app.security.otp import (
    OtpAccessError,
    OtpRateLimits,
    OtpRuntime,
    cleanup_expired_otp_challenges,
    enforce_email_otp_rate_limits,
    generate_otp_code,
    hash_otp,
    send_email_otp,
    validate_email_otp_config,
)


def _connect_factory(path: Path):
    def connect() -> sqlite3.Connection:
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        return conn

    return connect


def _request():
    return SimpleNamespace(headers={"user-agent": "module-test-agent"})


def test_event_writers_preserve_rows_and_sanitized_json(tmp_path):
    connect = _connect_factory(tmp_path / "events.sqlite3")
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE session_events (
                id TEXT, session_id TEXT, internal_user_id TEXT, event_type TEXT,
                ip_address TEXT, user_agent_hash TEXT, metadata_json TEXT, created_at TEXT
            );
            CREATE TABLE security_events (
                id TEXT, internal_user_id TEXT, session_id TEXT, severity TEXT,
                event_type TEXT, ip_address TEXT, user_agent_hash TEXT,
                details_json TEXT, created_at TEXT
            );
            CREATE TABLE event_logs (
                id TEXT, internal_user_id TEXT, legacy_user_id TEXT, anonymous_id TEXT,
                installation_id TEXT, session_id TEXT, event_name TEXT, platform TEXT,
                device_type TEXT, ip_address TEXT, user_agent_hash TEXT,
                properties_json TEXT, created_at TEXT
            );
            CREATE TABLE auth_login_attempts (
                id TEXT, internal_user_id TEXT, provider TEXT, identifier TEXT,
                success INTEGER, failure_reason TEXT, ip_address TEXT,
                user_agent_hash TEXT, platform TEXT, created_at TEXT
            );
            """
        )
    runtime = EventRuntime(
        connect=connect,
        get_client_ip=lambda request: "127.0.0.1" if request else None,
        hash_user_agent=lambda request: hashlib.sha256(b"module-test-agent").hexdigest() if request else None,
    )
    request = _request()
    with connect() as conn:
        record_session_event(runtime, conn, "session-1", "user-1", "created", request, {"safe": True})
        record_security_event(runtime, conn, "denied", "critical", "user-1", "session-1", request, {"reason": "test"})
        record_login_attempt(runtime, conn, "web_email", False, "hashed-id", "user-1", "bad_code", "web", request)
    record_product_event(runtime, "login_failed", "user-1", platform="web", request=request, properties={"provider": "web_email"})

    with connect() as conn:
        session = conn.execute("SELECT * FROM session_events").fetchone()
        security = conn.execute("SELECT * FROM security_events").fetchone()
        product = conn.execute("SELECT * FROM event_logs").fetchone()
        attempt = conn.execute("SELECT * FROM auth_login_attempts").fetchone()
    assert session["metadata_json"] == '{"safe": true}'
    assert security["severity"] == "critical" and security["details_json"] == '{"reason": "test"}'
    assert product["event_name"] == "login_failed" and product["ip_address"] == "127.0.0.1"
    assert attempt["success"] == 0 and attempt["failure_reason"] == "bad_code"


def test_otp_primitives_and_delivery_contract():
    codes = {generate_otp_code(6) for _ in range(10)}
    assert len(codes) > 1
    assert all(len(code) == 6 and code.isdigit() for code in codes)
    assert generate_otp_code(0).isdigit() and len(generate_otp_code(0)) == 1
    assert hash_otp("123456") == hashlib.sha256(b"otp:123456").hexdigest()
    assert hash_otp("123456", hmac_secret="secret") != hash_otp("123456")

    validate_email_otp_config(app_env="development", debug_return_code=True, provider_configured=False)
    with pytest.raises(RuntimeError, match="DEBUG_RETURN_CODE"):
        validate_email_otp_config(app_env="production", debug_return_code=True, provider_configured=True)
    with pytest.raises(RuntimeError, match="No email provider"):
        validate_email_otp_config(app_env="production", debug_return_code=False, provider_configured=False)

    outbox: list[dict[str, str]] = []
    send_email_otp("user@example.test", "123456", app_env="development", provider_configured=False, mock_outbox=outbox)
    assert outbox[0]["to"] == "user@example.test"
    assert "123456" not in repr(outbox)


def test_otp_cleanup_removes_only_stale_finished_challenges(tmp_path):
    connect = _connect_factory(tmp_path / "cleanup.sqlite3")
    with connect() as conn:
        conn.execute(
            "CREATE TABLE auth_otp_challenges "
            "(id TEXT, created_at TEXT, consumed_at TEXT, expires_at TEXT)"
        )
        conn.executemany(
            "INSERT INTO auth_otp_challenges VALUES (?, ?, ?, ?)",
            (
                ("old-expired", "2000-01-01T00:00:00+00:00", None, "2000-01-01T00:01:00+00:00"),
                ("old-consumed", "2000-01-01T00:00:00+00:00", "2000-01-01T00:00:30+00:00", "2999-01-01T00:00:00+00:00"),
                ("active", "2999-01-01T00:00:00+00:00", None, "2999-01-01T00:05:00+00:00"),
            ),
        )
    assert cleanup_expired_otp_challenges(connect, retention_seconds=86400) == 2
    with connect() as conn:
        assert [row["id"] for row in conn.execute("SELECT id FROM auth_otp_challenges")] == ["active"]


def test_otp_rate_limit_records_only_email_hash(tmp_path):
    connect = _connect_factory(tmp_path / "limits.sqlite3")
    with connect() as conn:
        conn.execute(
            "CREATE TABLE auth_otp_challenges "
            "(destination TEXT, created_at TEXT, ip_address TEXT, consumed_at TEXT, expires_at TEXT)"
        )
        conn.execute(
            "INSERT INTO auth_otp_challenges VALUES "
            "('user@example.test', '2999-01-01T00:00:00+00:00', '127.0.0.1', NULL, '2999-01-01T01:00:00+00:00')"
        )
    security_events: list[dict] = []
    product_events: list[tuple[str, dict]] = []

    def record_security(conn, event_type, **kwargs):
        del conn
        security_events.append({"event_type": event_type, **kwargs})

    def record_product(event_name, **kwargs):
        product_events.append((event_name, kwargs))

    runtime = OtpRuntime(
        connect=connect,
        get_client_ip=lambda request: "127.0.0.1",
        record_security_event=record_security,
        record_product_event=record_product,
    )
    limits = OtpRateLimits(60, 99, 900, 99, 900, 99)
    with pytest.raises(OtpAccessError) as caught:
        enforce_email_otp_rate_limits(runtime, limits, "user@example.test", _request(), "anon", "install", "web")
    assert caught.value.status_code == 429
    details = security_events[0]["details"]
    assert details["reason"] == "cooldown"
    assert details["email_hash"] == hashlib.sha256(b"user@example.test").hexdigest()
    assert "user@example.test" not in repr(security_events)
    assert product_events[0][0] == "login_rate_limited"
