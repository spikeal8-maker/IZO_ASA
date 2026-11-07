"""Application lifespan and ownership of its generation consumer task."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Coroutine
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Any


AsyncCallback = Callable[[], Awaitable[None]]
ConsumerFactory = Callable[[], Coroutine[Any, Any, None]]


class GenerationConsumerOwner:
    """Retain, cancel and drain only the task this owner created."""

    def __init__(self) -> None:
        self._task: asyncio.Task[None] | None = None
        self._stopping = False

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self, consumer: ConsumerFactory) -> bool:
        loop = asyncio.get_running_loop()
        if self._task is not None:
            if self._task.get_loop() is not loop:
                raise RuntimeError("Generation consumer belongs to another event loop")
            if self._stopping:
                raise RuntimeError("Generation consumer is still stopping")
            return self.running
        self._task = loop.create_task(consumer(), name="izo-generation-consumer")
        return self.running

    async def stop(self) -> None:
        task = self._task
        if task is None:
            return
        current = asyncio.current_task()
        if task.get_loop() is not asyncio.get_running_loop() or task is current:
            raise RuntimeError("Generation consumer must be stopped by its owning lifespan")
        cancellation_count = current.cancelling() if current is not None else 0
        if not self._stopping:
            self._stopping = True
            task.cancel()
        try:
            try:
                await task
            except asyncio.CancelledError:
                # Suppress only the expected cancellation of our consumer.
                if not task.cancelled():
                    raise
                if current is not None and current.cancelling() > cancellation_count:
                    raise
        finally:
            if task.done() and self._task is task:
                self._task = None
                self._stopping = False


async def stop_all(*callbacks: AsyncCallback) -> None:
    """Attempt every shutdown callback and retain every failure."""
    failures: list[BaseException] = []
    for callback in callbacks:
        try:
            await callback()
        except BaseException as exc:
            failures.append(exc)
    if failures:
        # The constructor returns ExceptionGroup when all failures are Exceptions.
        raise BaseExceptionGroup("Application shutdown callbacks failed", failures)


def make_application_lifespan(
    startup: AsyncCallback,
    shutdown: AsyncCallback,
    generation_owner: GenerationConsumerOwner,
) -> Callable[[Any], AbstractAsyncContextManager[None]]:
    """Use late-bound lambdas for composition callbacks that may be replaced.

    Cleanup also runs when startup fails before yielding. A generation failure
    cannot skip the remaining shutdown callback. Concurrent entries are rejected
    before startup so one context cannot shut down another context's resources.
    """
    entered = False

    @asynccontextmanager
    async def lifespan(_application: Any) -> AsyncIterator[None]:
        nonlocal entered
        if entered:
            raise RuntimeError("Application lifespan is already active")
        entered = True
        try:
            try:
                await startup()
                yield
            finally:
                try:
                    await generation_owner.stop()
                finally:
                    await shutdown()
        finally:
            entered = False

    return lifespan
