"""AUTH-LEGACY-001A: characterization of legacy authorization boundaries.

These tests PROVE current behavior without changing it: spoofable legacy
inputs (X-OneNode-User header, onenode_user cookie), unsigned provider data
and missing sessions must never produce trusted identity; webhooks keep their
own provider-secret boundary. Static tests pin the exact remaining legacy
consumers so any drift from architecture/contract.json fails loudly.

Temp DB only; fake tokens; no real provider traffic.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import main

ROOT = Path(__file__).resolve().parents[1]
SPOOF_ADMIN_ID = "telegram_admin_spoof"


@pytest.fixture
def temp_db(tmp_path: Path, monkeypatch):
    db_file = tmp_path / "auth_characterization.sqlite3"
    monkeypatch.setattr(main, "DB_PATH", db_file)
    monkeypatch.setattr(main, "TELEGRAM_BOT_TOKEN", "test-telegram-token")
    monkeypatch.setattr(main, "MAX_BOT_TOKEN", "test-max-token")
    main.init_db()
    # A real admin row exists so a successful spoof would be observable.
    now = "2026-07-20T00:00:00+00:00"
    with main.db() as conn:
        conn.execute(
            "INSERT INTO users (id, internal_user_id, language, role, created_at, last_login_at) "
            "VALUES (?, 'iuid-admin-spoof', 'ru', 'admin', ?, ?)",
            (SPOOF_ADMIN_ID, now, now),
        )
    return db_file


# --- 1-4: spoofed legacy header/cookie never authorize user or admin routes ---

def test_spoofed_header_does_not_grant_user_route(temp_db):
    with TestClient(main.app) as client:
        response = client.get("/api/me-v2", headers={"X-OneNode-User": SPOOF_ADMIN_ID})
    assert response.status_code == 401


def test_spoofed_header_with_admin_id_does_not_grant_admin_route(temp_db):
    with TestClient(main.app) as client:
        read = client.get("/api/admin/users-v2", headers={"X-OneNode-User": SPOOF_ADMIN_ID})
        mutation = client.put(
            "/api/admin/bots/config-v2",
            json={"config": {}},
            headers={"X-OneNode-User": SPOOF_ADMIN_ID},
        )
    assert read.status_code == 401
    assert mutation.status_code == 401


def test_spoofed_cookie_does_not_grant_user_route(temp_db):
    with TestClient(main.app) as client:
        client.cookies.set("onenode_user", SPOOF_ADMIN_ID)
        response = client.get("/api/me-v2")
    assert response.status_code == 401


def test_spoofed_cookie_with_admin_id_does_not_grant_admin_route(temp_db):
    with TestClient(main.app) as client:
        client.cookies.set("onenode_user", SPOOF_ADMIN_ID)
        read = client.get("/api/admin/users-v2")
        mutation = client.put("/api/admin/bots/config-v2", json={"config": {}})
    assert read.status_code == 401
    assert mutation.status_code == 401


# --- 5-6: unsigned provider data never creates trusted identity ---

def test_unsigned_or_corrupted_telegram_init_data_creates_no_identity(temp_db):
    assert main.validate_telegram_init_data("user=%7B%22id%22%3A1%7D&auth_date=1") is None
    assert main.validate_telegram_init_data("user=x&auth_date=1&hash=deadbeef") is None
    with TestClient(main.app) as client:
        response = client.post(
            "/api/auth/telegram-v2",
            json={"platform": "telegram_mini_app", "init_data": "user=x&auth_date=1&hash=deadbeef"},
        )
    assert response.status_code == 401
    with main.db() as conn:
        assert conn.execute("SELECT COUNT(*) AS c FROM auth_sessions").fetchone()["c"] == 0


def test_unverified_or_corrupted_max_web_app_data_creates_no_identity(temp_db):
    with pytest.raises(main.MaxAuthError):
        main.validate_max_web_app_data_strict("user=x&auth_date=1&hash=deadbeef")
    with TestClient(main.app) as client:
        response = client.post(
            "/api/auth/max-v2",
            json={"platform": "max_mini_app", "web_app_data": "user=x&auth_date=1&hash=deadbeef"},
        )
    assert response.status_code == 401
    with main.db() as conn:
        assert conn.execute("SELECT COUNT(*) AS c FROM auth_sessions").fetchone()["c"] == 0


# --- 7-8: protected mutations without trusted sessions are rejected ---

def test_protected_mutation_without_session_is_rejected(temp_db):
    with TestClient(main.app) as client:
        response = client.post("/api/generate", json={"mode": "text_to_image", "prompt": "x"})
    assert response.status_code == 401


def test_admin_mutation_without_trusted_admin_session_is_rejected(temp_db):
    with TestClient(main.app) as client:
        response = client.put("/api/admin/bots/config-v2", json={"config": {}})
    assert response.status_code == 401


# --- 9: webhooks keep a provider-secret boundary, legacy id is irrelevant ---

def test_telegram_webhook_requires_provider_secret_not_legacy_id(temp_db, monkeypatch):
    with TestClient(main.app) as client:
        disabled = client.post("/api/telegram/webhook", json={}, headers={"X-OneNode-User": SPOOF_ADMIN_ID})
        assert disabled.status_code == 404, "polling mode must keep the receiver disabled"
    monkeypatch.setattr(main, "BOT_UPDATES_MODE", "webhook")
    monkeypatch.setattr(main, "TELEGRAM_WEBHOOK_SECRET", "expected-telegram-secret")
    with TestClient(main.app) as client:
        spoofed = client.post(
            "/api/telegram/webhook",
            json={},
            headers={
                "X-OneNode-User": SPOOF_ADMIN_ID,
                "X-Telegram-Bot-Api-Secret-Token": "wrong-secret",
            },
        )
    assert spoofed.status_code == 403


def test_max_webhook_requires_provider_secret_not_legacy_id(temp_db, monkeypatch):
    monkeypatch.setattr(main, "MAX_UPDATES_MODE", "webhook")
    monkeypatch.setattr(main, "MAX_WEBHOOK_SECRET", "expected-max-secret-value")
    with TestClient(main.app) as client:
        spoofed = client.post(
            "/api/max/webhook",
            json={},
            headers={"X-OneNode-User": SPOOF_ADMIN_ID, "X-Max-Bot-Api-Secret": "wrong-secret"},
        )
    assert spoofed.status_code == 403


def test_yookassa_webhook_ignores_legacy_id(temp_db):
    with TestClient(main.app) as client:
        response = client.post(
            "/api/billing/yookassa/webhook-v2",
            json={"event": "", "object": {}},
            headers={"X-OneNode-User": SPOOF_ADMIN_ID},
        )
    # Not configured (503) or invalid event (400); never authorized by a
    # legacy id and never a 2xx state change.
    assert response.status_code in (400, 503)


# --- 10: request_user_id still exists — pin behavior, prove zero route callers ---

def test_request_user_id_compatibility_behavior_is_pinned(temp_db, monkeypatch):
    monkeypatch.setattr(main, "APP_ENV", "development")
    assert main.request_user_id(None) == "demo_user"
    assert callable(main.require_admin)


def _route_handlers_and_calls() -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    tree = ast.parse((ROOT / "backend" / "main.py").read_text(encoding="utf-8"))
    handler_calls: dict[str, set[str]] = {}
    all_function_calls: dict[str, set[str]] = {}
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        calls = {
            inner.func.id
            for inner in ast.walk(node)
            if isinstance(inner, ast.Call) and isinstance(inner.func, ast.Name)
        }
        all_function_calls[node.name] = calls
        is_route = any(
            isinstance(decorator, ast.Call)
            and isinstance(decorator.func, ast.Attribute)
            and isinstance(decorator.func.value, ast.Name)
            and decorator.func.value.id == "app"
            for decorator in node.decorator_list
        )
        if is_route:
            handler_calls[node.name] = calls
    return handler_calls, all_function_calls


def test_no_route_handler_calls_the_legacy_authorizers() -> None:
    handler_calls, all_function_calls = _route_handlers_and_calls()
    assert handler_calls, "route handlers must be discoverable"
    offenders = {
        name: sorted(calls & {"request_user_id", "require_admin"})
        for name, calls in handler_calls.items()
        if calls & {"request_user_id", "require_admin"}
    }
    assert not offenders, f"protected routes must not use legacy authorizers: {offenders}"
    request_user_id_callers = {
        name for name, calls in all_function_calls.items() if "request_user_id" in calls
    }
    assert request_user_id_callers == {"require_admin"}, (
        "request_user_id may only be reached through the frozen require_admin helper"
    )
    require_admin_callers = {
        name for name, calls in all_function_calls.items() if "require_admin" in calls
    }
    assert require_admin_callers == set(), "nothing may call the legacy require_admin"


# --- 11: every route is classified ---

KNOWN_POLICIES = {
    "public/optional/review",
    "user",
    "admin",
    "session",
    "webhook: telegram secret required",
    "webhook: MAX secret conditional",
}


def test_every_route_is_classified_in_the_symbol_map() -> None:
    text = (ROOT / "backend" / "SYMBOL_MAP.md").read_text(encoding="utf-8")
    rows = re.findall(
        r"^\| (GET|POST|PUT|DELETE|PATCH) \| `([^`]+)` \| `([^`]+)` \| \d+ \| ([^|]+) \|$",
        text,
        re.M,
    )
    assert len(rows) >= 200, "route table must be present and complete"
    unclassified = [path for _, path, _, policy in rows if not policy.strip()]
    assert not unclassified
    review_handlers = {
        handler for _, _, handler, policy in rows if policy.strip().startswith("REVIEW")
    }
    unknown = {
        policy.strip()
        for _, _, _, policy in rows
        if not policy.strip().startswith("REVIEW") and policy.strip() not in KNOWN_POLICIES
    }
    assert not unknown, f"unknown route policies need classification: {unknown}"
    import json

    contract = json.loads((ROOT / "architecture" / "contract.json").read_text(encoding="utf-8"))
    allowlisted = {entry["handler"] for entry in contract["reviewed_routes"]}
    assert review_handlers == allowlisted, (
        "REVIEW-marked routes must exactly match contract.json reviewed_routes"
    )


# --- 12: legacy inputs appear only at the registered compat/audit points ---

def test_legacy_inputs_exist_only_at_registered_consumers() -> None:
    main_source = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
    permissions_source = (
        ROOT / "backend" / "app" / "security" / "permissions.py"
    ).read_text(encoding="utf-8")

    header_reads = re.findall(r'headers\.get\(\s*"[Xx]-[Oo]ne[Nn]ode-[Uu]ser"', main_source)
    cookie_reads = re.findall(r'cookies\.get\(\s*"onenode_user"', main_source)
    cookie_sets = re.findall(r'set_cookie\(\s*"onenode_user"', main_source)
    cookie_deletes = re.findall(r'delete_cookie\(\s*"onenode_user"', main_source)
    audit_reads = re.findall(r'[Xx]-[Oo]ne[Nn]ode-[Uu]ser', permissions_source)

    assert len(header_reads) == 1, "exactly one header read (request_user_id) in main.py"
    assert len(cookie_reads) == 1, "exactly one cookie read (request_user_id) in main.py"
    assert len(cookie_sets) == 1, "exactly one compat cookie_set (bootstrap)"
    assert len(cookie_deletes) == 1, "exactly one compat cookie_delete (web_login)"
    assert audit_reads, "permissions.py keeps the audit-only header read"

    other_backend_files = [
        path
        for path in (ROOT / "backend" / "app").rglob("*.py")
        if path.name != "permissions.py"
    ]
    for path in other_backend_files:
        source = path.read_text(encoding="utf-8")
        assert "onenode_user" not in source.lower().replace("x-onenode-user", ""), path
        assert "x-onenode-user" not in source.lower(), path
