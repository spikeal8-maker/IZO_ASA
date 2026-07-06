"""Live Feed MVP tests. Temp SQLite; no live DB.

Security coverage: publish requires trusted session and image ownership;
reactions require session; public feed never leaks hidden prompts; feed media
is served only for published items; init_db stays idempotent with feed tables.
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from PIL import Image

import feed_media_audit
import feed_media_migrate
import job_media_ref_repair
import media_cleanup_apply
import media_health_check
import media_cleanup_plan
import media_storage_audit
import main
import user_gallery_link_audit


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "feed_v2_test.sqlite3"
    monkeypatch.setattr(main, "DB_PATH", db_file)
    monkeypatch.setattr(main, "TRUSTED_COOKIE_SECURE", False)
    monkeypatch.setattr(main, "MEDIA", tmp_path / "media")
    (tmp_path / "media").mkdir()
    main.init_db()
    return db_file


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def make_user(iuid: str, legacy: str, display_name: str = "Автор Теста") -> str:
    with main.db() as conn:
        conn.execute(
            "INSERT INTO users (id, internal_user_id, role, token_balance, language, display_name, created_at, last_login_at) "
            "VALUES (?, ?, 'user', 50, 'ru', ?, '2026-01-01', '2026-01-01')",
            (legacy, iuid, display_name),
        )
    return main.create_auth_session(iuid, legacy, provider="telegram", platform="telegram_mini_app")["session_token"]


def make_image(image_id: str, legacy_user: str, prompt: str = "секретный промпт про маяк") -> None:
    media_file = main.MEDIA / f"{image_id}.png"
    image = Image.new("RGB", (1200, 800), (70, 120, 180))
    pixels = image.load()
    for y in range(800):
        for x in range(1200):
            pixels[x, y] = ((x * 7 + y * 3) % 256, (x * 5 + y * 11) % 256, (x * 13 + y * 2) % 256)
    image.save(media_file, "PNG")
    thumb = main.MEDIA / f"{image_id}_thumb.webp"
    image.thumbnail((512, 512))
    image.save(thumb, "WEBP", quality=88)
    with main.db() as conn:
        conn.execute(
            "INSERT INTO images (id, user_id, job_id, url, thumbnail_url, width, height, mode, provider, "
            "prompt_original, settings_json, created_at) "
            "VALUES (?, ?, 'job-x', ?, ?, 1200, 800, 'text_to_image', 'comfyui', ?, '{\"seed\": 42}', '2026-07-03')",
            (image_id, legacy_user, f"/api/media/{image_id}.png?userId={legacy_user}",
             f"/api/media/{image_id}_thumb.webp?userId={legacy_user}", prompt),
        )


def publish(client: TestClient, token: str, image_id: str, visibility: str = "open", title: str = "Маяк") -> dict:
    r = client.post(
        "/api/feed/publications",
        json={"imageId": image_id, "title": title, "promptVisibility": visibility, "allowRecreate": True},
        headers=bearer(token),
    )
    assert r.status_code == 200, r.text
    return r.json()["publication"]


def test_publish_requires_session(temp_db):
    with TestClient(main.app) as client:
        r = client.post("/api/feed/publications", json={"imageId": "img-1", "title": "X"})
        assert r.status_code == 401


def test_publish_foreign_image_denied_and_logged(temp_db):
    with TestClient(main.app) as client:
        owner_token = make_user("iuid-owner", "web_owner")
        make_user("iuid-thief", "web_thief")
        thief_token = main.create_auth_session("iuid-thief", "web_thief", provider="web", platform="web")["session_token"]
        make_image("img-own", "web_owner")
        r = client.post(
            "/api/feed/publications",
            json={"imageId": "img-own", "title": "Чужое"},
            headers=bearer(thief_token),
        )
        assert r.status_code == 404
        with main.db() as conn:
            events = conn.execute(
                "SELECT COUNT(*) AS c FROM security_events WHERE event_type = 'feed_publish_denied'"
            ).fetchone()["c"]
        assert events == 1
        # Владелец публикует успешно.
        pub = publish(client, owner_token, "img-own")
        assert pub["title"] == "Маяк"
        assert pub["author_name"] == "Автор Теста"


def test_feed_public_read_and_prompt_visibility(temp_db):
    with TestClient(main.app) as client:
        token = make_user("iuid-a", "web_a")
        make_image("img-open", "web_a", prompt="открытый промпт")
        make_image("img-hidden", "web_a", prompt="секрет")
        publish(client, token, "img-open", visibility="open", title="Открытая")
        publish(client, token, "img-hidden", visibility="hidden", title="Скрытая")
    # Новый клиент без сессии: лента читается, hidden-промпт не утёк.
    with TestClient(main.app) as anon:
        r = anon.get("/api/feed?type=new")
        assert r.status_code == 200
        items = {i["title"]: i for i in r.json()["items"]}
        assert items["Открытая"]["prompt"] == "открытый промпт"
        assert items["Скрытая"]["prompt"] is None
        assert "секрет" not in r.text
        assert items["Открытая"]["is_liked_by_me"] is False
        assert items["Открытая"]["resolution"] == "1200×800"
        assert items["Открытая"]["seed"] == 42
        assert items["Открытая"]["media_status"] == "ready"
        assert items["Открытая"]["native_aspect_ratio"] == "3:2"
        assert items["Открытая"]["orientation"] == "landscape"


def test_reactions_require_session_and_toggle(temp_db):
    with TestClient(main.app) as client:
        token = make_user("iuid-b", "web_b")
        make_image("img-b", "web_b")
        pub = publish(client, token, "img-b")
        # Без сессии — 401.
        assert client.post(f"/api/feed/publications/{pub['id']}/like").status_code == 401
        # С сессией: like + save ставятся и снимаются, счётчики честные.
        r = client.post(f"/api/feed/publications/{pub['id']}/like", headers=bearer(token))
        assert r.status_code == 200
        assert r.json()["publication"]["like_count"] == 1
        assert r.json()["publication"]["is_liked_by_me"] is True
        # Повторный лайк не дублирует (PK-защита).
        r = client.post(f"/api/feed/publications/{pub['id']}/like", headers=bearer(token))
        assert r.json()["publication"]["like_count"] == 1
        r = client.delete(f"/api/feed/publications/{pub['id']}/like", headers=bearer(token))
        assert r.json()["publication"]["like_count"] == 0
        r = client.post(f"/api/feed/publications/{pub['id']}/save", headers=bearer(token))
        assert r.json()["publication"]["save_count"] == 1
        r = client.post(f"/api/feed/publications/{pub['id']}/recreate", headers=bearer(token))
        assert r.json()["publication"]["remix_count"] == 1


def test_generate_rejects_missing_media_input_before_job_created(temp_db):
    with TestClient(main.app) as client:
        token = make_user("iuid-gen-missing", "web_gen_missing")
        with main.db() as conn:
            before_jobs = conn.execute("SELECT COUNT(*) AS c FROM jobs").fetchone()["c"]
            before_balance = conn.execute("SELECT token_balance FROM users WHERE id = 'web_gen_missing'").fetchone()[0]
        r = client.post(
            "/api/generate",
            json={
                "mode": "image_to_image",
                "provider": "comfyui",
                "prompt": "test",
                "inputImage1": "/api/media/missing-input.png?userId=web_gen_missing",
            },
            headers=bearer(token),
        )
        assert r.status_code == 400
        assert r.json()["detail"]["code"] == "input_media_missing"
        with main.db() as conn:
            after_jobs = conn.execute("SELECT COUNT(*) AS c FROM jobs").fetchone()["c"]
            after_balance = conn.execute("SELECT token_balance FROM users WHERE id = 'web_gen_missing'").fetchone()[0]
        assert after_jobs == before_jobs
        assert after_balance == before_balance


def test_generate_rejects_foreign_media_input(temp_db):
    with TestClient(main.app) as client:
        make_user("iuid-gen-owner", "web_gen_owner")
        make_user("iuid-gen-other", "web_gen_other")
        make_image("img-gen-owner", "web_gen_owner")
        with main.db() as conn:
            before_jobs = conn.execute("SELECT COUNT(*) AS c FROM jobs").fetchone()["c"]
        r = client.post(
            "/api/generate",
            json={
                "mode": "image_to_image",
                "provider": "comfyui",
                "prompt": "test",
                "inputImage1": "/api/media/img-gen-owner.png?userId=web_gen_owner",
            },
            headers=bearer(main.create_auth_session("iuid-gen-other", "web_gen_other", provider="web", platform="web")["session_token"]),
        )
        assert r.status_code == 400
        assert r.json()["detail"]["code"] == "input_media_unavailable"
        with main.db() as conn:
            after_jobs = conn.execute("SELECT COUNT(*) AS c FROM jobs").fetchone()["c"]
        assert after_jobs == before_jobs


def test_feed_media_served_only_for_published(temp_db):
    with TestClient(main.app) as client:
        token = make_user("iuid-c", "web_c")
        make_image("img-c", "web_c")
        pub = publish(client, token, "img-c")
    with TestClient(main.app) as anon:
        # Публичный доступ к опубликованному файлу (без сессии, без владения).
        r = anon.get(f"/api/feed/media/{pub['id']}")
        assert r.status_code == 200
        assert r.headers["content-type"] == "image/webp"
        r = anon.get(f"/api/feed/media/{pub['id']}?thumb=1")
        assert r.status_code == 200
        assert r.headers["content-type"] == "image/webp"
        r = anon.get(f"/api/feed/media/{pub['id']}?variant=thumb")
        assert r.status_code == 200
        assert r.headers["content-type"] == "image/webp"
        # Несуществующая публикация — 404.
        assert anon.get("/api/feed/media/nope").status_code == 404
        # Приватный /api/media как был: без сессии чужой файл не отдаётся
        # (легаси-фолбэк ?userId в проде закрыт trusted-сессией — см. gallery).


def test_gallery_delete_retires_feed_publication_and_variants(temp_db):
    with TestClient(main.app) as client:
        token = make_user("iuid-delete-feed", "web_delete_feed")
        make_image("img-delete-feed", "web_delete_feed")
        pub = publish(client, token, "img-delete-feed")
        with main.db() as conn:
            row = conn.execute(
                "SELECT feed_thumb_name, feed_large_name FROM feed_publications WHERE id = ?",
                (pub["id"],),
            ).fetchone()
        thumb = main.MEDIA / row["feed_thumb_name"]
        large = main.MEDIA / row["feed_large_name"]
        assert thumb.exists()
        assert large.exists()

        r = client.delete("/api/gallery/img-delete-feed", headers=bearer(token))
        assert r.status_code == 200
        assert not thumb.exists()
        assert not large.exists()
        assert client.get(f"/api/feed/media/{pub['id']}?variant=thumb").status_code == 404
        feed = client.get("/api/feed?type=new")
        assert feed.status_code == 200
        assert all(item["id"] != pub["id"] for item in feed.json()["items"])
        with main.db() as conn:
            row = conn.execute(
                "SELECT status, feed_thumb_name, feed_large_name, media_ready_at, media_error "
                "FROM feed_publications WHERE id = ?",
                (pub["id"],),
            ).fetchone()
        assert row["status"] == "hidden"
        assert row["feed_thumb_name"] is None
        assert row["feed_large_name"] is None
        assert row["media_ready_at"] is None
        assert row["media_error"] == "source_image_deleted"


def test_feed_media_audit_flags_published_deleted_source(temp_db):
    with TestClient(main.app) as client:
        token = make_user("iuid-audit-deleted", "web_audit_deleted")
        make_image("img-audit-deleted", "web_audit_deleted")
        pub = publish(client, token, "img-audit-deleted")
        with main.db() as conn:
            conn.execute(
                "UPDATE images SET deleted_at = '2026-07-07T00:00:00+00:00' WHERE id = ?",
                ("img-audit-deleted",),
            )

    report = feed_media_audit.audit_feed_media(item_limit=10)
    assert report["published_deleted_sources"] == [
        {"id": pub["id"], "image_id": "img-audit-deleted", "deleted_at": "2026-07-07T00:00:00+00:00"}
    ]
    assert "published_deleted_sources" in report["issues"]


def test_feed_media_audit_flags_published_missing_source(temp_db):
    with TestClient(main.app) as client:
        token = make_user("iuid-audit-missing", "web_audit_missing")
        make_image("img-audit-missing", "web_audit_missing")
        pub = publish(client, token, "img-audit-missing")
        with main.db() as conn:
            conn.execute("DELETE FROM images WHERE id = ?", ("img-audit-missing",))

    report = feed_media_audit.audit_feed_media(item_limit=10)
    assert report["published_missing_sources"] == [{"id": pub["id"], "image_id": "img-audit-missing"}]
    assert "published_missing_sources" in report["issues"]


def test_media_health_check_rolls_up_nested_issues(temp_db):
    with TestClient(main.app) as client:
        token = make_user("iuid-health", "web_health")
        make_image("img-health", "web_health")
        publish(client, token, "img-health")
    ok = media_health_check.run_media_health_check(item_limit=10)
    assert ok["status"] == "ok", ok["issues"]
    assert ok["issues"] == []

    with main.db() as conn:
        conn.execute(
            "UPDATE images SET deleted_at = '2026-07-07T00:00:00+00:00' WHERE id = ?",
            ("img-health",),
        )
    broken = media_health_check.run_media_health_check(item_limit=10)
    assert broken["status"] == "issues"
    assert "feed:published_deleted_sources" in broken["issues"]


def test_publish_creates_feed_variants_not_original_fallback(temp_db):
    with TestClient(main.app) as client:
        token = make_user("iuid-d", "web_d")
        make_image("img-d", "web_d")
        original = main.MEDIA / "img-d.png"
        pub = publish(client, token, "img-d")
        assert pub["image_url"].endswith(f"/api/feed/media/{pub['id']}?variant=large")
        assert pub["thumbnail_url"].endswith(f"/api/feed/media/{pub['id']}?variant=thumb")
        with main.db() as conn:
            row = conn.execute(
                "SELECT feed_thumb_name, feed_large_name, feed_thumb_bytes, feed_large_bytes, "
                "native_aspect_ratio, orientation, source_type, display_policy "
                "FROM feed_publications WHERE id = ?",
                (pub["id"],),
            ).fetchone()
        thumb = main.MEDIA / row["feed_thumb_name"]
        large = main.MEDIA / row["feed_large_name"]
        assert thumb.exists()
        assert large.exists()
        assert thumb.suffix == ".webp"
        assert large.suffix == ".webp"
        assert row["feed_thumb_bytes"] == thumb.stat().st_size
        assert row["feed_large_bytes"] == large.stat().st_size
        assert row["feed_large_name"] != original.name
        with Image.open(large) as large_image:
            assert max(large_image.size) <= main.FEED_LARGE_MAX_SIDE
        with Image.open(thumb) as thumb_image:
            assert max(thumb_image.size) <= main.FEED_THUMB_MAX_SIDE
        assert row["native_aspect_ratio"] == "3:2"
        assert row["orientation"] == "landscape"
        assert row["source_type"] == "text_to_image"
        assert row["display_policy"] == "preserve_aspect_ratio"


def test_feed_ignores_published_without_ready_media(temp_db):
    with TestClient(main.app) as client:
        token = make_user("iuid-ready", "web_ready")
        make_image("img-ready", "web_ready")
        pub = publish(client, token, "img-ready", title="Готовая")
        with main.db() as conn:
            conn.execute(
                "UPDATE feed_publications SET media_ready_at = NULL, media_error = 'test missing media' WHERE id = ?",
                (pub["id"],),
            )
        r = client.get("/api/feed?type=new")
        assert r.status_code == 200
        assert all(item["id"] != pub["id"] for item in r.json()["items"])
        assert client.get(f"/api/feed/media/{pub['id']}?variant=thumb").status_code == 404


def test_feed_media_migrate_filters_targeted_rows(temp_db):
    with TestClient(main.app) as client:
        token = make_user("iuid-migrate", "web_migrate")
        make_image("img-migrate-ready", "web_migrate")
        make_image("img-migrate-missing", "web_migrate")
        ready_pub = publish(client, token, "img-migrate-ready", title="Ready")
        missing_pub = publish(client, token, "img-migrate-missing", title="Missing")
        with main.db() as conn:
            conn.execute(
                "UPDATE images SET url = ? WHERE id = ?",
                ("/api/media/does-not-exist.png?userId=web_migrate", "img-migrate-missing"),
            )
            conn.execute(
                "UPDATE feed_publications SET status = 'media_missing', media_ready_at = NULL WHERE id = ?",
                (missing_pub["id"],),
            )

    one = feed_media_migrate.migrate_feed_media(apply=False, publication_ids=[ready_pub["id"]])
    assert one["filters"]["publication_ids"] == [ready_pub["id"]]
    assert [item["id"] for item in one["items"]] == [ready_pub["id"]]
    assert one["skipped"] == 1
    assert one["media_missing"] == 0

    missing = feed_media_migrate.migrate_feed_media(apply=False, only_missing=True)
    assert missing["filters"]["only_missing"] is True
    assert [item["id"] for item in missing["items"]] == [missing_pub["id"]]
    assert missing["media_missing"] == 1


def test_media_storage_audit_reports_unreferenced_files(temp_db):
    make_user("iuid-storage", "web_storage")
    make_image("img-storage", "web_storage")
    orphan = main.MEDIA / "orphan-upload.tmp"
    orphan.write_bytes(b"unused")

    report = media_storage_audit.audit_media_storage(item_limit=10)
    assert report["active_referenced"]["count"] >= 2
    assert report["missing_active_refs"] == []
    assert any(item["file"] == "orphan-upload.tmp" for item in report["largest_unreferenced"])
    assert report["unreferenced"]["bytes"] >= len(b"unused")


def test_media_storage_audit_protects_job_settings_refs(temp_db):
    make_user("iuid-job-ref", "web_job_ref")
    make_image("img-job-ref", "web_job_ref")
    ref = main.MEDIA / "job-reference.png"
    ref.write_bytes(b"reference")
    with main.db() as conn:
        conn.execute(
            "INSERT INTO jobs (id, user_id, mode, provider, status, prompt_original, settings_json, created_at) "
            "VALUES ('job-ref', 'web_job_ref', 'image_to_image', 'comfyui', 'completed', 'prompt', ?, '2026-07-07')",
            ('{"inputImage": "job-reference.png", "nested": {"url": "/api/media/job-reference.png?userId=web_job_ref"}}',),
        )

    report = media_storage_audit.audit_media_storage(item_limit=20)
    assert report["job_referenced"]["count"] >= 1
    assert all(item["file"] != "job-reference.png" for item in report["largest_unreferenced"])


def test_job_media_ref_repair_moves_missing_inputs_to_diagnostics(temp_db):
    make_user("iuid-job-repair", "web_job_repair")
    existing = main.MEDIA / "existing-reference.png"
    existing.write_bytes(b"reference")
    with main.db() as conn:
        conn.execute(
            "INSERT INTO jobs (id, user_id, mode, provider, status, prompt_original, settings_json, created_at) "
            "VALUES ('job-repair', 'web_job_repair', 'edit', 'comfyui', 'completed', 'prompt', ?, '2026-07-07')",
            (
                '{"inputImage1": "/api/media/missing-reference.png?userId=web_job_repair", '
                '"inputImages": [{"index": 1, "role": "base", "image": "/api/media/missing-reference.png?userId=web_job_repair"}, '
                '{"index": 2, "role": "style", "image": "/api/media/existing-reference.png?userId=web_job_repair"}]}',
            ),
        )

    dry = job_media_ref_repair.repair_job_media_refs(apply=False)
    assert dry["jobs_with_missing_refs"] == 1
    applied = job_media_ref_repair.repair_job_media_refs(apply=True)
    assert applied["updated_jobs"] == 1
    with main.db() as conn:
        settings = conn.execute("SELECT settings_json FROM jobs WHERE id = 'job-repair'").fetchone()[0]
    payload = json.loads(settings)
    assert payload["inputImage1"] is None
    assert payload["inputImages"][0]["image"] is None
    assert payload["inputImages"][1]["image"].endswith("existing-reference.png?userId=web_job_repair")
    assert payload["_media_ref_status"]["missing"][0]["file"] == "missing-reference.png"
    report = media_storage_audit.audit_media_storage(item_limit=10)
    assert report["missing_active_refs"] == []


def test_media_cleanup_plan_excludes_protected_kinds(temp_db):
    make_user("iuid-cleanup", "web_cleanup")
    make_image("img-cleanup", "web_cleanup")
    (main.MEDIA / "orphan-original.png").write_bytes(b"original")
    (main.MEDIA / "seed_izo_fake.png").write_bytes(b"seed")
    feed_dir = main.MEDIA / "feed"
    feed_dir.mkdir(exist_ok=True)
    (feed_dir / "orphan-feed.webp").write_bytes(b"feed")

    plan = media_cleanup_plan.build_cleanup_plan(
        kinds={"original_or_input", "seed_original", "feed_variant"},
        item_limit=20,
    )
    files = {item["file"] for item in plan["candidates"]}
    assert "orphan-original.png" in files
    assert "seed_izo_fake.png" not in files
    assert "feed/orphan-feed.webp" not in files
    assert plan["deletes_files"] is False
    assert plan["ignored_requested_protected_kinds"] == ["feed_variant", "seed_original"]


def test_media_cleanup_apply_deletes_only_safe_candidates(temp_db):
    make_user("iuid-cleanup-apply", "web_cleanup_apply")
    make_image("img-cleanup-apply", "web_cleanup_apply")
    orphan = main.MEDIA / "orphan-apply.png"
    seed = main.MEDIA / "seed_izo_keep.png"
    feed_dir = main.MEDIA / "feed"
    feed_dir.mkdir(exist_ok=True)
    feed = feed_dir / "keep-feed.webp"
    orphan.write_bytes(b"delete")
    seed.write_bytes(b"seed")
    feed.write_bytes(b"feed")

    result = media_cleanup_apply.apply_cleanup(
        apply=True,
        kinds={"original_or_input", "seed_original", "feed_variant"},
        item_limit=20,
    )
    deleted_files = {item["file"] for item in result["deleted"]}
    assert "orphan-apply.png" in deleted_files
    assert not orphan.exists()
    assert seed.exists()
    assert feed.exists()
    assert result["deletes_files"] is True


def test_user_gallery_link_audit_separates_active_and_deleted_missing_files(temp_db):
    make_user("iuid-links", "web_links")
    make_image("img-links-active", "web_links")
    make_image("img-links-deleted", "web_links")
    with main.db() as conn:
        conn.execute(
            "UPDATE images SET deleted_at = '2026-07-07T00:00:00+00:00' WHERE id = ?",
            ("img-links-deleted",),
        )
    (main.MEDIA / "img-links-deleted.png").unlink()
    (main.MEDIA / "img-links-deleted_thumb.webp").unlink()

    report = user_gallery_link_audit.audit_user_gallery_links(item_limit=10)
    assert report["totals"]["missing_user_images"] == 0
    assert report["totals"]["active_missing_file_refs"] == 0
    assert report["totals"]["deleted_missing_file_refs"] == 2
    assert report["issues"] == []


def test_init_db_idempotent_with_feed_tables(temp_db):
    main.init_db()
    main.init_db()
    with main.db() as conn:
        for table in ("feed_publications", "feed_reactions"):
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchone()
            assert row is not None


def test_init_db_has_feed_media_contract_columns(temp_db):
    main.init_db()
    with main.db() as conn:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(feed_publications)").fetchall()}
    expected = {
        "feed_thumb_name",
        "feed_large_name",
        "feed_thumb_width",
        "feed_thumb_height",
        "feed_thumb_bytes",
        "feed_large_width",
        "feed_large_height",
        "feed_large_bytes",
        "media_ready_at",
        "media_error",
        "native_aspect_ratio",
        "orientation",
        "source_type",
        "source_label",
        "display_policy",
        "category",
        "remix_policy",
        "tags_json",
        "updated_at",
    }
    assert expected <= columns


def test_init_db_seeds_editorial_user_for_demo_feed(temp_db):
    main.init_db()
    with main.db() as conn:
        row = conn.execute(
            "SELECT id, internal_user_id, display_name, gallery_enabled FROM users WHERE id = 'seed_editorial'"
        ).fetchone()
    assert row is not None
    assert row["internal_user_id"] == "seed_editorial"
    assert row["display_name"] == "Выбор редакции"
    assert row["gallery_enabled"] == 0
