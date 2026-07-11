from __future__ import annotations

from PIL import Image

import main


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
