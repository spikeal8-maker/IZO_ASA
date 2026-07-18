from __future__ import annotations

import httpx
import pytest

from app.integrations.unisender import (
    UniSenderError,
    UniSenderMessage,
    create_unisender_list,
    get_unisender_lists,
    send_unisender_email,
)


def response(payload: dict) -> httpx.Response:
    return httpx.Response(200, json=payload, request=httpx.Request("POST", "https://api.unisender.test"))


def test_get_lists_posts_key_without_putting_it_in_url() -> None:
    captured: dict = {}

    def post(url, *, data, timeout):
        captured.update({"url": url, "data": data, "timeout": timeout})
        return response({"result": [{"id": "12", "title": "Пользователи"}]})

    lists = get_unisender_lists("secret-key", post=post)

    assert lists == [{"id": 12, "title": "Пользователи"}]
    assert "secret-key" not in captured["url"]
    assert captured["data"]["api_key"] == "secret-key"


def test_create_list_returns_normalized_list() -> None:
    created = create_unisender_list(
        "secret-key",
        "Пользователи ИЗО АСА",
        post=lambda *_args, **_kwargs: response({"result": {"id": "31"}}),
    )
    assert created == {"id": 31, "title": "Пользователи ИЗО АСА"}


def test_send_email_uses_verified_sender_and_list() -> None:
    captured: dict = {}

    def post(_url, *, data, timeout):
        captured.update(data)
        return response({"result": {"email_id": "mail-42"}})

    message_id = send_unisender_email(
        "secret-key",
        UniSenderMessage(
            to="user@example.test",
            subject="Код подтверждения",
            html="<p>123456</p>",
            sender_name="ИЗО АСА",
            sender_email="mail@alikinas.ru",
            list_id=31,
        ),
        post=post,
    )

    assert message_id == "mail-42"
    assert captured["email"] == "user@example.test"
    assert captured["sender_email"] == "mail@alikinas.ru"
    assert captured["list_id"] == "31"


def test_provider_error_is_human_readable() -> None:
    with pytest.raises(UniSenderError, match="не подтвержден"):
        send_unisender_email(
            "secret-key",
            UniSenderMessage(
                to="user@example.test",
                subject="Проверка",
                html="<p>test</p>",
                sender_name="ИЗО АСА",
                sender_email="mail@alikinas.ru",
                list_id=31,
            ),
            post=lambda *_args, **_kwargs: response({"error": "Email отправителя не подтвержден"}),
        )
