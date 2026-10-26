"""Authenticated phone-chat route and provider routing."""

from __future__ import annotations

import asyncio
import json
import math
import os
import re
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
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
from ...services import chat_billing, chat_request_lifecycle, chat_tool_policy, phone_chat_history


PROVIDER_ENDPOINTS = load_provider_endpoint_policy()
PHONE_CHAT_SYSTEM_PROMPT = (
    "Ты — помощник ИЗО АСА. Сегодня {current_date}. Отвечай по-русски, понятно и по существу. "
    "У тебя есть инструменты web_search и generate_image. Сам вызывай web_search, когда пользователь просит "
    "свежую, текущую или проверяемую информацию из интернета. Сам вызывай generate_image, когда пользователь "
    "явно просит создать, нарисовать или сгенерировать изображение. Не вызывай генерацию, если пользователь "
    "только обсуждает идею или просит написать промпт. "
    "Для текущей погоды, новостей, цен и прямой просьбы найти или проверить что-либо в интернете обязательно "
    "используй web_search. Никогда не говори, что у тебя нет интернета, пока не попробовал этот инструмент. "
    "Помогай формулировать идеи для изображений, видео и публикаций, но не утверждай, "
    "что файл или генерация уже созданы, если ты вернул только текст. "
    "Сначала дай прямой ответ. Пиши компактно: обычно 1–3 коротких абзаца или не больше трёх пунктов. "
    "Для погоды начни с одной строки: город, температура и состояние; затем только осадки, ветер и важное предупреждение. "
    "Не делай заголовок ради одного короткого ответа, не пересказывай вопрос и не описывай процесс поиска. "
    "Никогда не показывай JSON, имена полей, аргументы или внутренний результат вызова инструмента. "
    "После вызова инструмента не повторяй длинный промпт и дай только короткое человеческое пояснение. "
    "Если запрос не связан с творчеством, всё равно дай полезный краткий ответ."
)
PHONE_CHAT_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Найти в интернете актуальную информацию и источники. Использовать для свежих фактов, новостей, цен, расписаний и проверки сведений.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Точный поисковый запрос на языке пользователя"},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_image",
            "description": "Запустить реальную генерацию изображения в ИЗО АСА, когда пользователь прямо просит создать изображение.",
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {"type": "string", "description": "Подробное описание изображения без служебных комментариев"},
                    "aspect_ratio": {"type": "string", "enum": ["1:1", "9:16", "16:9", "3:2"], "description": "Формат изображения"},
                },
                "required": ["prompt"],
                "additionalProperties": False,
            },
        },
    },
]
_phone_chat_semaphore = asyncio.Semaphore(
    max(1, min(8, int(os.getenv("PHONE_CHAT_CONCURRENCY", "3"))))
)


class PhoneChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class PhoneChatRequest(BaseModel):
    messages: list[PhoneChatTurn] = Field(min_length=1, max_length=100)
    route: Literal["auto", "local", "api"] = "auto"
    toolChoice: Literal["auto", "web_search", "generate_image"] = "auto"
    modelId: str | None = Field(default=None, max_length=200)
    requestId: str = Field(default_factory=lambda: uuid.uuid4().hex, min_length=8, max_length=100, pattern=r"^[A-Za-z0-9._:-]+$")
    images: list[str] = Field(default_factory=list, max_length=4)
    threadId: str | None = Field(default=None, min_length=8, max_length=64, pattern=r"^[a-fA-F0-9]+$")


class PhoneChatThreadCreate(BaseModel):
    title: str = Field(default="Новый чат", max_length=80)
    chatModelId: str = Field(default="local:izo-chat", max_length=200)
    imageModelId: str | None = Field(default=None, max_length=200)
    videoModelId: str | None = Field(default=None, max_length=200)
    contextChars: int = Field(default=480000, ge=4000, le=480000)


class PhoneChatThreadUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=80)
    chatModelId: str | None = Field(default=None, max_length=200)
    imageModelId: str | None = Field(default=None, max_length=200)
    videoModelId: str | None = Field(default=None, max_length=200)
    contextChars: int | None = Field(default=None, ge=4000, le=480000)


class PhoneChatToolsUpdate(BaseModel):
    tools: list[dict[str, Any]] = Field(default_factory=list, max_length=8)


@dataclass(frozen=True)
class PhoneChatDependencies:
    require_trusted_user: Callable[[Request], dict[str, Any]]
    assistant_models_config: Callable[[], dict[str, Any]]
    openrouter_headers: Callable[[], dict[str, str]]
    record_openrouter_availability: Callable[[int], None]
    record_event: Callable[..., None]
    openrouter_text_models: Callable[[], Any]
    request_lifecycle: chat_request_lifecycle.ChatRequestLifecycle | None
    connect_db: Callable[[], Any] | None = None
    usd_rub_snapshot: Callable[[], dict[str, Any]] | None = None
    openrouter_economy: Callable[[], dict[str, float]] | None = None


def _chat_config(deps: PhoneChatDependencies) -> dict[str, Any]:
    config = deps.assistant_models_config()
    return config.get("chat") if isinstance(config.get("chat"), dict) else config["improve"]


def _resolve_phone_chat_model(req: PhoneChatRequest, config: dict[str, Any], plan: str | None = None) -> tuple[str, str, str, float, str]:
    published_api = {
        str(value) for value in config.get("publishedApiModels", config.get("enabledApiModels", []))
        if str(value).strip()
    }
    enabled_api = [str(value) for value in config.get("enabledApiModels", []) if str(value).strip()]
    selected = str(req.modelId or "").strip()
    if not selected:
        if req.route == "local":
            selected = "local:izo-chat"
        elif req.route == "api":
            selected = enabled_api[0] if enabled_api else str(config.get("apiModel") or "")
        else:
            selected = str(config.get("defaultModel") or "local:izo-chat")
    if selected == "local:izo-chat":
        if config.get("enabled") is False or config.get("localEnabled") is False:
            raise ValueError("Локальная модель чата сейчас отключена.")
        return selected, "local", str(config.get("localModel") or "gemma4:12b"), 0.0, "free"
    if config.get("enabled") is False or selected not in published_api or selected not in enabled_api:
        raise ValueError("Эта модель чата сейчас недоступна.")
    if plan is not None:
        tier_access = config.get("apiTierAccess") if isinstance(config.get("apiTierAccess"), dict) else {}
        allowed = set(enabled_api) if str(plan).lower() == "admin" else {str(value) for value in tier_access.get(str(plan).lower(), []) if str(value).strip()}
        if selected not in allowed:
            raise ValueError("Эта модель недоступна на вашем тарифе. Выберите другую модель.")
    costs = config.get("apiTokenCosts") if isinstance(config.get("apiTokenCosts"), dict) else {}
    return selected, "api", selected, float(costs.get(selected) or 0.1), "main"


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
    remaining = 480000
    selected: list[dict[str, Any]] = []
    for turn in reversed(req.messages):
        content = turn.content.strip()
        if selected and len(content) > remaining:
            break
        selected.append({"role": turn.role, "content": content[-remaining:]})
        remaining -= min(remaining, len(content))
        if remaining <= 0:
            break
    return list(reversed(selected))


def _system_prompt() -> str:
    return PHONE_CHAT_SYSTEM_PROMPT.format(current_date=date.today().isoformat())


def _required_web_query(req: PhoneChatRequest) -> str:
    """Guarantee a search for explicit live-data requests if a small model misses tool selection."""

    latest = req.messages[-1].content.strip()
    if req.toolChoice != "auto":
        return ""
    normalized = re.sub(r"\s+", " ", latest.lower())
    explicit_search = re.search(r"\b(найди|поищи|посмотри|проверь)\b.{0,80}\b(интернет|сеть|онлайн|сайт)", normalized)
    live_weather = re.search(r"\b(погода|температура|прогноз)\b", normalized) and re.search(
        r"\b(сейчас|сегодня|завтра|текущ|какая|какой|москв|город|на улице)\w*\b", normalized
    )
    return latest[:500] if explicit_search or live_weather else ""


def _required_search_arguments(req: PhoneChatRequest, provider_context: str = "") -> dict[str, Any]:
    return chat_tool_policy.required_search_arguments(req.messages, req.images, provider_context)


def _forced_search_model_arguments(req: PhoneChatRequest, arguments: dict[str, Any]) -> dict[str, Any]:
    return chat_tool_policy.forced_search_model_arguments(req.messages, req.images, arguments)


def _explicit_image_aspect_ratio(req: PhoneChatRequest) -> str | None:
    return chat_tool_policy.explicit_image_aspect_ratio(req.messages)


def _requested_image_aspect_ratio(req: PhoneChatRequest) -> str:
    return chat_tool_policy.requested_image_aspect_ratio(req.messages)


def _forced_image_model_arguments(req: PhoneChatRequest, arguments: dict[str, Any]) -> dict[str, Any]:
    return chat_tool_policy.forced_image_model_arguments(req.messages, req.images, arguments)


def _required_image_arguments(req: PhoneChatRequest, provider_context: str = "") -> dict[str, Any]:
    return chat_tool_policy.required_image_arguments(req.messages, req.images, provider_context)


def _round_tools(req: PhoneChatRequest, used_tools: set[str]) -> list[dict[str, Any]]:
    return chat_tool_policy.round_tools(req.toolChoice, used_tools, PHONE_CHAT_TOOLS)


def _tool_allowed(req: PhoneChatRequest, name: str) -> bool:
    return chat_tool_policy.tool_allowed(req.toolChoice, name)


def _assistant_message(payload: dict[str, Any]) -> dict[str, Any]:
    choices = payload.get("choices") if isinstance(payload, dict) else None
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        message = choices[0].get("message")
        if isinstance(message, dict):
            return message
    message = payload.get("message") if isinstance(payload, dict) else None
    return message if isinstance(message, dict) else {}


def _tool_calls(payload: dict[str, Any]) -> list[dict[str, Any]]:
    calls = _assistant_message(payload).get("tool_calls")
    return [call for call in calls if isinstance(call, dict)] if isinstance(calls, list) else []


def _tool_call(call: dict[str, Any]) -> tuple[str, dict[str, Any], str]:
    function = call.get("function") if isinstance(call.get("function"), dict) else {}
    name = str(function.get("name") or "").strip()
    raw = function.get("arguments")
    if isinstance(raw, str):
        try:
            arguments = json.loads(raw)
        except json.JSONDecodeError:
            arguments = {}
    else:
        arguments = raw if isinstance(raw, dict) else {}
    return name, arguments, str(call.get("id") or f"call_{uuid.uuid4().hex[:12]}")


def _web_sources(payload: dict[str, Any]) -> list[dict[str, str]]:
    annotations = _assistant_message(payload).get("annotations")
    sources: list[dict[str, str]] = []
    seen: set[str] = set()
    for annotation in annotations if isinstance(annotations, list) else []:
        citation = annotation.get("url_citation") if isinstance(annotation, dict) and isinstance(annotation.get("url_citation"), dict) else {}
        url = str(citation.get("url") or "").strip()
        if not url.startswith(("https://", "http://")) or url in seen:
            continue
        seen.add(url)
        sources.append({"url": url[:2000], "title": str(citation.get("title") or url)[:240]})
    return sources[:8]


async def _web_search(query: str, deps: PhoneChatDependencies, config: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    value = re.sub(r"\s+", " ", query).strip()[:500]
    if len(value) < 2:
        return {"ok": False, "error": "Поисковый запрос пустой."}, {}
    headers = deps.openrouter_headers()
    if not headers.get("Authorization", "").removeprefix("Bearer ").strip():
        return {"ok": False, "error": "Поиск временно недоступен."}, {}
    body = {
        "model": str(config.get("apiModel") or PROVIDER_ENDPOINTS.prompt_improve_model),
        "messages": [
            {"role": "system", "content": "Найди актуальные сведения по запросу. Ответь кратко на русском языке и опирайся только на найденные источники."},
            {"role": "user", "content": value},
        ],
        "tools": [{"type": "openrouter:web_search", "max_total_results": 5, "search_context_size": "medium"}],
        "max_tokens": 900,
        "temperature": 0.2,
    }
    status_code, payload = await request_openrouter_chat_completion(
        base_url=PROVIDER_ENDPOINTS.openrouter_base_url,
        headers=headers,
        body=body,
        timeout_seconds=max(20, min(90, int(config.get("apiTimeoutSeconds") or 60))),
    )
    if status_code >= 400 or not isinstance(payload, dict):
        deps.record_openrouter_availability(status_code)
        return {"ok": False, "error": "Поиск временно недоступен."}, payload if isinstance(payload, dict) else {}
    deps.record_openrouter_availability(200)
    summary = _openrouter_text_content(payload).strip()
    sources = _web_sources(payload)
    return {"ok": True, "query": value, "summary": summary[:6000], "sources": sources}, payload


async def _execute_tool(name: str, arguments: dict[str, Any], deps: PhoneChatDependencies, config: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    if name == "web_search":
        return await _web_search(str(arguments.get("query") or ""), deps, config)
    if name == "generate_image":
        prompt = re.sub(r"\s+", " ", str(arguments.get("prompt") or "")).strip()[:3000]
        aspect_ratio = str(arguments.get("aspect_ratio") or "1:1")
        if aspect_ratio not in {"1:1", "9:16", "16:9", "3:2"}:
            aspect_ratio = "1:1"
        if not prompt:
            return {"ok": False, "error": "Описание изображения пустое."}, {}
        return {"ok": True, "status": "requested", "prompt": prompt, "aspectRatio": aspect_ratio}, {}
    return {"ok": False, "error": "Неизвестный инструмент."}, {}


async def _append_synthetic_tool_call(
    *,
    name: str,
    arguments_value: dict[str, Any],
    messages: list[dict[str, Any]],
    deps: PhoneChatDependencies,
    config: dict[str, Any],
    openrouter_style: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    async def execute_tool(tool_name: str, arguments: dict[str, Any]):
        return await _execute_tool(tool_name, arguments, deps, config)

    return await chat_tool_policy.append_synthetic_tool_call(
        name=name,
        arguments=arguments_value,
        messages=messages,
        execute_tool=execute_tool,
        openrouter_style=openrouter_style,
    )


async def _prime_required_tool(
    req: PhoneChatRequest,
    messages: list[dict[str, Any]],
    deps: PhoneChatDependencies,
    config: dict[str, Any],
    *,
    openrouter_style: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], set[str]]:
    async def execute_tool(name: str, arguments: dict[str, Any]):
        return await _execute_tool(name, arguments, deps, config)

    return await chat_tool_policy.prime_required_tool(
        tool_choice=req.toolChoice,
        messages=messages,
        required_web_query=_required_web_query(req),
        execute_tool=execute_tool,
        openrouter_style=openrouter_style,
    )


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


def _public_tool_reply(reply: str, used_tools: set[str]) -> str:
    """Keep internal tool envelopes out of the user-facing chat transcript."""
    value = reply.strip()
    if "generate_image" not in used_tools:
        return value
    parsed: Any = None
    try:
        parsed = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        pass
    if isinstance(parsed, dict) and (
        parsed.get("action") == "generate_image"
        or "action_input" in parsed
        or {"prompt", "aspect_ratio"}.intersection(parsed)
    ):
        return "Создаю изображение."
    if re.match(r"^\s*\{[\s\S]*(?:action|action_input|generate_image)[\s\S]*\}\s*$", value, re.I):
        return "Создаю изображение."
    return value


async def phone_chat_ollama(
    req: PhoneChatRequest,
    deps: PhoneChatDependencies,
    config: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any], str]:
    config = config or _chat_config(deps)
    images = _phone_chat_image_payloads(req.images)
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": _system_prompt()},
        *_phone_chat_history(req),
    ]
    if images:
        messages[-1] = {**messages[-1], "images": [encoded for _kind, encoded in images]}
    model = str(config.get("localModel") or "gemma4:31b-cloud")
    keep_alive = os.getenv("OLLAMA_KEEP_ALIVE", "-1").strip() or "-1"
    timeout = max(10, min(1800, int(config.get("localTimeoutSeconds") or 1800)))
    tool_runs, tool_payloads, used_tools = await _prime_required_tool(
        req, messages, deps, config, openrouter_style=False,
    )
    payload: dict[str, Any] = {}
    for _round in range(3):
        round_tools = _round_tools(req, used_tools)
        body = {
            "model": model,
            "stream": False,
            "think": "xhigh" if model == "qwen3.8:27b" else False,
            "keep_alive": int(keep_alive) if keep_alive.lstrip("+-").isdigit() else keep_alive,
            "messages": messages,
            "options": {
                "temperature": 0.35,
                "num_predict": -1 if model == "qwen3.8:27b" else 1000,
                "num_ctx": max(4096, min(120000, int(config.get("localNumCtx") or 120000))),
            },
        }
        if round_tools:
            body["tools"] = round_tools
        content, raw_payload = await request_ollama_chat_message(body=body, timeout_seconds=timeout)
        payload = raw_payload if isinstance(raw_payload, dict) else {}
        calls = _tool_calls(payload)
        if not calls:
            if req.toolChoice != "auto" and req.toolChoice not in used_tools:
                arguments_value = (
                    _required_image_arguments(req, content)
                    if req.toolChoice == "generate_image"
                    else _required_search_arguments(req, content)
                )
                tool_run, provider_payload = await _append_synthetic_tool_call(
                    name=req.toolChoice,
                    arguments_value=arguments_value,
                    messages=messages,
                    deps=deps,
                    config=config,
                    openrouter_style=False,
                )
                tool_runs.append(tool_run)
                if provider_payload:
                    tool_payloads.append(provider_payload)
                used_tools.add(req.toolChoice)
                continue
            reply = _public_tool_reply(content, used_tools)
            if not reply:
                raise RuntimeError("Чат не вернул ответ.")
            payload["_izo_tool_runs"] = tool_runs
            payload["_izo_tool_payloads"] = tool_payloads
            return reply, payload, model
        messages.append({**_assistant_message(payload), "role": "assistant"})
        for call in calls[:2]:
            name, arguments, _call_id = _tool_call(call)
            if not _tool_allowed(req, name):
                result = {"ok": False, "error": "Этот инструмент не выбран для текущего запроса."}
                messages.append({"role": "tool", "tool_name": name, "content": json.dumps(result, ensure_ascii=False)})
                continue
            if name == "generate_image" and req.toolChoice == "generate_image":
                arguments = _forced_image_model_arguments(req, arguments)
            if name == "web_search" and req.toolChoice == "web_search":
                arguments = _forced_search_model_arguments(req, arguments)
            if name in used_tools:
                result, provider_payload = {"ok": False, "error": "Этот инструмент уже использован в текущем ответе."}, {}
            else:
                result, provider_payload = await _execute_tool(name, arguments, deps, config)
                used_tools.add(name)
            tool_runs.append({"name": name, **result})
            if provider_payload:
                tool_payloads.append(provider_payload)
            messages.append({"role": "tool", "tool_name": name, "content": json.dumps(result, ensure_ascii=False)})
    raise RuntimeError("Чат превысил допустимое число вызовов инструментов.")


async def phone_chat_openrouter(
    req: PhoneChatRequest,
    deps: PhoneChatDependencies,
    config: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any], str]:
    headers = deps.openrouter_headers()
    if not headers.get("Authorization", "").removeprefix("Bearer ").strip():
        raise RuntimeError("Облачный маршрут чата не настроен.")
    config = config or _chat_config(deps)
    images = _phone_chat_image_payloads(req.images)
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": _system_prompt()},
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
    timeout = max(10, min(90, int(config.get("apiTimeoutSeconds") or 30)))
    tool_runs, tool_payloads, used_tools = await _prime_required_tool(
        req, messages, deps, config, openrouter_style=True,
    )
    payload: dict[str, Any] = {}
    for _round in range(3):
        body = {"model": model, "messages": messages, "temperature": 0.35, "max_tokens": 1000}
        round_tools = _round_tools(req, used_tools)
        if round_tools:
            body["tools"] = round_tools
        status_code, raw_payload = await request_openrouter_chat_completion(
            base_url=PROVIDER_ENDPOINTS.openrouter_base_url,
            headers=headers,
            body=body,
            timeout_seconds=timeout,
        )
        payload = raw_payload if isinstance(raw_payload, dict) else {}
        if status_code >= 400:
            deps.record_openrouter_availability(status_code)
            raise RuntimeError(
                format_openrouter_public_error(
                    status_code,
                    payload,
                    truncate=lambda value, limit: value[:limit],
                )
            )
        deps.record_openrouter_availability(200)
        calls = _tool_calls(payload)
        if not calls:
            try:
                content = _openrouter_text_content(payload)
            except RuntimeError:
                content = ""
            if req.toolChoice != "auto" and req.toolChoice not in used_tools:
                arguments_value = (
                    _required_image_arguments(req, content)
                    if req.toolChoice == "generate_image"
                    else _required_search_arguments(req, content)
                )
                tool_run, provider_payload = await _append_synthetic_tool_call(
                    name=req.toolChoice,
                    arguments_value=arguments_value,
                    messages=messages,
                    deps=deps,
                    config=config,
                    openrouter_style=True,
                )
                tool_runs.append(tool_run)
                if provider_payload:
                    tool_payloads.append(provider_payload)
                used_tools.add(req.toolChoice)
                if payload:
                    tool_payloads.append(payload)
                continue
            reply = _public_tool_reply(content, used_tools)
            if not reply:
                raise RuntimeError("Чат не вернул ответ.")
            payload["_izo_tool_runs"] = tool_runs
            payload["_izo_tool_payloads"] = tool_payloads
            return reply, payload, model
        messages.append({**_assistant_message(payload), "role": "assistant"})
        for call in calls[:2]:
            name, arguments, call_id = _tool_call(call)
            if not _tool_allowed(req, name):
                result = {"ok": False, "error": "Этот инструмент не выбран для текущего запроса."}
                messages.append({"role": "tool", "tool_call_id": call_id, "content": json.dumps(result, ensure_ascii=False)})
                continue
            if name == "generate_image" and req.toolChoice == "generate_image":
                arguments = _forced_image_model_arguments(req, arguments)
            if name == "web_search" and req.toolChoice == "web_search":
                arguments = _forced_search_model_arguments(req, arguments)
            if name in used_tools:
                result, provider_payload = {"ok": False, "error": "Этот инструмент уже использован в текущем ответе."}, {}
            else:
                result, provider_payload = await _execute_tool(name, arguments, deps, config)
                used_tools.add(name)
            tool_runs.append({"name": name, **result})
            if provider_payload:
                tool_payloads.append(provider_payload)
            messages.append({"role": "tool", "tool_call_id": call_id, "content": json.dumps(result, ensure_ascii=False)})
        if payload:
            tool_payloads.append(payload)
    raise RuntimeError("Чат превысил допустимое число вызовов инструментов.")


async def route_phone_chat(
    req: PhoneChatRequest,
    deps: PhoneChatDependencies,
) -> tuple[str, dict[str, Any], str, str, str, int, str]:
    config = _chat_config(deps)
    public_model_id, provider, technical_model, token_cost, token_kind = _resolve_phone_chat_model(req, config)
    selected_config = {
        **config,
        "localModel": technical_model if provider == "local" else config.get("localModel"),
        "apiModel": technical_model if provider == "api" else config.get("apiModel"),
    }
    async with _phone_chat_semaphore:
        if provider == "local":
            reply, payload, model = await phone_chat_ollama(req, deps, selected_config)
        else:
            reply, payload, model = await phone_chat_openrouter(req, deps, selected_config)
    return reply, payload, provider, model, public_model_id, token_cost, token_kind


def create_phone_chat_router(deps: PhoneChatDependencies) -> APIRouter:
    router = APIRouter()

    def replay_or_raise(outcome: dict[str, Any]) -> dict[str, Any] | None:
        state = str(outcome.get("state") or "")
        if state == "succeeded":
            response = outcome.get("response")
            if isinstance(response, dict):
                return response
            raise HTTPException(503, "Не удалось восстановить сохранённый ответ чата.")
        if state in {"conflict", "processing", "failed"}:
            headers = None
            if state == "processing":
                headers = {"Retry-After": str(max(1, int(outcome.get("retry_after") or 1)))}
            raise HTTPException(
                int(outcome.get("status") or 503),
                str(outcome.get("detail") or "Чат временно недоступен."),
                headers=headers,
            )
        return None

    def trusted_user_id(request: Request) -> tuple[dict[str, Any], str]:
        trusted = deps.require_trusted_user(request)
        user_id = str(trusted.get("legacy_user_id") or "")
        if not user_id:
            raise HTTPException(401, "Требуется вход в аккаунт.")
        return trusted, user_id

    def trusted_user_plan(user_id: str) -> str:
        if deps.connect_db is None:
            return "mini"
        with deps.connect_db() as conn:
            row = conn.execute("SELECT plan,role FROM users WHERE id = ?", (user_id,)).fetchone()
        if row and str(row["role"] or "").lower() == "admin":
            return "admin"
        return str(row["plan"] or "mini").strip().lower() if row else "mini"

    @router.get("/api/phone/chat/threads")
    async def phone_chat_threads(request: Request) -> dict[str, Any]:
        _trusted, user_id = trusted_user_id(request)
        if deps.connect_db is None:
            return {"ok": True, "threads": []}
        with deps.connect_db() as conn:
            return {"ok": True, "threads": phone_chat_history.list_threads(conn, user_id)}

    @router.post("/api/phone/chat/threads")
    async def phone_chat_thread_create(req: PhoneChatThreadCreate, request: Request) -> dict[str, Any]:
        _trusted, user_id = trusted_user_id(request)
        if deps.connect_db is None:
            raise HTTPException(503, "История чатов временно недоступна.")
        with deps.connect_db() as conn:
            thread = phone_chat_history.create_thread(
                conn, user_id, title=req.title, chat_model_id=req.chatModelId,
                image_model_id=req.imageModelId, video_model_id=req.videoModelId,
                context_chars=req.contextChars,
            )
            conn.commit()
        return {"ok": True, "thread": thread}

    @router.patch("/api/phone/chat/threads/{thread_id}")
    async def phone_chat_thread_update(thread_id: str, req: PhoneChatThreadUpdate, request: Request) -> dict[str, Any]:
        _trusted, user_id = trusted_user_id(request)
        if deps.connect_db is None:
            raise HTTPException(503, "История чатов временно недоступна.")
        with deps.connect_db() as conn:
            thread = phone_chat_history.update_thread(conn, user_id, thread_id, req.model_dump(exclude_none=True))
            conn.commit()
        if thread is None:
            raise HTTPException(404, "Чат не найден.")
        return {"ok": True, "thread": thread}

    @router.delete("/api/phone/chat/threads/{thread_id}")
    async def phone_chat_thread_delete(thread_id: str, request: Request) -> dict[str, Any]:
        _trusted, user_id = trusted_user_id(request)
        if deps.connect_db is None:
            raise HTTPException(503, "История чатов временно недоступна.")
        with deps.connect_db() as conn:
            deleted = phone_chat_history.delete_thread(conn, user_id, thread_id)
            conn.commit()
        if not deleted:
            raise HTTPException(404, "Чат не найден.")
        return {"ok": True}

    @router.get("/api/phone/chat/threads/{thread_id}/messages")
    async def phone_chat_thread_messages(thread_id: str, request: Request) -> dict[str, Any]:
        _trusted, user_id = trusted_user_id(request)
        if deps.connect_db is None:
            return {"ok": True, "messages": []}
        with deps.connect_db() as conn:
            thread = phone_chat_history.get_thread(conn, user_id, thread_id)
            messages = phone_chat_history.list_messages(conn, user_id, thread_id) if thread else []
        if thread is None:
            raise HTTPException(404, "Чат не найден.")
        return {"ok": True, "thread": thread, "messages": messages}

    @router.patch("/api/phone/chat/threads/{thread_id}/messages/{message_id}/tools")
    async def phone_chat_message_tools(thread_id: str, message_id: str, req: PhoneChatToolsUpdate, request: Request) -> dict[str, Any]:
        _trusted, user_id = trusted_user_id(request)
        if deps.connect_db is None:
            raise HTTPException(503, "История чатов временно недоступна.")
        with deps.connect_db() as conn:
            updated = phone_chat_history.update_message_tools(conn, user_id, thread_id, message_id, req.tools)
            conn.commit()
        if not updated:
            raise HTTPException(404, "Сообщение не найдено.")
        return {"ok": True}

    @router.get("/api/phone/chat/models")
    async def phone_chat_models(request: Request) -> dict[str, Any]:
        _trusted, user_id = trusted_user_id(request)
        plan = trusted_user_plan(user_id)
        config = _chat_config(deps)
        models: list[dict[str, Any]] = []
        if config.get("enabled") is not False and config.get("localEnabled") is not False:
            models.append({
                "id": "local:izo-chat",
                "name": str(config.get("localLabel") or "ИЗО Чат"),
                "provider": "local",
                "tokenCost": 0,
                "tokenKind": "free",
                "description": "Базовая локальная модель · сообщения бесплатны",
                "contextChars": int(config.get("contextChars") or 60000),
                "runtimeContextTokens": int(config.get("localNumCtx") or 16384),
            })
        published_api = {
            str(value) for value in config.get("publishedApiModels", config.get("enabledApiModels", []))
            if str(value).strip()
        }
        enabled_api = {
            str(value) for value in config.get("enabledApiModels", [])
            if str(value) in published_api
        }
        tier_access = config.get("apiTierAccess") if isinstance(config.get("apiTierAccess"), dict) else {}
        allowed_api = set(enabled_api) if plan == "admin" else {str(value) for value in tier_access.get(plan, []) if str(value).strip()}
        costs = config.get("apiTokenCosts") if isinstance(config.get("apiTokenCosts"), dict) else {}
        try:
            catalog = await deps.openrouter_text_models()
        except Exception:
            catalog = []
        by_id = {str(item.get("id")): item for item in catalog if isinstance(item, dict) and item.get("id")}
        exchange = deps.usd_rub_snapshot() if deps.usd_rub_snapshot is not None else {}
        economy = deps.openrouter_economy() if deps.openrouter_economy is not None else {}
        usd_rub = float(exchange.get("rate") or 0)
        token_rub = max(0.01, float(economy.get("tokenRub") or 5))

        for model_id in config.get("enabledApiModels", []):
            model_id = str(model_id)
            if model_id not in published_api or model_id not in enabled_api:
                continue
            item = by_id.get(model_id, {})
            price_confirmed = model_id in by_id
            pricing = chat_billing.build_text_model_economics(
                input_per_million_usd=float(item.get("inputPerMillionUsd") or 0),
                output_per_million_usd=float(item.get("outputPerMillionUsd") or 0),
                exchange_rate=usd_rub if usd_rub > 0 else None,
                funding_reserve_percent=float(economy.get("usdFeePercent") or 0),
                minimum_margin_percent=float(economy.get("minMarginPercent") or 0),
                token_rub=token_rub,
                observed_at=str(exchange.get("fetchedAt") or exchange.get("sourceDate") or "") or None,
            )
            if not price_confirmed:
                pricing = {**pricing, "priceStatus": "missing_catalog", "inputPerMillion": None, "outputPerMillion": None, "millionRussianChars": None, "sample1000Input500Output": None}
            input_quote = pricing.get("inputPerMillion") or {}
            output_quote = pricing.get("outputPerMillion") or {}
            input_per_million = float(input_quote.get("reservedTokens") or 0)
            output_per_million = float(output_quote.get("reservedTokens") or 0)
            models.append({
                "id": model_id,
                "name": str(item.get("name") or model_id.rsplit("/", 1)[-1]),
                "provider": "api",
                "tokenCost": float(costs.get(model_id) or 0.1),
                "tokenKind": "main",
                "description": "Оплата по фактическому объёму ответа",
                "usageBased": bool(config.get("usageBillingEnabled", True)),
                "priceGuidance": "Цена зависит от истории, изображений и длины ответа; максимум резервируется заранее, остаток возвращается.",
                "available": model_id in allowed_api and price_confirmed,
                "unavailableReason": "Нет проверенной цены модели" if not price_confirmed else "Недоступна на вашем тарифе" if model_id not in allowed_api else "",
                "contextLength": int(item.get("contextLength") or 0),
                "inputPerMillionUsd": float(item.get("inputPerMillionUsd") or 0),
                "outputPerMillionUsd": float(item.get("outputPerMillionUsd") or 0),
                "inputPerMillionProductTokens": input_per_million,
                "outputPerMillionProductTokens": output_per_million,
                "retailPerMillionProductTokens": math.ceil(max(input_per_million, output_per_million) * 100) / 100,
                "economics": pricing,
                "contextChars": min(int(config.get("contextChars") or 60000), max(4000, int(item.get("contextLength") or 15000) * 4)),
            })
        default_model = str(config.get("defaultModel") or "local:izo-chat")
        available_ids = {str(item["id"]) for item in models if item.get("available", True)}
        if default_model not in available_ids:
            default_model = "local:izo-chat" if "local:izo-chat" in available_ids else next(iter(available_ids), "")
        return {"ok": True, "defaultModel": default_model, "plan": plan, "models": models}

    @router.post("/api/phone/chat")
    async def phone_chat(req: PhoneChatRequest, request: Request) -> dict[str, Any]:
        trusted, user_id = trusted_user_id(request)
        if req.messages[-1].role != "user":
            raise HTTPException(400, "Последним в чате должно быть сообщение пользователя.")
        try:
            _phone_chat_image_payloads(req.images)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        lifecycle = deps.request_lifecycle
        if lifecycle is None:
            raise HTTPException(503, "Защита повторных запросов чата не настроена.")
        fingerprint = chat_request_lifecycle.phone_chat_request_fingerprint(
            messages=req.messages,
            route=req.route,
            tool_choice=req.toolChoice,
            model_id=req.modelId,
            images=req.images,
            thread_id=req.threadId,
        )
        replay = replay_or_raise(lifecycle.inspect(
            user_id=user_id,
            request_id=req.requestId,
            fingerprint=fingerprint,
        ))
        if replay is not None:
            return replay
        routed_req = req
        if req.threadId and deps.connect_db is not None:
            with deps.connect_db() as conn:
                thread = phone_chat_history.get_thread(conn, user_id, req.threadId)
                if thread is None:
                    raise HTTPException(404, "Чат не найден.")
                history = phone_chat_history.bounded_history(conn, user_id, req.threadId, max(int(thread["contextChars"]), int(_chat_config(deps).get("contextChars") or 480000)))
            messages = [*map(lambda item: PhoneChatTurn.model_construct(**item), history), req.messages[-1]][-100:]
            routed_req = req.model_copy(update={"messages": messages, "modelId": req.modelId or thread["chatModelId"]})
        config = _chat_config(deps)
        plan = trusted_user_plan(user_id)
        try:
            _public_id, selected_provider, selected_model, selected_cost, selected_kind = _resolve_phone_chat_model(routed_req, config, plan)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        reservation_quote: dict[str, Any] | None = None
        if selected_provider == "api" and config.get("usageBillingEnabled", True):
            try:
                catalog = await deps.openrouter_text_models()
            except Exception as exc:
                raise HTTPException(503, "Не удалось получить актуальную цену модели чата.") from exc
            catalog_model = next((item for item in catalog if isinstance(item, dict) and str(item.get("id") or "") == selected_model), None)
            exchange = deps.usd_rub_snapshot() if deps.usd_rub_snapshot is not None else {}
            economy = deps.openrouter_economy() if deps.openrouter_economy is not None else {}
            if catalog_model is None or not isinstance(exchange.get("rate"), (int, float)):
                raise HTTPException(503, "Для этой модели пока нет проверенной цены или курса валют.")
            try:
                reservation_quote = chat_billing.build_chat_reservation_quote(
                    messages=routed_req.messages,
                    image_count=len(routed_req.images),
                    input_per_million_usd=float(catalog_model.get("inputPerMillionUsd") or 0),
                    output_per_million_usd=float(catalog_model.get("outputPerMillionUsd") or 0),
                    exchange_rate=float(exchange["rate"]),
                    funding_reserve_percent=float(economy.get("usdFeePercent") or 0),
                    minimum_margin_percent=float(economy.get("minMarginPercent") or 0),
                    token_rub=float(economy.get("tokenRub") or 5),
                )
            except (TypeError, ValueError) as exc:
                raise HTTPException(503, "Для этой модели пока нет проверенной цены.") from exc
            selected_cost = float(reservation_quote["reservedTokens"])
        claim = lifecycle.begin(
            user_id=user_id,
            token_cost=selected_cost,
            request_id=req.requestId,
            fingerprint=fingerprint,
            provider=selected_provider,
            model=selected_model,
        )
        replay = replay_or_raise(claim)
        if replay is not None:
            return replay
        if claim.get("state") != "started" or not isinstance(claim.get("charge"), dict):
            raise HTTPException(503, "Не удалось безопасно начать запрос чата.")
        started = time.monotonic()
        try:
            routed = await asyncio.wait_for(
                route_phone_chat(routed_req, deps),
                timeout=1860 if selected_provider == "local" else 185,
            )
            if len(routed) == 4:  # Compatibility for older isolated route test doubles.
                reply, provider_payload, provider, model = routed
                public_model_id, token_cost, token_kind = _public_id, selected_cost, selected_kind
            else:
                reply, provider_payload, provider, model, public_model_id, token_cost, token_kind = routed
            usage = provider_payload.get("usage") if isinstance(provider_payload.get("usage"), dict) else {}
            tool_runs = provider_payload.pop("_izo_tool_runs", []) if isinstance(provider_payload, dict) else []
            tool_payloads = provider_payload.pop("_izo_tool_payloads", []) if isinstance(provider_payload, dict) else []
            cost = float(extract_openrouter_generation_cost(provider_payload) or 0) if provider == "api" else 0.0
            cost += sum(
                float(extract_openrouter_generation_cost(item) or 0)
                for item in tool_payloads
                if isinstance(item, dict)
            )
            completion = lifecycle.complete(
                user_id=user_id,
                request_id=req.requestId,
                fingerprint=fingerprint,
                reply=reply,
                provider=provider,
                public_model_id=public_model_id,
                usage=usage,
                cost_usd=cost,
                token_cost=token_cost,
                token_kind=token_kind,
                reservation_quote=reservation_quote,
                tool_runs=tool_runs,
                thread_id=req.threadId,
                user_content=req.messages[-1].content,
            )
            response = replay_or_raise(completion)
            if response is None:
                raise RuntimeError("PHONE_CHAT_COMPLETION_OUTCOME_INVALID")
            settlement = completion.get("settlement") if isinstance(completion.get("settlement"), dict) else None
        except Exception as exc:
            if isinstance(exc, ValueError):
                status, detail, error_code = 400, str(exc), "invalid_provider_result"
            elif isinstance(exc, asyncio.TimeoutError):
                status, detail, error_code = 504, "Чат отвечает слишком долго. Повторите запрос.", "timeout"
            elif isinstance(exc, HTTPException):
                status = int(exc.status_code)
                detail = str(exc.detail)
                error_code = "http_error"
            elif isinstance(exc, (httpx.HTTPError, RuntimeError)):
                status, detail, error_code = (
                    502,
                    "Чат временно недоступен. Повторите позже или обратитесь в поддержку.",
                    "provider_or_completion_error",
                )
            else:
                status, detail, error_code = (
                    502,
                    "Чат временно недоступен. Повторите позже или обратитесь в поддержку.",
                    "unexpected_chat_error",
                )
            try:
                failure = lifecycle.fail(
                    user_id=user_id,
                    request_id=req.requestId,
                    fingerprint=fingerprint,
                    status=status,
                    detail=detail,
                    error_code=error_code,
                )
            except Exception as refund_exc:
                raise HTTPException(
                    503,
                    "Не удалось подтвердить возврат токенов. Повторите запрос позже.",
                ) from refund_exc
            if failure.get("state") == "succeeded" and isinstance(failure.get("response"), dict):
                return failure["response"]
            raise HTTPException(
                int(failure.get("status") or status),
                str(failure.get("detail") or detail),
            ) from exc
        try:
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
                    "product_token_cost": response["chargedTokens"],
                    "product_token_kind": token_kind,
                    "provider_usage": usage,
                    "billing_quote": reservation_quote,
                    "billing_settlement": settlement,
                    "tools": [str(item.get("name") or "") for item in tool_runs if isinstance(item, dict)],
                },
            )
        except Exception:
            pass
        return response

    return router
