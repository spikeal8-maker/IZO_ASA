"""Bounded private worker framing and task-local HTTP transport over a stream.

Provider credentials and bodies travel only over the owned Unix socket. They
are never interpolated into errors or logs. HTTP effects are not retried here.
"""
from __future__ import annotations

import asyncio
from contextlib import suppress
import json
import struct

import httpx

from ..generation_errors import GenerationClaimLost


MAX_METADATA_BYTES = 1024 * 1024
MAX_BODY_BYTES = 256 * 1024 * 1024
PROTOCOL_VERSION = 1


async def read_frame(reader, *, body_limit=None, before_body=None):
    size = struct.unpack("!I", await reader.readexactly(4))[0]
    if not 1 <= size <= MAX_METADATA_BYTES:
        raise ValueError("GENERATION_IPC_METADATA_LIMIT")
    value = json.loads(await reader.readexactly(size))
    if not isinstance(value, dict):
        raise ValueError("GENERATION_IPC_FRAME_INVALID")
    body_size = value.pop("bodyBytes", 0)
    if type(body_size) is not int or not 0 <= body_size <= MAX_BODY_BYTES:
        raise ValueError("GENERATION_IPC_BODY_LIMIT")
    if before_body is not None:
        await before_body(value)
    if body_limit is not None and body_size > body_limit(value):
        raise ValueError("GENERATION_IPC_INFLIGHT_LIMIT")
    value["body"] = await reader.readexactly(body_size) if body_size else b""
    return value


async def write_frame(writer, value, lock, *, body_chunks=None):
    metadata = dict(value)
    body = metadata.pop("body", b"")
    chunks = (body,) if body_chunks is None else body_chunks
    if (body_chunks is not None and body) or any(not isinstance(chunk, bytes) for chunk in chunks):
        raise ValueError("GENERATION_IPC_BODY_LIMIT")
    length = sum(len(chunk) for chunk in chunks)
    if length > MAX_BODY_BYTES:
        raise ValueError("GENERATION_IPC_BODY_LIMIT")
    metadata["bodyBytes"] = length
    encoded = json.dumps(metadata, ensure_ascii=True, separators=(",", ":"), allow_nan=False).encode("ascii")
    if len(encoded) > MAX_METADATA_BYTES:
        raise ValueError("GENERATION_IPC_METADATA_LIMIT")
    async with lock:
        writer.write(struct.pack("!I", len(encoded)))
        writer.write(encoded)
        for chunk in chunks:
            for offset in range(0, len(chunk), 64 * 1024):
                writer.write(chunk[offset:offset + 64 * 1024])
                await writer.drain()
        await writer.drain()


class WorkerChannel:
    def __init__(self, reader, writer, *, renew, before_command, abandon, lease_seconds):
        self.reader, self.writer = reader, writer
        self.renew, self.before_command = renew, before_command
        self.abandon = abandon
        self.lease_seconds = lease_seconds
        self.write_lock = asyncio.Lock()
        self.exchange_lock = asyncio.Lock()
        self.pending = {}
        self.sequence = 0
        self.closed = False
        self.finished = False
        self.reader_task = asyncio.create_task(self._read(), name="generation-worker-heartbeat")

    async def send(self, value):
        if self.closed:
            raise GenerationClaimLost("GENERATION_WORKER_CONNECTION_LOST")
        await write_frame(self.writer, value, self.write_lock)

    async def _read(self):
        async def validate_header(value):
            if value.get("kind") == "heartbeat":
                return
            if value.get("kind") != "response" or type(value.get("id")) is not int:
                raise GenerationClaimLost("GENERATION_WORKER_PROTOCOL_INVALID")
            future = self.pending.get(value["id"])
            if future is None or future.done():
                raise GenerationClaimLost("GENERATION_WORKER_RESPONSE_REPLAY")
        try:
            while True:
                value = await asyncio.wait_for(read_frame(self.reader, before_body=validate_header,
                    body_limit=lambda frame: 0 if frame.get("kind") == "heartbeat" else MAX_BODY_BYTES), self.lease_seconds)
                if value.get("kind") == "heartbeat":
                    if not self.finished:
                        self.renew()
                    await self.send({"kind": "heartbeat_ack"})
                    continue
                if value.get("kind") != "response" or type(value.get("id")) is not int:
                    raise GenerationClaimLost("GENERATION_WORKER_PROTOCOL_INVALID")
                future = self.pending.get(value["id"])
                if future is None or future.done():
                    raise GenerationClaimLost("GENERATION_WORKER_RESPONSE_REPLAY")
                self.renew()
                future.set_result(value)
        except (asyncio.CancelledError, Exception):
            self.closed = True
            try:
                self.abandon()
            finally:
                for future in tuple(self.pending.values()):
                    if not future.done():
                        future.set_exception(GenerationClaimLost("GENERATION_WORKER_CONNECTION_LOST"))

    async def exchange(self, value):
        # One request body and one response body per executor, including callers
        # that gather independent metadata lookups. Heartbeats use write_lock only.
        async with self.exchange_lock:
            if self.closed:
                raise GenerationClaimLost("GENERATION_WORKER_CONNECTION_LOST")
            self.before_command()
            self.sequence += 1
            sequence = self.sequence
            future = asyncio.get_running_loop().create_future()
            self.pending[sequence] = future
            try:
                await self.send({**value, "kind": "request", "id": sequence})
                return await future
            finally:
                self.pending.pop(sequence, None)
                if not future.done():
                    future.cancel()

    async def close(self):
        self.reader_task.cancel()
        try:
            await asyncio.gather(self.reader_task, return_exceptions=True)
        finally:
            self.writer.close()
            with suppress(Exception):
                await self.writer.wait_closed()


class WorkerHTTPTransport(httpx.AsyncBaseTransport):
    """A provider request can execute only on its connected leased worker."""
    def __init__(self, channel):
        self.channel = channel

    async def handle_async_request(self, request):
        body = await request.aread()
        response = await self.channel.exchange({
            "method": request.method, "url": str(request.url),
            "headers": [[key.decode("latin-1"), value.decode("latin-1")] for key, value in request.headers.raw],
            "timeout": request.extensions.get("timeout", {}), "body": body,
        })
        status = response.get("status")
        uncertain = response.get("error") or status == 408 or (type(status) is int and status >= 500)
        if uncertain and request.method not in {"GET", "HEAD"}:
            self.channel.abandon()
            raise GenerationClaimLost("GENERATION_PROVIDER_OPERATION_UNCERTAIN")
        if response.get("error") == "timeout":
            raise httpx.ReadTimeout("Generation provider worker HTTP timeout", request=request)
        if response.get("error"):
            raise httpx.NetworkError("Generation provider worker HTTP transport failed", request=request)
        headers = response.get("headers")
        if type(status) is not int or not 100 <= status <= 599 or not isinstance(headers, list):
            raise GenerationClaimLost("GENERATION_WORKER_RESPONSE_INVALID")
        return httpx.Response(status, headers=headers, content=response["body"], request=request)

    async def aclose(self):
        pass  # The dispatcher owns the stream across the provider's HTTP clients.
