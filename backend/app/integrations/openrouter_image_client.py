"""OpenRouter image generation HTTP transport with bounded size fallback."""

from __future__ import annotations

from typing import Any, Callable

import httpx


async def request_openrouter_image(
    *,
    base_url: str,
    headers_provider: Callable[[], dict[str, str]],
    body: dict[str, Any],
    timeout_seconds: float,
    is_size_error: Callable[[Any], bool],
    before_size_fallback: Callable[[], None] | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> tuple[int, Any]:
    """POST one image request and retry once with `size=auto` when required."""

    client_options: dict[str, Any] = {"timeout": timeout_seconds}
    if transport is not None:
        client_options["transport"] = transport
    async with httpx.AsyncClient(**client_options) as client:
        response = await client.post(
            f"{base_url}/images",
            headers=headers_provider(),
            json=body,
        )
        data = response.json() if response.content else {}
        if response.status_code >= 400 and body.get("size") not in {None, "auto"} and is_size_error(data):
            fallback_body = {**body, "size": "auto"}
            if before_size_fallback is not None:
                before_size_fallback()
            response = await client.post(
                f"{base_url}/images",
                headers=headers_provider(),
                json=fallback_body,
            )
            data = response.json() if response.content else {}
    return response.status_code, data
