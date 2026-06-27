"""CRM billing foundation tests (Phase 20E.1). Temp SQLite; no live DB."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

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
    with TestClient(main.app) as c:
        assert c.get("/api/admin/users/iuid-target/billing-v2").status_code == 401
        assert c.get("/api/admin/users/iuid-target/billing-v2", headers=bearer(user_token)).status_code == 403
        assert c.post("/api/admin/users/iuid-target/invoices-v2", json=invoice_payload(), headers=bearer(user_token)).status_code == 403


def test_create_invoice_writes_rows_audit_event_and_keeps_users_id(temp_db):
    token = admin_token()
    make_user("iuid-target", "telegram_target")
    with TestClient(main.app) as c:
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
    with TestClient(main.app) as c:
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
    with TestClient(main.app) as c:
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
    with TestClient(main.app) as c:
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
