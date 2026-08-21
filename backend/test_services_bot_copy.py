"""Focused contracts for deterministic Telegram/MAX user help copy."""

from app.services.bot_copy import build_bot_response


def test_login_copy_is_security_scoped_and_keeps_callback_payload() -> None:
    answer = build_bot_response(
        "max",
        "/start login_nonce",
        app_url="https://app.example/",
        login_payload="login_nonce",
    )

    assert "только если запрос открыли вы" in answer["text"]
    assert "пароль" in answer["text"]
    assert answer["buttons"] == [{"text": "Подтвердить вход", "callback_data": "approve:login_nonce"}]


def test_plain_language_help_routes_common_topics_for_both_bots() -> None:
    maximum = build_bot_response("max", "Как войти в аккаунт?", app_url="https://app.example/")
    telegram = build_bot_response("telegram", "Где мои работы в галерее?", app_url="https://app.example/")

    assert "Чтобы войти" in maximum["text"]
    assert maximum["command"] == "message"
    assert "галерее" in telegram["text"]
    assert telegram["buttons"][0]["url"].startswith("https://")


def test_unknown_text_gets_bounded_menu_without_external_ai() -> None:
    answer = build_bot_response("max", "Здравствуйте", app_url="https://app.example/")

    assert "/help" in answer["text"]
    assert len(answer["text"]) < 500


def test_gallery_copy_limits_identifier_count() -> None:
    answer = build_bot_response(
        "telegram",
        "/gallery",
        app_url="https://app.example/",
        latest_image_ids=(str(index) for index in range(10)),
    )

    assert "0, 1, 2, 3, 4" in answer["text"]
    assert "5" not in answer["text"]
