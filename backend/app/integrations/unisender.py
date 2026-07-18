"""UniSender adapter for transactional application email.

The API key is supplied by the caller and is never retained or logged here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import httpx


UNISENDER_API_BASE = "https://api.unisender.com/ru/api"


class UniSenderError(RuntimeError):
    pass


@dataclass(frozen=True)
class UniSenderMessage:
    to: str
    subject: str
    html: str
    sender_name: str
    sender_email: str
    list_id: int
    reference_key: str | None = None


def _request(
    method: str,
    api_key: str,
    data: dict[str, Any] | None = None,
    *,
    timeout_seconds: float = 20.0,
    post: Callable[..., httpx.Response] = httpx.post,
) -> Any:
    if not api_key.strip():
        raise UniSenderError("API-ключ UniSender не указан.")
    try:
        response = post(
            f"{UNISENDER_API_BASE}/{method}",
            data={"format": "json", "api_key": api_key, **(data or {})},
            timeout=timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise UniSenderError("Не удалось подключиться к UniSender.") from exc
    if not isinstance(payload, dict):
        raise UniSenderError("UniSender вернул некорректный ответ.")
    if payload.get("error"):
        raise UniSenderError(str(payload.get("error")))
    return payload.get("result")


def get_unisender_lists(
    api_key: str,
    *,
    timeout_seconds: float = 20.0,
    post: Callable[..., httpx.Response] = httpx.post,
) -> list[dict[str, Any]]:
    result = _request("getLists", api_key, timeout_seconds=timeout_seconds, post=post)
    if not isinstance(result, list):
        raise UniSenderError("UniSender не вернул списки контактов.")
    lists: list[dict[str, Any]] = []
    for item in result:
        if not isinstance(item, dict):
            continue
        try:
            list_id = int(item.get("id"))
        except (TypeError, ValueError):
            continue
        lists.append({"id": list_id, "title": str(item.get("title") or f"Список {list_id}")})
    return lists


def create_unisender_list(
    api_key: str,
    title: str,
    *,
    timeout_seconds: float = 20.0,
    post: Callable[..., httpx.Response] = httpx.post,
) -> dict[str, Any]:
    clean_title = title.strip()
    if not clean_title:
        raise UniSenderError("Не указано название списка контактов.")
    result = _request(
        "createList",
        api_key,
        {"title": clean_title},
        timeout_seconds=timeout_seconds,
        post=post,
    )
    if not isinstance(result, dict) or not result.get("id"):
        raise UniSenderError("UniSender не вернул идентификатор списка.")
    return {"id": int(result["id"]), "title": clean_title}


def send_unisender_email(
    api_key: str,
    message: UniSenderMessage,
    *,
    timeout_seconds: float = 20.0,
    post: Callable[..., httpx.Response] = httpx.post,
) -> str:
    result = _request(
        "sendEmail",
        api_key,
        {
            "email": message.to,
            "sender_name": message.sender_name,
            "sender_email": message.sender_email,
            "subject": message.subject,
            "body": message.html,
            "list_id": str(message.list_id),
            "lang": "ru",
            "error_checking": "1",
            "track_read": "0",
            "track_links": "0",
            **({"ref_key": message.reference_key} if message.reference_key else {}),
        },
        timeout_seconds=timeout_seconds,
        post=post,
    )
    if isinstance(result, dict) and result.get("email_id"):
        return str(result["email_id"])
    if isinstance(result, list) and result:
        first = result[0] if isinstance(result[0], dict) else {}
        errors = first.get("errors") if isinstance(first, dict) else None
        if errors:
            messages = [
                str(item.get("message") or item.get("code"))
                for item in errors
                if isinstance(item, dict)
            ]
            raise UniSenderError("; ".join(messages) or "UniSender отклонил письмо.")
        if first.get("id"):
            return str(first["id"])
    raise UniSenderError("UniSender не вернул идентификатор письма.")
