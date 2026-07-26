"""Read-only connection probes for supported social publication providers."""

from __future__ import annotations

from typing import Any

import httpx


class SocialProviderError(RuntimeError):
    pass


async def probe_social_provider(
    network: str,
    *,
    token: str,
    target_id: str,
    application_key: str = "",
    session_secret: str = "",
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    if not token.strip():
        raise SocialProviderError("Ключ доступа не сохранён.")
    own_client = client is None
    http = client or httpx.AsyncClient(timeout=15, follow_redirects=True)
    try:
        if network == "telegram":
            response = await http.get(f"https://api.telegram.org/bot{token}/getMe")
            payload = response.json()
            if response.status_code != 200 or not payload.get("ok"):
                raise SocialProviderError("Telegram отклонил токен.")
            bot = payload.get("result") or {}
            target = None
            if target_id.strip():
                check = await http.get(
                    f"https://api.telegram.org/bot{token}/getChat",
                    params={"chat_id": target_id.strip()},
                )
                checked = check.json()
                if check.status_code != 200 or not checked.get("ok"):
                    raise SocialProviderError("Telegram-канал или chat ID недоступен боту.")
                target = checked.get("result") or {}
            return {"identity": bot.get("username") or bot.get("id"), "target": target}
        if network == "max":
            response = await http.get(
                "https://platform-api2.max.ru/me",
                headers={"Authorization": token},
            )
            payload = response.json()
            if response.status_code != 200 or payload.get("code"):
                raise SocialProviderError("MAX отклонил ключ доступа.")
            target = None
            if target_id.strip():
                checked = await http.get(
                    f"https://platform-api2.max.ru/chats/{target_id.strip()}",
                    headers={"Authorization": token},
                )
                target = checked.json()
                if checked.status_code != 200 or target.get("code"):
                    raise SocialProviderError("Канал или чат MAX недоступен боту.")
            return {"identity": payload.get("username") or payload.get("user_id"), "target": target}
        if network == "vk":
            response = await http.get(
                "https://api.vk.com/method/groups.getById",
                params={"group_id": target_id.strip(), "access_token": token, "v": "5.199"},
            )
            payload = response.json()
            if response.status_code != 200 or payload.get("error"):
                raise SocialProviderError("VK отклонил ключ или группа недоступна.")
            row = ((payload.get("response") or {}).get("groups") or [{}])[0]
            return {"identity": row.get("name") or row.get("id"), "target": row}
        if network == "instagram":
            response = await http.get(
                "https://graph.instagram.com/me",
                params={"fields": "id,username", "access_token": token},
            )
            payload = response.json()
            if response.status_code != 200 or payload.get("error"):
                raise SocialProviderError("Instagram отклонил ключ доступа.")
            if target_id.strip() and str(payload.get("id")) != target_id.strip():
                raise SocialProviderError("Instagram account ID не совпадает с ключом.")
            return {"identity": payload.get("username") or payload.get("id"), "target": payload}
        if network == "ok":
            if not application_key.strip() or not session_secret.strip() or not target_id.strip():
                raise SocialProviderError(
                    "Для Одноклассников нужны application key, session secret и group ID."
                )
            raise SocialProviderError(
                "Реквизиты OK сохранены, но signed API-проверка ещё не подключена."
            )
        raise SocialProviderError("Неподдерживаемая социальная сеть.")
    except (httpx.HTTPError, ValueError) as exc:
        raise SocialProviderError("Сервис социальной сети не ответил.") from exc
    finally:
        if own_client:
            await http.aclose()
