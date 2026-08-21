"""MAX update parsing and handling with injected application dependencies."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any


MaxApiCall = Callable[[str, str, dict[str, Any] | None, dict[str, Any] | None], Awaitable[dict[str, Any]]]


@dataclass(frozen=True)
class MaxUpdateRuntime:
    api_call: MaxApiCall
    login_token_from_payload: Callable[[str | None], str | None]
    approve_login: Callable[[str, dict[str, Any]], bool]
    schedule_avatar: Callable[[str], None]
    command_response: Callable[[str], dict[str, Any]]
    now_iso: Callable[[], str]
    set_diagnostic: Callable[[str, Any], None]
    log: Callable[[str], None]


def max_update_type(update: dict[str, Any]) -> str:
    for key in ("bot_started", "botStarted", "message_callback", "callback", "message_created", "message"):
        if isinstance(update.get(key), dict):
            return key
    value = update.get("update_type") or update.get("type")
    return str(value or "unknown")


def sanitized_payload_prefix(payload: str | None) -> str | None:
    if not isinstance(payload, str) or not payload:
        return None
    if payload.startswith("login_"):
        return "login_"
    if payload.startswith("approve:login_") or payload.startswith("approve:"):
        return "approve_"
    return payload[:16]


def _max_human_user(candidate: Any) -> dict[str, Any] | None:
    """Normalize a MAX user object while refusing bot identities.

    A ``message_callback`` contains the original bot-authored message as well
    as the human actor who pressed the button.  The message sender must never
    win identity resolution in that shape: it is the bot and would collapse
    every login onto the bot's own ``user_id``.
    """
    if not isinstance(candidate, dict) or candidate.get("is_bot") is True:
        return None
    provider_id = candidate.get("user_id") or candidate.get("id")
    if not provider_id:
        return None
    user = dict(candidate)
    user["id"] = provider_id
    return user


def max_user_from_message(message: dict[str, Any]) -> dict[str, Any] | None:
    sender = message.get("sender") or message.get("user") or {}
    user = _max_human_user(sender)
    if user:
        return user
    user_id = message.get("user_id")
    if user_id:
        return {"id": user_id}
    return None


def max_message_is_bot_authored(update: dict[str, Any], message: dict[str, Any]) -> bool:
    """Detect provider-marked bot messages even when a top-level id is present."""
    candidates = [message.get("sender"), message.get("user"), update.get("user")]
    return any(isinstance(candidate, dict) and candidate.get("is_bot") is True for candidate in candidates)


def enrich_max_user_profile(user: dict[str, Any], update: dict[str, Any] | None) -> dict[str, Any]:
    if not user.get("photo_url"):
        avatar = user.get("full_avatar_url") or user.get("avatar_url")
        if isinstance(avatar, str) and avatar.startswith("https://"):
            user["photo_url"] = avatar
    if not user.get("language_code") and isinstance(update, dict):
        locale = update.get("user_locale")
        if isinstance(locale, str) and locale.strip():
            user["language_code"] = locale.strip()
    return user


def max_user_from_update(update: dict[str, Any], message: dict[str, Any]) -> dict[str, Any] | None:
    # Event-level users are the actors.  Resolve them before the nested
    # message because callback.message.sender is normally the bot that sent
    # the confirmation button, not the human who clicked it.
    user: dict[str, Any] | None = None
    for container_key in ("callback", "message_callback", "bot_started", "botStarted"):
        container = update.get(container_key)
        if not isinstance(container, dict):
            continue
        for user_key in ("user", "sender", "from"):
            user = _max_human_user(container.get(user_key))
            if user:
                break
        if user is None:
            provider_id = container.get("user_id") or container.get("sender_id")
            if provider_id:
                user = {"id": provider_id}
        if user is not None:
            break
    if not user:
        user = _max_human_user(update.get("user"))
        if not user and update.get("user_id"):
            user = {"id": update.get("user_id")}
    if not user:
        user = max_user_from_message(message)
    if not user:
        return None
    return enrich_max_user_profile(user, update)


def _bot_login_payload_from_text(text: str | None) -> str | None:
    if not isinstance(text, str):
        return None
    parts = text.strip().split(maxsplit=1)
    if not parts:
        return None
    payload = parts[1].strip() if parts[0].lower() == "/start" and len(parts) > 1 else parts[0].strip()
    return payload if payload.startswith("login_") else None


def max_login_payload_from_update(update: dict[str, Any], text: str | None) -> str | None:
    for key in ("payload", "start_payload", "startPayload"):
        value = update.get(key)
        if isinstance(value, str) and value.startswith("login_"):
            return value
    bot_started = update.get("bot_started") or update.get("botStarted") or {}
    if isinstance(bot_started, dict):
        for key in ("payload", "start_payload", "startPayload"):
            value = bot_started.get(key)
            if isinstance(value, str) and value.startswith("login_"):
                return value
    return _bot_login_payload_from_text(text)


def max_message_payload(answer: dict[str, Any]) -> dict[str, Any]:
    buttons = answer.get("buttons", [])
    payload: dict[str, Any] = {"text": answer["text"]}
    if buttons:
        row = []
        for button in buttons:
            if button.get("callback_data"):
                row.append({"type": "callback", "text": button["text"], "payload": button["callback_data"]})
            elif button.get("url"):
                row.append({"type": "link", "text": button["text"], "url": button["url"]})
        if row:
            payload["attachments"] = [{"type": "inline_keyboard", "payload": {"buttons": [row]}}]
    return payload


def extract_max_command(update: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    callback = update.get("callback") or update.get("message_callback") or {}
    message = (
        update.get("message")
        or update.get("message_created", {}).get("message")
        or update.get("bot_started", {}).get("message")
        or callback.get("message")
        or {}
    )
    body = message.get("body") or {}
    text = callback.get("payload") or callback.get("data") or message.get("text") or body.get("text") or ""
    return text, message


def max_recipient_params(message: dict[str, Any], update: dict[str, Any] | None = None) -> dict[str, Any]:
    recipient = message.get("recipient") or {}
    chat_id = message.get("chat_id") or recipient.get("chat_id")
    sender = message.get("sender") if isinstance(message.get("sender"), dict) else {}
    user_id = message.get("user_id") or recipient.get("user_id") or sender.get("user_id") or sender.get("id")
    if not chat_id and not user_id and isinstance(update, dict):
        chat_id = update.get("chat_id")
        top_user = update.get("user") if isinstance(update.get("user"), dict) else {}
        user_id = update.get("user_id") or top_user.get("user_id") or top_user.get("id")
    if chat_id:
        return {"chat_id": chat_id}
    if user_id:
        return {"user_id": user_id}
    return {}


async def handle_max_update_with_runtime(
    update: dict[str, Any], send_replies: bool, runtime: MaxUpdateRuntime,
) -> dict[str, Any] | None:
    text, message = extract_max_command(update)
    update_type = max_update_type(update)
    user_present = bool(max_user_from_update(update, message))
    payload_prefix = sanitized_payload_prefix(text if isinstance(text, str) else None)
    if update_type in {"bot_started", "botStarted"} or payload_prefix in {"login_", "approve_"}:
        runtime.log(f"MAX_UPDATE type={update_type} hasPayload={bool(payload_prefix)} payloadPrefix={payload_prefix or 'none'} userIdPresent={user_present}")
    if isinstance(text, str) and (text.startswith("approve:") or text.startswith("/approve ")):
        runtime.set_diagnostic("lastCallbackAt", runtime.now_iso())
        runtime.log(f"MAX approve callback received payloadPrefix={payload_prefix or 'none'} userIdPresent={user_present}")
        token_source = text.replace("approve:", "", 1) if text.startswith("approve:") else text.split(maxsplit=1)[1]
        token = runtime.login_token_from_payload(token_source)
        user = max_user_from_update(update, message)
        approved = bool(token and user and runtime.approve_login(token, user))
        runtime.log(f"MAX challenge status={'approved' if approved else 'rejected'}")
        if approved and user:
            runtime.schedule_avatar(str(user.get("id") or ""))
        params = max_recipient_params(message, update)
        if send_replies and params:
            await runtime.api_call(
                "POST",
                "/messages",
                {
                    "text": (
                        "Вход подтверждён. Вернитесь в ИЗО АСА — окно входа закроется автоматически."
                        if approved
                        else "Запрос входа устарел или уже использован. Вернитесь в ИЗО АСА и начните вход через MAX заново."
                    )
                },
                params,
            )
        return {"update": update, "recipient": params, "botLogin": "approved" if approved else "rejected"}
    login_payload = max_login_payload_from_update(update, text)
    if login_payload:
        runtime.set_diagnostic("lastBotStartedAt", runtime.now_iso())
        runtime.log(f"MAX payload login_ received userIdPresent={user_present}")
        answer = runtime.command_response(login_payload)
        params = max_recipient_params(message, update)
        if send_replies and params:
            await runtime.api_call("POST", "/messages", max_message_payload(answer), params)
            runtime.log("MAX confirmation button sent")
        return {"update": update, "recipient": params, "answer": answer}
    if isinstance(text, str) and text.strip() and user_present and not max_message_is_bot_authored(update, message):
        answer = runtime.command_response(text)
        params = max_recipient_params(message, update)
        if send_replies and params:
            await runtime.api_call("POST", "/messages", max_message_payload(answer), params)
        return {"update": update, "recipient": params, "answer": answer}
    return None


async def handle_max_updates_with_runtime(
    updates: list[dict[str, Any]], send_replies: bool, runtime: MaxUpdateRuntime,
) -> list[dict[str, Any]]:
    handled = []
    for update in updates:
        result = await handle_max_update_with_runtime(update, send_replies, runtime)
        if result:
            handled.append(result)
    return handled
