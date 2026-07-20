"""Email verification (OTP) after password registration.

Covers the post-registration verification gate added on top of the existing
email-OTP infrastructure:
- registration no longer issues a trusted session when email OTP is deliverable;
- the OTP is stored only as a hash;
- verify-code-v2 creates the trusted session and marks email_verified_at;
- bootstrap-v2 advertises email_otp only when it is actually available;
- existing password login is NOT broken.

Uses a TEMPORARY SQLite DB via monkeypatching main.DB_PATH; the live
backend/onenode.sqlite3 is never touched. The dev debug OTP path
(EMAIL_OTP_DEBUG_RETURN_CODE) returns the code in the response for testing.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from test_support.browser_client import BrowserTestClient

import main


@pytest.fixture
def client(tmp_path: Path, monkeypatch):
    db_file = tmp_path / "email_verify_test.sqlite3"
    monkeypatch.setattr(main, "DB_PATH", db_file)
    monkeypatch.setattr(main, "APP_ENV", "test")          # non-production
    monkeypatch.setattr(main, "EMAIL_PROVIDER", "")        # no real provider…
    monkeypatch.setattr(main, "EMAIL_OTP_DEBUG_RETURN_CODE", True)  # …but debug path on
    monkeypatch.setattr(main, "TRUSTED_COOKIE_SECURE", False)  # http TestClient resends the cookie
    main.init_db()
    return BrowserTestClient(main.app)


REG = {
    "email": "verify-me@example.com",
    "password": "Sup3rSecret!",
    "password_repeat": "Sup3rSecret!",
    "accepted_terms": True,
    "accepted_privacy": True,
    "accepted_personal_data": True,
    "platform": "web_desktop",
}


def _request_code(client: TestClient, email: str) -> tuple[str, str]:
    r = client.post("/api/auth/email/request-code-v2", json={"email": email, "platform": "web_desktop"})
    assert r.status_code == 200, r.text
    body = r.json()
    return body["challenge_id"], body["debug_code"]


def test_register_requires_verification_and_grants_no_session(client):
    r = client.post("/api/auth/password/register-v2", json=REG)
    assert r.status_code == 200, r.text
    assert r.json()["requires_email_verification"] is True
    # No trusted session cookie issued at registration time.
    assert "onenode_session" not in r.cookies
    # And the session is genuinely absent: /me-v2 is unauthenticated.
    assert client.get("/api/me-v2").status_code == 401


def test_verify_code_creates_trusted_session_and_marks_email(client):
    assert client.post("/api/auth/password/register-v2", json=REG).status_code == 200
    challenge_id, code = _request_code(client, REG["email"])
    vr = client.post(
        "/api/auth/email/verify-code-v2",
        json={"challenge_id": challenge_id, "code": code, "platform": "web_desktop"},
    )
    assert vr.status_code == 200, vr.text
    # Trusted session now works (cookie captured by the TestClient).
    me = client.get("/api/me-v2")
    assert me.status_code == 200, me.text
    # email_verified_at recorded for the account.
    with main.db() as conn:
        row = conn.execute(
            "SELECT u.email_verified_at AS v FROM users u "
            "JOIN auth_identities ai ON ai.internal_user_id = u.internal_user_id "
            "WHERE ai.provider = 'web_email' AND ai.provider_user_id = ?",
            (REG["email"],),
        ).fetchone()
    assert row is not None and row["v"]


def test_otp_is_stored_only_as_hash(client):
    _, code = _request_code(client, "hashme@example.com")
    with main.db() as conn:
        row = conn.execute(
            "SELECT code_hash FROM auth_otp_challenges WHERE destination = ?",
            ("hashme@example.com",),
        ).fetchone()
    assert row is not None
    assert row["code_hash"] != code               # raw code is never stored
    assert row["code_hash"] == main.hash_otp(code)  # only its hash


def test_bootstrap_gates_email_otp_on_availability(client, monkeypatch):
    r1 = client.post("/api/auth/bootstrap-v2", json={"platform": "web_desktop"})
    assert "email_otp" in r1.json()["auth_methods"]
    # Not deliverable -> not advertised.
    monkeypatch.setattr(main, "EMAIL_OTP_DEBUG_RETURN_CODE", False)
    monkeypatch.setattr(main, "EMAIL_PROVIDER", "")
    r2 = client.post("/api/auth/bootstrap-v2", json={"platform": "web_desktop"})
    assert "email_otp" not in r2.json()["auth_methods"]


def test_password_login_not_broken(client):
    client.post("/api/auth/password/register-v2", json=REG)
    challenge_id, code = _request_code(client, REG["email"])
    client.post("/api/auth/email/verify-code-v2", json={"challenge_id": challenge_id, "code": code, "platform": "web_desktop"})
    # A fresh client (no cookies) can still log in with the password.
    fresh = BrowserTestClient(main.app)
    lr = fresh.post(
        "/api/auth/password/login-v2",
        json={"email": REG["email"], "password": REG["password"], "platform": "web_desktop"},
    )
    assert lr.status_code == 200, lr.text
