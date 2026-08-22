"""Real MAX/Telegram proof gate for password registrations.

All provider operations are fake and every test uses a temporary SQLite file.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

import main
from test_support.browser_origin import BROWSER_ORIGIN


PASSWORD = "S3cret-Password!"


@pytest.fixture
def production_db(tmp_path: Path, monkeypatch):
    db_file = tmp_path / "social-verification.sqlite3"
    monkeypatch.setattr(main, "DB_PATH", db_file)
    monkeypatch.setattr(main, "APP_ENV", "production")
    monkeypatch.setattr(main, "SESSION_HMAC_SECRET", "social-verification-test-secret")
    monkeypatch.setattr(main, "EMAIL_PROVIDER", "")
    monkeypatch.setattr(main, "EMAIL_OTP_DEBUG_RETURN_CODE", False)
    monkeypatch.setattr(main, "TELEGRAM_BOT_TOKEN", "fake-telegram-token")
    monkeypatch.setattr(main, "TELEGRAM_BOT_USERNAME", "onenode_test_bot")
    monkeypatch.setattr(main, "TELEGRAM_BOT_DEEP_LINK_BASE", "https://t.me/onenode_test_bot")
    monkeypatch.setattr(main, "MAX_BOT_TOKEN", "fake-max-token")
    monkeypatch.setattr(main, "MAX_BOT_DEEP_LINK_BASE", "https://max.ru/onenode-test")
    monkeypatch.setattr(main, "TRUSTED_COOKIE_SECURE", False)
    main.BOT_RUNTIME.max_deep_link_cache.update(
        {"attempted": False, "base": None, "source": "unresolved", "resolved": False,
         "api_status": None, "fields": []}
    )
    main.init_db()
    yield db_file
    main.BOT_RUNTIME.max_deep_link_cache.update(
        {"attempted": False, "base": None, "source": "unresolved", "resolved": False,
         "api_status": None, "fields": []}
    )


def register(client: TestClient, email: str):
    return client.post(
        "/api/auth/password/register-v2",
        json={
            "email": email,
            "password": PASSWORD,
            "password_repeat": PASSWORD,
            "accepted_terms": True,
            "accepted_privacy": True,
            "accepted_personal_data": True,
            "platform": "web_desktop",
        },
        headers=BROWSER_ORIGIN,
    )


def login(client: TestClient, email: str):
    return client.post(
        "/api/auth/password/login-v2",
        json={"email": email, "password": PASSWORD, "platform": "web_desktop"},
        headers=BROWSER_ORIGIN,
    )


def challenge_token(deep_link: str) -> str:
    query = parse_qs(urlparse(deep_link).query)
    payload = next(
        (values[0] for key, values in query.items() if key in {"start", "startapp"} and values),
        "",
    )
    assert payload.startswith("login_")
    return payload.removeprefix("login_")


def test_registration_is_limited_until_real_social_proof(production_db):
    client = TestClient(main.app)
    created = register(client, "pending@example.com")
    assert created.status_code == 200
    payload = created.json()
    assert payload["social_verification_pending"] is True
    assert payload["social_verification_blocks_generation"] is True
    assert payload["should_prompt_social_verification"] is False
    assert payload["social_verification_options"] == {"telegram": True, "max": True}

    with main.db() as conn:
        user = conn.execute(
            "SELECT plan, token_balance, gallery_enabled FROM users WHERE internal_user_id=?",
            (payload["internal_user_id"],),
        ).fetchone()
        identity = conn.execute(
            "SELECT verified_at FROM auth_identities WHERE internal_user_id=? AND provider='web_email'",
            (payload["internal_user_id"],),
        ).fetchone()
    assert dict(user) == {"plan": "free", "token_balance": 0, "gallery_enabled": 0}
    assert identity["verified_at"] is None

    me = client.get("/api/me-v2")
    assert me.status_code == 200
    assert me.json()["account"]["social_verification"]["social_verification_pending"] is True

    image = client.post(
        "/api/generate",
        json={"mode": "text_to_image", "provider": "comfyui", "prompt": "must not run"},
        headers=BROWSER_ORIGIN,
    )
    assert image.status_code == 403
    assert image.json()["detail"]["code"] == "social_verification_required"

    video = client.post(
        "/api/video/generate",
        json={
            "mode": "text_to_video", "model": "fake-model", "prompt": "must not run",
            "duration": 5, "resolution": "720p", "aspectRatio": "16:9",
        },
        headers=BROWSER_ORIGIN,
    )
    assert video.status_code == 403
    assert video.json()["detail"]["code"] == "social_verification_required"


def test_next_login_prompts_only_after_24_hours(production_db):
    created = register(TestClient(main.app), "reminder@example.com").json()
    before = login(TestClient(main.app), "reminder@example.com")
    assert before.status_code == 200
    assert before.json()["should_prompt_social_verification"] is False

    now = datetime.now(timezone.utc)
    with main.db() as conn:
        conn.execute(
            "UPDATE account_verifications SET remind_after_at=?, delete_after_at=? WHERE internal_user_id=?",
            ((now - timedelta(seconds=1)).isoformat(), (now + timedelta(days=29)).isoformat(),
             created["internal_user_id"]),
        )
    after = login(TestClient(main.app), "reminder@example.com")
    assert after.status_code == 200
    assert after.json()["should_prompt_social_verification"] is True


@pytest.mark.parametrize("provider", ["max", "telegram"])
def test_verified_bot_identity_unlocks_same_account_idempotently(production_db, provider):
    client = TestClient(main.app)
    created = register(client, f"proof-{provider}@example.com").json()
    started = client.post(
        "/api/auth/link/bot/start",
        json={"provider": provider},
        headers=BROWSER_ORIGIN,
    )
    assert started.status_code == 200
    token = challenge_token(started.json()["deep_link"])
    provider_user = {"id": f"real-{provider}-user", "username": "proof_user"}

    for _ in range(5):
        assert main.approve_bot_login_challenge(provider, token, provider_user) is True

    status = client.get("/api/auth/bot-login/status")
    assert status.status_code == 200
    assert status.json()["status"] == "authenticated"
    with main.db() as conn:
        verification = conn.execute(
            "SELECT status, verified_provider FROM account_verifications WHERE internal_user_id=?",
            (created["internal_user_id"],),
        ).fetchone()
        user = conn.execute(
            "SELECT plan, token_balance, plan_started_at FROM users WHERE internal_user_id=?",
            (created["internal_user_id"],),
        ).fetchone()
        identities = conn.execute(
            "SELECT COUNT(*) c FROM auth_identities WHERE internal_user_id=? AND provider=? AND verified_at IS NOT NULL",
            (created["internal_user_id"], provider),
        ).fetchone()["c"]
    assert dict(verification) == {"status": "verified", "verified_provider": provider}
    assert identities == 1
    assert user["plan"] == "mini" and user["token_balance"] > 0 and user["plan_started_at"]

    later = login(TestClient(main.app), f"proof-{provider}@example.com")
    assert later.status_code == 200
    assert later.json()["social_verification_pending"] is False


def test_registration_fails_closed_when_no_confirmation_bot_exists(production_db, monkeypatch):
    monkeypatch.setattr(main, "bot_login_available", lambda _provider: False)
    response = register(TestClient(main.app), "no-confirmation@example.com")
    assert response.status_code == 503
    with main.db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM users WHERE email=?", ("no-confirmation@example.com",)).fetchone()[0] == 0


def test_due_cleanup_anonymizes_access_but_preserves_finance(production_db):
    created = register(TestClient(main.app), "expired@example.com").json()
    now = datetime.now(timezone.utc).isoformat()
    with main.db() as conn:
        conn.execute(
            "UPDATE account_verifications SET delete_after_at=? WHERE internal_user_id=?",
            (now, created["internal_user_id"]),
        )
        conn.execute(
            "INSERT INTO invoices (id, invoice_code, internal_user_id, user_id, status, created_at, updated_at) "
            "VALUES ('retained-invoice', 'RET-1', ?, ?, 'paid', ?, ?)",
            (created["internal_user_id"], created["legacy_user_id"], now, now),
        )

    report = main.cleanup_due_unverified_accounts(
        main.db, now=now, record_security_event=main.record_security_event,
    )
    assert report == {"checked": 1, "deleted": 1, "reconciled": 0, "protected": 0}
    assert main.cleanup_due_unverified_accounts(main.db, now=now)["deleted"] == 0
    with main.db() as conn:
        user = conn.execute(
            "SELECT banned, email, display_name FROM users WHERE internal_user_id=?",
            (created["internal_user_id"],),
        ).fetchone()
        verification = conn.execute(
            "SELECT status FROM account_verifications WHERE internal_user_id=?",
            (created["internal_user_id"],),
        ).fetchone()
        invoice = conn.execute("SELECT status FROM invoices WHERE id='retained-invoice'").fetchone()
    assert dict(user) == {"banned": 1, "email": None, "display_name": "Удалённый пользователь"}
    assert verification["status"] == "deleted"
    assert invoice["status"] == "paid"
    assert login(TestClient(main.app), "expired@example.com").status_code == 401


def test_migration_is_idempotent(production_db):
    main.init_db()
    main.init_db()
    with main.db() as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 4
        assert conn.execute(
            "SELECT COUNT(*) FROM schema_migrations WHERE name='social_account_verification'"
        ).fetchone()[0] == 1
