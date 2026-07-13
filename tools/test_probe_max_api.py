from __future__ import annotations

import asyncio

import httpx

from tools.probe_max_api import probe_max_api


def test_probe_uses_me_authorization_and_returns_only_transport_metadata():
    seen: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"private": "response-body"})

    result = asyncio.run(probe_max_api(
        base_url="https://platform-api2.max.test/",
        token="private-probe-token",
        trust_store="certifi",
        transport=httpx.MockTransport(handler),
    ))

    assert result == (200, "HTTP/1.1")
    assert len(seen) == 1
    assert seen[0].url.path == "/me"
    assert seen[0].headers["Authorization"] == "private-probe-token"
