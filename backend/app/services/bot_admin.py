"""Pure helpers for the trusted-admin bot integrations page."""

from __future__ import annotations

from copy import deepcopy
from typing import Any
from urllib.parse import urlparse


BOT_MODES = {"disabled", "polling", "webhook"}
DEFAULT_BOT_INTEGRATIONS: dict[str, Any] = {
    "telegram": {
        "mode": "disabled",
        "pollingEnabled": False,
        "botUsername": "",
        "deepLinkBase": "",
    },
    "max": {
        "mode": "disabled",
        "pollingEnabled": False,
        "apiBaseUrl": "https://platform-api2.max.ru",
        "deepLinkBase": "",
        "webhookUrl": "",
        "updateTypes": ["bot_started", "message_callback", "message_created"],
    },
    "public": {
        "siteUrl": "https://izo.alikinas.ru",
        "backendUrl": "https://izo.alikinas.ru",
    },
}


def _clean_url(value: Any, *, https_required: bool, allow_empty: bool = True) -> str:
    clean = str(value or "").strip().rstrip("/")
    if not clean and allow_empty:
        return ""
    parsed = urlparse(clean)
    if parsed.scheme not in ({"https"} if https_required else {"http", "https"}) or not parsed.netloc:
        requirement = "HTTPS" if https_required else "HTTP/HTTPS"
        raise ValueError(f"Укажите корректный {requirement}-адрес.")
    if parsed.username or parsed.password:
        raise ValueError("URL с логином или паролем запрещён.")
    return clean


def normalize_bot_integrations(
    raw: Any,
    *,
    production: bool,
) -> dict[str, Any]:
    source = raw if isinstance(raw, dict) else {}
    result = deepcopy(DEFAULT_BOT_INTEGRATIONS)

    telegram = source.get("telegram") if isinstance(source.get("telegram"), dict) else {}
    telegram_mode = str(telegram.get("mode") or "disabled").strip().lower()
    if telegram_mode not in BOT_MODES:
        raise ValueError("Недопустимый режим Telegram.")
    result["telegram"].update(
        {
            "mode": telegram_mode,
            "pollingEnabled": bool(telegram.get("pollingEnabled", False)),
            "botUsername": str(telegram.get("botUsername") or "").strip().lstrip("@")[:64],
            "deepLinkBase": _clean_url(telegram.get("deepLinkBase"), https_required=production),
        }
    )

    max_config = source.get("max") if isinstance(source.get("max"), dict) else {}
    max_mode = str(max_config.get("mode") or "disabled").strip().lower()
    if max_mode not in BOT_MODES:
        raise ValueError("Недопустимый режим MAX.")
    update_types = max_config.get("updateTypes")
    if not isinstance(update_types, list):
        update_types = result["max"]["updateTypes"]
    result["max"].update(
        {
            "mode": max_mode,
            "pollingEnabled": bool(max_config.get("pollingEnabled", False)),
            "apiBaseUrl": _clean_url(
                max_config.get("apiBaseUrl") or result["max"]["apiBaseUrl"],
                https_required=production,
                allow_empty=False,
            ),
            "deepLinkBase": _clean_url(max_config.get("deepLinkBase"), https_required=production),
            "webhookUrl": _clean_url(max_config.get("webhookUrl"), https_required=True),
            "updateTypes": [
                str(item).strip()
                for item in update_types
                if str(item).strip()
            ][:20],
        }
    )

    public = source.get("public") if isinstance(source.get("public"), dict) else {}
    result["public"].update(
        {
            "siteUrl": _clean_url(
                public.get("siteUrl") or result["public"]["siteUrl"],
                https_required=production,
                allow_empty=False,
            ),
            "backendUrl": _clean_url(
                public.get("backendUrl") or result["public"]["backendUrl"],
                https_required=production,
                allow_empty=False,
            ),
        }
    )
    if production:
        for key, value in result["public"].items():
            hostname = (urlparse(value).hostname or "").lower()
            if hostname in {"localhost", "127.0.0.1", "::1"}:
                raise ValueError(f"{key} не может указывать на localhost в production.")
    return result


def webhook_url(config: dict[str, Any], provider: str) -> str:
    provider_config = config.get(provider) if isinstance(config.get(provider), dict) else {}
    if provider == "max" and str(provider_config.get("webhookUrl") or "").strip():
        return str(provider_config["webhookUrl"]).rstrip("/")
    backend_url = str((config.get("public") or {}).get("backendUrl") or "").rstrip("/")
    return f"{backend_url}/api/{provider}/webhook" if backend_url else ""


def safe_bot_error(cause: BaseException) -> str:
    status_code = getattr(cause, "status_code", None)
    if status_code in {401, 403}:
        return "Неверный токен или доступ к API запрещён."
    name = type(cause).__name__.lower()
    text = str(cause).lower()
    if "timeout" in name or "timeout" in text:
        return "Сервис не ответил вовремя. Проверьте интернет или VPN."
    if any(marker in name or marker in text for marker in ("transport", "connect", "network", "tls", "ssl")):
        return "Сервис недоступен. Проверьте интернет, VPN и системные сертификаты."
    if "secret" in text:
        return "Секрет webhook отсутствует или имеет неверный формат."
    return "Операция не выполнена. Подробности сохранены в журнале сервера."
