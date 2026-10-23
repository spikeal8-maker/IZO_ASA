"""Ordinary OpenRouter API key validation must never require management credentials."""
from __future__ import annotations
import httpx
import pytest

from app.integrations.openrouter import fetch_openrouter_key_details


@pytest.fixture
def anyio_backend(): return "asyncio"


async def probe(handler):
    return await fetch_openrouter_key_details(
        base_url="https://openrouter.ai/api/v1",
        key_headers={"Authorization":"Bearer sk-or-synthetic-test"},
        credits_headers={"Authorization":"Bearer sk-or-synthetic-test"},
        transport=httpx.MockTransport(handler),
        timeout_seconds=2,
    )


@pytest.mark.anyio
async def test_regular_key_uses_only_current_key_endpoint():
    urls=[]
    def handler(request):
        urls.append(str(request.url))
        assert request.method=="GET"
        assert request.headers["Authorization"].startswith("Bearer sk-or-")
        return httpx.Response(200,json={"data":{"label":"OK","usage_monthly":4,"secret_disallowed":"must never return"}})
    result=await probe(handler)
    assert result["ok"] is True
    assert result["status_code"]==200
    assert "secret_disallowed" not in result["data"]
    assert result["credits"]["skipped"] is True
    assert urls==["https://openrouter.ai/api/v1/key"]


@pytest.mark.anyio
@pytest.mark.parametrize("code,expected",[(400,"OPENROUTER_REQUEST_INVALID"),(401,"OPENROUTER_KEY_INVALID"),(403,"OPENROUTER_KEY_FORBIDDEN"),(429,"OPENROUTER_RATE_LIMIT"),(500,"OPENROUTER_PROVIDER_UNAVAILABLE"),(503,"OPENROUTER_PROVIDER_UNAVAILABLE")])
async def test_provider_rejections_safe(code,expected):
    def handler(_):
        return httpx.Response(code,json={"error":{"message":"sk-or-SECRET-NEVER-ECHO"}})
    status=await probe(handler)
    assert status["ok"] is False
    assert status["error"]==expected
    assert "SECRET-NEVER-ECHO" not in repr(status)


@pytest.mark.anyio
async def test_transport_timeout_is_distinct_from_invalid_key():
    calls=[]
    def timeout(req):
        calls.append(req)
        raise httpx.ReadTimeout("external secret value",request=req)
    result=await probe(timeout)
    assert result["status_code"] is None
    assert result["error"]=="OPENROUTER_TIMEOUT"
    assert len(calls)==1


@pytest.mark.anyio
async def test_network_unavailable_does_not_delete_saved_key():
    def bad(req): raise httpx.ConnectError("openrouter.a network failure",request=req)
    result=await probe(bad)
    assert result["status_code"] is None
    assert result["error"]=="OPENROUTER_NETWORK_UNAVAILABLE"


@pytest.mark.anyio
async def test_bad_provider_json_fails_closed():
    def malformed(_): return httpx.Response(200,content=b"{}")
    result=await probe(malformed)
    assert result["ok"] is False
    assert result["error"]=="OPENROUTER_RESPONSE_INVALID"
