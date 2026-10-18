"""Real executor processes, private streams and a held loopback HTTP provider.

POSIX exercises the production Unix listener. Windows uses a test-only loopback
stream listener for the same handler/protocol, without claiming Unix support.
No provider, application DB, media or credentials outside this fixture is used.
"""
from __future__ import annotations

import asyncio
from contextlib import closing, suppress
from dataclasses import replace
import json
import os
from pathlib import Path
import signal
import sys
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import uuid

import httpx

from app.generation_worker import healthy
from app.integrations.comfyui_client import submit_comfyui_workflow
from app.services import generation_accounting as accounting
from app.services import generation_bootstrap as bootstrap
from app.services.generation_dispatch import DispatchRuntime, GenerationDispatcher
from app.services.generation_worker_persistence import cancel_job
from test_generation_claims import ClaimDatabase, NOW
from test_generation_worker_claims import DatabaseHarness
from test_generation_worker_status_support import status_file_lock


CHILD = """
import asyncio, json, sys
from pathlib import Path
from app.generation_worker import GenerationExecutor
from test_generation_worker_status_support import status_file_lock
assert 'main' not in sys.modules and 'sqlite3' not in sys.modules
Path(sys.argv[2] + '.imports.json').write_text(json.dumps({'main': False, 'sqlite3': False}))
class WindowsFixtureExecutor(GenerationExecutor):
    def _save(self, **updates):
        with status_file_lock(self.status_path):
            super()._save(**updates)
async def run():
    connector = None if sys.argv[1] == 'unix' else lambda: asyncio.open_connection('127.0.0.1', int(sys.argv[3]))
    executor_type = WindowsFixtureExecutor if sys.platform == 'win32' else GenerationExecutor
    executor = executor_type(sys.argv[3], status_path=sys.argv[2], connect=connector)
    await executor.run()
asyncio.run(run())
"""


class ExecutorProcessTests(ClaimDatabase, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.children, self.provider_tasks, self.requests = [], set(), []
        self.release, self.drop = {}, set()
        self.harness = DatabaseHarness(self)
        self.provider = await asyncio.start_server(self.serve_provider, "127.0.0.1", 0)
        port = self.provider.sockets[0].getsockname()[1]
        async def send(payload, job):
            response = await submit_comfyui_workflow(base_url=f"http://127.0.0.1:{port}",
                workflow={"owned_prompt": payload.prompt}, job_id=job["id"], timeout_seconds=10)
            self.assertEqual(response["prompt_id"], "controlled-prompt")
            return self.harness.comfy_result
        def make_runtime():
            return replace(self.harness.runtime(), send_to_comfyui=send,
                           new_image_id=lambda: "image_" + uuid.uuid4().hex)
        self.dispatcher = GenerationDispatcher(self.path.parent / "generation.sock",
            DispatchRuntime(self.connect, lambda value: SimpleNamespace(**value), make_runtime,
                            {}, accounting.refund_generation_tokens), lease_seconds=3, database_path=self.path)
        if os.name == "posix":
            await self.dispatcher.start()
            self.transport_kind, self.address = "unix", str(self.dispatcher.path)
        else:
            self.dispatcher.server = await asyncio.start_server(self.dispatcher._handle, "127.0.0.1", 0)
            self.dispatcher.watchdog = asyncio.create_task(self.dispatcher._watch())
            self.transport_kind = "tcp"
            self.address = str(self.dispatcher.server.sockets[0].getsockname()[1])

    async def asyncTearDown(self):
        for event in self.release.values():
            event.set()
        for process, _status in self.children:
            if process.returncode is None:
                process.kill()
            await process.communicate()
        await self.dispatcher.close()
        self.provider.close()
        await self.provider.wait_closed()
        for task in tuple(self.provider_tasks):
            task.cancel()
        await asyncio.gather(*tuple(self.provider_tasks), return_exceptions=True)

    async def until(self, predicate, *, seconds=8):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if predicate():
                return
            for process, _status in self.children:
                if process.returncode not in (None, 0) and not getattr(process, "expected_kill", False):
                    _out, error = await process.communicate()
                    self.fail(f"owned worker exited {process.returncode}: {error.decode(errors='replace')[:500]}")
            await asyncio.sleep(0.02)
        self.fail("owned fixture condition did not converge")

    def status(self, path):
        try:
            with status_file_lock(path):
                return json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError):
            return {}

    def worker_healthy(self, path):
        with status_file_lock(path):
            return healthy(path)

    async def start_worker(self):
        status = self.path.parent / f"worker-{len(self.children)}.json"
        environment = dict(os.environ)
        environment["IZO_PROCESS_ROLE"] = "worker"
        dependencies = [value for value in sys.path if Path(value).name.lower() in {"site-packages", "dist-packages"}]
        environment["PYTHONPATH"] = os.pathsep.join(filter(None,
            (str(Path(__file__).parent), *dependencies, environment.get("PYTHONPATH"))))
        executable = sys._base_executable if os.name == "nt" else sys.executable
        process = await asyncio.create_subprocess_exec(executable, "-c", CHILD,
            self.transport_kind, str(status), self.address, cwd=Path(__file__).parent,
            env=environment, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        self.children.append((process, status))
        await self.until(lambda: self.status(status).get("state") in {"idle", "working"})
        self.assertNotEqual(process.pid, os.getpid())
        self.assertEqual(self.status(status)["pid"], process.pid)
        self.assertEqual(json.loads(Path(str(status) + ".imports.json").read_text()), {"main": False, "sqlite3": False})
        return process, status

    async def kill_worker(self, process):
        process.expected_kill = True
        process.kill()
        await process.communicate()

    async def serve_provider(self, reader, writer):
        task = asyncio.current_task()
        self.provider_tasks.add(task)
        try:
            header = await reader.readuntil(b"\r\n\r\n")
            first, *lines = header.decode("latin-1").split("\r\n")
            headers = {key.lower(): value.strip() for line in lines if ":" in line
                       for key, value in [line.split(":", 1)]}
            body = await reader.readexactly(int(headers.get("content-length", 0)))
            value = json.loads(body)
            job_id = value["client_id"].removeprefix("onenode-backend-")
            self.requests.append({"job": job_id, "request": first, "body": value})
            self.release.setdefault(job_id, asyncio.Event())
            if job_id in self.drop:
                return
            await self.release[job_id].wait()
            response = json.dumps({"prompt_id": "controlled-prompt"}).encode()
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nConnection: close\r\n" +
                         f"Content-Length: {len(response)}\r\n\r\n".encode() + response)
            await writer.drain()
        except (ConnectionError, asyncio.IncompleteReadError):
            pass
        finally:
            writer.close()
            with suppress(Exception):
                await writer.wait_closed()
            self.provider_tasks.discard(task)

    def metadata(self, job_id="job_1"):
        return json.loads(self.state(job_id)["settings_json"])["_workerClaim"]

    def assert_refund_once(self, job_id="job_1", *, reason="worker_lease_expired"):
        with closing(self.open()) as conn:
            refunds = [json.loads(row[0]) for row in conn.execute(
                "SELECT meta_json FROM token_ledger WHERE reason='generation_refund'")]
            owned = [value for value in refunds if value["jobId"] == job_id]
            self.assertEqual([value["reason"] for value in owned], [reason])

    async def cancel(self, job_id, user_id, interrupt):
        return await cancel_job(job_id, user_id, connect=self.connect,
            jobs=self.dispatcher.runtime.jobs, persist_job=self.persist,
            refund=accounting.refund_generation_tokens, read_job=self.read_job,
            interrupt=interrupt, now_iso=NOW, admission_lock=self.dispatcher.admission_lock)

    async def test_two_real_workers_issue_one_submit_and_reconstruct_uncached_durable_work(self):
        self.seed(charge=7)
        self.assertEqual(self.dispatcher.runtime.jobs, {})
        await asyncio.sleep(0.05)
        self.assertEqual(self.state()["status"], "queued")
        self.assertEqual(self.requests, [])
        # Parent HTTP is forbidden; only the independently imported executors can submit.
        with patch.object(httpx.AsyncHTTPTransport, "handle_async_request", side_effect=AssertionError("server HTTP bypass")):
            first, first_status = await self.start_worker()
            second, second_status = await self.start_worker()
            await self.until(lambda: len(self.requests) == 1)
            owner = self.metadata()["workerId"]
            states = [self.status(path) for path in (first_status, second_status)]
            self.assertEqual(sum(value["workerId"] == owner for value in states), 1)
            self.assertEqual(sum(value["httpRequests"] for value in states), 1)
            self.assertNotEqual(first.pid, second.pid)
            self.assertEqual(self.metadata()["providerCommands"], 1)
            with closing(self.open()) as conn, conn:
                conn.execute("UPDATE users SET daily_tokens_used=1 WHERE id='user_2'")
            await asyncio.sleep(0.1)
            self.assertEqual(len(self.requests), 1)
            self.assertEqual(self.requests[0]["body"]["prompt"], {"owned_prompt": "owned"})
            self.release["job_1"].set()
            await self.until(lambda: self.state()["status"] == "completed")
        self.assertEqual(self.counts(), {"images": 1, "image_sources": 1, "token_ledger": 1})
        self.assertEqual(len(self.harness.cache), 1)
        await self.until(lambda: self.dispatcher.snapshot()["lastSuccessAt"] is not None)
        self.assertTrue(self.dispatcher.snapshot()["ready"])
        self.assertEqual(self.dispatcher.snapshot()["onlineWorkers"], 2)
        for path in (first_status, second_status):
            self.assertTrue(self.worker_healthy(path))
            report = self.status(path)
            self.assertFalse({"token", "url", "headers", "body", "apiKey"} & report.keys())

    async def test_killed_executing_worker_refunds_once_and_restart_cannot_accept_late_result(self):
        self.seed(charge=7)
        await self.start_worker()
        await self.start_worker()
        await self.until(lambda: len(self.requests) == 1)
        owner = self.metadata()["workerId"]
        executing = next(process for process, status in self.children if self.status(status)["workerId"] == owner)
        await self.kill_worker(executing)
        await self.until(lambda: self.state()["status"] == "failed")
        self.assertEqual(self.metadata()["lossReason"], "worker_connection_lost")
        self.assert_refund_once()
        self.release["job_1"].set()  # Provider finishes after the durable fence is terminal.
        restarted, status = await self.start_worker()
        self.assertNotEqual(self.status(status)["workerId"], owner)
        self.assertNotEqual(restarted.pid, executing.pid)
        await asyncio.sleep(1.1)
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(self.state()["status"], "failed")
        self.assertIsNone(self.state()["result_image_id"])
        self.assertEqual(self.counts(), {"images": 0, "image_sources": 0, "token_ledger": 2})
        self.assertEqual(self.harness.cache, {})
        self.assertGreaterEqual(self.dispatcher.snapshot()["expiredLeases"], 1)
        self.assert_refund_once()

    async def test_uncertain_submit_disconnect_is_terminal_and_never_retried_by_peer(self):
        self.seed(charge=7)
        self.drop.add("job_1")
        await self.start_worker()
        await self.start_worker()
        await self.until(lambda: self.state()["status"] == "failed")
        await asyncio.sleep(1.1)
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(self.metadata()["providerCommands"], 1)
        self.assert_refund_once()
        self.assertEqual(self.counts()["images"], 0)

    @unittest.skipUnless(os.name == "posix", "Heartbeat-loss injection uses POSIX SIGSTOP/SIGCONT")
    async def test_stopped_worker_expires_by_heartbeat_and_resumed_late_response_is_fenced(self):
        self.seed(charge=7)
        process, status = await self.start_worker()
        await self.until(lambda: len(self.requests) == 1)
        process.send_signal(signal.SIGSTOP)
        try:
            await self.until(lambda: self.state()["status"] == "failed", seconds=6)
            self.assertEqual(self.metadata()["lossReason"], "worker_heartbeat_expired")
            self.assert_refund_once()
            self.release["job_1"].set()
        finally:
            process.send_signal(signal.SIGCONT)
        await self.until(lambda: self.status(status).get("state") == "idle")
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(self.state()["status"], "failed")
        self.assertEqual(self.counts()["images"], 0)
        self.assert_refund_once()

    async def test_active_cancel_blocks_peer_submit_until_interrupt_finishes_without_sqlite_lock(self):
        self.seed("job_a", charge=7)
        await self.start_worker()
        await self.start_worker()
        await self.until(lambda: len(self.requests) == 1)
        self.seed("job_b", "user_2", charge=7)
        entered, finish = asyncio.Event(), asyncio.Event()
        async def interrupt():
            with closing(self.open()) as conn, conn:
                conn.execute("UPDATE users SET daily_tokens_used=1 WHERE id='user_2'")
            entered.set()
            await finish.wait()
        cancel = asyncio.create_task(self.cancel("job_a", "user_1", interrupt))
        try:
            await asyncio.wait_for(entered.wait(), 3)
            self.release["job_a"].set()
            await self.until(lambda: not self.dispatcher.channels)
            await asyncio.sleep(1.1)  # Peer reconnects while interrupt still owns admission.
            self.assertEqual(self.state("job_b")["status"], "queued")
            self.assertEqual([value["job"] for value in self.requests], ["job_a"])
            self.assertGreaterEqual(len(self.dispatcher.handlers), 1)
        finally:
            finish.set()
            response = await asyncio.wait_for(cancel, 3)
        self.assertEqual(response["status"], "cancelled")
        await self.until(lambda: len(self.requests) == 2)
        self.assertEqual(self.requests[1]["job"], "job_b")
        self.release["job_b"].set()
        await self.until(lambda: self.state("job_b")["status"] == "completed")
        self.assertEqual(self.state("job_a")["status"], "cancelled")
        self.assert_refund_once("job_a", reason="user_cancelled")
        self.assertEqual(self.counts()["images"], 1)

    async def test_queued_foreign_cancellation_does_not_interrupt_active_owner(self):
        self.seed("job_a", charge=7)
        await self.start_worker()
        await self.start_worker()
        await self.until(lambda: len(self.requests) == 1)
        self.seed("job_b", "user_2", charge=7)
        interrupted = []
        async def interrupt():
            interrupted.append(True)
        with self.assertRaises(LookupError):
            await self.cancel("job_b", "user_1", interrupt)
        for _repeat in range(2):
            response = await self.cancel("job_b", "user_2", interrupt)
            self.assertEqual(response["status"], "cancelled")
        self.assertEqual(interrupted, [])
        self.assertEqual([value["job"] for value in self.requests], ["job_a"])
        self.release["job_a"].set()
        await self.until(lambda: self.state("job_a")["status"] == "completed")
        self.assertEqual(self.state("job_b")["status"], "cancelled")
        self.assert_refund_once("job_b", reason="user_cancelled")

    async def test_worker_remains_alive_and_reconnects_after_backend_socket_restart(self):
        process, status = await self.start_worker()
        worker_id = self.status(status)["workerId"]
        await self.dispatcher.close()
        await self.until(lambda: self.status(status).get("state") == "reconnecting")
        self.assertIsNone(process.returncode)
        self.assertFalse(self.worker_healthy(status))
        if os.name == "posix":
            self.dispatcher = GenerationDispatcher(self.dispatcher.path, self.dispatcher.runtime,
                                                  lease_seconds=3, database_path=self.path)
            await self.dispatcher.start()
        else:
            previous = self.dispatcher
            self.dispatcher = GenerationDispatcher(previous.path, previous.runtime, lease_seconds=3)
            self.dispatcher.server = await asyncio.start_server(self.dispatcher._handle, "127.0.0.1", int(self.address))
            self.dispatcher.watchdog = asyncio.create_task(self.dispatcher._watch())
        await self.until(lambda: self.worker_healthy(status))
        self.assertEqual(self.status(status)["workerId"], worker_id)
        self.assertEqual(self.status(status)["pid"], process.pid)
        self.assertEqual(self.requests, [])

    async def assert_owner_handoff_blocked(self):
        runtime = replace(self.dispatcher.runtime, drain_storage=None)
        contender = GenerationDispatcher(self.path.parent / "other-ipc" / "generation.sock",
                                         runtime, database_path=self.path)
        try:
            with self.assertRaises(OSError):
                await contender.prepare()
        finally:
            await contender.close()

    async def assert_owner_handoff_released(self):
        successor = GenerationDispatcher(self.path.parent / "other-ipc" / "generation.sock",
            replace(self.dispatcher.runtime, drain_storage=None), database_path=self.path)
        try:
            await successor.prepare()
            self.assertIsNotNone(successor.database_lock)
        finally:
            await successor.close()

    @unittest.skipUnless(os.name == "posix", "Storage-writer handoff requires the production Unix/DB owner locks")
    async def test_completion_optimizer_drains_before_cancelled_close_releases_database_owner(self):
        entered, release, finished = threading.Event(), threading.Event(), threading.Event()
        original = self.harness.optimize
        def optimize(user_id, *, limit):
            entered.set()
            if not release.wait(8):
                raise AssertionError("owned optimizer barrier was not released")
            original(user_id, limit=limit)
            with closing(self.open()) as conn, conn:
                conn.execute("UPDATE users SET daily_tokens_used=9 WHERE id='user_2'")
            finished.set()
        self.harness.storage = replace(self.harness.storage, optimize=optimize)
        closing_task = None
        try:
            self.seed()
            await self.start_worker()
            await self.until(lambda: len(self.requests) == 1)
            self.release["job_1"].set()
            await self.until(entered.is_set)
            closing_task = asyncio.create_task(self.dispatcher.close())
            await self.until(lambda: self.dispatcher.closed)
            closing_task.cancel()
            await self.assert_owner_handoff_blocked()
            self.assertFalse(closing_task.done())
            self.assertFalse(finished.is_set())
        finally:
            release.set()
            if closing_task is not None:
                result = await asyncio.gather(closing_task, return_exceptions=True)
        self.assertIsInstance(result[0], asyncio.CancelledError)
        self.assertTrue(finished.is_set())
        with closing(self.open()) as conn:
            self.assertEqual(conn.execute("SELECT daily_tokens_used FROM users WHERE id='user_2'").fetchone()[0], 9)
        await self.assert_owner_handoff_released()

    @unittest.skipUnless(os.name == "posix", "Startup storage handoff requires the production Unix/DB owner locks")
    async def test_startup_optimizer_drains_before_database_owner_handoff(self):
        entered, release, finished = threading.Event(), threading.Event(), threading.Event()
        def optimize():
            entered.set()
            if not release.wait(8):
                raise AssertionError("owned startup optimizer barrier was not released")
            with closing(self.open()) as conn, conn:
                conn.execute("UPDATE users SET daily_tokens_used=8 WHERE id='user_2'")
            finished.set()
        host = SimpleNamespace(optimize_existing_gallery_storage=optimize)
        self.dispatcher.runtime = replace(self.dispatcher.runtime, drain_storage=lambda: bootstrap._drain_storage(host))
        closing_task = None
        try:
            bootstrap.start_storage_maintenance(host)
            await self.until(entered.is_set)
            closing_task = asyncio.create_task(self.dispatcher.close())
            await self.until(lambda: self.dispatcher.closed)
            await self.assert_owner_handoff_blocked()
            self.assertFalse(closing_task.done())
            self.assertFalse(finished.is_set())
        finally:
            release.set()
            if closing_task is not None:
                await closing_task
        self.assertTrue(finished.is_set())
        self.assertIsNone(host.generation_storage_task)
        await self.assert_owner_handoff_released()


if __name__ == "__main__":
    unittest.main()
