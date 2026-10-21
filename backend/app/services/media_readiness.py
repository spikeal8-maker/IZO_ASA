"""Bounded checks of the current media filesystem without modifying user files."""

from __future__ import annotations

import asyncio
import errno
import os
import tempfile
import threading
import time
from concurrent.futures import Future
from pathlib import Path


def probe_media_write(media: Path) -> str | None:
    """Write, sync and read one temporary byte; return only a public reason code.

    TemporaryFile exclusively creates its own file. On Linux it uses an unnamed
    inode, or unlinks its exclusive temporary name before the first write. The
    context closes it on every outcome, including write/fsync/read failures.
    Nothing creates the configured directory, changes its permissions, or opens
    an existing media object for writing.
    """
    try:
        if media.is_symlink() or not media.is_dir():
            return "MEDIA_UNAVAILABLE"
        with tempfile.TemporaryFile(dir=media, prefix=".izo-readiness-", buffering=0) as handle:
            if handle.write(b"\x00") != 1:
                return "MEDIA_IO_FAILED"
            handle.flush()
            os.fsync(handle.fileno())
            handle.seek(0)
            if handle.read(1) != b"\x00":
                return "MEDIA_IO_FAILED"
        return None
    except OSError as error:
        if error.errno in {errno.EACCES, errno.EPERM, errno.EROFS}:
            return "MEDIA_NOT_WRITABLE"
        if error.errno in {errno.ENOSPC, getattr(errno, "EDQUOT", errno.ENOSPC)}:
            return "MEDIA_CAPACITY_EXHAUSTED"
        if error.errno in {errno.ENOENT, errno.ENOTDIR}:
            return "MEDIA_UNAVAILABLE"
        return "MEDIA_IO_FAILED"


class MediaReadiness:
    """Allow only one filesystem probe in flight, even after a request timeout.

    A stalled filesystem cannot occupy the API event loop or create an unbounded
    executor backlog. A daemon thread permits normal process exit if an OS call
    never returns. No completed result is cached: the next request checks the
    current path again, allowing recovery without restarting the application.
    """

    def __init__(self, timeout_seconds: float = 1.0) -> None:
        if not 0 < timeout_seconds <= 5:
            raise ValueError("media_probe_timeout_invalid")
        self.timeout_seconds = timeout_seconds
        self._lock = threading.Lock()
        self._active: tuple[Path, float, Future[str | None]] | None = None

    @staticmethod
    def _run(media: Path, future: Future[str | None]) -> None:
        try:
            reason = probe_media_write(media)
        except Exception:
            reason = "MEDIA_IO_FAILED"
        future.set_result(reason)

    async def check(self, media: Path) -> str | None:
        requested = time.monotonic()
        deadline = requested + self.timeout_seconds
        while True:
            if time.monotonic() >= deadline:
                return "MEDIA_PROBE_TIMEOUT"
            with self._lock:
                if self._active is None or self._active[2].done():
                    future: Future[str | None] = Future()
                    self._active = (media, time.monotonic(), future)
                    try:
                        threading.Thread(target=self._run, args=(media, future),
                                         name="izo-media-readiness", daemon=True).start()
                    except RuntimeError:
                        future.set_result("MEDIA_PROBE_UNAVAILABLE")
                elif self._active[0] != media:
                    return "MEDIA_PROBE_BUSY"
                _, started, future = self._active
            while not future.done():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return "MEDIA_PROBE_TIMEOUT"
                await asyncio.sleep(min(.01, remaining))
            # A probe opened before this request may predate a storage failure.
            # Await its completion, then require a new probe within this deadline.
            if started >= requested:
                return future.result()


MEDIA_READINESS = MediaReadiness()


async def readiness_reason(media: Path, *, database_ready: bool) -> str | None:
    if not database_ready:
        return "DATABASE_NOT_READY"
    return await MEDIA_READINESS.check(media)
