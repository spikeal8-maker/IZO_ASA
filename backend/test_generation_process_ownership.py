"""API startup/Unix ownership, bounded peers and safe local status files."""
from __future__ import annotations

import ast
import asyncio
from contextlib import closing
import json
import os
from pathlib import Path
import stat
import struct
from types import SimpleNamespace
import unittest

from app.generation_worker import GenerationExecutor
from app.integrations import generation_ipc as ipc
from app.services import generation_bootstrap as bootstrap, generation_leases as leases
from app.services import generation_accounting as accounting
from app.services.generation_dispatch import DispatchRuntime, GenerationDispatcher
from test_generation_claims import ClaimDatabase
from test_generation_worker_claims import DatabaseHarness


@unittest.skipUnless(os.name == "posix", "Unix ownership contract requires POSIX; protocol tests run on every platform")
class UnixDispatcherOwnershipTests(ClaimDatabase, unittest.IsolatedAsyncioTestCase):
    def dispatcher(self, path=None):
        harness = DatabaseHarness(self)
        runtime = DispatchRuntime(self.connect, lambda value: SimpleNamespace(**value),
            harness.runtime, {}, accounting.refund_generation_tokens)
        return GenerationDispatcher(path or self.path.parent / "generation.sock", runtime,
                                    lease_seconds=2, database_path=self.path)

    async def test_owned_socket_is_private_and_second_server_cannot_replace_it(self):
        first, second = self.dispatcher(), self.dispatcher()
        try:
            await first.start()
            identity = first.path.stat().st_ino
            self.assertEqual(stat.S_IMODE(first.path.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(first.path.parent.stat().st_mode), 0o700)
            with self.assertRaises(OSError):
                await second.start()
            self.assertEqual(first.path.stat().st_ino, identity)
            self.assertEqual(first.snapshot()["watchdog"], "running")
            self.assertFalse(first.snapshot()["ready"])
        finally:
            await second.close()
            await first.close()
        self.assertFalse(first.path.exists())

    async def test_foreign_file_and_symlink_directory_are_preserved_and_rejected(self):
        dispatcher = self.dispatcher()
        dispatcher.path.write_bytes(b"owned non-socket sentinel")
        try:
            with self.assertRaisesRegex(RuntimeError, "SOCKET_OCCUPIED"):
                await dispatcher.start()
            self.assertEqual(dispatcher.path.read_bytes(), b"owned non-socket sentinel")
        finally:
            await dispatcher.close()
        alias = self.path.parent / "alias"
        alias.symlink_to(self.path.parent, target_is_directory=True)
        other = self.dispatcher(alias / "other.sock")
        with self.assertRaisesRegex(RuntimeError, "DIRECTORY_UNSAFE"):
            await other.start()

    def host(self, shutdown):
        harness = DatabaseHarness(self)
        return SimpleNamespace(os=SimpleNamespace(environ={"IZO_PROCESS_ROLE": "server",
            "IZO_WORKER_SOCKET": str(self.path.parent / "generation.sock")}),
            generation_dispatcher=None, queue=asyncio.Queue(), COMFYUI_MOCK_FALLBACK=False,
            db=self.connect, DB_PATH=self.path, GenerateRequest=SimpleNamespace, jobs={},
            _generation_worker_runtime=harness.runtime, refund_generation_tokens=accounting.refund_generation_tokens,
            shutdown=shutdown)

    async def test_second_server_is_rejected_before_startup_body_or_database_write(self):
        calls = []
        async def shutdown():
            calls.append("shutdown")
        first, second = self.host(shutdown), self.host(shutdown)
        try:
            async with bootstrap.prepared_api(first):
                calls.append("first-init-db")
                self.assertIsNone(first.generation_dispatcher.server)
            with self.assertRaises(OSError):
                async with bootstrap.prepared_api(second):
                    calls.append("second-init-db")
            self.assertEqual(calls, ["first-init-db"])
            tree = ast.parse(Path(__file__).with_name("main.py").read_text(encoding="utf-8"))
            startup = next(node for node in tree.body if isinstance(node, ast.AsyncFunctionDef) and node.name == "startup")
            boundary = next(node for node in startup.body if not isinstance(node, ast.Global))
            self.assertIsInstance(boundary, ast.AsyncWith)
            self.assertEqual(ast.unparse(boundary.items[0].context_expr),
                             "generation_bootstrap.prepared_api(sys.modules[__name__])")
            self.assertIn("init_db()", ast.unparse(boundary))
        finally:
            await bootstrap.stop(first)
            await bootstrap.stop(second)

    async def test_startup_failure_releases_owned_lock_for_clean_next_start(self):
        calls = []
        async def shutdown():
            calls.append("shutdown")
        failed, successor = self.host(shutdown), self.host(shutdown)
        try:
            with self.assertRaisesRegex(RuntimeError, "owned startup failure"):
                async with bootstrap.prepared_api(failed):
                    raise RuntimeError("owned startup failure")
            self.assertIsNone(failed.generation_dispatcher)
            self.assertEqual(calls, ["shutdown"])
            async with bootstrap.prepared_api(successor):
                self.assertIsNotNone(successor.generation_dispatcher.lock_file)
        finally:
            await bootstrap.stop(failed)
            await bootstrap.stop(successor)

    async def test_same_database_with_different_socket_directory_cannot_enter_startup_or_refund(self):
        self.seed(charge=7)
        entered = []
        async def shutdown():
            entered.append("shutdown")
        first, second = self.host(shutdown), self.host(shutdown)
        second.os.environ["IZO_WORKER_SOCKET"] = str(self.path.parent / "other-ipc" / "generation.sock")
        try:
            async with bootstrap.prepared_api(first):
                leases.claim_next(self.connect, "a" * 32)
            before = self.state()
            with self.assertRaises(OSError):
                async with bootstrap.prepared_api(second):
                    entered.append("init-or-recovery")
            self.assertEqual(entered, [])
            self.assertEqual(self.state(), before)
            self.assertEqual(self.counts()["token_ledger"], 1)
            with closing(self.open()) as conn:
                self.assertEqual(conn.execute("SELECT token_balance FROM users WHERE id='user_1'").fetchone()[0], 93)
        finally:
            await bootstrap.stop(first)
            await bootstrap.stop(second)

    async def test_symlink_alias_of_database_uses_same_owner_identity(self):
        first = self.dispatcher()
        alias = self.path.parent / "alias.sqlite3"
        alias.symlink_to(self.path)
        second = GenerationDispatcher(self.path.parent / "other-ipc" / "generation.sock", first.runtime,
                                      database_path=alias)
        try:
            await first.prepare()
            with self.assertRaises(OSError):
                await second.prepare()
            self.assertIsNotNone(first.database_lock)
            self.assertIsNone(second.database_lock)
        finally:
            await first.close()
            await second.close()

    async def test_combined_and_server_roles_exclude_each_other_before_database_mutation(self):
        self.seed(charge=7)
        for first_role, second_role in (("combined", "server"), ("server", "combined"), ("combined", "combined")):
            with self.subTest(first=first_role, second=second_role):
                entered = []
                async def shutdown():
                    entered.append("shutdown")
                first, second = self.host(shutdown), self.host(shutdown)
                first.os.environ["IZO_PROCESS_ROLE"] = first_role
                second.os.environ["IZO_PROCESS_ROLE"] = second_role
                second.os.environ["IZO_WORKER_SOCKET"] = str(self.path.parent / "other-ipc" / "generation.sock")
                before = self.state()
                try:
                    async with bootstrap.prepared_api(first):
                        if first_role == "combined":
                            self.assertIsNone(first.generation_dispatcher)
                            self.assertIsInstance(first.queue, asyncio.Queue)
                            self.assertIsNotNone(first.generation_database_owner)
                    with self.assertRaises(OSError):
                        async with bootstrap.prepared_api(second):
                            entered.append("second-init-or-recovery")
                    self.assertEqual(entered, [])
                    self.assertEqual(self.state(), before)
                    self.assertEqual(self.counts()["token_ledger"], 1)
                    self.assertFalse((self.path.parent / "other-ipc").exists())
                finally:
                    await bootstrap.stop(first)
                    await bootstrap.stop(second)

    async def test_combined_startup_failure_releases_its_database_owner_without_creating_ipc(self):
        async def shutdown():
            pass
        failed, successor = self.host(shutdown), self.host(shutdown)
        failed.os.environ["IZO_PROCESS_ROLE"] = "combined"
        with self.assertRaisesRegex(RuntimeError, "combined startup failure"):
            async with bootstrap.prepared_api(failed):
                raise RuntimeError("combined startup failure")
        self.assertIsNone(failed.generation_database_owner)
        self.assertIsNone(failed.generation_dispatcher)
        self.assertFalse((self.path.parent / "generation.sock").exists())
        try:
            async with bootstrap.prepared_api(successor):
                self.assertIsNotNone(successor.generation_dispatcher.database_lock)
        finally:
            await bootstrap.stop(successor)

    async def test_combined_cancelled_shutdown_drains_consumer_before_database_handoff(self):
        entered, cancelled, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
        async def shutdown():
            pass
        host, contender = self.host(shutdown), self.host(shutdown)
        host.os.environ["IZO_PROCESS_ROLE"] = "combined"
        host.asyncio, host.worker_started = asyncio, False
        async def consumer():
            entered.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                await release.wait()
                with closing(self.open()) as conn, conn:
                    conn.execute("UPDATE users SET daily_tokens_used=6 WHERE id='user_2'")
                raise
        host.worker = consumer
        closing_task = None
        try:
            async with bootstrap.prepared_api(host):
                host.worker_started = await bootstrap.start(host)
            await asyncio.wait_for(entered.wait(), 1)
            self.assertIsNone(host.generation_dispatcher)
            self.assertIsNotNone(host.generation_consumer_task)
            closing_task = asyncio.create_task(bootstrap.stop(host))
            await asyncio.wait_for(cancelled.wait(), 1)
            closing_task.cancel()
            with self.assertRaises(OSError):
                async with bootstrap.prepared_api(contender):
                    self.fail("contender entered before the consumer's final database write")
            self.assertFalse(closing_task.done())
        finally:
            release.set()
            if closing_task is not None:
                result = await asyncio.gather(closing_task, return_exceptions=True)
            await bootstrap.stop(host)
            await bootstrap.stop(contender)
        self.assertIsInstance(result[0], asyncio.CancelledError)
        self.assertFalse(host.worker_started)
        self.assertIsNone(host.generation_consumer_task)
        self.assertIsNone(host.generation_database_owner)
        with closing(self.open()) as conn:
            self.assertEqual(conn.execute("SELECT daily_tokens_used FROM users WHERE id='user_2'").fetchone()[0], 6)
        successor = self.host(shutdown)
        try:
            async with bootstrap.prepared_api(successor):
                self.assertIsNotNone(successor.generation_dispatcher.database_lock)
        finally:
            await bootstrap.stop(successor)

    async def test_worker_status_replaces_symlink_without_truncating_its_target(self):
        sentinel = self.path.parent / "owned-sentinel"
        sentinel.write_bytes(b"must remain intact")
        status = self.path.parent / "worker-status.json"
        status.symlink_to(sentinel)
        predictable = self.path.parent / "worker-status.json.tmp"
        predictable.symlink_to(sentinel)
        GenerationExecutor("unused-owned-socket", status_path=status)
        self.assertEqual(sentinel.read_bytes(), b"must remain intact")
        self.assertFalse(status.is_symlink())
        self.assertTrue(predictable.is_symlink())
        self.assertEqual(stat.S_IMODE(status.stat().st_mode), 0o600)
        self.assertEqual(json.loads(status.read_text())["role"], "worker")

    async def test_preclaim_body_and_excess_pending_connections_cannot_claim_or_allocate_body(self):
        from app.services.generation_dispatch import MAX_HANDLERS
        self.seed()
        dispatcher = self.dispatcher()
        writers = []
        try:
            await dispatcher.start()
            reader, writer = await asyncio.open_unix_connection(dispatcher.path)
            writers.append(writer)
            encoded = json.dumps({"kind": "claim", "version": 1, "workerId": "a" * 32,
                                  "bodyBytes": ipc.MAX_BODY_BYTES}).encode()
            writer.write(struct.pack("!I", len(encoded)) + encoded)
            await writer.drain()
            self.assertEqual(await asyncio.wait_for(reader.read(1), 1), b"")
            for _index in range(MAX_HANDLERS):
                _reader, writer = await asyncio.open_unix_connection(dispatcher.path)
                writers.append(writer)
            async def all_pending():
                while len(dispatcher.handlers) != MAX_HANDLERS:
                    await asyncio.sleep(.01)
            await asyncio.wait_for(all_pending(), 1)
            rejected, writer = await asyncio.open_unix_connection(dispatcher.path)
            writers.append(writer)
            self.assertEqual(await asyncio.wait_for(rejected.read(1), 1), b"")
            self.assertEqual(self.state()["status"], "queued")
            self.assertNotIn("_workerClaim", json.loads(self.state()["settings_json"]))
            self.assertEqual(dispatcher.snapshot()["onlineWorkers"], 0)
        finally:
            for writer in writers:
                writer.close()
            await asyncio.gather(*(writer.wait_closed() for writer in writers), return_exceptions=True)
            await dispatcher.close()

    async def test_online_worker_count_prunes_expiry_and_bounds_distinct_id_tracking(self):
        from app.services.generation_dispatch import MAX_RECENT_WORKERS
        dispatcher = self.dispatcher()
        for index in range(MAX_RECENT_WORKERS + 10):
            dispatcher._seen_worker(f"{index:032x}")
        self.assertEqual(len(dispatcher.recent_workers), MAX_RECENT_WORKERS)
        self.assertEqual(dispatcher.snapshot()["onlineWorkers"], MAX_RECENT_WORKERS)
        dispatcher.recent_workers = {worker: 0 for worker in dispatcher.recent_workers}
        self.assertEqual(dispatcher.snapshot()["onlineWorkers"], 0)
        dispatcher._prune_workers()
        self.assertEqual(dispatcher.recent_workers, {})



if __name__ == "__main__":
    unittest.main()
