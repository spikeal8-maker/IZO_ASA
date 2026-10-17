"""In-process generation queue consumer and one-shot task startup."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol


class GenerationQueue(Protocol):
    async def get(self) -> str: ...

    def task_done(self) -> None: ...


@dataclass(frozen=True)
class GenerationQueueRuntime:
    queue: GenerationQueue
    jobs: Mapping[str, dict[str, Any]]
    parse_request: Callable[[dict[str, Any]], Any]
    perf_counter: Callable[[], float]
    build_worker_runtime: Callable[[], Any]
    process_job: Callable[..., Awaitable[None]]


async def consume_generation_queue(runtime: GenerationQueueRuntime) -> None:
    while True:
        job_id = await runtime.queue.get()
        try:
            job = runtime.jobs[job_id]
            request = runtime.parse_request(job["request"])
            started_at = runtime.perf_counter()
            worker_runtime = runtime.build_worker_runtime()
            await runtime.process_job(
                job_id,
                job,
                request,
                worker_runtime,
                started_at=started_at,
            )
        finally:
            runtime.queue.task_done()


def start_generation_consumer_once(
    *,
    already_started: bool,
    create_task: Callable[[Awaitable[None]], Any],
    consumer: Callable[[], Awaitable[None]],
) -> bool:
    if already_started:
        return True
    create_task(consumer())
    return True
