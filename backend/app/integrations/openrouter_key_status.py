"""Read-only OpenRouter key checks with a fixed, non-reflective response schema."""

from __future__ import annotations

import math
from typing import Any

import httpx

from .openrouter_transport import client_options


_NUMBERS = {"limit", "limit_remaining", "usage", "usage_daily", "usage_weekly", "usage_monthly", "byok_usage"}
_BOOLEANS = {"is_free_tier", "is_management_key"}
_MAX_BODY = 65536


def failure(code: int | None, *, credits: bool = False) -> dict[str, Any]:
    if credits and code == 403:
        reason, message = "MANAGEMENT_SCOPE_REQUIRED", "Credits API недоступен этому ключу; проверка обычного ключа независима."
    elif code in {401, 403}:
        reason, message = "KEY_ACCESS_REJECTED", "OpenRouter не подтвердил доступ ключа."
    elif code == 429:
        reason, message = "PROVIDER_RATE_LIMIT", "OpenRouter временно ограничил частоту проверки."
    elif code is not None and 300 <= code < 400:
        reason, message = "PROVIDER_REDIRECT_REJECTED", "OpenRouter вернул запрещённое перенаправление."
    else:
        reason, message = "PROVIDER_CHECK_UNAVAILABLE", "Не удалось проверить ключ: OpenRouter временно недоступен."
    return {"ok": False, "status_code": code, "error_code": reason, "error": message}


def _numeric_fields(data: dict, names: set[str]) -> dict:
    return {name: value for name, value in data.items() if name in names
            and (value is None or (type(value) in {int, float} and math.isfinite(value) and abs(value) <= 1e18))}


async def _get(client: httpx.AsyncClient, url: str, headers: dict[str, str]) -> tuple[int, dict | None]:
    async with client.stream("GET", url, headers=headers, follow_redirects=False) as response:
        data = bytearray()
        async for chunk in response.aiter_bytes():
            data.extend(chunk)
            if len(data) > _MAX_BODY:
                return response.status_code, None
        try:
            decoded = httpx.Response(200, content=bytes(data)).json()
        except (ValueError, UnicodeError):
            return response.status_code, None
        if not isinstance(decoded, dict):
            return response.status_code, None
        if decoded.get("error") is not None:
            return response.status_code, None
        body = decoded.get("data", decoded)
        return response.status_code, body if isinstance(body, dict) else None


async def fetch_openrouter_key_details(
    *, base_url: str, key_headers: dict[str, str], credits_headers: dict[str, str],
    timeout_seconds: float = 15, transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    try:
        options = client_options(base_url, timeout=timeout_seconds, transport=transport)
        async with httpx.AsyncClient(**options) as client:
            code, body = await _get(client, base_url.rstrip("/") + "/key", key_headers)
            if not 200 <= code < 300 or body is None:
                return failure(code)
            data = _numeric_fields(body, _NUMBERS)
            data.update({name: value for name, value in body.items() if name in _BOOLEANS and type(value) is bool})
            if not data:
                return failure(code)
            result = {"ok": True, "status_code": code, "data": data}
            try:
                credits_code, credits_body = await _get(client, base_url.rstrip("/") + "/credits", credits_headers)
                if not 200 <= credits_code < 300 or credits_body is None:
                    credits = failure(credits_code, credits=True)
                else:
                    values = _numeric_fields(credits_body, {"total_credits", "total_usage"})
                    if not values:
                        result["credits"] = failure(credits_code, credits=True)
                        return result
                    credits = {"ok": True, "status_code": credits_code, "data": values}
                    total, usage = values.get("total_credits"), values.get("total_usage")
                    if total is not None and usage is not None:
                        credits["calculated_balance"] = round(total - usage, 6)
            except Exception:
                credits = failure(None, credits=True)
            result["credits"] = credits
            return result
    except Exception:
        return failure(None)
