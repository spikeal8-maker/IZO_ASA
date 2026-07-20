"""Jobs/Gallery ownership protection tests (Phase 16.1).

require_trusted_user guards job and gallery endpoints.
Temporary SQLite DB via monkeypatching main.DB_PATH; working DB never touched.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from test_support.browser_client import BrowserTestClient

import main


def count(table, where="", params=()):
    with main.db() as conn:
        return conn.execute(f"SELECT COUNT(*) AS c FROM {table} {where}", params).fetchone()["c"]


def make_session(iuid, legacy, provider="web_email", platform="web_desktop"):
    return main.create_auth_session(iuid, legacy, provider=provider, platform=platform)


@pytest.fixture
def temp_db(tmp_path: Path, monkeypatch):
    db_file = tmp_path / "ownership_test.sqlite3"
    media_dir = tmp_path / "media"
    media_dir.mkdir()
    avatar_dir = media_dir / "avatars"
    avatar_dir.mkdir()
    monkeypatch.setattr(main, "DB_PATH", db_file)
    monkeypatch.setattr(main, "MEDIA", media_dir)
    monkeypatch.setattr(main, "AVATAR_DIR", avatar_dir)
    monkeypatch.setattr(main, "TRUSTED_COOKIE_SECURE", False)
    monkeypatch.setattr(main, "COMFYUI_BASE_URL", "http://127.0.0.1:9999")
    monkeypatch.setattr(main, "TELEGRAM_BOT_TOKEN", "test")
    monkeypatch.setattr(main, "worker_started", True)
    # Before the security fix, /media is a StaticFiles mount created at import
    # time and therefore keeps the original live directory. Point that mount at
    # the temporary test directory so the regression test exercises the actual
    # route without ever touching live media. After the mount is removed this
    # loop intentionally becomes a no-op.
    for route in main.app.routes:
        if getattr(route, "path", None) == "/media" and hasattr(getattr(route, "app", None), "all_directories"):
            monkeypatch.setattr(route.app, "directory", str(media_dir))
            monkeypatch.setattr(route.app, "all_directories", [str(media_dir)])
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
            ("img-a-001", "web_a", "job-a-001", "/api/media/a.png?userId=web_a", "/api/media/a_thumb.webp?userId=web_a", 512, 512, "text_to_image", "comfyui", '{"seed":42}', 0, "2026-01-01T01:00:00+00:00"),
        )
        conn.execute(
            "INSERT INTO images (id, user_id, job_id, url, thumbnail_url, width, height, mode, provider, settings_json, is_favorite, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("img-b-001", "web_b", "job-a-001", "/images/b.png", "/images/b_thumb.png", 512, 512, "text_to_image", "comfyui", '{"seed":99}', 0, "2026-01-01T02:00:00+00:00"),
        )
    (main.MEDIA / "a.png").write_bytes(b"fake-png")
    (main.MEDIA / "a_thumb.webp").write_bytes(b"fake-webp")
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
    with BrowserTestClient(main.app) as c:
        r = c.get("/api/jobs/job-a-001")
    assert r.status_code == 401


# --- 2. GET job with spoofed X-OneNode-User only → 401 ---
def test_get_job_spoofed_header_401(temp_db, two_users):
    with BrowserTestClient(main.app) as c:
        r = c.get("/api/jobs/job-a-001", headers={"X-OneNode-User": "web_a"})
    assert r.status_code == 401


# --- 3. GET own job with valid session → 200 ---
def test_get_own_job_200(temp_db, two_users):
    sa = sess_a(two_users)
    with BrowserTestClient(main.app) as c:
        r = c.get("/api/jobs/job-a-001", cookies={"onenode_session": sa["session_token"]})
    assert r.status_code == 200
    assert r.json()["id"] == "job-a-001"


# --- 4. GET other user's job with valid session → 404 ---
def test_get_other_job_404(temp_db, two_users):
    sb = sess_b(two_users)
    with BrowserTestClient(main.app) as c:
        r = c.get("/api/jobs/job-a-001", cookies={"onenode_session": sb["session_token"]})
    assert r.status_code == 404


# --- 5. Cancel own job → success (200) ---
def test_cancel_own_job_200(temp_db, two_users):
    sa = sess_a(two_users)
    with BrowserTestClient(main.app) as c:
        with main.db() as conn:
            conn.execute(
                "INSERT INTO jobs (id, user_id, mode, provider, status, progress, settings_json, created_at) "
                "VALUES ('job-a-cancel', 'web_a', 'text_to_image', 'comfyui', 'queued', 0, '{}', "
                "'2026-01-01T03:00:00+00:00')"
            )
        main.load_db_state()
        r = c.post("/api/jobs/job-a-cancel/cancel", cookies={"onenode_session": sa["session_token"]})
    assert r.status_code == 200
    assert r.json()["status"] == "cancelled"


# --- 6. Cancel other user's job → 404 ---
def test_cancel_other_job_404(temp_db, two_users):
    sb = sess_b(two_users)
    with BrowserTestClient(main.app) as c:
        r = c.post("/api/jobs/job-a-001/cancel", cookies={"onenode_session": sb["session_token"]})
    assert r.status_code == 404


# --- 7. Gallery list without session → 401 ---
def test_gallery_no_session_401(temp_db, two_users):
    with BrowserTestClient(main.app) as c:
        r = c.get("/api/gallery")
    assert r.status_code == 401


# --- 8. Gallery list with spoofed X-OneNode-User → 401 ---
def test_gallery_spoofed_header_401(temp_db, two_users):
    with BrowserTestClient(main.app) as c:
        r = c.get("/api/gallery", headers={"X-OneNode-User": "web_a"})
    assert r.status_code == 401


# --- 9. Media URL query userId is not authentication ---
def test_media_query_user_id_without_session_401(temp_db, two_users):
    with BrowserTestClient(main.app) as c:
        r = c.get("/api/media/a.png?userId=web_a")
    assert r.status_code == 401


def test_media_query_user_id_with_other_session_404(temp_db, two_users):
    sb = sess_b(two_users)
    with BrowserTestClient(main.app) as c:
        r = c.get("/api/media/a.png?userId=web_a", cookies={"onenode_session": sb["session_token"]})
    assert r.status_code == 404


def test_media_own_session_200(temp_db, two_users):
    sa = sess_a(two_users)
    with BrowserTestClient(main.app) as c:
        r = c.get("/api/media/a.png?userId=web_a", cookies={"onenode_session": sa["session_token"]})
    assert r.status_code == 200
    assert r.content == b"fake-png"


def test_media_owner_prefix_does_not_authorize_different_filename(temp_db, two_users):
    (main.MEDIA / "a.png.evil").write_bytes(b"must-not-leak")
    sa = sess_a(two_users)
    with BrowserTestClient(main.app) as c:
        r = c.get(
            "/api/media/a.png.evil?userId=web_a",
            cookies={"onenode_session": sa["session_token"]},
        )
    assert r.status_code == 404


def test_legacy_media_path_without_session_401(temp_db, two_users):
    with BrowserTestClient(main.app) as c:
        r = c.get("/media/a.png")
    assert r.status_code == 401


def test_legacy_media_path_with_other_session_404(temp_db, two_users):
    sb = sess_b(two_users)
    with BrowserTestClient(main.app) as c:
        r = c.get("/media/a.png", cookies={"onenode_session": sb["session_token"]})
    assert r.status_code == 404


def test_legacy_media_path_with_owner_session_200(temp_db, two_users):
    sa = sess_a(two_users)
    with BrowserTestClient(main.app) as c:
        r = c.get("/media/a.png", cookies={"onenode_session": sa["session_token"]})
    assert r.status_code == 200
    assert r.content == b"fake-png"


def test_referenced_custom_avatar_stays_public(temp_db, two_users):
    avatar = main.AVATAR_DIR / "public-avatar.webp"
    avatar.write_bytes(b"fake-avatar")
    with main.db() as conn:
        conn.execute(
            "UPDATE users SET avatar_url = '/media/avatars/public-avatar.webp' WHERE id = 'web_a'"
        )
    with BrowserTestClient(main.app) as c:
        r = c.get("/media/avatars/public-avatar.webp")
    assert r.status_code == 200
    assert r.content == b"fake-avatar"


def test_unreferenced_custom_avatar_is_not_public(temp_db, two_users):
    (main.AVATAR_DIR / "orphan-avatar.webp").write_bytes(b"orphan")
    with BrowserTestClient(main.app) as c:
        r = c.get("/media/avatars/orphan-avatar.webp")
    assert r.status_code == 404


# --- 10. Gallery list returns only own images ---
def test_gallery_own_images_only(temp_db, two_users):
    sa = sess_a(two_users)
    with BrowserTestClient(main.app) as c:
        r = c.get("/api/gallery", cookies={"onenode_session": sa["session_token"]})
    assert r.status_code == 200
    items = r.json()
    ids = {img["id"] for img in items}
    assert "img-a-001" in ids
    assert "img-b-001" not in ids


# --- 10. Gallery favorite own image → success ---
def test_favorite_own_image_200(temp_db, two_users):
    sa = sess_a(two_users)
    with BrowserTestClient(main.app) as c:
        r = c.post("/api/gallery/img-a-001/favorite", json={"isFavorite": True}, cookies={"onenode_session": sa["session_token"]})
    assert r.status_code == 200
    assert r.json()["isFavorite"] is True


# --- 11. Gallery favorite other user's image → 404 ---
def test_favorite_other_image_404(temp_db, two_users):
    sa = sess_a(two_users)
    with BrowserTestClient(main.app) as c:
        r = c.post("/api/gallery/img-b-001/favorite", json={"isFavorite": True}, cookies={"onenode_session": sa["session_token"]})
    assert r.status_code == 404


# --- 12. Gallery delete own image → success ---
def test_delete_own_image_200(temp_db, two_users):
    sa = sess_a(two_users)
    with BrowserTestClient(main.app) as c:
        r = c.delete("/api/gallery/img-a-001", cookies={"onenode_session": sa["session_token"]})
    assert r.status_code == 200
    assert r.json()["ok"] is True


# --- 13. Gallery delete other user's image → 404 ---
def test_delete_other_image_404(temp_db, two_users):
    sa = sess_a(two_users)
    with BrowserTestClient(main.app) as c:
        r = c.delete("/api/gallery/img-b-001", cookies={"onenode_session": sa["session_token"]})
    assert r.status_code == 404


# --- 14. Gallery use-as own image → success ---
def test_use_as_own_image_200(temp_db, two_users):
    sa = sess_a(two_users)
    with BrowserTestClient(main.app) as c:
        r = c.post("/api/gallery/img-a-001/use-as", json={"target": "image_to_image"}, cookies={"onenode_session": sa["session_token"]})
    assert r.status_code == 200
    assert r.json()["ok"] is True


# --- 15. Gallery use-as other user's image → 404 ---
def test_use_as_other_image_404(temp_db, two_users):
    sa = sess_a(two_users)
    with BrowserTestClient(main.app) as c:
        r = c.post("/api/gallery/img-b-001/use-as", json={"target": "image_to_image"}, cookies={"onenode_session": sa["session_token"]})
    assert r.status_code == 404


def test_source_library_item_remains_usable_after_parent_gallery_image_is_deleted(temp_db, two_users):
    source_file = main.MEDIA / "source-a.webp"
    source_file.write_bytes(b"source-preview")
    with main.db() as conn:
        conn.execute(
            """
            INSERT INTO image_sources (
                id, image_id, user_id, source_kind, role, slot_index, thumb_url,
                thumb_width, thumb_height, thumb_bytes, availability_status, created_at
            ) VALUES (?, ?, ?, 'upload', 'base', 1, ?, 320, 240, ?, 'available', ?)
            """,
            (
                "source-a-001",
                "img-a-001",
                "web_a",
                "/api/media/source-a.webp?userId=web_a",
                source_file.stat().st_size,
                "2026-01-01T01:00:00+00:00",
            ),
        )
        conn.execute("UPDATE images SET deleted_at = ? WHERE id = ?", ("2026-02-01", "img-a-001"))

    sa = sess_a(two_users)
    with BrowserTestClient(main.app) as c:
        use_as = c.post(
            "/api/gallery/sources/source-a-001/use-as",
            json={"target": "image_to_image"},
            cookies={"onenode_session": sa["session_token"]},
        )
        media = c.get(
            "/api/media/source-a.webp?userId=web_a",
            cookies={"onenode_session": sa["session_token"]},
        )

    assert use_as.status_code == 200
    assert use_as.json()["inputImage"].startswith("/api/media/source-a.webp")
    assert media.status_code == 200
    assert media.content == b"source-preview"


# --- 16. Gallery send own image → success (local delivery) ---
def test_send_own_image_200(temp_db, two_users):
    sa = sess_a(two_users)
    with BrowserTestClient(main.app) as c:
        r = c.post("/api/gallery/img-a-001/send", json={"platform": "telegram"}, cookies={"onenode_session": sa["session_token"]})
    assert r.status_code == 200
    assert r.json()["ok"] is True


# --- 17. Gallery send other user's image → 404 ---
def test_send_other_image_404(temp_db, two_users):
    sa = sess_a(two_users)
    with BrowserTestClient(main.app) as c:
        r = c.post("/api/gallery/img-b-001/send", json={"platform": "telegram"}, cookies={"onenode_session": sa["session_token"]})
    assert r.status_code == 404


# --- 18. Banned user gets 403 ---
def test_banned_user_403(temp_db, two_users):
    with main.db() as conn:
        conn.execute("UPDATE users SET banned=1 WHERE internal_user_id=?", ("iuid-a",))
    sa = sess_a(two_users)
    with BrowserTestClient(main.app) as c:
        r = c.get("/api/gallery", cookies={"onenode_session": sa["session_token"]})
    assert r.status_code == 403


# --- 19. Spoofed X-OneNode-User with valid session does not override ---
def test_spoofed_header_does_not_override_session(temp_db, two_users):
    sa = sess_a(two_users)
    with BrowserTestClient(main.app) as c:
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
    with BrowserTestClient(main.app) as c:
        c.get("/api/gallery", cookies={"onenode_session": sa["session_token"]})
        c.post("/api/gallery/img-a-001/favorite", json={"isFavorite": True}, cookies={"onenode_session": sa["session_token"]})
    with main.db() as conn:
        after = sorted(r["id"] for r in conn.execute("SELECT id FROM users"))
    assert "telegram_legacy" in after
    assert all(i in after for i in before)
