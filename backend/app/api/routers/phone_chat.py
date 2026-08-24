"""Authenticated phone-chat route and provider routing."""

from __future__ import annotations

import asyncio
import json
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
    "Пиши компактно: обычно 2–5 коротких абзацев или пунктов. Не повторяй вопрос пользователя. "
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
    messages: list[PhoneChatTurn] = Field(min_length=1, max_length=20)
    route: Literal["auto", "local", "api"] = "auto"
    modelId: str | None = Field(default=None, max_length=200)
    requestId: str = Field(default_factory=lambda: uuid.uuid4().hex, min_length=8, max_length=100, pattern=r"^[A-Za-z0-9._:-]+$")
    images: list[str] = Field(default_factory=list, max_length=4)


@dataclass(frozen=True)
class PhoneChatDependencies:
    require_trusted_user: Callable[[Request], dict[str, Any]]
    assistant_models_config: Callable[[], dict[str, Any]]
    openrouter_headers: Callable[[], dict[str, str]]
    record_openrouter_availability: Callable[[int], None]
    record_event: Callable[..., None]
    openrouter_text_models: Callable[[], Any]
    charge_tokens: Callable[..., dict[str, Any]]
    refund_tokens: Callable[..., bool]


def _chat_config(deps: PhoneChatDependencies) -> dict[str, Any]:
    config = deps.assistant_models_config()
    return config.get("chat") if isinstance(config.get("chat"), dict) else config["improve"]


def _resolve_phone_chat_model(req: PhoneChatRequest, config: dict[str, Any]) -> tuple[str, str, str, int, str]:
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
        return selected, "local", str(config.get("localModel") or "gemma4:12b"), int(config.get("localTokenCost") or 1), "daily"
    if config.get("enabled") is False or selected not in enabled_api:
        raise ValueError("Эта модель чата сейчас недоступна.")
    costs = config.get("apiTokenCosts") if isinstance(config.get("apiTokenCosts"), dict) else {}
    return selected, "api", selected, int(costs.get(selected) or 1), "main"


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


def _system_prompt() -> str:
    return PHONE_CHAT_SYSTEM_PROMPT.format(current_date=date.today().isoformat())


def _required_web_query(req: PhoneChatRequest) -> str:
    """Guarantee a search for explicit live-data requests if a small model misses tool selection."""

    latest = req.messages[-1].content.strip()
    normalized = re.sub(r"\s+", " ", latest.lower())
    explicit_search = re.search(r"\b(найди|поищи|посмотри|проверь)\b.{0,80}\b(интернет|сеть|онлайн|сайт)", normalized)
    live_weather = re.search(r"\b(погода|температура|прогноз)\b", normalized) and re.search(
        r"\b(сейчас|сегодня|завтра|текущ|какая|какой|москв|город|на улице)\w*\b", normalized
    )
    return latest[:500] if explicit_search or live_weather else ""


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


async def _prime_required_web_search(
    req: PhoneChatRequest,
    messages: list[dict[str, Any]],
    deps: PhoneChatDependencies,
    config: dict[str, Any],
    *,
    openrouter_style: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], set[str]]:
    query = _required_web_query(req)
    if not query:
        return [], [], set()
    call_id = f"call_{uuid.uuid4().hex[:12]}"
    result, provider_payload = await _execute_tool("web_search", {"query": query}, deps, config)
    arguments: Any = json.dumps({"query": query}, ensure_ascii=False) if openrouter_style else {"query": query}
    messages.append({
        "role": "assistant",
        "content": "",
        "tool_calls": [{"id": call_id, "type": "function", "function": {"name": "web_search", "arguments": arguments}}],
    })
    tool_message = {"role": "tool", "content": json.dumps(result, ensure_ascii=False)}
    tool_message["tool_call_id" if openrouter_style else "tool_name"] = call_id if openrouter_style else "web_search"
    messages.append(tool_message)
    return [{"name": "web_search", **result}], [provider_payload] if provider_payload else [], {"web_search"}


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
    timeout = max(10, min(180, int(config.get("localTimeoutSeconds") or 45)))
    tool_runs, tool_payloads, used_tools = await _prime_required_web_search(
        req, messages, deps, config, openrouter_style=False,
    )
    payload: dict[str, Any] = {}
    for _round in range(3):
        body = {
            "model": model,
            "stream": False,
            "think": False,
            "keep_alive": int(keep_alive) if keep_alive.lstrip("+-").isdigit() else keep_alive,
            "messages": messages,
            "tools": PHONE_CHAT_TOOLS,
            "options": {"temperature": 0.35, "num_predict": 1000, "num_ctx": 16384},
        }
        content, raw_payload = await request_ollama_chat_message(body=body, timeout_seconds=timeout)
        payload = raw_payload if isinstance(raw_payload, dict) else {}
        calls = _tool_calls(payload)
        if not calls:
            reply = _public_tool_reply(content, used_tools)
            if not reply:
                raise RuntimeError("Чат не вернул ответ.")
            payload["_izo_tool_runs"] = tool_runs
            payload["_izo_tool_payloads"] = tool_payloads
            return reply[:8000], payload, model
        messages.append({**_assistant_message(payload), "role": "assistant"})
        for call in calls[:2]:
            name, arguments, _call_id = _tool_call(call)
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
    tool_runs, tool_payloads, used_tools = await _prime_required_web_search(
        req, messages, deps, config, openrouter_style=True,
    )
    payload: dict[str, Any] = {}
    for _round in range(3):
        body = {"model": model, "messages": messages, "tools": PHONE_CHAT_TOOLS, "temperature": 0.35, "max_tokens": 1000}
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
            reply = _public_tool_reply(_openrouter_text_content(payload), used_tools)
            if not reply:
                raise RuntimeError("Чат не вернул ответ.")
            payload["_izo_tool_runs"] = tool_runs
            payload["_izo_tool_payloads"] = tool_payloads
            return reply[:8000], payload, model
        messages.append({**_assistant_message(payload), "role": "assistant"})
        for call in calls[:2]:
            name, arguments, call_id = _tool_call(call)
            if name in used_tools:
                result, provider_payload = {"ok": False, "error": "Этот инструмент уже использован в текущем ответе."}, {}
            else:
                result, provider_payload = await _execute_tool(name, arguments, deps, config)
                used_tools.add(name)
            tool_runs.append({"name": name, **result})
            if provider_payload:
                tool_payloads.append(provider_payload)
            messages.append({"role": "tool", "tool_call_id": call_id, "content": json.dumps(result, ensure_ascii=False)})
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

    @router.get("/api/phone/chat/models")
    async def phone_chat_models(request: Request) -> dict[str, Any]:
        deps.require_trusted_user(request)
        config = _chat_config(deps)
        models: list[dict[str, Any]] = []
        if config.get("enabled") is not False and config.get("localEnabled") is not False:
            models.append({
                "id": "local:izo-chat",
                "name": str(config.get("localLabel") or "ИЗО Чат"),
                "provider": "local",
                "tokenCost": int(config.get("localTokenCost") or 1),
                "tokenKind": "daily",
                "description": "Быстрая локальная модель ИЗО АСА",
            })
        enabled_api = {str(value) for value in config.get("enabledApiModels", [])}
        costs = config.get("apiTokenCosts") if isinstance(config.get("apiTokenCosts"), dict) else {}
        try:
            catalog = await deps.openrouter_text_models()
        except Exception:
            catalog = []
        by_id = {str(item.get("id")): item for item in catalog if isinstance(item, dict) and item.get("id")}
        for model_id in config.get("enabledApiModels", []):
            model_id = str(model_id)
            if model_id not in enabled_api:
                continue
            item = by_id.get(model_id, {})
            models.append({
                "id": model_id,
                "name": str(item.get("name") or model_id.rsplit("/", 1)[-1]),
                "provider": "api",
                "tokenCost": int(costs.get(model_id) or 1),
                "tokenKind": "main",
                "description": "Облачная текстовая модель",
                "contextLength": int(item.get("contextLength") or 0),
            })
        return {"ok": True, "defaultModel": str(config.get("defaultModel") or "local:izo-chat"), "models": models}

    @router.post("/api/phone/chat")
    async def phone_chat(req: PhoneChatRequest, request: Request) -> dict[str, Any]:
        trusted = deps.require_trusted_user(request)
        if req.messages[-1].role != "user":
            raise HTTPException(400, "Последним в чате должно быть сообщение пользователя.")
        try:
            _phone_chat_image_payloads(req.images)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        config = _chat_config(deps)
        try:
            _public_id, selected_provider, selected_model, selected_cost, selected_kind = _resolve_phone_chat_model(req, config)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        user_id = str(trusted.get("legacy_user_id") or "")
        if not user_id:
            raise HTTPException(401, "Требуется вход в аккаунт.")
        charge = deps.charge_tokens(
            user_id=user_id,
            token_cost=selected_cost,
            request_id=req.requestId,
            provider=selected_provider,
            model=selected_model,
        )
        started = time.monotonic()
        try:
            routed = await asyncio.wait_for(
                route_phone_chat(req, deps),
                timeout=185,
            )
            if len(routed) == 4:  # Compatibility for older isolated route test doubles.
                reply, provider_payload, provider, model = routed
                public_model_id, token_cost, token_kind = _public_id, selected_cost, selected_kind
            else:
                reply, provider_payload, provider, model, public_model_id, token_cost, token_kind = routed
        except ValueError as exc:
            deps.refund_tokens(user_id=user_id, ledger_id=charge["ledger_id"], reason=str(exc))
            raise HTTPException(400, str(exc)) from exc
        except asyncio.TimeoutError as exc:
            deps.refund_tokens(user_id=user_id, ledger_id=charge["ledger_id"], reason="timeout")
            raise HTTPException(504, "Чат отвечает слишком долго. Повторите запрос.") from exc
        except (httpx.HTTPError, RuntimeError) as exc:
            deps.refund_tokens(user_id=user_id, ledger_id=charge["ledger_id"], reason=str(exc))
            raise HTTPException(
                502,
                "Чат временно недоступен. Повторите позже или обратитесь в поддержку.",
            ) from exc
        usage = provider_payload.get("usage") if isinstance(provider_payload.get("usage"), dict) else {}
        tool_runs = provider_payload.pop("_izo_tool_runs", []) if isinstance(provider_payload, dict) else []
        tool_payloads = provider_payload.pop("_izo_tool_payloads", []) if isinstance(provider_payload, dict) else []
        cost = extract_openrouter_generation_cost(provider_payload) if provider == "api" else 0
        cost += sum(
            extract_openrouter_generation_cost(item)
            for item in tool_payloads
            if isinstance(item, dict)
        )
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
                "product_token_cost": token_cost,
                "product_token_kind": token_kind,
                "tools": [str(item.get("name") or "") for item in tool_runs if isinstance(item, dict)],
            },
        )
        return {
            "ok": True,
            "reply": reply,
            "model": public_model_id,
            "provider": provider,
            "usage": usage,
            "costUsd": cost,
            "modelId": public_model_id,
            "chargedTokens": token_cost,
            "tokenKind": token_kind,
            "tokenBalance": charge.get("new_balance"),
            "dailyTokensUsed": charge.get("daily_tokens_used_after"),
            "dailyTokensLimit": charge.get("daily_tokens_limit"),
            "tools": tool_runs,
        }

    return router
