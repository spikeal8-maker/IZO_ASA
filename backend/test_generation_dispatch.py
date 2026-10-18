"""Role exclusion, private protocol fencing and Unix ownership lifecycle."""
from __future__ import annotations

import asyncio
import gzip
import json
from pathlib import Path
import struct
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import httpx

from app.generation_worker import GenerationExecutor
from app.integrations import generation_ipc as ipc, generation_transport as transport
from app.services import generation_bootstrap as bootstrap, generation_leases as leases
from app.services import generation_queue as queue_service
from app.services.generation_worker import GenerationClaimLost


class BufferWriter:
    def __init__(self):
        self.data = bytearray()
        self.closed = False

    def write(self, data):
        self.data.extend(data)

    async def drain(self):
        pass

    def close(self):
        self.closed = True

    async def wait_closed(self):
        pass


async def feed(reader, value):
    writer = BufferWriter()
    await ipc.write_frame(writer, value, asyncio.Lock())
    reader.feed_data(bytes(writer.data))


class RoleAndProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_server_neither_starts_nor_allows_local_queue_consumer(self):
        calls = []
        class Dispatcher:
            async def start(self):
                calls.append("private-dispatch")
        host = SimpleNamespace(os=SimpleNamespace(environ={"IZO_PROCESS_ROLE": "server"}),
            COMFYUI_MOCK_FALLBACK=False, db=lambda: self.fail("configuration must not open SQLite"),
            queue=asyncio.Queue(), generation_dispatcher=Dispatcher(), worker_started=False,
            asyncio=SimpleNamespace(create_task=lambda value: self.fail("local consumer started")))
        bootstrap.configure_api(host)
        self.assertIsInstance(host.queue, leases.DurableWakeQueue)
        self.assertFalse(await bootstrap.start(host))
        with self.assertRaisesRegex(RuntimeError, "BACKEND_CONSUMER_FORBIDDEN"):
            await host.queue.get()
        runtime = queue_service.GenerationQueueRuntime(queue=host.queue, jobs={},
            parse_request=lambda _: None, perf_counter=lambda: 0,
            build_worker_runtime=lambda: None, process_job=lambda *_: None, allow_consume=False)
        with self.assertRaisesRegex(RuntimeError, "BACKEND_CONSUMER_FORBIDDEN"):
            await queue_service.consume_generation_queue(runtime)
        self.assertEqual(calls, ["private-dispatch"])

    async def test_legacy_role_starts_once_and_worker_entrypoint_is_rejected_by_api(self):
        calls = []
        host = SimpleNamespace(os=SimpleNamespace(environ={}), worker_started=False,
            asyncio=SimpleNamespace(create_task=calls.append), worker=lambda: "consumer")
        host.worker_started = await bootstrap.start(host)
        host.worker_started = await bootstrap.start(host)
        self.assertEqual(calls, ["consumer"])
        host.os.environ["IZO_PROCESS_ROLE"] = "worker"
        with self.assertRaisesRegex(RuntimeError, "WORKER_MUST_USE_EXECUTOR_ENTRYPOINT"):
            bootstrap.configure_api(host)
        main = Path(__file__).with_name("main.py").read_text(encoding="utf-8")
        self.assertLess(main.index("generation_bootstrap.api_role(os.environ)"), main.index("MEDIA.mkdir("))
        host.os.environ["IZO_PROCESS_ROLE"] = "server"
        host.COMFYUI_MOCK_FALLBACK = True
        with self.assertRaisesRegex(RuntimeError, "MOCK_FALLBACK_FORBIDDEN"):
            bootstrap.configure_api(host)

    async def test_provider_guard_and_transport_are_task_local_and_cannot_be_overridden(self):
        environment = {"IZO_PROCESS_ROLE": "server"}
        with self.assertRaisesRegex(RuntimeError, "EXECUTOR_REQUIRED"):
            bootstrap.require_executor(environment)
        remote, other = object(), object()
        with transport.bind(remote):
            bootstrap.require_executor(environment)
            options = transport.client_options({"timeout": 5})
            self.assertIs(options["transport"], remote)
            self.assertFalse(options["trust_env"])
            with self.assertRaisesRegex(RuntimeError, "OVERRIDE_FORBIDDEN"):
                transport.client_options({}, other)
        self.assertFalse(transport.executor_bound())
        self.assertEqual(transport.client_options({"timeout": 5}), {"timeout": 5})
        bootstrap.require_executor({})

    async def test_frames_roundtrip_binary_and_reject_lengths_before_reading_body(self):
        reader = asyncio.StreamReader()
        await feed(reader, {"kind": "owned", "body": bytes(range(256)) * 1024})
        value = await ipc.read_frame(reader)
        self.assertEqual(value["body"], bytes(range(256)) * 1024)
        for size in (0, ipc.MAX_METADATA_BYTES + 1):
            reader = asyncio.StreamReader()
            reader.feed_data(struct.pack("!I", size))
            with self.assertRaisesRegex(ValueError, "METADATA_LIMIT"):
                await asyncio.wait_for(ipc.read_frame(reader), 1)
        for size in (-1, ipc.MAX_BODY_BYTES + 1, True):
            reader = asyncio.StreamReader()
            metadata = json.dumps({"bodyBytes": size}).encode()
            reader.feed_data(struct.pack("!I", len(metadata)) + metadata)
            with self.assertRaisesRegex(ValueError, "BODY_LIMIT"):
                await asyncio.wait_for(ipc.read_frame(reader), 1)
        reader = asyncio.StreamReader()
        metadata = json.dumps({"bodyBytes": 1}).encode()
        reader.feed_data(struct.pack("!I", len(metadata)) + metadata)
        with self.assertRaisesRegex(ValueError, "INFLIGHT_LIMIT"):
            await asyncio.wait_for(ipc.read_frame(reader, body_limit=lambda _value: 0), 1)

    async def test_concurrent_provider_calls_are_serialized_while_heartbeats_continue(self):
        reader, writer, calls = asyncio.StreamReader(), BufferWriter(), []
        channel = ipc.WorkerChannel(reader, writer, renew=lambda: calls.append("renew"),
            before_command=lambda: calls.append("dispatch"), abandon=lambda: None, lease_seconds=1)
        first = asyncio.create_task(channel.exchange({"method": "GET"}))
        second = asyncio.create_task(channel.exchange({"method": "GET"}))
        try:
            await asyncio.sleep(0)
            self.assertEqual(calls, ["dispatch"])
            await feed(reader, {"kind": "heartbeat"})
            await feed(reader, {"kind": "response", "id": 1, "status": 200, "headers": []})
            await asyncio.wait_for(first, 1)
            for _turn in range(4):
                await asyncio.sleep(0)
            self.assertEqual(calls.count("dispatch"), 2)
            self.assertGreaterEqual(calls.count("renew"), 2)
            await feed(reader, {"kind": "response", "id": 2, "status": 200, "headers": []})
            await asyncio.wait_for(second, 1)
        finally:
            await channel.close()
            await asyncio.gather(first, second, return_exceptions=True)

    async def test_duplicate_response_closes_channel_and_fences_pending_commands(self):
        reader, writer, calls = asyncio.StreamReader(), BufferWriter(), []
        channel = ipc.WorkerChannel(reader, writer, renew=lambda: calls.append("renew"),
            before_command=lambda: calls.append("dispatch"), abandon=lambda: calls.append("lost"), lease_seconds=1)
        task = asyncio.create_task(channel.exchange({"method": "GET"}))
        try:
            await asyncio.sleep(0)
            await feed(reader, {"kind": "response", "id": 1, "status": 200, "headers": []})
            await asyncio.wait_for(task, 1)
            await feed(reader, {"kind": "response", "id": 1, "status": 200, "headers": []})
            await asyncio.wait_for(channel.reader_task, 1)
            self.assertTrue(channel.closed)
            with self.assertRaises(GenerationClaimLost):
                await channel.exchange({"method": "POST"})
            self.assertEqual(calls.count("dispatch"), 1)
            self.assertEqual(calls.count("lost"), 1)
        finally:
            await channel.close()

    async def test_lost_stream_resolves_waiter_even_if_lease_storage_is_unavailable(self):
        reader, writer = asyncio.StreamReader(), BufferWriter()
        def unavailable():
            raise OSError("owned SQLite unavailable")
        channel = ipc.WorkerChannel(reader, writer, renew=lambda: None,
            before_command=lambda: None, abandon=unavailable, lease_seconds=1)
        task = asyncio.create_task(channel.exchange({"method": "POST"}))
        try:
            await asyncio.sleep(0)
            reader.feed_eof()
            with self.assertRaises(GenerationClaimLost):
                await asyncio.wait_for(task, 1)
        finally:
            await channel.close()
        self.assertTrue(writer.closed)
        self.assertEqual(channel.pending, {})

    async def test_unmatched_response_and_heartbeat_body_are_rejected_from_metadata_alone(self):
        for value in ({"kind": "response", "id": 999, "bodyBytes": ipc.MAX_BODY_BYTES},
                      {"kind": "heartbeat", "bodyBytes": ipc.MAX_BODY_BYTES}):
            reader, writer, revoked = asyncio.StreamReader(), BufferWriter(), []
            channel = ipc.WorkerChannel(reader, writer, renew=lambda: None,
                before_command=lambda: None, abandon=lambda: revoked.append(True), lease_seconds=3)
            encoded = json.dumps(value).encode()
            reader.feed_data(struct.pack("!I", len(encoded)) + encoded)
            try:
                await asyncio.wait_for(channel.reader_task, 1)
                self.assertTrue(channel.closed)
                self.assertEqual(revoked, [True])
            finally:
                await channel.close()

    async def test_mutation_timeout_or_server_failure_never_becomes_retryable_http_error(self):
        class Channel:
            def __init__(self, reply):
                self.reply, self.revoked, self.calls = reply, False, 0
            async def exchange(self, _value):
                self.calls += 1
                return self.reply
            def abandon(self):
                self.revoked = True
        for reply in ({"error": "timeout"}, {"error": "transport"},
                      {"status": 503, "headers": [], "body": b""},
                      {"status": 408, "headers": [], "body": b""}):
            channel = Channel(reply)
            async with httpx.AsyncClient(transport=ipc.WorkerHTTPTransport(channel)) as client:
                with self.assertRaisesRegex(GenerationClaimLost, "OPERATION_UNCERTAIN"):
                    await client.post("http://controlled.invalid/prompt")
            self.assertTrue(channel.revoked)
            self.assertEqual(channel.calls, 1)
        channel = Channel({"error": "timeout"})
        async with httpx.AsyncClient(transport=ipc.WorkerHTTPTransport(channel)) as client:
            with self.assertRaises(httpx.ReadTimeout):
                await client.get("http://controlled.invalid/history")
        self.assertFalse(channel.revoked)

    async def test_wire_response_decompresses_once_and_size_rejection_remains_explicit(self):
        body = b"owned image bytes" * 100
        class Channel:
            async def exchange(self, _value):
                return {"status": 200, "headers": [["content-encoding", "gzip"]],
                        "body": gzip.compress(body)}
        async with httpx.AsyncClient(transport=ipc.WorkerHTTPTransport(Channel())) as client:
            result = await client.get("http://controlled.invalid/view")
        self.assertEqual(result.content, body)

    async def test_oversized_executor_response_reports_bounded_failure_without_body_or_headers(self):
        class LargeReply(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield b"controlled response exceeds bound"
        executor, writer = GenerationExecutor("unused"), BufferWriter()
        value = {"kind": "request", "id": 1, "method": "POST", "url": "http://controlled.invalid/prompt",
                 "headers": [], "body": b"{}", "timeout": {}}
        provider = httpx.MockTransport(lambda request: httpx.Response(200,
            headers={"X-Provider-Detail": "must not be echoed"}, stream=LargeReply()))
        with patch("app.generation_worker.MAX_BODY_BYTES", 16):
            async with httpx.AsyncClient(transport=provider) as client:
                await executor._request(value, writer, asyncio.Lock(), client)
        reader = asyncio.StreamReader()
        reader.feed_data(bytes(writer.data))
        result = await ipc.read_frame(reader)
        self.assertEqual(result, {"kind": "response", "id": 1, "error": "transport", "body": b""})
        self.assertEqual(executor.state["httpRequests"], 1)
        self.assertEqual(executor.state["httpResponses"], 0)
        self.assertEqual(executor.state["httpFailures"], 1)
        self.assertIsNotNone(executor.state["lastFailureAt"])

    async def test_chunked_response_keeps_wire_shape_and_rejects_oversize_before_writing(self):
        writer, reader = BufferWriter(), asyncio.StreamReader()
        await ipc.write_frame(writer, {"kind": "response"}, asyncio.Lock(), body_chunks=[b"owned", b" result"])
        reader.feed_data(bytes(writer.data))
        self.assertEqual((await ipc.read_frame(reader))["body"], b"owned result")
        rejected = BufferWriter()
        with patch.object(ipc, "MAX_BODY_BYTES", 16):
            with self.assertRaisesRegex(ValueError, "BODY_LIMIT"):
                await ipc.write_frame(rejected, {"kind": "response"}, asyncio.Lock(), body_chunks=[b"x" * 10, b"y" * 10])
        self.assertEqual(rejected.data, b"")

    async def test_readiness_requires_recent_worker_and_live_watchdog_in_server_role(self):
        host = SimpleNamespace(os=SimpleNamespace(environ={}), generation_dispatcher=None)
        self.assertTrue(bootstrap.worker_ready(host))
        host.os.environ["IZO_PROCESS_ROLE"] = "server"
        self.assertFalse(bootstrap.worker_ready(host))
        host.generation_dispatcher = SimpleNamespace(snapshot=lambda: {"ready": False})
        self.assertFalse(bootstrap.worker_ready(host))
        host.generation_dispatcher = SimpleNamespace(snapshot=lambda: {"ready": True})
        self.assertTrue(bootstrap.worker_ready(host))


if __name__ == "__main__":
    unittest.main()
