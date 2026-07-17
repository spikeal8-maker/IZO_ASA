from __future__ import annotations

from fastapi.testclient import TestClient
import pytest

import main
from app.integrations.yookassa import YooKassaPayment


def checkout_payload(package_code: str, key: str) -> dict:
    return {
        "package_code": package_code,
        "idempotency_key": key,
        "offer_accepted": True,
        "receipt_contact": "buyer@example.test",
    }


@pytest.fixture
def payment_app(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "payments.sqlite3")
    monkeypatch.setattr(main, "TRUSTED_COOKIE_SECURE", False)
    monkeypatch.delenv("PUBLIC_SITE_URL", raising=False)
    monkeypatch.setattr(
        main,
        "yookassa_config",
        lambda: {
            "shop_id": "test-shop",
            "test_mode": True,
            "receipt_vat_code": 1,
            "payment_subject": "service",
        },
    )
    monkeypatch.setattr(main, "yookassa_secret_key", lambda: "test-secret")
    monkeypatch.setattr(main, "yookassa_ready", lambda config=None: True)
    main.init_db()
    with main.db() as conn:
        conn.execute(
            "INSERT INTO users (id, internal_user_id, role, token_balance, language, created_at, last_login_at) VALUES ('web_buyer', 'iuid-buyer', 'user', 10, 'ru', '2026-01-01', '2026-01-01')"
        )
        conn.execute(
            "INSERT INTO admin_settings (key, value_json, updated_at) VALUES ('legal', ?, '2026-01-01')",
            ('{"seller_name":"Тестовый продавец","seller_status":"ИП","inn":"123456789012","legal_address":"Тестовый адрес","support_email":"buyer@example.test"}',),
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
        response = client.post("/api/billing/checkout-v2", json=checkout_payload("tokens_50", "checkout-test-0001"), headers=payment_app["headers"])
    assert response.status_code == 200, response.text
    assert response.json()["confirmation_url"] == "https://pay.test/confirm"
    assert captured["return_url"] == f"https://izo.alikinas.ru/payment?payment_id={response.json()['payment_id']}"
    assert captured["receipt"]["customer"] == {"email": "buyer@example.test"}
    with main.db() as conn:
        payment = conn.execute("SELECT * FROM payments").fetchone()
        invoice = conn.execute("SELECT * FROM invoices").fetchone()
        acceptance = conn.execute("SELECT * FROM legal_acceptances").fetchone()
    assert payment["provider_payment_id"] == "provider-1" and payment["status"] == "pending"
    assert invoice["tokens_total"] == 50 and invoice["total_amount"] == 250
    assert acceptance["payment_id"] == payment["id"]
    assert acceptance["receipt_contact"] == "buyer@example.test"


def test_personal_discount_changes_invoice_payment_and_receipt(payment_app):
    captured = {}

    async def create(**kwargs):
        captured.update(kwargs)
        return YooKassaPayment("provider-discount", "pending", "200.00", "RUB", "https://pay.test/discount", False)

    payment_app["monkeypatch"].setattr(main, "create_yookassa_payment", create)
    with main.db() as conn:
        conn.execute(
            "UPDATE users SET personal_discount_percent=20 WHERE internal_user_id='iuid-buyer'"
        )
    with TestClient(main.app) as client:
        packages = client.get("/api/billing/packages-v2", headers=payment_app["headers"])
        response = client.post(
            "/api/billing/checkout-v2",
            json=checkout_payload("tokens_50", "checkout-discount-0001"),
            headers=payment_app["headers"],
        )
    assert packages.status_code == 200
    package = next(item for item in packages.json()["packages"] if item["code"] == "tokens_50")
    assert package["base_price_amount"] == 250
    assert package["discount_percent"] == 20
    assert package["discount_amount"] == 50
    assert package["price_amount"] == 200
    assert response.status_code == 200, response.text
    assert captured["amount"] == 200
    assert captured["receipt"]["items"][0]["amount"]["value"] == "200.00"
    with main.db() as conn:
        payment = conn.execute("SELECT amount FROM payments WHERE provider_payment_id='provider-discount'").fetchone()
        invoice = conn.execute("SELECT subtotal_amount, discount_amount, total_amount FROM invoices").fetchone()
    assert payment["amount"] == 200
    assert tuple(invoice) == (250, 50, 200)


def test_verified_webhook_grants_tokens_exactly_once(payment_app):
    async def create(**_kwargs):
        return YooKassaPayment("provider-2", "pending", "250.00", "RUB", "https://pay.test/confirm", False)

    async def fetch(*_args, **_kwargs):
        return YooKassaPayment("provider-2", "succeeded", "250.00", "RUB", None, True)

    payment_app["monkeypatch"].setattr(main, "create_yookassa_payment", create)
    payment_app["monkeypatch"].setattr(main, "fetch_yookassa_payment", fetch)
    with TestClient(main.app) as client:
        checkout = client.post("/api/billing/checkout-v2", json=checkout_payload("tokens_50", "checkout-test-0002"), headers=payment_app["headers"])
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
        client.post("/api/billing/checkout-v2", json=checkout_payload("tokens_50", "checkout-test-0003"), headers=payment_app["headers"])
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
        checkout = client.post("/api/billing/checkout-v2", json=checkout_payload("tariff_plus", "checkout-plan-0001"), headers=payment_app["headers"])
        assert checkout.status_code == 200, checkout.text
        webhook = client.post("/api/billing/yookassa/webhook-v2", json={"event": "payment.succeeded", "object": {"id": "provider-plan"}})
    assert webhook.status_code == 200, webhook.text
    with main.db() as conn:
        user = conn.execute("SELECT plan, plan_expires_at, token_balance FROM users WHERE internal_user_id='iuid-buyer'").fetchone()
    # Paid tariff activation credits the included monthly tokens to the one
    # persistent balance instead of maintaining a third premium wallet.
    assert user["plan"] == "plus" and user["plan_expires_at"] and user["token_balance"] == 260


def test_payment_result_reconciles_pending_payment(payment_app):
    async def create(**_kwargs):
        return YooKassaPayment("provider-result", "pending", "250.00", "RUB", "https://pay.test/confirm", False)

    async def fetch(*_args, **_kwargs):
        return YooKassaPayment("provider-result", "succeeded", "250.00", "RUB", None, True)

    payment_app["monkeypatch"].setattr(main, "create_yookassa_payment", create)
    payment_app["monkeypatch"].setattr(main, "fetch_yookassa_payment", fetch)
    with TestClient(main.app) as client:
        checkout = client.post("/api/billing/checkout-v2", json=checkout_payload("tokens_50", "checkout-result-0001"), headers=payment_app["headers"])
        result = client.get(f"/api/billing/payments/{checkout.json()['payment_id']}/status-v2", headers=payment_app["headers"])
    assert result.status_code == 200, result.text
    assert result.json()["payment"]["status"] == "paid"
    assert result.json()["account"]["token_balance"] == 60


def test_payment_result_requires_owner_session(payment_app):
    with TestClient(main.app) as client:
        result = client.get("/api/billing/payments/not-mine/status-v2")
    assert result.status_code == 401


def test_checkout_requires_offer_and_receipt_contact(payment_app):
    with TestClient(main.app) as client:
        no_offer = client.post("/api/billing/checkout-v2", json={"package_code": "tokens_50", "idempotency_key": "checkout-no-offer"}, headers=payment_app["headers"])
        no_contact = client.post("/api/billing/checkout-v2", json={"package_code": "tokens_50", "idempotency_key": "checkout-no-contact", "offer_accepted": True}, headers=payment_app["headers"])
    assert no_offer.status_code == 400
    assert no_contact.status_code == 400


def test_self_employed_checkout_saves_email_without_yookassa_receipt(payment_app):
    captured = {}

    async def create(**kwargs):
        captured.update(kwargs)
        return YooKassaPayment("provider-npd", "pending", "250.00", "RUB", "https://pay.test/npd", False)

    payment_app["monkeypatch"].setattr(main, "create_yookassa_payment", create)
    with main.db() as conn:
        conn.execute(
            "UPDATE admin_settings SET value_json=? WHERE key='legal'",
            ('{"seller_name":"Тестовый продавец","seller_status":"Самозанятый, НПД","inn":"123456789012","legal_address":"Тестовый адрес","support_email":"buyer@example.test"}',),
        )
    with TestClient(main.app) as client:
        checkout = client.post(
            "/api/billing/checkout-v2",
            json=checkout_payload("tokens_50", "checkout-self-employed-0001"),
            headers=payment_app["headers"],
        )
        profile = client.get("/api/me/profile-v2", headers=payment_app["headers"])
        packages = client.get("/api/billing/packages-v2", headers=payment_app["headers"])
    assert checkout.status_code == 200, checkout.text
    assert captured["receipt"] is None
    assert profile.status_code == 200
    assert profile.json()["billing"]["receipt_email"] == "buyer@example.test"
    assert packages.json()["checkout"]["fiscalization_mode"] == "self_employed_manual"
    assert packages.json()["checkout"]["receipt_email"] == "buyer@example.test"


def test_self_employed_checkout_rejects_phone_as_receipt_contact(payment_app):
    with main.db() as conn:
        conn.execute(
            "UPDATE admin_settings SET value_json=? WHERE key='legal'",
            ('{"seller_name":"Тестовый продавец","seller_status":"Самозанятый","inn":"123456789012","legal_address":"Тестовый адрес","support_email":"buyer@example.test"}',),
        )
    payload = checkout_payload("tokens_50", "checkout-self-employed-phone")
    payload["receipt_contact"] = "+7 900 000-00-00"
    with TestClient(main.app) as client:
        response = client.post("/api/billing/checkout-v2", json=payload, headers=payment_app["headers"])
    assert response.status_code == 400
    assert "email" in response.json()["detail"].lower()


def test_public_commerce_exposes_tariffs_documents_and_readiness(payment_app):
    with TestClient(main.app) as client:
        response = client.get("/api/public/commerce-v2")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["legal_readiness"]["ready"] is True
    assert body["legal"]["seller_name"] == "Тестовый продавец"
    assert "plus" in body["tariffs"]
    assert any(item["code"] == "tokens_50" for item in body["packages"])


def test_expired_paid_plan_falls_back_to_free(payment_app):
    with main.db() as conn:
        conn.execute("UPDATE users SET plan='pro', plan_expires_at='2020-01-01T00:00:00+00:00' WHERE internal_user_id='iuid-buyer'")
    with TestClient(main.app) as client:
        response = client.get("/api/billing/packages-v2", headers=payment_app["headers"])
    assert response.status_code == 200
    with main.db() as conn:
        user = conn.execute("SELECT plan, plan_expires_at FROM users WHERE internal_user_id='iuid-buyer'").fetchone()
    assert user["plan"] == "free" and user["plan_expires_at"] is None
