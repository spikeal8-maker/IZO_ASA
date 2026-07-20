"""Admin v2 (trusted-session) tests (Phase 10).

All tests use a TEMPORARY SQLite DB via monkeypatching main.DB_PATH;
backend/onenode.sqlite3 is never touched.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import main


NOW = "2026-06-25T00:00:00+00:00"


@pytest.fixture
def temp_db(tmp_path: Path, monkeypatch):
    db_file = tmp_path / "admin_v2_test.sqlite3"
    monkeypatch.setattr(main, "DB_PATH", db_file)
    main.init_db()
    return db_file


def make_user(internal_user_id, legacy_user_id, *, role="user", banned=0, username=None):
    with main.db() as conn:
        conn.execute(
            "INSERT INTO users (id, internal_user_id, username, first_name, language, role, created_at, last_login_at, banned, last_seen_at) "
            "VALUES (?, ?, ?, 'X', 'ru', ?, ?, ?, ?, ?)",
            (legacy_user_id, internal_user_id, username, role, NOW, NOW, banned, NOW),
        )


def make_identity(internal_user_id, legacy_user_id, provider="telegram", pid="1", email=None, username=None):
    with main.db() as conn:
        conn.execute(
            "INSERT INTO auth_identities (id, internal_user_id, legacy_user_id, provider, provider_user_id, provider_username, provider_email, linked_at, last_login_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (main.uuid.uuid4().hex, internal_user_id, legacy_user_id, provider, pid, username, email, NOW, NOW),
        )


def session_for(internal_user_id, legacy_user_id, provider="telegram", platform="telegram_mini_app"):
    return main.create_auth_session(internal_user_id, legacy_user_id, provider=provider, platform=platform)


def admin_session():
    make_user("iuid-admin", "telegram_admin", role="admin", username="boss")
    return session_for("iuid-admin", "telegram_admin")


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def set_cookie_headers(resp):
    return resp.headers.get_list("set-cookie") if hasattr(resp.headers, "get_list") else resp.headers.get("set-cookie", "").split(", ")


def find_cookie(resp, name):
    for sc in set_cookie_headers(resp):
        if sc.startswith(name + "="):
            return sc
    return None


def count(table, where="", params=()):
    with main.db() as conn:
        return conn.execute(f"SELECT COUNT(*) AS c FROM {table} {where}", params).fetchone()["c"]


ADMIN_GET = [
    "/api/admin/users-v2",
    "/api/admin/users/iuid-x/v2",
    "/api/admin/security-events-v2",
    "/api/admin/audit-logs-v2",
]


# 1
def test_admin_v2_without_session_401(temp_db):
    with TestClient(main.app) as client:
        for path in ADMIN_GET:
            assert client.get(path).status_code == 401
        assert client.post("/api/admin/users/iuid-x/block-v2", json={"reason": "x"}).status_code == 401


def test_admin_openrouter_status_without_key(temp_db, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    sess = admin_session()
    with TestClient(main.app) as client:
        response = client.get("/api/admin/openrouter/status", cookies={"onenode_session": sess["session_token"]})
    assert response.status_code == 200
    payload = response.json()
    assert payload["key"]["configured"] is False
    assert payload["usage"]["pricedImages"] == 0


def test_admin_can_save_openrouter_key_without_exposing_secret(temp_db, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    async def fake_status():
        return {"configured": True, "source": "dpapi", "ok": True, "data": {"limit": 10, "usage": 1}}

    monkeypatch.setattr(main, "fetch_openrouter_key_status", fake_status)
    sess = admin_session()
    with TestClient(main.app) as client:
        cookies = {"onenode_session": sess["session_token"]}
        saved = client.put("/api/admin/openrouter/key", json={"key": "sk-or-test-secret-123"}, cookies=cookies)
        settings = client.get("/api/admin/settings", cookies=cookies)
        deleted = client.delete("/api/admin/openrouter/key", cookies=cookies)

    assert saved.status_code == 200
    assert saved.json()["key"]["ok"] is True
    assert "sk-or-test-secret-123" not in saved.text
    assert settings.status_code == 200
    assert "sk-or-test-secret-123" not in settings.text
    assert deleted.status_code == 200
    assert main.OPENROUTER_SECRET_STORE.get(main.OPENROUTER_SECRET_NAME) == ""
    with main.db() as conn:
        assert conn.execute("SELECT COUNT(*) AS c FROM admin_secrets").fetchone()["c"] == 0


def test_admin_can_save_openrouter_model_config(temp_db):
    sess = admin_session()
    with TestClient(main.app) as client:
        response = client.post(
            "/api/admin/openrouter/config",
            json={"config": {"enabled": {"text_to_image": ["black-forest-labs/flux.2-klein-4b", "bad"]}, "defaults": {"text_to_image": "black-forest-labs/flux.2-klein-4b"}}},
            cookies={"onenode_session": sess["session_token"]},
        )
    assert response.status_code == 200
    payload = response.json()
    assert payload["config"]["enabled"]["text_to_image"] == ["black-forest-labs/flux.2-klein-4b"]
    assert payload["config"]["defaults"]["text_to_image"] == "black-forest-labs/flux.2-klein-4b"


def test_admin_openrouter_test_generate_records_cost(temp_db, monkeypatch):
    async def fake_send(payload, job):
        image_path, thumb_path = main.mock_image(payload, f"{job['id']}_openrouter")
        return main.OpenRouterResult(
            image_path=image_path,
            thumbnail_path=thumb_path,
            response_id="or_admin_test",
            model=payload.modelProfile,
            usage={"images": 1},
            cost_usd=0.014,
            width=payload.width,
            height=payload.height,
            raw={},
        )

    monkeypatch.setattr(main, "send_to_openrouter", fake_send)
    sess = admin_session()
    with TestClient(main.app) as client:
        response = client.post(
            "/api/admin/openrouter/test-generate",
            json={"model": "black-forest-labs/flux.2-klein-4b", "width": 1024, "height": 1024},
            cookies={"onenode_session": sess["session_token"]},
        )
    assert response.status_code == 200
    payload = response.json()
    assert payload["costUsd"] == 0.014
    assert payload["stats"]["pricedImages"] == 1


def test_admin_can_refresh_openrouter_exchange_rate(temp_db, monkeypatch):
    class FakeResponse:
        content = b'<ValCurs Date="09.07.2026"><Valute><CharCode>USD</CharCode><Nominal>1</Nominal><Value>78,4567</Value></Valute></ValCurs>'

        def raise_for_status(self):
            return None

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url):
            return FakeResponse()

    monkeypatch.setattr(main.httpx, "AsyncClient", FakeClient)
    sess = admin_session()
    with TestClient(main.app) as client:
        response = client.post("/api/admin/openrouter/exchange/refresh", cookies={"onenode_session": sess["session_token"]})
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["exchange"]["rate"] == 78.4567
    assert main._saved_setting("exchange_usd_rub")["rate"] == 78.4567


def test_admin_exchange_rate_uses_fallback_when_cbr_fails(temp_db, monkeypatch):
    class FakeResponse:
        def __init__(self, payload=None, *, content=b"", fail=False):
            self._payload = payload or {}
            self.content = content
            self.fail = fail

        def raise_for_status(self):
            if self.fail:
                raise RuntimeError("cbr unavailable")

        def json(self):
            return self._payload

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url):
            if "cbr.ru" in url:
                return FakeResponse(fail=True)
            return FakeResponse({"rates": {"RUB": 76.537079}, "time_last_update_utc": "Thu, 09 Jul 2026 00:02:32 +0000"})

    monkeypatch.setattr(main.httpx, "AsyncClient", FakeClient)
    sess = admin_session()
    with TestClient(main.app) as client:
        response = client.post("/api/admin/openrouter/exchange/refresh", cookies={"onenode_session": sess["session_token"]})
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["exchange"]["rate"] == 76.537079
    assert payload["exchange"]["fallback"] is True


def test_web_login_requires_explicit_admin_code(temp_db, monkeypatch):
    monkeypatch.delenv("ADMIN_ONE_TIME_CODE", raising=False)
    with TestClient(main.app) as client:
        r = client.post("/api/auth/web-login", json={"code": "admin-demo"})
    assert r.status_code == 503
    assert find_cookie(r, "onenode_session") is None
    assert find_cookie(r, "onenode_refresh") is None


def test_web_login_issues_trusted_admin_session(temp_db, monkeypatch):
    monkeypatch.setenv("ADMIN_ONE_TIME_CODE", "one-time-admin-code")
    monkeypatch.setattr(main, "TRUSTED_COOKIE_SECURE", False)
    with TestClient(main.app) as client:
        r = client.post("/api/auth/web-login", json={"code": "one-time-admin-code"})
        assert r.status_code == 200
        assert find_cookie(r, "onenode_session")
        assert find_cookie(r, "onenode_refresh")
        assert "httponly" in find_cookie(r, "onenode_session").lower()
        assert not client.cookies.get("onenode_user")
        admin = client.get("/api/admin/users-v2")
    assert admin.status_code == 200


# 2
def test_admin_v2_non_admin_403(temp_db):
    make_user("iuid-u", "telegram_u", role="user")
    s = session_for("iuid-u", "telegram_u")
    with TestClient(main.app) as client:
        for path in ADMIN_GET:
            assert client.get(path, headers=bearer(s["session_token"])).status_code == 403


# 3
def test_x_onenode_user_spoof_does_not_grant_admin(temp_db):
    make_user("iuid-u", "telegram_u", role="user")
    make_user("iuid-admin", "telegram_admin", role="admin")
    s = session_for("iuid-u", "telegram_u")
    with TestClient(main.app) as client:
        r = client.get("/api/admin/users-v2", headers={**bearer(s["session_token"]), "X-OneNode-User": "telegram_admin"})
    assert r.status_code == 403


# 4
def test_cookie_spoof_does_not_grant_admin(temp_db):
    make_user("iuid-u", "telegram_u", role="user")
    make_user("iuid-admin", "telegram_admin", role="admin")
    s = session_for("iuid-u", "telegram_u")
    with TestClient(main.app) as client:
        client.cookies.set("onenode_user", "telegram_admin")
        r = client.get("/api/admin/users-v2", headers=bearer(s["session_token"]))
    assert r.status_code == 403


# 5, 6, 7, 8
def test_admin_can_list_users_no_secrets(temp_db):
    s = admin_session()
    make_user("iuid-1", "telegram_1", username="ann")
    make_identity("iuid-1", "telegram_1", provider="telegram", pid="1", email="a@x.com", username="ann")
    session_for("iuid-1", "telegram_1")
    # create an OTP challenge to ensure code_hash never leaks into admin views
    with main.db() as conn:
        conn.execute(
            "INSERT INTO auth_otp_challenges (id, channel, destination, code_hash, purpose, attempts_count, max_attempts, expires_at, created_at) "
            "VALUES ('c1','email','a@x.com','SECRET_CODE_HASH','login',0,5, ?, ?)",
            (NOW, NOW),
        )
    with TestClient(main.app) as client:
        r = client.get("/api/admin/users-v2", headers=bearer(s["session_token"]))
    assert r.status_code == 200
    body = r.json()
    assert body["total"] >= 2  # admin + iuid-1 (+ demo_user)
    text = r.text
    assert "session_token_hash" not in text
    assert "refresh_token_hash" not in text
    assert "SECRET_CODE_HASH" not in text
    target = next(i for i in body["items"] if i["internal_user_id"] == "iuid-1")
    assert "telegram" in target["providers"]
    assert target["active_sessions_count"] == 1


def test_users_list_filters(temp_db):
    s = admin_session()
    make_user("iuid-1", "telegram_1", username="findme")
    make_identity("iuid-1", "telegram_1", provider="telegram", pid="1", username="findme")
    make_user("iuid-2", "max_2")
    make_identity("iuid-2", "max_2", provider="max", pid="2")
    with TestClient(main.app) as client:
        prov = client.get("/api/admin/users-v2?provider=max", headers=bearer(s["session_token"])).json()
        q = client.get("/api/admin/users-v2?q=findme", headers=bearer(s["session_token"])).json()
    assert [i["internal_user_id"] for i in prov["items"]] == ["iuid-2"]
    assert any(i["internal_user_id"] == "iuid-1" for i in q["items"])


# 9, 10, 11
def test_admin_user_detail(temp_db):
    s = admin_session()
    make_user("iuid-1", "telegram_1", username="ann")
    make_identity("iuid-1", "telegram_1", provider="web_email", pid="ann@example.com", email="ann@example.com")
    sess = session_for("iuid-1", "telegram_1")
    with TestClient(main.app) as client:
        r = client.get("/api/admin/users/iuid-1/v2", headers=bearer(s["session_token"]))
    assert r.status_code == 200
    body = r.json()
    assert body["user"]["internal_user_id"] == "iuid-1"
    assert len(body["identities"]) == 1
    assert len(body["sessions"]) == 1
    # email masked, not full
    assert body["identities"][0]["provider_email"] != "ann@example.com"
    assert "@example.com" in body["identities"][0]["provider_email"]
    text = r.text
    assert "session_token_hash" not in text and "refresh_token_hash" not in text
    assert sess["session_token"] not in text


def test_admin_user_detail_404(temp_db):
    s = admin_session()
    with TestClient(main.app) as client:
        r = client.get("/api/admin/users/nope/v2", headers=bearer(s["session_token"]))
    assert r.status_code == 404


# 12
def test_security_events_requires_admin(temp_db):
    make_user("iuid-u", "telegram_u", role="user")
    s = session_for("iuid-u", "telegram_u")
    with TestClient(main.app) as client:
        assert client.get("/api/admin/security-events-v2", headers=bearer(s["session_token"])).status_code == 403


# 13
def test_audit_logs_requires_admin(temp_db):
    make_user("iuid-u", "telegram_u", role="user")
    s = session_for("iuid-u", "telegram_u")
    with TestClient(main.app) as client:
        assert client.get("/api/admin/audit-logs-v2", headers=bearer(s["session_token"])).status_code == 403


# 14
def test_block_requires_reason(temp_db):
    s = admin_session()
    make_user("iuid-1", "telegram_1")
    with TestClient(main.app) as client:
        r = client.post("/api/admin/users/iuid-1/block-v2", json={"reason": "   "}, headers=bearer(s["session_token"]))
    assert r.status_code == 400


# 15
def test_block_forbids_self_block(temp_db):
    s = admin_session()
    with TestClient(main.app) as client:
        r = client.post("/api/admin/users/iuid-admin/block-v2", json={"reason": "x"}, headers=bearer(s["session_token"]))
    assert r.status_code == 403


# 16, 17, 18, 19
def test_block_sets_banned_revokes_sessions_and_logs(temp_db):
    s = admin_session()
    make_user("iuid-1", "telegram_1")
    target_sess = session_for("iuid-1", "telegram_1")
    with TestClient(main.app) as client:
        r = client.post("/api/admin/users/iuid-1/block-v2", json={"reason": "abuse"}, headers=bearer(s["session_token"]))
    assert r.status_code == 200
    with main.db() as conn:
        banned = conn.execute("SELECT banned FROM users WHERE internal_user_id='iuid-1'").fetchone()["banned"]
        active = conn.execute("SELECT COUNT(*) AS c FROM auth_sessions WHERE internal_user_id='iuid-1' AND revoked_at IS NULL").fetchone()["c"]
    assert banned == 1                                                            # 16
    assert active == 0                                                           # 17
    assert count("audit_logs", "WHERE action='admin_block_user' AND target_internal_user_id='iuid-1'") == 1  # 18
    assert count("security_events", "WHERE event_type='admin_user_blocked'") == 1  # 19


# 20
def test_blocked_user_cannot_refresh(temp_db):
    s = admin_session()
    make_user("iuid-1", "telegram_1")
    target = session_for("iuid-1", "telegram_1")
    with TestClient(main.app) as client:
        client.post("/api/admin/users/iuid-1/block-v2", json={"reason": "abuse"}, headers=bearer(s["session_token"]))
        # the target session is revoked AND the user is banned
        r = client.post("/api/auth/session/refresh-v2", json={"refresh_token": target["refresh_token"]})
    assert r.status_code in (401, 403)


# 21, 22, 23, 24
def test_unblock_flow(temp_db):
    s = admin_session()
    make_user("iuid-1", "telegram_1", banned=1)
    # a previously revoked session
    revoked = session_for("iuid-1", "telegram_1")
    main.revoke_auth_session(revoked["session_id"], reason="admin_block")
    with TestClient(main.app) as client:
        # 21: reason required
        assert client.post("/api/admin/users/iuid-1/unblock-v2", json={"reason": ""}, headers=bearer(s["session_token"])).status_code == 400
        r = client.post("/api/admin/users/iuid-1/unblock-v2", json={"reason": "appeal granted"}, headers=bearer(s["session_token"]))
    assert r.status_code == 200
    with main.db() as conn:
        banned = conn.execute("SELECT banned FROM users WHERE internal_user_id='iuid-1'").fetchone()["banned"]
        still_revoked = conn.execute("SELECT revoked_at FROM auth_sessions WHERE id=?", (revoked["session_id"],)).fetchone()["revoked_at"]
    assert banned == 0                                                            # 22
    assert count("audit_logs", "WHERE action='admin_unblock_user'") == 1         # 23
    assert still_revoked is not None                                             # 24: sessions NOT restored


# Audit hardening (Phase 10.1): q filter must be injection-safe (parameterized).
def test_users_list_q_filter_is_injection_safe(temp_db):
    s = admin_session()
    make_user("iuid-1", "telegram_1", username="ann")
    make_identity("iuid-1", "telegram_1", provider="telegram", pid="1", username="ann")
    malicious = "'; DROP TABLE users; --"
    with TestClient(main.app) as client:
        r = client.get("/api/admin/users-v2", params={"q": malicious}, headers=bearer(s["session_token"]))
    assert r.status_code == 200          # no SQL error
    assert r.json()["items"] == []        # no rows match the literal string
    # users table still intact (injection did not execute)
    with main.db() as conn:
        assert conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"] >= 2


# Audit hardening: limit is clamped to <= 200.
def test_users_list_limit_clamped(temp_db):
    s = admin_session()
    with TestClient(main.app) as client:
        r = client.get("/api/admin/users-v2", params={"limit": 99999}, headers=bearer(s["session_token"]))
    assert r.json()["limit"] == 200


def patch_config_ui_dependencies(monkeypatch, *, comfy_up=True, interrupted=None):
    async def fake_comfyui_available():
        return comfy_up

    async def fake_flux_klein_config():
        return {
            "autofill_prompts": {"portrait": "x"},
            "lora_triggers_custom": {"head": "x"},
            "t2i_templates": [{"id": "base"}],
            "discover_prompts": {"home": ["x", "y"]},
        }

    async def fake_comfyui_models():
        return {
            "diffusion_models": ["flux.safetensors"],
            "text_encoders": ["t5xxl.safetensors"],
            "vaes": ["ae.safetensors"],
            "loras": ["refcontrol_v2_poses.safetensors"],
        }

    async def fake_comfyui_node_names():
        return {"FluxKleinOneNode", "DWPreprocessor", "SaveImage"}

    async def fake_interrupt_comfyui_prompt():
        if interrupted is not None:
            interrupted["called"] = True
        return None

    async def fake_free_comfyui_models():
        return True

    monkeypatch.setattr(main, "comfyui_available", fake_comfyui_available)
    monkeypatch.setattr(main, "get_flux_klein_config", fake_flux_klein_config)
    monkeypatch.setattr(main, "get_comfyui_models", fake_comfyui_models)
    monkeypatch.setattr(main, "comfyui_node_names", fake_comfyui_node_names)
    monkeypatch.setattr(main, "interrupt_comfyui_prompt", fake_interrupt_comfyui_prompt)
    monkeypatch.setattr(main, "free_comfyui_models", fake_free_comfyui_models)


def test_config_ui_status_requires_admin(temp_db):
    with TestClient(main.app) as client:
        assert client.get("/api/admin/config-ui/status-v2").status_code == 401

    make_user("iuid-u", "telegram_u", role="user")
    s = session_for("iuid-u", "telegram_u")
    with TestClient(main.app) as client:
        assert client.get("/api/admin/config-ui/status-v2", headers=bearer(s["session_token"])).status_code == 403


def test_config_ui_status_reports_config_models_nodes_and_jobs(temp_db, monkeypatch):
    patch_config_ui_dependencies(monkeypatch)
    old_jobs = dict(main.jobs)
    main.jobs.clear()
    main.jobs["job-1"] = {
        "id": "job-1",
        "status": "running",
        "mode": "txt2img",
        "provider": "local",
        "progress": 42,
        "message": "long config operation",
    }
    try:
        s = admin_session()
        with TestClient(main.app) as client:
            main.jobs["job-1"] = {
                "id": "job-1",
                "status": "running",
                "mode": "txt2img",
                "provider": "local",
                "progress": 42,
                "message": "long config operation",
            }
            r = client.get("/api/admin/config-ui/status-v2", headers=bearer(s["session_token"]))
    finally:
        main.jobs.clear()
        main.jobs.update(old_jobs)

    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ready"
    assert body["comfyui"]["available"] is True
    assert body["config_api"]["sections"]["autofill_prompts"] == 1
    assert body["models_api"]["counts"]["loras"] == 1
    assert body["nodes"]["required"]["Flux Klein API"] is True
    assert body["active_jobs"][0]["id"] == "job-1"


def test_config_ui_reload_requires_reason_clears_cache_and_logs(temp_db, monkeypatch):
    patch_config_ui_dependencies(monkeypatch)
    main._admin_models_page_cache["ts"] = 123.0
    main._admin_models_page_cache["data"] = {"cached": True}
    s = admin_session()
    with TestClient(main.app) as client:
        empty = client.post("/api/admin/config-ui/reload-v2", json={"reason": "  "}, headers=bearer(s["session_token"]))
        r = client.post("/api/admin/config-ui/reload-v2", json={"reason": "config api завис"}, headers=bearer(s["session_token"]))

    assert empty.status_code == 400
    assert r.status_code == 200
    assert r.json()["reloaded"] is True
    assert main._admin_models_page_cache["data"] is None
    assert count("audit_logs", "WHERE action='admin_config_ui_reload'") == 1


def test_config_ui_interrupt_requires_reason_calls_comfy_and_logs(temp_db, monkeypatch):
    interrupted = {"called": False}
    patch_config_ui_dependencies(monkeypatch, interrupted=interrupted)
    old_jobs = dict(main.jobs)
    main.jobs.clear()
    main.jobs["job-2"] = {"id": "job-2", "status": "sent_to_comfyui"}
    try:
        s = admin_session()
        with TestClient(main.app) as client:
            empty = client.post("/api/admin/config-ui/interrupt-v2", json={"reason": ""}, headers=bearer(s["session_token"]))
            main.jobs["job-2"] = {"id": "job-2", "status": "sent_to_comfyui"}
            r = client.post("/api/admin/config-ui/interrupt-v2", json={"reason": "ручной interrupt"}, headers=bearer(s["session_token"]))
    finally:
        main.jobs.clear()
        main.jobs.update(old_jobs)

    assert empty.status_code == 400
    assert r.status_code == 200
    assert r.json()["active_jobs_before"] == ["job-2"]
    assert interrupted["called"] is True
    assert count("audit_logs", "WHERE action='admin_config_ui_interrupt'") == 1


def test_config_ui_switch_updates_global_profile_and_routes(temp_db, monkeypatch):
    patch_config_ui_dependencies(monkeypatch)
    main._save_setting("generation_routes", {"routes": [{"routeId": "text_to_image", "provider": "local", "modelProfileId": "flux_klein_9b"}]})
    s = admin_session()
    with TestClient(main.app) as client:
        response = client.post("/api/admin/config-ui/switch-v2", json={"profileId": "flux_klein_4b", "reason": "снижаю нагрузку"}, headers=bearer(s["session_token"]))

    assert response.status_code == 200
    assert response.json()["profileId"] == "flux_klein_4b"
    assert main.get_model_settings()["editModelProfile"] == "flux_klein_4b"
    assert main._saved_setting("generation_routes")["routes"][0]["modelProfileId"] == "flux_klein_4b"
    assert count("audit_logs", "WHERE action='admin_config_ui_switch'") == 1


# 25, 26
def test_old_admin_and_require_admin_unchanged():
    import inspect
    ra = inspect.getsource(main.require_admin)
    assert "auth_sessions" not in ra  # legacy, untouched
    routes = {r.path for r in main.app.routes}
    # legacy admin endpoints still present
    assert "/api/admin/summary" in routes
    assert "/api/admin/users" in routes
