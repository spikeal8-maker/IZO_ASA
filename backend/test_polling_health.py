"""BOT-TG-001: provider polling health, backoff and single-owner contracts.

Fake transports only — no real Telegram/MAX traffic, no webhook deletion, no
cursor reset. The live DB is never touched: DB_PATH is redirected to a temp
file and initialized per test.
"""
from __future__ import annotations

import asyncio
import random
from pathlib import Path

import pytest

import main
from app.services.polling_health import (
    PollingHealthRegistry,
    compute_poll_backoff,
    is_auth_polling_error,
    polling_retry_after,
)


class FakeTransportError(Exception):
    """Timeout/TLS-class transport failure without an HTTP response."""


class FakeHttpError(Exception):
    def __init__(self, status_code: int, retry_after: float | None = None) -> None:
        super().__init__(f"http {status_code}")
        self.status_code = status_code
        if retry_after is not None:
            self.retry_after = retry_after


@pytest.fixture
def temp_db(tmp_path: Path, monkeypatch):
    db_file = tmp_path / "polling_health.sqlite3"
    monkeypatch.setattr(main, "DB_PATH", db_file)
    main.init_db()
    yield db_file


def test_backoff_is_bounded_exponential_with_jitter() -> None:
    rng = random.Random(7)
    delays = [
        compute_poll_backoff(failures, base=2.0, cap=60.0, rng=rng)
        for failures in (1, 2, 3, 4, 5, 6, 10, 50)
    ]
    expected_raw = [2.0, 4.0, 8.0, 16.0, 32.0, 60.0, 60.0, 60.0]
    for delay, raw in zip(delays, expected_raw):
        assert raw * 0.8 <= delay <= raw * 1.2
    assert max(delays) <= 60.0 * 1.2


def test_backoff_respects_longer_provider_retry_after() -> None:
    rng = random.Random(3)
    delay = compute_poll_backoff(1, provider_retry_after=45.0, base=2.0, cap=60.0, rng=rng)
    assert delay >= 45.0 * 0.8
    shorter = compute_poll_backoff(6, provider_retry_after=1.0, base=2.0, cap=60.0, rng=rng)
    assert shorter >= 60.0 * 0.8, "a short provider hint must not shrink the computed backoff"


def test_retry_after_and_auth_classifiers_for_fake_transports() -> None:
    assert polling_retry_after(FakeHttpError(429, retry_after=9.0)) == 9.0
    assert polling_retry_after(FakeTransportError(), default=5.0) == 5.0
    assert is_auth_polling_error(FakeHttpError(401)) is True
    assert is_auth_polling_error(FakeHttpError(500)) is False
    assert is_auth_polling_error(FakeTransportError()) is False


def test_health_alert_fires_once_and_recovery_clears_it() -> None:
    registry = PollingHealthRegistry(alert_threshold=3)
    events = [registry.record_failure("telegram", FakeTransportError()) for _ in range(5)]
    assert events == [False, False, True, False, False], "alert exactly once at threshold"
    health = registry.snapshot("telegram")
    assert health["alertActive"] is True
    assert health["consecutiveFailures"] == 5
    assert health["lastErrorClass"] == "FakeTransportError"

    recovered = registry.record_success("telegram")
    assert recovered is True
    health = registry.snapshot("telegram")
    assert health["alertActive"] is False
    assert health["consecutiveFailures"] == 0
    assert health["lastErrorClass"] is None
    assert health["totalFailures"] == 5
    assert health["totalSuccesses"] == 1
    assert registry.record_success("telegram") is False


def test_health_snapshot_contains_no_secret_material() -> None:
    registry = PollingHealthRegistry()
    registry.record_failure("max", FakeHttpError(503))
    registry.record_success("max")
    serialized = str(registry.snapshot_all())
    assert "token" not in serialized.lower()
    assert "://" not in serialized


def test_worker_cycle_records_failure_backoff_then_recovery(monkeypatch, temp_db) -> None:
    registry = PollingHealthRegistry(alert_threshold=2)
    monkeypatch.setattr(main, "POLLING_HEALTH", registry)
    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(main.asyncio, "sleep", fake_sleep)
    calls = {"count": 0}

    async def flaky_poll(timeout: int = 0, limit: int = 0) -> dict:
        calls["count"] += 1
        if calls["count"] <= 2:
            raise FakeTransportError()
        return {"ok": True}

    async def scenario() -> None:
        for _ in range(3):
            assert await main._provider_polling_cycle("telegram", flaky_poll) is True

    asyncio.run(scenario())

    health = registry.snapshot("telegram")
    assert health["totalFailures"] == 2
    assert health["totalSuccesses"] == 1
    assert health["alertActive"] is False, "success after alert must clear it"
    assert len(sleeps) == 2
    assert sleeps[1] > sleeps[0] * 1.2, "backoff must grow between consecutive failures"


def test_worker_cycle_stops_on_auth_error_and_records_event(monkeypatch, temp_db) -> None:
    registry = PollingHealthRegistry()
    monkeypatch.setattr(main, "POLLING_HEALTH", registry)

    async def auth_poll(timeout: int = 0, limit: int = 0) -> dict:
        raise FakeHttpError(401)

    assert asyncio.run(main._provider_polling_cycle("telegram", auth_poll)) is False
    assert registry.snapshot("telegram")["lastErrorClass"] == "FakeHttpError"
    with main.db() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM security_events WHERE event_type = 'telegram_polling_auth_error'"
        ).fetchone()
    assert row["c"] == 1


def test_start_bot_polling_tasks_never_duplicates_a_live_owner(monkeypatch, temp_db) -> None:
    monkeypatch.setattr(main, "BOT_UPDATES_MODE", "polling")
    monkeypatch.setattr(main, "TELEGRAM_POLLING_ENABLED", True)
    monkeypatch.setattr(main, "TELEGRAM_BOT_TOKEN", "fake-token")
    monkeypatch.setattr(main, "MAX_UPDATES_MODE", "disabled")
    monkeypatch.setattr(main, "bot_polling_tasks", {})

    async def scenario() -> None:
        forever = asyncio.Event()

        async def blocked_worker() -> None:
            await forever.wait()

        monkeypatch.setattr(main, "telegram_polling_worker", blocked_worker)
        first = main.start_bot_polling_tasks()
        second = main.start_bot_polling_tasks()
        try:
            assert first == ["telegram"]
            assert second == [], "a live polling owner must never be duplicated"
            assert len(main.bot_polling_tasks) == 1
        finally:
            forever.set()
            await main.bot_polling_tasks["telegram"]

    asyncio.run(scenario())


def test_start_bot_polling_tasks_replaces_finished_owner(monkeypatch, temp_db) -> None:
    monkeypatch.setattr(main, "BOT_UPDATES_MODE", "polling")
    monkeypatch.setattr(main, "TELEGRAM_POLLING_ENABLED", True)
    monkeypatch.setattr(main, "TELEGRAM_BOT_TOKEN", "fake-token")
    monkeypatch.setattr(main, "MAX_UPDATES_MODE", "disabled")
    monkeypatch.setattr(main, "bot_polling_tasks", {})

    async def scenario() -> None:
        async def crashed_worker() -> None:
            return None

        monkeypatch.setattr(main, "telegram_polling_worker", crashed_worker)
        first = main.start_bot_polling_tasks()
        assert first == ["telegram"]
        await main.bot_polling_tasks["telegram"]

        restarted = main.start_bot_polling_tasks()
        assert restarted == ["telegram"], "an explicit start call may replace a finished owner"
        await main.bot_polling_tasks["telegram"]

    asyncio.run(scenario())


def test_telegram_cursor_advances_and_is_idempotent(monkeypatch, temp_db) -> None:
    batches = [
        [{"update_id": 10}, {"update_id": 11}],
        [],
    ]

    async def fake_api(method: str, payload: dict | None = None) -> dict:
        assert method == "getUpdates"
        return {"ok": True, "result": batches.pop(0) if batches else []}

    async def fake_handle(updates: list, send_replies: bool) -> list:
        return []

    monkeypatch.setattr(main, "telegram_api", fake_api)
    monkeypatch.setattr(main, "handle_telegram_updates", fake_handle)

    first = asyncio.run(main.telegram_poll_once_from_api(timeout=0, limit=10))
    assert first["cursor"] == "12", "cursor = max(update_id) + 1"
    # An empty poll must not move or reset the confirmed cursor.
    second = asyncio.run(main.telegram_poll_once_from_api(timeout=0, limit=10))
    assert second["cursor"] == "12"
