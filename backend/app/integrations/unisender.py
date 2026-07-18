"""UniSender adapter for transactional application email.

The API key is supplied by the caller and is never retained or logged here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping

import httpx

from .smtp import SmtpConfig, SmtpError, SmtpMessage


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


def build_unisender_config(raw: Any, environment: Mapping[str, str]) -> dict[str, Any]:
    current = raw if isinstance(raw, dict) else {}
    return {
        "provider": "unisender",
        "source": "admin" if current else "environment",
        "sender_name": str(current.get("sender_name") or environment.get("UNISENDER_SENDER_NAME", "ИЗО АСА")).strip(),
        "sender_email": str(current.get("sender_email") or environment.get("UNISENDER_SENDER_EMAIL", "")).strip(),
        "list_id": int(current.get("list_id") or environment.get("UNISENDER_LIST_ID", "0") or 0),
        "verified_at": str(current.get("verified_at") or "").strip() or None,
        "last_error": str(current.get("last_error") or "").strip() or None,
    }


def is_unisender_configured(api_key: str, config: Mapping[str, Any]) -> bool:
    return bool(api_key and config.get("sender_email") and int(config.get("list_id") or 0) > 0)


def is_unisender_ready(api_key: str, config: Mapping[str, Any]) -> bool:
    return is_unisender_configured(api_key, config) and (
        config.get("source") == "environment" or bool(config.get("verified_at"))
    )


def deliver_transactional_email(
    recipient: str,
    subject: str,
    html: str,
    unisender_api_key: str,
    unisender_config: Mapping[str, Any] | None,
    smtp_connection: SmtpConfig | None,
    smtp_settings: Mapping[str, Any],
    unisender_sender: Callable[..., str],
    smtp_sender: Callable[..., str],
) -> str:
    if not recipient:
        raise RuntimeError("Некорректный email получателя.")
    if unisender_config is not None:
        try:
            return unisender_sender(
                unisender_api_key,
                UniSenderMessage(
                    to=recipient,
                    subject=subject,
                    html=html,
                    sender_name=str(unisender_config.get("sender_name") or "ИЗО АСА"),
                    sender_email=str(unisender_config["sender_email"]),
                    list_id=int(unisender_config["list_id"]),
                ),
            )
        except UniSenderError as exc:
            raise RuntimeError(str(exc)) from exc
    if smtp_connection is not None:
        try:
            return smtp_sender(
                smtp_connection,
                SmtpMessage(
                    to=recipient,
                    subject=subject,
                    html=html,
                    sender_name=str(smtp_settings.get("sender_name") or "ИЗО АСА"),
                    sender_email=str(smtp_settings["sender_email"]),
                ),
            )
        except SmtpError as exc:
            raise RuntimeError(str(exc)) from exc
    raise RuntimeError("Почтовый провайдер не подключен.")


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
