from __future__ import annotations

import os
import time

import pytest
from fastapi.testclient import TestClient

import main


_GITHUB_ACTIONS_TIMING_MULTIPLIER = 4.0


def _gallery_timing_limit(local_seconds: float) -> float:
    if os.environ.get("GITHUB_ACTIONS", "").strip().lower() == "true":
        return local_seconds * _GITHUB_ACTIONS_TIMING_MULTIPLIER
    return local_seconds


def test_gallery_load_timing_limit_is_strict_locally_and_bounded_on_github(monkeypatch) -> None:
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    assert _gallery_timing_limit(1.0) == 1.0
    assert _gallery_timing_limit(3.0) == 3.0

    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    assert _gallery_timing_limit(1.0) == 4.0
    assert _gallery_timing_limit(3.0) == 12.0


def _seed_gallery(tmp_path, monkeypatch, count: int) -> str:
    monkeypatch.setattr(main, "DB_PATH", tmp_path / f"gallery-load-{count}.sqlite3")
    monkeypatch.setattr(main, "MEDIA", tmp_path / "media")
    main.MEDIA.mkdir()
    main.init_db()
    now = "2026-07-12T00:00:00+00:00"
    with main.db() as conn:
        conn.execute(
            "INSERT INTO users (id, internal_user_id, language, role, plan, gallery_enabled, created_at, last_login_at) "
            "VALUES ('load-user', 'load-iuid', 'ru', 'user', 'business', 1, ?, ?)",
            (now, now),
        )
        conn.executemany(
            "INSERT INTO images (id, user_id, job_id, url, thumbnail_url, width, height, mode, provider, "
            "prompt_original, settings_json, created_at) VALUES (?, 'load-user', ?, ?, ?, ?, ?, 'text_to_image', "
            "'benchmark', ?, ?, ?)",
            [
                (
                    f"load-image-{index:04d}",
                    f"load-job-{index:04d}",
                    f"/api/media/load-{index:04d}.webp?userId=load-user",
                    f"/api/media/load-{index:04d}-thumb.webp?userId=load-user",
                    1024 if index % 3 else 1536,
                    1024 if index % 2 else 768,
                    f"benchmark {'needle' if index % 10 == 0 else 'gallery'} {index}",
                    '{"modelProfile":"gpt-image-2"}',
                    f"2026-07-12T00:{index // 60:02d}:{index % 60:02d}+00:00",
                )
                for index in range(count)
            ],
        )
    return main.create_auth_session("load-iuid", "load-user", provider="web", platform="web")["session_token"]


@pytest.mark.parametrize("count", [10, 100, 500])
def test_gallery_cursor_load_profiles(tmp_path, monkeypatch, count, capsys):
    token = _seed_gallery(tmp_path, monkeypatch, count)
    client = TestClient(main.app)
    headers = {"Authorization": f"Bearer {token}"}

    started = time.perf_counter()
    response = client.get("/api/gallery/items?limit=24", headers=headers)
    first_page_seconds = time.perf_counter() - started
    assert response.status_code == 200
    payload = response.json()
    assert len(payload["items"]) == min(24, count)

    seen = {item["id"] for item in payload["items"]}
    cursor = payload["nextCursor"]
    pages = 1
    scan_started = time.perf_counter()
    while cursor:
        page = client.get(f"/api/gallery/items?limit=24&cursor={cursor}", headers=headers)
        assert page.status_code == 200
        page_payload = page.json()
        page_ids = [item["id"] for item in page_payload["items"]]
        assert len(page_ids) <= 24
        assert not seen.intersection(page_ids)
        seen.update(page_ids)
        cursor = page_payload["nextCursor"]
        pages += 1
    scan_seconds = time.perf_counter() - scan_started

    search_started = time.perf_counter()
    search = client.get("/api/gallery/items?limit=60&q=needle", headers=headers)
    search_seconds = time.perf_counter() - search_started
    assert search.status_code == 200
    assert len(search.json()["items"]) == (count + 9) // 10
    assert len(seen) == count
    assert first_page_seconds < _gallery_timing_limit(1.0)
    assert scan_seconds < _gallery_timing_limit(3.0)
    assert search_seconds < _gallery_timing_limit(1.0)
    secondary_seconds = 0.0
    if count == 500:
        secondary_started = time.perf_counter()
        secondary = client.get("/api/gallery/secondary?limit=24", headers=headers)
        secondary_seconds = time.perf_counter() - secondary_started
        assert secondary.status_code == 200
        assert "items" not in secondary.json()
        assert secondary_seconds < _gallery_timing_limit(1.0)
        compatibility = client.get("/api/gallery/page?limit=24", headers=headers)
        assert compatibility.status_code == 200
        assert len(compatibility.json()["items"]) == 24
    print(
        f"gallery-load count={count} pages={pages} first={first_page_seconds:.4f}s "
        f"scan={scan_seconds:.4f}s search={search_seconds:.4f}s secondary={secondary_seconds:.4f}s"
    )
