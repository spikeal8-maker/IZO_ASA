from __future__ import annotations

import asyncio
import json
from decimal import Decimal

import httpx
import pytest

from app.integrations.polza import (
    PolzaTransportError,
    extract_polza_actual_cost_rub,
    fetch_polza_models,
    parse_polza_models,
    polza_public_model_id,
    request_polza_chat_completion,
)


FAKE_API_KEY = "pza_test_nonproduction_key_123456"
MODEL = "openai/gpt-4o"


def test_polza_catalog_namespaces_ids_and_preserves_rub_prices():
    rows = parse_polza_models({"data": [{
        "id": MODEL,
        "name": "OpenAI GPT-4o",
        "architecture": {"input_modalities": ["text", "image"], "output_modalities": ["text"]},
        "context_length": "128000",
        "pricing": {"currency": "RUB", "prompt_per_million": "17.95", "completion_per_million": "71.79"},
    }]})
    assert len(rows) == 1
    row = rows[0]
    assert row["id"] == "polza:" + MODEL and row["provider"] == "polza"
    assert row["inputModalities"] == ["image", "text"]
    assert row["outputModalities"] == ["text"]
    assert row["inputPerMillionRub"] == "17.95"
    assert row["outputPerMillionRub"] == "71.79"
    assert row["currency"] == "RUB" and row["pricingVerified"]
    assert row["priceSource"] == "polza:/api/v1/models"
    assert polza_public_model_id(MODEL) != MODEL
    assert polza_public_model_id(rows[0]["id"]) == rows[0]["id"]


def test_catalog_never_invents_prices_or_flattens_unverified_routes():
    rows = parse_polza_models({"models": [
        {"id": "a/no-currency", "pricing": {"prompt_per_million": 2, "completion_per_million": 4}},
        {"id": "a/usd", "pricing": {"currency": "USD", "prompt_per_million": 2, "completion_per_million": 4}},
        {"id": "a/route-only", "routes": [{"pricing": {"currency": "RUB", "prompt_per_million": 1, "completion_per_million": 2}}]},
        {"id": "a/bad", "pricing": {"currency": "RUB", "prompt_per_million": "NaN", "completion_per_million": -1}},
        {"id": "a/zero", "pricing": {"currency": "RUB", "prompt_per_million": 0, "completion_per_million": 0}},
        {"id": "a/zero", "pricing": {"currency": "RUB", "prompt_per_million": 10, "completion_per_million": 10}},
        {"name": "no id"}, {"id": "evil:wrong/model"}, 1,
    ]})
    assert len(rows) == 5
    by_id = {row["upstreamId"]: row for row in rows}
    for name in ["a/no-currency", "a/usd", "a/route-only", "a/bad"]:
        assert by_id[name]["pricingVerified"] is False
        assert by_id[name]["inputPerMillionRub"] is None
        assert by_id[name]["priceSource"] is None
    assert by_id["a/zero"]["pricingVerified"] is True
    assert by_id["a/zero"]["inputPerMillionRub"] == "0"


@pytest.mark.parametrize("payload", [None, {}, {"data": None}, {"data": {}}, []])
def test_catalog_rejects_bad_schema(payload):
    with pytest.raises(PolzaTransportError, match="POLZA_CATALOG_INVALID"):
        parse_polza_models(payload)


def test_actual_cost_is_rub_not_usd_and_never_zero_on_missing():
    assert extract_polza_actual_cost_rub({"usage": {"cost_rub": 1.25, "cost": 1.25}}) == Decimal("1.25")
    assert extract_polza_actual_cost_rub({"usage": {"cost": "0.025"}}) == Decimal("0.025")
    assert extract_polza_actual_cost_rub({"usage": {"cost_rub": 0}}) == Decimal("0")
    assert extract_polza_actual_cost_rub({"usage": {"prompt_tokens": 10}}) is None
    assert extract_polza_actual_cost_rub({"choices": []}) is None


@pytest.mark.parametrize("usage,code", [
    ({"cost_rub": "NaN"}, "POLZA_COST_INVALID"),
    ({"cost_rub": "-3"}, "POLZA_COST_INVALID"),
    ({"cost_rub": True}, "POLZA_COST_INVALID"),
    ({"cost_rub": 1.2, "cost": 3.1}, "POLZA_COST_CONFLICT"),
    ({"cost_rub": "1E99999"}, "POLZA_COST_INVALID"),
])
def test_cost_rejects_invalid_and_conflicting_values(usage, code):
    with pytest.raises(PolzaTransportError, match=code):
        extract_polza_actual_cost_rub({"usage": usage})


def test_mock_catalog_fetch_has_fixed_path_and_bearer_key():
    seen = []
    def fake(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, json={"data": [{"id": MODEL, "name": "GPT-4o"}]})
    models = asyncio.run(fetch_polza_models(
        api_key=FAKE_API_KEY, transport=httpx.MockTransport(fake),
    ))
    assert len(seen) == 1
    assert seen[0].url.scheme == "https"
    assert seen[0].url.host == "polza.ai"
    assert seen[0].url.path == "/api/v1/models"
    assert seen[0].headers["Authorization"] == "Bearer " + FAKE_API_KEY
    assert models[0]["provider"] == "polza"
    assert models[0]["pricingVerified"] is False


def test_mock_chat_uses_polza_model_id_and_returns_actual_rub():
    seen = []
    def fake(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, json={
            "choices": [{"message": {"role": "assistant", "content": "Готово"}}],
            "usage": {"prompt_tokens": 25, "completion_tokens": 20, "cost_rub": 0.15, "cost": 0.15},
        })
    result = asyncio.run(request_polza_chat_completion(
        api_key=FAKE_API_KEY, model_id="polza:" + MODEL,
        messages=[{"role": "user", "content": "Привет"}],
        transport=httpx.MockTransport(fake),
    ))
    assert len(seen) == 1
    assert seen[0].method == "POST"
    assert seen[0].url.path == "/api/v1/chat/completions"
    assert json.loads(seen[0].content)["model"] == MODEL
    assert json.loads(seen[0].content)["stream"] is False
    assert extract_polza_actual_cost_rub(result) == Decimal("0.15")


@pytest.mark.parametrize("status,code", [(401, "POLZA_BAD_KEY"), (402, "POLZA_HTTP_ERROR"), (429, "POLZA_TOO_MANY_REQUESTS")])
def test_provider_errors_are_sanitized_and_no_retry(status, code):
    seen = []
    def fake(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        json_response = {"error": {"code": "BAD_KEY" if status == 401 else "TOO_MANY_REQUESTS" if status == 429 else "insufficient funds", "message": FAKE_API_KEY}}
        return httpx.Response(status, json=json_response)
    with pytest.raises(PolzaTransportError) as error:
        asyncio.run(fetch_polza_models(api_key=FAKE_API_KEY, transport=httpx.MockTransport(fake)))
    assert error.value.code == code
    assert error.value.status_code == status
    assert FAKE_API_KEY not in str(error.value)
    assert len(seen) == 1


def test_timeout_is_not_automatically_retried_or_replayed():
    seen = []
    def fake(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        raise httpx.ReadTimeout("fake-timeout")
    with pytest.raises(PolzaTransportError, match="POLZA_CONNECTION_FAILED"):
        asyncio.run(request_polza_chat_completion(
            api_key=FAKE_API_KEY, model_id=MODEL,
            messages=[{"role": "user", "content": "A"}],
            transport=httpx.MockTransport(fake),
        ))
    assert len(seen) == 1


def test_bad_key_or_model_rejected_before_http():
    with pytest.raises(ValueError, match="POLZA_API_KEY_INVALID"):
        asyncio.run(fetch_polza_models(api_key="sk-or-not-polza", transport=httpx.MockTransport(lambda req: httpx.Response(200))))
    with pytest.raises(ValueError, match="POLZA_MODEL_INVALID"):
        asyncio.run(request_polza_chat_completion(api_key=FAKE_API_KEY, model_id="openrouter:foo", messages=[{"role": "user", "content": "Hi"}]))


def test_invalid_http_response_is_sanitized():
    fake = httpx.MockTransport(lambda req: httpx.Response(200, text="not-json"))
    with pytest.raises(PolzaTransportError, match="POLZA_RESPONSE_INVALID"):
        asyncio.run(fetch_polza_models(api_key=FAKE_API_KEY, transport=fake))
