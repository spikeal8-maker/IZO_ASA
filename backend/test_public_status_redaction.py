"""SEC-DIAG-001: anonymous status endpoints must not expose operator data.

`/api/platforms` and `/api/bots/status` are unauthenticated product surfaces.
They must never reveal database location, provider token presence, webhook or
internal service URLs, TLS/proxy details or polling diagnostics. The full
operator picture stays in `/api/admin/bots/status-v2` behind
`require_trusted_admin`.
"""
from __future__ import annotations

import json
import re

from fastapi.testclient import TestClient

import main

FORBIDDEN_KEYS = {
    "database",
    "tokens",
    "publicUrls",
    "manualWebhookDisable",
    "mode",
    "domainRequired",
    "apiBaseUrl",
    "tlsTrustStore",
    "pollingReady",
    "webhookReady",
    "webhookSecretConfigured",
    "webhookConfigured",
    "webhookUrlSet",
    "subscriptionStatus",
    "updateTypes",
    "updatesStatus",
    "lastUpdatesError",
    "deepLinkBaseSource",
    "apiMeStatus",
    "botNicknameResolved",
    "path",
}


def _all_keys(payload: object) -> set[str]:
    keys: set[str] = set()
    if isinstance(payload, dict):
        for key, value in payload.items():
            keys.add(str(key))
            keys |= _all_keys(value)
    elif isinstance(payload, list):
        for item in payload:
            keys |= _all_keys(item)
    return keys


def test_platforms_payload_is_product_safe() -> None:
    with TestClient(main.app) as client:
        response = client.get("/api/platforms")
    assert response.status_code == 200
    payload = response.json()

    assert payload["web"]["ready"] is True
    assert payload["telegram"]["ready"] is True
    assert payload["max"]["ready"] is True
    assert payload["telegram"]["commands"] == ["/start", "/app", "/help", "/gallery", "/settings"]
    assert payload["max"]["buttonText"] == "Открыть генератор"

    serialized = json.dumps(payload, ensure_ascii=False)
    assert "database" not in payload
    assert not re.search(r"[A-Za-z]:\\\\?", serialized), "absolute Windows path leaked"
    assert "sqlite" not in serialized.lower()
    assert "DB_PATH" not in serialized


def test_bots_status_payload_is_minimal_public_product_status() -> None:
    with TestClient(main.app) as client:
        response = client.get("/api/bots/status")
    assert response.status_code == 200
    payload = response.json()

    assert payload["ok"] is True
    assert payload["platforms"]["telegram"]["ready"] is True
    assert payload["platforms"]["max"]["commands"] == ["/start", "/app", "/help", "/gallery", "/settings"]

    leaked = _all_keys(payload) & FORBIDDEN_KEYS
    assert not leaked, f"operator diagnostics leaked into public payload: {sorted(leaked)}"

    serialized = json.dumps(payload, ensure_ascii=False)
    assert "127.0.0.1" not in serialized
    assert "webhook" not in serialized.lower()
    assert "token" not in serialized.lower()
    assert "https://platform-api" not in serialized


def test_public_payload_hides_configured_internal_urls(monkeypatch) -> None:
    monkeypatch.setenv("BACKEND_PUBLIC_URL", "http://10.20.30.40:8000")
    with TestClient(main.app) as client:
        platforms = client.get("/api/platforms").json()
        bots = client.get("/api/bots/status").json()
    combined = json.dumps([platforms, bots], ensure_ascii=False)
    assert "10.20.30.40" not in combined
    assert "/api/telegram/webhook" not in combined
    assert "/api/max/webhook" not in combined


def test_admin_bot_diagnostics_require_trusted_admin() -> None:
    with TestClient(main.app) as client:
        response = client.get("/api/admin/bots/status-v2")
    assert response.status_code == 401
