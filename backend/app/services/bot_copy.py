"""Safe, deterministic Russian help copy shared by Telegram and MAX bots."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Literal


BotPlatform = Literal["telegram", "max"]


def _open_button(text: str, url: str) -> list[dict[str, str]]:
    return [{"text": text, "url": url}]


def _normalized_command(message: str) -> str:
    first = message.strip().split(maxsplit=1)[0].lower() if message.strip() else "/start"
    return first if first.startswith("/") else "message"


def _help_topic(message: str) -> str:
    lowered = message.casefold()
    topics = (
        ("login", ("вход", "войти", "авториза", "регистра", "аккаунт", "парол", "код")),
        ("generation", ("генера", "картин", "изображ", "фото", "промпт", "prompt", "описан")),
        ("gallery", ("галере", "работ", "результат", "сохран", "скача")),
        ("settings", ("настрой", "профил", "тариф", "лимит", "баланс", "оплат")),
        ("problem", ("ошиб", "не работает", "не могу", "проблем", "завис", "помощ", "поддерж")),
    )
    for topic, markers in topics:
        if any(marker in lowered for marker in markers):
            return topic
    return "general"


def build_bot_response(
    platform: BotPlatform,
    message: str,
    *,
    app_url: str,
    login_payload: str | None = None,
    latest_image_ids: Iterable[str] = (),
) -> dict[str, Any]:
    """Return bounded help copy without external AI calls or sensitive data."""
    command = _normalized_command(message)
    latest = [str(image_id) for image_id in latest_image_ids][:5]

    if login_payload:
        text = (
            "Подтвердите вход в ИЗО АСА только если запрос открыли вы. "
            "Мы никогда не просим здесь пароль, код из письма или данные карты."
        )
        buttons = [{"text": "Подтвердить вход", "callback_data": f"approve:{login_payload}"}]
    elif command == "/start":
        text = (
            "Добро пожаловать! Я бот ИЗО АСА. Помогу открыть студию, войти в аккаунт "
            "и разобраться с генерацией. Можно написать вопрос обычными словами."
        )
        buttons = _open_button("Открыть приложение", app_url)
    elif command == "/app":
        text = "Студия готова: откройте ИЗО АСА и выберите нужный режим создания."
        buttons = _open_button("Открыть студию", app_url)
    elif command == "/help":
        text = (
            "Чем помочь? Напишите: «как войти», «как создать изображение», "
            "«где мои работы» или опишите проблему. Команды: /app, /gallery, /settings."
        )
        buttons = _open_button("Открыть студию", app_url)
    elif command == "/gallery":
        text = "Последние работы: " + (", ".join(latest) if latest else "галерея пока пуста.")
        buttons = _open_button("Открыть галерею", f"{app_url}#gallery")
    elif command == "/settings":
        text = "В настройках можно проверить профиль, лимиты, тариф и способы входа."
        buttons = _open_button("Открыть настройки", f"{app_url}#settings")
    elif command.startswith("/"):
        text = "Такой команды пока нет. Используйте /app, /help, /gallery или /settings."
        buttons = _open_button("Открыть студию", app_url)
    else:
        topic = _help_topic(message)
        copy = {
            "login": (
                "Чтобы войти, откройте ИЗО АСА кнопкой ниже и выберите вход через бота. "
                "Подтверждайте запрос только если начали вход сами."
            ),
            "generation": (
                "Откройте студию, выберите режим, опишите желаемый результат простыми словами "
                "и нажмите «Создать». Для режима по фото сначала загрузите исходное изображение."
            ),
            "gallery": "Готовые результаты находятся в личной галерее. Там их можно открыть, сохранить и продолжить редактирование.",
            "settings": "Профиль, лимиты и тариф находятся в разделе настроек ИЗО АСА.",
            "problem": (
                "Помогу разобраться. Проверьте интернет, закройте и снова откройте ИЗО АСА, "
                "затем повторите действие. Если ошибка останется, напишите, на каком шаге она появилась."
            ),
            "general": (
                "Я могу подсказать про вход, создание изображений, галерею и настройки. "
                "Напишите вопрос подробнее или используйте /help."
            ),
        }
        text = copy[topic]
        buttons = _open_button("Открыть ИЗО АСА", app_url)

    return {
        "ok": True,
        "platform": platform,
        "command": command,
        "text": text,
        "buttons": buttons,
    }
