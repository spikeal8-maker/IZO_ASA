from __future__ import annotations

from fastapi.testclient import TestClient
import pytest

import main
from app.integrations.yookassa import YooKassaPayment


@pytest.fixture
def payment_app(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "payments.sqlite3")
    monkeypatch.setattr(main, "TRUSTED_COOKIE_SECURE", False)
    monkeypatch.setattr(main, "yookassa_config", lambda: {"shop_id": "test-shop", "test_mode": True})
    monkeypatch.setattr(main, "yookassa_secret_key", lambda: "test-secret")
    monkeypatch.setattr(main, "yookassa_ready", lambda config=None: True)
    main.init_db()
    with main.db() as conn:
        conn.execute(
            "INSERT INTO users (id, internal_user_id, role, token_balance, language, created_at, last_login_at) VALUES ('web_buyer', 'iuid-buyer', 'user', 10, 'ru', '2026-01-01', '2026-01-01')"
        )
    token = main.create_auth_session("iuid-buyer", "web_buyer", provider="web_email", platform="web_desktop")["session_token"]
    return {"headers": {"Authorization": f"Bearer {token}"}, "monkeypatch": monkeypatch}


def test_checkout_creates_invoice_and_provider_payment(payment_app):
    async def create(**_kwargs):
        return YooKassaPayment("provider-1", "pending", "250.00", "RUB", "https://pay.test/confirm", False)

    payment_app["monkeypatch"].setattr(main, "create_yookassa_payment", create)
    with TestClient(main.app) as client:
        response = client.post("/api/billing/checkout-v2", json={"package_code": "tokens_50", "idempotency_key": "checkout-test-0001"}, headers=payment_app["headers"])
    assert response.status_code == 200, response.text
    assert response.json()["confirmation_url"] == "https://pay.test/confirm"
    with main.db() as conn:
        payment = conn.execute("SELECT * FROM payments").fetchone()
        invoice = conn.execute("SELECT * FROM invoices").fetchone()
    assert payment["provider_payment_id"] == "provider-1" and payment["status"] == "pending"
    assert invoice["tokens_total"] == 50 and invoice["total_amount"] == 250


def test_verified_webhook_grants_tokens_exactly_once(payment_app):
    async def create(**_kwargs):
        return YooKassaPayment("provider-2", "pending", "250.00", "RUB", "https://pay.test/confirm", False)

    async def fetch(*_args, **_kwargs):
        return YooKassaPayment("provider-2", "succeeded", "250.00", "RUB", None, True)

    payment_app["monkeypatch"].setattr(main, "create_yookassa_payment", create)
    payment_app["monkeypatch"].setattr(main, "fetch_yookassa_payment", fetch)
    with TestClient(main.app) as client:
        checkout = client.post("/api/billing/checkout-v2", json={"package_code": "tokens_50", "idempotency_key": "checkout-test-0002"}, headers=payment_app["headers"])
        assert checkout.status_code == 200
        body = {"event": "payment.succeeded", "object": {"id": "provider-2"}}
        first = client.post("/api/billing/yookassa/webhook-v2", json=body)
        second = client.post("/api/billing/yookassa/webhook-v2", json=body)
    assert first.status_code == 200, first.text
    assert second.status_code == 200 and second.json()["idempotent"] is True
    with main.db() as conn:
        balance = conn.execute("SELECT token_balance FROM users WHERE internal_user_id='iuid-buyer'").fetchone()["token_balance"]
        ledger_count = conn.execute("SELECT COUNT(*) AS c FROM token_ledger WHERE reason='payment_grant'").fetchone()["c"]
        payment = conn.execute("SELECT status FROM payments WHERE provider_payment_id='provider-2'").fetchone()
    assert balance == 60 and ledger_count == 1 and payment["status"] == "paid"


def test_webhook_rejects_amount_mismatch_without_tokens(payment_app):
    async def create(**_kwargs):
        return YooKassaPayment("provider-3", "pending", "250.00", "RUB", "https://pay.test/confirm", False)

    async def fetch(*_args, **_kwargs):
        return YooKassaPayment("provider-3", "succeeded", "1.00", "RUB", None, True)

    payment_app["monkeypatch"].setattr(main, "create_yookassa_payment", create)
    payment_app["monkeypatch"].setattr(main, "fetch_yookassa_payment", fetch)
    with TestClient(main.app) as client:
        client.post("/api/billing/checkout-v2", json={"package_code": "tokens_50", "idempotency_key": "checkout-test-0003"}, headers=payment_app["headers"])
        webhook = client.post("/api/billing/yookassa/webhook-v2", json={"event": "payment.succeeded", "object": {"id": "provider-3"}})
    assert webhook.status_code == 502
    with main.db() as conn:
        balance = conn.execute("SELECT token_balance FROM users WHERE internal_user_id='iuid-buyer'").fetchone()["token_balance"]
        ledger_count = conn.execute("SELECT COUNT(*) AS c FROM token_ledger WHERE reason='payment_grant'").fetchone()["c"]
    assert balance == 10 and ledger_count == 0
