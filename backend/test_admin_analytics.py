"""Admin/auth analytics tests (Phase 18). Temp SQLite via monkeypatch; no live DB."""
from __future__ import annotations

import re
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import main

PW = "S3cret-Password!"


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "analytics_test.sqlite3"
    monkeypatch.setattr(main, "DB_PATH", db_file)
    monkeypatch.setattr(main, "TRUSTED_COOKIE_SECURE", False)
    main.init_db()
    return db_file


def count(table, where="", params=()):
    with main.db() as conn:
        return conn.execute(f"SELECT COUNT(*) AS c FROM {table} {where}", params).fetchone()["c"]


def make_admin():
    iuid = "iuid-admin"
    with main.db() as conn:
        conn.execute("INSERT INTO users (id, internal_user_id, role, language, created_at, last_login_at) "
                     "VALUES ('telegram_admin', ?, 'admin', 'ru', '2026-01-01', '2026-01-01')", (iuid,))
    s = main.create_auth_session(iuid, "telegram_admin", provider="telegram", platform="telegram_mini_app")
    return s["session_token"]


def bearer(t):
    return {"Authorization": f"Bearer {t}"}


def register(c, email):
    return c.post("/api/auth/password/register-v2", json={"email": email, "password": PW, "password_repeat": PW,
                  "accepted_terms": True, "accepted_privacy": True, "accepted_personal_data": True, "platform": "web_desktop"})


# 1, 2, 3
def test_public_code_assigned_stable_unique_prefixed(temp_db):
    with TestClient(main.app) as c:
        register(c, "a@example.com")
        register(c, "b@example.com")
    with main.db() as conn:
        codes = [r["public_user_code"] for r in conn.execute("SELECT public_user_code FROM users WHERE public_user_code IS NOT NULL")]
    assert all(c and re.match(r"^(WEB|TG|MAX|USR)-\d{6}$", c) for c in codes)
    assert len(codes) == len(set(codes))  # unique
    web = [c for c in codes if c.startswith("WEB-")]
    assert len(web) >= 2  # web/email users get WEB prefix
    # stable across re-init
    main.init_db()
    with main.db() as conn:
        codes2 = sorted(r["public_user_code"] for r in conn.execute("SELECT public_user_code FROM users WHERE public_user_code IS NOT NULL"))
    assert sorted(codes) == codes2


# 4
def test_display_name_priority(temp_db):
    class Row(dict):
        def __getitem__(self, k):
            return super().get(k)
        def keys(self):
            return super().keys()
    u = Row(display_name="Custom Name", first_name="F", last_name="L", username="nick", email="x@y.com", public_user_code="WEB-000001")
    assert main.resolve_display_name(u) == "Custom Name"
    assert main.resolve_display_name(Row(first_name="Иван", last_name="Петров")) == "Иван Петров"
    assert main.resolve_display_name(Row(username="cooluser")) == "cooluser"
    assert main.resolve_display_name(Row(email="local.part@mail.com")) == "local.part"
    assert main.resolve_display_name(Row(public_user_code="TG-000009")) == "TG-000009"
    assert main.resolve_display_name(Row()) == "Пользователь"


# 5
def test_password_login_updates_session_platform_lastseen(temp_db):
    with TestClient(main.app) as c:
        register(c, "act@example.com")
    with main.db() as conn:
        u = conn.execute("SELECT internal_user_id, last_seen_at FROM users WHERE email='act@example.com' OR id IN (SELECT legacy_user_id FROM auth_identities WHERE provider_user_id='act@example.com')").fetchone()
        iuid = conn.execute("SELECT internal_user_id FROM auth_identities WHERE provider_user_id='act@example.com'").fetchone()["internal_user_id"]
        sess = conn.execute("SELECT provider, platform FROM auth_sessions WHERE internal_user_id=? ORDER BY created_at DESC LIMIT 1", (iuid,)).fetchone()
        last_seen = conn.execute("SELECT last_seen_at FROM users WHERE internal_user_id=?", (iuid,)).fetchone()["last_seen_at"]
    assert sess["provider"] == "web_email" and sess["platform"] == "web"
    assert last_seen is not None


# 8, 9
def test_get_client_ip_trust(temp_db, monkeypatch):
    class Req:
        def __init__(self, headers, host="1.2.3.4"):
            self.headers = headers
            self.client = type("C", (), {"host": host})()
    # default: ignore forwarded headers
    monkeypatch.setattr(main, "TRUST_PROXY_HEADERS", False)
    monkeypatch.setattr(main, "TRUST_CLOUDFLARE_HEADERS", False)
    assert main.get_client_ip(Req({"x-forwarded-for": "9.9.9.9", "cf-connecting-ip": "8.8.8.8"})) == "1.2.3.4"
    # cloudflare trust on
    monkeypatch.setattr(main, "TRUST_CLOUDFLARE_HEADERS", True)
    assert main.get_client_ip(Req({"cf-connecting-ip": "8.8.8.8"}, host="127.0.0.1")) == "8.8.8.8"
    assert main.get_client_ip(Req({"cf-connecting-ip": "8.8.8.8"}, host="1.2.3.4")) == "1.2.3.4"
    # proxy trust on -> first XFF
    monkeypatch.setattr(main, "TRUST_CLOUDFLARE_HEADERS", False)
    monkeypatch.setattr(main, "TRUST_PROXY_HEADERS", True)
    assert main.get_client_ip(Req({"x-forwarded-for": "9.9.9.9, 10.0.0.1"}, host="127.0.0.1")) == "9.9.9.9"


# 10, 11
def test_dashboard_requires_admin(temp_db):
    with TestClient(main.app) as c:
        assert c.get("/api/admin/dashboard-v2").status_code == 401
    # non-admin
    with TestClient(main.app) as c:
        register(c, "nonadmin@example.com")
        r = c.get("/api/admin/dashboard-v2")
    assert r.status_code == 403


# 12
def test_dashboard_counts(temp_db):
    tok = make_admin()
    with TestClient(main.app) as c:
        register(c, "u1@example.com")
        register(c, "u2@example.com")
        r = c.get("/api/admin/dashboard-v2", headers=bearer(tok))
    d = r.json()["dashboard"]
    assert d["total_users"] >= 3
    assert d["new_today"] >= 2
    assert d["logins_today"] >= 2  # two register-succeeded logins
    assert "web_email" in d["users_by_provider"]
    assert d["sessions_active"] >= 1


# 13, 14
def test_users_analytics_no_hashes_and_clean_ids(temp_db):
    tok = make_admin()
    with TestClient(main.app) as c:
        register(c, "clean@example.com")
        r = c.get("/api/admin/users-analytics-v2", headers=bearer(tok))
    text = r.text
    for forbidden in ("session_token_hash", "refresh_token_hash", "code_hash", "password_hash"):
        assert forbidden not in text
    item = next(i for i in r.json()["items"] if i["public_user_code"] and i["public_user_code"].startswith("WEB-"))
    assert "public_user_code" in item and "display_name" in item and "primary_provider" in item
    # full internal_user_id is provided for the drawer fetch (not a primary display field);
    # a short form is also present for the collapsed technical view
    assert "internal_user_id" in item and item["internal_user_id"]
    assert item["internal_user_id_short"].endswith("…")


def test_trusted_crm_full_contacts_search_sort_and_groups(temp_db):
    tok = make_admin()
    with TestClient(main.app) as c:
        register(c, "support.lookup@example.com")
        with main.db() as conn:
            identity = conn.execute(
                "SELECT internal_user_id FROM auth_identities WHERE provider_user_id='support.lookup@example.com'"
            ).fetchone()
            conn.execute(
                "UPDATE auth_identities SET provider_username='support_nick', provider_phone='+79991234567' "
                "WHERE internal_user_id=?",
                (identity["internal_user_id"],),
            )
        by_phone = c.get(
            "/api/admin/users-analytics-v2?q=9991234567&sort=contact_desc",
            headers=bearer(tok),
        )
        admins = c.get("/api/admin/users-analytics-v2?group=admin&sort=name_asc", headers=bearer(tok))
        detail = c.get(f"/api/admin/users/{identity['internal_user_id']}/analytics-v2", headers=bearer(tok))

    assert by_phone.status_code == 200
    item = by_phone.json()["items"][0]
    assert item["email"] == "support.lookup@example.com"
    assert item["username"] == "support_nick"
    assert item["phone"] == "+79991234567"
    assert item["account_group"] == "customer"
    assert admins.status_code == 200
    assert all(row["account_group"] == "admin" for row in admins.json()["items"])
    assert detail.json()["identities"][0]["provider_email"] == "support.lookup@example.com"
    assert detail.json()["identities"][0]["phone"] == "+79991234567"


# 15
def test_user_detail_analytics_safe(temp_db):
    tok = make_admin()
    with TestClient(main.app) as c:
        register(c, "detail@example.com")
        iuid = None
        with main.db() as conn:
            iuid = conn.execute("SELECT internal_user_id FROM auth_identities WHERE provider_user_id='detail@example.com'").fetchone()["internal_user_id"]
        r = c.get(f"/api/admin/users/{iuid}/analytics-v2", headers=bearer(tok))
    assert r.status_code == 200
    b = r.json()
    assert "summary" in b and "identities" in b and "sessions" in b and "devices" in b
    text = r.text
    for forbidden in ("session_token_hash", "refresh_token_hash", "password_hash", "code_hash", "raw_profile_json"):
        assert forbidden not in text


def test_user_detail_analytics_p0_real_data_and_no_secret_leaks(temp_db):
    tok = make_admin()
    long_prompt = "cinematic neon city " * 30
    with TestClient(main.app) as c:
        register(c, "p0@example.com")
        with main.db() as conn:
            u = conn.execute("SELECT id, internal_user_id FROM auth_identities WHERE provider_user_id='p0@example.com'").fetchone()
            user_id, iuid = u["id"], u["internal_user_id"]
            user_id = conn.execute("SELECT legacy_user_id FROM auth_identities WHERE internal_user_id=?", (iuid,)).fetchone()["legacy_user_id"]
            conn.execute(
                "INSERT INTO jobs (id,user_id,mode,provider,status,progress,prompt_original,prompt_translated,result_image_id,error_message,settings_json,created_at,completed_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                ("job_secret_1234567890", user_id, "text_to_image", "comfyui", "completed", 100, long_prompt, "", "img_safe_1234567890", "C:\\secret\\traceback.txt", json.dumps({"modelProfile": "flux"}, ensure_ascii=False), "2026-06-27T10:00:00+00:00", "2026-06-27T10:01:00+00:00"),
            )
            conn.execute(
                "INSERT INTO images (id,user_id,job_id,url,thumbnail_url,width,height,mode,provider,prompt_original,prompt_translated,settings_json,is_favorite,created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                ("img_safe_1234567890", user_id, "job_secret_1234567890", "/api/media/img.png?userId=x", "/api/media/thumb.webp?userId=x", 1024, 1024, "text_to_image", "comfyui", long_prompt, "", "{}", 1, "2026-06-27T10:01:00+00:00"),
            )
            conn.execute(
                "INSERT INTO images (id,user_id,job_id,url,thumbnail_url,width,height,mode,provider,prompt_original,prompt_translated,settings_json,is_favorite,created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                ("img_bad", user_id, "job_bad", "C:/media/img.png", "C:/media/thumb.webp", 1024, 1024, "text_to_image", "comfyui", "bad", "", "{}", 0, "2026-06-27T09:00:00+00:00"),
            )
            conn.execute(
                "INSERT INTO token_ledger (id,user_id,delta,reason,meta_json,created_at) VALUES (?,?,?,?,?,?)",
                ("ledger_1234567890", user_id, -12, "generation", json.dumps({"jobId": "job_secret_1234567890", "mode": "text_to_image", "provider": "comfyui", "password_hash": "NOPE"}, ensure_ascii=False), "2026-06-27T10:00:00+00:00"),
            )
            conn.execute(
                "INSERT INTO auth_sessions (id,internal_user_id,legacy_user_id,session_token_hash,refresh_token_hash,provider,platform,ip_address,user_agent_hash,created_at,last_seen_at,expires_at,revoked_at,revoke_reason,metadata_json) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                ("sess1", iuid, user_id, "secret_session_hash", "secret_refresh_hash", "web_email", "web", "1.2.3.4", "ua_hash", "2026-06-27", "2026-06-27", "2099-01-01", "2026-06-27", "logout", json.dumps({"device": {"browser": "Chrome", "os": "Windows", "device_type": "desktop"}, "client": {"app_version": "20D.1"}}, ensure_ascii=False)),
            )
            conn.execute(
                "INSERT INTO device_installations (id,internal_user_id,legacy_user_id,installation_id,anonymous_id,platform,storage_type,first_seen_at,last_seen_at,metadata_json) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                ("dev1", iuid, user_id, "installation-secret-long", "anonymous-secret-long", "web", "local", "2026-06-01", "2026-06-27", json.dumps({"device": {"browser": "Chrome", "os": "Windows", "device_type": "desktop"}, "client": {"app_version": "20D.1"}}, ensure_ascii=False)),
            )
            conn.execute("INSERT INTO auth_login_attempts (id,internal_user_id,provider,identifier,success,failure_reason,ip_address,user_agent_hash,platform,created_at) VALUES ('la1',?,'web_email','p0@example.com',0,'bad','1.2.3.4','ua','web','2026-06-27')", (iuid,))
            conn.execute("INSERT INTO security_events (id,internal_user_id,session_id,severity,event_type,ip_address,user_agent_hash,details_json,created_at) VALUES ('sec1',?,NULL,'warning','admin_password_reset','1.2.3.4','ua','{}','2026-06-27')", (iuid,))
            conn.execute("INSERT INTO audit_logs (id,actor_internal_user_id,target_internal_user_id,action,entity_type,entity_id,before_json,after_json,ip_address,user_agent_hash,created_at) VALUES ('aud1','admin',?,'admin_change_role','user',?,NULL,?,'1.2.3.4','ua','2026-06-27')", (iuid, user_id, json.dumps({"reason": "test role"}, ensure_ascii=False)))
            conn.execute("INSERT INTO audit_logs (id,actor_internal_user_id,target_internal_user_id,action,entity_type,entity_id,before_json,after_json,ip_address,user_agent_hash,created_at) VALUES ('aud2','admin',?,'admin_block_user','user',?,NULL,?,'1.2.3.4','ua','2026-06-27')", (iuid, user_id, json.dumps({"reason": "test ban"}, ensure_ascii=False)))
        r = c.get(f"/api/admin/users/{iuid}/analytics-v2", headers=bearer(tok))
    assert r.status_code == 200
    b = r.json()
    assert b["recent_generations"][0]["id"].endswith("…")
    assert b["recent_generations"][0]["token_cost"] == 12
    assert len(b["recent_generations"][0]["prompt"]) < len(long_prompt)
    assert b["recent_generations"][0]["error"] == "Ошибка генерации. Детали скрыты."
    assert b["recent_gallery"][0]["thumbnail_url"].startswith("/api/media/")
    assert all(not g["thumbnail_url"].startswith("C:") for g in b["recent_gallery"])
    assert b["token_ledger_recent"][0]["delta"] == -12
    assert b["token_ledger_recent"][0]["job_id"].endswith("…")
    assert any(s["device"]["browser"] == "Chrome" for s in b["sessions"])
    assert all(s["device"]["mac_status"] == "MAC: недоступен" for s in b["sessions"])
    assert b["devices"][0]["installation_id"].endswith("…")
    assert b["security_summary"]["failed_login_count"] == 1
    assert b["security_summary"]["password_reset_count"] == 1
    assert b["security_summary"]["ban_count"] == 1
    assert b["security_summary"]["role_change_count"] == 1
    assert b["security_summary"]["session_revocation_count"] == 1
    text = r.text
    for forbidden in ("session_token_hash", "refresh_token_hash", "password_hash", "raw_profile_json", "secret_session_hash", "secret_refresh_hash", "initData", "WebAppData"):
        assert forbidden not in text


# 6, 7: provider profile fields captured (telegram/max upsert already store them)
def test_provider_profile_fields_captured(temp_db):
    now = "2026-06-26T00:00:00+00:00"
    with main.db() as conn:
        main.telegram_upsert_identity(conn, {"id": 555, "first_name": "Ольга", "last_name": "И", "username": "olga", "language_code": "ru", "photo_url": "http://x/p.jpg"}, now)
        main.max_upsert_identity(conn, {"id": 777, "first_name": "Max", "username": "maxuser", "language_code": "en"}, now)
        tg = conn.execute("SELECT * FROM auth_identities WHERE provider='telegram' AND provider_user_id='555'").fetchone()
        mx = conn.execute("SELECT * FROM auth_identities WHERE provider='max' AND provider_user_id='777'").fetchone()
    assert tg["provider_username"] == "olga" and tg["provider_first_name"] == "Ольга" and tg["provider_avatar_url"] == "http://x/p.jpg"
    assert mx["provider_username"] == "maxuser" and mx["provider_language_code"] == "en"


# 16-ish: users.id never changed
def test_users_id_unchanged(temp_db):
    with main.db() as conn:
        conn.execute("INSERT INTO users (id, internal_user_id, language, role, created_at, last_login_at) VALUES ('telegram_keep','iuid-keep','ru','user','2026-01-01','2026-01-01')")
    main.init_db()
    with main.db() as conn:
        assert conn.execute("SELECT COUNT(*) AS c FROM users WHERE id='telegram_keep'").fetchone()["c"] == 1
