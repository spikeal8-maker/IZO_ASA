"""Import-safe MAX Bot API HTTP client and sanitized health probe."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal

import httpx


class MaxClientError(RuntimeError):
    """Base error that never includes the MAX token or request URL."""

    def __init__(
        self,
        message: str,
        *,
        operation: str,
        status_code: int | None = None,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message)
        self.operation = operation
        self.status_code = status_code
        self.retry_after = retry_after


class MaxConfigurationError(MaxClientError):
    """MAX client configuration is incomplete."""


class MaxTransportError(MaxClientError):
    """The HTTP request failed or MAX returned a non-success HTTP status."""


class MaxResponseError(MaxClientError):
    """MAX returned invalid JSON or a non-object payload."""


MaxHealthStatus = Literal[
    "ok",
    "not_configured",
    "unauthorized",
    "unavailable",
    "invalid_response",
]


@dataclass(frozen=True)
class MaxBotHealth:
    configured: bool
    ok: bool
    status: MaxHealthStatus
    status_code: int | None = None
    error_type: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _validate_configuration(*, token: str, base_url: str, operation: str) -> str:
    if not token:
        raise MaxConfigurationError(
            "MAX bot token is not configured.",
            operation=operation,
        )
    resolved_base_url = base_url.rstrip("/")
    if not resolved_base_url:
        raise MaxConfigurationError(
            "MAX API base URL is not configured.",
            operation=operation,
        )
    return resolved_base_url


def _retry_after_from_response(response: Any) -> float | None:
    try:
        payload = response.json()
    except Exception:
        payload = None
    if isinstance(payload, dict):
        value = payload.get("retry_after")
        if value is None and isinstance(payload.get("details"), dict):
            value = payload["details"].get("retry_after")
        if value is not None:
            try:
                return float(value)
            except (TypeError, ValueError):
                pass
    headers = getattr(response, "headers", None)
    value = headers.get("Retry-After") if headers is not None else None
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_payload(response: Any, *, operation: str) -> dict[str, Any]:
    status_code = getattr(response, "status_code", None)
    if status_code is None and callable(getattr(response, "raise_for_status", None)):
        try:
            response.raise_for_status()
        except Exception:
            raise MaxTransportError(
                "MAX API request failed.",
                operation=operation,
            ) from None
        status_code = 200
    if not isinstance(status_code, int) or not 200 <= status_code < 300:
        raise MaxTransportError(
            "MAX API request failed." if status_code is None else f"MAX API returned HTTP {status_code}.",
            operation=operation,
            status_code=status_code if isinstance(status_code, int) else None,
            retry_after=_retry_after_from_response(response),
        )
    try:
        payload = response.json()
    except Exception:
        raise MaxResponseError(
            "MAX API returned invalid JSON.",
            operation=operation,
            status_code=status_code,
        ) from None
    if not isinstance(payload, dict):
        raise MaxResponseError(
            "MAX API returned a non-object payload.",
            operation=operation,
            status_code=status_code,
        )
    return payload


async def request_max_api(
    *,
    token: str,
    base_url: str,
    verify: Any,
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
    timeout_seconds: float = 30,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    """Call one MAX API endpoint with the legacy authorization/body contract."""

    operation = f"{method.upper()} {path}"
    resolved_base_url = _validate_configuration(
        token=token,
        base_url=base_url,
        operation=operation,
    )
    client_options: dict[str, Any] = {
        "timeout": timeout_seconds,
        "verify": verify,
    }
    if transport is not None:
        client_options["transport"] = transport
    try:
        async with httpx.AsyncClient(**client_options) as client:
            response = await client.request(
                method,
                f"{resolved_base_url}{path}",
                headers={"Authorization": token, "Content-Type": "application/json"},
                json=payload,
                params=params,
            )
    except httpx.RequestError:
        raise MaxTransportError(
            "MAX API transport failed.",
            operation=operation,
        ) from None
    return _parse_payload(response, operation=operation)


def request_max_bot_me(
    *,
    token: str,
    base_url: str,
    verify: Any,
    timeout_seconds: float = 10,
    transport: httpx.BaseTransport | None = None,
) -> tuple[dict[str, Any], int]:
    """Synchronously read `/me` for startup deep-link discovery."""

    operation = "GET /me"
    resolved_base_url = _validate_configuration(
        token=token,
        base_url=base_url,
        operation=operation,
    )
    client_options: dict[str, Any] = {
        "timeout": timeout_seconds,
        "verify": verify,
    }
    if transport is not None:
        client_options["transport"] = transport
    try:
        with httpx.Client(**client_options) as client:
            response = client.get(
                f"{resolved_base_url}/me",
                headers={"Authorization": token, "Content-Type": "application/json"},
            )
    except httpx.RequestError:
        raise MaxTransportError(
            "MAX API transport failed.",
            operation=operation,
        ) from None
    payload = _parse_payload(response, operation=operation)
    return payload, response.status_code


async def probe_max_bot(
    *,
    token: str,
    base_url: str,
    verify: Any,
    timeout_seconds: float = 5,
    transport: httpx.AsyncBaseTransport | None = None,
) -> MaxBotHealth:
    """Run a read-only `/me` probe and expose no provider response fields."""

    if not token or not base_url.rstrip("/"):
        return MaxBotHealth(False, False, "not_configured")
    try:
        await request_max_api(
            token=token,
            base_url=base_url,
            verify=verify,
            method="GET",
            path="/me",
            timeout_seconds=timeout_seconds,
            transport=transport,
        )
    except MaxTransportError as exc:
        status = "unauthorized" if exc.status_code in {401, 403} else "unavailable"
        return MaxBotHealth(
            True,
            False,
            status,
            status_code=exc.status_code,
            error_type=type(exc).__name__,
        )
    except MaxClientError as exc:
        return MaxBotHealth(
            True,
            False,
            "invalid_response",
            status_code=exc.status_code,
            error_type=type(exc).__name__,
        )
    return MaxBotHealth(True, True, "ok", status_code=200)
