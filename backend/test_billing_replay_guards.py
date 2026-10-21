"""Owned SQLite + normal HTTP payment replay regressions; local simulator only.

The existing simulator fixture uses the real app, schema and trusted sessions.
No notification processor or live-provider route is invoked by this module.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import threading
import uuid

from fastapi.testclient import TestClient
import pytest

import main
from test_billing_simulator_checkout_v2 import simulator_app


@pytest.fixture
def replay_app(simulator_app):
    with main.db() as conn:
        conn.execute(
            "INSERT INTO users (id,internal_user_id,role,token_balance,language,created_at,last_login_at) "
            "VALUES ('other-buyer','iuid-other-buyer','user',13,'ru','2026-01-01','2026-01-01')"
        )
    token = main.create_auth_session("iuid-other-buyer", "other-buyer", provider="web_email",
                                     platform="web_desktop")["session_token"]
    return simulator_app | {"other": {"Authorization": f"Bearer {token}"}}


def checkout_body(key: str) -> dict:
    return {"package_code": "tokens_50", "idempotency_key": key,
            "offer_accepted": True, "receipt_contact": "buyer@example.test"}


def financial_state() -> dict:
    # Audit/session activity may advance on a replay; financial obligations may not.
    with main.db() as conn:
        state = {table: [dict(row) for row in conn.execute(f"SELECT * FROM {table} ORDER BY id")]
                 for table in ("payments", "invoices", "invoice_items", "refunds", "token_ledger",
                               "legal_acceptances", "payment_notification_outbox")}
        state["users"] = [dict(row) for row in conn.execute(
            "SELECT id,internal_user_id,token_balance,daily_tokens_used FROM users ORDER BY id")]
        return state


def settle(client: TestClient, payment_id: str, headers: dict):
    return client.post(f"/api/admin/payments/{payment_id}/simulate-v2",
        json={"status": "succeeded", "reason": "Owned payment replay regression"}, headers=headers)


def test_checkout_replay_never_discloses_another_users_payment(replay_app):
    body = checkout_body("owner-checkout-" + uuid.uuid4().hex)
    with TestClient(main.app) as client:
        first = client.post("/api/billing/checkout-v2", json=body, headers=replay_app["buyer"])
        assert first.status_code == 200
        payment = first.json()
        same = client.post("/api/billing/checkout-v2", json=body, headers=replay_app["buyer"])
        assert same.status_code == 200
        assert same.json()["payment_id"] == payment["payment_id"]
        assert same.json()["idempotent"] is True
        before = financial_state()
        for _ in range(5):
            foreign = client.post("/api/billing/checkout-v2", json=body, headers=replay_app["other"])
            assert foreign.status_code == 409
            public = json.dumps(foreign.json())
            for private in (payment["payment_id"], payment["provider_payment_id"], "iuid-buyer"):
                assert private not in public
            assert financial_state() == before
        assert client.get(f"/api/billing/payments/{payment['payment_id']}/status-v2",
                          headers=replay_app["other"]).status_code == 404
        assert client.post("/api/billing/checkout-v2", json=body).status_code == 401
        assert financial_state() == before


@pytest.mark.parametrize("refund_kind", ("full", "partial"))
def test_refunded_success_replay_preserves_money_ledger_and_terminal_state(replay_app, refund_kind):
    with TestClient(main.app) as client:
        checkout = client.post("/api/billing/checkout-v2",
            json=checkout_body("refund-checkout-" + uuid.uuid4().hex), headers=replay_app["buyer"])
        assert checkout.status_code == 200
        payment_id = checkout.json()["payment_id"]
        paid = settle(client, payment_id, replay_app["admin"])
        assert paid.status_code == 200
        assert paid.json()["completed"]["idempotent"] is False
        paid_state = financial_state()
        again = settle(client, payment_id, replay_app["admin"])
        assert again.status_code == 200 and again.json()["completed"]["idempotent"] is True
        assert financial_state() == paid_state
        original = next(row for row in paid_state["payments"] if row["id"] == payment_id)
        amount = int(original["amount"])
        assert amount > 1
        refund_amount = amount if refund_kind == "full" else amount // 2
        expected_status = "refunded" if refund_kind == "full" else "partially_refunded"
        refund_body = {"amount": refund_amount, "reason": "Owned simulator refund regression",
                       "idempotency_key": "refund-" + uuid.uuid4().hex}
        refund = client.post(f"/api/admin/payments/{payment_id}/refund-v2",
                             json=refund_body, headers=replay_app["admin"])
        assert refund.status_code == 200
        assert refund.json()["payment"]["status"] == expected_status
        assert refund.json()["refund"]["token_reversal_policy"] == "deferred"
        assert not refund.json()["refund"]["token_reversal_ledger_id"]
        before = financial_state()
        assert before["users"] == paid_state["users"]
        assert before["token_ledger"] == paid_state["token_ledger"]
        assert len([row for row in before["token_ledger"] if row["reason"] == "payment_grant"]) == 1
        refund_again = client.post(f"/api/admin/payments/{payment_id}/refund-v2",
                                   json=refund_body, headers=replay_app["admin"])
        assert refund_again.status_code == 200 and refund_again.json()["idempotent"] is True
        assert financial_state() == before
        # Five exact two-request replay races; each uses the same refunded payment.
        for _ in range(5):
            barrier = threading.Barrier(2)
            def retry():
                barrier.wait(timeout=5)
                return settle(client, payment_id, replay_app["admin"])
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(retry) for _ in range(2)]
                replies = [future.result(timeout=15) for future in futures]
            for reply in replies:
                assert reply.status_code == 200
                assert reply.json()["payment"]["status"] == expected_status
                assert reply.json()["completed"]["idempotent"] is True
            assert financial_state() == before
        status = client.get(f"/api/billing/payments/{payment_id}/status-v2", headers=replay_app["buyer"])
        assert status.status_code == 200 and status.json()["payment"]["status"] == expected_status
        assert financial_state() == before
        with main.db() as conn:
            actions = conn.execute("SELECT COUNT(*) FROM audit_logs WHERE action='admin_simulate_payment' AND entity_id=?",
                                   (payment_id,)).fetchone()[0]
        assert actions >= 12
