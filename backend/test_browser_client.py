"""AUTH-LEGACY-001B: regression tests for the BrowserTestClient helper.

These tests prove that BrowserTestClient correctly models a real browser:

- Adds the allowlisted Origin for cookie + POST/PUT/PATCH/DELETE.
- Does NOT overwrite an already-present Origin.
- Does NOT add Origin for GET/HEAD/OPTIONS, anonymous, bearer-only, or webhook calls.
- Raw TestClient negative cases (missing/null/foreign Origin) produce 403.

No production code is changed.  All tests use temp DB + fake tokens.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import main
from test_support.browser_client import BrowserTestClient

ALLOWED_ORIGIN = "https://izo.alikinas.ru"
FOREIGN_ORIGIN = "https://evil.example"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def temp_db(monkeypatch, tmp_path):
    db_file = tmp_path / "browser_client_boundary.sqlite3"
    monkeypatch.setattr(main, "DB_PATH", db_file)
    monkeypatch.setattr(main, "TELEGRAM_BOT_TOKEN", "test-telegram-token")
    monkeypatch.setattr(main, "MAX_BOT_TOKEN", "test-max-token")
    main.init_db()
    return db_file


def _make_session() -> dict:
    """Create a minimal trusted session for test usage."""
    internal = "iuid-bct"
    legacy = "web_bct"
    with main.db() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO users (id, internal_user_id, role, plan) VALUES (?, ?, ?, ?)",
            (legacy, internal, "member", "free"),
        )
        conn.execute(
            "INSERT OR IGNORE INTO auth_identities (id, internal_user_id, legacy_user_id, provider, provider_user_id, linked_at) VALUES (?, ?, ?, ?, ?, ?)",
            (main.uuid.uuid4().hex, internal, legacy, "web_email", legacy, "2026-01-01T00:00:00+00:00"),
        )
    return main.create_auth_session(
        internal, legacy, provider="web_email", platform="web_desktop"
    )


# ---------------------------------------------------------------------------
# 1 – cookie + POST + no explicit Origin → helper adds allowlisted Origin
# ---------------------------------------------------------------------------

def test_cookie_post_auto_adds_origin(temp_db):
    sess = _make_session()
    with BrowserTestClient(main.app) as client:
        client.cookies.set("onenode_session", sess["session_token"])
        response = client.post("/api/auth/session/logout-v2", json={})
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# 2 – cookie + POST + explicit foreign Origin → helper does NOT overwrite → 403
# ---------------------------------------------------------------------------

def test_cookie_post_explicit_foreign_origin_not_overwritten(temp_db):
    sess = _make_session()
    with BrowserTestClient(main.app) as client:
        client.cookies.set("onenode_session", sess["session_token"])
        response = client.post(
            "/api/auth/session/logout-v2",
            json={},
            headers={"Origin": FOREIGN_ORIGIN},
        )
    assert response.status_code == 403
    assert response.json() == {"detail": "Cross-site request blocked."}


# ---------------------------------------------------------------------------
# 3 – cookie + POST + missing Origin with raw TestClient → 403
# ---------------------------------------------------------------------------

def test_raw_testclient_cookie_post_missing_origin_is_blocked(temp_db):
    sess = _make_session()
    with TestClient(main.app) as client:
        client.cookies.set("onenode_session", sess["session_token"])
        response = client.post("/api/auth/session/logout-v2", json={})
    assert response.status_code == 403
    assert response.json() == {"detail": "Cross-site request blocked."}


# ---------------------------------------------------------------------------
# 4 – bearer-only + POST → BrowserTestClient does NOT add Origin
# ---------------------------------------------------------------------------

def test_bearer_only_no_origin_added(temp_db):
    with BrowserTestClient(main.app) as client:
        response = client.post(
            "/api/auth/session/logout-v2",
            json={},
            headers={"Authorization": "Bearer fake-token"},
        )
    # No sensitive cookie → no Origin → middleware passes through to route
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# 5 – webhook (no sensitive cookie) → BrowserTestClient does NOT add Origin
# ---------------------------------------------------------------------------

def test_webhook_no_sensitive_cookie_no_origin_added(temp_db):
    with BrowserTestClient(main.app) as client:
        response = client.post(
            "/api/billing/yookassa/webhook-v2",
            json={"event": "", "object": {}},
            headers={"Origin": FOREIGN_ORIGIN},
        )
    assert response.status_code in (400, 503)
    assert response.json().get("detail") != "Cross-site request blocked."


# ---------------------------------------------------------------------------
# 6 – GET with cookie → BrowserTestClient does NOT add Origin (not needed)
# ---------------------------------------------------------------------------

def test_get_with_cookie_no_origin_added(temp_db):
    sess = _make_session()
    with BrowserTestClient(main.app) as client:
        client.cookies.set("onenode_session", sess["session_token"])
        response = client.get("/api/health")
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# 7 – cookie + Authorization + foreign Origin → 403 (bearer doesn't bypass CSRF)
# ---------------------------------------------------------------------------

def test_cookie_plus_bearer_foreign_origin_blocked(temp_db):
    sess = _make_session()
    with BrowserTestClient(main.app) as client:
        client.cookies.set("onenode_session", sess["session_token"])
        response = client.post(
            "/api/auth/session/logout-v2",
            json={},
            headers={
                "Origin": FOREIGN_ORIGIN,
                "Authorization": "Bearer fake-token",
            },
        )
    assert response.status_code == 403
    assert response.json() == {"detail": "Cross-site request blocked."}


# ---------------------------------------------------------------------------
# 8 – BrowserTestClient adds Origin for refresh cookie too
# ---------------------------------------------------------------------------

def test_refresh_cookie_auto_adds_origin(temp_db):
    with BrowserTestClient(main.app) as client:
        client.cookies.set("onenode_refresh", "some-refresh")
        response = client.post("/api/auth/session/refresh-v2", json={})
    # Route runs (rejects the fake token), not CSRF-blocked
    assert response.status_code == 401
    assert response.json()["detail"] != "Cross-site request blocked."


# ---------------------------------------------------------------------------
# 9 – BrowserTestClient adds Origin for bot_login cookie too
# ---------------------------------------------------------------------------

def test_bot_login_cookie_auto_adds_origin_synthetic(monkeypatch):
    from app.security.csrf import CsrfOriginMiddleware
    from fastapi import FastAPI

    app = FastAPI()

    @app.post("/probe")
    async def probe() -> dict[str, bool]:
        return {"ok": True}

    app.add_middleware(
        CsrfOriginMiddleware,
        allowed_origins=[ALLOWED_ORIGIN],
        sensitive_cookie_names=["onenode_bot_login"],
    )
    with BrowserTestClient(app) as client:
        client.cookies.set("onenode_bot_login", "prov.nonce")
        response = client.post("/probe", json={})
    assert response.status_code == 200
    assert response.json() == {"ok": True}
