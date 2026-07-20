"""CRM promo/bonus/referral foundation tests (Phase 20E.2). Temp SQLite; no live DB."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from test_support.browser_client import BrowserTestClient

import main


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "promo_bonus_referral_v2_test.sqlite3"
    monkeypatch.setattr(main, "DB_PATH", db_file)
    monkeypatch.setattr(main, "TRUSTED_COOKIE_SECURE", False)
    main.init_db()
    return db_file


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def make_user(iuid: str, legacy: str, role: str = "user", balance: int = 50) -> None:
    with main.db() as conn:
        conn.execute(
            "INSERT INTO users (id, internal_user_id, role, token_balance, language, created_at, last_login_at) "
            "VALUES (?, ?, ?, ?, 'ru', '2026-01-01', '2026-01-01')",
            (legacy, iuid, role, balance),
        )


def admin_token() -> str:
    make_user("iuid-admin", "telegram_admin", role="admin")
    return main.create_auth_session("iuid-admin", "telegram_admin", provider="telegram", platform="telegram_mini_app")["session_token"]


def test_loyalty_migration_idempotent(temp_db):
    main.init_db()
    with main.db() as conn:
        for table in ("promo_redemptions", "bonus_grants", "referral_links", "referral_relations", "referral_rewards"):
            assert conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()


def test_loyalty_requires_trusted_admin(temp_db):
    make_user("iuid-user", "telegram_user")
    make_user("iuid-target", "telegram_target")
    user_token = main.create_auth_session("iuid-user", "telegram_user", provider="telegram", platform="telegram_mini_app")["session_token"]
    with BrowserTestClient(main.app) as c:
        assert c.get("/api/admin/users/iuid-target/promos-v2").status_code == 401
        assert c.get("/api/admin/users/iuid-target/promos-v2", headers=bearer(user_token)).status_code == 403
        assert c.post("/api/admin/users/iuid-target/bonus-v2", json={"token_amount": 10, "reason": "x"}, headers=bearer(user_token)).status_code == 403


def test_bonus_grant_idempotent_cancel_and_users_id_safe(temp_db):
    token = admin_token()
    make_user("iuid-target", "telegram_target", balance=20)
    body = {"token_amount": 100, "bonus_type": "manual", "reason": "support bonus", "idempotency_key": "bonus-1"}
    with BrowserTestClient(main.app) as c:
        first = c.post("/api/admin/users/iuid-target/bonus-v2", json=body, headers=bearer(token))
        again = c.post("/api/admin/users/iuid-target/bonus-v2", json=body, headers=bearer(token))
        bonus_id = first.json()["bonus"]["id"]
        cancel = c.post(f"/api/admin/users/iuid-target/bonus/{bonus_id}/cancel-v2", json={"reason": "mistake"}, headers=bearer(token))
    assert first.status_code == 200, first.text
    assert first.json()["new_token_balance"] == 120
    assert again.status_code == 200 and again.json()["idempotent"] is True
    assert cancel.status_code == 200 and cancel.json()["new_token_balance"] == 20
    with main.db() as conn:
        assert conn.execute("SELECT token_balance FROM users WHERE internal_user_id='iuid-target'").fetchone()["token_balance"] == 20
        assert conn.execute("SELECT COUNT(*) AS c FROM bonus_grants").fetchone()["c"] == 1
        assert conn.execute("SELECT COUNT(*) AS c FROM token_ledger WHERE user_id='telegram_target'").fetchone()["c"] == 2
        assert conn.execute("SELECT COUNT(*) AS c FROM audit_logs WHERE action='crm_bonus_granted'").fetchone()["c"] == 1
        assert conn.execute("SELECT COUNT(*) AS c FROM audit_logs WHERE action='crm_bonus_cancelled'").fetchone()["c"] == 1
        assert conn.execute("SELECT COUNT(*) AS c FROM event_logs WHERE event_name='crm_bonus_granted'").fetchone()["c"] == 1
        assert conn.execute("SELECT COUNT(*) AS c FROM users WHERE id='telegram_target'").fetchone()["c"] == 1


def test_bonus_cancel_blocked_when_balance_insufficient(temp_db):
    token = admin_token()
    make_user("iuid-target", "telegram_target", balance=0)
    with BrowserTestClient(main.app) as c:
        r = c.post("/api/admin/users/iuid-target/bonus-v2", json={"token_amount": 100, "reason": "x", "idempotency_key": "bonus-low"}, headers=bearer(token))
        bonus_id = r.json()["bonus"]["id"]
        c.post("/api/admin/users/iuid-target/tokens-v2", json={"delta": -100, "reason": "spent elsewhere"}, headers=bearer(token))
        cancel = c.post(f"/api/admin/users/iuid-target/bonus/{bonus_id}/cancel-v2", json={"reason": "mistake"}, headers=bearer(token))
    assert cancel.status_code == 400


def test_apply_promo_duplicate_blocked_and_safe(temp_db):
    token = admin_token()
    make_user("iuid-target", "telegram_target", balance=10)
    with main.db() as conn:
        conn.execute("INSERT INTO promo_codes (code, tokens, activation_limit, activation_count, enabled, created_at, updated_at) VALUES ('WELCOME', 25, 10, 0, 1, '2026-01-01', '2026-01-01')")
    with BrowserTestClient(main.app) as c:
        first = c.post("/api/admin/users/iuid-target/apply-promo-v2", json={"promo_code": "welcome", "reason": "manual apply", "idempotency_key": "promo-1"}, headers=bearer(token))
        idem = c.post("/api/admin/users/iuid-target/apply-promo-v2", json={"promo_code": "WELCOME", "reason": "manual apply", "idempotency_key": "promo-1"}, headers=bearer(token))
        duplicate = c.post("/api/admin/users/iuid-target/apply-promo-v2", json={"promo_code": "WELCOME", "reason": "manual apply", "idempotency_key": "promo-2"}, headers=bearer(token))
        detail = c.get("/api/admin/users/iuid-target/analytics-v2", headers=bearer(token))
    assert first.status_code == 200 and first.json()["new_token_balance"] == 35
    assert idem.status_code == 200 and idem.json()["idempotent"] is True
    assert duplicate.status_code == 400
    b = detail.json()
    assert b["loyalty_summary"]["promo_redemption_count"] == 1
    assert b["promo_redemptions_recent"][0]["promo_code"] == "WELCOME"
    assert b["promo_redemptions_recent"][0]["token_bonus"] == 25
    text = detail.text
    for forbidden in ("password_hash", "session_token_hash", "refresh_token_hash", "code_hash", "initData", "WebAppData"):
        assert forbidden not in text


def test_user_apply_promo_grants_50_once_and_writes_clear_ledger(temp_db):
    make_user("iuid-user", "web_user", balance=10)
    user_token = main.create_auth_session("iuid-user", "web_user", provider="web_email", platform="web")["session_token"]
    with main.db() as conn:
        conn.execute("INSERT INTO promo_codes (code, tokens, activation_limit, activation_count, enabled, created_at, updated_at) VALUES ('FRIEND50', 5, 10, 0, 1, '2026-01-01', '2026-01-01')")
    with BrowserTestClient(main.app) as c:
        first = c.post("/api/account/apply-promo-v2", json={"promo_code": "friend50"}, headers=bearer(user_token))
        duplicate = c.post("/api/account/apply-promo-v2", json={"promo_code": "FRIEND50"}, headers=bearer(user_token))
    assert first.status_code == 200, first.text
    assert first.json()["token_bonus"] == 5
    assert first.json()["new_token_balance"] == 15
    assert duplicate.status_code == 400
    with main.db() as conn:
        ledger = conn.execute("SELECT delta, reason FROM token_ledger WHERE user_id='web_user'").fetchone()
        redemption = conn.execute("SELECT token_bonus, reason FROM promo_redemptions WHERE internal_user_id='iuid-user'").fetchone()
    assert ledger["delta"] == 5
    assert ledger["reason"] == "promo_code_redeemed"
    assert redemption["token_bonus"] == 5
    assert redemption["reason"] == "promo_code_redeemed"


def test_referral_reward_writes_reward_and_ledger(temp_db):
    token = admin_token()
    make_user("iuid-parent", "telegram_parent", balance=5)
    make_user("iuid-child", "telegram_child", balance=5)
    with main.db() as conn:
        conn.execute(
            "INSERT INTO referral_relations (id, parent_internal_user_id, child_internal_user_id, referral_code, status, created_at) VALUES ('rel1','iuid-parent','iuid-child','REF-PARENT','active','2026-01-01')"
        )
    body = {"token_amount": 0, "referral_relation_id": "rel1", "reason": "friend signup", "idempotency_key": "reward-1"}
    with BrowserTestClient(main.app) as c:
        first = c.post("/api/admin/users/iuid-parent/referral-reward-v2", json=body, headers=bearer(token))
        again = c.post("/api/admin/users/iuid-parent/referral-reward-v2", json=body, headers=bearer(token))
        refs = c.get("/api/admin/users/iuid-parent/referrals-v2", headers=bearer(token))
    assert first.status_code == 200, first.text
    assert first.json()["new_token_balance"] == 55
    assert again.status_code == 200 and again.json()["idempotent"] is True
    assert refs.json()["loyalty_summary"]["referral_children_count"] == 1
    assert refs.json()["referral_rewards_recent"][0]["token_amount"] == 50
    with main.db() as conn:
        assert conn.execute("SELECT COUNT(*) AS c FROM referral_rewards").fetchone()["c"] == 1
        assert conn.execute("SELECT COUNT(*) AS c FROM token_ledger WHERE reason='referral_friend_signup'").fetchone()["c"] == 1
        assert conn.execute("SELECT COUNT(*) AS c FROM audit_logs WHERE action='crm_referral_reward_granted'").fetchone()["c"] == 1
