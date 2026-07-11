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

import db_schema_audit
import feed_media_audit
import feed_media_migrate
import feed_seed_demo_migrate
import gallery_original_audit
import gallery_original_migrate
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


def make_admin(iuid: str = "iuid-admin-feed", legacy: str = "web_admin_feed") -> str:
    with main.db() as conn:
        conn.execute(
            "INSERT INTO users (id, internal_user_id, role, token_balance, language, display_name, created_at, last_login_at) "
            "VALUES (?, ?, 'admin', 50, 'ru', 'Админ', '2026-01-01', '2026-01-01')",
            (legacy, iuid),
        )
    return main.create_auth_session(iuid, legacy, provider="web", platform="web")["session_token"]


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


def test_gallery_page_shell_serves_installed_visual_file(temp_db):
    with TestClient(main.app) as client:
        r = client.get("/gallery")
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]
        assert "no-store" in r.headers["cache-control"]
        assert "galleryGrid" in r.text
        assert "/static/gallery/gallery.js" in r.text
        assert 'href="/#text-to-image"' in r.text
        assert 'href="/#image-to-image"' in r.text
        assert 'href="/#editor"' in r.text
        assert 'href="/#face"' in r.text
        assert "/new#text-to-image" not in r.text
        assert "legacy-unused-topbar" not in r.text
        assert "n2-tab" not in r.text
        assert "data:image" not in r.text
        script = client.get("/static/gallery/gallery.js")
        assert script.status_code == 200
        assert "/api/gallery/page" in script.text
        assert "/#text-to-image" in script.text
        assert "/#image-to-image" in script.text
        assert "/new#" not in script.text


def test_home_page_serves_gallery_as_primary_page(temp_db):
    with TestClient(main.app) as client:
        r = client.get("/")
        assert r.status_code == 200
        assert "galleryGrid" in r.text
        assert "/static/gallery/gallery.js" in r.text


def test_feed_page_shell_serves_installed_visual_file(temp_db):
    with TestClient(main.app) as client:
        r = client.get("/feed")
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]
        assert "no-store" in r.headers["cache-control"]
        assert "/api/feed" in r.text
        assert "/api/gallery/page" not in r.text
        assert "data:image" not in r.text
        assert "return 6" not in r.text
        assert "mode-tile" in r.text
        assert "rail-challenge" in r.text
        assert "/static/feed/assets/mode_text.webp" in r.text
        assert 'href="/#text-to-image"' in r.text
        assert "/new#text-to-image" not in r.text
        assert "legacy-unused-topbar" not in r.text
        assert "n2-tab" not in r.text
        assert 'data-action="challenge"' in r.text
        assert "downloadCurrent" in r.text
        assert "modalSaveBtn" in r.text
        assert "modalDeleteBtn" in r.text
        assert "modalEditBtn" in r.text
        assert "detailOwnerActions" in r.text
        assert "signalFilter" in r.text
        assert "Лайкнутые" in r.text
        assert "authorNotifyBtn" in r.text
        assert "authorModal" in r.text
        assert "renderAuthorPublicProfile" in r.text
        assert "detailAuthor.addEventListener('click'" in r.text
        assert "Чем занимается" in r.text
        assert "Основной сайт" in r.text
        assert "photo-zoom" in r.text
        assert "/api/me-v2" in r.text
        assert "arrangeModalForViewport" in r.text
        assert "avatarHtml(item.author, item.avatarUrl)" in r.text
        assert "function deleteCurrentPublication()" in r.text
        assert "function editCurrentPublication()" in r.text
        assert "method:'PATCH'" in r.text
        assert "/save" in r.text
        assert "nf-page" not in r.text
        assert "iv3-feed" not in r.text
        assert "Загружаем ленту" not in r.text
        assert "src:item.thumbnail_url || ''" in r.text
        assert "fullSrc:item.image_url || ''" in r.text
        assert "i.thumbnail_url && i.image_url" in r.text
        assert ".inline-action{appearance:none;border:0;background:transparent" in r.text
        assert ".author-line{display:flex;align-items:center;gap:7px;min-width:0;color:#fff" in r.text
        assert '<button class="persist-stat remix" type="button" data-action="remix"' in r.text
        assert '<button class="persist-stat heart' in r.text
        assert ".card-actions{display:none}" in r.text
        assert "card.dataset.publicationId = item.id" in r.text
        assert "function syncPublicationUi(item)" in r.text
        assert "showToast(method === 'POST' ? 'Лайк поставлен' : 'Лайк снят'); await loadFeed" not in r.text
        assert "detail-panels" in r.text
        assert "authorTotals" in r.text
        assert "function renderAuthorCard(item, authorWorks)" in r.text
        assert "author-work-count" in r.text
        assert "more-col" in r.text
        assert "overflow-y:auto;overflow-x:hidden" in r.text
        assert "--more-ratio" in r.text
        assert "modalSaveBtn" in r.text
        assert "detail-icon save" in r.text
        assert "detail-management" in r.text
        assert "detail-more" in r.text
        assert "detail-secondary-actions" in r.text
        assert "modalMoreBtn" in r.text
        assert "authorSocialCounts" in r.text
        assert "followersCount" in r.text
        assert "followingCount" in r.text
        assert "author-followers" in r.text
        assert '<div class="author-actions">' in r.text
        assert "<small>просмотров</small>" in r.text
        assert "<small>в избранном</small>" in r.text
        assert 'role="tablist" aria-label="Разделы ленты"' in r.text
        assert 'role="tab" aria-controls="feedPanel" aria-selected="true"' in r.text
        assert "function activateFeedTab(filter" in r.text
        assert "feedMain.addEventListener('touchstart'" in r.text
        assert "feedMain.addEventListener('touchmove'" in r.text
        assert "feedMain.addEventListener('touchend'" in r.text
        assert "current + (dx < 0 ? 1 : -1)" in r.text
        assert "dx > 0 && current === 0" in r.text
        assert "const feedCache = new Map()" in r.text
        assert "new AbortController()" in r.text
        assert 'role="tabpanel"' in r.text
        assert "prefers-reduced-motion:reduce" in r.text
        assert "detail-owner-actions" not in r.text
        assert "избранных" in r.text
        assert "view_count" in r.text
        assert "/view" in r.text
        assert "data-panel=\"history\"" in r.text
        assert "function setActivePanel(name = '')" in r.text
        assert "История создания" not in r.text
        assert "modalHistory" in r.text
        assert "function renderSourceHistory(item)" in r.text
        assert "tab-explainer" not in r.text
        assert "скрыт автором" not in r.text
        assert "Работы автора появятся во вкладке Подписки" in r.text
        assert "Снять вашу публикацию с публичной ленты" in r.text
        assert "feedbar.feedbar-hidden" in r.text
        assert "updateFeedbarForScroll" in r.text
        assert ".iv3.topbar-scope{--line:" in r.text
        assert "position:sticky;top:0;z-index:160" in r.text
        assert "mobile-bottom-nav" not in r.text

        asset = client.get("/static/feed/assets/mode_text.webp")
        assert asset.status_code == 200
        assert asset.headers["content-type"] == "image/webp"
        avatar = client.get("/avatars/avatar-001.webp")
        assert avatar.status_code == 200
        assert avatar.headers["content-type"] == "image/webp"


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


def test_publish_keeps_generation_snapshot_and_public_controls(temp_db):
    with TestClient(main.app) as client:
        token = make_user("iuid-snapshot", "web_snapshot")
        make_image("img-snapshot", "web_snapshot", prompt="исходный промпт для снимка")
        response = client.post(
            "/api/feed/publications",
            json={
                "imageId": "img-snapshot",
                "title": "Зафиксированная работа",
                "description": "Описание публикации",
                "promptVisibility": "partial",
                "allowRecreate": False,
                "category": "design",
                "tags": ["неон", "город", "неон"],
            },
            headers=bearer(token),
        )
        assert response.status_code == 200, response.text
        publication = response.json()["publication"]
        assert publication["description"] == "Описание публикации"
        assert publication["prompt_visibility"] == "partial"
        assert publication["allow_recreate"] is False
        assert publication["category"] == "design"
        assert publication["tags"] == ["неон", "город"]
        assert publication["prompt"] == "исходный промпт для снимка"
        assert publication["generation_params"]

        with main.db() as conn:
            row = conn.execute(
                "SELECT generation_snapshot_json FROM feed_publications WHERE image_id = 'img-snapshot'"
            ).fetchone()
            snapshot = json.loads(row["generation_snapshot_json"])
            assert snapshot["prompt"] == "исходный промпт для снимка"
            conn.execute(
                "UPDATE images SET prompt_original = 'измененный промпт', settings_json = '{\"seed\": 999}' WHERE id = 'img-snapshot'"
            )

        feed = client.get("/api/feed?type=fresh&limit=10")
        assert feed.status_code == 200
        restored = next(item for item in feed.json()["items"] if item["id"] == publication["id"])
        assert restored["prompt"] == "исходный промпт для снимка"
        assert restored["seed"] == 42
        assert restored["category"] == "design"
        assert restored["tags"] == ["неон", "город"]


def test_feed_public_read_and_prompt_visibility(temp_db):
    with TestClient(main.app) as client:
        token = make_user("iuid-a", "web_a")
        with main.db() as conn:
            conn.execute(
                """
                UPDATE users
                SET username = 'public_artist',
                    public_about = 'Создаю сказочные города и персонажей.',
                    public_website = 'https://artist.example',
                    public_focus = 'Фэнтези и архитектура',
                    public_phone = '+79990001122',
                    public_links_json = ?,
                    city = 'Москва',
                    country = 'RU',
                    age = 31
                WHERE internal_user_id = 'iuid-a'
                """,
                (json.dumps([{"label": "Портфолио", "url": "https://portfolio.example"}], ensure_ascii=False),),
            )
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
        assert items["Открытая"]["view_count"] == 0
        author = items["Открытая"]["author"]
        assert author["username"] == "public_artist"
        assert author["publicAbout"] == "Создаю сказочные города и персонажей."
        assert author["publicWebsite"] == "https://artist.example"
        assert author["publicFocus"] == "Фэнтези и архитектура"
        assert author["publicPhone"] == "+79990001122"
        assert author["publicLinks"] == [{"label": "Портфолио", "url": "https://portfolio.example"}]
        assert author["city"] == "Москва"
        assert author["country"] == "RU"
        assert author["age"] == 31


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


def test_feed_publication_view_count_is_public_and_incremented(temp_db):
    with TestClient(main.app) as client:
        token = make_user("iuid-view-author", "web_view_author")
        make_image("img-view", "web_view_author")
        pub = publish(client, token, "img-view")

    with TestClient(main.app) as anon:
        r = anon.post(f"/api/feed/publications/{pub['id']}/view")
        assert r.status_code == 200
        assert r.json()["publication"]["view_count"] == 1
        r = anon.post(f"/api/feed/publications/{pub['id']}/view")
        assert r.json()["publication"]["view_count"] == 2
        feed = anon.get("/api/feed?type=new").json()
        item = next(i for i in feed["items"] if i["id"] == pub["id"])
        assert item["view_count"] == 2


def test_feed_tabs_follow_challenge_and_remix_start(temp_db):
    with TestClient(main.app) as client:
        author_token = make_user("iuid-author-tabs", "web_author_tabs", display_name="Тимур Ким")
        viewer_token = make_user("iuid-viewer-tabs", "web_viewer_tabs", display_name="Зритель")
        make_image("img-tabs-a", "web_author_tabs", prompt="Москва 2120, город будущего")
        make_image("img-tabs-b", "web_author_tabs", prompt="Неоновый двор")
        make_image("img-tabs-c", "web_author_tabs", prompt="Стеклянная башня")
        pub_a = publish(client, author_token, "img-tabs-a", title="Москва 2120")
        pub_b = publish(client, author_token, "img-tabs-b", title="Двор")
        pub_c = publish(client, author_token, "img-tabs-c", title="Башня")
        other_token = make_user("iuid-other-tabs", "web_other_tabs", display_name="Другой автор")
        make_image("img-tabs-other", "web_other_tabs", prompt="Новая публикация другого автора")
        publish(client, other_token, "img-tabs-other", title="Свежая чужая работа")
        with main.db() as conn:
            conn.execute(
                "UPDATE feed_publications SET category = 'challenge_moscow_2120' WHERE id = ?",
                (pub_a["id"],),
            )

        challenge = client.get("/api/feed?type=challenge", headers=bearer(viewer_token)).json()
        assert challenge["type"] == "challenge"
        assert [item["id"] for item in challenge["items"]] == [pub_a["id"]]
        assert challenge["items"][0]["challenge"]["id"] == "moscow_2120_week"

        remix_started = client.post(
            f"/api/feed/publications/{pub_a['id']}/remix/start",
            headers=bearer(viewer_token),
        )
        assert remix_started.status_code == 200
        remix_body = remix_started.json()
        assert remix_body["ok"] is True
        assert remix_body["prompt"] == "Москва 2120, город будущего"
        remix_feed = client.get("/api/feed?type=remix", headers=bearer(viewer_token)).json()
        assert remix_feed["items"][0]["id"] == pub_a["id"]

        followed = client.post(
            f"/api/feed/authors/{pub_a['user_id']}/follow",
            headers=bearer(viewer_token),
        )
        assert followed.status_code == 200
        author_after_follow = client.get("/api/feed?type=fresh", headers=bearer(viewer_token)).json()
        author_item = next(item for item in author_after_follow["items"] if item["id"] == pub_a["id"])
        assert author_item["author"]["followersCount"] == 1
        assert author_item["author"]["followingCount"] == 0
        following = client.get("/api/feed?type=following", headers=bearer(viewer_token)).json()
        assert {item["id"] for item in following["items"]} == {pub_a["id"], pub_b["id"], pub_c["id"]}
        assert all(item["is_followed_by_me"] for item in following["items"])
        personalized = client.get("/api/feed?type=for_you", headers=bearer(viewer_token)).json()
        assert personalized["items"][0]["user_id"] == pub_a["user_id"]

        author_items = client.get(
            f"/api/feed/authors/{pub_a['user_id']}/publications",
            headers=bearer(viewer_token),
        ).json()
        assert {item["id"] for item in author_items["items"]} == {pub_a["id"], pub_b["id"], pub_c["id"]}
        assert all(item["author"]["displayName"] == "Тимур Ким" for item in author_items["items"])

        disliked = client.post(
            f"/api/feed/publications/{pub_b['id']}/dislike",
            headers=bearer(viewer_token),
        )
        assert disliked.status_code == 200
        assert disliked.json()["publication"]["is_disliked_by_me"] is True
        hidden = client.post(
            f"/api/feed/publications/{pub_b['id']}/hide",
            headers=bearer(viewer_token),
        )
        assert hidden.status_code == 200
        assert hidden.json()["publication"]["is_hidden_by_me"] is True

        following_after_hide = client.get("/api/feed?type=following", headers=bearer(viewer_token)).json()
        assert {item["id"] for item in following_after_hide["items"]} == {pub_a["id"], pub_c["id"]}
        fresh_after_hide = client.get("/api/feed?type=new&limit=2", headers=bearer(viewer_token)).json()
        assert len(fresh_after_hide["items"]) == 2
        assert pub_b["id"] not in {item["id"] for item in fresh_after_hide["items"]}

        # Hide is personal: guests still see the published item.
        guest_fresh = client.get("/api/feed?type=new").json()
        assert pub_b["id"] in {item["id"] for item in guest_fresh["items"]}

        reported = client.post(
            f"/api/feed/publications/{pub_b['id']}/report",
            headers=bearer(viewer_token),
        )
        assert reported.status_code == 200
        assert reported.json()["publication"]["is_reported_by_me"] is True

        # Negative reactions do not promote an item in Top. pub_a has a
        # recreate signal; pub_b has dislike/hide/report and must not outrank it.
        top_guest = client.get("/api/feed?type=top").json()
        assert top_guest["items"][0]["id"] == pub_a["id"]

        challenges = client.get("/api/feed/challenges", headers=bearer(viewer_token)).json()
        assert challenges["ok"] is True
        assert challenges["items"][0]["id"] == "moscow_2120_week"
        assert challenges["items"][0]["publicationCount"] >= 1


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


def test_gallery_quota_eviction_preserves_feed_publication_and_variants(temp_db):
    with TestClient(main.app) as client:
        token = make_user("iuid-quota-feed", "web_quota_feed")
        make_image("img-quota-feed", "web_quota_feed")
        pub = publish(client, token, "img-quota-feed", title="Остаётся в ленте")
        with main.db() as conn:
            media = conn.execute(
                "SELECT feed_thumb_name, feed_large_name FROM feed_publications WHERE id = ?",
                (pub["id"],),
            ).fetchone()
            evicted = main.evict_gallery_images_for_new_save(
                conn,
                "web_quota_feed",
                {"gallery_slots": 1, "gallery_used": 1},
                "2026-07-11T00:00:00+00:00",
            )
            image = conn.execute("SELECT deleted_at FROM images WHERE id = 'img-quota-feed'").fetchone()
            publication = conn.execute(
                "SELECT status, feed_thumb_name, feed_large_name, media_ready_at, media_error "
                "FROM feed_publications WHERE id = ?",
                (pub["id"],),
            ).fetchone()

        assert evicted == 1
        assert image["deleted_at"] == "2026-07-11T00:00:00+00:00"
        assert publication["status"] == "published"
        assert publication["feed_thumb_name"] == media["feed_thumb_name"]
        assert publication["feed_large_name"] == media["feed_large_name"]
        assert publication["media_ready_at"] is not None
        assert publication["media_error"] is None
        assert (main.MEDIA / media["feed_thumb_name"]).exists()
        assert (main.MEDIA / media["feed_large_name"]).exists()
        assert client.get(f"/api/feed/media/{pub['id']}?variant=thumb").status_code == 200
        feed = client.get("/api/feed?type=fresh")
        assert any(item["id"] == pub["id"] for item in feed.json()["items"])


def test_admin_can_delete_feed_publication_without_deleting_gallery_source(temp_db):
    with TestClient(main.app) as client:
        owner_token = make_user("iuid-admin-feed-owner", "web_admin_feed_owner")
        non_admin_token = make_user("iuid-admin-feed-user", "web_admin_feed_user")
        admin_token = make_admin()
        make_image("img-admin-feed-delete", "web_admin_feed_owner")
        pub = publish(client, owner_token, "img-admin-feed-delete", title="Удалить из ленты")
        with main.db() as conn:
            row = conn.execute(
                "SELECT feed_thumb_name, feed_large_name FROM feed_publications WHERE id = ?",
                (pub["id"],),
            ).fetchone()
        thumb = main.MEDIA / row["feed_thumb_name"]
        large = main.MEDIA / row["feed_large_name"]
        assert thumb.exists()
        assert large.exists()

        denied = client.post(
            f"/api/admin/feed/publications/{pub['id']}/delete-v2",
            json={"reason": "moderation"},
            headers=bearer(non_admin_token),
        )
        assert denied.status_code == 403

        missing_reason = client.post(
            f"/api/admin/feed/publications/{pub['id']}/delete-v2",
            json={"reason": ""},
            headers=bearer(admin_token),
        )
        assert missing_reason.status_code == 400

        deleted = client.post(
            f"/api/admin/feed/publications/{pub['id']}/delete-v2",
            json={"reason": "moderation"},
            headers=bearer(admin_token),
        )
        assert deleted.status_code == 200, deleted.text
        assert deleted.json()["status"] == "hidden"
        assert not thumb.exists()
        assert not large.exists()
        assert client.get(f"/api/feed/media/{pub['id']}?variant=thumb").status_code == 404
        feed = client.get("/api/feed?type=new").json()
        assert pub["id"] not in {item["id"] for item in feed["items"]}

        gallery = client.get("/api/gallery/page", headers=bearer(owner_token)).json()
        assert gallery["items"][0]["id"] == "img-admin-feed-delete"
        assert gallery["items"][0]["published"] is False
        assert gallery["items"][0]["feedMediaStatus"] is None
        with main.db() as conn:
            row = conn.execute(
                "SELECT status, feed_thumb_name, feed_large_name, media_ready_at, media_error "
                "FROM feed_publications WHERE id = ?",
                (pub["id"],),
            ).fetchone()
            audits = conn.execute(
                "SELECT COUNT(*) AS c FROM audit_logs WHERE action = 'admin_delete_feed_publication'"
            ).fetchone()["c"]
            events = conn.execute(
                "SELECT COUNT(*) AS c FROM security_events WHERE event_type = 'admin_feed_publication_deleted'"
            ).fetchone()["c"]
        assert row["status"] == "hidden"
        assert row["feed_thumb_name"] is None
        assert row["feed_large_name"] is None
        assert row["media_ready_at"] is None
        assert row["media_error"] == "admin_deleted"
        assert audits == 1
        assert events == 1


def test_owner_can_delete_feed_publication_without_deleting_gallery_source(temp_db):
    with TestClient(main.app) as client:
        owner_token = make_user("iuid-owner-feed-delete", "web_owner_feed_delete")
        other_token = make_user("iuid-other-feed-delete", "web_other_feed_delete")
        make_image("img-owner-feed-delete", "web_owner_feed_delete")
        pub = publish(client, owner_token, "img-owner-feed-delete", title="Снять из ленты")
        with main.db() as conn:
            row = conn.execute(
                "SELECT feed_thumb_name, feed_large_name FROM feed_publications WHERE id = ?",
                (pub["id"],),
            ).fetchone()
        thumb = main.MEDIA / row["feed_thumb_name"]
        large = main.MEDIA / row["feed_large_name"]
        assert thumb.exists()
        assert large.exists()

        denied = client.delete(f"/api/feed/publications/{pub['id']}", headers=bearer(other_token))
        assert denied.status_code == 403

        deleted = client.delete(f"/api/feed/publications/{pub['id']}", headers=bearer(owner_token))
        assert deleted.status_code == 200, deleted.text
        assert deleted.json()["status"] == "hidden"
        assert not thumb.exists()
        assert not large.exists()
        assert client.get(f"/api/feed/media/{pub['id']}?variant=thumb").status_code == 404
        feed = client.get("/api/feed?type=new").json()
        assert pub["id"] not in {item["id"] for item in feed["items"]}

        gallery = client.get("/api/gallery/page", headers=bearer(owner_token)).json()
        assert gallery["items"][0]["id"] == "img-owner-feed-delete"
        assert gallery["items"][0]["published"] is False
        assert gallery["items"][0]["feedMediaStatus"] is None
        with main.db() as conn:
            row = conn.execute(
                "SELECT status, feed_thumb_name, feed_large_name, media_ready_at, media_error "
                "FROM feed_publications WHERE id = ?",
                (pub["id"],),
            ).fetchone()
            denied_events = conn.execute(
                "SELECT COUNT(*) AS c FROM security_events WHERE event_type = 'feed_publication_delete_denied'"
            ).fetchone()["c"]
            deleted_events = conn.execute(
                "SELECT COUNT(*) AS c FROM security_events WHERE event_type = 'feed_publication_owner_deleted'"
            ).fetchone()["c"]
            audits = conn.execute(
                "SELECT COUNT(*) AS c FROM audit_logs WHERE action = 'delete_own_feed_publication'"
            ).fetchone()["c"]
        assert row["status"] == "hidden"
        assert row["feed_thumb_name"] is None
        assert row["feed_large_name"] is None
        assert row["media_ready_at"] is None
        assert row["media_error"] == "owner_deleted"
        assert denied_events == 1
        assert deleted_events == 1
        assert audits == 1


def test_owner_can_update_feed_publication_title(temp_db):
    with TestClient(main.app) as client:
        owner_token = make_user("iuid-owner-feed-edit", "web_owner_feed_edit")
        other_token = make_user("iuid-other-feed-edit", "web_other_feed_edit")
        make_image("img-owner-feed-edit", "web_owner_feed_edit")
        pub = publish(client, owner_token, "img-owner-feed-edit", title="Старое название")

        denied = client.patch(
            f"/api/feed/publications/{pub['id']}",
            json={"title": "Чужая правка"},
            headers=bearer(other_token),
        )
        assert denied.status_code == 403

        empty = client.patch(
            f"/api/feed/publications/{pub['id']}",
            json={"title": ""},
            headers=bearer(owner_token),
        )
        assert empty.status_code == 400

        updated = client.patch(
            f"/api/feed/publications/{pub['id']}",
            json={"title": "Новое название"},
            headers=bearer(owner_token),
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["publication"]["title"] == "Новое название"
        with main.db() as conn:
            row = conn.execute("SELECT title FROM feed_publications WHERE id = ?", (pub["id"],)).fetchone()
            audits = conn.execute(
                "SELECT COUNT(*) AS c FROM audit_logs WHERE action = 'update_own_feed_publication'"
            ).fetchone()["c"]
        assert row["title"] == "Новое название"
        assert audits == 1


def test_feed_payload_marks_owner_and_admin_delete_capability(temp_db):
    with TestClient(main.app) as client:
        owner_token = make_user("iuid-feed-delete-owner", "web_feed_delete_owner")
        other_token = make_user("iuid-feed-delete-other", "web_feed_delete_other")
        admin_token = make_admin("iuid-feed-delete-admin", "web_feed_delete_admin")
        make_image("img-feed-delete-capability", "web_feed_delete_owner")
        pub = publish(client, owner_token, "img-feed-delete-capability", title="Право удаления")

        owner_item = client.get("/api/feed?type=new", headers=bearer(owner_token)).json()["items"][0]
        other_item = client.get("/api/feed?type=new", headers=bearer(other_token)).json()["items"][0]
        admin_item = client.get("/api/feed?type=new", headers=bearer(admin_token)).json()["items"][0]
        anon_item = client.get("/api/feed?type=new").json()["items"][0]

        assert owner_item["id"] == pub["id"]
        assert owner_item["can_delete_by_me"] is True
        assert owner_item["delete_role"] == "owner"
        assert other_item["can_delete_by_me"] is False
        assert other_item["delete_role"] is None
        assert admin_item["can_delete_by_me"] is True
        assert admin_item["delete_role"] == "admin"
        assert anon_item["can_delete_by_me"] is False
        assert anon_item["delete_role"] is None


def test_feed_payload_exposes_author_avatar(temp_db):
    with TestClient(main.app) as client:
        token = make_user("iuid-feed-avatar", "web_feed_avatar", display_name="Алекс")
        with main.db() as conn:
            conn.execute(
                "UPDATE users SET avatar_url = '/media/avatars/alex.webp' WHERE internal_user_id = ?",
                ("iuid-feed-avatar",),
            )
        make_image("img-feed-avatar", "web_feed_avatar")
        pub = publish(client, token, "img-feed-avatar", title="Аватар автора")

        item = client.get("/api/feed?type=new", headers=bearer(token)).json()["items"][0]
        assert item["id"] == pub["id"]
        assert item["author"]["displayName"] == "Алекс"
        assert item["author"]["avatarUrl"] == "/media/avatars/alex.webp"


def test_feed_payload_exposes_creation_history(temp_db):
    with TestClient(main.app) as client:
        token = make_user("iuid-feed-history", "web_feed_history")
        make_image("img-feed-history", "web_feed_history")
        with main.db() as conn:
            conn.execute(
                """
                INSERT INTO image_sources (
                    id, image_id, user_id, source_kind, role, slot_index,
                    thumb_url, thumb_width, thumb_height, thumb_bytes, children_json, created_at
                )
                VALUES ('src-feed-history', 'img-feed-history', 'web_feed_history', 'upload', 'base', 1,
                        '/api/media/source.webp?userId=web_feed_history', 320, 240, 1000, '[]', '2026-07-03')
                """
            )
        publish(client, token, "img-feed-history", title="История")

        item = client.get("/api/feed?type=new", headers=bearer(token)).json()["items"][0]
        assert item["source_history"][0]["roleLabel"] == "Основа"
        assert item["source_history"][0]["thumbUrl"].startswith("/api/media/source.webp")
        assert item["source_history"][0]["width"] == 320


def test_gallery_page_returns_visual_shell_contract(temp_db):
    with TestClient(main.app) as client:
        token = make_user("iuid-gallery-page", "web_gallery_page")
        make_image("img-gallery-page", "web_gallery_page", prompt="город на рассвете")
        with main.db() as conn:
            conn.execute(
                "UPDATE images SET provider = 'openrouter', settings_json = ? WHERE id = 'img-gallery-page'",
                (json.dumps({
                    "seed": 42,
                    "modelProfile": "black-forest-labs/flux.2-pro",
                    "tokenCost": 2,
                    "generationTimeMs": 12450,
                    "openrouterBilling": {"chargedTokens": 2, "modelName": "FLUX.2 Pro"},
                    "loras": ["internal-lora"],
                    "preset": "internal-preset",
                }, ensure_ascii=False),),
            )
        pub = publish(client, token, "img-gallery-page", title="Рассвет")
        client.post(f"/api/feed/publications/{pub['id']}/like", headers=bearer(token))

        r = client.get("/api/gallery/page", headers=bearer(token))
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["ok"] is True
        assert data["limits"]["originals"]["used"] == 1
        assert data["limits"]["feed"]["used"] == 1
        assert data["limits"]["favorites"]["limit"] >= 0

        item = data["items"][0]
        assert item["id"] == "img-gallery-page"
        assert item["prompt"] == "город на рассвете"
        assert item["published"] is True
        assert item["feedPublicationId"] == pub["id"]
        assert item["modeLabel"] == "По тексту"
        assert item["aspectRatio"] == "3:2"
        assert item["src"].startswith("/api/media/")
        assert item["fileSizeBytes"] > 0
        params = {row["label"]: row["value"] for row in item["publicParams"]}
        assert params["Токены"] == "2 ток."
        assert params["Разрешение"] == "1200×800"
        assert params["Формат"] == "3:2"
        assert params["Вес файла"].endswith(("КБ", "МБ"))
        assert params["Время генерации"] == "12,4 с"
        assert params["Дата генерации"].startswith("03.07.2026")
        assert params["Режим"] == "По тексту"
        assert params["Полное наименование модели"] == "FLUX.2 Pro · BFL · выпуск: 2026"
        assert list(params)[-1] == "Полное наименование модели"
        assert item["modelInfo"]["shortName"] == "FLUX.2 Pro"
        assert item["modelInfo"]["release"] == "2026"
        assert "Seed" not in params
        assert "LoRA" not in params
        assert "Пресет" not in params

        feed_item = data["feedItems"][0]
        assert feed_item["id"] == "img-gallery-page"
        assert feed_item["src"].endswith(f"/api/feed/media/{pub['id']}?variant=thumb")
        assert feed_item["viewerSrc"].endswith(f"/api/feed/media/{pub['id']}?variant=large")
        assert feed_item["likes"] == 1
        feed_params = {row["label"]: row["value"] for row in feed_item["publicParams"]}
        assert feed_params["Полное наименование модели"] == "FLUX.2 Pro · BFL · выпуск: 2026"
        assert feed_params["Токены"] == "2 ток."

        feed_payload = client.get("/api/feed?type=new", headers=bearer(token)).json()["items"][0]
        generation_params = {row["label"]: row["value"] for row in feed_payload["generation_params"]}
        assert generation_params["Полное наименование модели"] == "FLUX.2 Pro · BFL · выпуск: 2026"
        assert generation_params["Токены"] == "2 ток."
        assert generation_params["Дата генерации"].startswith("03.07.2026")
        assert feed_payload["model_info"]["shortName"] == "FLUX.2 Pro"
        assert feed_payload["token_cost"] == 2
        assert feed_payload["file_size_bytes"] > 0


def test_gallery_page_feed_items_are_not_limited_to_visible_original_page(temp_db):
    with TestClient(main.app) as client:
        token = make_user("iuid-gallery-feed-page", "web_gallery_feed_page")
        for index in range(5):
            image_id = f"img-gallery-feed-page-{index}"
            make_image(image_id, "web_gallery_feed_page", prompt=f"лента {index}")
            if index < 3:
                publish(client, token, image_id, title=f"Публикация {index}")

        r = client.get("/api/gallery/page?limit=2", headers=bearer(token))
        assert r.status_code == 200, r.text
        data = r.json()

        assert data["limits"]["feed"]["used"] == 3
        assert len(data["items"]) == 2
        assert len(data["feedItems"]) == 2
        assert {item["id"] for item in data["feedItems"]} != {item["id"] for item in data["items"]}


def test_gallery_page_does_not_mark_missing_feed_media_as_published(temp_db):
    with TestClient(main.app) as client:
        token = make_user("iuid-gallery-missing-feed", "web_gallery_missing_feed")
        make_image("img-gallery-missing-feed", "web_gallery_missing_feed", prompt="город в тумане")
        pub = publish(client, token, "img-gallery-missing-feed", title="Туман")
        with main.db() as conn:
            conn.execute(
                "UPDATE feed_publications SET media_ready_at = NULL, media_error = 'test missing media' WHERE id = ?",
                (pub["id"],),
            )

        r = client.get("/api/gallery/page", headers=bearer(token))
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["limits"]["feed"]["used"] == 0
        item = data["items"][0]
        assert item["id"] == "img-gallery-missing-feed"
        assert item["published"] is False
        assert item["feedPublicationId"] == pub["id"]
        assert item["feedMediaStatus"] == "missing"
        assert data["feedItems"] == []


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


def test_gallery_original_audit_reports_optimization_candidates(temp_db):
    make_user("iuid-gallery-originals", "web_gallery_originals")
    make_image("img-gallery-originals", "web_gallery_originals")

    report = gallery_original_audit.audit_gallery_originals(item_limit=10)
    assert report["issues"] == []
    assert report["totals"]["active_originals"] >= 1
    candidate = next(item for item in report["candidates"] if item["image_id"] == "img-gallery-originals")
    assert candidate["file"] == "img-gallery-originals.png"
    assert "legacy_format" in candidate["reasons"]


def test_gallery_original_migrate_dry_run_excludes_seed_by_default(temp_db):
    make_user("iuid-gallery-migrate", "web_gallery_migrate")
    make_image("img-gallery-migrate", "web_gallery_migrate")
    make_image("seed_izo_migrate", "seed_editorial")

    report = gallery_original_migrate.migrate_gallery_originals(apply=False, item_limit=20)
    files = {item["source"] for item in report["items"]}
    skipped = {item["file"]: item["skip_reason"] for item in report["skipped"] if item.get("file")}
    assert "img-gallery-migrate.png" in files
    assert "seed_izo_migrate.png" not in files
    assert skipped["seed_izo_migrate.png"] == "seed_not_requested"
    assert report["changes_db"] is False


def test_gallery_original_migrate_apply_updates_url_without_deleting_source(temp_db):
    make_user("iuid-gallery-apply", "web_gallery_apply")
    make_image("img-gallery-apply", "web_gallery_apply")
    source = main.MEDIA / "img-gallery-apply.png"

    report = gallery_original_migrate.migrate_gallery_originals(apply=True, item_limit=1)
    item = report["items"][0]
    target = main.MEDIA / item["target"]
    with main.db() as conn:
        row = conn.execute("SELECT url, width, height FROM images WHERE id = 'img-gallery-apply'").fetchone()

    assert report["changes_db"] is True
    assert target.exists()
    assert target.suffix == ".webp"
    assert row["url"].startswith("/api/media/")
    assert row["url"].split("?", 1)[0].endswith(".webp")
    assert row["width"] <= main.GALLERY_IMAGE_MAX_SIDE
    assert row["height"] <= main.GALLERY_IMAGE_MAX_SIDE
    assert source.exists()


def test_gallery_original_migrate_updates_thumbnail_when_it_matches_source(temp_db):
    make_image("seed_izo_thumb_match", "seed_editorial")
    source = main.MEDIA / "seed_izo_thumb_match.png"
    with main.db() as conn:
        conn.execute(
            "UPDATE images SET thumbnail_url = url WHERE id = ?",
            ("seed_izo_thumb_match",),
        )

    report = gallery_original_migrate.migrate_gallery_originals(
        apply=True,
        include_seed=True,
        delete_source=True,
        item_limit=1,
    )
    item = report["items"][0]
    with main.db() as conn:
        row = conn.execute(
            "SELECT url, thumbnail_url FROM images WHERE id = ?",
            ("seed_izo_thumb_match",),
        ).fetchone()

    assert item["source_deleted"] is True
    assert not source.exists()
    assert row["url"].split("?", 1)[0].endswith(".webp")
    assert row["thumbnail_url"] == row["url"]
    assert (main.MEDIA / item["target"]).exists()


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


def test_media_cleanup_apply_blocks_when_source_audit_has_issues(temp_db, monkeypatch):
    candidate = main.MEDIA / "blocked-orphan.png"
    candidate.write_bytes(b"keep")

    def fake_plan(**_kwargs):
        return {
            "created_at": "2026-07-07T00:00:00+00:00",
            "candidate_summary": {"count": 1, "bytes": 4, "human": "4 B", "truncated_to": 1},
            "source_audit": {"issues": ["missing_active_refs"]},
            "selected_kinds": ["original_or_input"],
            "protected_kinds": [],
            "ignored_requested_protected_kinds": [],
            "candidates": [
                {
                    "file": "blocked-orphan.png",
                    "bytes": 4,
                    "human": "4 B",
                    "kind": "original_or_input",
                    "reason": "unreferenced",
                }
            ],
        }

    monkeypatch.setattr(media_cleanup_plan, "build_cleanup_plan", fake_plan)

    result = media_cleanup_apply.apply_cleanup(apply=True)
    assert result["mode"] == "blocked"
    assert result["deletes_files"] is False
    assert result["source_issues"] == ["missing_active_refs"]
    assert result["skipped"][0]["skip_reason"] == "blocked_by_source_issues"
    assert candidate.exists()


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


def test_init_db_has_media_query_indexes(temp_db):
    main.init_db()
    with main.db() as conn:
        indexes = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index'"
            ).fetchall()
        }
    expected = {
        "idx_images_user_deleted_created",
        "idx_images_job_id",
        "idx_jobs_user_created",
        "idx_jobs_result_image",
        "idx_feed_publications_media_ready",
        "idx_feed_publications_category_ready_created",
        "idx_feed_publications_legacy_ready_created",
    }
    assert expected <= indexes


def test_db_schema_audit_reports_ready_schema(temp_db):
    report = db_schema_audit.audit_db_schema()
    assert report["issues"] == []
    assert report["missing_columns"] == {}
    assert report["missing_indexes"] == []


def test_media_health_check_includes_schema_readiness(temp_db):
    report = media_health_check.run_media_health_check(item_limit=3)
    assert report["summary"]["schema"] == {"missing_columns": {}, "missing_indexes": []}
    assert report["reports"]["schema"]["issues"] == []
    assert "gallery_originals" in report["summary"]


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


def test_seed_demo_migrate_assigns_demo_authors_and_reactions(temp_db):
    make_image("seed-img-01", "seed_editorial")
    make_image("seed-img-02", "seed_editorial")
    make_image("real-img-01", "web_real")
    with main.db() as conn:
        conn.execute(
            "INSERT INTO feed_publications (id, image_id, internal_user_id, legacy_user_id, title, status, created_at) "
            "VALUES ('seed-pub-01', 'seed-img-01', 'seed_editorial', 'seed_editorial', 'Seed 1', 'published', '2026-07-01')"
        )
        conn.execute(
            "INSERT INTO feed_publications (id, image_id, internal_user_id, legacy_user_id, title, status, created_at) "
            "VALUES ('seed-pub-02', 'seed-img-02', 'seed_editorial', 'seed_editorial', 'Seed 2', 'published', '2026-07-01')"
        )
        conn.execute(
            "INSERT INTO users (id, internal_user_id, display_name, role, token_balance, language, created_at, last_login_at) "
            "VALUES ('web_real', 'iuid_real', 'Настоящий пользователь', 'user', 0, 'ru', '2026-07-01', '2026-07-01')"
        )
        conn.execute(
            "INSERT INTO feed_publications (id, image_id, internal_user_id, legacy_user_id, title, status, created_at) "
            "VALUES ('real-pub-01', 'real-img-01', 'iuid_real', 'web_real', 'Real', 'published', '2026-07-01')"
        )

    dry = feed_seed_demo_migrate.migrate_seed_demo_feed(apply=False)
    assert dry["apply"] is False
    assert dry["seed_publications"] == 2

    report = feed_seed_demo_migrate.migrate_seed_demo_feed(apply=True)
    assert report["changed_publications"] == 2
    with main.db() as conn:
        seed = conn.execute(
            "SELECT internal_user_id, legacy_user_id, category, source_label FROM feed_publications WHERE id = 'seed-pub-01'"
        ).fetchone()
        real = conn.execute(
            "SELECT internal_user_id, legacy_user_id FROM feed_publications WHERE id = 'real-pub-01'"
        ).fetchone()
        reactions = conn.execute(
            "SELECT COUNT(*) AS c FROM feed_reactions WHERE publication_id IN ('seed-pub-01', 'seed-pub-02')"
        ).fetchone()["c"]
        authors = conn.execute(
            "SELECT COUNT(*) AS c FROM users WHERE id LIKE 'seed_author_%'"
        ).fetchone()["c"]
        author_avatars = conn.execute(
            """
            SELECT COUNT(*) AS c FROM users
            WHERE id LIKE 'seed_author_%'
              AND avatar_preset LIKE 'avatar-%'
              AND avatar_url LIKE '/avatars/avatar-%.webp'
            """
        ).fetchone()["c"]
    assert seed["internal_user_id"].startswith("seed_author_")
    assert seed["legacy_user_id"].startswith("seed_author_")
    assert seed["category"] == "challenge_moscow_2120"
    assert seed["source_label"] != "Выбор редакции"
    assert real["internal_user_id"] == "iuid_real"
    assert real["legacy_user_id"] == "web_real"
    assert reactions > 0
    assert authors == len(feed_seed_demo_migrate.DEMO_AUTHORS)
    assert author_avatars == len(feed_seed_demo_migrate.DEMO_AUTHORS)
