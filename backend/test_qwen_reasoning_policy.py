"""Real HTTP boundary regression: legacy short calls must not disable Qwen reasoning."""
import asyncio
import json

import httpx

from app.integrations.ollama import request_ollama_chat_message, qwen_max_reasoning_body
from app.services.chat_billing import normalize_chat_config


def test_legacy_improve_request_gets_xhigh_and_complete_long_answer():
    answer = "def answer(): return 42\n" * 2000
    original = {"model": "qwen3.8:27b", "think": False, "options": {"num_predict": 500}}

    def handler(request):
        body = json.loads(request.content)
        assert body["think"] == "xhigh"
        assert body["keep_alive"] == -1
        assert body["options"] == {"num_ctx": 120000, "num_predict": -1}
        assert request.extensions["timeout"]["read"] == 1800
        return httpx.Response(200, json={"message": {"content": answer}, "done": True})

    content, _ = asyncio.run(request_ollama_chat_message(
        body=original, timeout_seconds=10, transport=httpx.MockTransport(handler),
    ))
    assert content == answer
    assert original["think"] is False


def test_other_models_are_not_given_unsupported_reasoning_levels():
    body = {"model": "gemma4:12b", "think": False, "options": {"num_predict": 500}}
    assert qwen_max_reasoning_body(body) is body


def test_shared_qwen_defaults_and_upper_context_bound():
    config = normalize_chat_config({})
    assert config["localModel"] == "qwen3.8:27b"
    assert config["localNumCtx"] == 120000
    assert config["localTimeoutSeconds"] == 1800
    assert normalize_chat_config({"localNumCtx": 999999})["localNumCtx"] == 120000


def test_second_request_can_use_complete_persisted_long_code(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app.api.routers import phone_chat
    from test_phone_chat_idempotency import _database, _app, _deps, _payload, THREAD_ID, MODEL_ID

    path = tmp_path / "long-code.sqlite3"
    _database(path, with_thread=True)
    answer = "print('complete code')\n" * 4000
    seen = []

    async def fake_route(request, _deps):
        seen.append(phone_chat._phone_chat_history(request))
        return answer, {}, "api", MODEL_ID, MODEL_ID, 1.0, "main"

    monkeypatch.setattr(phone_chat, "route_phone_chat", fake_route)
    with TestClient(_app(_deps(path, with_db=True))) as client:
        first = client.post("/api/phone/chat", json=_payload(request_id="long-code-first", thread_id=THREAD_ID))
        assert first.status_code == 200
        second = client.post("/api/phone/chat", json=_payload(request_id="long-code-next", thread_id=THREAD_ID))
        assert second.status_code == 200
    assert any(item["role"] == "assistant" and item["content"] == answer.strip() for item in seen[1])


def test_live_long_reasoning_is_not_refunded_by_retry_after_five_minutes(tmp_path):
    from dataclasses import replace
    from datetime import datetime, timedelta, timezone
    from test_phone_chat_idempotency import _database, _lifecycle, _connect

    path = tmp_path / "long-reasoning.sqlite3"
    _database(path)
    now = [datetime(2026, 10, 26, tzinfo=timezone.utc)]
    lifecycle = replace(_lifecycle(path), clock=lambda: now[0])
    common = {"user_id": "user-1", "request_id": "long-reasoning", "fingerprint": "a" * 64}
    assert lifecycle.begin(**common, token_cost=0, provider="local", model="qwen3.8:27b")["state"] == "started"
    now[0] += timedelta(seconds=600)
    assert lifecycle.inspect(**common)["state"] == "processing"
    with _connect(path)() as conn:
        assert conn.execute("SELECT COUNT(*) FROM token_ledger WHERE reason='chat_refund'").fetchone()[0] == 0
    now[0] += timedelta(seconds=1301)
    assert lifecycle.inspect(**common)["state"] == "failed"


def test_prompt_improvement_outer_deadline_allows_local_reasoning(monkeypatch):
    import main
    import pytest

    class DeadlineCaptured(BaseException):
        pass

    seen = []

    async def fake_wait(coroutine, *, timeout):
        coroutine.close()
        seen.append(timeout)
        raise DeadlineCaptured()

    monkeypatch.setattr(main, "require_trusted_user", lambda _request: {})
    monkeypatch.setattr(main.asyncio, "wait_for", fake_wait)
    for route in ("local", "api"):
        monkeypatch.setattr(main, "assistant_models_config", lambda: {"improve": {"route": route}})
        with pytest.raises(DeadlineCaptured):
            asyncio.run(main.improve_prompt(main.ImprovePromptRequest(prompt="Test"), object()))
    assert seen == [1860, 240]
