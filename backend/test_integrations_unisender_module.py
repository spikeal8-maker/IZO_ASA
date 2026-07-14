from __future__ import annotations

import httpx
import pytest

from app.integrations.unisender import UniSenderError, UniSenderMessage, get_unisender_lists, send_unisender_email


def message() -> UniSenderMessage:
    return UniSenderMessage(
        to="user@example.test",
        subject="Код подтверждения",
        html="<b>123456</b>",
        sender_name="ИЗО АСА",
        sender_email="mail@example.test",
        list_id=12,
        reference_key="otp-1",
    )


def response(payload: dict, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json=payload, request=httpx.Request("POST", "https://example.test"))


def test_send_unisender_email_posts_required_fields_without_logging_key():
    captured = {}

    def post(url, **kwargs):
        captured.update({"url": url, **kwargs})
        return response({"result": [{"index": 0, "email": "user@example.test", "id": "mail-42"}]})

    assert send_unisender_email("secret-key", message(), post=post) == "mail-42"
    assert captured["data"]["list_id"] == "12"
    assert captured["data"]["ref_key"] == "otp-1"
    assert captured["data"]["api_key"] == "secret-key"


def test_send_unisender_email_surfaces_provider_validation_error():
    def post(_url, **_kwargs):
        return response({"result": [{"errors": [{"code": "unchecked_sender_email", "message": "Sender is not confirmed"}]}]})

    with pytest.raises(UniSenderError, match="Sender is not confirmed"):
        send_unisender_email("secret-key", message(), post=post)


def test_send_unisender_email_rejects_missing_delivery_id():
    with pytest.raises(UniSenderError, match="message id"):
        send_unisender_email("secret-key", message(), post=lambda *_args, **_kwargs: response({"result": []}))


def test_get_unisender_lists_returns_human_titles():
    captured = {}

    def get(url, **kwargs):
        captured.update({"url": url, **kwargs})
        return response({"result": [{"id": 7, "title": "Пользователи ИЗО"}]})

    assert get_unisender_lists("secret-key", get=get) == [{"id": 7, "title": "Пользователи ИЗО"}]
    assert captured["params"]["api_key"] == "secret-key"


def test_get_unisender_lists_surfaces_provider_error():
    with pytest.raises(UniSenderError, match="invalid_api_key"):
        get_unisender_lists("bad-key", get=lambda *_args, **_kwargs: response({"error": "invalid_api_key"}))
