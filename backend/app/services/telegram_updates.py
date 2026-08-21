"""Telegram update parsing and handling with injected application dependencies."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any


TelegramApiCall = Callable[[str, dict[str, Any] | None], Awaitable[dict[str, Any]]]


@dataclass(frozen=True)
class TelegramUpdateRuntime:
    api_call: TelegramApiCall
    login_token_from_payload: Callable[[str | None], str | None]
    approve_login: Callable[[str, dict[str, Any]], bool]
    schedule_avatar: Callable[[str], None]
    command_response: Callable[[str], dict[str, Any]]
    report_callback_error: Callable[[Exception], None]


def telegram_user_from_update(update: dict[str, Any]) -> dict[str, Any] | None:
    callback = update.get("callback_query") or {}
    if isinstance(callback, dict) and isinstance(callback.get("from"), dict):
        return callback["from"]
    message = update.get("message") or {}
    if isinstance(message, dict) and isinstance(message.get("from"), dict):
        return message["from"]
    return None


def telegram_answer_payload(chat_id: Any, answer: dict[str, Any]) -> dict[str, Any]:
    buttons = []
    for button in answer.get("buttons", []):
        callback_data = button.get("callback_data")
        if callback_data:
            buttons.append({"text": button["text"], "callback_data": callback_data})
            continue
        url = button.get("url", "")
        if url.startswith("https://"):
            buttons.append({"text": button["text"], "web_app": {"url": url}})
        else:
            buttons.append({"text": button["text"], "url": url})
    payload: dict[str, Any] = {"chat_id": chat_id, "text": answer["text"]}
    if buttons:
        payload["reply_markup"] = {"inline_keyboard": [buttons]}
    return payload


def telegram_message_from_update(update: dict[str, Any]) -> tuple[str, dict[str, Any], Any, str | None]:
    message = update.get("message") or {}
    callback = update.get("callback_query") or {}
    callback_id = callback.get("id") if isinstance(callback, dict) else None
    if callback:
        message = callback.get("message") or {}
        text = callback.get("data") or message.get("text") or ""
    else:
        text = message.get("text") or ""
    chat = message.get("chat") or {}
    return text, message, chat.get("id"), callback_id


async def handle_telegram_update_with_runtime(
    update: dict[str, Any],
    send_replies: bool,
    runtime: TelegramUpdateRuntime,
) -> dict[str, Any] | None:
    update_id = update.get("update_id")
    text, _message, chat_id, callback_id = telegram_message_from_update(update)
    if isinstance(text, str) and text.startswith("approve:"):
        token = runtime.login_token_from_payload(text.replace("approve:", "", 1))
        user = telegram_user_from_update(update)
        approved = bool(token and user and runtime.approve_login(token, user))
        if approved and user:
            runtime.schedule_avatar(str(user.get("id") or ""))
        if send_replies and callback_id:
            await runtime.api_call(
                "answerCallbackQuery",
                {"callback_query_id": callback_id, "text": "Вход подтверждён" if approved else "Ссылка устарела"},
            )
        if send_replies and chat_id is not None:
            await runtime.api_call(
                "sendMessage",
                {
                    "chat_id": chat_id,
                    "text": (
                        "Вход подтверждён. Вернитесь в ИЗО АСА — окно входа закроется автоматически."
                        if approved
                        else "Запрос входа устарел или уже использован. Вернитесь в ИЗО АСА и начните вход через Telegram заново."
                    ),
                },
            )
        return {"updateId": update_id, "chatId": chat_id, "botLogin": "approved" if approved else "rejected"}
    if isinstance(text, str) and text.strip():
        answer = runtime.command_response(text)
        if send_replies and chat_id is not None:
            await runtime.api_call("sendMessage", telegram_answer_payload(chat_id, answer))
        if send_replies and callback_id:
            try:
                await runtime.api_call("answerCallbackQuery", {"callback_query_id": callback_id})
            except Exception as exc:
                runtime.report_callback_error(exc)
        return {"updateId": update_id, "chatId": chat_id, "answer": answer}
    return None


async def handle_telegram_updates_with_runtime(
    updates: list[dict[str, Any]],
    send_replies: bool,
    runtime: TelegramUpdateRuntime,
) -> list[dict[str, Any]]:
    handled = []
    for update in updates:
        result = await handle_telegram_update_with_runtime(update, send_replies, runtime)
        if result:
            handled.append(result)
    return handled
