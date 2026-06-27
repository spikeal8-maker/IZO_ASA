"""Jobs/Gallery ownership protection tests (Phase 16.1).

require_trusted_user guards job and gallery endpoints.
Temporary SQLite DB via monkeypatching main.DB_PATH; working DB never touched.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import main


def count(table, where="", params=()):
    with main.db() as conn:
        return conn.execute(f"SELECT COUNT(*) AS c FROM {table} {where}", params).fetchone()["c"]


def make_session(iuid, legacy, provider="web_email", platform="web_desktop"):
    return main.create_auth_session(iuid, legacy, provider=provider, platform=platform)


@pytest.fixture
def temp_db(tmp_path: Path, monkeypatch):
    db_file = tmp_path / "ownership_test.sqlite3"
    monkeypatch.setattr(main, "DB_PATH", db_file)
    monkeypatch.setattr(main, "TRUSTED_COOKIE_SECURE", False)
    monkeypatch.setattr(main, "COMFYUI_BASE_URL", "http://127.0.0.1:9999")
    monkeypatch.setattr(main, "TELEGRAM_BOT_TOKEN", "test")
    monkeypatch.setattr(main, "worker_started", True)
    main.init_db()
    return db_file


@pytest.fixture
def two_users(temp_db):
    """Create two users: user_a (has job + image) and user_b (has image).
    Persist data to SQLite so load_db_state() doesn't wipe it on TestClient startup."""
    now = "2026-01-01T00:00:00+00:00"
    with main.db() as conn:
        conn.execute(
            "INSERT INTO users (id, internal_user_id, language, role, token_balance, created_at, last_login_at) VALUES (?, ?, 'ru', 'user', 100, ?, ?)",
            ("web_a", "iuid-a", now, now),
        )
        conn.execute(
            "INSERT INTO auth_identities (id, internal_user_id, legacy_user_id, provider, provider_user_id, linked_at) VALUES (?, ?, ?, 'web_email', 'a@test.local', ?)",
            ("id-a", "iuid-a", "web_a", now),
        )
        conn.execute(
            "INSERT INTO users (id, internal_user_id, language, role, token_balance, created_at, last_login_at) VALUES (?, ?, 'ru', 'user', 100, ?, ?)",
            ("web_b", "iuid-b", now, now),
        )
        conn.execute(
            "INSERT INTO auth_identities (id, internal_user_id, legacy_user_id, provider, provider_user_id, linked_at) VALUES (?, ?, ?, 'web_email', 'b@test.local', ?)",
            ("id-b", "iuid-b", "web_b", now),
        )
        # Persist job and images to SQLite so load_db_state() picks them up
        conn.execute(
            "INSERT INTO jobs (id, user_id, mode, provider, status, progress, settings_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("job-a-001", "web_a", "text_to_image", "comfyui", "completed", 100, '{"mode":"text_to_image","prompt":"a cat"}', "2026-01-01T01:00:00+00:00"),
        )
        conn.execute(
            "INSERT INTO images (id, user_id, job_id, url, thumbnail_url, width, height, mode, provider, settings_json, is_favorite, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("img-a-001", "web_a", "job-a-001", "/images/a.png", "/images/a_thumb.png", 512, 512, "text_to_image", "comfyui", '{"seed":42}', 0, "2026-01-01T01:00:00+00:00"),
        )
        conn.execute(
            "INSERT INTO images (id, user_id, job_id, url, thumbnail_url, width, height, mode, provider, settings_json, is_favorite, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("img-b-001", "web_b", "job-a-001", "/images/b.png", "/images/b_thumb.png", 512, 512, "text_to_image", "comfyui", '{"seed":99}', 0, "2026-01-01T02:00:00+00:00"),
        )
    # Populate in-memory stores (will be rebuilt by load_db_state on TestClient startup, but set here for tests that run before client is created)
    main.load_db_state()
    return {
        "a": {"internal_user_id": "iuid-a", "legacy_user_id": "web_a"},
        "b": {"internal_user_id": "iuid-b", "legacy_user_id": "web_b"},
    }


def sess_a(two_users):
    return make_session("iuid-a", "web_a")


def sess_b(two_users):
    return make_session("iuid-b", "web_b")


# --- 1. GET job without session → 401 ---
def test_get_job_no_session_401(temp_db, two_users):
    with TestClient(main.app) as c:
        r = c.get("/api/jobs/job-a-001")
    assert r.status_code == 401


# --- 2. GET job with spoofed X-OneNode-User only → 401 ---
def test_get_job_spoofed_header_401(temp_db, two_users):
    with TestClient(main.app) as c:
        r = c.get("/api/jobs/job-a-001", headers={"X-OneNode-User": "web_a"})
    assert r.status_code == 401


# --- 3. GET own job with valid session → 200 ---
def test_get_own_job_200(temp_db, two_users):
    sa = sess_a(two_users)
    with TestClient(main.app) as c:
        r = c.get("/api/jobs/job-a-001", cookies={"onenode_session": sa["session_token"]})
    assert r.status_code == 200
    assert r.json()["id"] == "job-a-001"


# --- 4. GET other user's job with valid session → 404 ---
def test_get_other_job_404(temp_db, two_users):
    sb = sess_b(two_users)
    with TestClient(main.app) as c:
        r = c.get("/api/jobs/job-a-001", cookies={"onenode_session": sb["session_token"]})
    assert r.status_code == 404


# --- 5. Cancel own job → success (200) ---
def test_cancel_own_job_200(temp_db, two_users):
    sa = sess_a(two_users)
    ja = main.jobs.get("job-a-001", {})
    ja["status"] = "queued"  # make it cancellable
    with TestClient(main.app) as c:
        r = c.post("/api/jobs/job-a-001/cancel", cookies={"onenode_session": sa["session_token"]})
    assert r.status_code == 200
    assert r.json()["status"] == "cancelled"


# --- 6. Cancel other user's job → 404 ---
def test_cancel_other_job_404(temp_db, two_users):
    sb = sess_b(two_users)
    with TestClient(main.app) as c:
        r = c.post("/api/jobs/job-a-001/cancel", cookies={"onenode_session": sb["session_token"]})
    assert r.status_code == 404


# --- 7. Gallery list without session → 401 ---
def test_gallery_no_session_401(temp_db, two_users):
    with TestClient(main.app) as c:
        r = c.get("/api/gallery")
    assert r.status_code == 401


# --- 8. Gallery list with spoofed X-OneNode-User → 401 ---
def test_gallery_spoofed_header_401(temp_db, two_users):
    with TestClient(main.app) as c:
        r = c.get("/api/gallery", headers={"X-OneNode-User": "web_a"})
    assert r.status_code == 401


# --- 9. Gallery list returns only own images ---
def test_gallery_own_images_only(temp_db, two_users):
    sa = sess_a(two_users)
    with TestClient(main.app) as c:
        r = c.get("/api/gallery", cookies={"onenode_session": sa["session_token"]})
    assert r.status_code == 200
    items = r.json()
    ids = {img["id"] for img in items}
    assert "img-a-001" in ids
    assert "img-b-001" not in ids


# --- 10. Gallery favorite own image → success ---
def test_favorite_own_image_200(temp_db, two_users):
    sa = sess_a(two_users)
    with TestClient(main.app) as c:
        r = c.post("/api/gallery/img-a-001/favorite", json={"isFavorite": True}, cookies={"onenode_session": sa["session_token"]})
    assert r.status_code == 200
    assert r.json()["isFavorite"] is True


# --- 11. Gallery favorite other user's image → 404 ---
def test_favorite_other_image_404(temp_db, two_users):
    sa = sess_a(two_users)
    with TestClient(main.app) as c:
        r = c.post("/api/gallery/img-b-001/favorite", json={"isFavorite": True}, cookies={"onenode_session": sa["session_token"]})
    assert r.status_code == 404


# --- 12. Gallery delete own image → success ---
def test_delete_own_image_200(temp_db, two_users):
    sa = sess_a(two_users)
    with TestClient(main.app) as c:
        r = c.delete("/api/gallery/img-a-001", cookies={"onenode_session": sa["session_token"]})
    assert r.status_code == 200
    assert r.json()["ok"] is True


# --- 13. Gallery delete other user's image → 404 ---
def test_delete_other_image_404(temp_db, two_users):
    sa = sess_a(two_users)
    with TestClient(main.app) as c:
        r = c.delete("/api/gallery/img-b-001", cookies={"onenode_session": sa["session_token"]})
    assert r.status_code == 404


# --- 14. Gallery use-as own image → success ---
def test_use_as_own_image_200(temp_db, two_users):
    sa = sess_a(two_users)
    with TestClient(main.app) as c:
        r = c.post("/api/gallery/img-a-001/use-as", json={"target": "image_to_image"}, cookies={"onenode_session": sa["session_token"]})
    assert r.status_code == 200
    assert r.json()["ok"] is True


# --- 15. Gallery use-as other user's image → 404 ---
def test_use_as_other_image_404(temp_db, two_users):
    sa = sess_a(two_users)
    with TestClient(main.app) as c:
        r = c.post("/api/gallery/img-b-001/use-as", json={"target": "image_to_image"}, cookies={"onenode_session": sa["session_token"]})
    assert r.status_code == 404


# --- 16. Gallery send own image → success (local delivery) ---
def test_send_own_image_200(temp_db, two_users):
    sa = sess_a(two_users)
    with TestClient(main.app) as c:
        r = c.post("/api/gallery/img-a-001/send", json={"platform": "telegram"}, cookies={"onenode_session": sa["session_token"]})
    assert r.status_code == 200
    assert r.json()["ok"] is True


# --- 17. Gallery send other user's image → 404 ---
def test_send_other_image_404(temp_db, two_users):
    sa = sess_a(two_users)
    with TestClient(main.app) as c:
        r = c.post("/api/gallery/img-b-001/send", json={"platform": "telegram"}, cookies={"onenode_session": sa["session_token"]})
    assert r.status_code == 404


# --- 18. Banned user gets 403 ---
def test_banned_user_403(temp_db, two_users):
    with main.db() as conn:
        conn.execute("UPDATE users SET banned=1 WHERE internal_user_id=?", ("iuid-a",))
    sa = sess_a(two_users)
    with TestClient(main.app) as c:
        r = c.get("/api/gallery", cookies={"onenode_session": sa["session_token"]})
    assert r.status_code == 403


# --- 19. Spoofed X-OneNode-User with valid session does not override ---
def test_spoofed_header_does_not_override_session(temp_db, two_users):
    sa = sess_a(two_users)
    with TestClient(main.app) as c:
        r = c.get("/api/gallery", headers={"X-OneNode-User": "web_b"}, cookies={"onenode_session": sa["session_token"]})
    assert r.status_code == 200
    items = r.json()
    ids = {img["id"] for img in items}
    assert "img-a-001" in ids   # user A's image (from session, not header)
    assert "img-b-001" not in ids  # user B's image not leaked


# --- 20. request_user_id unchanged ---
def test_request_user_id_unchanged():
    import inspect
    src = inspect.getsource(main.request_user_id)
    assert "X-OneNode-User" in src
    assert "onenode_user" in src


# --- 21. require_admin unchanged ---
def test_require_admin_unchanged():
    import inspect
    src = inspect.getsource(main.require_admin)
    assert "request_user_id" in src


# --- 22. users.id unchanged after operations ---
def test_users_id_unchanged(temp_db, two_users):
    with main.db() as conn:
        conn.execute("INSERT INTO users (id, internal_user_id, language, role, created_at, last_login_at) VALUES ('telegram_legacy','iuid-legacy','ru','user','2026-01-01','2026-01-01')")
        before = sorted(r["id"] for r in conn.execute("SELECT id FROM users"))
    sa = sess_a(two_users)
    with TestClient(main.app) as c:
        c.get("/api/gallery", cookies={"onenode_session": sa["session_token"]})
        c.post("/api/gallery/img-a-001/favorite", json={"isFavorite": True}, cookies={"onenode_session": sa["session_token"]})
    with main.db() as conn:
        after = sorted(r["id"] for r in conn.execute("SELECT id FROM users"))
    assert "telegram_legacy" in after
    assert all(i in after for i in before)
