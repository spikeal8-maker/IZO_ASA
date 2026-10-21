"""Direct OpenAI Responses API adapter; no OpenRouter proxy or implicit retries."""
from __future__ import annotations

from typing import Any

import httpx

OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
OPENAI_MODELS_URL = "https://api.openai.com/v1/models"
SUPPORTED_MODELS = ("gpt-4.1-mini", "gpt-4.1", "gpt-4o-mini")
DEFAULT_MODEL = SUPPORTED_MODELS[0]


class OpenAIProviderError(RuntimeError):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code


def normalize_openai_settings(value: Any) -> dict[str, Any]:
    saved = value if isinstance(value, dict) else {}
    model = str(saved.get("model") or DEFAULT_MODEL)
    return {
        "enabled": saved.get("enabled") is True,
        "model": model if model in SUPPORTED_MODELS else DEFAULT_MODEL,
    }


def _failure(code: int) -> OpenAIProviderError:
    if code == 401:
        return OpenAIProviderError(401, "invalid_key", "OpenAI отклонил API-ключ (401).")
    if code == 403:
        return OpenAIProviderError(403, "access_denied", "OpenAI запрещает доступ к выбранной модели (403).")
    if code == 404:
        return OpenAIProviderError(404, "model_unavailable", "Модель OpenAI недоступна для проекта (404).")
    if code == 429:
        return OpenAIProviderError(429, "rate_limit", "OpenAI сообщил о лимите запросов или бюджета (429).")
    return OpenAIProviderError(502, "provider_error", "OpenAI временно недоступен. Проверьте статус провайдера.")


def _options(timeout: float, transport: httpx.AsyncBaseTransport | None) -> dict[str, Any]:
    options: dict[str, Any] = {
        "timeout": httpx.Timeout(min(90, max(2, timeout))),
        "trust_env": False,
        "follow_redirects": False,
    }
    if transport is not None:
        options["transport"] = transport
    return options


async def check_openai_access(
    *, key: str, model: str, transport: httpx.AsyncBaseTransport | None = None
) -> dict[str, Any]:
    if model not in SUPPORTED_MODELS:
        raise ValueError("Модель не входит в разрешённый каталог.")
    if not key:
        raise OpenAIProviderError(503, "missing_key", "API-ключ OpenAI не сохранён.")
    try:
        async with httpx.AsyncClient(**_options(12, transport)) as client:
            response = await client.get(
                f"{OPENAI_MODELS_URL}/{model}",
                headers={"Authorization": f"Bearer {key}"},
            )
    except httpx.TimeoutException as exc:
        raise OpenAIProviderError(504, "timeout", "Проверка OpenAI превысила время ожидания.") from exc
    except httpx.HTTPError as exc:
        raise OpenAIProviderError(503, "network", "Безопасное соединение с OpenAI недоступно.") from exc
    if response.status_code != 200:
        raise _failure(response.status_code)
    return {"ok": True, "model": model, "verified": True}


async def request_openai_response(
    *, key: str, model: str, messages: list[dict[str, str]],
    instructions: str, timeout_seconds: float = 45,
    transport: httpx.AsyncBaseTransport | None = None,
) -> tuple[str, dict[str, Any]]:
    if model not in SUPPORTED_MODELS:
        raise ValueError("Недоступная модель OpenAI.")
    if not key:
        raise OpenAIProviderError(503, "missing_key", "Ключ OpenAI не настроен.")
    if not messages or any(message.get("role") not in {"user", "assistant"} for message in messages):
        raise ValueError("Недопустимый контекст чата.")
    body = {
        "model": model,
        "instructions": instructions,
        "input": [{"role": message["role"], "content": message["content"]} for message in messages],
        "max_output_tokens": 1000,
        "store": False,
    }
    try:
        async with httpx.AsyncClient(**_options(timeout_seconds, transport)) as client:
            response = await client.post(
                OPENAI_RESPONSES_URL,
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json=body,
            )
    except httpx.TimeoutException as exc:
        raise OpenAIProviderError(
            504, "ambiguous_timeout",
            "OpenAI не подтвердил результат. Возможен платный запрос; автоматический повтор отключён.",
        ) from exc
    except httpx.HTTPError as exc:
        raise OpenAIProviderError(
            503, "ambiguous_transport",
            "Соединение с OpenAI прервалось; результат запроса неизвестен. Автоповтора нет.",
        ) from exc
    if response.status_code != 200:
        raise _failure(response.status_code)
    try:
        payload = response.json()
        if payload.get("status") not in (None, "completed") or payload.get("error"):
            raise ValueError("incomplete response")
        texts = [
            str(part.get("text") or "")
            for item in payload.get("output", [])
            if isinstance(item, dict) and item.get("type") == "message"
            for part in item.get("content", [])
            if isinstance(part, dict) and part.get("type") == "output_text"
        ]
        result = "\n".join(text for text in texts if text).strip()
        if not result:
            raise ValueError("no text")
    except (ValueError, KeyError, TypeError) as exc:
        raise OpenAIProviderError(502, "invalid_response", "OpenAI не вернул корректный текстовый ответ.") from exc
    usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
    return result[:8000], {"usage": usage, "provider": "openai"}
