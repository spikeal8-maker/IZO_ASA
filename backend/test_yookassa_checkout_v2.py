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
    captured = {}

    async def create(**_kwargs):
        captured.update(_kwargs)
        return YooKassaPayment("provider-1", "pending", "250.00", "RUB", "https://pay.test/confirm", False)

    payment_app["monkeypatch"].setattr(main, "create_yookassa_payment", create)
    with TestClient(main.app) as client:
        response = client.post("/api/billing/checkout-v2", json={"package_code": "tokens_50", "idempotency_key": "checkout-test-0001"}, headers=payment_app["headers"])
    assert response.status_code == 200, response.text
    assert response.json()["confirmation_url"] == "https://pay.test/confirm"
    assert captured["return_url"].endswith(f"/payment?payment_id={response.json()['payment_id']}")
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


def test_paid_tariff_changes_plan_and_sets_expiry(payment_app):
    async def create(**_kwargs):
        return YooKassaPayment("provider-plan", "pending", "990.00", "RUB", "https://pay.test/confirm", False)

    async def fetch(*_args, **_kwargs):
        return YooKassaPayment("provider-plan", "succeeded", "990.00", "RUB", None, True)

    payment_app["monkeypatch"].setattr(main, "create_yookassa_payment", create)
    payment_app["monkeypatch"].setattr(main, "fetch_yookassa_payment", fetch)
    with TestClient(main.app) as client:
        checkout = client.post("/api/billing/checkout-v2", json={"package_code": "tariff_plus", "idempotency_key": "checkout-plan-0001"}, headers=payment_app["headers"])
        assert checkout.status_code == 200, checkout.text
        webhook = client.post("/api/billing/yookassa/webhook-v2", json={"event": "payment.succeeded", "object": {"id": "provider-plan"}})
    assert webhook.status_code == 200, webhook.text
    with main.db() as conn:
        user = conn.execute("SELECT plan, plan_expires_at, token_balance FROM users WHERE internal_user_id='iuid-buyer'").fetchone()
    assert user["plan"] == "plus" and user["plan_expires_at"] and user["token_balance"] == 10


def test_payment_result_reconciles_pending_payment(payment_app):
    async def create(**_kwargs):
        return YooKassaPayment("provider-result", "pending", "250.00", "RUB", "https://pay.test/confirm", False)

    async def fetch(*_args, **_kwargs):
        return YooKassaPayment("provider-result", "succeeded", "250.00", "RUB", None, True)

    payment_app["monkeypatch"].setattr(main, "create_yookassa_payment", create)
    payment_app["monkeypatch"].setattr(main, "fetch_yookassa_payment", fetch)
    with TestClient(main.app) as client:
        checkout = client.post("/api/billing/checkout-v2", json={"package_code": "tokens_50", "idempotency_key": "checkout-result-0001"}, headers=payment_app["headers"])
        result = client.get(f"/api/billing/payments/{checkout.json()['payment_id']}/status-v2", headers=payment_app["headers"])
    assert result.status_code == 200, result.text
    assert result.json()["payment"]["status"] == "paid"
    assert result.json()["account"]["token_balance"] == 60


def test_payment_result_requires_owner_session(payment_app):
    with TestClient(main.app) as client:
        result = client.get("/api/billing/payments/not-mine/status-v2")
    assert result.status_code == 401


def test_expired_paid_plan_falls_back_to_free(payment_app):
    with main.db() as conn:
        conn.execute("UPDATE users SET plan='pro', plan_expires_at='2020-01-01T00:00:00+00:00' WHERE internal_user_id='iuid-buyer'")
    with TestClient(main.app) as client:
        response = client.get("/api/billing/packages-v2", headers=payment_app["headers"])
    assert response.status_code == 200
    with main.db() as conn:
        user = conn.execute("SELECT plan, plan_expires_at FROM users WHERE internal_user_id='iuid-buyer'").fetchone()
    assert user["plan"] == "free" and user["plan_expires_at"] is None
