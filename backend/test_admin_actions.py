"""Trusted per-user admin actions tests (Phase 20C). Temp DB; no live DB."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from test_support.browser_client import BrowserTestClient

import main

PW = "S3cret-Password!"


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "admin_actions_test.sqlite3"
    monkeypatch.setattr(main, "DB_PATH", db_file)
    monkeypatch.setattr(main, "TRUSTED_COOKIE_SECURE", False)
    main.init_db()
    return db_file


def count(table, where="", params=()):
    with main.db() as conn:
        return conn.execute(f"SELECT COUNT(*) AS c FROM {table} {where}", params).fetchone()["c"]


def make_user(iuid, legacy, role="user", banned=0, balance=50, plan="mini"):
    with main.db() as conn:
        conn.execute("INSERT INTO users (id, internal_user_id, role, banned, token_balance, plan, language, created_at, last_login_at) "
                     "VALUES (?, ?, ?, ?, ?, ?, 'ru', '2026-01-01', '2026-01-01')", (legacy, iuid, role, banned, balance, plan))


def admin_token(iuid="iuid-admin", legacy="telegram_admin"):
    make_user(iuid, legacy, role="admin")
    return main.create_auth_session(iuid, legacy, provider="telegram", platform="telegram_mini_app")["session_token"]


def bearer(t):
    return {"Authorization": f"Bearer {t}"}


# Role: 1,2
def test_role_requires_session_and_admin(temp_db):
    make_user("iuid-1", "telegram_1")
    with BrowserTestClient(main.app) as c:
        assert c.post("/api/admin/users/iuid-1/role-v2", json={"role": "admin", "reason": "x"}).status_code == 401
    make_user("iuid-u", "telegram_u")
    tok = main.create_auth_session("iuid-u", "telegram_u", provider="telegram", platform="telegram_mini_app")["session_token"]
    with BrowserTestClient(main.app) as c:
        assert c.post("/api/admin/users/iuid-1/role-v2", json={"role": "admin", "reason": "x"}, headers=bearer(tok)).status_code == 403


# Role: 3, 5, 6
def test_role_change_and_logs(temp_db):
    tok = admin_token()
    make_user("iuid-1", "telegram_1", role="user")
    with BrowserTestClient(main.app) as c:
        # reason required
        assert c.post("/api/admin/users/iuid-1/role-v2", json={"role": "admin", "reason": ""}, headers=bearer(tok)).status_code == 400
        r = c.post("/api/admin/users/iuid-1/role-v2", json={"role": "admin", "reason": "promote"}, headers=bearer(tok))
    assert r.status_code == 200 and r.json()["role"] == "admin"
    with main.db() as conn:
        assert conn.execute("SELECT role FROM users WHERE internal_user_id='iuid-1'").fetchone()["role"] == "admin"
    assert count("audit_logs", "WHERE action='admin_change_role'") == 1
    assert count("security_events", "WHERE event_type='admin_role_changed'") == 1


# Role: 4 self-demotion, last admin
def test_self_demotion_and_last_admin_blocked(temp_db):
    tok = admin_token()  # iuid-admin is the only admin
    with BrowserTestClient(main.app) as c:
        # self-demotion
        assert c.post("/api/admin/users/iuid-admin/role-v2", json={"role": "user", "reason": "x"}, headers=bearer(tok)).status_code == 403
        # make a 2nd admin then demote them -> ok; but demoting the last admin must fail
        make_user("iuid-2", "telegram_2", role="admin")
        # now 2 admins; demote iuid-2 ok
        assert c.post("/api/admin/users/iuid-2/role-v2", json={"role": "user", "reason": "x"}, headers=bearer(tok)).status_code == 200
        # only iuid-admin remains admin; demoting via another admin path not possible (self) -> covered above


# Tokens: 7, 8, 11, 12
def test_token_adjust_and_logs(temp_db):
    tok = admin_token()
    make_user("iuid-1", "telegram_1", balance=50)
    with BrowserTestClient(main.app) as c:
        assert c.post("/api/admin/users/iuid-1/tokens-v2", json={"delta": 50, "reason": ""}, headers=bearer(tok)).status_code == 400  # reason
        up = c.post("/api/admin/users/iuid-1/tokens-v2", json={"delta": 50, "reason": "grant"}, headers=bearer(tok))
        down = c.post("/api/admin/users/iuid-1/tokens-v2", json={"delta": -30, "reason": "correction"}, headers=bearer(tok))
    assert up.json()["new_balance"] == 100 and down.json()["new_balance"] == 70
    with main.db() as conn:
        assert conn.execute("SELECT token_balance FROM users WHERE internal_user_id='iuid-1'").fetchone()["token_balance"] == 70
    assert count("token_ledger", "WHERE reason='admin_adjust'") == 2
    assert count("audit_logs", "WHERE action='admin_adjust_tokens'") == 2
    assert count("event_logs", "WHERE event_name='admin_tokens_adjusted'") == 2


# Tokens: 9, 10
def test_token_negative_and_zero_blocked(temp_db):
    tok = admin_token()
    make_user("iuid-1", "telegram_1", balance=20)
    with BrowserTestClient(main.app) as c:
        assert c.post("/api/admin/users/iuid-1/tokens-v2", json={"delta": -50, "reason": "x"}, headers=bearer(tok)).status_code == 400
        assert c.post("/api/admin/users/iuid-1/tokens-v2", json={"delta": 0, "reason": "x"}, headers=bearer(tok)).status_code == 400
        assert c.post("/api/admin/users/iuid-1/tokens-v2", json={"delta": 999999, "reason": "x"}, headers=bearer(tok)).status_code == 400
    with main.db() as conn:
        assert conn.execute("SELECT token_balance FROM users WHERE internal_user_id='iuid-1'").fetchone()["token_balance"] == 20


# Plan: 13
def test_plan_change_audit(temp_db):
    tok = admin_token()
    make_user("iuid-1", "telegram_1", plan="mini")
    with BrowserTestClient(main.app) as c:
        assert c.post("/api/admin/users/iuid-1/plan-v2", json={"plan": "pro", "reason": ""}, headers=bearer(tok)).status_code == 400
        r = c.post("/api/admin/users/iuid-1/plan-v2", json={"plan": "pro", "reason": "upgrade"}, headers=bearer(tok))
    assert r.status_code == 200 and r.json()["plan"] == "pro"
    with main.db() as conn:
        row = conn.execute("SELECT plan, gallery_enabled FROM users WHERE internal_user_id='iuid-1'").fetchone()
    assert row["plan"] == "pro" and row["gallery_enabled"] == 1
    assert count("audit_logs", "WHERE action='admin_change_plan'") == 1


def test_personal_discount_change_is_persisted_and_audited(temp_db):
    tok = admin_token()
    make_user("iuid-1", "telegram_1")
    with BrowserTestClient(main.app) as c:
        assert c.post("/api/admin/users/iuid-1/discount-v2", json={"percent": 25, "reason": ""}, headers=bearer(tok)).status_code == 400
        response = c.post(
            "/api/admin/users/iuid-1/discount-v2",
            json={"percent": 25, "reason": "Персональное предложение"},
            headers=bearer(tok),
        )
    assert response.status_code == 200
    assert response.json()["personal_discount_percent"] == 25
    with main.db() as conn:
        row = conn.execute(
            "SELECT personal_discount_percent FROM users WHERE internal_user_id='iuid-1'"
        ).fetchone()
    assert row["personal_discount_percent"] == 25
    assert count("audit_logs", "WHERE action='admin_change_personal_discount'") == 1


# Profile: 15, 16, 17, 18
def test_profile_update(temp_db):
    tok = admin_token()
    make_user("iuid-1", "telegram_1")
    with BrowserTestClient(main.app) as c:
        assert c.post("/api/admin/users/iuid-1/profile-v2", json={"display_name": "X", "reason": ""}, headers=bearer(tok)).status_code == 400
        r = c.post("/api/admin/users/iuid-1/profile-v2", json={"display_name": "Новое Имя", "role": "admin", "id": "hax", "reason": "fix"}, headers=bearer(tok))
    assert r.status_code == 200
    with main.db() as conn:
        row = conn.execute("SELECT id, display_name, role FROM users WHERE internal_user_id='iuid-1'").fetchone()
    assert row["display_name"] == "Новое Имя"
    assert row["id"] == "telegram_1"  # protected
    assert row["role"] == "user"      # protected (not in profile model)
    assert count("audit_logs", "WHERE action='admin_update_user_profile'") == 1


# 21: no hashes in any action response
def test_no_hashes_in_responses(temp_db):
    tok = admin_token()
    make_user("iuid-1", "telegram_1")
    with BrowserTestClient(main.app) as c:
        texts = [
            c.post("/api/admin/users/iuid-1/role-v2", json={"role": "admin", "reason": "x"}, headers=bearer(tok)).text,
            c.post("/api/admin/users/iuid-1/tokens-v2", json={"delta": 10, "reason": "x"}, headers=bearer(tok)).text,
            c.post("/api/admin/users/iuid-1/plan-v2", json={"plan": "pro", "reason": "x"}, headers=bearer(tok)).text,
            c.post("/api/admin/users/iuid-1/profile-v2", json={"display_name": "Y", "reason": "x"}, headers=bearer(tok)).text,
        ]
    for t in texts:
        for forbidden in ("password_hash", "session_token_hash", "refresh_token_hash", "code_hash"):
            assert forbidden not in t


# 22: users.id unchanged after actions
def test_users_id_unchanged(temp_db):
    tok = admin_token()
    make_user("iuid-1", "telegram_1")
    with BrowserTestClient(main.app) as c:
        c.post("/api/admin/users/iuid-1/role-v2", json={"role": "admin", "reason": "x"}, headers=bearer(tok))
        c.post("/api/admin/users/iuid-1/tokens-v2", json={"delta": 5, "reason": "x"}, headers=bearer(tok))
    with main.db() as conn:
        assert conn.execute("SELECT COUNT(*) AS c FROM users WHERE id='telegram_1'").fetchone()["c"] == 1
