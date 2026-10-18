"""Private single-writer request handler for separately leased executors.

There is no job-consumer task in this API process. An executor connects and
claims durable work; this handler supplies provider commands and commits the
existing accounting/media callbacks. The executor performs their HTTP effects.
"""
from __future__ import annotations

import asyncio
from contextlib import nullcontext, suppress
from dataclasses import dataclass, replace
import errno
import os
from pathlib import Path
import stat
import time

from ..integrations import generation_ipc, generation_transport
from . import generation_claims, generation_leases, generation_worker
from .generation_worker_persistence import drain_owned_task


MAX_HANDLERS = 8
MAX_RECENT_WORKERS = 64


def _owned_lock(path):
    import fcntl
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    stream = os.fdopen(descriptor, "a+b")
    try:
        info = os.fstat(descriptor)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1):
            raise RuntimeError("GENERATION_WORKER_OWNER_LOCK_UNSAFE")
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return stream
    except BaseException:
        stream.close()
        raise


def acquire_database_ownership(path):
    """Fence every POSIX API role using its canonical database identity."""
    database = Path(path)
    if not database.is_absolute():
        raise RuntimeError("GENERATION_WORKER_DATABASE_PATH_REQUIRED")
    database = database.resolve()
    info = database.parent.stat()
    if (info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o022
            or (database.exists() and database.stat().st_nlink != 1)):
        raise RuntimeError("GENERATION_WORKER_DATABASE_OWNER_UNSAFE")
    return _owned_lock(database.with_name(database.name + ".owner.lock"))


@dataclass(frozen=True)
class DispatchRuntime:
    connect: object
    parse_request: object
    make_runtime: object
    jobs: object
    refund_job: object
    process_job: object = generation_worker.process_generation_job
    drain_storage: object = None


class GenerationDispatcher:
    def __init__(self, path, runtime, *, lease_seconds=generation_leases.LEASE_SECONDS, database_path=None):
        self.path = Path(path)
        self.database_path = Path(database_path) if database_path is not None else None
        self.runtime = runtime
        self.lease_seconds = lease_seconds
        self.server = None
        self.lock_file = None
        self.database_lock = None
        self.socket_identity = None
        self.watchdog = None
        self.close_task = None
        self.handlers = set()
        self.channels = set()
        self.executions = {}
        self.admission_lock = asyncio.Lock()
        self.last_worker_seen = None
        self.recent_workers = {}
        self.last_success = None
        self.last_failure = None
        self.expired_count = 0
        self.completed_count = 0
        self.claimed_count = 0
        self.closed = False

    async def prepare(self):
        """Take process ownership before the API may open its SQLite writer."""
        if self.lock_file is not None:
            return
        if os.name != "posix" or not self.path.is_absolute() or len(os.fsencode(self.path)) >= 100:
            raise RuntimeError("GENERATION_WORKER_UNIX_SOCKET_REQUIRED")
        try:
            if self.database_path is not None:
                self.database_lock = acquire_database_ownership(self.database_path)
            parent = self.path.parent
            parent.mkdir(mode=0o700, exist_ok=True)
            info = parent.lstat()
            if (not stat.S_ISDIR(info.st_mode) or parent != parent.resolve()
                    or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700):
                raise RuntimeError("GENERATION_WORKER_SOCKET_DIRECTORY_UNSAFE")
            self.lock_file = _owned_lock(parent / "generation-owner.lock")
            if self.path.exists() or self.path.is_symlink():
                info = self.path.lstat()
                if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.geteuid():
                    raise RuntimeError("GENERATION_WORKER_SOCKET_OCCUPIED")
                try:
                    _reader, writer = await asyncio.wait_for(asyncio.open_unix_connection(self.path), 1)
                except OSError as error:
                    if error.errno != errno.ECONNREFUSED:
                        raise
                    self.path.unlink()
                else:
                    writer.close()
                    await writer.wait_closed()
                    raise RuntimeError("GENERATION_WORKER_SOCKET_ALREADY_ACTIVE")
        except BaseException:
            await self.close()
            raise

    async def start(self):
        if self.server is not None:
            return
        if self.lock_file is None:
            await self.prepare()
        try:
            self.server = await asyncio.start_unix_server(self._handle, path=self.path)
            os.chmod(self.path, 0o600)
            info = self.path.lstat()
            self.socket_identity = (info.st_dev, info.st_ino)
            self.watchdog = asyncio.create_task(self._watch(), name="generation-lease-watchdog")
        except BaseException:
            await self.close()
            raise

    def _expire(self):
        expired = generation_leases.expire(self.runtime.connect, self.runtime.refund_job)
        if expired:
            self.expired_count += len(expired)
            self.last_failure = time.time()
            worker_runtime = self.runtime.make_runtime()
            for job_id in expired:
                job = self.runtime.jobs.get(job_id)
                if job is not None:
                    worker_runtime.refresh_job(job_id, job)
                task = self.executions.get(job_id)
                if task is not None and task is not asyncio.current_task():
                    task.cancel()

    async def _watch(self):
        try:
            while True:
                async with self.admission_lock:
                    self._expire()
                    self._prune_workers()
                await asyncio.sleep(min(1, self.lease_seconds / 3))
        except Exception:
            self.last_failure = time.time()
            raise

    def _renew(self, claim):
        generation_leases.renew(self.runtime.connect, claim, lease_seconds=self.lease_seconds)
        self._seen_worker(claim.worker_id)

    def _prune_workers(self):
        now = time.time()
        self.recent_workers = {worker: seen for worker, seen in self.recent_workers.items()
                               if 0 <= now - seen <= self.lease_seconds}

    def _seen_worker(self, worker_id):
        self._prune_workers()
        if worker_id not in self.recent_workers and len(self.recent_workers) >= MAX_RECENT_WORKERS:
            del self.recent_workers[min(self.recent_workers, key=self.recent_workers.get)]
        self.last_worker_seen = time.time()
        self.recent_workers[worker_id] = self.last_worker_seen

    async def _handle(self, reader, writer):
        if self.closed or len(self.handlers) >= MAX_HANDLERS:
            writer.close()
            with suppress(Exception):
                await writer.wait_closed()
            return
        task = asyncio.current_task()
        self.handlers.add(task)
        channel = None
        claim = None
        try:
            hello = await asyncio.wait_for(generation_ipc.read_frame(reader, body_limit=lambda _value: 0), 5)
            if (hello.get("kind") != "claim" or hello.get("version") != generation_ipc.PROTOCOL_VERSION
                    or hello["body"] or not isinstance(hello.get("workerId"), str)
                    or generation_leases.WORKER_ID.fullmatch(hello["workerId"]) is None):
                raise ValueError("GENERATION_WORKER_HANDSHAKE_INVALID")
            if reader.at_eof():
                return
            if self.closed:
                return
            async with self.admission_lock:
                self._expire()
                grant = (None if self.channels else generation_leases.claim_next(
                    self.runtime.connect, hello.get("workerId"), lease_seconds=self.lease_seconds))
            self._seen_worker(hello["workerId"])
            if grant is None:
                await generation_ipc.write_frame(writer, {"kind": "idle"}, asyncio.Lock())
                return
            claim, job = grant
            self.executions[claim.job_id] = task
            self.claimed_count += 1
            self.runtime.jobs[claim.job_id] = job
            channel = generation_ipc.WorkerChannel(
                reader, writer,
                renew=lambda: self._renew(claim),
                before_command=lambda: generation_leases.command_started(self.runtime.connect, claim),
                abandon=lambda: generation_leases.abandon(self.runtime.connect, claim),
                lease_seconds=self.lease_seconds,
            )
            self.channels.add(channel)
            await channel.send({"kind": "claimed", "jobId": claim.job_id,
                                "heartbeatSeconds": min(2, self.lease_seconds / 3)})
            request = self.runtime.parse_request(job["request"])
            original = self.runtime.make_runtime()
            runtime = replace(original, claim_job=lambda *_args: nullcontext(True), after_completion=None)
            transport = generation_ipc.WorkerHTTPTransport(channel)
            with generation_claims.bind_claim(claim), generation_transport.bind(transport):
                run_completion_hooks = await self.runtime.process_job(
                    claim.job_id, job, request, runtime, started_at=time.perf_counter(),
                )
            channel.finished = True
            if job.get("status") == "completed":
                self.completed_count += 1
                self.last_success = time.time()
                if run_completion_hooks is not False and original.after_completion is not None:
                    await original.after_completion(claim.user_id)
            elif job.get("status") in {"failed", "cancelled"}:
                self.last_failure = time.time()
            if not channel.closed:
                await channel.send({"kind": "finished", "status": job.get("status")})
        except asyncio.CancelledError:
            raise
        except Exception:
            self.last_failure = time.time()
        finally:
            try:
                if claim is not None:
                    generation_leases.abandon(self.runtime.connect, claim)
            except Exception:
                self.last_failure = time.time()
            finally:
                if channel is not None:
                    await channel.close()
                    self.channels.discard(channel)
                else:
                    writer.close()
                    with suppress(Exception):
                        await writer.wait_closed()
                self.handlers.discard(task)
                if claim is not None:
                    self.executions.pop(claim.job_id, None)
            if claim is not None and not self.closed:
                try:
                    self._expire()
                except Exception:
                    self.last_failure = time.time()

    def snapshot(self):
        now = time.time()
        watchdog_ok = not self.closed and self.watchdog is not None and not self.watchdog.done()
        recent = self.last_worker_seen is not None and 0 <= now - self.last_worker_seen <= self.lease_seconds
        online = sum(0 <= now - seen <= self.lease_seconds for seen in self.recent_workers.copy().values())
        return {
            "role": "server", "localConsumer": False, "ready": bool(watchdog_ok and recent),
            "connectedWorkers": len(self.channels), "lastWorkerSeenAt": self.last_worker_seen,
            "onlineWorkers": online,
            "lastSuccessAt": self.last_success, "lastFailureAt": self.last_failure,
            "claimedJobs": self.claimed_count, "completedJobs": self.completed_count,
            "expiredLeases": self.expired_count, "watchdog": "running" if watchdog_ok else "stopped",
        }

    async def close(self):
        self.closed = True
        if self.close_task is None:
            self.close_task = asyncio.create_task(self._close_owned(), name="generation-dispatcher-close")
        await drain_owned_task(self.close_task)

    async def _close_owned(self):
        if self.server is not None:
            self.server.close()
            await self.server.wait_closed()
        for task in tuple(self.handlers):
            task.cancel()
        if self.handlers:
            await asyncio.gather(*tuple(self.handlers), return_exceptions=True)
        if self.watchdog is not None:
            self.watchdog.cancel()
            await asyncio.gather(self.watchdog, return_exceptions=True)
        try:
            if self.runtime.drain_storage is not None:
                await self.runtime.drain_storage()
            if self.socket_identity is not None and self.path.exists():
                info = self.path.lstat()
                if stat.S_ISSOCK(info.st_mode) and (info.st_dev, info.st_ino) == self.socket_identity:
                    self.path.unlink()
        finally:
            for name in ("lock_file", "database_lock"):
                stream = getattr(self, name)
                if stream is not None:
                    stream.close()
                    setattr(self, name, None)
