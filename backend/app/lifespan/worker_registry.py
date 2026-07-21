"""Bot worker lifecycle registry (ARCH-BE-BOTS-001).

Owns the start/stop wiring for the polling workers so `main.py` only wires the
registry rather than driving asyncio tasks itself. This module does not import
`backend.main`; the poll callables are injected.
"""
from __future__ import annotations

from typing import Any, Awaitable, Callable

try:
    from ..services.bot_workers import (
        BotRuntime,
        start_bot_polling_tasks,
        stop_bot_polling_tasks,
    )
except ImportError:  # Direct `python backend/main.py` execution.
    from app.services.bot_workers import (
        BotRuntime,
        start_bot_polling_tasks,
        stop_bot_polling_tasks,
    )


def start_bot_workers(
    runtime: BotRuntime,
    *,
    telegram_poll: Callable[..., Awaitable[Any]],
    max_poll: Callable[..., Awaitable[Any]],
) -> list[str]:
    """Start the polling workers on the shared runtime; returns started names."""
    return start_bot_polling_tasks(runtime, telegram_poll=telegram_poll, max_poll=max_poll)


async def stop_bot_workers(runtime: BotRuntime) -> None:
    """Cancel and drain the polling workers on the shared runtime."""
    await stop_bot_polling_tasks(runtime)
