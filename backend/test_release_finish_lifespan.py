"""FastAPI uses late-bound lifecycle callbacks and drains its owned consumer."""
import asyncio

import pytest
import main


@pytest.mark.parametrize("fail_startup", [False, True])
def test_real_app_lifespan_cleans_partial_start_and_can_restart(monkeypatch, fail_startup):
    events = []
    owner = main.GENERATION_CONSUMER
    assert not owner.running

    async def consumer():
        events.append("consumer-start")
        try:
            await asyncio.Event().wait()
        finally:
            events.append("consumer-stop")

    async def startup():
        events.append("startup")
        owner.start(consumer)
        await asyncio.sleep(0)
        if fail_startup:
            raise RuntimeError("synthetic partial startup")

    async def shutdown():
        events.append("shutdown")
        assert not owner.running

    monkeypatch.setattr(main, "startup", startup)
    monkeypatch.setattr(main, "shutdown", shutdown)

    async def run():
        for _ in range(2):
            if fail_startup:
                with pytest.raises(RuntimeError, match="synthetic partial startup"):
                    async with main.app.router.lifespan_context(main.app):
                        pytest.fail("Failed startup yielded application control")
            else:
                async with main.app.router.lifespan_context(main.app):
                    assert owner.running
            assert not owner.running

    asyncio.run(run())
    assert events == ["startup", "consumer-start", "consumer-stop", "shutdown"] * 2
    assert main.app.router.on_startup == main.app.router.on_shutdown == []
