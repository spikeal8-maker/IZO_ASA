"""Isolated router contract; fixture authorization is not a historical login."""

from __future__ import annotations

import secrets

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.api.routers.openrouter_keys import OpenRouterKeyDependencies, create_openrouter_key_router
from app.security.secret_store import SecretStoreError


@pytest.fixture
def api():
    state = {"saved": [], "deleted": 0, "checks": 0, "catalog": 0,
             "provider_ok": True, "source": "linux-aes-gcm", "fail_save": False, "audit": []}

    def require_admin(request):
        if request.headers.get("x-fixture-role") != "admin":
            raise HTTPException(403, "TRUSTED_ADMIN_REQUIRED")
        return {"internal_user_id": 17}

    def save(key):
        if state["fail_save"]:
            raise SecretStoreError("diagnostic must not echo " + key)
        state["saved"].append(key)

    def delete():
        state["deleted"] += 1
        state["saved"].clear()

    async def status():
        state["checks"] += 1
        return {"ok": state["provider_ok"], "configured": bool(state["saved"]) or state["source"] == "env", "source": state["source"]}

    def refresh():
        state["catalog"] += 1
        return True

    app = FastAPI()
    app.include_router(create_openrouter_key_router(OpenRouterKeyDependencies(
        require_trusted_admin=require_admin, save=save, delete=delete, status=status,
        refresh_catalog=refresh, usage=lambda: {}, config=lambda: {},
        audit=lambda actor, action, outcome, request: state["audit"].append({"actor": actor["internal_user_id"], "action": action, "outcome": outcome}),
    )))
    with TestClient(app) as client:
        yield client, state


def _key():
    return "sk-" + "or-" + secrets.token_hex(24)


def test_successful_save_is_distinct_from_provider_verification(api):
    client, state = api
    state["provider_ok"] = False
    key = _key()
    response = client.put("/api/admin/openrouter/key", json={"key": key}, headers={"x-fixture-role": "admin"})
    assert response.status_code == 200
    result = response.json()
    assert result["ok"] is True and result["keySaved"] is True
    assert result["keyVerified"] is False and result["key"]["configured"] is True
    assert state["saved"] == [key] and state["checks"] == state["catalog"] == 1
    assert key not in response.text
    assert state["audit"] == [{"actor": 17, "action": "save", "outcome": "stored"}]
    assert response.headers["Cache-Control"] == "no-store"


def test_storage_failure_cannot_claim_success_or_start_provider_checks(api):
    client, state = api
    state["fail_save"] = True
    key = _key()
    response = client.put("/api/admin/openrouter/key", json={"key": key}, headers={"x-fixture-role": "admin"})
    assert response.status_code == 503
    assert response.json() == {"detail": "OPENROUTER_KEY_SAVE_UNCONFIRMED"}
    assert key not in response.text
    assert state["checks"] == state["catalog"] == 0
    assert state["audit"] == [{"actor": 17, "action": "save", "outcome": "unconfirmed"}]


@pytest.mark.parametrize("kind", ["short", "long", "invalid", "object", "array", "bad-json", "extra"])
def test_invalid_input_never_appears_in_validation_response(api, kind):
    client, state = api
    marker = _key()
    payload = {"short": {"key": "tiny"}, "long": {"key": marker * 30}, "invalid": {"key": marker + "\nheader:value"},
               "object": {"key": {"secret": marker}}, "array": [marker], "extra": {"key": marker, "extra": marker}}
    response = client.put("/api/admin/openrouter/key", content=marker if kind == "bad-json" else __import__("json").dumps(payload[kind]),
                          headers={"x-fixture-role": "admin", "Content-Type": "application/json"})
    assert response.status_code == 422
    assert marker not in response.text and "input" not in response.json()
    assert state["saved"] == [] and state["checks"] == 0


def test_oversized_body_is_rejected_before_parse_and_store(api):
    client, state = api
    response = client.put("/api/admin/openrouter/key", content=b"x" * 2049,
                          headers={"x-fixture-role": "admin", "Content-Type": "application/json"})
    assert response.status_code == 413
    assert state["saved"] == []


@pytest.mark.parametrize("method", ["put", "get", "delete"])
def test_trusted_admin_guard_precedes_input_and_all_operations(api, method):
    client, state = api
    response = client.request(method, "/api/admin/openrouter/key", content=b"private-invalid-body")
    assert response.status_code == 403
    assert "private-invalid-body" not in response.text
    assert state["saved"] == [] and state["deleted"] == state["checks"] == 0


def test_check_is_fresh_read_only_and_never_queues_a_catalog_or_paid_operation(api):
    client, state = api
    for _ in range(2):
        result = client.get("/api/admin/openrouter/key", headers={"x-fixture-role": "admin"})
        assert result.status_code == 200 and result.headers["Cache-Control"] == "no-store"
    assert state["checks"] == 2
    assert state["saved"] == [] and state["deleted"] == state["catalog"] == 0


def test_environment_override_does_not_claim_submitted_key_was_verified(api):
    client, state = api
    state["source"] = "env"
    result = client.put("/api/admin/openrouter/key", json={"key": _key()}, headers={"x-fixture-role": "admin"}).json()
    assert result["keySaved"] is True and result["keyVerified"] is False
    assert result["environmentOverride"] is True
    deleted = client.delete("/api/admin/openrouter/key", headers={"x-fixture-role": "admin"}).json()
    assert deleted["keyRemoved"] is True and deleted["key"]["configured"] is True
    assert deleted["environmentOverride"] is True


def test_wired_application_rejects_anonymous_and_spoofed_legacy_identity(monkeypatch):
    import main

    async def provider_must_not_run(*_args, **_kwargs):
        pytest.fail("provider check ran before trusted authorization")

    monkeypatch.setattr(main, "fetch_openrouter_key_status", provider_must_not_run)
    main.init_db()
    client = TestClient(main.app)
    try:
        for method in ("PUT", "GET", "DELETE"):
            response = client.request(method, "/api/admin/openrouter/key", json={"key": _key()},
                                      headers={"x-onenode-user": "admin", "x-user-role": "admin"})
            assert response.status_code in {401, 403}
        assert not main.OPENROUTER_SECRET_STORE.exists(main.OPENROUTER_SECRET_NAME)
    finally:
        client.close()


@pytest.mark.parametrize("method", ["PUT", "DELETE"])
def test_wired_key_mutations_keep_existing_cookie_csrf_boundary(monkeypatch, method):
    import main

    def handler_must_not_run(_request):
        pytest.fail("cross-site request reached trusted-admin handler")

    monkeypatch.setattr(main, "require_trusted_admin", handler_must_not_run)
    client = TestClient(main.app)
    try:
        client.cookies.set(main.TRUSTED_SESSION_COOKIE_NAME, "fixture-invalid-session")
        response = client.request(method, "/api/admin/openrouter/key", json={"key": _key()},
                                  headers={"Origin": "https://foreign.invalid"})
        assert response.status_code == 403
        assert response.json() == {"detail": "Cross-site request blocked."}
    finally:
        client.close()


def test_existing_static_route_map_sees_full_urls_and_trusted_admin_guard():
    from pathlib import Path
    from app.api.routers import openrouter_keys
    from tools.generate_backend_map import parse_source

    _, routes = parse_source(Path(openrouter_keys.__file__))
    assert {(route.method, route.path, route.auth) for route in routes} == {
        (method, "/api/admin/openrouter/key", "admin") for method in ("PUT", "GET", "DELETE")
    }
