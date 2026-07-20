"""Identity Core session service tests (Phase 4).

All tests use a TEMPORARY SQLite file via monkeypatching main.DB_PATH.
The working database backend/onenode.sqlite3 is never touched.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import main
from test_support.browser_client import BrowserTestClient


NOW = "2026-06-25T00:00:00+00:00"


@pytest.fixture
def temp_db(tmp_path: Path, monkeypatch):
    db_file = tmp_path / "session_test.sqlite3"
    monkeypatch.setattr(main, "DB_PATH", db_file)
    main.init_db()
    return db_file


def make_user(internal_user_id="iuid-1", legacy_user_id="telegram_1", banned=0):
    with main.db() as conn:
        conn.execute(
            """
            INSERT INTO users (id, internal_user_id, language, role, created_at, last_login_at, banned)
            VALUES (?, ?, 'ru', 'user', ?, ?, ?)
            """,
            (legacy_user_id, internal_user_id, NOW, NOW, banned),
        )
    return internal_user_id, legacy_user_id


def get_session_row(token_hash):
    with main.db() as conn:
        return conn.execute(
            "SELECT * FROM auth_sessions WHERE session_token_hash = ?", (token_hash,)
        ).fetchone()


def count(table, where="", params=()):
    with main.db() as conn:
        return conn.execute(f"SELECT COUNT(*) AS c FROM {table} {where}", params).fetchone()["c"]


# 1-5: hashing / no raw token storage
def test_create_session_stores_only_hashes(temp_db):
    iuid, legacy = make_user()
    created = main.create_auth_session(iuid, legacy, provider="telegram", platform="telegram")
    raw_session = created["session_token"]
    raw_refresh = created["refresh_token"]
    with main.db() as conn:
        row = conn.execute("SELECT * FROM auth_sessions").fetchone()
    # 2 & 3: hashes present
    assert row["session_token_hash"]
    assert row["refresh_token_hash"]
    # 1: stored hashes != raw tokens
    assert row["session_token_hash"] != raw_session
    assert row["refresh_token_hash"] != raw_refresh
    assert row["session_token_hash"] == main.hash_token(raw_session)
    # 4 & 5: raw tokens not present anywhere in the row
    blob = " ".join(str(v) for v in tuple(row))
    assert raw_session not in blob
    assert raw_refresh not in blob


# 6
def test_resolve_valid_session(temp_db):
    iuid, legacy = make_user()
    created = main.create_auth_session(iuid, legacy)
    with TestClient(main.app) as client:
        r = client.get("/api/auth/sessions-v2", headers={"Authorization": f"Bearer {created['session_token']}"})
    assert r.status_code == 200
    body = r.json()
    assert body["currentSessionId"] == created["session_id"]


# 7
def test_resolve_invalid_session_fails(temp_db):
    make_user()
    with TestClient(main.app) as client:
        r = client.get("/api/auth/sessions-v2", headers={"Authorization": "Bearer not-a-real-token"})
    assert r.status_code == 401
    assert count("security_events", "WHERE event_type = 'session_invalid'") == 1


# 8
def test_expired_session_fails(temp_db):
    iuid, legacy = make_user()
    created = main.create_auth_session(iuid, legacy)
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    with main.db() as conn:
        conn.execute("UPDATE auth_sessions SET expires_at = ? WHERE id = ?", (past, created["session_id"]))
    with TestClient(main.app) as client:
        r = client.get("/api/auth/sessions-v2", headers={"Authorization": f"Bearer {created['session_token']}"})
    assert r.status_code == 401
    assert count("security_events", "WHERE event_type = 'session_expired'") == 1


# 9 & 13
def test_revoked_session_cannot_be_resolved(temp_db):
    iuid, legacy = make_user()
    created = main.create_auth_session(iuid, legacy)
    main.revoke_auth_session(created["session_id"], reason="manual")
    with TestClient(main.app) as client:
        r = client.get("/api/auth/sessions-v2", headers={"Authorization": f"Bearer {created['session_token']}"})
    assert r.status_code == 401
    assert count("security_events", "WHERE event_type = 'session_revoked'") == 1


# 10
def test_refresh_returns_new_tokens(temp_db):
    iuid, legacy = make_user()
    created = main.create_auth_session(iuid, legacy)
    with TestClient(main.app) as client:
        r = client.post("/api/auth/session/refresh-v2", json={"refresh_token": created["refresh_token"]})
    assert r.status_code == 200
    body = r.json()
    assert body["session_token"] and body["session_token"] != created["session_token"]
    assert body["refresh_token"] and body["refresh_token"] != created["refresh_token"]
    assert body["expires_at"]


# 11
def test_old_refresh_token_cannot_be_reused(temp_db):
    iuid, legacy = make_user()
    created = main.create_auth_session(iuid, legacy)
    # Browser flow: the first refresh stores rotated cookies, the second
    # refresh is an unsafe request from the same browser (AUTH-LEGACY-001B).
    with BrowserTestClient(main.app) as client:
        first = client.post("/api/auth/session/refresh-v2", json={"refresh_token": created["refresh_token"]})
        assert first.status_code == 200
        # reusing the old refresh token must now fail
        reuse = client.post("/api/auth/session/refresh-v2", json={"refresh_token": created["refresh_token"]})
    assert reuse.status_code == 401


# 12
def test_logout_revokes_session(temp_db):
    iuid, legacy = make_user()
    created = main.create_auth_session(iuid, legacy)
    with TestClient(main.app) as client:
        r = client.post("/api/auth/session/logout-v2", json={"session_token": created["session_token"]})
        assert r.status_code == 200
        assert r.json()["ok"] is True
        again = client.get("/api/auth/sessions-v2", headers={"Authorization": f"Bearer {created['session_token']}"})
    assert again.status_code == 401
    with main.db() as conn:
        row = conn.execute("SELECT revoked_at, revoke_reason FROM auth_sessions WHERE id = ?", (created["session_id"],)).fetchone()
    assert row["revoked_at"] is not None
    assert row["revoke_reason"] == "logout"


# 14
def test_banned_user_cannot_refresh(temp_db):
    iuid, legacy = make_user(internal_user_id="iuid-ban", legacy_user_id="telegram_ban", banned=1)
    created = main.create_auth_session(iuid, legacy)
    with TestClient(main.app) as client:
        r = client.post("/api/auth/session/refresh-v2", json={"refresh_token": created["refresh_token"]})
    assert r.status_code == 403
    assert count("security_events", "WHERE event_type = 'refresh_user_banned'") == 1


# 15
def test_sessions_v2_does_not_expose_token_hashes(temp_db):
    iuid, legacy = make_user()
    created = main.create_auth_session(iuid, legacy)
    with TestClient(main.app) as client:
        r = client.get("/api/auth/sessions-v2", headers={"Authorization": f"Bearer {created['session_token']}"})
    body = r.json()
    assert body["sessions"]
    for s in body["sessions"]:
        assert "session_token_hash" not in s
        assert "refresh_token_hash" not in s
    # And no hash value leaks into the serialized payload.
    with main.db() as conn:
        hashes = conn.execute("SELECT session_token_hash, refresh_token_hash FROM auth_sessions").fetchone()
    assert hashes["session_token_hash"] not in r.text
    assert hashes["refresh_token_hash"] not in r.text


# 16
def test_security_events_written_for_failures(temp_db):
    iuid, legacy = make_user()
    created = main.create_auth_session(iuid, legacy)
    # invalid
    with TestClient(main.app) as client:
        client.get("/api/auth/sessions-v2", headers={"Authorization": "Bearer wrong"})
    # revoked
    main.revoke_auth_session(created["session_id"], reason="manual")
    with TestClient(main.app) as client:
        client.get("/api/auth/sessions-v2", headers={"Authorization": f"Bearer {created['session_token']}"})
    assert count("security_events", "WHERE event_type = 'session_invalid'") == 1
    assert count("security_events", "WHERE event_type = 'session_revoked'") == 1


# 17
def test_session_events_lifecycle(temp_db):
    iuid, legacy = make_user()
    created = main.create_auth_session(iuid, legacy)
    assert count("session_events", "WHERE event_type = 'created'") == 1
    with TestClient(main.app) as client:
        client.post("/api/auth/session/refresh-v2", json={"refresh_token": created["refresh_token"]})
    assert count("session_events", "WHERE event_type = 'refreshed'") == 1
    # the rotated-new session also logs a 'created'
    assert count("session_events", "WHERE event_type = 'created'") == 2
    with TestClient(main.app) as client:
        # logout the new (current) session via a fresh create to isolate
        c2 = main.create_auth_session(iuid, legacy)
        client.post("/api/auth/session/logout-v2", json={"session_token": c2["session_token"]})
    assert count("session_events", "WHERE event_type = 'logout'") == 1


# Extra: resolver must ignore X-OneNode-User / legacy cookie entirely.
def test_resolver_ignores_legacy_identity_headers(temp_db):
    make_user(internal_user_id="iuid-admin", legacy_user_id="admin")
    with TestClient(main.app) as client:
        r = client.get(
            "/api/auth/sessions-v2",
            headers={"X-OneNode-User": "admin"},
            cookies={"onenode_user": "admin"},
        )
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# Phase 4.1 hardening: split TTLs + production secret requirement
# ---------------------------------------------------------------------------

def _seconds_between(later_iso: str, earlier_iso: str) -> float:
    return (datetime.fromisoformat(later_iso) - datetime.fromisoformat(earlier_iso)).total_seconds()


# access/session token expires according to SESSION_ACCESS_TTL_SECONDS
def test_access_expiry_uses_access_ttl(temp_db, monkeypatch):
    monkeypatch.setattr(main, "SESSION_ACCESS_TTL_SECONDS", 900)
    monkeypatch.setattr(main, "SESSION_REFRESH_TTL_SECONDS", 2592000)
    iuid, legacy = make_user()
    created = main.create_auth_session(iuid, legacy)
    with main.db() as conn:
        row = conn.execute("SELECT created_at, expires_at FROM auth_sessions WHERE id = ?", (created["session_id"],)).fetchone()
    assert abs(_seconds_between(row["expires_at"], row["created_at"]) - 900) < 5


# refresh token expires according to SESSION_REFRESH_TTL_SECONDS
def test_refresh_expiry_uses_refresh_ttl(temp_db, monkeypatch):
    monkeypatch.setattr(main, "SESSION_ACCESS_TTL_SECONDS", 900)
    monkeypatch.setattr(main, "SESSION_REFRESH_TTL_SECONDS", 2592000)
    iuid, legacy = make_user()
    created = main.create_auth_session(iuid, legacy)
    with main.db() as conn:
        row = conn.execute("SELECT created_at, refresh_expires_at FROM auth_sessions WHERE id = ?", (created["session_id"],)).fetchone()
    assert row["refresh_expires_at"] is not None
    assert abs(_seconds_between(row["refresh_expires_at"], row["created_at"]) - 2592000) < 5


# refresh_expires_at is stored (column added by init_db)
def test_refresh_expires_at_is_stored(temp_db):
    with main.db() as conn:
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(auth_sessions)")}
    assert "refresh_expires_at" in cols
    iuid, legacy = make_user()
    created = main.create_auth_session(iuid, legacy)
    with main.db() as conn:
        val = conn.execute("SELECT refresh_expires_at FROM auth_sessions WHERE id = ?", (created["session_id"],)).fetchone()["refresh_expires_at"]
    assert val is not None
    assert created["refresh_expires_at"] == val


# expired access token cannot resolve, but split lifetimes let refresh still work
def test_expired_access_still_allows_refresh(temp_db, monkeypatch):
    # Access already expired, refresh still valid.
    monkeypatch.setattr(main, "SESSION_ACCESS_TTL_SECONDS", -1)
    monkeypatch.setattr(main, "SESSION_REFRESH_TTL_SECONDS", 2592000)
    iuid, legacy = make_user()
    created = main.create_auth_session(iuid, legacy)
    with TestClient(main.app) as client:
        # access token is expired -> resolve fails
        resolve = client.get("/api/auth/sessions-v2", headers={"Authorization": f"Bearer {created['session_token']}"})
        assert resolve.status_code == 401
        # refresh still works because refresh lifetime is independent
        refreshed = client.post("/api/auth/session/refresh-v2", json={"refresh_token": created["refresh_token"]})
    assert refreshed.status_code == 200


# expired refresh token cannot refresh
def test_expired_refresh_cannot_refresh(temp_db, monkeypatch):
    monkeypatch.setattr(main, "SESSION_ACCESS_TTL_SECONDS", 900)
    monkeypatch.setattr(main, "SESSION_REFRESH_TTL_SECONDS", -1)  # refresh already expired
    iuid, legacy = make_user()
    created = main.create_auth_session(iuid, legacy)
    with TestClient(main.app) as client:
        r = client.post("/api/auth/session/refresh-v2", json={"refresh_token": created["refresh_token"]})
    assert r.status_code == 401
    assert count("security_events", "WHERE event_type = 'refresh_expired'") == 1


# production without SESSION_HMAC_SECRET fails config validation
def test_production_without_secret_fails_validation(temp_db, monkeypatch):
    monkeypatch.setattr(main, "APP_ENV", "production")
    monkeypatch.setattr(main, "SESSION_HMAC_SECRET", "")
    with pytest.raises(RuntimeError):
        main.validate_session_crypto_config()
    # and session creation refuses too
    iuid, legacy = make_user()
    with pytest.raises(RuntimeError):
        main.create_auth_session(iuid, legacy)


def test_production_secret_not_leaked_in_error(temp_db, monkeypatch):
    monkeypatch.setattr(main, "APP_ENV", "production")
    monkeypatch.setattr(main, "SESSION_HMAC_SECRET", "")
    try:
        main.validate_session_crypto_config()
    except RuntimeError as exc:
        assert "super-secret" not in str(exc)
        assert "SESSION_HMAC_SECRET" in str(exc)


# development without SESSION_HMAC_SECRET still works
def test_development_without_secret_still_works(temp_db, monkeypatch):
    monkeypatch.setattr(main, "APP_ENV", "development")
    monkeypatch.setattr(main, "SESSION_HMAC_SECRET", "")
    iuid, legacy = make_user()
    created = main.create_auth_session(iuid, legacy)  # must not raise
    assert created["session_token"]
    with main.db() as conn:
        row = conn.execute("SELECT session_token_hash FROM auth_sessions").fetchone()
    # plain SHA-256 fallback is used in dev
    assert row["session_token_hash"] == main.hash_token(created["session_token"])


# production WITH secret works and uses HMAC
def test_production_with_secret_uses_hmac(temp_db, monkeypatch):
    monkeypatch.setattr(main, "APP_ENV", "production")
    monkeypatch.setattr(main, "SESSION_HMAC_SECRET", "unit-test-secret")
    iuid, legacy = make_user()
    created = main.create_auth_session(iuid, legacy)  # must not raise
    import hmac as _hmac, hashlib as _hashlib
    expected = _hmac.new(b"unit-test-secret", created["session_token"].encode(), _hashlib.sha256).hexdigest()
    with main.db() as conn:
        row = conn.execute("SELECT session_token_hash FROM auth_sessions").fetchone()
    assert row["session_token_hash"] == expected


# raw tokens still not stored after the TTL changes
def test_raw_tokens_still_not_stored_after_hardening(temp_db):
    iuid, legacy = make_user()
    created = main.create_auth_session(iuid, legacy)
    with main.db() as conn:
        row = conn.execute("SELECT * FROM auth_sessions").fetchone()
    blob = " ".join(str(v) for v in tuple(row))
    assert created["session_token"] not in blob
    assert created["refresh_token"] not in blob
