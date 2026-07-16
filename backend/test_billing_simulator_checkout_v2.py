from __future__ import annotations

from fastapi.testclient import TestClient
import pytest

import main


@pytest.fixture
def simulator_app(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "simulator.sqlite3")
    monkeypatch.setattr(main, "TRUSTED_COOKIE_SECURE", False)
    monkeypatch.setattr(main, "_SIMULATED_PAYMENT_PROVIDER", None)
    monkeypatch.setenv("BILLING_SIMULATOR_ENABLED", "1")
    monkeypatch.setattr(main, "APP_ENV", "test")
    monkeypatch.setattr(main, "ENV_NAME", "test")
    monkeypatch.setattr(main, "MODE_NAME", "test")
    monkeypatch.setattr(main, "yookassa_ready", lambda config=None: False)
    main.init_db()
    with main.db() as conn:
        conn.execute(
            "INSERT INTO users (id, internal_user_id, role, token_balance, language, created_at, last_login_at) VALUES ('buyer', 'iuid-buyer', 'user', 10, 'ru', '2026-01-01', '2026-01-01')"
        )
        conn.execute(
            "INSERT INTO users (id, internal_user_id, role, token_balance, language, created_at, last_login_at) VALUES ('admin', 'iuid-admin', 'admin', 0, 'ru', '2026-01-01', '2026-01-01')"
        )
        conn.execute(
            "INSERT INTO admin_settings (key, value_json, updated_at) VALUES ('legal', ?, '2026-01-01')",
            ('{"seller_name":"Тестовый продавец","seller_status":"ИП","inn":"123456789012","legal_address":"Тестовый адрес","support_email":"support@example.test"}',),
        )
    buyer_token = main.create_auth_session("iuid-buyer", "buyer", provider="web_email", platform="web_desktop")["session_token"]
    admin_token = main.create_auth_session("iuid-admin", "admin", provider="web_email", platform="web_desktop")["session_token"]
    return {
        "buyer": {"Authorization": f"Bearer {buyer_token}"},
        "admin": {"Authorization": f"Bearer {admin_token}"},
    }


def test_simulator_checkout_success_is_end_to_end_and_idempotent(simulator_app) -> None:
    body = {
        "package_code": "tokens_50",
        "idempotency_key": "simulator-checkout-0001",
        "offer_accepted": True,
        "receipt_contact": "buyer@example.test",
    }
    with TestClient(main.app) as client:
        checkout = client.post("/api/billing/checkout-v2", json=body, headers=simulator_app["buyer"])
        assert checkout.status_code == 200, checkout.text
        payload = checkout.json()
        assert payload["status"] == "pending"
        assert payload["confirmation_url"].startswith("http")

        duplicate = client.post("/api/billing/checkout-v2", json=body, headers=simulator_app["buyer"])
        assert duplicate.status_code == 200
        assert duplicate.json()["payment_id"] == payload["payment_id"]
        assert duplicate.json()["idempotent"] is True

        settled = client.post(
            f"/api/admin/payments/{payload['payment_id']}/simulate-v2",
            json={"status": "succeeded", "reason": "Автоматический интеграционный тест"},
            headers=simulator_app["admin"],
        )
        assert settled.status_code == 200, settled.text

        status = client.get(
            f"/api/billing/payments/{payload['payment_id']}/status-v2",
            headers=simulator_app["buyer"],
        )
        assert status.status_code == 200
        assert status.json()["payment"]["status"] == "paid"
        assert status.json()["account"]["token_balance"] == 60

        processed = client.post(
            "/api/admin/payments/notifications/process-v2",
            json={"limit": 20, "reason": "Проверка очереди уведомлений"},
            headers=simulator_app["admin"],
        )
        assert processed.status_code == 200, processed.text
        assert processed.json()["sent"] == 1

    with main.db() as conn:
        assert conn.execute("SELECT COUNT(*) AS c FROM token_ledger WHERE reason='payment_grant'").fetchone()["c"] == 1
        assert conn.execute("SELECT COUNT(*) AS c FROM audit_logs WHERE action='admin_simulate_payment'").fetchone()["c"] == 1
        notification = conn.execute("SELECT * FROM payment_notification_outbox").fetchone()
        assert notification["channel"] == "in_app"
        assert notification["status"] == "sent"


def test_simulator_checkout_cancellation_updates_invoice(simulator_app) -> None:
    with TestClient(main.app) as client:
        checkout = client.post(
            "/api/billing/checkout-v2",
            json={
                "package_code": "tokens_50",
                "idempotency_key": "simulator-checkout-0002",
                "offer_accepted": True,
                "receipt_contact": "+79990000000",
            },
            headers=simulator_app["buyer"],
        ).json()
        canceled = client.post(
            f"/api/admin/payments/{checkout['payment_id']}/simulate-v2",
            json={"status": "canceled", "reason": "Проверка отмены платежа"},
            headers=simulator_app["admin"],
        )
        assert canceled.status_code == 200, canceled.text
    with main.db() as conn:
        payment = conn.execute("SELECT * FROM payments WHERE id=?", (checkout["payment_id"],)).fetchone()
        invoice = conn.execute("SELECT * FROM invoices WHERE id=?", (payment["invoice_id"],)).fetchone()
        assert payment["status"] == "canceled"
        assert invoice["status"] == "cancelled"


def test_admin_reconciliation_finishes_pending_simulated_payment(simulator_app) -> None:
    with TestClient(main.app) as client:
        checkout = client.post(
            "/api/billing/checkout-v2",
            json={
                "package_code": "tokens_50",
                "idempotency_key": "simulator-reconcile-0001",
                "offer_accepted": True,
                "receipt_contact": "buyer@example.test",
            },
            headers=simulator_app["buyer"],
        ).json()
        main.simulated_payment_provider().transition(checkout["provider_payment_id"], "succeeded")
        reconciled = client.post(
            "/api/admin/payments/reconcile-v2",
            json={"limit": 20, "reason": "Проверка фоновой сверки"},
            headers=simulator_app["admin"],
        )
        assert reconciled.status_code == 200, reconciled.text
        assert reconciled.json()["paid"] == 1

    with main.db() as conn:
        payment = conn.execute("SELECT * FROM payments WHERE id=?", (checkout["payment_id"],)).fetchone()
        assert payment["status"] == "paid"
        assert conn.execute("SELECT COUNT(*) AS c FROM token_ledger WHERE reason='payment_grant'").fetchone()["c"] == 1
        assert conn.execute("SELECT COUNT(*) AS c FROM audit_logs WHERE action='admin_reconcile_payments'").fetchone()["c"] == 1
