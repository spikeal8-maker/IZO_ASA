"""Closed-beta account admission; synthetic users, signatures and passwords only.

TestClient is deliberately not entered as a context manager: these tests do not
start lifespan workers, a listening server, email transports or GPU providers.
The repository conftest isolates SQLite and media before ``beta_client`` runs.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from contextlib import closing
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import pytest
from fastapi.testclient import TestClient

import main
from app.security.account_verification import upsert_web_email_identity
from test_support.browser_origin import BROWSER_ORIGIN


PASSWORD = "Synthetic-Beta-Password-42!"
BOT_TOKEN = "123456:Synthetic-closed-beta-test-token"
EMAIL = "existing-beta@example.com"
USER_ID = "web_closed_beta_existing"
INTERNAL_ID = "closed-beta-existing-internal"
OLD_DATE = "2026-01-01T00:00:00+00:00"
TABLES = ("users", "auth_identities", "auth_passwords", "auth_sessions", "token_ledger", "user_consents")


def forbidden(*_args, **_kwargs):
    raise AssertionError("Closed-beta denial reached a forbidden side effect")


@pytest.fixture
def beta_client(monkeypatch):
    monkeypatch.setenv("IZO_CLOSED_BETA", "1")
    monkeypatch.delenv("IZO_PREPROD_PRESERVE_HISTORY", raising=False)
    monkeypatch.delenv("IZO_HISTORY_SNAPSHOT_ID", raising=False)
    monkeypatch.setattr(main, "APP_ENV", "development")
    monkeypatch.setattr(main, "SESSION_HMAC_SECRET", "closed-beta-synthetic-session-secret")
    monkeypatch.setattr(main, "EMAIL_PROVIDER", "")
    monkeypatch.setattr(main, "EMAIL_OTP_DEBUG_RETURN_CODE", False)
    monkeypatch.setattr(main, "TRUSTED_COOKIE_SECURE", False)
    monkeypatch.setattr(main, "TELEGRAM_BOT_TOKEN", BOT_TOKEN)
    monkeypatch.setattr(main, "MAX_BOT_TOKEN", BOT_TOKEN)
    monkeypatch.setattr(
        main, "resolve_max_bot_deep_link_base",
        lambda: "https://max.ru/synthetic_closed_beta_bot",
    )
    monkeypatch.setattr(main, "TELEGRAM_INIT_DATA_TTL_SECONDS", 86400)
    monkeypatch.setattr(main, "MAX_WEB_APP_DATA_TTL_SECONDS", 86400)
    monkeypatch.setattr(main, "schedule_avatar_cache", lambda *_args: None)
    monkeypatch.setattr(main, "send_email_otp", forbidden)
    main.init_db()
    client = TestClient(main.app, headers=BROWSER_ORIGIN)
    try:
        yield client
    finally:
        client.close()


def snapshot():
    with closing(main.db()) as conn:
        return {
            table: [tuple(row) for row in conn.execute(f"SELECT * FROM {table} ORDER BY id")]
            for table in TABLES
        }


def billing_snapshot():
    with closing(main.db()) as conn:
        return (
            [tuple(row) for row in conn.execute("SELECT id, token_balance FROM users ORDER BY id")],
            [tuple(row) for row in conn.execute("SELECT * FROM token_ledger ORDER BY id")],
        )


def seed_email(*, password=False, identity=True):
    stored_hash = main.hash_password_argon2(PASSWORD) if password else None
    with closing(main.db()) as conn, conn:
        conn.execute(
            "INSERT INTO users (id, internal_user_id, email, email_verified_at, language, role, "
            "plan, plan_started_at, token_balance, created_at, last_login_at) "
            "VALUES (?, ?, ?, ?, 'ru', 'user', 'mini', ?, 41, ?, ?)",
            (USER_ID, INTERNAL_ID, EMAIL, OLD_DATE, OLD_DATE, OLD_DATE, OLD_DATE),
        )
        if identity:
            conn.execute(
                "INSERT INTO auth_identities (id, internal_user_id, legacy_user_id, provider, "
                "provider_user_id, provider_email, verified_at, linked_at, last_login_at) "
                "VALUES ('beta-email-identity', ?, ?, 'web_email', ?, ?, ?, ?, ?)",
                (INTERNAL_ID, USER_ID, EMAIL, EMAIL, OLD_DATE, OLD_DATE, OLD_DATE),
            )
        if stored_hash:
            conn.execute(
                "INSERT INTO auth_passwords (id, internal_user_id, password_hash, algorithm, "
                "created_at, updated_at, password_updated_at) VALUES "
                "('beta-password', ?, ?, 'argon2id', ?, ?, ?)",
                (INTERNAL_ID, stored_hash, OLD_DATE, OLD_DATE, OLD_DATE),
            )
        conn.execute(
            "INSERT INTO token_ledger (id, user_id, delta, reason, meta_json, created_at) "
            "VALUES ('beta-old-ledger', ?, 41, 'synthetic_historical_fixture', '{}', ?)",
            (USER_ID, OLD_DATE),
        )
    return stored_hash


def registration_payload(email=EMAIL):
    return {
        "email": email, "password": PASSWORD, "password_repeat": PASSWORD,
        "accepted_terms": True, "accepted_privacy": True, "accepted_personal_data": True,
        "platform": "web_desktop",
    }


def assert_denied(response):
    assert response.status_code == 403, response.text
    assert response.json() == {"detail": "closed_beta_registration_disabled"}
    assert "set-cookie" not in response.headers


@pytest.mark.parametrize("value, expected", [
    (None, False), ("", False), ("0", False), ("false", False), (" NO ", False),
    ("off", False), ("1", True), ("TRUE", True), ("yes", True), ("on", True),
    ("unexpected-value", True),
])
def test_closed_beta_policy_default_and_fail_closed_values(monkeypatch, value, expected):
    if value is None:
        monkeypatch.delenv("IZO_CLOSED_BETA", raising=False)
    else:
        monkeypatch.setenv("IZO_CLOSED_BETA", value)
    assert main.closed_beta_enabled() is expected


def test_capabilities_hide_registration_but_keep_password_login(beta_client):
    response = beta_client.get("/api/auth/capabilities-v2")
    assert response.status_code == 200
    assert response.json()["password_register_available"] is False
    assert response.json()["password_login_available"] is True
    assert response.json()["bot_login"]["max_bot_login_available"] is True


@pytest.mark.parametrize("existing_identity", [False, True])
def test_password_registration_denied_before_hash_or_account_mutation(beta_client, monkeypatch, existing_identity):
    if existing_identity:
        seed_email(password=False)
    before = snapshot()
    monkeypatch.setattr(main, "hash_password_argon2", forbidden)
    assert_denied(beta_client.post("/api/auth/password/register-v2", json=registration_payload()))
    assert snapshot() == before


@pytest.mark.parametrize("target, forged_identity", [
    ("new-beta-user", False), ("closed_beta_existing", False), ("closed_beta_existing", True),
])
def test_legacy_bootstrap_cannot_provision_or_read_existing_profile(beta_client, monkeypatch, target, forged_identity):
    seed_email()
    before = snapshot()
    for name in ("upsert_user", "get_flux_klein_config", "get_comfyui_models", "get_flux_bgremoval_models"):
        monkeypatch.setattr(main, name, forbidden)
    headers = {"X-OneNode-User": USER_ID, "Cookie": f"onenode_user={USER_ID}"} if forged_identity else {}
    response = beta_client.post(
        "/api/app/bootstrap", json={"platform": "web", "userId": target, "email": "injected@example.com"},
        headers=headers,
    )
    assert_denied(response)
    assert snapshot() == before


def signed_provider_payload(provider, user_id=881001):
    fields = {
        "auth_date": str(int(time.time())), "query_id": "closed-beta-synthetic-query",
        "user": json.dumps({"id": user_id, "first_name": "Synthetic beta user"}, separators=(",", ":")),
    }
    data = "\n".join(f"{key}={fields[key]}" for key in sorted(fields))
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    signature = hmac.new(secret, data.encode(), hashlib.sha256).hexdigest()
    field = "init_data" if provider == "telegram" else "web_app_data"
    return {"platform": f"{provider}_mini_app", field: urlencode({**fields, "hash": signature})}


@pytest.mark.parametrize("provider", ["telegram", "max"])
def test_verified_new_provider_cannot_create_account(beta_client, provider):
    before = snapshot()
    response = beta_client.post(f"/api/auth/{provider}-v2", json=signed_provider_payload(provider))
    assert_denied(response)
    assert snapshot() == before


@pytest.mark.parametrize("provider", ["telegram", "max"])
@pytest.mark.parametrize("mode", ["existing_identity", "legacy", "legacy_missing_internal"])
def test_existing_provider_identity_and_legacy_adoption_still_login(beta_client, provider, mode):
    legacy_id = f"{provider}_881001"
    internal_id = None if mode == "legacy_missing_internal" else f"beta-{provider}-internal"
    with closing(main.db()) as conn, conn:
        conn.execute(
            f"INSERT INTO users (id, internal_user_id, {provider}_id, language, role, plan, "
            "plan_started_at, token_balance, created_at, last_login_at) "
            "VALUES (?, ?, '881001', 'ru', 'user', 'mini', ?, 41, ?, ?)",
            (legacy_id, internal_id, OLD_DATE, OLD_DATE, OLD_DATE),
        )
        if mode == "existing_identity":
            conn.execute(
                "INSERT INTO auth_identities (id, internal_user_id, legacy_user_id, provider, "
                "provider_user_id, verified_at, linked_at, last_login_at) VALUES (?, ?, ?, ?, '881001', ?, ?, ?)",
                (f"beta-{provider}-identity", internal_id, legacy_id, provider, OLD_DATE, OLD_DATE, OLD_DATE),
            )
    before = billing_snapshot()
    response = beta_client.post(f"/api/auth/{provider}-v2", json=signed_provider_payload(provider))
    assert response.status_code == 200, response.text
    assert response.json()["legacy_user_id"] == legacy_id
    assert response.json()["internal_user_id"]
    if internal_id:
        assert response.json()["internal_user_id"] == internal_id
    assert billing_snapshot() == before
    with closing(main.db()) as conn:
        row = conn.execute("SELECT internal_user_id FROM users WHERE id=?", (legacy_id,)).fetchone()
        assert row["internal_user_id"] == response.json()["internal_user_id"]
        assert conn.execute(
            "SELECT COUNT(*) FROM auth_identities WHERE provider=? AND provider_user_id='881001'", (provider,),
        ).fetchone()[0] == 1


@pytest.mark.parametrize("unverified_profile_email", [False, True])
def test_email_creation_callback_runs_before_insert_and_never_adopts_profile_email(beta_client, unverified_profile_email):
    if unverified_profile_email:
        seed_email(identity=False)
    before = snapshot()
    with pytest.raises(main.HTTPException) as error:
        with closing(main.db()) as conn, conn:
            upsert_web_email_identity(
                conn, EMAIL, OLD_DATE, initialize_intro=False,
                random_avatar_choice=forbidden, initialize_intro_tariff=forbidden,
                require_account_creation=main.require_public_account_creation_allowed,
            )
    assert error.value.status_code == 403
    assert error.value.detail == "closed_beta_registration_disabled"
    assert snapshot() == before


def test_existing_email_identity_bypasses_new_account_callback(beta_client):
    seed_email()
    before = billing_snapshot()
    with closing(main.db()) as conn, conn:
        result = upsert_web_email_identity(
            conn, EMAIL, datetime.now(timezone.utc).isoformat(), initialize_intro=False,
            random_avatar_choice=forbidden, initialize_intro_tariff=forbidden,
            require_account_creation=forbidden,
        )
    assert result == (INTERNAL_ID, USER_ID)
    assert billing_snapshot() == before


@pytest.mark.parametrize("existing_identity", [False, True])
def test_verified_email_otp_only_authenticates_existing_accounts(beta_client, existing_identity):
    if existing_identity:
        seed_email()
    now = datetime.now(timezone.utc)
    code = "731946"
    with closing(main.db()) as conn, conn:
        conn.execute(
            "INSERT INTO auth_otp_challenges (id, channel, destination, code_hash, purpose, "
            "max_attempts, expires_at, created_at) VALUES "
            "('beta-challenge', 'email', ?, ?, 'login', 5, ?, ?)",
            (EMAIL, main.hash_otp(code), (now + timedelta(minutes=5)).isoformat(), now.isoformat()),
        )
    before = snapshot()
    billing_before = billing_snapshot()
    response = beta_client.post("/api/auth/email/verify-code-v2", json={
        "challenge_id": "beta-challenge", "code": code, "platform": "web_desktop",
    })
    if existing_identity:
        assert response.status_code == 200, response.text
        assert response.json()["legacy_user_id"] == USER_ID
        assert len(snapshot()["users"]) == len(before["users"])
        assert billing_snapshot() == billing_before
    else:
        assert_denied(response)
        assert snapshot() == before
    with closing(main.db()) as conn:
        consumed = conn.execute("SELECT consumed_at FROM auth_otp_challenges WHERE id='beta-challenge'").fetchone()[0]
    assert (consumed is not None) is existing_identity


def test_existing_password_hash_authenticates_without_balance_or_ledger_changes(beta_client):
    stored_hash = seed_email(password=True)
    before = billing_snapshot()
    response = beta_client.post("/api/auth/password/login-v2", json={
        "email": EMAIL, "password": PASSWORD, "platform": "web_desktop",
    })
    assert response.status_code == 200, response.text
    assert response.json()["internal_user_id"] == INTERNAL_ID
    assert response.json()["legacy_user_id"] == USER_ID
    cookie_headers = " ".join(response.headers.get_list("set-cookie")).lower()
    assert "httponly" in cookie_headers
    assert main.TRUSTED_SESSION_COOKIE_NAME + "=" in cookie_headers
    assert main.TRUSTED_REFRESH_COOKIE_NAME + "=" in cookie_headers
    token = response.cookies[main.TRUSTED_SESSION_COOKIE_NAME]
    with closing(main.db()) as conn:
        assert conn.execute("SELECT password_hash FROM auth_passwords WHERE id='beta-password'").fetchone()[0] == stored_hash
        session = conn.execute("SELECT internal_user_id, legacy_user_id FROM auth_sessions WHERE session_token_hash=?", (main.hash_token(token),)).fetchone()
        assert tuple(session) == (INTERNAL_ID, USER_ID)
    assert billing_snapshot() == before


@pytest.mark.parametrize("banned, password, status", [(False, "incorrect-synthetic-password", 401), (True, PASSWORD, 403)])
def test_closed_beta_preserves_wrong_password_and_banned_checks(beta_client, banned, password, status):
    seed_email(password=True)
    if banned:
        with closing(main.db()) as conn, conn:
            conn.execute("UPDATE users SET banned=1 WHERE id=?", (USER_ID,))
    before = snapshot()
    response = beta_client.post("/api/auth/password/login-v2", json={"email": EMAIL, "password": password})
    assert response.status_code == status, response.text
    assert "set-cookie" not in response.headers
    assert snapshot() == before


def test_anonymous_v2_bootstrap_is_still_device_only(beta_client):
    before = snapshot()
    response = beta_client.post("/api/auth/bootstrap-v2", json={
        "platform": "web_desktop", "installation_id": "beta-anonymous-installation",
        "user_id": USER_ID, "internal_user_id": INTERNAL_ID, "role": "admin",
    })
    assert response.status_code == 200, response.text
    assert response.json()["is_authenticated"] is False
    assert snapshot() == before
    with closing(main.db()) as conn:
        row = conn.execute(
            "SELECT internal_user_id, legacy_user_id FROM device_installations WHERE installation_id='beta-anonymous-installation'",
        ).fetchone()
    assert tuple(row) == (None, None)


def test_registration_remains_available_when_closed_beta_is_explicitly_disabled(beta_client, monkeypatch):
    monkeypatch.setenv("IZO_CLOSED_BETA", "0")
    before = len(snapshot()["users"])
    response = beta_client.post("/api/auth/password/register-v2", json=registration_payload("open-mode@example.com"))
    assert response.status_code == 200, response.text
    assert len(snapshot()["users"]) == before + 1
    assert beta_client.get("/api/auth/capabilities-v2").json()["password_register_available"] is True
