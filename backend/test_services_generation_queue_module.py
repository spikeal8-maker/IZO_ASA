from __future__ import annotations

import asyncio
import inspect
from typing import Any

import pytest

import app.services.generation_queue as generation_queue_module
from app.services.generation_queue import (
    GenerationQueueRuntime,
    consume_generation_queue,
    start_generation_consumer_once,
)


class QueueExhausted(RuntimeError):
    pass


class FakeQueue:
    def __init__(self, *job_ids: str) -> None:
        self.job_ids = list(job_ids)
        self.get_calls = 0
        self.task_done_calls = 0

    async def get(self) -> str:
        self.get_calls += 1
        if not self.job_ids:
            raise QueueExhausted("queue exhausted")
        return self.job_ids.pop(0)

    def task_done(self) -> None:
        self.task_done_calls += 1


def runtime(
    queue: FakeQueue,
    *,
    jobs: dict[str, dict[str, Any]] | None = None,
    parse_request: Any = None,
    perf_counter: Any = None,
    build_worker_runtime: Any = None,
    process_job: Any = None,
) -> GenerationQueueRuntime:
    async def default_process(
        _job_id: str,
        _job: dict[str, Any],
        _request: Any,
        _worker_runtime: Any,
        *,
        started_at: float,
    ) -> None:
        assert started_at == 123.5

    return GenerationQueueRuntime(
        queue=queue,
        jobs=jobs if jobs is not None else {"job_1": {"request": {"prompt": "test"}}},
        parse_request=parse_request or (lambda payload: ("parsed", payload)),
        perf_counter=perf_counter or (lambda: 123.5),
        build_worker_runtime=build_worker_runtime or (lambda: "worker-runtime"),
        process_job=process_job or default_process,
    )


def test_queue_module_has_no_framework_database_or_application_dependencies() -> None:
    source = inspect.getsource(generation_queue_module).lower()

    for forbidden in ("fastapi", "pydantic", "sqlite3", "httpx", "os.environ", "pathlib", "import main"):
        assert forbidden not in source


def test_consumer_processes_one_item_then_marks_it_done_exactly_once() -> None:
    queue = FakeQueue("job_1")
    calls: list[tuple[Any, ...]] = []

    async def process(job_id: str, job: dict[str, Any], request: Any, worker_runtime: Any, *, started_at: float) -> None:
        calls.append((job_id, job, request, worker_runtime, started_at))

    with pytest.raises(QueueExhausted, match="queue exhausted"):
        asyncio.run(consume_generation_queue(runtime(queue, process_job=process)))

    assert calls == [
        (
            "job_1",
            {"request": {"prompt": "test"}},
            ("parsed", {"prompt": "test"}),
            "worker-runtime",
            123.5,
        )
    ]
    assert queue.task_done_calls == 1
    assert queue.get_calls == 2


def test_process_error_still_marks_dequeued_item_done() -> None:
    queue = FakeQueue("job_1")

    async def fail(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("processor failed")

    with pytest.raises(RuntimeError, match="processor failed"):
        asyncio.run(consume_generation_queue(runtime(queue, process_job=fail)))

    assert queue.task_done_calls == 1


def test_process_cancellation_still_marks_dequeued_item_done() -> None:
    queue = FakeQueue("job_1")

    async def cancel(*_args: Any, **_kwargs: Any) -> None:
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(consume_generation_queue(runtime(queue, process_job=cancel)))

    assert queue.task_done_calls == 1


def test_missing_job_fails_before_task_done_like_legacy_consumer() -> None:
    queue = FakeQueue("missing")

    with pytest.raises(KeyError, match="missing"):
        asyncio.run(consume_generation_queue(runtime(queue, jobs={})))

    assert queue.task_done_calls == 0


def test_request_parse_failure_happens_before_task_done() -> None:
    queue = FakeQueue("job_1")

    def fail_parse(_payload: dict[str, Any]) -> Any:
        raise ValueError("invalid request")

    with pytest.raises(ValueError, match="invalid request"):
        asyncio.run(consume_generation_queue(runtime(queue, parse_request=fail_parse)))

    assert queue.task_done_calls == 0


def test_runtime_build_failure_happens_before_task_done() -> None:
    queue = FakeQueue("job_1")

    def fail_runtime() -> Any:
        raise RuntimeError("runtime unavailable")

    with pytest.raises(RuntimeError, match="runtime unavailable"):
        asyncio.run(consume_generation_queue(runtime(queue, build_worker_runtime=fail_runtime)))

    assert queue.task_done_calls == 0


def test_start_once_schedules_consumer_and_returns_started() -> None:
    scheduled: list[Any] = []

    async def consumer() -> None:
        return None

    def create_task(coroutine: Any) -> object:
        scheduled.append(coroutine)
        coroutine.close()
        return object()

    started = start_generation_consumer_once(
        already_started=False,
        create_task=create_task,
        consumer=consumer,
    )

    assert started is True
    assert len(scheduled) == 1


def test_start_once_does_not_create_duplicate_consumer() -> None:
    def unexpected_consumer() -> Any:
        raise AssertionError("consumer must not be created")

    def unexpected_task(_coroutine: Any) -> Any:
        raise AssertionError("task must not be scheduled")

    assert start_generation_consumer_once(
        already_started=True,
        create_task=unexpected_task,
        consumer=unexpected_consumer,
    ) is True


def test_start_once_propagates_task_creation_failure() -> None:
    async def consumer() -> None:
        return None

    def fail_create_task(coroutine: Any) -> Any:
        coroutine.close()
        raise RuntimeError("task creation failed")

    with pytest.raises(RuntimeError, match="task creation failed"):
        start_generation_consumer_once(
            already_started=False,
            create_task=fail_create_task,
            consumer=consumer,
        )
