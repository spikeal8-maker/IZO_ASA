"""Security hotfix 2026-06-29: demo_user + SESSION_HMAC_SECRET guards.

Temporary SQLite DB via monkeypatching main.DB_PATH; working DB never touched.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

import main


def count(table, where="", params=()):
    with main.db() as conn:
        return conn.execute(f"SELECT COUNT(*) AS c FROM {table} {where}", params).fetchone()["c"]


@pytest.fixture
def temp_db(tmp_path: Path, monkeypatch):
    db_file = tmp_path / "hotfix_test.sqlite3"
    monkeypatch.setattr(main, "DB_PATH", db_file)
    monkeypatch.setattr(main, "APP_ENV", "development")
    monkeypatch.setattr(main, "TRUSTED_COOKIE_SECURE", False)
    main.init_db()
    return db_file


# ---------------------------------------------------------------------------
# 1. request_user_id() — production without auth raises 401
# ---------------------------------------------------------------------------

def test_request_user_id_dev_fallback_unchanged(temp_db, monkeypatch):
    monkeypatch.setattr(main, "APP_ENV", "development")
    req = Request(scope={"type": "http", "headers": []})
    uid = main.request_user_id(req)
    assert uid == "demo_user"


def test_request_user_id_prod_no_auth_401(temp_db, monkeypatch):
    monkeypatch.setattr(main, "APP_ENV", "production")
    req = Request(scope={"type": "http", "headers": []})
    with pytest.raises(main.HTTPException) as exc:
        main.request_user_id(req)
    assert exc.value.status_code == 401


def test_request_user_id_prod_with_header_works(temp_db, monkeypatch):
    monkeypatch.setattr(main, "APP_ENV", "production")
    req = Request(scope={"type": "http", "headers": [
        (b"x-onenode-user", b"telegram_123"),
    ]})
    uid = main.request_user_id(req)
    assert uid == "telegram_123"


def test_request_user_id_none_request_unchanged(temp_db, monkeypatch):
    monkeypatch.setattr(main, "APP_ENV", "production")
    uid = main.request_user_id(None)
    assert uid == "demo_user"


# ---------------------------------------------------------------------------
# 2. /app/bootstrap — production without valid userId raises 401
# ---------------------------------------------------------------------------

def test_bootstrap_dev_fallback_unchanged(temp_db, monkeypatch):
    monkeypatch.setattr(main, "APP_ENV", "development")
    with TestClient(main.app) as c:
        r = c.post("/api/app/bootstrap", json={
            "platform": "web",
            "userId": "",
        })
    assert r.status_code == 200
    assert r.json()["user"]["id"] == "demo_user"


@pytest.fixture
def temp_db_prod(tmp_path: Path, monkeypatch):
    db_file = tmp_path / "hotfix_prod_test.sqlite3"
    monkeypatch.setattr(main, "DB_PATH", db_file)
    monkeypatch.setattr(main, "APP_ENV", "production")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")
    monkeypatch.setattr(main, "TRUSTED_COOKIE_SECURE", False)
    monkeypatch.setattr(main, "SESSION_HMAC_SECRET", "test-secret")
    monkeypatch.setattr(main, "DB_GUARD_MIN_SIZE_MB", 0.0)
    monkeypatch.setattr(main, "DB_GUARD_MIN_USERS", 1)
    monkeypatch.setattr(main, "DB_GUARD_MIN_ACTIVE_ADMINS", 1)
    main.init_db()
    now = "2026-01-01T00:00:00+00:00"
    with main.db() as conn:
        conn.execute(
            "INSERT INTO users (id, internal_user_id, language, role, created_at, last_login_at) "
            "VALUES (?, ?, 'ru', 'admin', ?, ?)",
            ("web_admin", "iuid-admin", now, now),
        )
    return db_file


def test_bootstrap_prod_no_user_id_401(temp_db_prod):
    with TestClient(main.app) as c:
        r = c.post("/api/app/bootstrap", json={
            "platform": "web",
            "userId": "",
        })
    assert r.status_code == 401


def test_bootstrap_prod_demo_user_id_401(temp_db_prod):
    with TestClient(main.app) as c:
        r = c.post("/api/app/bootstrap", json={
            "platform": "web",
            "userId": "demo_user",
        })
    assert r.status_code == 401


def test_bootstrap_prod_with_real_user_works(temp_db_prod):
    with TestClient(main.app) as c:
        r = c.post("/api/app/bootstrap", json={
            "platform": "web",
            "userId": "web_real_user",
        })
    assert r.status_code == 200
    assert r.json()["user"]["id"] == "web_real_user"


# ---------------------------------------------------------------------------
# 3. validate_session_crypto_config() — production empty secret fails at startup
# ---------------------------------------------------------------------------

def test_prod_empty_secret_startup_fails(temp_db, monkeypatch):
    monkeypatch.setattr(main, "APP_ENV", "production")
    monkeypatch.setattr(main, "SESSION_HMAC_SECRET", "")
    with pytest.raises(RuntimeError) as exc:
        main.validate_session_crypto_config()
    assert "SESSION_HMAC_SECRET" in str(exc.value)


def test_prod_with_secret_passes(temp_db, monkeypatch):
    monkeypatch.setattr(main, "APP_ENV", "production")
    monkeypatch.setattr(main, "SESSION_HMAC_SECRET", "prod-secret-here")
    main.validate_session_crypto_config()


def test_dev_empty_secret_no_error(temp_db, monkeypatch):
    monkeypatch.setattr(main, "APP_ENV", "development")
    monkeypatch.setattr(main, "SESSION_HMAC_SECRET", "")
    main.validate_session_crypto_config()


# ---------------------------------------------------------------------------
# 4. dev/test fallback from request_user_id for require_admin
# ---------------------------------------------------------------------------

def test_require_admin_dev_still_blocks_demo_user(temp_db, monkeypatch):
    monkeypatch.setattr(main, "APP_ENV", "development")
    req = Request(scope={"type": "http", "headers": []})
    with pytest.raises(main.HTTPException) as exc:
        main.require_admin(req)
    assert exc.value.status_code == 403


def test_users_id_not_changed(temp_db, monkeypatch):
    monkeypatch.setattr(main, "APP_ENV", "production")
    monkeypatch.setattr(main, "SESSION_HMAC_SECRET", "test")
    now = "2026-01-01T00:00:00+00:00"
    with main.db() as conn:
        conn.execute(
            "INSERT INTO users (id, internal_user_id, language, role, created_at, last_login_at) "
            "VALUES ('web_test', 'iuid-test', 'ru', 'user', ?, ?)",
            (now, now),
        )
    with main.db() as conn:
        row = conn.execute("SELECT id FROM users WHERE id = 'web_test'").fetchone()
    assert row["id"] == "web_test"
