from __future__ import annotations

from PIL import Image
from fastapi.testclient import TestClient

import main


def setup_gallery_db(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "gallery-phase1.sqlite3")
    monkeypatch.setattr(main, "MEDIA", tmp_path / "media")
    main.MEDIA.mkdir()
    main.init_db()
    with main.db() as conn:
        conn.execute(
            "INSERT INTO users (id, internal_user_id, language, role, gallery_enabled, created_at, last_login_at) "
            "VALUES ('phase-user', 'phase-iuid', 'ru', 'user', 1, '2026-01-01', '2026-01-01')"
        )
        conn.execute(
            "INSERT INTO images (id, user_id, url, thumbnail_url, width, height, mode, provider, settings_json, created_at) "
            "VALUES ('phase-image', 'phase-user', '/api/media/result.webp?userId=phase-user', "
            "'/api/media/result-thumb.webp?userId=phase-user', 100, 100, 'text_to_image', 'test', '{}', '2026-01-01')"
        )


def test_source_availability_reconciliation_is_non_destructive(tmp_path, monkeypatch):
    setup_gallery_db(tmp_path, monkeypatch)
    available = main.MEDIA / "available.webp"
    Image.new("RGB", (32, 24), "green").save(available, "WEBP")
    with main.db() as conn:
        for source_id, filename in (("available", available.name), ("missing", "missing.webp")):
            conn.execute(
                "INSERT INTO image_sources (id, image_id, user_id, source_kind, role, slot_index, thumb_url, created_at) "
                "VALUES (?, 'phase-image', 'phase-user', 'upload', 'base', 1, ?, '2026-01-01')",
                (source_id, f"/api/media/{filename}?userId=phase-user"),
            )

    result = main.reconcile_image_source_availability("phase-user")
    assert result == {"checked": 2, "available": 1, "missing": 1, "changed": 2}
    with main.db() as conn:
        rows = {row["id"]: row for row in conn.execute("SELECT * FROM image_sources").fetchall()}
    assert rows["available"]["availability_status"] == "available"
    assert rows["available"]["unavailable_at"] is None
    assert rows["missing"]["availability_status"] == "missing"
    assert rows["missing"]["unavailable_at"]
    assert available.exists()


def test_active_gallery_query_uses_ordered_partial_index(tmp_path, monkeypatch):
    setup_gallery_db(tmp_path, monkeypatch)
    with main.db() as conn:
        plan = conn.execute(
            "EXPLAIN QUERY PLAN SELECT * FROM images WHERE user_id = ? AND deleted_at IS NULL "
            "ORDER BY created_at DESC, id DESC LIMIT 25",
            ("phase-user",),
        ).fetchall()
    details = " ".join(str(row["detail"]) for row in plan)
    assert "idx_images_active_user_created" in details
    assert "TEMP B-TREE" not in details


def test_primary_items_endpoint_has_small_independent_contract(tmp_path, monkeypatch):
    setup_gallery_db(tmp_path, monkeypatch)
    with main.db() as conn:
        for index in range(1, 15):
            conn.execute(
                "INSERT INTO images (id, user_id, url, thumbnail_url, width, height, mode, provider, settings_json, created_at) "
                "VALUES (?, 'phase-user', ?, ?, 100, 100, 'text_to_image', 'test', '{}', ?)",
                (
                    f"phase-image-{index}",
                    f"/api/media/result-{index}.webp?userId=phase-user",
                    f"/api/media/result-{index}-thumb.webp?userId=phase-user",
                    f"2026-01-{index + 1:02d}",
                ),
            )
    token = main.create_auth_session("phase-iuid", "phase-user", provider="web", platform="web")["session_token"]
    with TestClient(main.app) as client:
        response = client.get("/api/gallery/items?limit=12", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    payload = response.json()
    assert len(payload["items"]) == 12
    assert payload["hasMore"] is True
    assert payload["nextCursor"]
    assert "feedItems" not in payload
    assert "uploadedItems" not in payload


def test_primary_items_search_uses_fts_index(tmp_path, monkeypatch):
    setup_gallery_db(tmp_path, monkeypatch)
    with main.db() as conn:
        conn.execute(
            "UPDATE images SET prompt_original = 'космический маяк над морем', settings_json = '{\"modelProfile\":\"gpt-image-2\"}' "
            "WHERE id = 'phase-image'"
        )
    token = main.create_auth_session("phase-iuid", "phase-user", provider="web", platform="web")["session_token"]
    with TestClient(main.app) as client:
        response = client.get("/api/gallery/items?limit=12&q=маяк", headers={"Authorization": f"Bearer {token}"})
        model_response = client.get("/api/gallery/items?limit=12&q=gpt-image", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert [item["id"] for item in response.json()["items"]] == ["phase-image"]
    assert model_response.status_code == 200
    assert [item["id"] for item in model_response.json()["items"]] == ["phase-image"]
