"""Small sanitized VK API client used by social syndication."""

from __future__ import annotations

from typing import Any

import httpx


async def request_vk_api(
    *,
    token: str,
    method: str,
    params: dict[str, Any],
    timeout_seconds: float = 30,
) -> dict[str, Any]:
    if not token.strip():
        raise RuntimeError("VK access token is not configured.")
    payload = {**params, "access_token": token, "v": "5.199"}
    try:
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            response = await client.post(
                f"https://api.vk.com/method/{method}", data=payload
            )
        body = response.json()
    except httpx.TimeoutException as exc:
        raise RuntimeError("VK API timeout.") from exc
    except (httpx.HTTPError, ValueError) as exc:
        raise RuntimeError("VK API is unavailable.") from exc
    if response.status_code != 200:
        raise RuntimeError(f"VK API returned HTTP {response.status_code}.")
    if not isinstance(body, dict):
        raise RuntimeError("VK API returned invalid JSON.")
    error = body.get("error")
    if isinstance(error, dict):
        code = error.get("error_code")
        message = str(error.get("error_msg") or "request rejected")[:180]
        raise RuntimeError(f"VK API error {code}: {message}")
    return body
