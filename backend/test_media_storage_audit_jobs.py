from __future__ import annotations

import json

import main
import media_storage_audit


def test_missing_completed_job_reference_is_diagnostic_not_blocking(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "audit.sqlite3")
    monkeypatch.setattr(main, "MEDIA", tmp_path / "media")
    main.MEDIA.mkdir()
    main.init_db()
    settings = json.dumps({"inputImage1": "/api/media/old-input.png?userId=user"})
    with main.db() as conn:
        conn.execute(
            "INSERT INTO jobs (id, user_id, status, progress, mode, provider, settings_json, created_at, completed_at) "
            "VALUES ('done-job', 'user', 'completed', 100, 'edit', 'test', ?, '2026-07-11', '2026-07-11')",
            (settings,),
        )

    report = media_storage_audit.audit_media_storage(item_limit=10)

    assert report["missing_active_refs"] == []
    assert report["issues"] == []
    assert report["missing_historical_job_refs"][0]["file"] == "old-input.png"


def test_missing_running_job_reference_remains_blocking(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "audit.sqlite3")
    monkeypatch.setattr(main, "MEDIA", tmp_path / "media")
    main.MEDIA.mkdir()
    main.init_db()
    settings = json.dumps({"inputImage1": "/api/media/live-input.png?userId=user"})
    with main.db() as conn:
        conn.execute(
            "INSERT INTO jobs (id, user_id, status, progress, mode, provider, settings_json, created_at, started_at) "
            "VALUES ('live-job', 'user', 'running', 50, 'edit', 'test', ?, '2026-07-11', '2026-07-11')",
            (settings,),
        )

    report = media_storage_audit.audit_media_storage(item_limit=10)

    assert report["issues"] == ["missing_active_refs"]
    assert report["missing_active_refs"][0]["file"] == "live-input.png"


def test_user_avatar_and_active_source_thumbnail_are_referenced(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "audit.sqlite3")
    monkeypatch.setattr(main, "MEDIA", tmp_path / "media")
    main.MEDIA.mkdir()
    (main.MEDIA / "avatars").mkdir()
    (main.MEDIA / "avatars" / "user.webp").write_bytes(b"avatar")
    (main.MEDIA / "source.webp").write_bytes(b"source")
    main.init_db()
    with main.db() as conn:
        conn.execute(
            "INSERT INTO users (id, language, role, avatar_url, created_at, last_login_at) "
            "VALUES ('owner', 'ru', 'user', '/media/avatars/user.webp', '2026-07-11', '2026-07-11')"
        )
        conn.execute(
            "INSERT INTO images (id, user_id, job_id, url, thumbnail_url, width, height, mode, provider, settings_json, created_at) "
            "VALUES ('image', 'owner', 'job', '/api/media/source.webp', '/api/media/source.webp', 10, 10, 'edit', 'test', '{}', '2026-07-11')"
        )
        conn.execute(
            "INSERT INTO image_sources (id, image_id, user_id, source_kind, role, slot_index, thumb_url, created_at) "
            "VALUES ('source', 'image', 'owner', 'upload', 'base', 0, '/api/media/source.webp', '2026-07-11')"
        )

    report = media_storage_audit.audit_media_storage(item_limit=10)

    assert report["issues"] == []
    assert report["unreferenced"]["count"] == 0
    assert report["active_referenced"]["count"] == 2


def test_known_missing_source_is_diagnostic_not_blocking(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "audit.sqlite3")
    monkeypatch.setattr(main, "MEDIA", tmp_path / "media")
    main.MEDIA.mkdir()
    main.init_db()
    with main.db() as conn:
        conn.execute(
            "INSERT INTO images (id, user_id, job_id, url, thumbnail_url, width, height, mode, provider, settings_json, created_at) "
            "VALUES ('image', 'owner', 'job', '/api/media/image.webp', '/api/media/image.webp', 10, 10, 'edit', 'test', '{}', '2026-07-11')"
        )
        (main.MEDIA / "image.webp").write_bytes(b"image")
        conn.execute(
            "INSERT INTO image_sources (id, image_id, user_id, source_kind, role, slot_index, thumb_url, created_at, availability_status) "
            "VALUES ('source', 'image', 'owner', 'upload', 'base', 0, '/api/media/known-missing.webp', '2026-07-11', 'missing')"
        )

    report = media_storage_audit.audit_media_storage(item_limit=10)

    assert report["issues"] == []
    assert report["missing_active_refs"] == []
    assert report["missing_known_unavailable_refs"][0]["file"] == "known-missing.webp"
