"""Feed media continuity tests kept separate from the primary API contract suite."""
from fastapi.testclient import TestClient
from test_support.browser_client import BrowserTestClient

import feed_media_audit
import gallery_original_audit
import main
import media_storage_audit
import user_gallery_link_audit
from test_feed_v2 import (
    bearer,
    make_image,
    make_user,
    make_video,
    publish,
    temp_db,
    wait_for_video_publication,
)


def test_feed_watermark_uses_canonical_brand_domain():
    assert main.feed_downloads.BRAND_NAME == "ИЗО АСА"
    assert main.feed_downloads.BRAND_DOMAIN == "izo.alikinas.ru"
    assert main.feed_downloads.WATERMARK_VERSION == "v2"
    assert main.feed_downloads.render_feed_download.__kwdefaults__["domain"] == "izo.alikinas.ru"
    assert main.feed_downloads.render_video_watermark_overlay.__kwdefaults__["domain"] == "izo.alikinas.ru"


def test_feed_video_download_is_branded_cached_and_deleted_with_publication(temp_db, monkeypatch):
    source = main.MEDIA / "synthetic-branded-source.mp4"
    main._run_feed_ffmpeg(
        [
            "-f", "lavfi", "-i", "testsrc=size=160x96:rate=10",
            "-t", "1", "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-threads", "1", str(source),
        ],
        timeout=30,
    )
    assets = main.create_feed_video_assets(
        "synthetic-branded-assets",
        source,
        width=160,
        height=96,
        duration_seconds=1,
        has_audio=False,
    )
    monkeypatch.setattr(main, "FEED_VIDEO_PUBLICATION_ENABLED", True)
    monkeypatch.setattr(main, "create_feed_video_assets", lambda *_args, **_kwargs: assets)

    with BrowserTestClient(main.app) as client:
        token = make_user("iuid-video-download", "web_video_download", "Автор MP4")
        make_video("vid-feed-download", "web_video_download")
        accepted = client.post(
            "/api/feed/publications",
            json={"videoId": "vid-feed-download", "title": "Видео для скачивания"},
            headers=bearer(token),
        )
        assert accepted.status_code == 202, accepted.text
        publication_id = accepted.json()["publication"]["id"]
        wait_for_video_publication(client, token, publication_id, expected_status="published")
        legacy_path = main.MEDIA / main.feed_downloads.video_download_name(publication_id, version="v1")
        legacy_path.write_bytes(b"legacy-watermark-cache")

        first = client.get(f"/api/feed/publications/{publication_id}/download?format=mp4")
        assert first.status_code == 200, first.text
        assert first.headers["content-type"].startswith("video/mp4")
        assert first.headers["x-izo-watermark-version"] == main.feed_downloads.WATERMARK_VERSION
        assert first.content[4:8] == b"ftyp"
        cached_path = main.MEDIA / main.feed_downloads.video_download_name(publication_id)
        assert cached_path.is_file()
        assert not legacy_path.exists()
        first_mtime = cached_path.stat().st_mtime_ns

        second = client.get(f"/api/feed/publications/{publication_id}/download?format=mp4")
        assert second.status_code == 200
        assert cached_path.stat().st_mtime_ns == first_mtime
        audit = feed_media_audit.audit_feed_media(item_limit=20)
        assert all(
            item["file"] != main.feed_downloads.video_download_name(publication_id)
            for item in audit["orphan_feed_files"]
        )
        storage_audit = media_storage_audit.audit_media_storage(item_limit=20)
        assert all(
            item["file"] != main.feed_downloads.video_download_name(publication_id)
            for item in storage_audit["largest_unreferenced"]
        )
        legacy_path.write_bytes(b"legacy-watermark-cache")

        deleted = client.delete(f"/api/feed/publications/{publication_id}", headers=bearer(token))
        assert deleted.status_code == 200
        assert not cached_path.exists()
        assert not legacy_path.exists()


def test_feed_media_audit_allows_published_copy_after_source_deletion(temp_db):
    with BrowserTestClient(main.app) as client:
        token = make_user("iuid-audit-deleted", "web_audit_deleted")
        make_image("img-audit-deleted", "web_audit_deleted")
        pub = publish(client, token, "img-audit-deleted")
        with main.db() as conn:
            conn.execute(
                "UPDATE images SET deleted_at = '2026-07-07T00:00:00+00:00' WHERE id = ?",
                ("img-audit-deleted",),
            )

    report = feed_media_audit.audit_feed_media(item_limit=10)
    assert report["published_deleted_sources"] == []
    assert report["published_detached_sources"] == [
        {
            "id": pub["id"],
            "image_id": "img-audit-deleted",
            "reason": "source_deleted",
            "deleted_at": "2026-07-07T00:00:00+00:00",
        }
    ]
    assert "published_deleted_sources" not in report["issues"]
    assert "published_missing_sources" not in report["issues"]
    assert "missing_files" not in report["issues"]


def test_feed_media_audit_allows_published_copy_after_source_row_removal(temp_db):
    with BrowserTestClient(main.app) as client:
        token = make_user("iuid-audit-missing", "web_audit_missing")
        make_image("img-audit-missing", "web_audit_missing")
        pub = publish(client, token, "img-audit-missing")
        with main.db() as conn:
            conn.execute("DELETE FROM images WHERE id = ?", ("img-audit-missing",))

    report = feed_media_audit.audit_feed_media(item_limit=10)
    assert report["published_missing_sources"] == []
    assert report["published_detached_sources"] == [
        {"id": pub["id"], "image_id": "img-audit-missing", "reason": "source_row_missing"}
    ]
    assert "published_deleted_sources" not in report["issues"]
    assert "published_missing_sources" not in report["issues"]
    assert "missing_files" not in report["issues"]


def test_media_storage_audit_does_not_require_removed_source_library_thumb(temp_db):
    make_user("iuid-storage-source", "web_storage_source")
    make_image("img-storage-source", "web_storage_source")
    with main.db() as conn:
        conn.execute(
            """
            INSERT INTO image_sources (
                id, image_id, user_id, source_kind, role, slot_index, thumb_url,
                created_at, library_deleted_at
            ) VALUES (?, ?, ?, 'upload', 'mask', 2, ?, ?, ?)
            """,
            (
                "source-library-removed",
                "img-storage-source",
                "web_storage_source",
                "/api/media/source-library-removed.webp?userId=web_storage_source",
                "2026-07-07T00:00:00+00:00",
                "2026-07-08T00:00:00+00:00",
            ),
        )

    report = media_storage_audit.audit_media_storage(item_limit=10)
    assert report["missing_active_refs"] == []
    assert report["issues"] == []


def test_gallery_audits_accept_exact_seed_feed_backing_but_keep_public_file_guard(temp_db):
    with BrowserTestClient(main.app) as client:
        token = make_user("iuid-seed-backing", "web_seed_backing")
        make_image("img-seed-backing", "web_seed_backing")
        pub = publish(client, token, "img-seed-backing", title="Демо-публикация")
    with main.db() as conn:
        feed_url = f"/api/feed/media/{pub['id']}?variant=large"
        conn.execute(
            "UPDATE images SET user_id = 'seed_editorial', url = ?, thumbnail_url = ? WHERE id = ?",
            (feed_url, feed_url, "img-seed-backing"),
        )
        conn.execute(
            "UPDATE jobs SET user_id = 'seed_editorial' WHERE id = ?",
            ("job-img-seed-backing",),
        )
    (main.MEDIA / "img-seed-backing.png").unlink()
    (main.MEDIA / "img-seed-backing_thumb.webp").unlink()

    originals = gallery_original_audit.audit_gallery_originals(item_limit=10)
    assert originals["issues"] == []
    assert originals["totals"]["feed_backed_originals"] == 1
    assert originals["feed_backed_originals"][0]["publication_id"] == pub["id"]

    links = user_gallery_link_audit.audit_user_gallery_links(item_limit=10)
    assert links["issues"] == []
    assert links["totals"]["feed_backed_active_images"] == 1
    assert links["totals"]["active_missing_file_refs"] == 0

    with main.db() as conn:
        feed_name = conn.execute(
            "SELECT feed_large_name FROM feed_publications WHERE id = ?",
            (pub["id"],),
        ).fetchone()["feed_large_name"]
    (main.MEDIA / feed_name).unlink()
    broken = gallery_original_audit.audit_gallery_originals(item_limit=10)
    assert broken["issues"] == ["missing_files"]
    assert broken["missing_files"][0]["reason"] == "feed_backing_missing"
