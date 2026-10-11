"""IZO shell adapter exposing the portable text-chat core over HTTP."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ...chat_core.contracts import (
    ChatTurn,
    ProviderChatRequest,
    ProviderError,
    TextDelta,
    TextProvider,
    ToolCall,
)
from ...chat_core.providers.deepseek import DeepSeekProvider
from ...chat_core.user_secrets import SecretStore, UserProviderSecrets
from ...security.secret_store import DpapiSecretStore, assert_secret_store_outside_repository, default_secret_store_dir
from ...services import phone_chat_history


class ProviderKeyRequest(BaseModel):
    key: str = Field(min_length=1, max_length=1024)


class PortableTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=12000)


class PortableChatRequest(BaseModel):
    provider: str = Field(min_length=2, max_length=24, pattern=r"^[a-z0-9_]+$")
    model: str = Field(min_length=2, max_length=100)
    messages: list[PortableTurn] = Field(min_length=1, max_length=100)
    toolChoice: Literal["auto", "generate_image"] = "auto"
    threadId: str | None = Field(
        default=None,
        min_length=8,
        max_length=64,
        pattern=r"^[a-fA-F0-9]+$",
    )


@dataclass(frozen=True)
class PortableChatDependencies:
    require_trusted_user: Callable[[Request], dict[str, Any]]
    secret_store: SecretStore
    connect_db: Callable[[], Any] | None = None
    providers: dict[str, TextProvider] | None = None


def create_izo_portable_chat_dependencies(
    *,
    require_trusted_user: Callable[[Request], dict[str, Any]],
    connect_db: Callable[[], Any] | None = None,
) -> PortableChatDependencies:
    secret_root = default_secret_store_dir()
    repository_root = Path(__file__).resolve().parents[4]
    assert_secret_store_outside_repository(secret_root, repository_root)
    return PortableChatDependencies(
        require_trusted_user=require_trusted_user,
        secret_store=DpapiSecretStore(secret_root),
        connect_db=connect_db,
    )


def _provider_models(provider: TextProvider, configured: bool) -> list[dict[str, Any]]:
    return [
        {
            "id": f"{provider.provider_id}:{model.id}",
            "providerModelId": model.id,
            "name": model.name,
            "provider": provider.provider_id,
            "description": model.description,
            "available": configured,
            "unavailableReason": "" if configured else "Требуется DeepSeek API key.",
        }
        for model in provider.models()
    ]


def _event(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")


def _trusted_subjects(
    deps: PortableChatDependencies,
    request: Request,
) -> tuple[str, str]:
    trusted = deps.require_trusted_user(request)
    subject = str(
        trusted.get("internal_user_id")
        or trusted.get("legacy_user_id")
        or ""
    ).strip()
    history_user = str(trusted.get("legacy_user_id") or "").strip()
    if not subject:
        raise HTTPException(401, "Требуется вход в аккаунт.")
    return subject, history_user


def _validate_key(value: str) -> str:
    key = value.strip()
    if len(key) < 10 or any(char.isspace() for char in key):
        raise HTTPException(400, "Некорректный формат DeepSeek API key.")
    return key


def _tool_payload(call: ToolCall) -> dict[str, Any] | None:
    if call.name != "generate_image":
        return None
    prompt = str(call.arguments.get("prompt") or "").strip()[:2000]
    if not prompt:
        return {
            "name": "generate_image",
            "status": "error",
            "error": "DeepSeek не передал описание изображения.",
        }
    ratio = str(call.arguments.get("aspect_ratio") or "1:1")
    if ratio not in {"1:1", "9:16", "16:9", "3:2"}:
        ratio = "1:1"
    return {
        "name": "generate_image",
        "status": "requested",
        "prompt": prompt,
        "aspectRatio": ratio,
    }


def create_portable_chat_router(deps: PortableChatDependencies) -> APIRouter:
    router = APIRouter()
    providers = deps.providers or {"deepseek": DeepSeekProvider()}
    secrets = UserProviderSecrets(deps.secret_store)

    @router.get("/api/chat/providers/deepseek")
    async def deepseek_status(request: Request) -> dict[str, Any]:
        subject, _history_user = _trusted_subjects(deps, request)
        provider = providers["deepseek"]
        try:
            configured = secrets.configured(subject, provider.provider_id)
        except Exception as exc:
            raise HTTPException(503, "Хранилище API key недоступно.") from exc
        return {
            "ok": True,
            "provider": provider.provider_id,
            "configured": configured,
            "models": _provider_models(provider, configured),
        }

    @router.put("/api/chat/providers/deepseek/key")
    async def deepseek_save_key(req: ProviderKeyRequest, request: Request) -> dict[str, Any]:
        subject, _history_user = _trusted_subjects(deps, request)
        key = _validate_key(req.key)
        try:
            secrets.set(subject, "deepseek", key)
        except Exception as exc:
            raise HTTPException(503, "Не удалось безопасно сохранить API key.") from exc
        return {"ok": True, "configured": True}

    @router.delete("/api/chat/providers/deepseek/key")
    async def deepseek_delete_key(request: Request) -> dict[str, Any]:
        subject, _history_user = _trusted_subjects(deps, request)
        try:
            deleted = secrets.delete(subject, "deepseek")
        except Exception as exc:
            raise HTTPException(503, "Не удалось удалить API key.") from exc
        return {"ok": True, "configured": False, "deleted": deleted}

    @router.post("/api/chat/providers/deepseek/test")
    async def deepseek_test(request: Request) -> dict[str, Any]:
        subject, _history_user = _trusted_subjects(deps, request)
        provider = providers["deepseek"]
        try:
            key = secrets.get(subject, provider.provider_id)
        except Exception as exc:
            raise HTTPException(503, "Хранилище API key недоступно.") from exc
        if not key:
            raise HTTPException(400, "Сначала сохраните DeepSeek API key.")
        try:
            models = await provider.check(key)
        except ProviderError as exc:
            raise HTTPException(exc.status_code, exc.public_message) from exc
        return {
            "ok": True,
            "connected": True,
            "models": [model.id for model in models],
        }

    @router.post("/api/chat/stream")
    async def portable_chat_stream(
        req: PortableChatRequest,
        request: Request,
    ) -> StreamingResponse:
        subject, history_user = _trusted_subjects(deps, request)
        provider = providers.get(req.provider)
        if provider is None:
            raise HTTPException(400, "Неизвестный провайдер чата.")
        if req.messages[-1].role != "user":
            raise HTTPException(400, "Последним должно быть сообщение пользователя.")
        if sum(len(turn.content) for turn in req.messages) > 120000:
            raise HTTPException(400, "Контекст чата слишком большой.")
        try:
            key = secrets.get(subject, provider.provider_id)
        except Exception as exc:
            raise HTTPException(503, "Хранилище API key недоступно.") from exc
        if not key:
            raise HTTPException(400, "DeepSeek API key не настроен.")

        if req.threadId:
            if deps.connect_db is None or not history_user:
                raise HTTPException(503, "История чата недоступна.")
            with deps.connect_db() as conn:
                if phone_chat_history.get_thread(
                    conn,
                    history_user,
                    req.threadId,
                ) is None:
                    raise HTTPException(404, "Чат не найден.")

        provider_request = ProviderChatRequest(
            model=req.model,
            messages=tuple(
                ChatTurn(role=turn.role, content=turn.content)
                for turn in req.messages
            ),
            tool_choice=req.toolChoice,
        )

        async def generate():
            reply_parts: list[str] = []
            tools: list[dict[str, Any]] = []
            try:
                yield _event({"type": "state", "state": "streaming"})
                async for item in provider.stream(key, provider_request):
                    if isinstance(item, TextDelta):
                        reply_parts.append(item.text)
                        yield _event({"type": "delta", "text": item.text})
                    elif isinstance(item, ToolCall):
                        tool = _tool_payload(item)
                        if tool is not None:
                            tools.append(tool)
                            yield _event({"type": "tool", "tool": tool})

                message_id: str | None = None
                if req.threadId and deps.connect_db is not None and history_user:
                    with deps.connect_db() as conn:
                        saved = phone_chat_history.add_exchange(
                            conn,
                            history_user,
                            req.threadId,
                            user_content=req.messages[-1].content,
                            assistant_content="".join(reply_parts),
                            provider=provider.provider_id,
                            model=req.model,
                            tools=tools,
                            charged_tokens=0.0,
                            token_kind="",
                        )
                        conn.commit()
                        message_id = saved["assistantMessageId"]
                yield _event(
                    {
                        "type": "done",
                        "provider": provider.provider_id,
                        "model": req.model,
                        "messageId": message_id,
                    }
                )
            except asyncio.CancelledError:
                raise
            except ProviderError as exc:
                yield _event(
                    {
                        "type": "error",
                        "code": exc.code,
                        "message": exc.public_message,
                        "status": exc.status_code,
                    }
                )
            except Exception:
                yield _event(
                    {
                        "type": "error",
                        "code": "internal",
                        "message": "Чат временно недоступен.",
                        "status": 503,
                    }
                )

        return StreamingResponse(
            generate(),
            media_type="application/x-ndjson",
            headers={
                "Cache-Control": "no-store",
                "X-Accel-Buffering": "no",
            },
        )

    return router
