"""Live Feed MVP tests. Temp SQLite; no live DB.

Security coverage: publish requires trusted session and image ownership;
reactions require session; public feed never leaks hidden prompts; feed media
is served only for published items; init_db stays idempotent with feed tables.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import main


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
    media_file.write_bytes(b"\x89PNG fake")
    thumb = main.MEDIA / f"{image_id}_thumb.webp"
    thumb.write_bytes(b"RIFF fake")
    with main.db() as conn:
        conn.execute(
            "INSERT INTO images (id, user_id, job_id, url, thumbnail_url, width, height, mode, provider, "
            "prompt_original, settings_json, created_at) "
            "VALUES (?, ?, 'job-x', ?, ?, 1024, 1024, 'text_to_image', 'comfyui', ?, '{\"seed\": 42}', '2026-07-03')",
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
        assert items["Открытая"]["resolution"] == "1024×1024"
        assert items["Открытая"]["seed"] == 42


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


def test_feed_media_served_only_for_published(temp_db):
    with TestClient(main.app) as client:
        token = make_user("iuid-c", "web_c")
        make_image("img-c", "web_c")
        pub = publish(client, token, "img-c")
    with TestClient(main.app) as anon:
        # Публичный доступ к опубликованному файлу (без сессии, без владения).
        r = anon.get(f"/api/feed/media/{pub['id']}")
        assert r.status_code == 200
        r = anon.get(f"/api/feed/media/{pub['id']}?thumb=1")
        assert r.status_code == 200
        # Несуществующая публикация — 404.
        assert anon.get("/api/feed/media/nope").status_code == 404
        # Приватный /api/media как был: без сессии чужой файл не отдаётся
        # (легаси-фолбэк ?userId в проде закрыт trusted-сессией — см. gallery).


def test_init_db_idempotent_with_feed_tables(temp_db):
    main.init_db()
    main.init_db()
    with main.db() as conn:
        for table in ("feed_publications", "feed_reactions"):
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchone()
            assert row is not None


# --- Seed publications + image compression (Phase: feed seed) ---

def make_real_image(image_id: str, legacy_user: str, w: int = 1600, h: int = 900,
                    prompt: str = "секретный промпт про маяк") -> None:
    """Реальный PNG (PIL может открыть) — для проверки сжатия."""
    from PIL import Image
    img = Image.new("RGB", (w, h), (40, 90, 160))
    (main.MEDIA).mkdir(exist_ok=True)
    img.save(main.MEDIA / f"{image_id}.png")
    (main.MEDIA / f"{image_id}_thumb.webp").write_bytes(b"RIFF fake")
    with main.db() as conn:
        conn.execute(
            "INSERT INTO images (id, user_id, job_id, url, thumbnail_url, width, height, mode, provider, "
            "prompt_original, settings_json, created_at) "
            "VALUES (?, ?, 'job-r', ?, ?, ?, ?, 'text_to_image', 'comfyui', ?, '{\"seed\": 42}', '2026-07-03')",
            (image_id, legacy_user, f"/api/media/{image_id}.png?userId={legacy_user}",
             f"/api/media/{image_id}_thumb.webp?userId={legacy_user}", w, h, prompt),
        )


def test_publish_creates_compressed_derivatives(temp_db):
    with TestClient(main.app) as client:
        token = make_user("iuid-c1", "web_c1")
        make_real_image("img-real", "web_c1", 1600, 900)
        pub = publish(client, token, "img-real", visibility="open", title="Сжатие")
        assert pub["thumbnail_url"].endswith("?thumb=1")
        assert pub["display_url"] and "display_url" not in pub["thumbnail_url"]
        with main.db() as conn:
            row = conn.execute("SELECT feed_thumb_name, feed_large_name FROM feed_publications WHERE id = ?", (pub["id"],)).fetchone()
        assert row["feed_thumb_name"] and row["feed_large_name"]
        thumb_file = main.MEDIA / "feed" / row["feed_thumb_name"]
        large_file = main.MEDIA / "feed" / row["feed_large_name"]
        assert thumb_file.exists() and large_file.exists()
        # derived thumb is much smaller than the 1600x900 original
        assert thumb_file.stat().st_size < large_file.stat().st_size
    with TestClient(main.app) as anon:
        rt = anon.get(f"/api/feed/media/{pub['id']}?thumb=1")
        assert rt.status_code == 200
        assert rt.headers["content-type"] == "image/webp"
        rl = anon.get(f"/api/feed/media/{pub['id']}")
        assert rl.status_code == 200
        assert rl.headers["content-type"] == "image/webp"


def insert_seed(pub_id: str, image_id: str, badge: str | None = "trend",
                like: int = 1200, save: int = 200, recreate: int = 40, view: int = 15000) -> None:
    """Прямая вставка seed-публикации (как делает seed_feed.py)."""
    from PIL import Image
    img = Image.new("RGB", (1254, 1254), (120, 60, 160))
    img.save(main.MEDIA / f"{image_id}.png")
    with main.db() as conn:
        conn.execute(
            "INSERT INTO images (id, user_id, job_id, url, thumbnail_url, width, height, mode, provider, "
            "prompt_original, settings_json, created_at) "
            "VALUES (?, 'seed_editorial', 'seed', ?, ?, 1254, 1254, 'image_to_image', 'comfyui', '', '{}', '2026-06-10')",
            (image_id, f"/api/media/{image_id}.png?userId=seed_editorial",
             f"/api/media/{image_id}.png?userId=seed_editorial"),
        )
        conn.execute(
            "INSERT INTO feed_publications (id, image_id, internal_user_id, legacy_user_id, title, description, "
            "prompt_visibility, allow_recreate, status, created_at, is_seed, author_type, author_handle, "
            "author_display, author_avatar, badge, category, base_like_count, base_save_count, "
            "base_recreate_count, view_count) "
            "VALUES (?, ?, 'seed_editorial', 'seed_editorial', 'Seed работа', NULL, 'hidden', 1, 'published', "
            "'2026-06-10', 1, 'editorial', 'nova_render', 'Nova', 'ava_01.webp', ?, NULL, ?, ?, ?, ?)",
            (pub_id, image_id, badge, like, save, recreate, view),
        )
        main.feed_build_derivatives(conn, pub_id, image_id)


def test_seed_publication_public_hidden_and_not_mine(temp_db):
    insert_seed("seed-pub-x", "seed-img-x", badge="editor_pick", like=1500)
    # гость (без сессии) видит seed-ленту
    with TestClient(main.app) as anon:
        r = anon.get("/api/feed?type=foryou&limit=50")
        assert r.status_code == 200
        items = r.json()["items"]
        seed = next(i for i in items if i["id"] == "seed-pub-x")
        assert seed["is_seed"] is True
        assert seed["is_current_user"] is False
        assert seed["is_mine"] is False
        assert seed["prompt"] is None          # hidden prompt не раскрывается
        assert seed["prompt_visibility"] == "hidden"
        assert seed["badge"] == "editor_pick"
        assert seed["author_name"] == "Nova"
        assert seed["author_avatar"] == "/api/feed/avatar/ava_01.webp"
        assert seed["like_count"] >= 1500      # базовый seed-счётчик
        assert seed["thumbnail_url"] and seed["display_url"]
        # компрессия seed отдаётся как webp
        rt = anon.get(f"/api/feed/media/seed-pub-x?thumb=1")
        assert rt.status_code == 200 and rt.headers["content-type"] == "image/webp"


def test_seed_like_requires_auth_and_increments_over_base(temp_db):
    insert_seed("seed-pub-y", "seed-img-y", badge=None, like=1000)
    with TestClient(main.app) as anon:
        assert anon.post("/api/feed/publications/seed-pub-y/like").status_code == 401
    with TestClient(main.app) as client:
        token = make_user("iuid-v", "web_v")
        r = client.post("/api/feed/publications/seed-pub-y/like", headers=bearer(token))
        assert r.status_code == 200
        # база 1000 + 1 реальный лайк
        assert r.json()["publication"]["like_count"] == 1001
        # повторный лайк не дублирует
        r = client.post("/api/feed/publications/seed-pub-y/like", headers=bearer(token))
        assert r.json()["publication"]["like_count"] == 1001
