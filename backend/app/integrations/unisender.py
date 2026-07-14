"""Small UniSender transactional email adapter.

The API key is supplied by the caller and is never retained or logged here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import httpx


UNISENDER_SEND_EMAIL_URL = "https://api.unisender.com/ru/api/sendEmail"


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


def _delivery_id(payload: Any) -> str:
    if not isinstance(payload, dict):
        raise UniSenderError("UniSender returned an invalid response.")
    if payload.get("error"):
        raise UniSenderError(str(payload.get("error")))
    result = payload.get("result")
    if isinstance(result, dict) and result.get("email_id"):
        return str(result["email_id"])
    if isinstance(result, list) and result:
        first = result[0] if isinstance(result[0], dict) else {}
        errors = first.get("errors") if isinstance(first, dict) else None
        if errors:
            messages = [str(item.get("message") or item.get("code")) for item in errors if isinstance(item, dict)]
            raise UniSenderError("; ".join(messages) or "UniSender rejected the message.")
        if first.get("id"):
            return str(first["id"])
    raise UniSenderError("UniSender did not return a message id.")


def send_unisender_email(
    api_key: str,
    message: UniSenderMessage,
    *,
    timeout_seconds: float = 20.0,
    post: Callable[..., httpx.Response] = httpx.post,
) -> str:
    if not api_key.strip():
        raise UniSenderError("UniSender API key is not configured.")
    response = post(
        UNISENDER_SEND_EMAIL_URL,
        data={
            "format": "json",
            "api_key": api_key,
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
        timeout=timeout_seconds,
    )
    try:
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise UniSenderError("UniSender request failed.") from exc
    return _delivery_id(payload)
