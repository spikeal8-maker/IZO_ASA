"""Unit contracts for the injected Telegram update service."""

from __future__ import annotations

import asyncio

import pytest

from app.services.telegram_updates import (
    TelegramUpdateRuntime,
    handle_telegram_update_with_runtime,
    handle_telegram_updates_with_runtime,
    telegram_answer_payload,
    telegram_message_from_update,
    telegram_user_from_update,
)


def make_runtime(
    *,
    api_call,
    approve_login=lambda _token, _user: False,
    schedule_avatar=lambda _provider_user_id: None,
    command_response=lambda text: {"text": text, "buttons": []},
    report_callback_error=lambda _exc: None,
) -> TelegramUpdateRuntime:
    return TelegramUpdateRuntime(
        api_call=api_call,
        login_token_from_payload=lambda payload: payload.removeprefix("login_") if payload else None,
        approve_login=approve_login,
        schedule_avatar=schedule_avatar,
        command_response=command_response,
        report_callback_error=report_callback_error,
    )


def test_user_and_message_parsing_preserve_message_shape() -> None:
    update = {
        "update_id": 3,
        "message": {
            "text": "/help",
            "chat": {"id": 77},
            "from": {"id": 8, "username": "message_user"},
        },
    }

    assert telegram_user_from_update(update) == {"id": 8, "username": "message_user"}
    assert telegram_message_from_update(update) == (
        "/help",
        update["message"],
        77,
        None,
    )


def test_user_and_message_parsing_prefer_callback_shape() -> None:
    callback_message = {"text": "fallback", "chat": {"id": 99}}
    update = {
        "message": {"text": "/ignored", "chat": {"id": 1}, "from": {"id": 1}},
        "callback_query": {
            "id": "callback-1",
            "data": "/settings",
            "from": {"id": 2, "username": "callback_user"},
            "message": callback_message,
        },
    }

    assert telegram_user_from_update(update) == {"id": 2, "username": "callback_user"}
    assert telegram_message_from_update(update) == (
        "/settings",
        callback_message,
        99,
        "callback-1",
    )


def test_answer_payload_preserves_callback_web_app_and_url_buttons() -> None:
    payload = telegram_answer_payload(
        77,
        {
            "text": "Choose",
            "buttons": [
                {"text": "Approve", "callback_data": "approve:login_x"},
                {"text": "App", "url": "https://app.example/path"},
                {"text": "Link", "url": "http://local.example/path"},
            ],
        },
    )

    assert payload == {
        "chat_id": 77,
        "text": "Choose",
        "reply_markup": {
            "inline_keyboard": [[
                {"text": "Approve", "callback_data": "approve:login_x"},
                {"text": "App", "web_app": {"url": "https://app.example/path"}},
                {"text": "Link", "url": "http://local.example/path"},
            ]]
        },
    }


def test_approve_update_preserves_dependency_and_api_call_order() -> None:
    events: list[tuple] = []

    async def api_call(method: str, payload: dict | None = None) -> dict:
        events.append(("api", method, payload))
        return {"ok": True}

    def approve(token: str, user: dict) -> bool:
        events.append(("approve", token, user))
        return True

    runtime = make_runtime(
        api_call=api_call,
        approve_login=approve,
        schedule_avatar=lambda provider_user_id: events.append(("avatar", provider_user_id)),
    )
    user = {"id": 777, "username": "tg_user"}
    result = asyncio.run(handle_telegram_update_with_runtime(
        {
            "update_id": 10,
            "callback_query": {
                "id": "cb-1",
                "data": "approve:login_nonce",
                "from": user,
                "message": {"chat": {"id": 777}},
            },
        },
        True,
        runtime,
    ))

    assert result == {"updateId": 10, "chatId": 777, "botLogin": "approved"}
    assert events == [
        ("approve", "nonce", user),
        ("avatar", "777"),
        (
            "api",
            "answerCallbackQuery",
            {"callback_query_id": "cb-1", "text": "Вход подтверждён"},
        ),
        (
            "api",
            "sendMessage",
            {"chat_id": 777, "text": "Вход подтверждён. Вернитесь в ИЗО АСА — окно входа закроется автоматически."},
        ),
    ]


def test_rejected_approve_keeps_replies_and_does_not_schedule_avatar() -> None:
    calls: list[tuple[str, dict | None]] = []
    avatars: list[str] = []

    async def api_call(method: str, payload: dict | None = None) -> dict:
        calls.append((method, payload))
        return {"ok": True}

    runtime = make_runtime(
        api_call=api_call,
        approve_login=lambda _token, _user: False,
        schedule_avatar=avatars.append,
    )
    result = asyncio.run(handle_telegram_update_with_runtime(
        {
            "update_id": 11,
            "callback_query": {
                "id": "cb-2",
                "data": "approve:login_expired",
                "from": {"id": 8},
                "message": {"chat": {"id": 8}},
            },
        },
        True,
        runtime,
    ))

    assert result == {"updateId": 11, "chatId": 8, "botLogin": "rejected"}
    assert avatars == []
    assert calls == [
        ("answerCallbackQuery", {"callback_query_id": "cb-2", "text": "Ссылка устарела"}),
        ("sendMessage", {"chat_id": 8, "text": "Запрос входа устарел или уже использован. Вернитесь в ИЗО АСА и начните вход через Telegram заново."}),
    ]


def test_command_callback_reports_only_callback_answer_error() -> None:
    calls: list[tuple[str, dict | None]] = []
    errors: list[Exception] = []
    answer = {
        "text": "Настройки приложения",
        "buttons": [{"text": "Open", "url": "https://app.example/#settings"}],
    }

    async def api_call(method: str, payload: dict | None = None) -> dict:
        calls.append((method, payload))
        if method == "answerCallbackQuery":
            raise RuntimeError("callback expired")
        return {"ok": True}

    runtime = make_runtime(
        api_call=api_call,
        command_response=lambda text: answer if text == "/settings" else {},
        report_callback_error=errors.append,
    )
    result = asyncio.run(handle_telegram_update_with_runtime(
        {
            "update_id": 12,
            "callback_query": {
                "id": "cb-3",
                "data": "/settings",
                "message": {"chat": {"id": 9}},
            },
        },
        True,
        runtime,
    ))

    assert result == {"updateId": 12, "chatId": 9, "answer": answer}
    assert [method for method, _payload in calls] == ["sendMessage", "answerCallbackQuery"]
    assert calls[0][1] == telegram_answer_payload(9, answer)
    assert len(errors) == 1
    assert str(errors[0]) == "callback expired"


def test_send_message_error_still_propagates() -> None:
    async def api_call(method: str, payload: dict | None = None) -> dict:
        raise RuntimeError(f"{method} failed")

    runtime = make_runtime(api_call=api_call)

    with pytest.raises(RuntimeError, match="sendMessage failed"):
        asyncio.run(handle_telegram_update_with_runtime(
            {"message": {"text": "/help", "chat": {"id": 5}}},
            True,
            runtime,
        ))


def test_batch_answers_plain_messages_and_preserves_order() -> None:
    async def api_call(method: str, payload: dict | None = None) -> dict:
        raise AssertionError(f"unexpected API call: {method} {payload}")

    runtime = make_runtime(
        api_call=api_call,
        command_response=lambda text: {"text": f"answer:{text}", "buttons": []},
    )
    result = asyncio.run(handle_telegram_updates_with_runtime(
        [
            {"update_id": 1, "message": {"text": "plain", "chat": {"id": 1}}},
            {"update_id": 2, "message": {"text": "/help", "chat": {"id": 2}}},
            {"update_id": 3, "message": {"text": "plain", "chat": {"id": 3}}},
            {"update_id": 4, "message": {"text": "/app", "chat": {"id": 4}}},
        ],
        False,
        runtime,
    ))

    assert result == [
        {"updateId": 1, "chatId": 1, "answer": {"text": "answer:plain", "buttons": []}},
        {"updateId": 2, "chatId": 2, "answer": {"text": "answer:/help", "buttons": []}},
        {"updateId": 3, "chatId": 3, "answer": {"text": "answer:plain", "buttons": []}},
        {"updateId": 4, "chatId": 4, "answer": {"text": "answer:/app", "buttons": []}},
    ]
