"""Shared worker runtime for Telegram/MAX delivery (ARCH-BE-BOTS-001).

Commit 1 scope: the `BotRuntime` owns only the mutable *worker* state that the
polling workers and lifecycle registry operate on — the polling health
registry, the polling task table, the started flag, the MAX polling
diagnostics and the MAX deep-link cache. Nothing here imports `backend.main`.

Provider *configuration* (tokens, secrets, modes, api base url, webhook url)
stays canonical in `main.py` for now; workers read a point-in-time
`ProviderConfigSnapshot` through the single injected `get_provider_config`
dependency, so the existing dynamic behavior (config can change at runtime via
admin settings) is preserved without a second source of truth.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

try:
    from .polling_health import (
        PollingHealthRegistry,
        compute_poll_backoff,
        is_auth_polling_error,
        polling_retry_after,
    )
except ImportError:  # Direct `python backend/main.py` execution.
    from app.services.polling_health import (
        PollingHealthRegistry,
        compute_poll_backoff,
        is_auth_polling_error,
        polling_retry_after,
    )


def _default_max_polling_diag() -> dict[str, Any]:
    return {
        "lastPollAt": None,
        "lastPollStatus": None,
        "lastPollError": None,
        "lastPollMarker": None,
        "lastPollNextMarker": None,
        "lastRawCount": None,
        "lastBotStartedAt": None,
        "lastCallbackAt": None,
        "lastWebhookAt": None,
        "lastWebhookError": None,
        "subscriptionStatus": None,
        "webhookConfigured": False,
        "webhookUrlSet": False,
        "updateTypes": [],
    }


def _default_max_deep_link_cache() -> dict[str, Any]:
    return {
        "attempted": False,
        "base": None,
        "source": "unresolved",
        "resolved": False,
        "api_status": None,
        "fields": [],
    }


@dataclass(frozen=True)
class ProviderConfigSnapshot:
    """Point-in-time provider configuration. Token never appears in repr."""

    provider: str
    mode: str
    polling_enabled: bool
    token: str = field(default="", repr=False)
    api_base_url: str = ""
    webhook_url: str = ""

    @property
    def token_configured(self) -> bool:
        return bool(self.token)


@dataclass(frozen=True)
class BotRuntimeDependencies:
    """Injected collaborators for the worker domain (constructed in main.py)."""

    connect: Callable[[], Any]
    record_security_event: Callable[..., Any]
    get_provider_config: Callable[[str], ProviderConfigSnapshot]
    now_iso: Callable[[], str]
    log: Callable[[str], None]


@dataclass
class BotRuntime:
    """The single owner of mutable worker state (health/tasks/diag/cache)."""

    polling_health: PollingHealthRegistry
    dependencies: BotRuntimeDependencies
    polling_tasks: dict[str, asyncio.Task] = field(default_factory=dict)
    polling_started: bool = False
    max_polling_diag: dict[str, Any] = field(default_factory=_default_max_polling_diag)
    max_deep_link_cache: dict[str, Any] = field(default_factory=_default_max_deep_link_cache)

    def provider_config(self, provider: str) -> ProviderConfigSnapshot:
        return self.dependencies.get_provider_config(provider)

    def snapshot(self) -> dict[str, Any]:
        """Secret-free view for diagnostics/tests. No tokens or secrets."""
        telegram = self.dependencies.get_provider_config("telegram")
        maximum = self.dependencies.get_provider_config("max")
        return {
            "telegram": {
                "mode": telegram.mode,
                "pollingEnabled": telegram.polling_enabled,
                "tokenConfigured": telegram.token_configured,
            },
            "max": {
                "mode": maximum.mode,
                "pollingEnabled": maximum.polling_enabled,
                "tokenConfigured": maximum.token_configured,
                "apiBaseUrl": maximum.api_base_url,
            },
            "pollingStarted": self.polling_started,
            "pollingTasks": sorted(self.polling_tasks.keys()),
        }


def create_bot_runtime(
    *,
    polling_health: PollingHealthRegistry,
    dependencies: BotRuntimeDependencies,
) -> BotRuntime:
    return BotRuntime(polling_health=polling_health, dependencies=dependencies)


# --- Polling workers and lifecycle (ARCH-BE-BOTS-001, commit 1) -------------
#
# The workers operate on a BotRuntime. Provider config is read fresh each loop
# iteration via runtime.provider_config so runtime config changes keep effect
# (unchanged from the previous in-main behavior); cursor/backoff/health logic
# is identical to the extracted originals. The poll callables stay in main.py
# (they depend on the provider transport + cursor helpers) and are injected.


def provider_polling_active(config: ProviderConfigSnapshot) -> bool:
    active = config.mode == "polling" and config.polling_enabled and bool(config.token)
    if config.provider == "max":
        active = active and bool(config.api_base_url)
    return active


async def provider_polling_cycle(
    runtime: BotRuntime,
    provider: str,
    poll: Callable[..., Awaitable[Any]],
) -> bool:
    """One worker cycle feeding runtime health; False = stop (auth error)."""
    deps = runtime.dependencies
    health = runtime.polling_health
    try:
        await poll(timeout=25, limit=20)
    except Exception as exc:
        if is_auth_polling_error(exc):
            health.record_failure(provider, exc)
            with deps.connect() as conn:
                deps.record_security_event(conn, f"{provider}_polling_auth_error", severity="critical")
            deps.log(f"{provider} polling stopped after auth error")
            return False
        alerted = health.record_failure(provider, exc)
        snapshot = health.snapshot(provider)
        if alerted:
            deps.log(f"BOT_POLLING_ALERT provider={provider} consecutiveFailures={snapshot['consecutiveFailures']} class={type(exc).__name__}")
        delay = compute_poll_backoff(
            snapshot["consecutiveFailures"],
            provider_retry_after=polling_retry_after(exc, default=0.0) or None,
        )
        deps.log(f"{provider} polling error {type(exc).__name__} backoff={delay:.1f}s")
        await asyncio.sleep(delay)
        return True
    if health.record_success(provider):
        deps.log(f"BOT_POLLING_RECOVERED provider={provider}")
    return True


async def run_provider_polling(
    runtime: BotRuntime,
    provider: str,
    poll: Callable[..., Awaitable[Any]],
) -> None:
    runtime.polling_health.record_worker_started(provider)
    while provider_polling_active(runtime.provider_config(provider)):
        if not await provider_polling_cycle(runtime, provider, poll):
            break


def start_bot_polling_tasks(
    runtime: BotRuntime,
    *,
    telegram_poll: Callable[..., Awaitable[Any]],
    max_poll: Callable[..., Awaitable[Any]],
) -> list[str]:
    tasks = runtime.polling_tasks
    started: list[str] = []
    # A live task is never duplicated; a finished one may be replaced here.
    for provider in ("telegram", "max"):
        existing_task = tasks.get(provider)
        if existing_task is not None and existing_task.done():
            tasks.pop(provider, None)
    polls = {"telegram": telegram_poll, "max": max_poll}
    for provider in ("telegram", "max"):
        if provider not in tasks and provider_polling_active(runtime.provider_config(provider)):
            tasks[provider] = asyncio.create_task(run_provider_polling(runtime, provider, polls[provider]))
            started.append(provider)
    runtime.polling_started = bool(tasks)
    return started


async def stop_bot_polling_tasks(runtime: BotRuntime) -> None:
    tasks = runtime.polling_tasks
    for task in list(tasks.values()):
        task.cancel()
    for task in list(tasks.values()):
        try:
            await task
        except BaseException:  # noqa: BLE001 - cancellation and worker exit are both fine
            pass
    tasks.clear()
    runtime.polling_started = False
