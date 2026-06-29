from __future__ import annotations

import base64
import asyncio
import time
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from PIL import Image

import main


MODES = [
    "text_to_image",
    "image_to_image",
    "edit",
    "paint",
    "inpaint",
    "outpaint",
    "faceswap",
    "remove_background",
    "try_on",
    "texture_transfer",
]


def tiny_image_data_url() -> str:
    image = Image.new("RGB", (8, 8), "#117865")
    buffer = BytesIO()
    image.save(buffer, "PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def wait_for_terminal_job(client: TestClient, job_id: str, timeout: float = 8) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        response = client.get(f"/api/jobs/{job_id}")
        assert response.status_code == 200
        payload = response.json()
        if payload["status"] in {"completed", "failed", "cancelled"}:
            return payload
        time.sleep(0.2)
    raise AssertionError(f"job {job_id} did not finish before timeout")


async def fake_send_to_comfyui(_payload: main.GenerateRequest, job: dict) -> main.ComfyUIResult:
    image_path, thumb_path = main.mock_image(_payload, job["id"])
    return main.ComfyUIResult(prompt_id="prompt_test_123", image_path=image_path, thumbnail_path=thumb_path, history={"outputs": {}})


# Populated by the isolated_db fixture for each test: the seeded admin user and a
# trusted server session whose raw token is sent as the onenode_session cookie.
_SESSION: dict[str, str] = {}


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    """Run every test against a throwaway SQLite file — never the working DB.

    Also seeds one admin user plus a trusted server session so endpoints guarded
    by require_trusted_user / require_admin can be exercised. POST /api/generate
    now demands a trusted session (see test_generation_protection.py); admin
    endpoints still use the legacy request_user_id path (X-OneNode-User header).
    """
    db_file = tmp_path / "api_test.sqlite3"
    monkeypatch.setattr(main, "DB_PATH", db_file)
    monkeypatch.setattr(main, "TRUSTED_COOKIE_SECURE", False)
    main.init_db()
    main.jobs.clear()
    main.images.clear()
    main.queue = asyncio.Queue()
    main.worker_started = False
    main.bot_polling_started = False
    main.bot_polling_tasks.clear()

    iuid = "iuid-api-test"
    legacy = "web_apitest"
    now = "2026-01-01T00:00:00+00:00"
    with main.db() as conn:
        conn.execute(
            "INSERT INTO users (id, internal_user_id, language, role, token_balance, created_at, last_login_at)"
            " VALUES (?, ?, 'ru', 'admin', 100000, ?, ?)",
            (legacy, iuid, now, now),
        )
        conn.execute(
            "INSERT INTO auth_identities (id, internal_user_id, legacy_user_id, provider, provider_user_id, linked_at)"
            " VALUES (?, ?, ?, 'web_email', 'apitest@local', ?)",
            ("id-api-test", iuid, legacy, now),
        )
    session = main.create_auth_session(iuid, legacy, provider="web_email", platform="web_desktop")
    _SESSION.clear()
    _SESSION.update({"internal_user_id": iuid, "legacy_user_id": legacy, "session_token": session["session_token"]})
    yield
    _SESSION.clear()


def authed_client() -> TestClient:
    """TestClient carrying the trusted session cookie + matching legacy header."""
    client = TestClient(main.app)
    client.cookies.set(main.TRUSTED_SESSION_COOKIE_NAME, _SESSION["session_token"])
    client.headers.update({"X-OneNode-User": _SESSION["legacy_user_id"]})
    return client


def test_health_reports_core_fields(monkeypatch) -> None:
    async def fake_available() -> bool:
        return True

    monkeypatch.setattr(main, "comfyui_available", fake_available)
    with TestClient(main.app) as client:
        response = client.get("/api/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["comfyuiBaseUrl"] == main.COMFYUI_BASE_URL
    assert payload["fluxKleinOneNode"] is True
    assert payload["database"]["ready"] is True
    assert payload["db_guard"]["status"] == "ok"
    assert payload["database"]["users_count"] >= 1
    assert payload["database"]["active_admin_count"] >= 1
    assert "sqlite" in payload["database"]["type"]
    assert "://" not in payload["database"]["path"]
    assert payload["platforms"] == {"web": True, "telegram": True, "max": True}


def test_all_generation_modes_complete_and_save_gallery_records(monkeypatch) -> None:
    monkeypatch.setattr(main, "send_to_comfyui", fake_send_to_comfyui)
    data_url = tiny_image_data_url()

    with authed_client() as client:
        completed = []
        for mode in MODES:
            body = {
                "mode": mode,
                "provider": "comfyui",
                "prompt": f"automated test prompt for {mode}",
                "seed": 100,
                "width": 512,
                "height": 512,
                "inputImage1": data_url if mode != "text_to_image" else None,
                "inputImage2": data_url if mode in {"faceswap", "try_on", "texture_transfer"} else None,
                "canvas": "[]" if mode in {"paint", "inpaint"} else None,
                "loras": [{"id": "bfs_head_v1_flux-klein_9b_step3500_rank128.safetensors", "strength": 1.0}] if mode == "faceswap" else [],
            }
            response = client.post("/api/generate", json=body)
            assert response.status_code == 200
            created = response.json()
            assert created["status"] == "queued"
            final = wait_for_terminal_job(client, created["id"])
            assert final["status"] == "completed"
            assert final["progress"] == 100
            assert final["resultImageId"]
            assert final["resultUrl"].split("?", 1)[0].endswith(".png")
            completed.append(final)

        gallery = client.get("/api/gallery").json()
        assert len(gallery) == len(MODES)
        assert {item["mode"] for item in gallery} == set(MODES)
        assert all(item["thumbnailUrl"].split("?", 1)[0].endswith(".webp") for item in gallery)
        assert all(item["comfyuiPromptId"] == "prompt_test_123" for item in gallery)
        assert len(completed) == len(MODES)


def test_openrouter_generation_skips_comfyui(monkeypatch) -> None:
    async def fail_if_called(_payload: main.GenerateRequest, _job: dict) -> str:
        raise AssertionError("OpenRouter path must not call ComfyUI adapter")

    monkeypatch.setattr(main, "send_to_comfyui", fail_if_called)
    with authed_client() as client:
        response = client.post(
            "/api/generate",
            json={
                "mode": "text_to_image",
                "provider": "openrouter",
                "prompt": "cloud image test",
                "width": 512,
                "height": 512,
            },
        )
        assert response.status_code == 200
        final = wait_for_terminal_job(client, response.json()["id"])

    assert final["status"] == "completed"
    assert final["resultUrl"].split("?", 1)[0].endswith(".png")


def test_cancel_generation_sets_cancelled_status(monkeypatch) -> None:
    monkeypatch.setattr(main, "send_to_comfyui", fake_send_to_comfyui)
    with authed_client() as client:
        created = client.post(
            "/api/generate",
            json={"mode": "text_to_image", "provider": "comfyui", "prompt": "cancel me", "width": 512, "height": 512},
        ).json()
        cancelled = client.post(f"/api/jobs/{created['id']}/cancel").json()
        final = wait_for_terminal_job(client, created["id"])

    assert cancelled["status"] == "cancelled"
    assert final["status"] == "cancelled"


def test_validation_and_not_found_errors() -> None:
    with authed_client() as client:
        bad_size = client.post(
            "/api/generate",
            json={"mode": "text_to_image", "provider": "comfyui", "prompt": "bad", "width": 128, "height": 512},
        )
        missing_faceswap_lora = client.post(
            "/api/generate",
            json={"mode": "faceswap", "provider": "comfyui", "prompt": "swap", "width": 512, "height": 512, "inputImage1": tiny_image_data_url(), "inputImage2": tiny_image_data_url()},
        )
        missing = client.get("/api/jobs/missing")

    assert bad_size.status_code == 422
    assert missing_faceswap_lora.status_code == 422
    assert missing.status_code == 404


def test_translate_presets_webhooks_and_admin(monkeypatch) -> None:
    monkeypatch.setattr(main, "send_to_comfyui", fake_send_to_comfyui)
    with authed_client() as client:
        ru_to_en = client.post("/api/translate", json={"text": "уютная студия", "target": "en"}).json()
        en_to_ru = client.post("/api/translate", json={"text": "cozy studio", "target": "ru"}).json()
        presets = client.get("/api/presets").json()
        # Webhooks now expect the real Telegram/MAX update shape (message as an
        # object) and only acknowledge with {"ok": True}; replies are pushed via
        # the bot APIs, not returned inline. Omit chat/sender so no outbound send
        # is attempted. Button payloads are covered by the bot-adapter tests.
        telegram = client.post("/api/telegram/webhook", json={"message": {"text": "/start"}}).json()
        max_hook = client.post("/api/max/webhook", json={"message": {"text": "/app"}}).json()
        client.post(
            "/api/generate",
            json={"mode": "text_to_image", "provider": "comfyui", "prompt": "admin summary", "width": 512, "height": 512},
        )
        summary = client.get("/api/admin/summary").json()

    assert "translated to English" in ru_to_en["translated"]
    assert "черновой перевод" in en_to_ru["translated"]
    assert {item["id"] for item in presets} >= {"portrait", "enhance", "collage"}
    assert telegram["ok"] is True
    assert max_hook["ok"] is True
    assert summary["users"] >= 1
    assert summary["jobs"] >= 1
    assert "local_flux_klein" in summary["availableModels"]


def test_stage1_bootstrap_platforms_and_database_are_ready() -> None:
    with TestClient(main.app) as client:
        web = client.post("/api/app/bootstrap", json={"platform": "web", "language": "ru"}).json()
        telegram = client.post(
            "/api/app/bootstrap",
            json={"platform": "telegram", "userId": "42", "username": "tg_user", "firstName": "Tg", "language": "ru"},
        ).json()
        max_app = client.post(
            "/api/app/bootstrap",
            json={"platform": "max", "userId": "99", "username": "max_user", "firstName": "Max", "language": "ru"},
        ).json()
        platforms = client.get("/api/platforms").json()

    assert web["ok"] is True
    assert web["features"]["database"] is True
    # Telegram bootstrap without server-validated initData now degrades to a web
    # identity (real Telegram identity is covered by test_auth_telegram_v2.py).
    assert telegram["user"]["id"] == "web_42"
    assert max_app["user"]["id"] == "max_99"
    assert platforms["web"]["ready"] is True
    assert platforms["telegram"]["ready"] is True
    assert platforms["max"]["ready"] is True
    assert platforms["database"]["ready"] is True


def test_bootstrap_includes_flux_klein_runtime_data(monkeypatch) -> None:
    async def fake_config() -> dict:
        return {
            "autofill_prompts": {},
            "lora_triggers_custom": {},
            "t2i_templates": [{"name": "Foggy street deer", "prompt": "A silhouetted deer"}],
            "discover_prompts": {"faceswap": {"categories": [{"cat": "FACE SWAP", "items": [{"label": "Head swap", "prompt": "Replace the head"}]}]}},
        }

    async def fake_models() -> dict:
        return {"diffusion_models": ["flux-2-klein-4b-fp8.safetensors"], "text_encoders": ["clip.safetensors"], "vaes": ["ae.safetensors"], "loras": ["bfs_head.safetensors"]}

    async def fake_bgremoval() -> dict:
        return {"models": ["BiRefNet"]}

    monkeypatch.setattr(main, "get_flux_klein_config", fake_config)
    monkeypatch.setattr(main, "get_comfyui_models", fake_models)
    monkeypatch.setattr(main, "get_flux_bgremoval_models", fake_bgremoval)

    with TestClient(main.app) as client:
        payload = client.post("/api/app/bootstrap", json={"platform": "web", "language": "ru"}).json()

    assert payload["features"]["modes"] == ["text_to_image", "image_to_image", "edit", "paint", "faceswap"]
    assert payload["fluxKleinConfig"]["t2i_templates"][0]["name"] == "Foggy street deer"
    assert "faceswap" in payload["fluxKleinConfig"]["discover_prompts"]
    assert payload["models"]["diffusion_models"] == ["flux-2-klein-4b-fp8.safetensors"]
    assert payload["bgRemovalModels"]["models"] == ["BiRefNet"]


def test_bot_adapters_work_without_domain_in_local_mode(monkeypatch) -> None:
    monkeypatch.setattr(main, "BOT_MODE", "local")
    monkeypatch.setattr(main, "TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setattr(main, "MAX_BOT_TOKEN", "")

    with TestClient(main.app) as client:
        status = client.get("/api/bots/status").json()
        telegram = client.post("/api/bots/local-command", json={"platform": "telegram", "text": "/app", "chatId": "1"}).json()
        max_app = client.post("/api/bots/local-command", json={"platform": "max", "text": "/settings", "chatId": "2"}).json()
        missing_token = client.post("/api/telegram/send-message", json={"chatId": "1", "text": "hello"})

    assert status["mode"] == "local"
    assert status["domainRequired"] is False
    assert status["telegram"]["local"] is True
    assert status["telegram"]["pollingReady"] is False
    assert telegram["delivery"] == "local"
    assert telegram["buttons"][0]["url"].endswith("?platform=telegram")
    assert max_app["buttons"][0]["url"].endswith("?platform=max#settings")
    assert missing_token.status_code == 400


def test_real_bot_endpoints_require_tokens_and_https(monkeypatch) -> None:
    monkeypatch.setattr(main, "TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setattr(main, "MAX_BOT_TOKEN", "")
    monkeypatch.setenv("BACKEND_PUBLIC_URL", "http://127.0.0.1:8000")

    with TestClient(main.app) as client:
        telegram_poll = client.post("/api/telegram/poll-once")
        max_send = client.post("/api/max/send-message", json={"userId": "1", "text": "hello"})
        telegram_webhook = client.post("/api/telegram/set-webhook")
        max_webhook = client.post("/api/max/set-webhook")

    assert telegram_poll.status_code == 400
    assert max_send.status_code == 400
    assert telegram_webhook.status_code == 400
    assert max_webhook.status_code == 400


def test_max_api_uses_authorization_header(monkeypatch) -> None:
    calls = []

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"message": {"id": "m1"}}

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self) -> "FakeAsyncClient":
            return self

        async def __aexit__(self, *args) -> None:
            return None

        async def request(self, method: str, url: str, headers: dict, json: dict | None = None, params: dict | None = None) -> FakeResponse:
            calls.append({"method": method, "url": url, "headers": headers, "json": json, "params": params})
            return FakeResponse()

    monkeypatch.setattr(main, "MAX_BOT_TOKEN", "max_secret")
    monkeypatch.setattr(main.httpx, "AsyncClient", FakeAsyncClient)

    with TestClient(main.app) as client:
        payload = client.post("/api/max/send-message", json={"userId": "100", "text": "hello"}).json()

    assert payload["message"]["id"] == "m1"
    assert calls[0]["method"] == "POST"
    assert calls[0]["url"].endswith("/messages")
    assert calls[0]["headers"]["Authorization"] == "max_secret"
    assert calls[0]["params"] == {"user_id": "100"}


def test_telegram_poll_once_sends_command_reply(monkeypatch) -> None:
    calls = []

    async def fake_telegram_api(method: str, payload: dict | None = None) -> dict:
        calls.append({"method": method, "payload": payload})
        if method == "getUpdates":
            return {
                "ok": True,
                "result": [
                    {"update_id": 10, "message": {"text": "/app", "chat": {"id": 777}}},
                ],
            }
        return {"ok": True, "result": {"message_id": 1}}

    monkeypatch.setattr(main, "telegram_api", fake_telegram_api)

    result = asyncio.run(main.telegram_poll_once_from_api(timeout=0, limit=10))

    assert result["handled"][0]["chatId"] == 777
    assert calls[0]["method"] == "getUpdates"
    assert calls[1]["method"] == "sendMessage"
    assert calls[1]["payload"]["chat_id"] == 777
    assert calls[1]["payload"]["reply_markup"]["inline_keyboard"][0][0]["text"] == "Открыть генератор"


def test_max_poll_once_sends_command_reply(monkeypatch) -> None:
    calls = []

    async def fake_max_api(method: str, path: str, payload: dict | None = None, params: dict | None = None) -> dict:
        calls.append({"method": method, "path": path, "payload": payload, "params": params})
        if method == "GET":
            return {
                "updates": [
                    {"message": {"body": {"text": "/settings"}, "sender": {"user_id": "u1"}}},
                ],
                "marker": "next",
            }
        return {"message": {"id": "m1"}}

    monkeypatch.setattr(main, "max_api", fake_max_api)

    result = asyncio.run(main.max_poll_once_from_api(timeout=0, limit=10))

    assert result["handled"][0]["recipient"] == {"user_id": "u1"}
    assert calls[0]["method"] == "GET"
    assert calls[1]["method"] == "POST"
    assert calls[1]["path"] == "/messages"
    assert calls[1]["params"] == {"user_id": "u1"}
    assert "Открыть настройки" in calls[1]["payload"]["text"]


def test_telegram_polling_persists_offset_and_uses_allowed_updates(monkeypatch) -> None:
    calls = []

    async def fake_telegram_api(method: str, payload: dict | None = None) -> dict:
        calls.append({"method": method, "payload": payload})
        if method == "getUpdates":
            return {"ok": True, "result": [{"update_id": 15, "message": {"text": "/app", "chat": {"id": 777}}}]}
        return {"ok": True, "result": {"message_id": 1}}

    monkeypatch.setattr(main, "telegram_api", fake_telegram_api)

    result = asyncio.run(main.telegram_poll_once_from_api(timeout=0, limit=10))

    assert result["cursor"] == "16"
    assert calls[0]["payload"]["allowed_updates"] == ["message", "callback_query"]
    assert calls[0]["payload"].get("offset") is None
    with main.db() as conn:
        row = conn.execute("SELECT cursor FROM bot_polling_state WHERE provider = 'telegram'").fetchone()
    assert row["cursor"] == "16"


def test_telegram_polling_callback_query_and_saved_offset(monkeypatch) -> None:
    calls = []
    main.set_bot_polling_cursor("telegram", 16)

    async def fake_telegram_api(method: str, payload: dict | None = None) -> dict:
        calls.append({"method": method, "payload": payload})
        if method == "getUpdates":
            return {
                "ok": True,
                "result": [
                    {
                        "update_id": 16,
                        "callback_query": {
                            "id": "cb1",
                            "data": "/settings",
                            "message": {"chat": {"id": 888}},
                        },
                    }
                ],
            }
        return {"ok": True, "result": {"message_id": 1}}

    monkeypatch.setattr(main, "telegram_api", fake_telegram_api)

    result = asyncio.run(main.telegram_poll_once_from_api(timeout=0, limit=10))

    assert calls[0]["payload"]["offset"] == 16
    assert result["cursor"] == "17"
    assert result["handled"][0]["chatId"] == 888
    assert calls[1]["method"] == "sendMessage"
    assert calls[2]["method"] == "answerCallbackQuery"


def test_telegram_saved_offset_prevents_repeat(monkeypatch) -> None:
    calls = []
    main.set_bot_polling_cursor("telegram", 42)

    async def fake_telegram_api(method: str, payload: dict | None = None) -> dict:
        calls.append({"method": method, "payload": payload})
        return {"ok": True, "result": []}

    monkeypatch.setattr(main, "telegram_api", fake_telegram_api)

    result = asyncio.run(main.telegram_poll_once_from_api(timeout=0, limit=10))

    assert calls[0]["payload"]["offset"] == 42
    assert result["handled"] == []
    assert result["cursor"] == "42"


def test_max_polling_persists_marker(monkeypatch) -> None:
    calls = []

    async def fake_max_api(method: str, path: str, payload: dict | None = None, params: dict | None = None) -> dict:
        calls.append({"method": method, "path": path, "payload": payload, "params": params})
        if method == "GET":
            return {"updates": [{"message": {"body": {"text": "/app"}, "sender": {"user_id": "u1"}}}], "marker": "m2"}
        return {"message": {"id": "m1"}}

    monkeypatch.setattr(main, "max_api", fake_max_api)

    result = asyncio.run(main.max_poll_once_from_api(timeout=0, limit=10))

    assert calls[0]["params"] == {"limit": 10, "timeout": 0}
    assert result["marker"] == "m2"
    with main.db() as conn:
        row = conn.execute("SELECT cursor FROM bot_polling_state WHERE provider = 'max'").fetchone()
    assert row["cursor"] == "m2"


def test_max_polling_uses_saved_marker(monkeypatch) -> None:
    calls = []
    main.set_bot_polling_cursor("max", "m2")

    async def fake_max_api(method: str, path: str, payload: dict | None = None, params: dict | None = None) -> dict:
        calls.append({"method": method, "path": path, "payload": payload, "params": params})
        return {"updates": [], "marker": "m3"}

    monkeypatch.setattr(main, "max_api", fake_max_api)

    result = asyncio.run(main.max_poll_once_from_api(timeout=0, limit=10))

    assert calls[0]["params"]["marker"] == "m2"
    assert result["marker"] == "m3"


def test_bot_polling_start_respects_mode_and_guard(monkeypatch) -> None:
    created = []

    class FakeTask:
        pass

    def fake_create_task(coro):
        coro.close()
        task = FakeTask()
        created.append(task)
        return task

    monkeypatch.setattr(main.asyncio, "create_task", fake_create_task)
    monkeypatch.setattr(main, "BOT_UPDATES_MODE", "webhook")
    monkeypatch.setattr(main, "TELEGRAM_BOT_TOKEN", "tg")
    monkeypatch.setattr(main, "MAX_BOT_TOKEN", "max")
    assert main.start_bot_polling_tasks() == []
    assert created == []

    monkeypatch.setattr(main, "BOT_UPDATES_MODE", "polling")
    started = main.start_bot_polling_tasks()
    assert started == ["telegram", "max"]
    assert len(created) == 2
    assert main.start_bot_polling_tasks() == []
    assert len(created) == 2


def test_bot_webhook_endpoints_still_handle_commands(monkeypatch) -> None:
    telegram_calls = []
    max_calls = []

    async def fake_telegram_api(method: str, payload: dict | None = None) -> dict:
        telegram_calls.append({"method": method, "payload": payload})
        return {"ok": True, "result": {"message_id": 1}}

    async def fake_max_api(method: str, path: str, payload: dict | None = None, params: dict | None = None) -> dict:
        max_calls.append({"method": method, "path": path, "payload": payload, "params": params})
        return {"message": {"id": "m1"}}

    monkeypatch.setattr(main, "telegram_api", fake_telegram_api)
    monkeypatch.setattr(main, "max_api", fake_max_api)

    client = TestClient(main.app)
    tg = client.post("/api/telegram/webhook", json={"update_id": 1, "message": {"text": "/app", "chat": {"id": 777}}})
    mx = client.post("/api/max/webhook", json={"message": {"body": {"text": "/app"}, "sender": {"user_id": "u1"}}})

    assert tg.status_code == 200
    assert mx.status_code == 200
    assert telegram_calls[0]["method"] == "sendMessage"
    assert max_calls[0]["path"] == "/messages"


def test_completed_generation_is_persisted_to_sqlite(monkeypatch) -> None:
    monkeypatch.setattr(main, "send_to_comfyui", fake_send_to_comfyui)
    with authed_client() as client:
        created = client.post(
            "/api/generate",
            json={"mode": "text_to_image", "provider": "comfyui", "prompt": "persist me", "width": 512, "height": 512},
        ).json()
        final = wait_for_terminal_job(client, created["id"])

    with main.db() as conn:
        job_row = conn.execute("SELECT status, result_image_id FROM jobs WHERE id = ?", (created["id"],)).fetchone()
        image_row = conn.execute("SELECT id, prompt_original FROM images WHERE id = ?", (final["resultImageId"],)).fetchone()

    assert job_row["status"] == "completed"
    assert job_row["result_image_id"] == final["resultImageId"]
    assert image_row["prompt_original"] == "persist me"


def test_stage3_gallery_detail_favorite_use_as_and_delete(monkeypatch) -> None:
    monkeypatch.setattr(main, "send_to_comfyui", fake_send_to_comfyui)
    with authed_client() as client:
        created = client.post(
            "/api/generate",
            json={"mode": "text_to_image", "provider": "comfyui", "prompt": "gallery item", "width": 512, "height": 512},
        ).json()
        final = wait_for_terminal_job(client, created["id"])
        image_id = final["resultImageId"]
        detail = client.get(f"/api/gallery/{image_id}").json()
        favorite = client.post(f"/api/gallery/{image_id}/favorite", json={"isFavorite": True}).json()
        use_as = client.post(f"/api/gallery/{image_id}/use-as", json={"target": "image_to_image"}).json()
        deleted = client.delete(f"/api/gallery/{image_id}").json()
        missing = client.get(f"/api/gallery/{image_id}")

    assert detail["promptOriginal"] == "gallery item"
    assert favorite["isFavorite"] is True
    assert use_as["inputImage"].startswith("/api/media/")
    assert use_as["target"] == "image_to_image"
    assert deleted["ok"] is True
    assert missing.status_code == 404


def test_stage3_media_url_inputs_work_for_i2i_and_edit(monkeypatch) -> None:
    seen_modes = []

    async def fake_send(payload: main.GenerateRequest, job: dict) -> main.ComfyUIResult:
        seen_modes.append((payload.mode, payload.inputImage1, payload.inputImage2))
        image_path, thumb_path = main.mock_image(payload, job["id"])
        return main.ComfyUIResult(prompt_id=f"prompt_{payload.mode}", image_path=image_path, thumbnail_path=thumb_path, history={"outputs": {}})

    monkeypatch.setattr(main, "send_to_comfyui", fake_send)
    with authed_client() as client:
        first = client.post(
            "/api/generate",
            json={"mode": "text_to_image", "provider": "comfyui", "prompt": "source", "width": 512, "height": 512},
        ).json()
        first_final = wait_for_terminal_job(client, first["id"])
        source_url = first_final["resultUrl"]
        i2i = client.post(
            "/api/generate",
            json={"mode": "image_to_image", "provider": "comfyui", "prompt": "variation", "width": 512, "height": 512, "inputImage1": source_url},
        ).json()
        edit = client.post(
            "/api/generate",
            json={"mode": "edit", "provider": "comfyui", "prompt": "edit it", "width": 512, "height": 512, "inputImage1": source_url},
        ).json()
        i2i_final = wait_for_terminal_job(client, i2i["id"])
        edit_final = wait_for_terminal_job(client, edit["id"])

    assert i2i_final["status"] == "completed"
    assert edit_final["status"] == "completed"
    assert ("image_to_image", source_url, None) in seen_modes
    assert ("edit", source_url, None) in seen_modes


def test_stage3_local_media_url_resolves_to_safe_file() -> None:
    image_path, _thumb = main.mock_image(main.GenerateRequest(mode="text_to_image", prompt="media"), "job_media_url")
    resolved = main.local_media_path_from_url(f"/media/{image_path.name}")
    missing = main.local_media_path_from_url("/media/not-found.png")

    assert resolved == image_path.resolve()
    assert missing is None


def test_patch_t2i_workflow_sets_real_flux_values() -> None:
    prompt = {
        "FK:165": {"inputs": {"unet_name": "old"}},
        "FK:155": {"inputs": {"clip_name": "old"}},
        "FK:153": {"inputs": {"vae_name": "old"}},
        "FK:166": {"inputs": {"text": ""}},
        "FK:156": {"inputs": {"text": ""}},
        "FK:170": {"inputs": {"width": 1024, "height": 1024}},
        "FK:171": {"inputs": {"seed": 0, "steps": 4, "cfg": 1, "denoise": 1}},
        "FK:86": {"inputs": {"filename_prefix": "old"}},
    }
    request = main.GenerateRequest(
        mode="text_to_image",
        prompt="real comfy prompt",
        negativePrompt="no blur",
        seed=987,
        width=1920,
        height=1088,
        steps=12,
        cfg=2.5,
    )

    main.patch_mode_nodes(
        prompt,
        request,
        {},
        "flux-2-klein-9b-fp8.safetensors",
        "qwen_3_8b_fp8mixed.safetensors",
        "flux2-vae.safetensors",
    )

    assert prompt["FK:165"]["inputs"]["unet_name"] == "flux-2-klein-9b-fp8.safetensors"
    assert prompt["FK:155"]["inputs"]["clip_name"] == "qwen_3_8b_fp8mixed.safetensors"
    assert prompt["FK:153"]["inputs"]["vae_name"] == "flux2-vae.safetensors"
    assert prompt["FK:166"]["inputs"]["text"] == "real comfy prompt"
    assert prompt["FK:156"]["inputs"]["text"] == "no blur"
    assert prompt["FK:170"]["inputs"]["width"] == 1920
    assert prompt["FK:170"]["inputs"]["height"] == 1088
    assert prompt["FK:171"]["inputs"]["seed"] == 987
    assert prompt["FK:171"]["inputs"]["steps"] == 12
    assert prompt["FK:171"]["inputs"]["cfg"] == 2.5
    assert prompt["FK:86"]["inputs"]["filename_prefix"] == "one-node-flux-2-klein/FK"
