from __future__ import annotations

import base64
import json
from io import BytesIO

from PIL import Image

import main
import gallery_original_migrate


def test_older_gallery_images_are_compacted_once(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "gallery.sqlite3")
    monkeypatch.setattr(main, "MEDIA", tmp_path / "media")
    monkeypatch.setattr(main, "GALLERY_ARCHIVE_MAX_SIDE", 768)
    main.MEDIA.mkdir()
    main.init_db()

    user_id = "storage-user"
    with main.db() as conn:
        conn.execute(
            "INSERT INTO users (id, language, role, created_at, last_login_at) "
            "VALUES (?, 'ru', 'user', '2026-01-01', '2026-01-01')",
            (user_id,),
        )
        for index in range(12):
            image_id = f"img-{index:02d}"
            path = main.MEDIA / f"{image_id}.png"
            image = Image.effect_noise((1024, 768), 80).convert("RGB")
            image.save(path, "PNG")
            thumb = main.create_thumbnail(path)
            conn.execute(
                "INSERT INTO images (id, user_id, job_id, url, thumbnail_url, width, height, mode, provider, "
                "settings_json, created_at) VALUES (?, ?, ?, ?, ?, 1024, 768, 'text_to_image', 'test', '{}', ?)",
                (
                    image_id,
                    user_id,
                    f"job-{index}",
                    main.public_url(path, user_id),
                    main.public_url(thumb, user_id),
                    f"2026-07-11T12:{index:02d}:00+00:00",
                ),
            )

    result = main.optimize_gallery_storage_for_user(user_id, keep_recent=10)
    assert result["optimized"] == 2
    assert result["errors"] == 0
    assert result["bytes_after"] < result["bytes_before"]

    with main.db() as conn:
        rows = conn.execute(
            "SELECT id, url, width, height, storage_tier FROM images WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,),
        ).fetchall()
    assert all(row["storage_tier"] == "original" for row in rows[:10])
    assert all(row["storage_tier"] == "optimized" for row in rows[10:])
    assert all(row["url"].split("?", 1)[0].endswith("_archive.webp") for row in rows[10:])
    assert all(max(row["width"], row["height"]) <= 768 for row in rows[10:])
    assert not (main.MEDIA / "img-00.png").exists()
    assert not (main.MEDIA / "img-01.png").exists()

    repeated = main.optimize_gallery_storage_for_user(user_id, keep_recent=10)
    assert repeated["checked"] == 0
    assert repeated["optimized"] == 0


def test_missing_thumbnail_is_rebuilt_from_available_archive(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "gallery.sqlite3")
    monkeypatch.setattr(main, "MEDIA", tmp_path / "media")
    main.MEDIA.mkdir()
    main.init_db()

    source = main.MEDIA / "available_archive.webp"
    Image.new("RGB", (900, 600), "navy").save(source, "WEBP", quality=86)
    with main.db() as conn:
        conn.execute(
            "INSERT INTO users (id, language, role, created_at, last_login_at) VALUES ('repair-user', 'ru', 'user', '2026-01-01', '2026-01-01')"
        )
        conn.execute(
            "INSERT INTO images (id, user_id, job_id, url, thumbnail_url, width, height, mode, provider, settings_json, created_at) "
            "VALUES ('repair-image', 'repair-user', 'repair-job', ?, '/api/media/missing_thumb.webp?userId=repair-user', 900, 600, 'text_to_image', 'test', '{}', '2026-07-11')",
            (main.public_url(source, "repair-user"),),
        )

    result = main.repair_missing_gallery_thumbnails()

    assert result == {"checked": 1, "repaired": 1, "unrecoverable": 0, "errors": 0}
    with main.db() as conn:
        row = conn.execute("SELECT thumbnail_url FROM images WHERE id = 'repair-image'").fetchone()
    assert row["thumbnail_url"].endswith("available_archive_thumb.webp?userId=repair-user")
    assert (main.MEDIA / "available_archive_thumb.webp").is_file()


def test_missing_custom_avatar_falls_back_to_preset(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "gallery.sqlite3")
    monkeypatch.setattr(main, "MEDIA", tmp_path / "media")
    main.MEDIA.mkdir()
    main.init_db()
    with main.db() as conn:
        conn.execute(
            "INSERT INTO users (id, language, role, avatar_url, created_at, last_login_at) "
            "VALUES ('avatar-user', 'ru', 'user', '/media/avatars/lost.jpg', '2026-01-01', '2026-01-01')"
        )

    result = main.repair_missing_user_avatars()

    assert result == {"checked": 1, "repaired": 1}
    with main.db() as conn:
        row = conn.execute("SELECT avatar_url, avatar_preset FROM users WHERE id = 'avatar-user'").fetchone()
    assert row["avatar_preset"] in main.AVATAR_PRESET_IDS
    assert row["avatar_url"] == f"/avatars/{row['avatar_preset']}.webp"


def test_missing_source_thumbnail_is_repaired_without_replacing_row(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "gallery.sqlite3")
    monkeypatch.setattr(main, "MEDIA", tmp_path / "media")
    main.MEDIA.mkdir()
    main.init_db()
    buffer = BytesIO()
    Image.new("RGB", (40, 30), "purple").save(buffer, "PNG")
    data_url = "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")
    settings = json.dumps({"mode": "image_to_image", "provider": "comfyui", "prompt": "repair", "inputImage1": data_url})
    with main.db() as conn:
        conn.execute(
            "INSERT INTO users (id, language, role, created_at, last_login_at) VALUES ('source-user', 'ru', 'user', '2026-01-01', '2026-01-01')"
        )
        conn.execute(
            "INSERT INTO jobs (id, user_id, mode, provider, status, settings_json, created_at) "
            "VALUES ('source-job', 'source-user', 'image_to_image', 'comfyui', 'completed', ?, '2026-01-01')",
            (settings,),
        )
        conn.execute(
            "INSERT INTO images (id, user_id, job_id, url, thumbnail_url, width, height, mode, provider, settings_json, created_at) "
            "VALUES ('source-image', 'source-user', 'source-job', '/api/media/result.webp', '/api/media/result-thumb.webp', 40, 30, 'image_to_image', 'comfyui', ?, '2026-01-01')",
            (settings,),
        )
        conn.execute(
            "INSERT INTO image_sources (id, image_id, user_id, source_kind, role, slot_index, thumb_url, is_favorite, availability_status, created_at) "
            "VALUES ('stable-source-id', 'source-image', 'source-user', 'upload', 'base', 1, '/api/media/missing.webp', 1, 'missing', '2026-01-01')"
        )

    result = main.repair_unavailable_image_sources_from_jobs("source-user")

    assert result == {"checked": 1, "repaired": 1, "unrecoverable": 0, "errors": 0}
    with main.db() as conn:
        row = conn.execute("SELECT * FROM image_sources WHERE id = 'stable-source-id'").fetchone()
    assert row["availability_status"] == "available"
    assert row["is_favorite"] == 1
    assert row["thumb_url"].endswith(".webp?userId=source-user")
    assert main.local_media_path_from_url(row["thumb_url"]).is_file()


def test_gallery_original_history_rewrite_is_structured_and_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "gallery.sqlite3")
    monkeypatch.setattr(main, "MEDIA", tmp_path / "media")
    main.MEDIA.mkdir()
    main.init_db()
    old_url = "/api/media/legacy.png?userId=archive-user"
    settings = json.dumps(
        {
            "resultUrl": old_url,
            "nested": {"inputImage1": old_url},
            "workflowImage": "legacy.png",
            "note": "legacy.png is descriptive text, not a media URL",
        }
    )
    with main.db() as conn:
        conn.execute(
            "INSERT INTO users (id, language, role, created_at, last_login_at) "
            "VALUES ('archive-user', 'ru', 'user', '2026-01-01', '2026-01-01')"
        )
        conn.execute(
            "INSERT INTO jobs (id, user_id, mode, provider, status, settings_json, created_at) "
            "VALUES ('archive-job', 'archive-user', 'image_to_image', 'comfyui', 'completed', ?, '2026-01-01')",
            (settings,),
        )

    first = gallery_original_migrate.rewrite_migrated_settings({"legacy.png": "legacy.webp"})
    second = gallery_original_migrate.rewrite_migrated_settings({"legacy.png": "legacy.webp"})

    assert first == {"rows": 1, "references": 3, "jobs": 1, "images": 0}
    assert second == {"rows": 0, "references": 0, "jobs": 0, "images": 0}
    with main.db() as conn:
        stored = json.loads(conn.execute("SELECT settings_json FROM jobs WHERE id = 'archive-job'").fetchone()[0])
    assert stored["resultUrl"] == "/api/media/legacy.webp?userId=archive-user"
    assert stored["nested"]["inputImage1"] == "/api/media/legacy.webp?userId=archive-user"
    assert stored["workflowImage"] == "legacy.webp"
    assert stored["note"] == "legacy.png is descriptive text, not a media URL"
