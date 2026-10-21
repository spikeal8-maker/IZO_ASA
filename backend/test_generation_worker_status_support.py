"""Windows-only synchronization for the real-process fixture's status file.

Windows replacement of an open target fails even with FILE_SHARE_DELETE.
Serialize fixture reads with the original executor save; POSIX remains direct.
This never retries a save, replaces the writer, or changes file permissions.
"""
from __future__ import annotations

from contextlib import contextmanager
import errno
import os
import time


@contextmanager
def status_file_lock(path, *, timeout=.25):
    if os.name != "nt":
        yield
        return
    import msvcrt
    deadline = time.monotonic() + timeout
    with open(str(path) + ".fixture-lock", "a+b") as stream:
        if stream.tell() == 0:
            stream.write(b"\0")
            stream.flush()
        while True:
            stream.seek(0)
            try:
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                break
            except OSError as error:
                if error.errno not in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
                    raise
                if time.monotonic() >= deadline:
                    raise TimeoutError("owned fixture status lock timed out") from error
                time.sleep(.002)
        try:
            yield
        finally:
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
