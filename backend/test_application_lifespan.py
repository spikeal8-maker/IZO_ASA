"""Real asyncio task checks for application lifespan ownership."""

from __future__ import annotations

import asyncio
from contextlib import suppress

import pytest

from app.services.application_lifespan import (
    GenerationConsumerOwner,
    make_application_lifespan,
    stop_all,
)


def test_repeated_lifespan_resolves_callbacks_and_runs_exactly_one_consumer():
    async def scenario():
        owner = GenerationConsumerOwner()
        events = []
        tasks = []
        started = asyncio.Event()

        async def consumer():
            tasks.append(asyncio.current_task())
            events.append("consumer-start")
            started.set()
            try:
                await asyncio.Future()
            finally:
                events.append("consumer-stop")

        async def original_startup():
            raise AssertionError("stale callback")

        async def original_shutdown():
            raise AssertionError("stale callback")

        callbacks = {"startup": original_startup, "shutdown": original_shutdown}
        lifespan = make_application_lifespan(
            lambda: callbacks["startup"](), lambda: callbacks["shutdown"](), owner
        )
        for index in range(3):
            started = asyncio.Event()

            async def startup():
                events.append(f"startup-{index}")
                assert owner.start(consumer)
                assert owner.start(consumer)
                await started.wait()

            async def shutdown():
                assert not owner.running
                events.append(f"shutdown-{index}")

            callbacks.update(startup=startup, shutdown=shutdown)
            async with lifespan(None):
                assert owner.running
                assert len(tasks) == index + 1
                assert sum(not task.done() for task in tasks) == 1
            assert not owner.running
        assert len({id(task) for task in tasks}) == 3
        assert all(task.cancelled() for task in tasks)
        assert events == [
            event
            for index in range(3)
            for event in (f"startup-{index}", "consumer-start", "consumer-stop", f"shutdown-{index}")
        ]

    asyncio.run(scenario())


def test_partial_startup_failure_drains_consumer_and_preserves_original_error():
    async def scenario():
        owner = GenerationConsumerOwner()
        started = asyncio.Event()
        stopped = asyncio.Event()
        shutdown_calls = []
        original = ValueError("startup validation failed after consumer start")

        async def consumer():
            started.set()
            try:
                await asyncio.Future()
            finally:
                stopped.set()

        async def startup():
            owner.start(consumer)
            await started.wait()
            raise original

        async def shutdown():
            assert stopped.is_set()
            shutdown_calls.append(True)

        lifespan = make_application_lifespan(startup, shutdown, owner)
        with pytest.raises(ValueError) as captured:
            async with lifespan(None):
                pytest.fail("startup failed before entering application")
        assert captured.value is original
        assert stopped.is_set() and not owner.running
        assert shutdown_calls == [True]

    asyncio.run(scenario())


def test_shutdown_failure_does_not_leak_consumer_or_cancel_unrelated_task():
    async def scenario():
        owner = GenerationConsumerOwner()
        started = asyncio.Event()
        stopped = asyncio.Event()
        unrelated = asyncio.create_task(asyncio.Event().wait())

        async def consumer():
            started.set()
            try:
                await asyncio.Future()
            finally:
                stopped.set()

        async def startup():
            owner.start(consumer)
            await started.wait()

        async def shutdown():
            raise RuntimeError("shutdown failed")

        try:
            with pytest.raises(RuntimeError, match="shutdown failed"):
                async with make_application_lifespan(startup, shutdown, owner)(None):
                    pass
            assert stopped.is_set() and not owner.running
            assert not unrelated.done()
            await owner.stop()
        finally:
            unrelated.cancel()
            with suppress(asyncio.CancelledError):
                await unrelated

    asyncio.run(scenario())


def test_concurrent_stop_drains_once_and_blocks_restart_until_cleanup_finishes():
    async def scenario():
        owner = GenerationConsumerOwner()
        started = asyncio.Event()
        cleaning = asyncio.Event()
        finish_cleanup = asyncio.Event()
        stopped = []

        async def consumer():
            started.set()
            try:
                await asyncio.Future()
            finally:
                cleaning.set()
                await finish_cleanup.wait()
                stopped.append(True)

        owner.start(consumer)
        await started.wait()
        first_stop = asyncio.create_task(owner.stop())
        await cleaning.wait()
        second_stop = asyncio.create_task(owner.stop())
        await asyncio.sleep(0)
        with pytest.raises(RuntimeError, match="still stopping"):
            owner.start(consumer)
        finish_cleanup.set()
        await asyncio.gather(first_stop, second_stop)
        assert stopped == [True]
        assert not owner.running
        assert owner.start(consumer)
        await asyncio.sleep(0)
        await owner.stop()
        assert stopped == [True, True]

    asyncio.run(scenario())


def test_consumer_failure_still_runs_shutdown_and_resets_owner():
    async def scenario():
        owner = GenerationConsumerOwner()
        shutdown_calls = []

        async def consumer():
            raise LookupError("consumer failed")

        async def startup():
            owner.start(consumer)
            await asyncio.sleep(0)

        async def shutdown():
            shutdown_calls.append(True)

        with pytest.raises(LookupError, match="consumer failed"):
            async with make_application_lifespan(startup, shutdown, owner)(None):
                pass
        assert shutdown_calls == [True] and not owner.running
        await owner.stop()

    asyncio.run(scenario())


def test_overlapping_lifespan_is_rejected_without_stopping_active_context():
    async def scenario():
        owner = GenerationConsumerOwner()
        shutdown_calls = []

        async def startup():
            owner.start(asyncio.Event().wait)

        async def shutdown():
            shutdown_calls.append(True)

        lifespan = make_application_lifespan(startup, shutdown, owner)
        async with lifespan(None):
            with pytest.raises(RuntimeError, match="already active"):
                async with lifespan(None):
                    pytest.fail("overlapping context entered")
            assert owner.running and shutdown_calls == []
        assert not owner.running and shutdown_calls == [True]

    asyncio.run(scenario())


def test_stop_all_attempts_every_callback_and_preserves_all_errors():
    async def scenario():
        calls = []
        first = ValueError("first")
        second = RuntimeError("second")

        async def stop(name, failure=None):
            calls.append(name)
            if failure is not None:
                raise failure

        with pytest.raises(ExceptionGroup) as captured:
            await stop_all(
                lambda: stop("first", first),
                lambda: stop("middle"),
                lambda: stop("last", second),
            )
        assert calls == ["first", "middle", "last"]
        assert captured.value.exceptions == (first, second)

    asyncio.run(scenario())


def test_stop_all_preserves_cancellation_and_attempts_remaining_callbacks():
    async def scenario():
        completed = []

        async def cancelled():
            raise asyncio.CancelledError("callback cancelled")

        async def remaining():
            completed.append(True)

        with pytest.raises(BaseExceptionGroup) as captured:
            await stop_all(cancelled, remaining)
        assert completed == [True]
        assert len(captured.value.exceptions) == 1
        assert isinstance(captured.value.exceptions[0], asyncio.CancelledError)

    asyncio.run(scenario())
