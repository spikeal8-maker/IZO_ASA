from __future__ import annotations

import asyncio
import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

import main
# Browser-faithful contract: authenticated cookie-auth mutations carry an
# allowlisted Origin to pass the CSRF boundary (AUTH-LEGACY-001B).
from test_support.browser_origin import BROWSER_ORIGIN


@pytest.fixture
def temp_db(tmp_path: Path, monkeypatch):
    db_file = tmp_path / "identity.sqlite3"
    monkeypatch.setattr(main, "DB_PATH", db_file)
    monkeypatch.setattr(main, "TRUSTED_COOKIE_SECURE", False)
    monkeypatch.setattr(main, "APP_ENV", "development")
    monkeypatch.setattr(main, "TELEGRAM_BOT_USERNAME", "OneNodeTestBot")
    monkeypatch.setattr(main, "TELEGRAM_BOT_TOKEN", "test-telegram-token")
    monkeypatch.setattr(main, "MAX_BOT_TOKEN", "test-max-token")
    monkeypatch.setattr(main, "MAX_BOT_DEEP_LINK_BASE", "https://max.ru/onenode-test")
    avatar_dir = tmp_path / "avatars"
    avatar_dir.mkdir()
    monkeypatch.setattr(main, "AVATAR_DIR", avatar_dir)
    main.init_db()
    yield db_file


def _png_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), (10, 20, 30)).save(buf, format="PNG")
    return buf.getvalue()


def _login_token_from_deep_link(deep_link: str) -> str:
    from urllib.parse import parse_qs, urlparse
    payload = parse_qs(urlparse(deep_link).query).get("start", [""])[0]
    assert payload.startswith("login_")
    return payload.replace("login_", "", 1)


# --- Phase 1a: MAX user normalization ------------------------------------

def test_max_user_from_update_normalizes_avatar_and_language(temp_db):
    update = {
        "update_type": "bot_started",
        "user_locale": "ru-RU",
        "chat_id": 555,
        "user": {
            "user_id": "mx-7",
            "first_name": "Макс",
            "last_name": "Юзер",
            "avatar_url": "https://cdn.example/a.png",
            "full_avatar_url": "https://cdn.example/full.png",
        },
        "payload": "login_abc",
    }
    user = main.max_user_from_update(update, {})
    assert user is not None
    assert user["id"] == "mx-7"
    # avatar mapped onto the canonical photo_url (prefers full_avatar_url)
    assert user["photo_url"] == "https://cdn.example/full.png"
    # locale (top-level on the update) mapped onto canonical language_code
    assert user["language_code"] == "ru-RU"


# --- Phase 1b/1c: MAX login captures avatar/lang/name + caches avatar -----

def test_max_login_captures_profile_and_caches_avatar(temp_db, monkeypatch):
    async def fake_max_api(method, path, payload=None, params=None):
        return {"ok": True, "path": path}

    async def fake_download(url: str):
        assert url == "https://cdn.example/full.png"
        return _png_bytes()

    monkeypatch.setattr(main, "max_api", fake_max_api)
    monkeypatch.setattr(main, "_download_avatar_bytes", fake_download)

    client = TestClient(main.app)
    started = client.post("/api/auth/bot-login/start", json={"provider": "max"}).json()
    token = _login_token_from_deep_link(started["deep_link"])

    user_obj = {
        "user_id": "mx-7", "first_name": "Макс", "last_name": "Юзер",
        "avatar_url": "https://cdn.example/a.png", "full_avatar_url": "https://cdn.example/full.png",
    }
    approved = asyncio.run(main.handle_max_update({
        "update_type": "message_callback",
        "user_locale": "ru-RU",
        "message_callback": {
            "payload": f"approve:login_{token}",
            "user": user_obj,
            "message": {"recipient": {"user_id": "mx-7"}},
        },
    }, send_replies=True))
    assert approved["botLogin"] == "approved"

    # Synchronous identity upsert captures avatar/language/name (no network).
    with main.db() as conn:
        ident = conn.execute(
            "SELECT provider_avatar_url, provider_language_code, provider_first_name FROM auth_identities WHERE provider='max' AND provider_user_id='mx-7'"
        ).fetchone()
        urow = conn.execute("SELECT first_name FROM users WHERE max_id = 'mx-7'").fetchone()
    assert ident["provider_avatar_url"] == "https://cdn.example/full.png"
    assert ident["provider_language_code"] == "ru-RU"
    assert ident["provider_first_name"] == "Макс"
    assert urow["first_name"] == "Макс"

    # New accounts receive an in-app preset immediately; provider caching must
    # not overwrite that default avatar.
    cached = asyncio.run(main.ensure_user_avatar_cached("max", "mx-7"))
    with main.db() as conn:
        urow2 = conn.execute("SELECT avatar_url, avatar_preset FROM users WHERE max_id = 'mx-7'").fetchone()
    assert (urow2["avatar_url"] or "").startswith("/avatars/avatar-")
    assert (urow2["avatar_url"] or "").endswith(".webp")
    assert (urow2["avatar_preset"] or "").startswith("avatar-")
    assert cached == urow2["avatar_url"]


def test_avatar_cache_does_not_overwrite_custom_avatar(temp_db, monkeypatch):
    async def fake_download(url: str):
        return _png_bytes()

    monkeypatch.setattr(main, "_download_avatar_bytes", fake_download)
    now = main.datetime.now(main.timezone.utc).isoformat()
    with main.db() as conn:
        main.max_upsert_identity(conn, {
            "id": "mx-9", "first_name": "Кастом",
            "photo_url": "https://cdn.example/x.png",
        }, now)
        conn.execute("UPDATE users SET avatar_preset = 'avatar_3', avatar_url = '' WHERE max_id = 'mx-9'")

    result = asyncio.run(main.ensure_user_avatar_cached("max", "mx-9"))
    assert not result  # preset chosen -> no-op (no cached avatar produced)
    with main.db() as conn:
        urow = conn.execute("SELECT avatar_url, avatar_preset FROM users WHERE max_id = 'mx-9'").fetchone()
    assert urow["avatar_preset"] == "avatar_3"
    assert (urow["avatar_url"] or "") == ""


# --- Phase 1d: me-v2 fallback + telegram auth helper ----------------------

def _authenticate_telegram(client: TestClient, monkeypatch, user_id: int = 777) -> None:
    async def fake_telegram_api(method, payload=None):
        return {"ok": True, "result": {"method": method}}

    monkeypatch.setattr(main, "telegram_api", fake_telegram_api)
    started = client.post("/api/auth/bot-login/start", json={"provider": "telegram"}).json()
    token = _login_token_from_deep_link(started["deep_link"])
    res = asyncio.run(main.handle_telegram_update({
        "update_id": 1,
        "callback_query": {
            "id": "cb1", "data": f"approve:login_{token}",
            "from": {"id": user_id, "username": "tg_user", "first_name": "Тест"},
            "message": {"chat": {"id": user_id}},
        },
    }, send_replies=True))
    assert res["botLogin"] == "approved"
    assert client.get("/api/auth/bot-login/status").json()["status"] == "authenticated"


def test_me_v2_avatar_falls_back_to_provider(temp_db, monkeypatch):
    client = TestClient(main.app)
    _authenticate_telegram(client, monkeypatch)
    # Telegram bot login has no avatar; inject a provider avatar and clear users.avatar_url.
    with main.db() as conn:
        conn.execute("UPDATE auth_identities SET provider_avatar_url = 'https://cdn.example/tg.png' WHERE provider='telegram'")
        conn.execute("UPDATE users SET avatar_url = NULL, avatar_preset = NULL WHERE telegram_id = '777'")
    me = client.get("/api/me-v2").json()
    assert me["profile"]["avatar_url"] == "https://cdn.example/tg.png"
    assert me["profile"]["first_name"] == "Тест"


# --- Phase 2: sessions list + revoke --------------------------------------

def test_sessions_requires_auth(temp_db):
    client = TestClient(main.app)
    assert client.get("/api/auth/sessions").status_code == 401


def test_sessions_list_shows_current_and_revoke_others(temp_db, monkeypatch):
    client = TestClient(main.app)
    _authenticate_telegram(client, monkeypatch)
    data = client.get("/api/auth/sessions").json()
    assert data["ok"] is True
    assert len(data["sessions"]) >= 1
    current = [s for s in data["sessions"] if s["current"]]
    assert len(current) == 1
    assert current[0]["provider"] == "telegram"
    # revoke-others should not touch the current session
    revoked = client.post("/api/auth/sessions/revoke-others", headers=BROWSER_ORIGIN).json()
    assert revoked["ok"] is True
    assert client.get("/api/me-v2").status_code == 200


def test_revoke_foreign_session_is_rejected(temp_db, monkeypatch):
    client = TestClient(main.app)
    _authenticate_telegram(client, monkeypatch)
    resp = client.post("/api/auth/sessions/non-existent-id/revoke", headers=BROWSER_ORIGIN)
    assert resp.status_code == 404


# --- Phase 3: activity summary --------------------------------------------

def test_activity_v2_reports_logins_and_methods(temp_db, monkeypatch):
    client = TestClient(main.app)
    _authenticate_telegram(client, monkeypatch)
    data = client.get("/api/account/activity-v2").json()
    assert data["ok"] is True
    assert data["total_logins"] >= 1
    assert data["active_sessions"] >= 1
    providers = {m["provider"] for m in data["login_methods"]}
    assert "telegram" in providers
    assert data["account_created_at"]


def test_activity_v2_requires_auth(temp_db):
    client = TestClient(main.app)
    assert client.get("/api/account/activity-v2").status_code == 401
