from __future__ import annotations

import asyncio
import copy
import json

import httpx
import pytest

import main
from app.integrations.openrouter_image_client import request_openrouter_image


def test_image_request_posts_exact_body_headers_timeout_without_retry():
    seen: list[httpx.Request] = []
    header_calls = 0
    predicate_calls = 0

    def headers_provider():
        nonlocal header_calls
        header_calls += 1
        return {"Authorization": "Bearer test", "X-Call": str(header_calls)}

    def size_predicate(_data):
        nonlocal predicate_calls
        predicate_calls += 1
        return True

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(201, json={"id": "response"})

    status, data = asyncio.run(request_openrouter_image(
        base_url="https://openrouter.test/api/v1",
        headers_provider=headers_provider,
        body={"model": "provider/image", "size": "1024x1024"},
        timeout_seconds=17,
        is_size_error=size_predicate,
        transport=httpx.MockTransport(handler),
    ))

    assert (status, data) == (201, {"id": "response"})
    assert header_calls == 1
    assert predicate_calls == 0
    assert len(seen) == 1
    assert seen[0].url == httpx.URL("https://openrouter.test/api/v1/images")
    assert seen[0].headers["Authorization"] == "Bearer test"
    assert seen[0].headers["X-Call"] == "1"
    assert json.loads(seen[0].content) == {"model": "provider/image", "size": "1024x1024"}
    assert set(seen[0].extensions["timeout"].values()) == {17}


def test_image_request_does_not_retry_non_size_error():
    requests = 0
    predicate_payloads: list[object] = []

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(422, json={"error": {"message": "invalid prompt"}})

    status, data = asyncio.run(request_openrouter_image(
        base_url="https://openrouter.test/api/v1",
        headers_provider=dict,
        body={"size": "1024x1024"},
        timeout_seconds=10,
        is_size_error=lambda payload: predicate_payloads.append(payload) or False,
        before_size_fallback=lambda: pytest.fail("non-size errors must not retry"),
        transport=httpx.MockTransport(handler),
    ))

    assert status == 422
    assert data == {"error": {"message": "invalid prompt"}}
    assert predicate_payloads == [data]
    assert requests == 1


@pytest.mark.parametrize("size", [None, "auto"])
def test_image_request_does_not_classify_or_retry_safe_size_values(size):
    requests = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(400, json={"error": {"message": "invalid size"}})

    status, _data = asyncio.run(request_openrouter_image(
        base_url="https://openrouter.test/api/v1",
        headers_provider=dict,
        body={"size": size},
        timeout_seconds=10,
        is_size_error=lambda _payload: pytest.fail("safe size values must bypass classification"),
        before_size_fallback=lambda: pytest.fail("safe size values must not retry"),
        transport=httpx.MockTransport(handler),
    ))

    assert status == 400
    assert requests == 1


def test_image_request_retries_once_with_auto_after_callback_and_fresh_headers():
    events: list[str] = []
    original_body = {"model": "provider/image", "size": "1536x1024", "prompt": "test"}

    def headers_provider():
        call = sum(event.startswith("headers:") for event in events) + 1
        events.append(f"headers:{call}")
        return {"X-Call": str(call)}

    def size_predicate(data):
        events.append(f"predicate:{data['error']['message']}")
        return True

    def before_fallback():
        events.append("callback")

    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        events.append(f"post:{body['size']}:{request.headers['X-Call']}")
        if body["size"] != "auto":
            return httpx.Response(400, json={"error": {"message": "invalid size"}})
        return httpx.Response(200, json={"id": "fallback-success"})

    status, data = asyncio.run(request_openrouter_image(
        base_url="https://openrouter.test/api/v1",
        headers_provider=headers_provider,
        body=original_body,
        timeout_seconds=10,
        is_size_error=size_predicate,
        before_size_fallback=before_fallback,
        transport=httpx.MockTransport(handler),
    ))

    assert (status, data) == (200, {"id": "fallback-success"})
    assert original_body == {"model": "provider/image", "size": "1536x1024", "prompt": "test"}
    assert events == [
        "headers:1",
        "post:1536x1024:1",
        "predicate:invalid size",
        "callback",
        "headers:2",
        "post:auto:2",
    ]


def test_image_request_returns_second_error_without_third_attempt():
    bodies: list[dict] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        bodies.append(body)
        return httpx.Response(
            400 if len(bodies) == 1 else 429,
            json={"error": {"message": "invalid size" if len(bodies) == 1 else "rate limited"}},
        )

    status, data = asyncio.run(request_openrouter_image(
        base_url="https://openrouter.test/api/v1",
        headers_provider=dict,
        body={"size": "1024x1024"},
        timeout_seconds=10,
        is_size_error=lambda _payload: True,
        transport=httpx.MockTransport(handler),
    ))

    assert status == 429
    assert data == {"error": {"message": "rate limited"}}
    assert [body["size"] for body in bodies] == ["1024x1024", "auto"]


def test_image_request_callback_failure_blocks_retry():
    requests = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(400, json={"error": {"message": "invalid size"}})

    def failed_callback():
        raise RuntimeError("persist failed")

    with pytest.raises(RuntimeError, match="persist failed"):
        asyncio.run(request_openrouter_image(
            base_url="https://openrouter.test/api/v1",
            headers_provider=dict,
            body={"size": "1024x1024"},
            timeout_seconds=10,
            is_size_error=lambda _payload: True,
            before_size_fallback=failed_callback,
            transport=httpx.MockTransport(handler),
        ))

    assert requests == 1


def test_image_request_preserves_empty_and_invalid_json_responses():
    async def empty_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(204)

    assert asyncio.run(request_openrouter_image(
        base_url="https://openrouter.test/api/v1",
        headers_provider=dict,
        body={},
        timeout_seconds=10,
        is_size_error=lambda _payload: False,
        transport=httpx.MockTransport(empty_handler),
    )) == (204, {})

    async def invalid_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not-json")

    with pytest.raises(json.JSONDecodeError):
        asyncio.run(request_openrouter_image(
            base_url="https://openrouter.test/api/v1",
            headers_provider=dict,
            body={},
            timeout_seconds=10,
            is_size_error=lambda _payload: False,
            transport=httpx.MockTransport(invalid_handler),
        ))


def test_send_to_openrouter_persists_fallback_before_mapping_final_error(monkeypatch):
    request = main.GenerateRequest(
        mode="text_to_image",
        provider="openrouter",
        modelProfile="provider/image",
        prompt="test",
        width=1024,
        height=1024,
    )
    job = {"id": "job-test", "status": "queued", "progress": 0, "message": ""}
    persisted: list[dict] = []
    captured: dict[str, object] = {}

    monkeypatch.setattr(main, "openrouter_api_key", lambda: "configured")

    async def capabilities():
        return [{"id": "provider/image", "modes": ["text_to_image"], "parameters": []}]

    monkeypatch.setattr(main, "fetch_openrouter_image_capabilities", capabilities)
    monkeypatch.setattr(main, "openrouter_image_request_plan", lambda *_args: {"size": "1024x1024"})
    monkeypatch.setattr(main, "build_openrouter_image_body", lambda *_args: {"size": "1024x1024"})
    monkeypatch.setattr(main, "persist_job", lambda value, _payload: persisted.append(copy.deepcopy(value)))

    async def failed_request(**kwargs):
        captured.update(kwargs)
        kwargs["before_size_fallback"]()
        return 429, {"error": {"message": "rate limited"}}

    monkeypatch.setattr(main, "request_openrouter_image", failed_request)
    monkeypatch.setattr(main, "_openrouter_public_error", lambda status, _data: f"mapped:{status}")

    with pytest.raises(RuntimeError, match="mapped:429"):
        asyncio.run(main.send_to_openrouter(request, job))

    assert len(persisted) == 2
    assert persisted[0]["status"] == "sent_to_openrouter"
    assert persisted[0]["message"] == "Отправляем в OpenRouter"
    assert "fallbackSize" not in persisted[0]["openrouterRequest"]
    assert persisted[1]["message"] == "OpenRouter подбирает безопасный формат"
    assert persisted[1]["openrouterRequest"]["fallbackSize"] == "auto"
    callback = captured.pop("before_size_fallback")
    assert callable(callback)
    assert captured == {
        "base_url": main.OPENROUTER_BASE_URL,
        "headers_provider": main.openrouter_headers,
        "body": {"size": "1024x1024"},
        "timeout_seconds": main.OPENROUTER_TIMEOUT_SECONDS,
        "is_size_error": main._openrouter_is_size_error,
    }
