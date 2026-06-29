"""Phase 20E.2B product consistency tests. Temp SQLite; no live DB."""
from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

import main
from test_api import fake_send_to_comfyui, wait_for_terminal_job

PW = "S3cret-Password!"


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "product_consistency_test.sqlite3"
    monkeypatch.setattr(main, "DB_PATH", db_file)
    monkeypatch.setattr(main, "TRUSTED_COOKIE_SECURE", False)
    main.init_db()
    main.jobs.clear()
    main.images.clear()
    main.queue = asyncio.Queue()
    main.worker_started = False
    return db_file


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def make_user(iuid: str, legacy: str, role: str = "user", plan: str = "mini", gallery_enabled: int = 1, balance: int = 50) -> None:
    with main.db() as conn:
        conn.execute(
            "INSERT INTO users (id, internal_user_id, role, plan, gallery_enabled, token_balance, language, created_at, last_login_at) "
            "VALUES (?, ?, ?, ?, ?, ?, 'ru', '2026-01-01', '2026-01-01')",
            (legacy, iuid, role, plan, gallery_enabled, balance),
        )


def admin_token() -> str:
    make_user("iuid-admin", "telegram_admin", role="admin", plan="mini")
    return main.create_auth_session("iuid-admin", "telegram_admin", provider="telegram", platform="telegram_mini_app")["session_token"]


def test_password_registration_defaults_to_mini_and_gallery_enabled(temp_db):
    with TestClient(main.app) as c:
        r = c.post("/api/auth/password/register-v2", json={
            "email": "mini-default@example.com",
            "password": PW,
            "password_repeat": PW,
            "accepted_terms": True,
            "accepted_privacy": True,
            "accepted_personal_data": True,
            "platform": "web_desktop",
        })
    assert r.status_code == 200, r.text
    with main.db() as conn:
        row = conn.execute("SELECT plan, gallery_enabled FROM users WHERE email='mini-default@example.com'").fetchone()
    assert row["plan"] == "mini"
    assert row["gallery_enabled"] == 1


def test_plan_v2_updates_canonical_field_and_analytics_reads_it(temp_db):
    token = admin_token()
    make_user("iuid-target", "telegram_target", plan="mini")
    with TestClient(main.app) as c:
        r = c.post("/api/admin/users/iuid-target/plan-v2", json={"plan": "pro", "reason": "upgrade"}, headers=bearer(token))
        table = c.get("/api/admin/users-analytics-v2", headers=bearer(token))
        card = c.get("/api/admin/users/iuid-target/analytics-v2", headers=bearer(token))
    assert r.status_code == 200
    item = next(i for i in table.json()["items"] if i["internal_user_id"] == "iuid-target")
    assert item["plan"] == "pro"
    assert item["gallery_access"] is True
    assert card.json()["summary"]["plan"] == "pro"


def test_gallery_access_matches_plan_and_soft_delete_keeps_db_row(temp_db):
    make_user("iuid-mini", "web_mini", plan="mini", gallery_enabled=0)
    make_user("iuid-free", "web_free", plan="free", gallery_enabled=0)
    mini_token = main.create_auth_session("iuid-mini", "web_mini", provider="web_email", platform="web")["session_token"]
    free_token = main.create_auth_session("iuid-free", "web_free", provider="web_email", platform="web")["session_token"]
    with main.db() as conn:
        conn.execute(
            "INSERT INTO images (id,user_id,job_id,url,thumbnail_url,width,height,mode,provider,prompt_original,prompt_translated,settings_json,is_favorite,created_at) "
            "VALUES ('img1','web_mini','job1','/api/media/img1.png','/api/media/thumb1.png',512,512,'text_to_image','test','prompt','','{}',0,'2026-01-02')"
        )
    main.load_db_state()
    with TestClient(main.app) as c:
        free_gallery = c.get("/api/gallery", headers=bearer(free_token))
        before = c.get("/api/gallery", headers=bearer(mini_token))
        deleted = c.delete("/api/gallery/img1", headers=bearer(mini_token))
        after = c.get("/api/gallery", headers=bearer(mini_token))
    assert free_gallery.status_code == 200 and free_gallery.json() == []
    assert before.status_code == 200 and len(before.json()) == 1
    assert deleted.status_code == 200
    assert after.status_code == 200 and after.json() == []
    with main.db() as conn:
        row = conn.execute("SELECT deleted_at FROM images WHERE id='img1'").fetchone()
    assert row is not None
    assert row["deleted_at"] is not None


def test_mini_gallery_access_ignores_stale_disabled_flag(temp_db):
    make_user("iuid-mini-stale", "web_mini_stale", plan="mini", gallery_enabled=0)
    make_user("iuid-admin2", "web_admin2", role="admin", plan="free", gallery_enabled=0)
    with main.db() as conn:
        assert main.user_gallery_allowed(conn, "iuid-mini-stale", "web_mini_stale") is True
        assert main.user_gallery_allowed(conn, "iuid-admin2", "web_admin2") is True


def test_tariff_defaults_and_admin_settings_normalize(temp_db):
    token = admin_token()
    with TestClient(main.app) as c:
        c.cookies.set(main.TRUSTED_SESSION_COOKIE_NAME, token)
        c.headers.update({"X-OneNode-User": "telegram_admin"})
        public_default = c.get("/api/tariffs")
        saved = c.post(
            "/api/admin/settings/tariffs",
            json={"settings": {"free": {"daily_tokens": 11, "gallery_slots": 2}}},
        )
        settings = c.get("/api/admin/settings")
    assert public_default.status_code == 200
    assert public_default.json()["tariffs"]["free"] == {"daily_tokens": 10, "gallery_slots": 1}
    assert saved.status_code == 200
    assert saved.json()["settings"]["free"] == {"daily_tokens": 11, "gallery_slots": 2}
    assert saved.json()["settings"]["mini"] == {"daily_tokens": 50, "gallery_slots": 10}
    assert settings.json()["tariffs"]["free"]["gallery_slots"] == 2


def test_tariff_settings_persist_and_read_from_admin_settings(temp_db):
    token = admin_token()
    with TestClient(main.app) as c:
        c.cookies.set(main.TRUSTED_SESSION_COOKIE_NAME, token)
        c.headers.update({"X-OneNode-User": "telegram_admin"})
        saved = c.post(
            "/api/admin/settings/tariffs",
            json={"settings": {
                "free": {"daily_tokens": 12, "gallery_slots": 3},
                "mini": {"daily_tokens": 55, "gallery_slots": 11},
                "plus": {"daily_tokens": 110, "gallery_slots": 51},
                "pro": {"daily_tokens": 220, "gallery_slots": 101},
            }},
        )
    assert saved.status_code == 200
    main.load_db_state()
    with main.db() as conn:
        row = conn.execute("SELECT value_json FROM admin_settings WHERE key='tariffs'").fetchone()
        loaded = main.get_tariff_config(conn)
    assert row is not None
    assert loaded["free"] == {"daily_tokens": 12, "gallery_slots": 3}
    assert loaded["mini"] == {"daily_tokens": 55, "gallery_slots": 11}
    assert loaded["plus"] == {"daily_tokens": 110, "gallery_slots": 51}
    assert loaded["pro"] == {"daily_tokens": 220, "gallery_slots": 101}


def test_tariff_settings_reject_invalid_and_unauthorized(temp_db):
    admin = admin_token()
    make_user("iuid-user", "web_user", role="user", plan="mini")
    user_token = main.create_auth_session("iuid-user", "web_user", provider="web_email", platform="web")["session_token"]
    cases = [
        ({"unknown": {"daily_tokens": 1, "gallery_slots": 1}}, 400),
        ({"free": {"daily_tokens": -1, "gallery_slots": 1}}, 400),
        ({}, 400),
    ]
    with TestClient(main.app) as c:
        c.headers.update({"X-OneNode-User": "telegram_admin"})
        no_session = c.post("/api/admin/settings/tariffs", json={"settings": {"free": {"daily_tokens": 1, "gallery_slots": 1}}})
        c.cookies.set(main.TRUSTED_SESSION_COOKIE_NAME, user_token)
        non_admin = c.post("/api/admin/settings/tariffs", json={"settings": {"free": {"daily_tokens": 1, "gallery_slots": 1}}}, headers={"X-OneNode-User": "web_user"})
        c.cookies.set(main.TRUSTED_SESSION_COOKIE_NAME, admin)
        invalid = [c.post("/api/admin/settings/tariffs", json={"settings": payload}) for payload, _ in cases]
    assert no_session.status_code in (401, 403)
    assert non_admin.status_code == 403
    assert [r.status_code for r in invalid] == [code for _, code in cases]


def test_gallery_quota_free_slot_and_soft_delete(temp_db):
    make_user("iuid-free", "web_free", plan="free", gallery_enabled=0)
    with main.db() as conn:
        user = conn.execute("SELECT * FROM users WHERE id='web_free'").fetchone()
        empty = main.gallery_quota_for_user(conn, user, "web_free")
        conn.execute(
            "INSERT INTO images (id,user_id,job_id,url,thumbnail_url,width,height,mode,provider,prompt_original,prompt_translated,settings_json,is_favorite,created_at) "
            "VALUES ('img-free','web_free','job1','/api/media/img.png','/api/media/thumb.png',512,512,'text_to_image','test','prompt','','{}',0,'2026-01-02')"
        )
        full = main.gallery_quota_for_user(conn, user, "web_free")
        conn.execute("UPDATE images SET deleted_at='2026-01-03' WHERE id='img-free'")
        freed = main.gallery_quota_for_user(conn, user, "web_free")
    assert empty["gallery_slots"] == 1 and empty["gallery_free"] == 1
    assert full["gallery_used"] == 1 and full["gallery_full"] is True
    assert freed["gallery_used"] == 0 and freed["gallery_free"] == 1


def test_generation_completes_but_skips_gallery_when_slots_full(temp_db, monkeypatch):
    monkeypatch.setattr(main, "send_to_comfyui", fake_send_to_comfyui)
    make_user("iuid-free", "web_free", plan="free", gallery_enabled=1, balance=50)
    token = main.create_auth_session("iuid-free", "web_free", provider="web_email", platform="web")["session_token"]
    with main.db() as conn:
        conn.execute(
            "INSERT INTO images (id,user_id,job_id,url,thumbnail_url,width,height,mode,provider,prompt_original,prompt_translated,settings_json,is_favorite,created_at) "
            "VALUES ('img-existing','web_free','job-existing','/api/media/existing.png','/api/media/existing.webp',512,512,'text_to_image','test','prompt','','{}',0,'2026-01-02')"
        )
    main.load_db_state()
    with TestClient(main.app) as c:
        c.headers.update(bearer(token))
        created = c.post(
            "/api/generate",
            json={"mode": "text_to_image", "provider": "comfyui", "prompt": "slot full still returns result", "width": 512, "height": 512},
        )
        final = wait_for_terminal_job(c, created.json()["id"])
        gallery = c.get("/api/gallery")
    assert created.status_code == 200
    assert final["status"] == "completed"
    assert final["resultUrl"].startswith("/api/media/")
    assert final.get("resultImageId") is None
    assert final["gallerySaveStatus"] == "quota_full"
    assert final["galleryQuota"]["gallery_slots"] == 1
    assert len(gallery.json()) == 1


def test_deactivate_blocks_login_and_audits(temp_db):
    token = admin_token()
    make_user("iuid-target", "telegram_target", plan="mini")
    session = main.create_auth_session("iuid-target", "telegram_target", provider="telegram", platform="telegram_mini_app")
    with TestClient(main.app) as c:
        r = c.post("/api/admin/users/iuid-target/block-v2", json={"reason": "deactivate disposable"}, headers=bearer(token))
        me = c.get("/api/me-v2", headers=bearer(session["session_token"]))
    assert r.status_code == 200
    assert me.status_code == 401
    with main.db() as conn:
        assert conn.execute("SELECT banned FROM users WHERE internal_user_id='iuid-target'").fetchone()["banned"] == 1
        assert conn.execute("SELECT COUNT(*) AS c FROM audit_logs WHERE action='admin_block_user'").fetchone()["c"] == 1


def test_bonus_type_compensation_visible_in_row(temp_db):
    token = admin_token()
    make_user("iuid-target", "telegram_target", plan="mini")
    with TestClient(main.app) as c:
        r = c.post("/api/admin/users/iuid-target/bonus-v2", json={
            "token_amount": 1,
            "bonus_type": "compensation",
            "reason": "live disposable test",
            "idempotency_key": "bonus-comp-1",
        }, headers=bearer(token))
        detail = c.get("/api/admin/users/iuid-target/analytics-v2", headers=bearer(token))
    assert r.status_code == 200
    assert detail.json()["bonus_grants_recent"][0]["bonus_type"] == "compensation"
    with main.db() as conn:
        assert conn.execute("SELECT COUNT(*) AS c FROM token_ledger WHERE reason='admin_bonus_compensation'").fetchone()["c"] == 1
