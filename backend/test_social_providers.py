import asyncio
import json
import sqlite3
from contextlib import contextmanager
import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routers.admin_operations import (
    AdminOperationsDependencies,
    create_admin_operations_router,
)
from app.database.migrations import (
    apply_admin_notification_delivery_migration,
    apply_admin_notifications_migration,
)
from app.integrations.social_providers import SocialProviderError, probe_social_provider


def test_telegram_probe_checks_bot_and_target_without_sending_messages():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/getMe"):
            return httpx.Response(200, json={"ok": True, "result": {"id": 1, "username": "izo_admin"}})
        return httpx.Response(200, json={"ok": True, "result": {"id": -1001, "title": "IZO"}})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await probe_social_provider(
                "telegram", token="fake-token", target_id="-1001", client=client
            )
    result = asyncio.run(run())
    assert result["identity"] == "izo_admin"
    assert [request.url.path.rsplit("/", 1)[-1] for request in requests] == ["getMe", "getChat"]
    assert all("send" not in request.url.path.lower() for request in requests)


def test_vk_and_instagram_probes_reject_provider_errors_safely():
    async def run(network: str):
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(403, json={"error": {"message": "private provider detail"}})
            )
        ) as client:
            await probe_social_provider(
                network, token="fake-token", target_id="123", client=client
            )

    with pytest.raises(SocialProviderError, match="VK отклонил"):
        asyncio.run(run("vk"))
    with pytest.raises(SocialProviderError, match="Instagram отклонил"):
        asyncio.run(run("instagram"))


def test_ok_probe_requires_all_credential_parts():
    with pytest.raises(SocialProviderError, match="application key"):
        asyncio.run(probe_social_provider("ok", token="fake", target_id=""))
    with pytest.raises(SocialProviderError, match="signed API"):
        asyncio.run(probe_social_provider(
            "ok", token="fake", target_id="group-1",
            application_key="public-key", session_secret="fake-session-secret",
        ))


def test_social_admin_credentials_are_write_only_and_deletable():
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE admin_settings (key TEXT PRIMARY KEY, value_json TEXT, updated_at TEXT)")
    apply_admin_notifications_migration(conn, applied_at="2026-07-24T00:00:00+00:00")
    apply_admin_notification_delivery_migration(
        conn, applied_at="2026-07-24T00:00:01+00:00"
    )
    settings_store = {}
    secrets = {}

    @contextmanager
    def db():
        yield conn
        conn.commit()

    def saved(key):
        return json.loads(json.dumps(settings_store.get(key, {})))

    async def probe(network, **kwargs):
        expected = "fake-telegram-token" if network == "telegram" else "fake-max-token"
        assert kwargs["token"] == expected
        return {"identity": f"fake_{network}", "target": {"id": kwargs["target_id"]}}

    sent_messages = []

    async def send_test(**kwargs):
        sent_messages.append(kwargs)
        if kwargs.get("network") == "max":
            return {"message": {"body": {"mid": "max-test-9"}}}
        return {"ok": True, "result": {"message_id": 321}}

    async def empty_async():
        return {}

    app = FastAPI()
    app.include_router(create_admin_operations_router(AdminOperationsDependencies(
        db=db,
        require_admin=lambda request: {"internal_user_id": "admin-1"},
        saved_setting=saved,
        save_setting=lambda key, value: settings_store.__setitem__(key, value),
        record_audit=lambda *args, **kwargs: None,
        fetch_openrouter_key_status=empty_async,
        openrouter_usage_stats=lambda: {},
        get_openrouter_config=lambda: {},
        fetch_usd_rub_rate=empty_async,
        openrouter_catalog_snapshot=lambda: {"meta": {}},
        schedule_openrouter_catalog_refresh=lambda: False,
        openrouter_economy_settings=lambda: {"usdFeePercent": 0.0},
        openrouter_price_catalog=lambda: {},
        invalidate_openrouter_admin_caches=lambda: None,
        secret_exists=lambda name: name in secrets,
        secret_get=lambda name: secrets.get(name, ""),
        secret_set=lambda name, value: secrets.__setitem__(name, value),
        secret_delete=lambda name: secrets.pop(name, None) is not None,
        probe_social=probe,
        send_social_test=send_test,
    )))
    client = TestClient(app)
    saved_response = client.put("/api/admin/social/telegram/credentials-v2", json={
        "token": "fake-telegram-token", "targetId": "@izo_channel",
    })
    assert saved_response.status_code == 200
    status = client.get("/api/admin/social-v2").json()
    assert status["settings"]["networks"]["telegram"]["configured"] is True
    assert "fake-telegram-token" not in json.dumps(status)
    assert client.post("/api/admin/social/telegram/check-v2").status_code == 200
    unchanged = client.put("/api/admin/social/telegram/credentials-v2", json={
        "token": "", "targetId": "@izo_channel",
    })
    assert unchanged.status_code == 200
    assert client.get("/api/admin/social-v2").json()["settings"]["networks"]["telegram"]["verified"] is True
    delivery = client.post("/api/admin/social/telegram/test-delivery-v2")
    assert delivery.status_code == 200
    assert delivery.json()["messageId"] == 321
    assert sent_messages == [{
        "network": "telegram",
        "token": "fake-telegram-token",
        "target_id": "@izo_channel",
        "text": (
            "✅ Тест публикации ИЗО АСА\n\n"
            "Подключение Telegram проверено. Это служебное тестовое сообщение из админки."
        ),
    }]
    assert client.delete("/api/admin/social/telegram/credentials-v2").json()["deleted"] is True
    assert "social_telegram_access_token" not in secrets

    max_saved = client.put("/api/admin/social/max/credentials-v2", json={
        "token": "fake-max-token", "targetId": "-700000000001",
    })
    assert max_saved.status_code == 200
    assert client.post("/api/admin/social/max/check-v2").status_code == 200
    max_delivery = client.post("/api/admin/social/max/test-delivery-v2")
    assert max_delivery.status_code == 200
    assert max_delivery.json()["messageId"] == "max-test-9"

    vk_saved = client.put("/api/admin/social/vk/credentials-v2", json={
        "token": "fake-vk-group-token", "mediaToken": "fake-vk-user-token",
        "targetId": "240405661",
    })
    assert vk_saved.status_code == 200
    vk_status = client.get("/api/admin/social-v2").json()["settings"]["networks"]["vk"]
    assert vk_status["configured"] is True
    assert vk_status["mediaConfigured"] is True
    assert "fake-vk-user-token" not in json.dumps(vk_status)
    assert client.delete("/api/admin/social/vk/credentials-v2").json()["deleted"] is True
    assert "social_vk_access_token" not in secrets
    assert "social_vk_media_access_token" not in secrets

    invalid = client.put("/api/admin/notifications/settings-v2", json={
        "settings": {
            "telegramEnabled": True,
            "telegramChatId": "",
            "emailEnabled": True,
            "emailAddress": "not-an-email",
        }
    })
    assert invalid.status_code == 400
    valid = client.put("/api/admin/notifications/settings-v2", json={
        "settings": {
            "telegramEnabled": True,
            "telegramChatId": "-1001",
            "emailEnabled": True,
            "emailAddress": "Admin@Example.test",
            "minimumSeverity": "warning",
            "digestMode": "immediate",
        }
    })
    assert valid.status_code == 200
    notification_status = client.get(
        "/api/admin/notifications/settings-v2"
    ).json()
    assert notification_status["settings"]["telegramChatId"] == "-1001"
    assert notification_status["settings"]["emailAddress"] == "admin@example.test"
    assert notification_status["worker"]["running"] is False
