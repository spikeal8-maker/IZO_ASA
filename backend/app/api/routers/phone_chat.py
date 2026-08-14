"""Authenticated phone-chat route and provider routing."""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ...config import load_provider_endpoint_policy
from ...integrations.ollama import request_ollama_chat_message
from ...integrations.openrouter import (
    extract_openrouter_generation_cost,
    format_openrouter_public_error,
    request_openrouter_chat_completion,
)


PROVIDER_ENDPOINTS = load_provider_endpoint_policy()
PHONE_CHAT_SYSTEM_PROMPT = (
    "Ты — помощник ИЗО АСА. Отвечай по-русски, понятно и по существу. "
    "Помогай формулировать идеи для изображений, видео и публикаций, но не утверждай, "
    "что файл или генерация уже созданы, если ты вернул только текст. "
    "Если запрос не связан с творчеством, всё равно дай полезный краткий ответ."
)
_phone_chat_semaphore = asyncio.Semaphore(
    max(1, min(8, int(os.getenv("PHONE_CHAT_CONCURRENCY", "3"))))
)


class PhoneChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class PhoneChatRequest(BaseModel):
    messages: list[PhoneChatTurn] = Field(min_length=1, max_length=20)
    route: Literal["auto", "local", "api"] = "auto"
    images: list[str] = Field(default_factory=list, max_length=4)


@dataclass(frozen=True)
class PhoneChatDependencies:
    require_trusted_user: Callable[[Request], dict[str, Any]]
    assistant_models_config: Callable[[], dict[str, Any]]
    openrouter_headers: Callable[[], dict[str, str]]
    record_openrouter_availability: Callable[[int], None]
    record_event: Callable[..., None]


def _phone_chat_image_payloads(images: list[str]) -> list[tuple[str, str]]:
    if sum(len(value) for value in images) > 12_000_000:
        raise ValueError("Вложения чата слишком большие.")
    normalized: list[tuple[str, str]] = []
    for value in images:
        match = re.fullmatch(
            r"data:image/(jpeg|jpg|png|webp);base64,([A-Za-z0-9+/=\r\n]+)",
            value.strip(),
            flags=re.IGNORECASE,
        )
        if not match:
            raise ValueError("Чат принимает изображения JPEG, PNG или WebP.")
        media_type = "jpeg" if match.group(1).lower() == "jpg" else match.group(1).lower()
        normalized.append((media_type, re.sub(r"\s+", "", match.group(2))))
    return normalized


def _phone_chat_history(req: PhoneChatRequest) -> list[dict[str, Any]]:
    return [{"role": turn.role, "content": turn.content.strip()} for turn in req.messages[-20:]]


def _openrouter_text_content(payload: dict[str, Any]) -> str:
    choices = payload.get("choices") if isinstance(payload, dict) else None
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise RuntimeError("OpenRouter не вернул текст улучшенного промпта.")
    message = choices[0].get("message") if isinstance(choices[0].get("message"), dict) else {}
    content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, dict):
        return json.dumps(content, ensure_ascii=False)
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict):
                value = part.get("text") or part.get("content") or part.get("value")
                if isinstance(value, str):
                    parts.append(value)
                elif isinstance(value, dict):
                    parts.append(json.dumps(value, ensure_ascii=False))
        if parts:
            return "".join(parts).strip()
    parsed = message.get("parsed")
    if isinstance(parsed, dict):
        return json.dumps(parsed, ensure_ascii=False)
    tool_calls = message.get("tool_calls")
    if isinstance(tool_calls, list):
        for call in tool_calls:
            function = call.get("function") if isinstance(call, dict) and isinstance(call.get("function"), dict) else {}
            arguments = function.get("arguments")
            if isinstance(arguments, str) and arguments.strip():
                return arguments.strip()
            if isinstance(arguments, dict):
                return json.dumps(arguments, ensure_ascii=False)
    choice_text = choices[0].get("text")
    if isinstance(choice_text, str) and choice_text.strip():
        return choice_text.strip()
    raise RuntimeError("OpenRouter вернул неподдерживаемый формат текста.")


async def phone_chat_ollama(
    req: PhoneChatRequest,
    deps: PhoneChatDependencies,
    config: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any], str]:
    config = config or deps.assistant_models_config()["improve"]
    images = _phone_chat_image_payloads(req.images)
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": PHONE_CHAT_SYSTEM_PROMPT},
        *_phone_chat_history(req),
    ]
    if images:
        messages[-1] = {**messages[-1], "images": [encoded for _kind, encoded in images]}
    model = str(config.get("localModel") or "gemma4:31b-cloud")
    keep_alive = os.getenv("OLLAMA_KEEP_ALIVE", "-1").strip() or "-1"
    body = {
        "model": model,
        "stream": False,
        "think": False,
        "keep_alive": int(keep_alive) if keep_alive.lstrip("+-").isdigit() else keep_alive,
        "messages": messages,
        "options": {"temperature": 0.45, "num_predict": 1000, "num_ctx": 16384},
    }
    timeout = max(10, min(180, int(config.get("localTimeoutSeconds") or 45)))
    content, payload = await request_ollama_chat_message(body=body, timeout_seconds=timeout)
    reply = content.strip()
    if not reply:
        raise RuntimeError("Чат не вернул ответ.")
    return reply[:8000], payload if isinstance(payload, dict) else {}, model


async def phone_chat_openrouter(
    req: PhoneChatRequest,
    deps: PhoneChatDependencies,
    config: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any], str]:
    headers = deps.openrouter_headers()
    if not headers.get("Authorization", "").removeprefix("Bearer ").strip():
        raise RuntimeError("Облачный маршрут чата не настроен.")
    config = config or deps.assistant_models_config()["improve"]
    images = _phone_chat_image_payloads(req.images)
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": PHONE_CHAT_SYSTEM_PROMPT},
        *_phone_chat_history(req),
    ]
    if images:
        messages[-1] = {
            "role": messages[-1]["role"],
            "content": [
                {"type": "text", "text": messages[-1]["content"]},
                *[
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/{kind};base64,{encoded}"},
                    }
                    for kind, encoded in images
                ],
            ],
        }
    model = str(config.get("apiModel") or PROVIDER_ENDPOINTS.prompt_improve_model)
    body = {"model": model, "messages": messages, "temperature": 0.45, "max_tokens": 1000}
    timeout = max(10, min(90, int(config.get("apiTimeoutSeconds") or 30)))
    status_code, payload = await request_openrouter_chat_completion(
        base_url=PROVIDER_ENDPOINTS.openrouter_base_url,
        headers=headers,
        body=body,
        timeout_seconds=timeout,
    )
    if status_code >= 400:
        deps.record_openrouter_availability(status_code)
        safe_payload = payload if isinstance(payload, dict) else {}
        raise RuntimeError(
            format_openrouter_public_error(
                status_code,
                safe_payload,
                truncate=lambda value, limit: value[:limit],
            )
        )
    deps.record_openrouter_availability(200)
    if not isinstance(payload, dict):
        raise RuntimeError("Чат вернул некорректный ответ.")
    reply = _openrouter_text_content(payload).strip()
    if not reply:
        raise RuntimeError("Чат не вернул ответ.")
    return reply[:8000], payload, model


async def route_phone_chat(
    req: PhoneChatRequest,
    deps: PhoneChatDependencies,
) -> tuple[str, dict[str, Any], str, str]:
    config = deps.assistant_models_config()["improve"]
    providers = ["local", "api"] if req.route == "auto" else [req.route]
    last_error: Exception | None = None
    async with _phone_chat_semaphore:
        for provider in providers:
            try:
                if provider == "local":
                    reply, payload, model = await phone_chat_ollama(req, deps, config)
                else:
                    reply, payload, model = await phone_chat_openrouter(req, deps, config)
                return reply, payload, provider, model
            except (httpx.HTTPError, RuntimeError, ValueError) as exc:
                last_error = exc
    raise RuntimeError(str(last_error or "Чат временно недоступен."))


def create_phone_chat_router(deps: PhoneChatDependencies) -> APIRouter:
    router = APIRouter()

    @router.post("/api/phone/chat")
    async def phone_chat(req: PhoneChatRequest, request: Request) -> dict[str, Any]:
        trusted = deps.require_trusted_user(request)
        if req.messages[-1].role != "user":
            raise HTTPException(400, "Последним в чате должно быть сообщение пользователя.")
        try:
            _phone_chat_image_payloads(req.images)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        started = time.monotonic()
        try:
            reply, provider_payload, provider, model = await asyncio.wait_for(
                route_phone_chat(req, deps),
                timeout=185,
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except asyncio.TimeoutError as exc:
            raise HTTPException(504, "Чат отвечает слишком долго. Повторите запрос.") from exc
        except (httpx.HTTPError, RuntimeError) as exc:
            raise HTTPException(
                502,
                "Чат временно недоступен. Повторите позже или обратитесь в поддержку.",
            ) from exc
        usage = provider_payload.get("usage") if isinstance(provider_payload.get("usage"), dict) else {}
        cost = extract_openrouter_generation_cost(provider_payload) if provider == "api" else 0
        deps.record_event(
            "phone_chat_answered",
            internal_user_id=trusted.get("internal_user_id"),
            legacy_user_id=trusted.get("legacy_user_id"),
            session_id=trusted.get("session_id"),
            platform="web",
            request=request,
            properties={
                "model": model,
                "provider": provider,
                "message_count": len(req.messages),
                "input_chars": sum(len(turn.content) for turn in req.messages),
                "image_count": len(req.images),
                "output_chars": len(reply),
                "latency_ms": round((time.monotonic() - started) * 1000),
                "cost_usd": cost,
            },
        )
        return {
            "ok": True,
            "reply": reply,
            "model": model,
            "provider": provider,
            "usage": usage,
            "costUsd": cost,
        }

    return router
