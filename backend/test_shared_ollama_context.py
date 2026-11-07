"""Verify shared context reaches the provider without real inference."""
import asyncio

from app.api.routers import phone_chat
from app.api.routers.phone_chat import PhoneChatDependencies, PhoneChatRequest


def test_local_chat_preserves_shared_64k_context_in_provider_request(monkeypatch):
    captured = []

    async def fake_ollama(*, body, timeout_seconds):
        captured.append(body)
        return "Ready.", {"message": {"content": "Ready."}}

    monkeypatch.setattr(phone_chat, "request_ollama_chat_message", fake_ollama)
    deps = PhoneChatDependencies(
        require_trusted_user=lambda _request: {},
        assistant_models_config=lambda: {},
        openrouter_headers=lambda: {},
        record_openrouter_availability=lambda _status: None,
        record_event=lambda *args, **kwargs: None,
        openrouter_text_models=lambda: [],
        request_lifecycle=None,
    )
    request = PhoneChatRequest(messages=[{"role": "user", "content": "Hello"}])
    config = {"localModel": "qwen3.8:27b", "localNumCtx": 65536}
    asyncio.run(phone_chat.phone_chat_ollama(request, deps, config))
    assert captured[0]["options"]["num_ctx"] == 65536
