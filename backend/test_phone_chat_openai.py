"""Deterministic OpenAI adapter and chat provider selection."""
from __future__ import annotations

import httpx
import pytest


@pytest.fixture
def anyio_backend():
    return "asyncio"

from app.api.routers.phone_chat import (
    PhoneChatRequest, _resolve_phone_chat_model, phone_chat_openai,
    PhoneChatDependencies,
)
from app.integrations.openai import (
    OpenAIProviderError, request_openai_response, check_openai_access,
    normalize_openai_settings,
)


@pytest.mark.anyio
async def test_response_api_text_and_privacy_boundary():
    calls = []
    def fake(request):
        calls.append(request)
        assert request.url == "https://api.openai.com/v1/responses"
        assert request.headers["authorization"].startswith("Bearer sk-proj-")
        import json
        body = json.loads(request.content.decode())
        assert body["store"] is False
        assert body["input"][-1] == {"role": "user", "content": "Привет!"}
        assert body["max_output_tokens"] == 1000
        return httpx.Response(200, json={
            "status": "completed",
            "output": [{"type": "message", "content": [{"type": "output_text", "text": "Ответ OpenAI."}]}],
            "usage": {"input_tokens": 6, "output_tokens": 5},
        })
    reply, payload = await request_openai_response(
        key="sk-proj-local-unit-test", model="gpt-4.1-mini",
        messages=[{"role": "user", "content": "Привет!"}],
        instructions="Ответь коротко.", transport=httpx.MockTransport(fake),
    )
    assert reply == "Ответ OpenAI."
    assert payload["usage"]["input_tokens"] == 6
    assert len(calls) == 1
    assert "authorization" not in payload


@pytest.mark.anyio
@pytest.mark.parametrize("status,expected", [(401, "invalid_key"), (403, "access_denied"), (404, "model_unavailable"), (429, "rate_limit"), (503, "provider_error")])
async def test_provider_errors_never_reveal_secret(status, expected):
    def fake(_):
        return httpx.Response(status, json={"error": {"message": "SK_TEST_LEAK"}})
    with pytest.raises(OpenAIProviderError) as error:
        await request_openai_response(
            key="sk-proj-secret-do-not-leak", model="gpt-4.1-mini",
            messages=[{"role": "user", "content": "x"}],
            instructions="a", transport=httpx.MockTransport(fake),
        )
    assert error.value.code == expected
    assert "SK_TEST_LEAK" not in str(error.value)
    assert "sk-proj-secret" not in str(error.value)


@pytest.mark.anyio
async def test_no_automatic_retry_after_ambiguous_timeout():
    observed = []
    def fail(request):
        observed.append(request)
        raise httpx.ReadTimeout("delayed", request=request)
    with pytest.raises(OpenAIProviderError) as error:
        await request_openai_response(
            key="sk-proj-test", model="gpt-4.1-mini",
            messages=[{"role": "user", "content": "x"}],
            instructions="a", transport=httpx.MockTransport(fail),
        )
    assert error.value.code == "ambiguous_timeout"
    assert len(observed) == 1


@pytest.mark.anyio
async def test_verify_is_read_only_model_get():
    def fake(request):
        assert request.method == "GET"
        assert request.url == "https://api.openai.com/v1/models/gpt-4.1-mini"
        return httpx.Response(200, json={"id": "gpt-4.1-mini"})
    result = await check_openai_access(key="sk-proj-test", model="gpt-4.1-mini", transport=httpx.MockTransport(fake))
    assert result["ok"] is True


def test_openai_admin_only_and_default_disabled():
    config = {"enabled": True, "_openai": normalize_openai_settings({"enabled": True, "model": "gpt-4.1-mini"})}
    req = PhoneChatRequest(messages=[{"role": "user", "content": "x"}], modelId="openai:gpt-4.1-mini")
    assert _resolve_phone_chat_model(req, config, "admin")[1] == "openai"
    with pytest.raises(ValueError):
        _resolve_phone_chat_model(req, config, "mini")
    with pytest.raises(ValueError):
        _resolve_phone_chat_model(req, {"enabled": True, "_openai": normalize_openai_settings({})}, "admin")
