"""DeepSeek implementation of the portable text-provider contract."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from ..contracts import (
    ProviderChatRequest,
    ProviderError,
    ProviderEvent,
    TextDelta,
    TextModel,
    ToolCall,
    Usage,
)


DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODELS = (
    TextModel(
        id="deepseek-flash",
        name="DeepSeek V4.1 Flash",
        provider="deepseek",
        description="Быстрая актуальная модель DeepSeek.",
    ),
    TextModel(
        id="deepseek-v4-pro",
        name="DeepSeek V4 Pro",
        provider="deepseek",
        description="Старшая модель DeepSeek для сложных задач.",
    ),
)
GENERIC_SYSTEM_PROMPT = (
    "You are a helpful assistant. Answer the user directly and use clear Markdown when useful. "
    "When the user explicitly asks to create, draw, render, or generate an image, call the "
    "generate_image tool instead of claiming that an image was already generated."
)
IMAGE_TOOL = {
    "type": "function",
    "function": {
        "name": "generate_image",
        "description": "Generate an image requested by the user.",
        "parameters": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "A complete image-generation prompt.",
                },
                "aspect_ratio": {
                    "type": "string",
                    "enum": ["1:1", "9:16", "16:9", "3:2"],
                },
            },
            "required": ["prompt"],
            "additionalProperties": False,
        },
    },
}


def _status_error(status_code: int) -> ProviderError:
    if status_code in {401, 403}:
        return ProviderError(
            "auth",
            "DeepSeek API key недействителен или не имеет доступа.",
            status_code=401,
        )
    if status_code == 402:
        return ProviderError(
            "balance",
            "На аккаунте DeepSeek недостаточно средств для запроса.",
            status_code=402,
        )
    if status_code == 429:
        return ProviderError(
            "rate_limit",
            "DeepSeek временно ограничил частоту запросов. Повторите позже.",
            status_code=429,
        )
    if status_code == 400:
        return ProviderError(
            "bad_request",
            "DeepSeek отклонил параметры запроса.",
            status_code=400,
        )
    return ProviderError(
        "provider_unavailable",
        "DeepSeek временно недоступен.",
        status_code=503 if status_code >= 500 else 502,
    )


class DeepSeekProvider:
    provider_id = "deepseek"

    def __init__(
        self,
        *,
        base_url: str = DEEPSEEK_BASE_URL,
        timeout_seconds: float = 90.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds
        self._transport = transport

    def models(self) -> tuple[TextModel, ...]:
        return DEEPSEEK_MODELS

    def _client(self, api_key: str) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self._base_url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Accept": "application/json",
            },
            timeout=httpx.Timeout(self._timeout, connect=min(15.0, self._timeout)),
            transport=self._transport,
        )

    async def check(self, api_key: str) -> tuple[TextModel, ...]:
        try:
            async with self._client(api_key) as client:
                response = await client.get("/models")
        except (httpx.TimeoutException, httpx.RequestError) as exc:
            raise ProviderError(
                "network",
                "Не удалось подключиться к DeepSeek.",
                status_code=503,
            ) from exc
        if response.status_code >= 400:
            raise _status_error(response.status_code)
        try:
            payload = response.json()
        except ValueError as exc:
            raise ProviderError(
                "invalid_response",
                "DeepSeek вернул некорректный ответ.",
                status_code=502,
            ) from exc
        available = {
            str(item.get("id") or "")
            for item in payload.get("data", [])
            if isinstance(item, dict)
        }
        return tuple(model for model in DEEPSEEK_MODELS if model.id in available)

    def stream(
        self,
        api_key: str,
        request: ProviderChatRequest,
    ) -> AsyncIterator[ProviderEvent]:
        return self._stream(api_key, request)

    async def _stream(
        self,
        api_key: str,
        request: ProviderChatRequest,
    ) -> AsyncIterator[ProviderEvent]:
        if request.model not in {model.id for model in DEEPSEEK_MODELS}:
            raise ProviderError("model", "Неизвестная модель DeepSeek.", status_code=400)

        messages = [{"role": "system", "content": GENERIC_SYSTEM_PROMPT}]
        messages.extend(
            {"role": turn.role, "content": turn.content}
            for turn in request.messages
        )
        tool_choice: Any = "auto"
        if request.tool_choice == "generate_image":
            tool_choice = {
                "type": "function",
                "function": {"name": "generate_image"},
            }
        body = {
            "model": request.model,
            "messages": messages,
            "stream": True,
            "stream_options": {"include_usage": True},
            "thinking": {"type": "disabled"},
            "tools": [IMAGE_TOOL],
            "tool_choice": tool_choice,
        }
        tool_buffers: dict[int, dict[str, str]] = {}
        saw_output = False
        try:
            async with self._client(api_key) as client:
                async with client.stream(
                    "POST",
                    "/chat/completions",
                    json=body,
                    headers={"Accept": "text/event-stream"},
                ) as response:
                    if response.status_code >= 400:
                        await response.aread()
                        raise _status_error(response.status_code)
                    async for line in response.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if not data:
                            continue
                        if data == "[DONE]":
                            break
                        try:
                            payload = json.loads(data)
                        except json.JSONDecodeError:
                            continue
                        usage = payload.get("usage")
                        if isinstance(usage, dict):
                            yield Usage(
                                input_tokens=int(usage.get("prompt_tokens") or 0),
                                output_tokens=int(usage.get("completion_tokens") or 0),
                            )
                        choices = payload.get("choices")
                        if not isinstance(choices, list) or not choices:
                            continue
                        delta = choices[0].get("delta")
                        if not isinstance(delta, dict):
                            continue
                        content = delta.get("content")
                        if isinstance(content, str) and content:
                            saw_output = True
                            yield TextDelta(content)
                        for raw_call in delta.get("tool_calls") or []:
                            if not isinstance(raw_call, dict):
                                continue
                            index = int(raw_call.get("index") or 0)
                            buffer = tool_buffers.setdefault(
                                index,
                                {"id": "", "name": "", "arguments": ""},
                            )
                            if raw_call.get("id"):
                                buffer["id"] = str(raw_call["id"])
                            function = raw_call.get("function")
                            if isinstance(function, dict):
                                if function.get("name"):
                                    buffer["name"] = str(function["name"])
                                if function.get("arguments"):
                                    buffer["arguments"] += str(function["arguments"])
        except ProviderError:
            raise
        except (httpx.TimeoutException, httpx.RequestError) as exc:
            raise ProviderError(
                "network",
                "Соединение с DeepSeek было прервано.",
                status_code=503,
            ) from exc

        for index in sorted(tool_buffers):
            buffer = tool_buffers[index]
            try:
                arguments = json.loads(buffer["arguments"] or "{}")
            except json.JSONDecodeError:
                arguments = {}
            if not isinstance(arguments, dict):
                arguments = {}
            if buffer["name"]:
                saw_output = True
                yield ToolCall(
                    name=buffer["name"],
                    arguments=arguments,
                    call_id=buffer["id"],
                )
        if not saw_output:
            raise ProviderError(
                "empty_response",
                "DeepSeek не вернул ответ.",
                status_code=502,
            )
