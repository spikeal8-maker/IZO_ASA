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

    monkeypatch.setattr(main, "comfyui_available", fake_comfyui_available)
    monkeypatch.setattr(main, "get_flux_klein_config", fake_flux_klein_config)
    monkeypatch.setattr(main, "get_comfyui_models", fake_comfyui_models)
    monkeypatch.setattr(main, "comfyui_node_names", fake_comfyui_node_names)
    monkeypatch.setattr(main, "interrupt_comfyui_prompt", fake_interrupt_comfyui_prompt)


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
    assert body["nodes"]["required"]["FluxKleinOneNode"] is True
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


# 25, 26
def test_old_admin_and_require_admin_unchanged():
    import inspect
    ra = inspect.getsource(main.require_admin)
    assert "auth_sessions" not in ra  # legacy, untouched
    routes = {r.path for r in main.app.routes}
    # legacy admin endpoints still present
    assert "/api/admin/summary" in routes
    assert "/api/admin/users" in routes
