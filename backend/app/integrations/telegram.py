"""Import-safe Telegram Bot API HTTP client and health probe."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal

import httpx


TELEGRAM_API_BASE_URL = "https://api.telegram.org"


class TelegramClientError(RuntimeError):
    """Base error that never includes the bot token in its message."""

    def __init__(
        self,
        message: str,
        *,
        method: str,
        status_code: int | None = None,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message)
        self.method = method
        self.status_code = status_code
        self.retry_after = retry_after


class TelegramConfigurationError(TelegramClientError):
    """The Bot API cannot be called because required configuration is absent."""


class TelegramTransportError(TelegramClientError):
    """The HTTP request failed or Telegram returned a non-success HTTP status."""


class TelegramResponseError(TelegramClientError):
    """Telegram returned JSON that does not match the Bot API envelope."""


class TelegramApiError(TelegramClientError):
    """Telegram returned a valid ``ok=false`` Bot API envelope."""

    def __init__(self, *, method: str, payload: dict[str, Any]) -> None:
        error_code = payload.get("error_code")
        status_code = error_code if isinstance(error_code, int) else None
        super().__init__(
            f"Telegram Bot API rejected {method}." if status_code is None else f"Telegram Bot API rejected {method} ({status_code}).",
            method=method,
            status_code=status_code,
            retry_after=_retry_after_from_payload(payload),
        )
        self.payload = payload


TelegramHealthStatus = Literal[
    "ok",
    "not_configured",
    "unauthorized",
    "unavailable",
    "invalid_response",
]


@dataclass(frozen=True)
class TelegramBotHealth:
    configured: bool
    ok: bool
    status: TelegramHealthStatus
    bot_id: int | None = None
    username: str | None = None
    status_code: int | None = None
    error_type: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _retry_after_from_payload(payload: dict[str, Any]) -> float | None:
    parameters = payload.get("parameters")
    value = parameters.get("retry_after") if isinstance(parameters, dict) else None
    if value is None:
        value = payload.get("retry_after")
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _retry_after_from_response(response: httpx.Response) -> float | None:
    try:
        payload = response.json()
    except Exception:
        payload = None
    if isinstance(payload, dict):
        retry_after = _retry_after_from_payload(payload)
        if retry_after is not None:
            return retry_after
    value = response.headers.get("Retry-After")
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def telegram_file_url(token: str, file_path: str) -> str:
    """Build the official Bot API file URL without logging or persisting it."""

    if not token:
        raise TelegramConfigurationError(
            "Telegram bot token is not configured.",
            method="getFile",
        )
    return f"{TELEGRAM_API_BASE_URL}/file/bot{token}/{file_path}"


async def request_telegram_bot_api(
    *,
    token: str,
    method: str,
    payload: dict[str, Any] | None = None,
    timeout_seconds: float = 30,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    """POST one Bot API method and return a validated Telegram envelope."""

    if not token:
        raise TelegramConfigurationError(
            "Telegram bot token is not configured.",
            method=method,
        )
    client_options: dict[str, Any] = {"timeout": timeout_seconds}
    if transport is not None:
        client_options["transport"] = transport
    try:
        async with httpx.AsyncClient(**client_options) as client:
            response = await client.post(
                f"{TELEGRAM_API_BASE_URL}/bot{token}/{method}",
                json=payload or {},
            )
    except httpx.RequestError as exc:
        raise TelegramTransportError(
            f"Telegram Bot API transport failed for {method}.",
            method=method,
        ) from None

    if not 200 <= response.status_code < 300:
        raise TelegramTransportError(
            f"Telegram Bot API returned HTTP {response.status_code} for {method}.",
            method=method,
            status_code=response.status_code,
            retry_after=_retry_after_from_response(response),
        )
    try:
        data = response.json()
    except Exception:
        raise TelegramResponseError(
            f"Telegram Bot API returned invalid JSON for {method}.",
            method=method,
            status_code=response.status_code,
        ) from None
    if not isinstance(data, dict) or not isinstance(data.get("ok"), bool):
        raise TelegramResponseError(
            f"Telegram Bot API returned an invalid envelope for {method}.",
            method=method,
            status_code=response.status_code,
        )
    if not data["ok"]:
        raise TelegramApiError(method=method, payload=data)
    return data


async def probe_telegram_bot(
    *,
    token: str,
    timeout_seconds: float = 5,
    transport: httpx.AsyncBaseTransport | None = None,
) -> TelegramBotHealth:
    """Run a sanitized ``getMe`` health probe without exposing the bot token."""

    if not token:
        return TelegramBotHealth(False, False, "not_configured")
    try:
        payload = await request_telegram_bot_api(
            token=token,
            method="getMe",
            timeout_seconds=timeout_seconds,
            transport=transport,
        )
    except (TelegramTransportError, TelegramApiError) as exc:
        status = "unauthorized" if exc.status_code in {401, 403} else "unavailable"
        return TelegramBotHealth(
            True,
            False,
            status,
            status_code=exc.status_code,
            error_type=type(exc).__name__,
        )
    except TelegramClientError as exc:
        return TelegramBotHealth(
            True,
            False,
            "invalid_response",
            status_code=exc.status_code,
            error_type=type(exc).__name__,
        )

    result = payload.get("result")
    if not isinstance(result, dict) or not isinstance(result.get("id"), int):
        return TelegramBotHealth(
            True,
            False,
            "invalid_response",
            error_type="TelegramResponseError",
        )
    username = result.get("username")
    return TelegramBotHealth(
        True,
        True,
        "ok",
        bot_id=result["id"],
        username=username if isinstance(username, str) else None,
        status_code=200,
    )
