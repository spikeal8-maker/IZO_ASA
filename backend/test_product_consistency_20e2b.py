"""Phase 20E.2B product consistency tests. Temp SQLite; no live DB."""
from __future__ import annotations

import pytest
import asyncio
from fastapi.testclient import TestClient

import main
from test_api import fake_send_to_comfyui, wait_for_terminal_job

PW = "S3cret-Password!"


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "product_consistency_test.sqlite3"
    monkeypatch.setattr(main, "DB_PATH", db_file)
    monkeypatch.setattr(main, "TRUSTED_COOKIE_SECURE", False)
    monkeypatch.setattr(main, "send_to_comfyui", fake_send_to_comfyui)
    main.jobs.clear()
    main.images.clear()
    main.queue = asyncio.Queue()
    main.worker_started = False
    main.init_db()
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
        free = c.get("/api/gallery", headers=bearer(free_token))
        before = c.get("/api/gallery", headers=bearer(mini_token))
        deleted = c.delete("/api/gallery/img1", headers=bearer(mini_token))
        after = c.get("/api/gallery", headers=bearer(mini_token))
    assert free.status_code == 200 and free.json() == []
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
        assert main.user_gallery_allowed(conn, "missing", "missing") is False


def test_tariff_defaults_and_admin_settings_normalize(temp_db):
    token = admin_token()
    with TestClient(main.app) as c:
        public = c.get("/api/tariffs")
        settings = c.get("/api/admin/settings", headers=bearer(token))
    assert public.status_code == 200
    assert public.json()["tariffs"]["free"] == {"daily_tokens": 10, "gallery_slots": 1}
    assert public.json()["tariffs"]["mini"] == {"daily_tokens": 50, "gallery_slots": 10}
    assert public.json()["tariffs"]["plus"] == {"daily_tokens": 100, "gallery_slots": 50}
    assert public.json()["tariffs"]["pro"] == {"daily_tokens": 200, "gallery_slots": 100}
    assert settings.status_code == 200
    assert settings.json()["tariffs"]["pro"]["gallery_slots"] == 100


def test_tariff_settings_persist_and_read_from_admin_settings(temp_db):
    token = admin_token()
    payload = {
        "free": {"daily_tokens": 11, "gallery_slots": 2},
        "mini": {"daily_tokens": 55, "gallery_slots": 12},
        "plus": {"daily_tokens": 110, "gallery_slots": 52},
        "pro": {"daily_tokens": 220, "gallery_slots": 102},
    }
    with TestClient(main.app) as c:
        saved = c.post("/api/admin/settings/tariffs", json={"settings": payload}, headers=bearer(token))
        public = c.get("/api/tariffs")
    assert saved.status_code == 200, saved.text
    assert saved.json()["settings"] == payload
    assert public.json()["tariffs"] == payload
    with main.db() as conn:
        row = conn.execute("SELECT value_json FROM admin_settings WHERE key='tariffs'").fetchone()
        assert row is not None
        assert main.get_tariff_config(conn) == payload


def test_tariff_settings_reject_invalid_and_unauthorized(temp_db):
    admin = admin_token()
    make_user("iuid-user", "web_user", role="user", plan="mini")
    user = main.create_auth_session("iuid-user", "web_user", provider="web_email", platform="web")["session_token"]
    with TestClient(main.app) as c:
        assert c.post("/api/admin/settings/tariffs", json={"settings": main.DEFAULT_TARIFFS}).status_code in {401, 403}
        assert c.post("/api/admin/settings/tariffs", json={"settings": main.DEFAULT_TARIFFS}, headers=bearer(user)).status_code == 403
        assert c.post("/api/admin/settings/tariffs", json={"settings": {}}, headers=bearer(admin)).status_code == 400
        assert c.post("/api/admin/settings/tariffs", json={"settings": {"vip": {"daily_tokens": 1, "gallery_slots": 1}}}, headers=bearer(admin)).status_code == 400
        negative = {**main.DEFAULT_TARIFFS, "free": {"daily_tokens": -1, "gallery_slots": 1}}
        assert c.post("/api/admin/settings/tariffs", json={"settings": negative}, headers=bearer(admin)).status_code == 400


def test_gallery_quota_free_slot_and_soft_delete(temp_db):
    make_user("iuid-free-quota", "web_free_quota", plan="free", gallery_enabled=0)
    token = main.create_auth_session("iuid-free-quota", "web_free_quota", provider="web_email", platform="web")["session_token"]
    with main.db() as conn:
        conn.execute(
            "INSERT INTO images (id,user_id,job_id,url,thumbnail_url,width,height,mode,provider,prompt_original,prompt_translated,settings_json,is_favorite,created_at) "
            "VALUES ('img-free-1','web_free_quota','job1','/api/media/img1.png','/api/media/thumb1.png',512,512,'text_to_image','test','prompt','','{}',0,'2026-01-02')"
        )
        row = conn.execute("SELECT * FROM users WHERE id='web_free_quota'").fetchone()
        quota = main.gallery_quota_for_user(conn, row, "web_free_quota")
    assert quota["gallery_slots"] == 1
    assert quota["gallery_used"] == 1
    assert quota["gallery_full"] is True
    main.load_db_state()
    with TestClient(main.app) as c:
        deleted = c.delete("/api/gallery/img-free-1", headers=bearer(token))
        me = c.get("/api/me-v2", headers=bearer(token))
    assert deleted.status_code == 200
    assert me.status_code == 200
    assert me.json()["account"]["gallery_used"] == 0
    assert me.json()["account"]["gallery_free"] == 1
    assert me.json()["account"]["gallery_full"] is False
    with main.db() as conn:
        row = conn.execute("SELECT * FROM users WHERE id='web_free_quota'").fetchone()
        quota = main.gallery_quota_for_user(conn, row, "web_free_quota")
    assert quota["gallery_used"] == 0
    assert quota["gallery_free"] == 1


def test_generation_replaces_oldest_gallery_slot_when_full(temp_db):
    make_user("iuid-free-gen", "web_free_gen", plan="free", gallery_enabled=0, balance=100)
    token = main.create_auth_session("iuid-free-gen", "web_free_gen", provider="web_email", platform="web")["session_token"]
    payload = {
        "mode": "text_to_image",
        "provider": "comfyui",
        "prompt": "safe prompt",
        "width": 512,
        "height": 512,
        "steps": 4,
        "cfg": 1,
        "loras": [],
    }
    with TestClient(main.app) as c:
        c.cookies.set("onenode_session", token)
        first = c.post("/api/generate", json=payload, headers=bearer(token))
        assert first.status_code == 200, first.text
        first_final = wait_for_terminal_job(c, first.json()["id"])
        second = c.post("/api/generate", json=payload, headers=bearer(token))
        assert second.status_code == 200, second.text
        second_final = wait_for_terminal_job(c, second.json()["id"])
    assert first_final["status"] == "completed"
    assert first_final["gallerySaveStatus"] == "saved"
    assert first_final["resultImageId"]
    assert second_final["status"] == "completed"
    assert second_final["gallerySaveStatus"] == "saved"
    assert second_final["resultUrl"]
    assert second_final["resultImageId"]
    with main.db() as conn:
        active = conn.execute("SELECT id FROM images WHERE user_id='web_free_gen' AND deleted_at IS NULL ORDER BY created_at").fetchall()
        deleted = conn.execute("SELECT id FROM images WHERE user_id='web_free_gen' AND deleted_at IS NOT NULL").fetchall()
    assert len(active) == 1
    assert [row["id"] for row in active] == [second_final["resultImageId"]]
    assert [row["id"] for row in deleted] == [first_final["resultImageId"]]


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
