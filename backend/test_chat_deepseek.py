from __future__ import annotations

import asyncio
import json

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routers.chat_portable import (
    PortableChatDependencies,
    create_portable_chat_router,
)
from app.chat_core.contracts import ProviderChatRequest, ChatTurn, TextDelta, ToolCall
from app.chat_core.providers.deepseek import DeepSeekProvider
from app.chat_core.user_secrets import UserProviderSecrets, provider_secret_name


class MemorySecretStore:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def exists(self, name: str) -> bool:
        return name in self.values

    def get(self, name: str) -> str:
        return self.values.get(name, "")

    def set(self, name: str, value: str) -> None:
        self.values[name] = value

    def delete(self, name: str) -> bool:
        return self.values.pop(name, None) is not None


def test_provider_secret_name_is_stable_and_does_not_leak_user_id() -> None:
    first = provider_secret_name("student@example.test", "deepseek")
    second = provider_secret_name("student@example.test", "deepseek")
    other = provider_secret_name("other@example.test", "deepseek")
    assert first == second
    assert first != other
    assert "student" not in first
    assert len(first) <= 64


def test_deepseek_provider_checks_models_and_streams_text_and_tool() -> None:
    sse = "\n".join(
        [
            'data: {"choices":[{"delta":{"content":"Hello "}}]}',
            'data: {"choices":[{"delta":{"content":"world"}}]}',
            'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_1","function":{"name":"generate_image","arguments":"{\\\"prompt\\\":\\\"cat\\\","}}]}}]}',
            'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"\\\"aspect_ratio\\\":\\\"1:1\\\"}"}}]}}]}',
            'data: [DONE]',
            "",
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/models":
            return httpx.Response(
                200,
                json={
                    "object": "list",
                    "data": [
                        {"id": "deepseek-flash"},
                        {"id": "deepseek-v4-pro"},
                    ],
                },
            )
        assert request.url.path == "/chat/completions"
        return httpx.Response(200, text=sse, headers={"Content-Type": "text/event-stream"})

    provider = DeepSeekProvider(transport=httpx.MockTransport(handler))
    checked = asyncio.run(provider.check("test-key-123456"))
    assert [item.id for item in checked] == ["deepseek-flash", "deepseek-v4-pro"]

    async def collect():
        request = ProviderChatRequest(
            model="deepseek-flash",
            messages=(ChatTurn(role="user", content="draw a cat"),),
        )
        return [item async for item in provider.stream("test-key-123456", request)]

    events = asyncio.run(collect())
    assert "".join(item.text for item in events if isinstance(item, TextDelta)) == "Hello world"
    tool = next(item for item in events if isinstance(item, ToolCall))
    assert tool.name == "generate_image"
    assert tool.arguments == {"prompt": "cat", "aspect_ratio": "1:1"}


def test_portable_router_never_echoes_key_and_streams_normalized_events() -> None:
    class FakeProvider:
        provider_id = "deepseek"

        def models(self):
            return DeepSeekProvider().models()

        async def check(self, api_key: str):
            assert api_key == "saved-key-123456"
            return self.models()

        async def stream(self, api_key: str, request: ProviderChatRequest):
            assert api_key == "saved-key-123456"
            assert request.model == "deepseek-flash"
            yield TextDelta("Готово")
            yield ToolCall(
                "generate_image",
                {"prompt": "violet robot", "aspect_ratio": "16:9"},
                "call_1",
            )

    store = MemorySecretStore()
    app = FastAPI()
    app.include_router(
        create_portable_chat_router(
            PortableChatDependencies(
                require_trusted_user=lambda _request: {
                    "internal_user_id": "internal-user-1",
                    "legacy_user_id": "legacy-user-1",
                },
                secret_store=store,
                providers={"deepseek": FakeProvider()},
            )
        )
    )
    client = TestClient(app)

    saved = client.put(
        "/api/chat/providers/deepseek/key",
        json={"key": "saved-key-123456"},
    )
    assert saved.status_code == 200
    assert "saved-key-123456" not in saved.text

    status = client.get("/api/chat/providers/deepseek")
    assert status.json()["configured"] is True
    assert "saved-key-123456" not in status.text

    checked = client.post("/api/chat/providers/deepseek/test")
    assert checked.status_code == 200
    assert checked.json()["connected"] is True
    assert "saved-key-123456" not in checked.text

    streamed = client.post(
        "/api/chat/stream",
        json={
            "provider": "deepseek",
            "model": "deepseek-flash",
            "messages": [{"role": "user", "content": "Нарисуй робота"}],
            "toolChoice": "auto",
        },
    )
    assert streamed.status_code == 200
    events = [json.loads(line) for line in streamed.text.splitlines() if line]
    assert any(item["type"] == "delta" and item["text"] == "Готово" for item in events)
    assert any(
        item["type"] == "tool"
        and item["tool"]["name"] == "generate_image"
        and item["tool"]["status"] == "requested"
        for item in events
    )
    assert events[-1]["type"] == "done"


def test_user_provider_secrets_isolate_users() -> None:
    store = MemorySecretStore()
    secrets = UserProviderSecrets(store)
    secrets.set("u1", "deepseek", "key-one")
    secrets.set("u2", "deepseek", "key-two")
    assert secrets.get("u1", "deepseek") == "key-one"
    assert secrets.get("u2", "deepseek") == "key-two"
    assert secrets.delete("u1", "deepseek") is True
    assert secrets.get("u1", "deepseek") == ""
