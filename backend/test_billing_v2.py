"""CRM billing foundation tests (Phase 20E.1). Temp SQLite; no live DB."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from test_support.browser_client import BrowserTestClient

import main


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "billing_v2_test.sqlite3"
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


def invoice_payload(amount: int = 1200, tokens: int = 500) -> dict:
    return {
        "currency": "RUB",
        "reason": "manual crm invoice",
        "items": [{"title": "Token package", "quantity": 1, "unit_amount": amount, "token_amount": tokens}],
    }


def create_invoice(client: TestClient, token: str, iuid: str, amount: int = 1200, tokens: int = 500) -> dict:
    r = client.post(f"/api/admin/users/{iuid}/invoices-v2", json=invoice_payload(amount, tokens), headers=bearer(token))
    assert r.status_code == 200, r.text
    return r.json()["invoice"]


def test_billing_migration_idempotent(temp_db):
    main.init_db()
    with main.db() as conn:
        for table in ("billing_packages", "invoices", "invoice_items", "payments", "refunds"):
            assert conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()


def test_billing_requires_trusted_admin(temp_db):
    make_user("iuid-user", "telegram_user")
    make_user("iuid-target", "telegram_target")
    user_token = main.create_auth_session("iuid-user", "telegram_user", provider="telegram", platform="telegram_mini_app")["session_token"]
    with BrowserTestClient(main.app) as c:
        assert c.get("/api/admin/users/iuid-target/billing-v2").status_code == 401
        assert c.get("/api/admin/users/iuid-target/billing-v2", headers=bearer(user_token)).status_code == 403
        assert c.post("/api/admin/users/iuid-target/invoices-v2", json=invoice_payload(), headers=bearer(user_token)).status_code == 403


def test_create_invoice_writes_rows_audit_event_and_keeps_users_id(temp_db):
    token = admin_token()
    make_user("iuid-target", "telegram_target")
    with BrowserTestClient(main.app) as c:
        invoice = create_invoice(c, token, "iuid-target")
    assert invoice["status"] == "issued"
    assert invoice["total_amount"] == 1200
    assert invoice["tokens_total"] == 500
    with main.db() as conn:
        assert conn.execute("SELECT COUNT(*) AS c FROM invoices").fetchone()["c"] == 1
        assert conn.execute("SELECT COUNT(*) AS c FROM invoice_items").fetchone()["c"] == 1
        assert conn.execute("SELECT COUNT(*) AS c FROM audit_logs WHERE action='billing_invoice_created'").fetchone()["c"] == 1
        assert conn.execute("SELECT COUNT(*) AS c FROM event_logs WHERE event_name='billing_invoice_created'").fetchone()["c"] == 1
        assert conn.execute("SELECT COUNT(*) AS c FROM users WHERE id='telegram_target'").fetchone()["c"] == 1


def test_mark_paid_grants_tokens_once_through_ledger(temp_db):
    token = admin_token()
    make_user("iuid-target", "telegram_target", balance=10)
    with BrowserTestClient(main.app) as c:
        invoice = create_invoice(c, token, "iuid-target", amount=900, tokens=300)
        body = {"amount": 900, "method": "manual", "reason": "cash received", "idempotency_key": "pay-1"}
        paid = c.post(f"/api/admin/invoices/{invoice['id']}/mark-paid-v2", json=body, headers=bearer(token))
        again = c.post(f"/api/admin/invoices/{invoice['id']}/mark-paid-v2", json=body, headers=bearer(token))
        second_key = c.post(f"/api/admin/invoices/{invoice['id']}/mark-paid-v2", json={**body, "idempotency_key": "pay-2"}, headers=bearer(token))
    assert paid.status_code == 200, paid.text
    assert paid.json()["new_token_balance"] == 310
    assert again.status_code == 200 and again.json()["idempotent"] is True
    assert second_key.status_code == 400
    with main.db() as conn:
        assert conn.execute("SELECT token_balance FROM users WHERE internal_user_id='iuid-target'").fetchone()["token_balance"] == 310
        ledgers = conn.execute("SELECT delta, reason, meta_json FROM token_ledger WHERE user_id='telegram_target'").fetchall()
        assert len(ledgers) == 1
        assert ledgers[0]["delta"] == 300 and ledgers[0]["reason"] == "payment_grant"
        assert json.loads(ledgers[0]["meta_json"])["invoice_id"] == invoice["id"]


def test_cancel_unpaid_and_cannot_cancel_paid(temp_db):
    token = admin_token()
    make_user("iuid-target", "telegram_target")
    with BrowserTestClient(main.app) as c:
        unpaid = create_invoice(c, token, "iuid-target", amount=100, tokens=0)
        cancel = c.post(f"/api/admin/invoices/{unpaid['id']}/cancel-v2", json={"reason": "client changed mind"}, headers=bearer(token))
        paid_invoice = create_invoice(c, token, "iuid-target", amount=100, tokens=0)
        c.post(f"/api/admin/invoices/{paid_invoice['id']}/mark-paid-v2", json={"amount": 100, "reason": "paid", "idempotency_key": "paid-cancel"}, headers=bearer(token))
        cancel_paid = c.post(f"/api/admin/invoices/{paid_invoice['id']}/cancel-v2", json={"reason": "x"}, headers=bearer(token))
    assert cancel.status_code == 200 and cancel.json()["invoice"]["status"] == "cancelled"
    assert cancel_paid.status_code == 400


def test_refund_limits_and_analytics_safe(temp_db):
    token = admin_token()
    make_user("iuid-target", "telegram_target")
    with BrowserTestClient(main.app) as c:
        invoice = create_invoice(c, token, "iuid-target", amount=500, tokens=0)
        pay = c.post(f"/api/admin/invoices/{invoice['id']}/mark-paid-v2", json={"amount": 500, "reason": "paid", "idempotency_key": "pay-ref"}, headers=bearer(token)).json()["payment"]
        too_much = c.post(f"/api/admin/payments/{pay['id']}/refund-v2", json={"amount": 600, "reason": "refund", "idempotency_key": "ref-big"}, headers=bearer(token))
        ok = c.post(f"/api/admin/payments/{pay['id']}/refund-v2", json={"amount": 200, "reason": "refund", "idempotency_key": "ref-ok"}, headers=bearer(token))
        detail = c.get("/api/admin/users/iuid-target/analytics-v2", headers=bearer(token))
    assert too_much.status_code == 400
    assert ok.status_code == 200 and ok.json()["refund"]["token_reversal_policy"] == "deferred"
    b = detail.json()
    assert b["billing_summary"]["invoice_count"] == 1
    assert b["billing_summary"]["total_paid"] == 500
    assert b["billing_summary"]["total_refunded"] == 200
    assert b["invoices_recent"][0]["status"] == "partially_refunded"
    text = detail.text
    for forbidden in ("password_hash", "session_token_hash", "refresh_token_hash", "code_hash", "provider_payload", "webhook_payload"):
        assert forbidden not in text


def test_yookassa_refund_cannot_be_falsely_completed_only_in_local_db(temp_db):
    token = admin_token()
    make_user("iuid-target", "telegram_target")
    with BrowserTestClient(main.app) as c:
        invoice = create_invoice(c, token, "iuid-target", amount=500, tokens=0)
        payment = c.post(
            f"/api/admin/invoices/{invoice['id']}/mark-paid-v2",
            json={"amount": 500, "reason": "paid", "idempotency_key": "pay-yookassa-ref"},
            headers=bearer(token),
        ).json()["payment"]
        with main.db() as conn:
            conn.execute("UPDATE payments SET provider='yookassa' WHERE id=?", (payment["id"],))
        response = c.post(
            f"/api/admin/payments/{payment['id']}/refund-v2",
            json={"amount": 200, "reason": "refund", "idempotency_key": "refund-yookassa"},
            headers=bearer(token),
        )
    assert response.status_code == 409
    with main.db() as conn:
        assert conn.execute("SELECT COUNT(*) AS c FROM refunds").fetchone()["c"] == 0
        assert conn.execute("SELECT status FROM payments WHERE id=?", (payment["id"],)).fetchone()["status"] == "paid"


def test_admin_can_update_token_package_but_not_tariff_package(temp_db):
    token = admin_token()
    body = {"name": "80 токенов", "price_amount": 360, "token_amount": 80, "is_active": True}
    with BrowserTestClient(main.app) as client:
        updated = client.put("/api/admin/payments/packages/tokens_50-v2", json=body, headers=bearer(token))
        rejected = client.put("/api/admin/payments/packages/tariff_pro-v2", json=body, headers=bearer(token))
    assert updated.status_code == 200, updated.text
    assert updated.json()["package"]["price_amount"] == 360
    assert updated.json()["package"]["token_amount"] == 80
    assert rejected.status_code == 400


def test_extending_current_tariff_restores_next_monthly_grant(temp_db):
    make_user("iuid-target", "telegram_target")
    now = datetime(2026, 7, 17, 12, 0, tzinfo=timezone.utc)
    current_expiry = main.add_calendar_months(now, 1)
    with main.db() as conn:
        conn.execute(
            """
            UPDATE users
            SET plan='pro', plan_started_at=?, plan_expires_at=?,
                plan_next_token_grant_at=NULL, plan_monthly_token_grant=500,
                plan_term_months=1, pending_plan_json='{"plan":"mini","term_months":1}'
            WHERE internal_user_id='iuid-target'
            """,
            (now.isoformat(), current_expiry.isoformat()),
        )
        result = main._schedule_or_activate_paid_tariff(
            conn,
            internal_user_id="iuid-target",
            plan="pro",
            term_months=3,
            source="test_payment",
            source_id="payment-extend",
            now=now,
        )
        row = conn.execute(
            "SELECT plan_expires_at, plan_next_token_grant_at, plan_term_months, pending_plan_json FROM users WHERE internal_user_id='iuid-target'"
        ).fetchone()

    assert result["extended"] is True
    assert row["plan_expires_at"] == main.add_calendar_months(current_expiry, 3).isoformat()
    assert row["plan_next_token_grant_at"] == current_expiry.isoformat()
    assert int(row["plan_term_months"]) == 4
    assert row["pending_plan_json"] is None


def test_user_can_schedule_free_without_losing_main_balance(temp_db):
    make_user("iuid-target", "telegram_target", balance=321)
    now = datetime.now(timezone.utc)
    expiry = main.add_calendar_months(now, 1)
    with main.db() as conn:
        conn.execute(
            "UPDATE users SET plan='pro', plan_started_at=?, plan_expires_at=?, plan_monthly_token_grant=500 WHERE internal_user_id='iuid-target'",
            (now.isoformat(), expiry.isoformat()),
        )
    token = main.create_auth_session(
        "iuid-target",
        "telegram_target",
        provider="telegram",
        platform="telegram_mini_app",
    )["session_token"]
    with BrowserTestClient(main.app) as client:
        response = client.post(
            "/api/account/tariff-v2/schedule-free",
            json={"confirm": True},
            headers=bearer(token),
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["plan"] == "pro"
    assert body["pending_plan"]["plan"] == "free"
    assert body["token_balance"] == 321
    with main.db() as conn:
        row = conn.execute(
            "SELECT plan, pending_plan_json, token_balance FROM users WHERE internal_user_id='iuid-target'"
        ).fetchone()
    assert row["plan"] == "pro"
    assert json.loads(row["pending_plan_json"])["plan"] == "free"
    assert row["token_balance"] == 321
