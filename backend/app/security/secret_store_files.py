"""Fail-closed POSIX file operations for an owner-only secret directory."""

from __future__ import annotations

import os
import stat
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from .secret_store import SecretStoreError


MAX_FILE_BYTES = 65536
LOCK_NAME = ".store.lock"


def absolute_private_path(root: Path) -> Path:
    path = Path(root).expanduser()
    if not path.is_absolute() or ".." in path.parts or len(path.parts) < 2:
        raise SecretStoreError("The secret-store path must be absolute.")
    return path


def _directory(root: Path, create: bool) -> int:
    if os.name != "posix":
        raise SecretStoreError("POSIX secret storage is unavailable.")
    path = absolute_private_path(root)
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    descriptor = os.open(path.anchor, flags)
    try:
        for index, component in enumerate(path.parts[1:], 1):
            parent = os.fstat(descriptor)
            writable = stat.S_IMODE(parent.st_mode) & 0o022
            sticky_root = parent.st_uid == 0 and parent.st_mode & stat.S_ISVTX
            if parent.st_uid not in {0, os.geteuid()} or (writable and not sticky_root):
                raise SecretStoreError("Unsafe secret-store parent directory.")
            try:
                child = os.open(component, flags, dir_fd=descriptor)
            except FileNotFoundError:
                if not create:
                    raise
                try:
                    os.mkdir(component, 0o700, dir_fd=descriptor)
                    os.fsync(descriptor)
                except FileExistsError:
                    pass
                child = os.open(component, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
            if index == len(path.parts) - 1:
                info = os.fstat(descriptor)
                if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
                    raise SecretStoreError("Secret directory must be owner-only (0700).")
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _check_file(descriptor: int) -> None:
    info = os.fstat(descriptor)
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
            or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != 0o600):
        raise SecretStoreError("Secret files must be private, single-link regular files (0600).")


def read_private(directory: int, name: str) -> bytes | None:
    try:
        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    except FileNotFoundError:
        return None
    try:
        _check_file(descriptor)
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            value = stream.read(MAX_FILE_BYTES + 1)
        if len(value) > MAX_FILE_BYTES:
            raise SecretStoreError("Secret document is too large.")
        return value
    finally:
        os.close(descriptor)


def replace_private(directory: int, name: str, value: bytes) -> None:
    if len(value) > MAX_FILE_BYTES:
        raise SecretStoreError("Secret document is too large.")
    read_private(directory, name)
    temporary = f".{name}.{uuid.uuid4().hex}.tmp"
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         0o600, dir_fd=directory)
    try:
        _check_file(descriptor)
        with os.fdopen(descriptor, "wb", closefd=False) as stream:
            stream.write(value)
            stream.flush()
            os.fsync(descriptor)
        os.replace(temporary, name, src_dir_fd=directory, dst_dir_fd=directory)
        os.fsync(directory)
    finally:
        os.close(descriptor)
        try:
            os.unlink(temporary, dir_fd=directory)
        except FileNotFoundError:
            pass


@contextmanager
def locked_directory(root: Path, *, create: bool = False, timeout: float = 10.0,
                     read_only: bool = False):
    """Pin all directories with no-follow openat and serialize processes/threads."""
    directory = lock = None
    try:
        if read_only and create:
            raise SecretStoreError("Read-only secret snapshots cannot initialize storage.")
        try:
            directory = _directory(root, create)
        except FileNotFoundError:
            if create:
                raise
            yield None
            return
        import fcntl  # Windows imports remain side-effect free.

        flags = os.O_RDONLY if read_only else os.O_RDWR | os.O_CREAT
        lock = os.open(LOCK_NAME, flags | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600, dir_fd=directory)
        _check_file(lock)
        deadline = time.monotonic() + timeout
        while True:
            try:
                kind = fcntl.LOCK_SH if read_only else fcntl.LOCK_EX
                fcntl.flock(lock, kind | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise SecretStoreError("Secret-store lock is busy.") from None
                time.sleep(0.01)
        yield directory
    except SecretStoreError:
        raise
    except OSError:
        raise SecretStoreError("Protected secret storage is unavailable.") from None
    finally:
        if lock is not None:
            os.close(lock)
        if directory is not None:
            os.close(directory)
