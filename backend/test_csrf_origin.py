"""AUTH-LEGACY-001B: CSRF origin boundary and HTTP middleware composition.

Two layers of proof:

- against the real ``main.app`` (temp DB, fake tokens) — the boundary and the
  preserved webhook/CORS/TrustedHost/body-limit behavior;
- against a small synthetic app built by ``install_http_security_middleware``
  with a stub policy — the exact middleware order, "handler not called on
  rejection", and per-cookie cases without touching real auth flows.

No production DB/media/secrets; no real providers.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import main
from app.security.csrf import CsrfOriginMiddleware
from app.security.http_middleware import install_http_security_middleware

FOREIGN_ORIGIN = "https://evil.example"
SUFFIX_ATTACK_ORIGIN = "https://izo.alikinas.ru.evil.example"
ALLOWED_PROD_ORIGIN = "https://izo.alikinas.ru"


@pytest.fixture
def temp_db(tmp_path: Path, monkeypatch):
    db_file = tmp_path / "csrf_boundary.sqlite3"
    monkeypatch.setattr(main, "DB_PATH", db_file)
    monkeypatch.setattr(main, "TELEGRAM_BOT_TOKEN", "test-telegram-token")
    monkeypatch.setattr(main, "MAX_BOT_TOKEN", "test-max-token")
    main.init_db()
    return db_file


@dataclass(frozen=True)
class StubPolicy:
    cors_allowed_origins: tuple[str, ...] = tuple(main.CORS_ALLOWED_ORIGINS)
    trusted_hosts: tuple[str, ...] = ("testserver", "localhost", "127.0.0.1")
    session_cookie_name: str = main.TRUSTED_SESSION_COOKIE_NAME
    refresh_cookie_name: str = main.TRUSTED_REFRESH_COOKIE_NAME
    bot_login_challenge_cookie_name: str = main.BOT_LOGIN_CHALLENGE_COOKIE_NAME


def build_synthetic_app(max_body_bytes: int = 4096) -> tuple[FastAPI, dict[str, int]]:
    app = FastAPI()
    hits = {"count": 0}

    @app.post("/probe")
    async def probe() -> dict[str, bool]:
        hits["count"] += 1
        return {"ok": True}

    @app.get("/probe")
    async def probe_get() -> dict[str, bool]:
        hits["count"] += 1
        return {"ok": True}

    install_http_security_middleware(
        app, policy=StubPolicy(), request_body_max_bytes=max_body_bytes
    )
    return app, hits


def synthetic_client(max_body_bytes: int = 4096) -> tuple[TestClient, dict[str, int]]:
    app, hits = build_synthetic_app(max_body_bytes)
    return TestClient(app), hits


# --- 1-3: safe methods and cookie-less requests are never CSRF-blocked ---

def test_get_with_cookie_and_foreign_origin_passes_csrf(temp_db):
    with TestClient(main.app) as client:
        client.cookies.set(main.TRUSTED_SESSION_COOKIE_NAME, "some-session")
        response = client.get("/api/health", headers={"Origin": FOREIGN_ORIGIN})
    assert response.status_code == 200


def test_options_preflight_is_not_blocked(temp_db):
    with TestClient(main.app) as client:
        client.cookies.set(main.TRUSTED_SESSION_COOKIE_NAME, "some-session")
        response = client.options(
            "/api/auth/session/logout-v2",
            headers={
                "Origin": FOREIGN_ORIGIN,
                "Access-Control-Request-Method": "POST",
            },
        )
    # CORS middleware answers the preflight (an unallowed origin gets its
    # CORS failure, not the CSRF 403 body).
    assert response.text != '{"detail":"Cross-site request blocked."}'


def test_unsafe_request_without_sensitive_cookie_gets_no_csrf_403(temp_db):
    with TestClient(main.app) as client:
        response = client.post(
            "/api/generate",
            json={"mode": "text_to_image", "prompt": "x"},
            headers={"Origin": FOREIGN_ORIGIN},
        )
    # Existing anonymous behavior is preserved: the route's own 401.
    assert response.status_code == 401
    assert response.json()["detail"] != "Cross-site request blocked."


# --- 4-6: each sensitive cookie with an allowed origin passes the middleware ---

def test_session_cookie_with_allowed_origin_passes(temp_db):
    with TestClient(main.app) as client:
        client.cookies.set(main.TRUSTED_SESSION_COOKIE_NAME, "some-session")
        response = client.post(
            "/api/auth/session/logout-v2", json={}, headers={"Origin": ALLOWED_PROD_ORIGIN}
        )
    assert response.status_code == 200  # idempotent logout ran


def test_refresh_cookie_with_allowed_origin_passes(temp_db):
    with TestClient(main.app) as client:
        client.cookies.set(main.TRUSTED_REFRESH_COOKIE_NAME, "some-refresh")
        response = client.post(
            "/api/auth/session/refresh-v2", json={}, headers={"Origin": ALLOWED_PROD_ORIGIN}
        )
    # The route runs and rejects the fake refresh token itself.
    assert response.status_code == 401
    assert response.json()["detail"] != "Cross-site request blocked."


def test_challenge_cookie_with_allowed_origin_passes(temp_db):
    client, hits = synthetic_client()
    client.cookies.set(main.BOT_LOGIN_CHALLENGE_COOKIE_NAME, "prov.nonce")
    response = client.post("/probe", json={}, headers={"Origin": ALLOWED_PROD_ORIGIN})
    assert response.status_code == 200
    assert hits["count"] == 1


# --- 7-13: cookie-auth unsafe requests with a bad/missing origin get 403 ---

@pytest.mark.parametrize(
    "cookie_name",
    [
        main.TRUSTED_SESSION_COOKIE_NAME,
        main.TRUSTED_REFRESH_COOKIE_NAME,
        main.BOT_LOGIN_CHALLENGE_COOKIE_NAME,
    ],
)
def test_each_sensitive_cookie_with_foreign_origin_is_blocked(temp_db, cookie_name):
    with TestClient(main.app) as client:
        client.cookies.set(cookie_name, "value")
        response = client.post(
            "/api/auth/session/logout-v2", json={}, headers={"Origin": FOREIGN_ORIGIN}
        )
    assert response.status_code == 403
    assert response.json() == {"detail": "Cross-site request blocked."}


def test_sensitive_cookie_with_missing_origin_is_blocked(temp_db):
    with TestClient(main.app) as client:
        client.cookies.set(main.TRUSTED_SESSION_COOKIE_NAME, "value")
        response = client.post("/api/auth/session/logout-v2", json={})
    assert response.status_code == 403


def test_sensitive_cookie_with_null_origin_is_blocked(temp_db):
    with TestClient(main.app) as client:
        client.cookies.set(main.TRUSTED_SESSION_COOKIE_NAME, "value")
        response = client.post(
            "/api/auth/session/logout-v2", json={}, headers={"Origin": "null"}
        )
    assert response.status_code == 403


@pytest.mark.parametrize(
    "bad_origin",
    [
        SUFFIX_ATTACK_ORIGIN,
        "http://izo.alikinas.ru",          # scheme downgrade
        "https://izo.alikinas.ru:8443",    # different port
        "https://user:pass@izo.alikinas.ru",  # userinfo trick
        "https://izo.alikinas.ru/path",    # path instead of clean origin
        "https://izo.alikinas.ru?q=1",     # query instead of clean origin
        "http://127.0.0.1:8000",           # wrong dev port
    ],
)
def test_sensitive_cookie_with_malformed_or_lookalike_origin_is_blocked(temp_db, bad_origin):
    with TestClient(main.app) as client:
        client.cookies.set(main.TRUSTED_SESSION_COOKIE_NAME, "value")
        response = client.post(
            "/api/auth/session/logout-v2", json={}, headers={"Origin": bad_origin}
        )
    assert response.status_code == 403
    assert bad_origin not in response.text, "the received Origin must not be echoed"


# --- 14: bearer-only transport is not CSRF-able; a sensitive cookie always is ---

def test_bearer_without_sensitive_cookie_and_foreign_origin_is_not_csrf_blocked(temp_db):
    with TestClient(main.app) as client:
        response = client.post(
            "/api/auth/session/logout-v2",
            json={},
            headers={"Origin": FOREIGN_ORIGIN, "Authorization": "Bearer fake-token"},
        )
    assert response.status_code == 200
    assert response.json().get("detail") != "Cross-site request blocked."


@pytest.mark.parametrize("origin_headers", [{"Origin": FOREIGN_ORIGIN}, {}])
def test_bearer_with_sensitive_cookie_stays_under_csrf(temp_db, origin_headers):
    # An Authorization header must not disable CSRF when the browser also
    # auto-attaches a sensitive cookie: the ambient credential is the risk.
    with TestClient(main.app) as client:
        client.cookies.set(main.TRUSTED_SESSION_COOKIE_NAME, "value")
        response = client.post(
            "/api/auth/session/logout-v2",
            json={},
            headers={"Authorization": "Bearer fake-token", **origin_headers},
        )
    assert response.status_code == 403
    assert response.json() == {"detail": "Cross-site request blocked."}


# --- 15-16: same-origin dev origins pass ---

@pytest.mark.parametrize("dev_origin", ["http://localhost:5173", "http://127.0.0.1:5173"])
def test_same_origin_dev_hosts_pass(temp_db, dev_origin):
    assert dev_origin in main.CORS_ALLOWED_ORIGINS
    with TestClient(main.app) as client:
        client.cookies.set(main.TRUSTED_SESSION_COOKIE_NAME, "value")
        response = client.post(
            "/api/auth/session/logout-v2", json={}, headers={"Origin": dev_origin}
        )
    assert response.status_code == 200


# --- 17-18: exact rejection payload; handler is never invoked ---

def test_rejection_response_has_exact_safe_json(temp_db):
    with TestClient(main.app) as client:
        client.cookies.set(main.TRUSTED_SESSION_COOKIE_NAME, "value")
        response = client.post(
            "/api/auth/session/logout-v2", json={}, headers={"Origin": FOREIGN_ORIGIN}
        )
    assert response.status_code == 403
    assert response.headers["content-type"] == "application/json"
    assert response.json() == {"detail": "Cross-site request blocked."}


def test_route_handler_is_not_called_on_csrf_rejection():
    client, hits = synthetic_client()
    client.cookies.set(main.TRUSTED_SESSION_COOKIE_NAME, "value")
    response = client.post("/probe", json={}, headers={"Origin": FOREIGN_ORIGIN})
    assert response.status_code == 403
    assert hits["count"] == 0, "the route handler must never run on rejection"


# --- 19-21: webhooks without browser cookies keep their own boundaries ---

def test_telegram_webhook_keeps_provider_secret_behavior(temp_db, monkeypatch):
    monkeypatch.setattr(main, "BOT_UPDATES_MODE", "webhook")
    monkeypatch.setattr(main, "TELEGRAM_WEBHOOK_SECRET", "expected-telegram-secret")
    with TestClient(main.app) as client:
        response = client.post(
            "/api/telegram/webhook",
            json={},
            headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"},
        )
    assert response.status_code == 403
    assert "Invalid Telegram webhook secret." in response.text


def test_max_webhook_keeps_provider_secret_behavior(temp_db, monkeypatch):
    monkeypatch.setattr(main, "MAX_UPDATES_MODE", "webhook")
    monkeypatch.setattr(main, "MAX_WEBHOOK_SECRET", "expected-max-secret-value")
    with TestClient(main.app) as client:
        response = client.post(
            "/api/max/webhook", json={}, headers={"X-Max-Bot-Api-Secret": "wrong"}
        )
    assert response.status_code == 403
    assert "Invalid MAX webhook secret." in response.text


def test_yookassa_webhook_keeps_existing_behavior(temp_db):
    with TestClient(main.app) as client:
        response = client.post("/api/billing/yookassa/webhook-v2", json={"event": "", "object": {}})
    assert response.status_code in (400, 503)
    assert response.json().get("detail") != "Cross-site request blocked."


# --- 22-24: preserved behavior of the pre-existing middleware ---

def test_request_body_limit_still_returns_413():
    client, _ = synthetic_client(max_body_bytes=64)
    response = client.post("/probe", content=b"x" * 4096, headers={"Content-Type": "application/json"})
    assert response.status_code == 413


def test_trusted_host_still_blocks_foreign_host():
    client, hits = synthetic_client()
    response = client.get("/probe", headers={"Host": "evil.example"})
    assert response.status_code == 400
    assert hits["count"] == 0


def test_cors_preflight_still_works_for_allowed_origin(temp_db):
    with TestClient(main.app) as client:
        response = client.options(
            "/api/auth/session/logout-v2",
            headers={
                "Origin": ALLOWED_PROD_ORIGIN,
                "Access-Control-Request-Method": "POST",
            },
        )
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == ALLOWED_PROD_ORIGIN


# --- 25: the effective middleware order is pinned, not assumed ---

def test_effective_middleware_order_is_exactly_as_required():
    app, _ = build_synthetic_app()
    order = [m.cls.__name__ for m in app.user_middleware]
    assert order == [
        "RequestBodyLimitMiddleware",
        "TrustedHostMiddleware",
        "CORSMiddleware",
        "CsrfOriginMiddleware",
    ], "user_middleware lists outermost first; composition must not drift"
    production_order = [m.cls.__name__ for m in main.app.user_middleware]
    assert production_order == order


def test_csrf_middleware_ignores_lookalike_cookie_names():
    app = FastAPI()

    @app.post("/probe")
    async def probe() -> dict[str, bool]:
        return {"ok": True}

    app.add_middleware(
        CsrfOriginMiddleware,
        allowed_origins=["https://izo.alikinas.ru"],
        sensitive_cookie_names=["onenode_session"],
    )
    client = TestClient(app)
    client.cookies.set("onenode_session_lookalike", "value")
    response = client.post("/probe", json={}, headers={"Origin": FOREIGN_ORIGIN})
    assert response.status_code == 200, "only exact cookie names are sensitive"
