"""Import-safe Polza API transport; RUB costs, fixed endpoints, no live billing."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx


POLZA_BASE_URL = "https://polza.ai/api/v1"
POLZA_PROVIDER_ID = "polza"
POLZA_PUBLIC_PREFIX = "polza:"
POLZA_CATALOG_SOURCE = "polza:/api/v1/models"
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
_MODEL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,199}$")
_ERROR_CODE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")


class PolzaTransportError(RuntimeError):
    def __init__(self, code: str, *, status_code: int | None = None):
        self.code = code
        self.status_code = status_code
        super().__init__(code)


def _rub_amount(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    if not isinstance(value, (str, int, float, Decimal)):
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not number.is_finite() or number < 0 or number > Decimal("1000000000000"):
        return None
    return number


def _upstream_id(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("POLZA_MODEL_INVALID")
    raw = value.removeprefix(POLZA_PUBLIC_PREFIX)
    if ":" in raw or ".." in raw or not _MODEL_ID.fullmatch(raw):
        raise ValueError("POLZA_MODEL_INVALID")
    return raw


def polza_public_model_id(upstream_model_id: str) -> str:
    return POLZA_PUBLIC_PREFIX + _upstream_id(upstream_model_id)


def extract_polza_actual_cost_rub(payload: Any) -> Decimal | None:
    """Parse cost_rub (or its RUB alias cost); missing cost stays unknown."""
    if not isinstance(payload, dict):
        raise PolzaTransportError("POLZA_PAYLOAD_INVALID")
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        return None
    rub_present = usage.get("cost_rub") is not None
    alias_present = usage.get("cost") is not None
    if not rub_present and not alias_present:
        return None
    rub = _rub_amount(usage.get("cost_rub")) if rub_present else None
    alias = _rub_amount(usage.get("cost")) if alias_present else None
    if (rub_present and rub is None) or (alias_present and alias is None):
        raise PolzaTransportError("POLZA_COST_INVALID")
    if rub_present and alias_present and rub != alias:
        raise PolzaTransportError("POLZA_COST_CONFLICT")
    return rub if rub_present else alias


def _text_modalities(model: dict[str, Any]) -> tuple[list[str], list[str]]:
    architecture = model.get("architecture")
    architecture = architecture if isinstance(architecture, dict) else {}
    inputs = architecture.get("input_modalities", model.get("input_modalities"))
    outputs = architecture.get("output_modalities", model.get("output_modalities"))
    def cleaned(raw: Any) -> list[str]:
        if not isinstance(raw, list):
            return []
        return sorted({item.lower() for item in raw if isinstance(item, str) and 1 <= len(item) <= 32})
    return cleaned(inputs), cleaned(outputs)


def _price_per_million_rub(model: dict[str, Any]) -> tuple[Decimal | None, Decimal | None]:
    pricing = model.get("pricing")
    if not isinstance(pricing, dict):
        return None, None
    currency = str(pricing.get("currency") or model.get("currency") or "").upper()
    if currency not in {"RUB", "RUR"}:
        return None, None
    input_rub = _rub_amount(pricing.get("prompt_per_million"))
    output_rub = _rub_amount(pricing.get("completion_per_million"))
    return (input_rub, output_rub) if input_rub is not None and output_rub is not None else (None, None)


def parse_polza_models(payload: Any) -> list[dict[str, Any]]:
    """Normalize model identities; leave unknown/route-specific prices unpriced."""
    if not isinstance(payload, dict):
        raise PolzaTransportError("POLZA_CATALOG_INVALID")
    rows = payload.get("data", payload.get("models"))
    if not isinstance(rows, list):
        raise PolzaTransportError("POLZA_CATALOG_INVALID")
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        original = row.get("id")
        try:
            model_id = _upstream_id(original)
        except ValueError:
            continue
        if model_id in seen:
            continue
        seen.add(model_id)
        inputs, outputs = _text_modalities(row)
        input_price, output_price = _price_per_million_rub(row)
        priced = input_price is not None and output_price is not None
        context = row.get("context_length")
        try:
            context_value = max(0, int(context)) if context is not None and not isinstance(context, bool) else 0
        except (ValueError, TypeError, OverflowError):
            context_value = 0
        name = row.get("name") if isinstance(row.get("name"), str) and row["name"].strip() else model_id
        result.append({
            "id": polza_public_model_id(model_id),
            "upstreamId": model_id,
            "name": name,
            "provider": POLZA_PROVIDER_ID,
            "supplier": model_id.split("/", 1)[0] if "/" in model_id else "",
            "inputModalities": inputs,
            "outputModalities": outputs,
            "contextLength": context_value,
            "inputPerMillionRub": str(input_price) if priced else None,
            "outputPerMillionRub": str(output_price) if priced else None,
            "currency": "RUB",
            "pricingVerified": priced,
            "priceSource": POLZA_CATALOG_SOURCE if priced else None,
        })
    result.sort(key=lambda model: (model["name"].casefold(), model["id"]))
    return result


def _safe_error_code(response: httpx.Response) -> str:
    try:
        payload = response.json()
        error = payload.get("error") if isinstance(payload, dict) else None
        code = error.get("code") if isinstance(error, dict) else None
        if isinstance(code, str) and _ERROR_CODE.fullmatch(code):
            return "POLZA_" + code
    except (ValueError, TypeError):
        pass
    return "POLZA_HTTP_ERROR"


async def _json_request(
    method: str,
    endpoint: str,
    *,
    api_key: str,
    json_body: dict[str, Any] | None = None,
    timeout_seconds: float = 45.0,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    if not isinstance(api_key, str) or not api_key.startswith("pza_") or len(api_key) < 8 or len(api_key) > 512:
        raise ValueError("POLZA_API_KEY_INVALID")
    if not 1 <= timeout_seconds <= 600:
        raise ValueError("POLZA_TIMEOUT_INVALID")
    headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_seconds),
            transport=transport,
            follow_redirects=False,
            trust_env=False,
        ) as client:
            response = await client.request(
                method, POLZA_BASE_URL + endpoint, headers=headers, json=json_body,
            )
    except httpx.HTTPError:
        raise PolzaTransportError("POLZA_CONNECTION_FAILED") from None
    if len(response.content) > MAX_RESPONSE_BYTES:
        raise PolzaTransportError("POLZA_RESPONSE_TOO_LARGE", status_code=response.status_code)
    if response.status_code >= 400 or 300 <= response.status_code < 400:
        raise PolzaTransportError(_safe_error_code(response), status_code=response.status_code)
    try:
        parsed = response.json()
    except ValueError:
        raise PolzaTransportError("POLZA_RESPONSE_INVALID", status_code=response.status_code) from None
    if not isinstance(parsed, dict):
        raise PolzaTransportError("POLZA_RESPONSE_INVALID", status_code=response.status_code)
    return parsed


async def fetch_polza_models(
    *, api_key: str, timeout_seconds: float = 15.0, transport: httpx.AsyncBaseTransport | None = None,
) -> list[dict[str, Any]]:
    return parse_polza_models(await _json_request(
        "GET", "/models", api_key=api_key, timeout_seconds=timeout_seconds, transport=transport,
    ))


async def request_polza_chat_completion(
    *,
    api_key: str,
    model_id: str,
    messages: list[dict[str, Any]],
    timeout_seconds: float = 90.0,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    upstream = _upstream_id(model_id)
    if not isinstance(messages, list) or not messages or not all(isinstance(item, dict) for item in messages):
        raise ValueError("POLZA_MESSAGES_INVALID")
    payload = await _json_request(
        "POST", "/chat/completions",
        api_key=api_key, json_body={"model": upstream, "messages": messages, "stream": False},
        timeout_seconds=timeout_seconds, transport=transport,
    )
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise PolzaTransportError("POLZA_CHAT_RESPONSE_INVALID")
    extract_polza_actual_cost_rub(payload)
    return payload
