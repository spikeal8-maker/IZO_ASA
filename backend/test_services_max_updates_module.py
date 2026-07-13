"""Unit contracts for the injected MAX update service."""

from __future__ import annotations

import asyncio

from app.services.max_updates import (
    MaxUpdateRuntime,
    extract_max_command,
    handle_max_update_with_runtime,
    handle_max_updates_with_runtime,
    max_message_payload,
    max_recipient_params,
    max_user_from_update,
    sanitized_payload_prefix,
)


def make_runtime(*, api_call, approve=lambda _token, _user: False, command=lambda text: {"text": text, "buttons": []}, avatars=None, diagnostics=None, logs=None):
    avatars = [] if avatars is None else avatars
    diagnostics = {} if diagnostics is None else diagnostics
    logs = [] if logs is None else logs
    return MaxUpdateRuntime(
        api_call=api_call,
        login_token_from_payload=lambda payload: payload.removeprefix("login_") if payload and payload.startswith("login_") else None,
        approve_login=approve,
        schedule_avatar=avatars.append,
        command_response=command,
        now_iso=lambda: "2026-07-13T19:00:00+00:00",
        set_diagnostic=lambda key, value: diagnostics.__setitem__(key, value),
        log=logs.append,
    )


def test_real_shapes_extract_user_command_recipient_and_profile() -> None:
    update = {
        "user_locale": " ru ",
        "chat_id": "chat-1",
        "bot_started": {
            "payload": "login_nonce",
            "user": {"user_id": "user-1", "full_avatar_url": "https://cdn.test/avatar.png"},
            "message": {"body": {"text": "/fallback"}},
        },
    }
    text, message = extract_max_command(update)
    user = max_user_from_update(update, message)

    assert text == "/fallback"
    assert user == {
        "user_id": "user-1",
        "id": "user-1",
        "full_avatar_url": "https://cdn.test/avatar.png",
        "photo_url": "https://cdn.test/avatar.png",
        "language_code": "ru",
    }
    assert max_recipient_params(message, update) == {"chat_id": "chat-1"}


def test_recipient_and_button_mapping_preserve_priority_and_shape() -> None:
    assert max_recipient_params({"chat_id": "chat", "user_id": "user"}) == {"chat_id": "chat"}
    assert max_recipient_params({"sender": {"user_id": "user"}}) == {"user_id": "user"}
    assert max_message_payload({
        "text": "choose",
        "buttons": [
            {"text": "Approve", "callback_data": "approve:login_x"},
            {"text": "App", "url": "https://app.test"},
        ],
    }) == {
        "text": "choose",
        "attachments": [{
            "type": "inline_keyboard",
            "payload": {"buttons": [[
                {"type": "callback", "text": "Approve", "payload": "approve:login_x"},
                {"type": "link", "text": "App", "url": "https://app.test"},
            ]]},
        }],
    }


def test_payload_prefix_is_sanitized() -> None:
    assert sanitized_payload_prefix("login_private-value") == "login_"
    assert sanitized_payload_prefix("approve:login_private-value") == "approve_"
    assert sanitized_payload_prefix("ordinary-private-value") == "ordinary-private"
    assert sanitized_payload_prefix(None) is None


def test_approve_preserves_order_diagnostics_avatar_and_reply() -> None:
    events: list[tuple] = []
    diagnostics: dict = {}
    logs: list[str] = []
    avatars: list[str] = []

    async def api_call(method, path, payload, params):
        events.append(("api", method, path, payload, params))
        return {"ok": True}

    user = {"user_id": "user-7", "id": "user-7"}
    runtime = make_runtime(
        api_call=api_call,
        approve=lambda token, actual_user: events.append(("approve", token, actual_user)) or True,
        avatars=avatars,
        diagnostics=diagnostics,
        logs=logs,
    )
    update = {
        "callback": {"payload": "approve:login_nonce", "user": user, "message": {"sender": user}},
    }
    result = asyncio.run(handle_max_update_with_runtime(update, True, runtime))

    assert result["botLogin"] == "approved"
    assert result["recipient"] == {"user_id": "user-7"}
    assert events[0] == ("approve", "nonce", user)
    assert events[1][1:3] == ("POST", "/messages")
    assert avatars == ["user-7"]
    assert diagnostics == {"lastCallbackAt": "2026-07-13T19:00:00+00:00"}
    assert all("nonce" not in line for line in logs)


def test_bot_started_login_preserves_button_send_and_diagnostic() -> None:
    calls: list[tuple] = []
    diagnostics: dict = {}
    logs: list[str] = []
    answer = {"text": "confirm", "buttons": [{"text": "Approve", "callback_data": "approve:login_nonce"}]}

    async def api_call(method, path, payload, params):
        calls.append((method, path, payload, params))
        return {"ok": True}

    runtime = make_runtime(api_call=api_call, command=lambda _text: answer, diagnostics=diagnostics, logs=logs)
    update = {"bot_started": {"payload": "login_nonce"}, "user_id": "user-8"}
    result = asyncio.run(handle_max_update_with_runtime(update, True, runtime))

    assert result["answer"] == answer
    assert result["recipient"] == {"user_id": "user-8"}
    assert calls == [("POST", "/messages", max_message_payload(answer), {"user_id": "user-8"})]
    assert diagnostics == {"lastBotStartedAt": "2026-07-13T19:00:00+00:00"}
    assert "MAX confirmation button sent" in logs
    assert all("nonce" not in line for line in logs)


def test_command_and_batch_filtering_preserve_order_without_replies() -> None:
    async def api_call(method, path, payload, params):
        raise AssertionError(f"unexpected API call: {method} {path} {payload} {params}")

    runtime = make_runtime(api_call=api_call, command=lambda text: {"text": f"answer:{text}", "buttons": []})
    updates = [
        {"message": {"body": {"text": "plain"}, "sender": {"user_id": "1"}}},
        {"message": {"body": {"text": "/help"}, "sender": {"user_id": "2"}}},
        {"message": {"body": {"text": "/settings"}, "sender": {"user_id": "3"}}},
    ]
    result = asyncio.run(handle_max_updates_with_runtime(updates, False, runtime))

    assert [item["answer"]["text"] for item in result] == ["answer:/help", "answer:/settings"]
    assert [item["recipient"] for item in result] == [{"user_id": "2"}, {"user_id": "3"}]
