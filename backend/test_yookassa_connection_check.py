from __future__ import annotations

import asyncio

import httpx
import pytest
from fastapi.testclient import TestClient
from test_support.browser_client import BrowserTestClient

import main
from app.integrations.yookassa import YooKassaError, check_yookassa_connection


def test_connection_check_reads_payments_without_creating_one() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"type": "list", "items": []})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await check_yookassa_connection(shop_id="shop", secret_key="secret", client=client)

    result = asyncio.run(run())
    assert result.payments_visible == 0
    assert len(requests) == 1
    assert requests[0].method == "GET"
    assert requests[0].url.path == "/v3/payments"
    assert requests[0].url.params["limit"] == "1"


def test_connection_check_explains_invalid_credentials() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"type": "error", "code": "invalid_credentials"})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await check_yookassa_connection(shop_id="bad", secret_key="bad-secret", client=client)

    with pytest.raises(YooKassaError, match="shopId"):
        asyncio.run(run())


@pytest.fixture
def admin_app(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "admin-yookassa.sqlite3")
    monkeypatch.setattr(main, "TRUSTED_COOKIE_SECURE", False)
    monkeypatch.setattr(main, "yookassa_secret_key", lambda: "saved-secret")
    main.init_db()
    with main.db() as conn:
        conn.execute(
            "INSERT INTO users (id, internal_user_id, role, token_balance, language, created_at, last_login_at) "
            "VALUES ('admin', 'iuid-admin', 'admin', 0, 'ru', '2026-01-01', '2026-01-01')"
        )
        conn.execute(
            "INSERT INTO admin_settings (key, value_json, updated_at) VALUES ('yookassa', ?, '2026-01-01')",
            ('{"shop_id":"saved-shop","test_mode":true,"receipt_vat_code":1,"payment_subject":"service"}',),
        )
    token = main.create_auth_session("iuid-admin", "admin", provider="web_email", platform="web_desktop")["session_token"]
    return {"headers": {"Authorization": f"Bearer {token}"}, "monkeypatch": monkeypatch}


def test_admin_connection_check_persists_success(admin_app) -> None:
    class Result:
        payments_visible = 1

    async def successful_check(**_kwargs):
        return Result()

    admin_app["monkeypatch"].setattr(main, "check_yookassa_connection", successful_check)
    with BrowserTestClient(main.app) as client:
        response = client.post("/api/admin/payments/check-v2", json={}, headers=admin_app["headers"])
        status = client.get("/api/admin/payments/status-v2", headers=admin_app["headers"])
    assert response.status_code == 200, response.text
    assert response.json()["ok"] is True
    assert status.json()["connection_check"]["ok"] is True
    assert status.json()["connection_check"]["checked_at"]


def test_admin_connection_check_persists_failure(admin_app) -> None:
    async def failed_check(**_kwargs):
        raise YooKassaError("ЮKassa не приняла shopId или секретный ключ.")

    admin_app["monkeypatch"].setattr(main, "check_yookassa_connection", failed_check)
    with BrowserTestClient(main.app) as client:
        response = client.post("/api/admin/payments/check-v2", json={}, headers=admin_app["headers"])
        status = client.get("/api/admin/payments/status-v2", headers=admin_app["headers"])
    assert response.status_code == 502
    assert "shopId" in response.json()["message"]
    assert status.json()["connection_check"]["ok"] is False
