from __future__ import annotations

import asyncio
import json
import secrets

import httpx
import pytest
import main

from app.integrations.openrouter_key_status import fetch_openrouter_key_details


def _run(handler):
    return asyncio.run(fetch_openrouter_key_details(
        base_url="https://openrouter.test/api/v1",
        key_headers={"Authorization": "Bearer fixture"}, credits_headers={},
        transport=httpx.MockTransport(handler),
    ))


def test_normal_key_stays_verified_when_credits_requires_management_scope():
    paths = []

    def handler(request):
        paths.append(request.url.path)
        if request.url.path.endswith("/key"):
            return httpx.Response(200, json={"data": {"usage_monthly": 2, "limit": None, "is_free_tier": False}})
        return httpx.Response(403, json={"error": {"message": "management key required"}})

    result = _run(handler)
    assert result["ok"] is True
    assert result["credits"]["ok"] is False
    assert result["credits"]["error_code"] == "MANAGEMENT_SCOPE_REQUIRED"
    assert paths == ["/api/v1/key", "/api/v1/credits"]


def test_provider_strings_and_unlisted_fields_never_reach_status():
    marker = "sk-" + "or-" + secrets.token_hex(24)

    def handler(request):
        if request.url.path.endswith("/key"):
            return httpx.Response(200, json={"data": {"label": marker, "token": marker,
                "usage": 2, "limit": marker, "is_free_tier": marker, "unexpected": {"value": marker}}})
        return httpx.Response(200, json={"data": {"total_credits": 20, "total_usage": 2, "token": marker}})

    result = _run(handler)
    assert result["data"] == {"usage": 2}
    assert result["credits"]["calculated_balance"] == 18
    assert marker not in json.dumps(result)


@pytest.mark.parametrize("code", [301, 302, 400, 401, 403, 429, 500, 503])
def test_provider_error_body_is_not_reflected_or_redirected(code):
    marker = secrets.token_hex(24)
    seen = []

    def handler(request):
        seen.append(str(request.url))
        return httpx.Response(code, json={"error": {"message": marker}}, headers={"Location": "https://untrusted.invalid/" + marker})

    result = _run(handler)
    assert result["ok"] is False
    assert result["status_code"] == code
    assert marker not in json.dumps(result)
    assert len(seen) == 1


@pytest.mark.parametrize("content", [b"not-json", b"[]", b'{"data":[]}', b"x" * 65537],
                         ids=["invalid-json", "nonobject-root", "nonobject-data", "oversized-65537-bytes"])
def test_invalid_or_oversized_provider_payload_is_safe(content):
    result = _run(lambda _request: httpx.Response(200, content=content))
    assert result["ok"] is False
    assert result["error_code"] == "PROVIDER_CHECK_UNAVAILABLE"


def test_transport_exception_does_not_echo_request_details():
    marker = secrets.token_hex(24)

    def handler(_request):
        raise httpx.ConnectError("Authorization: " + marker)

    result = _run(handler)
    assert result["ok"] is False
    assert marker not in json.dumps(result)


def test_credits_transport_failure_does_not_invalidate_successful_key():
    def handler(request):
        if request.url.path.endswith("/key"):
            return httpx.Response(200, json={"data": {"limit": 10}})
        raise httpx.ReadTimeout("private upstream detail")

    result = _run(handler)
    assert result["ok"] is True
    assert result["credits"]["ok"] is False
    assert "private upstream detail" not in json.dumps(result)


@pytest.mark.parametrize("payload", [{}, {"error": {"code": 401}}, {"data": {}}, {"data": {"unknown": True}}])
def test_http_200_without_valid_key_schema_does_not_verify_a_key(payload):
    result = _run(lambda _request: httpx.Response(200, json=payload))
    assert result["ok"] is False


def test_key_details_preserve_paths_headers_data_and_calculated_balance():
    seen: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path.endswith("/key"):
            return httpx.Response(200, json={"data": {"limit": 10, "usage": 2}})
        return httpx.Response(200, json={"data": {"total_credits": 10.125, "total_usage": 2.1}})

    result = asyncio.run(fetch_openrouter_key_details(
        base_url="https://openrouter.test/api/v1/",
        key_headers={"Authorization": "Bearer key-request"},
        credits_headers={"Authorization": "Bearer credits-request"},
        timeout_seconds=15,
        transport=httpx.MockTransport(handler),
    ))

    assert result == {
        "ok": True,
        "status_code": 200,
        "data": {"limit": 10, "usage": 2},
        "credits": {
            "ok": True,
            "status_code": 200,
            "data": {"total_credits": 10.125, "total_usage": 2.1},
            "calculated_balance": 8.025,
        },
    }
    assert [request.url.path for request in seen] == ["/api/v1/key", "/api/v1/credits"]
    assert seen[0].headers["Authorization"] == "Bearer key-request"
    assert seen[1].headers["Authorization"] == "Bearer credits-request"


def test_key_details_reject_error_without_reflecting_provider_body():
    seen: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        if request.url.path.endswith("/key"):
            return httpx.Response(401, json={"error": {"message": "invalid key"}})
        return httpx.Response(200, json={"data": {"total_credits": 100, "total_usage": 1}})

    result = asyncio.run(fetch_openrouter_key_details(
        base_url="https://openrouter.test/api/v1",
        key_headers={},
        credits_headers={},
        transport=httpx.MockTransport(handler),
    ))

    assert seen == ["/api/v1/key"]
    assert result == {
        "ok": False,
        "status_code": 401,
        "error_code": "KEY_ACCESS_REJECTED",
        "error": "OpenRouter не подтвердил доступ ключа.",
    }


def test_key_details_preserve_nested_credits_error():
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/key"):
            return httpx.Response(200, json={"data": {"limit": 10}})
        return httpx.Response(503, json={"error": "credits unavailable"})

    result = asyncio.run(fetch_openrouter_key_details(
        base_url="https://openrouter.test/api/v1",
        key_headers={},
        credits_headers={},
        transport=httpx.MockTransport(handler),
    ))

    assert result["ok"] is True
    assert result["credits"] == {
        "ok": False,
        "status_code": 503,
        "error_code": "PROVIDER_CHECK_UNAVAILABLE",
        "error": "Не удалось проверить ключ: OpenRouter временно недоступен.",
    }


def test_key_details_reject_invalid_json_without_exposing_exception():
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/key"):
            return httpx.Response(200, content=b"not-json")
        return httpx.Response(200, json={})

    result = asyncio.run(fetch_openrouter_key_details(
        base_url="https://openrouter.test/api/v1", key_headers={}, credits_headers={},
        transport=httpx.MockTransport(handler),
    ))
    assert result["ok"] is False
    assert result["error_code"] == "PROVIDER_CHECK_UNAVAILABLE"


def test_main_key_status_without_key_skips_integration(monkeypatch):
    async def unexpected_fetch(**_kwargs):
        raise AssertionError("OpenRouter HTTP must not run without a key")

    monkeypatch.setattr(main, "openrouter_api_key", lambda: "")
    monkeypatch.setattr(main, "fetch_openrouter_key_details", unexpected_fetch)

    assert asyncio.run(main.fetch_openrouter_key_status()) == {
        "configured": False,
        "ok": False,
        "error": "OPENROUTER_API_KEY не задан",
        "availability": {
            "state": "unknown",
            "ready": None,
            "lastStatusCode": None,
            "lastFailureAt": None,
            "lastSuccessAt": None,
        },
        "ready": False,
    }


def test_main_key_status_preserves_header_calls_source_and_shape(monkeypatch):
    captured: dict[str, object] = {}
    header_calls = 0

    def fake_headers():
        nonlocal header_calls
        header_calls += 1
        return {"X-Request": str(header_calls)}

    async def fake_fetch(**kwargs):
        captured.update(kwargs)
        return {"ok": True, "status_code": 200, "data": {"limit": 10}, "credits": {"ok": True}}

    monkeypatch.setattr(main, "openrouter_api_key", lambda: "configured-secret")
    monkeypatch.setattr(main, "openrouter_api_key_source", lambda: "admin_ui")
    monkeypatch.setattr(main, "openrouter_headers", fake_headers)
    monkeypatch.setattr(main, "fetch_openrouter_key_details", fake_fetch)

    result = asyncio.run(main.fetch_openrouter_key_status())

    assert result == {
        "configured": True,
        "source": "admin_ui",
        "ok": True,
        "status_code": 200,
        "data": {"limit": 10},
        "credits": {"ok": True},
        "availability": {
            "state": "unknown",
            "ready": None,
            "lastStatusCode": None,
            "lastFailureAt": None,
            "lastSuccessAt": None,
        },
        "ready": None,
    }
    assert captured == {
        "base_url": main.OPENROUTER_BASE_URL,
        "key_headers": {"X-Request": "1"},
        "credits_headers": {"X-Request": "2"},
        "timeout_seconds": 15,
    }


def test_main_key_status_preserves_safe_exception_wrapper(monkeypatch):
    async def failed_fetch(**_kwargs):
        raise httpx.ConnectError("provider unavailable")

    monkeypatch.setattr(main, "openrouter_api_key", lambda: "configured-secret")
    monkeypatch.setattr(main, "openrouter_api_key_source", lambda: "env")
    monkeypatch.setattr(main, "openrouter_headers", lambda: {"Authorization": "not-returned"})
    monkeypatch.setattr(main, "fetch_openrouter_key_details", failed_fetch)

    assert asyncio.run(main.fetch_openrouter_key_status()) == {
        "configured": True,
        "source": "env",
        "ok": False,
        "error": "Не удалось проверить ключ: OpenRouter временно недоступен.",
        "availability": {
            "state": "unknown",
            "ready": None,
            "lastStatusCode": None,
            "lastFailureAt": None,
            "lastSuccessAt": None,
        },
        "ready": False,
    }
