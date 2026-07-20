"""Provider polling health model (BOT-TG-001).

Replaces "token configured" claims with observable operational health: last
success/failure timestamps, consecutive failure counts, alert/recovery events
and bounded exponential backoff with jitter for the polling workers.

The snapshot is operator data for the trusted-admin status endpoint only; it
never contains tokens, URLs or raw provider payloads — failures are recorded
as exception class names.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

DEFAULT_ALERT_THRESHOLD = 5
DEFAULT_BACKOFF_BASE_SECONDS = 2.0
DEFAULT_BACKOFF_CAP_SECONDS = 60.0
DEFAULT_JITTER_RATIO = 0.2


def polling_retry_after(exc: Exception, default: float = 5.0) -> float:
    """Provider-suggested retry delay (Retry-After / retry_after) or default."""
    typed_retry_after = getattr(exc, "retry_after", None)
    if typed_retry_after is not None:
        try:
            return float(typed_retry_after)
        except (TypeError, ValueError):
            return default
    response = getattr(exc, "response", None)
    if response is None:
        return default
    try:
        payload = response.json()
        retry_after = payload.get("parameters", {}).get("retry_after") or payload.get("retry_after")
        if retry_after:
            return float(retry_after)
    except Exception:
        pass
    header_value = getattr(response, "headers", {}).get("Retry-After") if getattr(response, "headers", None) else None
    if header_value:
        try:
            return float(header_value)
        except ValueError:
            return default
    return default


def is_auth_polling_error(exc: Exception) -> bool:
    if getattr(exc, "status_code", None) in {401, 403}:
        return True
    response = getattr(exc, "response", None)
    return bool(response is not None and getattr(response, "status_code", None) in {401, 403})


def compute_poll_backoff(
    consecutive_failures: int,
    *,
    provider_retry_after: float | None = None,
    base: float = DEFAULT_BACKOFF_BASE_SECONDS,
    cap: float = DEFAULT_BACKOFF_CAP_SECONDS,
    jitter_ratio: float = DEFAULT_JITTER_RATIO,
    rng: random.Random | None = None,
) -> float:
    """Bounded exponential backoff with jitter.

    The provider's own Retry-After always wins when it is longer than the
    computed backoff (rate limits must be respected, never shortened).
    """
    failures = max(1, int(consecutive_failures))
    delay = min(cap, base * (2.0 ** (failures - 1)))
    if provider_retry_after is not None and provider_retry_after > delay:
        delay = float(provider_retry_after)
    jitter_source = rng if rng is not None else random
    jitter = 1.0 + jitter_source.uniform(-jitter_ratio, jitter_ratio)
    return max(0.5, delay * jitter)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ProviderPollingHealth:
    provider: str
    started_at: str | None = None
    last_success_at: str | None = None
    last_failure_at: str | None = None
    last_error_class: str | None = None
    consecutive_failures: int = 0
    total_successes: int = 0
    total_failures: int = 0
    alert_active: bool = False
    alert_raised_at: str | None = None

    def snapshot(self) -> dict[str, Any]:
        return {
            "startedAt": self.started_at,
            "lastSuccessAt": self.last_success_at,
            "lastFailureAt": self.last_failure_at,
            "lastErrorClass": self.last_error_class,
            "consecutiveFailures": self.consecutive_failures,
            "totalSuccesses": self.total_successes,
            "totalFailures": self.total_failures,
            "alertActive": self.alert_active,
            "alertRaisedAt": self.alert_raised_at,
        }


class PollingHealthRegistry:
    """In-process registry; one entry per provider.

    `record_failure` returns True exactly once when the consecutive-failure
    threshold is crossed (alert event); `record_success` returns True when it
    clears an active alert (recovery event). The caller decides how to log —
    the registry itself never touches tokens or provider payloads.
    """

    def __init__(
        self,
        *,
        alert_threshold: int = DEFAULT_ALERT_THRESHOLD,
        now_iso: Callable[[], str] = _utc_now_iso,
    ) -> None:
        self._alert_threshold = max(1, int(alert_threshold))
        self._now_iso = now_iso
        self._providers: dict[str, ProviderPollingHealth] = {}

    def _entry(self, provider: str) -> ProviderPollingHealth:
        if provider not in self._providers:
            self._providers[provider] = ProviderPollingHealth(provider=provider)
        return self._providers[provider]

    def record_worker_started(self, provider: str) -> None:
        entry = self._entry(provider)
        entry.started_at = self._now_iso()

    def record_success(self, provider: str) -> bool:
        entry = self._entry(provider)
        entry.last_success_at = self._now_iso()
        entry.total_successes += 1
        entry.consecutive_failures = 0
        recovered = entry.alert_active
        entry.alert_active = False
        entry.alert_raised_at = None
        entry.last_error_class = None
        return recovered

    def record_failure(self, provider: str, exc: Exception) -> bool:
        entry = self._entry(provider)
        entry.last_failure_at = self._now_iso()
        entry.last_error_class = type(exc).__name__
        entry.total_failures += 1
        entry.consecutive_failures += 1
        if entry.consecutive_failures >= self._alert_threshold and not entry.alert_active:
            entry.alert_active = True
            entry.alert_raised_at = entry.last_failure_at
            return True
        return False

    def snapshot(self, provider: str) -> dict[str, Any]:
        return self._entry(provider).snapshot()

    def snapshot_all(self) -> dict[str, dict[str, Any]]:
        return {provider: entry.snapshot() for provider, entry in self._providers.items()}
