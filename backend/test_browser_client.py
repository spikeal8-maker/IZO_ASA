"""Regression for BrowserTestClient (AUTH-LEGACY-001B).

Proves the browser-faithful contract end to end against main.app: an https
base URL stores the login cookie, a following unsafe request auto-receives the
allowlisted Origin and passes CSRF, while an explicit foreign Origin is not
replaced and is rejected. Independent of the local TRUSTED_COOKIE_SECURE
setting; temp DB only.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from pathlib import Path
from urllib.parse import urlencode

import pytest

import main
from test_support.browser_client import ALLOWLISTED_BROWSER_ORIGIN, BrowserTestClient

TG_TOKEN = "99999:TEST-browser-client-token"


@pytest.fixture
def temp_db(tmp_path: Path, monkeypatch):
    db_file = tmp_path / "browser_client_test.sqlite3"
    monkeypatch.setattr(main, "DB_PATH", db_file)
    monkeypatch.setattr(main, "TELEGRAM_BOT_TOKEN", TG_TOKEN)
    monkeypatch.setattr(main, "TELEGRAM_INIT_DATA_TTL_SECONDS", 86400)
    main.init_db()
    return db_file


def _telegram_init_data(user_id: int = 4242) -> str:
    user = {"id": user_id, "first_name": "Br", "username": "browser_user"}
    fields = {"auth_date": str(int(time.time())), "user": json.dumps(user, separators=(",", ":"))}
    data_check_string = "\n".join(f"{key}={fields[key]}" for key in sorted(fields))
    secret_key = hmac.new(b"WebAppData", TG_TOKEN.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


def _login(client) -> None:
    response = client.post(
        "/api/auth/telegram-v2",
        json={"init_data": _telegram_init_data(), "platform": "telegram_mini_app"},
    )
    assert response.status_code == 200, response.text


def test_browser_client_uses_https_base_url(temp_db):
    client = BrowserTestClient(main.app)
    assert str(client.base_url).startswith("https://")


def test_login_cookie_is_stored_and_next_mutation_passes_csrf(temp_db):
    with BrowserTestClient(main.app) as client:
        _login(client)
        # The login cookie is held in the browser jar.
        jar_names = {cookie.name for cookie in client.cookies.jar}
        assert main.TRUSTED_SESSION_COOKIE_NAME in jar_names
        # A following unsafe request auto-receives the allowlisted Origin and
        # is handled by the route (idempotent logout) instead of a CSRF 403.
        logout = client.post("/api/auth/session/logout-v2", json={})
    assert logout.status_code == 200
    assert logout.json().get("detail") != "Cross-site request blocked."


def test_browser_client_does_not_replace_explicit_foreign_origin(temp_db):
    with BrowserTestClient(main.app) as client:
        _login(client)
        blocked = client.post(
            "/api/auth/session/logout-v2",
            json={},
            headers={"Origin": "https://evil.example"},
        )
    assert blocked.status_code == 403
    assert blocked.json() == {"detail": "Cross-site request blocked."}


def test_browser_client_adds_no_origin_without_sensitive_cookie(temp_db):
    # No login: an anonymous unsafe request is not decorated with an Origin and
    # keeps the route's own behavior (401), not an injected CSRF 403.
    with BrowserTestClient(main.app) as client:
        response = client.post("/api/generate", json={"mode": "text_to_image", "prompt": "x"})
    assert response.status_code == 401


def test_browser_client_origin_value_is_allowlisted(temp_db):
    assert ALLOWLISTED_BROWSER_ORIGIN in main.CORS_ALLOWED_ORIGINS
