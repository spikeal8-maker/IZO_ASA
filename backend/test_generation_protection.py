"""Generation endpoint protection tests (Phase 15).

require_trusted_user guards POST /api/generate.
Temporary SQLite DB via monkeypatching main.DB_PATH; working DB never touched.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import main


def count(table, where="", params=()):
    with main.db() as conn:
        return conn.execute(f"SELECT COUNT(*) AS c FROM {table} {where}", params).fetchone()["c"]


def make_trusted_session(iuid, legacy, provider="web_email", platform="web_desktop"):
    session = main.create_auth_session(iuid, legacy, provider=provider, platform=platform)
    return session


@pytest.fixture
def temp_db(tmp_path: Path, monkeypatch):
    db_file = tmp_path / "gen_protection_test.sqlite3"
    monkeypatch.setattr(main, "DB_PATH", db_file)
    monkeypatch.setattr(main, "TRUSTED_COOKIE_SECURE", False)
    monkeypatch.setattr(main, "COMFYUI_BASE_URL", "http://127.0.0.1:9999")
    monkeypatch.setattr(main, "TELEGRAM_BOT_TOKEN", "test")
    # Disable the worker so it doesn't interfere with queue state
    monkeypatch.setattr(main, "worker_started", True)
    main.init_db()
    return db_file


@pytest.fixture
def authed_user(temp_db):
    iuid = "iuid-test-gen"
    legacy = "web_testgen"
    now = "2026-01-01T00:00:00+00:00"
    with main.db() as conn:
        conn.execute(
            "INSERT INTO users (id, internal_user_id, language, role, token_balance, created_at, last_login_at) VALUES (?, ?, 'ru', 'user', 100, ?, ?)",
            (legacy, iuid, now, now),
        )
        conn.execute(
            "INSERT INTO auth_identities (id, internal_user_id, legacy_user_id, provider, provider_user_id, linked_at) VALUES (?, ?, ?, 'web_email', 'test@gen.local', ?)",
            ("id-test-gen", iuid, legacy, now),
        )
    return {"internal_user_id": iuid, "legacy_user_id": legacy}


# 1
def test_generate_no_session_401(temp_db, authed_user):
    with TestClient(main.app) as c:
        r = c.post("/api/generate", json={"mode": "text_to_image", "prompt": "a cat", "width": 512, "height": 512, "steps": 1})
    assert r.status_code == 401


# 2
def test_generate_x_onenode_user_no_session_401(temp_db, authed_user):
    with TestClient(main.app) as c:
        r = c.post("/api/generate", json={"mode": "text_to_image", "prompt": "a cat", "width": 512, "height": 512, "steps": 1}, headers={"X-OneNode-User": authed_user["legacy_user_id"]})
    assert r.status_code == 401


# 3
def test_generate_onenode_user_cookie_no_session_401(temp_db, authed_user):
    with TestClient(main.app) as c:
        r = c.post("/api/generate", json={"mode": "text_to_image", "prompt": "a cat", "width": 512, "height": 512, "steps": 1}, cookies={"onenode_user": authed_user["legacy_user_id"]})
    assert r.status_code == 401


# 4 — spoofed body user_id is irrelevant for v2 (no such field in GenerateRequest)
def test_generate_spoofed_body_ignored(temp_db, authed_user):
    with TestClient(main.app) as c:
        r = c.post("/api/generate", json={"mode": "text_to_image", "prompt": "a cat", "width": 512, "height": 512, "steps": 1, "userId": authed_user["legacy_user_id"]})
    assert r.status_code == 401


# 5
def test_generate_with_valid_session_reaches_worker(temp_db, authed_user):
    sess = make_trusted_session(authed_user["internal_user_id"], authed_user["legacy_user_id"])
    with TestClient(main.app) as c:
        r = c.post("/api/generate", json={"mode": "text_to_image", "prompt": "a cat", "width": 512, "height": 512, "steps": 1}, cookies={"onenode_session": sess["session_token"]})
    assert r.status_code == 200
    body = r.json()
    assert body.get("userId") == authed_user["legacy_user_id"]
    assert "tokenCost" in body
    # job created in SQLite
    jc = count("jobs", "WHERE user_id=?", (authed_user["legacy_user_id"],))
    assert jc >= 1


# 6 — trusted session overrides any spoofed header
def test_trusted_session_overrides_spoofed_header(temp_db, authed_user):
    sess = make_trusted_session(authed_user["internal_user_id"], authed_user["legacy_user_id"])
    with TestClient(main.app) as c:
        r = c.post("/api/generate", json={"mode": "text_to_image", "prompt": "a cat", "width": 512, "height": 512, "steps": 1}, cookies={"onenode_session": sess["session_token"]}, headers={"X-OneNode-User": "hacker"})
    assert r.status_code == 200
    assert r.json()["userId"] == authed_user["legacy_user_id"]


# 7
def test_banned_user_403(temp_db, authed_user):
    with main.db() as conn:
        conn.execute("UPDATE users SET banned=1 WHERE internal_user_id=?", (authed_user["internal_user_id"],))
    sess = make_trusted_session(authed_user["internal_user_id"], authed_user["legacy_user_id"])
    with TestClient(main.app) as c:
        r = c.post("/api/generate", json={"mode": "text_to_image", "prompt": "a cat", "width": 512, "height": 512, "steps": 1}, cookies={"onenode_session": sess["session_token"]})
    assert r.status_code == 403


# 8
def test_unauthenticated_creates_no_job(temp_db, authed_user):
    before = count("jobs")
    with TestClient(main.app) as c:
        r = c.post("/api/generate", json={"mode": "text_to_image", "prompt": "a cat", "width": 512, "height": 512, "steps": 1})
    assert r.status_code == 401
    assert count("jobs") == before


# 9 — unauthenticated creates no image (images table unchanged)
def test_unauthenticated_creates_no_image(temp_db, authed_user):
    before = count("images")
    with TestClient(main.app) as c:
        r = c.post("/api/generate", json={"mode": "text_to_image", "prompt": "a cat", "width": 512, "height": 512, "steps": 1})
    assert r.status_code == 401
    assert count("images") == before


# 10 — unauthenticated spends no tokens
def test_unauthenticated_spends_no_tokens(temp_db, authed_user):
    before = count("token_ledger")
    with TestClient(main.app) as c:
        r = c.post("/api/generate", json={"mode": "text_to_image", "prompt": "a cat", "width": 512, "height": 512, "steps": 1})
    assert r.status_code == 401
    assert count("token_ledger") == before


# 11
def test_successful_generation_writes_event_log(temp_db, authed_user):
    sess = make_trusted_session(authed_user["internal_user_id"], authed_user["legacy_user_id"])
    with TestClient(main.app) as c:
        r = c.post("/api/generate", json={"mode": "text_to_image", "prompt": "a cat", "width": 512, "height": 512, "steps": 1}, cookies={"onenode_session": sess["session_token"]})
    assert r.status_code == 200
    ec = count("event_logs", "WHERE event_name='generation_started' AND internal_user_id=?", (authed_user["internal_user_id"],))
    assert ec == 1


# 12 — prompt not in event_logs
def test_prompt_not_in_event_logs(temp_db, authed_user):
    prompt = "a very specific cat drawing"
    sess = make_trusted_session(authed_user["internal_user_id"], authed_user["legacy_user_id"])
    with TestClient(main.app) as c:
        r = c.post("/api/generate", json={"mode": "text_to_image", "prompt": prompt, "width": 512, "height": 512, "steps": 1}, cookies={"onenode_session": sess["session_token"]})
    assert r.status_code == 200
    with main.db() as conn:
        for row in conn.execute("SELECT properties_json FROM event_logs WHERE event_name='generation_started' AND internal_user_id=?", (authed_user["internal_user_id"],)).fetchall():
            assert prompt not in (row["properties_json"] or "")
        for row in conn.execute("SELECT details_json FROM security_events").fetchall():
            assert prompt not in (row["details_json"] or "")


# 13 — raw cookies/tokens not logged
def test_raw_tokens_not_logged_for_generation(temp_db, authed_user):
    sess = make_trusted_session(authed_user["internal_user_id"], authed_user["legacy_user_id"])
    with TestClient(main.app) as c:
        r = c.post("/api/generate", json={"mode": "text_to_image", "prompt": "a cat", "width": 512, "height": 512, "steps": 1}, cookies={"onenode_session": sess["session_token"]})
    assert r.status_code == 200
    raw = sess["session_token"]
    with main.db() as conn:
        for table in ("event_logs", "security_events"):
            for row in conn.execute(f"SELECT * FROM {table}").fetchall():
                blob = " ".join(str(v) for v in tuple(row))
                assert raw not in blob, f"raw session token leaked into {table}"


# 14 — old request_user_id unchanged
def test_request_user_id_unchanged():
    import inspect
    src = inspect.getsource(main.request_user_id)
    assert "auth_sessions" not in src
    assert "X-OneNode-User" in src
    assert "onenode_user" in src


# 15 — old require_admin unchanged
def test_require_admin_unchanged():
    import inspect
    src = inspect.getsource(main.require_admin)
    assert "request_user_id" in src
    assert "trusted" not in src.lower() or "require_trusted" not in src


# 16 — users.id unchanged after generation
def test_users_id_unchanged_after_generation(temp_db, authed_user):
    with main.db() as conn:
        conn.execute("INSERT INTO users (id, internal_user_id, language, role, created_at, last_login_at) VALUES ('telegram_legacy','iuid-legacy','ru','user','2026-01-01','2026-01-01')")
        before = sorted(r["id"] for r in conn.execute("SELECT id FROM users"))
    sess = make_trusted_session(authed_user["internal_user_id"], authed_user["legacy_user_id"])
    with TestClient(main.app) as c:
        r = c.post("/api/generate", json={"mode": "text_to_image", "prompt": "a cat", "width": 512, "height": 512, "steps": 1}, cookies={"onenode_session": sess["session_token"]})
    assert r.status_code == 200
    with main.db() as conn:
        after = sorted(r["id"] for r in conn.execute("SELECT id FROM users"))
    assert "telegram_legacy" in after
    assert all(i in after for i in before)
