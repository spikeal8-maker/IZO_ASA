"""Generation executor entry point; no application DB, media or main import."""
from __future__ import annotations

import argparse
import asyncio
from contextlib import suppress
import json
import os
from pathlib import Path
import signal
import tempfile
import time
import uuid

import httpx

from .integrations.generation_ipc import MAX_BODY_BYTES, PROTOCOL_VERSION, read_frame, write_frame


STATUS_PATH = Path("/tmp/izo-generation-worker.json")
SOCKET_PATH = "/home/izo/worker/generation.sock"


class GenerationExecutor:
    def __init__(self, socket_path, *, status_path=None, connect=None):
        self.socket_path = socket_path
        self.status_path = status_path
        self.connect = connect or (lambda: asyncio.open_unix_connection(socket_path))
        self.worker_id = uuid.uuid4().hex
        self.state = {
            "version": 1, "role": "worker", "workerId": self.worker_id, "pid": os.getpid(),
            "state": "starting", "currentJobId": None, "lastContactAt": None,
            "lastSuccessAt": None, "lastFailureAt": None, "httpRequests": 0,
            "httpResponses": 0, "httpFailures": 0, "completedJobs": 0,
        }
        self.stop = asyncio.Event()
        self._save()

    def _save(self, **updates):
        self.state.update(updates)
        if self.status_path is not None:
            path = Path(self.status_path)
            descriptor, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
            try:
                with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                    json.dump(self.state, stream, separators=(",", ":"), allow_nan=False)
                    stream.write("\n")
                os.replace(temporary, path)
            finally:
                with suppress(FileNotFoundError):
                    os.unlink(temporary)

    async def _heartbeat(self, writer, lock, interval):
        try:
            while True:
                await write_frame(writer, {"kind": "heartbeat"}, lock)
                await asyncio.sleep(interval)
        except Exception:
            writer.close()
            raise

    async def _request(self, value, writer, lock, client):
        sequence = value.get("id")
        if type(sequence) is not int or value.get("method") not in {"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"}:
            raise ValueError("GENERATION_WORKER_COMMAND_INVALID")
        timeout = value.get("timeout")
        if not isinstance(timeout, dict) or not set(timeout) <= {"connect", "read", "write", "pool"}:
            raise ValueError("GENERATION_WORKER_TIMEOUT_INVALID")
        self._save(httpRequests=self.state["httpRequests"] + 1, lastContactAt=time.time())
        reply = {"kind": "response", "id": sequence}
        chunks = []
        try:
            async with client.stream(value["method"], value["url"], headers=value["headers"],
                                     content=value["body"], timeout=httpx.Timeout(5.0, **timeout)) as response:
                total = 0
                async for chunk in response.aiter_raw(chunk_size=64 * 1024):
                    total += len(chunk)
                    if total > MAX_BODY_BYTES:
                        raise ValueError("GENERATION_WORKER_RESPONSE_LIMIT")
                    chunks.append(chunk)
                reply.update(status=response.status_code,
                             headers=[[key.decode("latin-1"), val.decode("latin-1")] for key, val in response.headers.raw])
            self._save(httpResponses=self.state["httpResponses"] + 1)
        except httpx.TimeoutException:
            reply["error"] = "timeout"
            self._save(httpFailures=self.state["httpFailures"] + 1, lastFailureAt=time.time())
        except Exception:
            reply["error"] = "transport"
            self._save(httpFailures=self.state["httpFailures"] + 1, lastFailureAt=time.time())
        await write_frame(writer, reply, lock, body_chunks=() if reply.get("error") else chunks)

    async def run_session(self):
        reader, writer = await asyncio.wait_for(self.connect(), 5)
        write_lock = asyncio.Lock()
        heartbeat = None
        requests = set()
        async def before_body(value):
            if value.get("kind") == "request":
                if type(value.get("id")) is not int or value["id"] != last_sequence + 1:
                    raise ValueError("GENERATION_WORKER_COMMAND_REPLAY")
                if requests:
                    await asyncio.gather(*tuple(requests))
            elif value.get("kind") not in {"heartbeat_ack", "finished"}:
                raise ValueError("GENERATION_WORKER_COMMAND_INVALID")
        try:
            await write_frame(writer, {"kind": "claim", "version": PROTOCOL_VERSION,
                                       "workerId": self.worker_id}, write_lock)
            reply = await asyncio.wait_for(read_frame(reader, body_limit=lambda _value: 0), 10)
            self._save(lastContactAt=time.time())
            if reply.get("kind") == "idle":
                self._save(state="idle", currentJobId=None)
                return
            if reply.get("kind") != "claimed" or not isinstance(reply.get("jobId"), str):
                raise ValueError("GENERATION_WORKER_GRANT_INVALID")
            interval = reply.get("heartbeatSeconds")
            if not isinstance(interval, (int, float)) or not 0 < interval <= 10:
                raise ValueError("GENERATION_WORKER_HEARTBEAT_INVALID")
            self._save(state="working", currentJobId=reply["jobId"])
            heartbeat = asyncio.create_task(self._heartbeat(writer, write_lock, interval))
            async with httpx.AsyncClient(trust_env=False, follow_redirects=False) as client:
                last_sequence = 0
                while True:
                    value = await read_frame(reader, before_body=before_body,
                        body_limit=lambda frame: MAX_BODY_BYTES if frame.get("kind") == "request" else 0)
                    self._save(lastContactAt=time.time())
                    if value.get("kind") == "heartbeat_ack":
                        if value["body"]:
                            raise ValueError("GENERATION_WORKER_HEARTBEAT_INVALID")
                        continue
                    if value.get("kind") == "finished":
                        if value.get("status") == "completed":
                            self._save(completedJobs=self.state["completedJobs"] + 1, lastSuccessAt=time.time())
                        else:
                            self._save(lastFailureAt=time.time())
                        return
                    if (value.get("kind") != "request" or type(value.get("id")) is not int
                            or value["id"] != last_sequence + 1 or any(not task.done() for task in requests)):
                        raise ValueError("GENERATION_WORKER_COMMAND_REPLAY")
                    last_sequence = value["id"]
                    task = asyncio.create_task(self._request(value, writer, write_lock, client))
                    requests.add(task)
                    task.add_done_callback(requests.discard)
                    task.add_done_callback(lambda finished: writer.close() if not finished.cancelled() and finished.exception() else None)
        finally:
            if heartbeat is not None:
                heartbeat.cancel()
                await asyncio.gather(heartbeat, return_exceptions=True)
            for task in tuple(requests):
                task.cancel()
            if requests:
                await asyncio.gather(*tuple(requests), return_exceptions=True)
            writer.close()
            with suppress(Exception):
                await writer.wait_closed()
            self._save(currentJobId=None)

    async def run(self):
        try:
            while not self.stop.is_set():
                try:
                    await self.run_session()
                except (OSError, asyncio.IncompleteReadError, ValueError):
                    self._save(state="reconnecting", lastFailureAt=time.time())
                try:
                    await asyncio.wait_for(self.stop.wait(), 1)
                except asyncio.TimeoutError:
                    pass
        finally:
            self._save(state="stopped", currentJobId=None)


def healthy(path=STATUS_PATH, *, now=None):
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
        recent = (time.time() if now is None else now) - float(value["lastContactAt"])
        return value["role"] == "worker" and value["state"] in {"idle", "working"} and 0 <= recent <= 15
    except (OSError, ValueError, TypeError, KeyError):
        return False


async def _main(socket_path):
    executor = GenerationExecutor(socket_path, status_path=STATUS_PATH)
    loop = asyncio.get_running_loop()
    current = asyncio.current_task()
    for signum in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(signum, current.cancel)
    try:
        await executor.run()
    except asyncio.CancelledError:
        pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--health", action="store_true")
    args = parser.parse_args()
    if args.health:
        return 0 if healthy() else 1
    if os.environ.get("IZO_PROCESS_ROLE") != "worker" or os.name != "posix":
        raise SystemExit("GENERATION_WORKER_ROLE_REQUIRED")
    path = os.environ.get("IZO_WORKER_SOCKET", SOCKET_PATH)
    if not Path(path).is_absolute():
        raise SystemExit("GENERATION_WORKER_UNIX_SOCKET_REQUIRED")
    asyncio.run(_main(path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
