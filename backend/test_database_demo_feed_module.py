from __future__ import annotations

import hashlib
import json
from pathlib import Path

import main
from app.database.demo_feed import restore_demo_feed_bundle


def _asset(bundle: Path, name: str, data: bytes) -> dict[str, object]:
    path = bundle / name
    path.write_bytes(data)
    return {
        "file": name,
        "target": f"feed/{name}",
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def test_demo_feed_bundle_restores_only_seed_rows_and_retires_faceless_item(tmp_path):
    main.init_db()
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    manifest = {
        "version": 1,
        "authors": [
            {
                "id": "seed_author_test",
                "internal_user_id": "seed_author_test",
                "username": "seed_test",
                "first_name": "Автор",
                "display_name": "Автор Тест",
                "language": "ru",
                "role": "user",
                "plan": "mini",
                "token_balance": 0,
                "gallery_enabled": 0,
                "avatar_url": "/avatars/avatar-001.webp",
                "avatar_preset": "avatar-001",
                "created_at": "2026-07-01T00:00:00+00:00",
                "last_login_at": "2026-07-01T00:00:00+00:00",
            }
        ],
        "items": [
            {
                "publication": {
                    "id": "seed-pub-01",
                    "image_id": "seed-img-01",
                    "internal_user_id": "seed_author_test",
                    "legacy_user_id": "seed_author_test",
                    "title": "Seed publication",
                    "prompt_visibility": "hidden",
                    "allow_recreate": 1,
                    "status": "published",
                    "created_at": "2026-07-01T00:00:00+00:00",
                    "is_seed": 1,
                    "category": "showcase",
                    "feed_thumb_name": "feed/seed-pub-01_thumb.webp",
                    "feed_large_name": "feed/seed-pub-01_large.webp",
                    "media_ready_at": "2026-07-01T00:00:00+00:00",
                    "metric_origin": "editorial_seed",
                },
                "image": {
                    "id": "seed-img-01",
                    "user_id": "seed_editorial",
                    "job_id": "seed-1",
                    "width": 640,
                    "height": 640,
                    "mode": "text_to_image",
                    "provider": "seed",
                    "prompt_original": "",
                    "settings_json": "{}",
                    "is_favorite": 0,
                    "created_at": "2026-07-01T00:00:00+00:00",
                },
                "assets": {
                    "thumb": _asset(bundle, "seed-pub-01_thumb.webp", b"thumb-seed"),
                    "large": _asset(bundle, "seed-pub-01_large.webp", b"large-seed"),
                },
            }
        ],
        "retired": [
            {
                "publicationId": "seed-pub-41",
                "imageId": "seed-img-41",
                "runtimeFiles": ["feed/seed-pub-41_large.webp"],
            }
        ],
    }
    (bundle / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    retired_file = main.MEDIA / "feed" / "seed-pub-41_large.webp"
    retired_file.parent.mkdir(parents=True)
    retired_file.write_bytes(b"retired")

    with main.db() as conn:
        conn.execute(
            "INSERT INTO images (id,user_id,job_id,url,thumbnail_url,width,height,mode,provider,prompt_original,settings_json,is_favorite,created_at) "
            "VALUES ('seed-img-41','seed_editorial','seed-41','/old','/old',1,1,'text_to_image','seed','','{}',0,'2026-07-01')"
        )
        conn.execute(
            "INSERT INTO feed_publications (id,image_id,internal_user_id,title,status,created_at) "
            "VALUES ('seed-pub-41','seed-img-41','seed_editorial','Faceless','published','2026-07-01')"
        )
        conn.execute(
            "INSERT INTO users (id,internal_user_id,display_name,role,language,created_at,last_login_at) "
            "VALUES ('real-user','real-user','Real user','user','ru','2026-07-01','2026-07-01')"
        )
        conn.execute(
            "INSERT INTO images (id,user_id,job_id,url,thumbnail_url,width,height,mode,provider,prompt_original,settings_json,is_favorite,created_at) "
            "VALUES ('real-img','real-user','real-job','/real','/real',1,1,'text_to_image','test','','{}',0,'2026-07-01')"
        )
        conn.execute(
            "INSERT INTO feed_publications (id,image_id,internal_user_id,title,status,created_at) "
            "VALUES ('real-pub','real-img','real-user','Real','published','2026-07-01')"
        )

    with main.db() as conn:
        dry = restore_demo_feed_bundle(conn, main.MEDIA, bundle_root=bundle)
    assert dry == {
        "apply": False,
        "authors": 1,
        "publications": 1,
        "assets": 2,
        "retired": ["seed-pub-41"],
        "assetsCopied": 0,
        "reactionsEnsured": 0,
    }

    with main.db() as conn:
        applied = restore_demo_feed_bundle(conn, main.MEDIA, bundle_root=bundle, apply=True)
    assert applied["assetsCopied"] == 2
    assert not retired_file.exists()
    assert (main.MEDIA / "feed" / "seed-pub-01_large.webp").read_bytes() == b"large-seed"

    with main.db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM feed_publications WHERE id='seed-pub-01'").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM feed_publications WHERE id='seed-pub-41'").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM feed_publications WHERE id='real-pub'").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM feed_reactions WHERE publication_id='seed-pub-01'").fetchone()[0] > 0

    with main.db() as conn:
        repeated = restore_demo_feed_bundle(conn, main.MEDIA, bundle_root=bundle, apply=True)
    assert repeated["assetsCopied"] == 0


def test_feed_shell_does_not_label_editorial_seed_as_demo():
    html = (Path(__file__).parent / "static" / "feed" / "index.html").read_text(encoding="utf-8")
    assert "Демо-витрина" not in html
