"""Execute the real cancel/refresh functions with SQLite and deferred fake I/O.

This is source-level route characterization, not an ASGI or media-decode proof.
"""
from __future__ import annotations

import __future__
import ast
import asyncio
from collections.abc import Callable, Mapping
from contextlib import closing, contextmanager, nullcontext, suppress
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
import sqlite3
import sys
import tempfile
import threading
import time
from types import ModuleType, SimpleNamespace
from typing import Protocol
import unittest
import uuid


ROOT = Path(__file__).resolve().parent


def definitions(path, *, include=None, bindings=None):
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
    kinds = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Assign, ast.AnnAssign)
    def names(node):
        if hasattr(node, "name"):
            return {node.name}
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        return {target.id for target in targets if isinstance(target, ast.Name)}
    nodes = [node for node in tree.body if isinstance(node, kinds)
             and (include is None or names(node) & set(include))]
    if include is not None and set().union(*(names(node) for node in nodes)) != set(include):
        raise AssertionError("A requested production definition is missing")
    module = ModuleType("_video_cancel_contract_" + uuid.uuid4().hex)
    namespace = module.__dict__
    namespace.update({key: value for key, value in globals().items() if not key.startswith("__")})
    namespace.update({key: value for key, value in (bindings or {}).items() if not key.startswith("__")})
    sys.modules[module.__name__] = module
    try:
        exec(compile(ast.Module(body=nodes, type_ignores=[]), str(ROOT / path), "exec",
                     flags=__future__.annotations.compiler_flag), namespace)
    finally:
        sys.modules.pop(module.__name__, None)
    return SimpleNamespace(**namespace)


class BoundaryError(Exception):
    def __init__(self, status_code, detail):
        super().__init__(detail)
        self.status_code = status_code


class Harness:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.connections, self.routes, self.auth_calls = [], {}, []
        self.downloads, self.interrupts, self.frees = [], 0, 0
        self.entered, self.release = asyncio.Event(), asyncio.Event()
        self.state = {"status": "completed", "output": {"filename": "fixture.mp4"}}
        self.download_entered, self.download_release = asyncio.Event(), asyncio.Event()
        self.download_release.set()
        self.download_error = None
        with self.connect() as conn:
            conn.executescript("""
                CREATE TABLE users (id TEXT PRIMARY KEY, token_balance INTEGER,
                    daily_tokens_used INTEGER, tokens_used INTEGER, generation_count INTEGER);
                CREATE TABLE jobs (id TEXT PRIMARY KEY, user_id TEXT, mode TEXT, provider TEXT,
                    status TEXT, progress INTEGER, prompt_original TEXT, prompt_translated TEXT,
                    result_image_id TEXT, error_message TEXT, settings_json TEXT,
                    created_at TEXT, started_at TEXT, completed_at TEXT);
                CREATE TABLE images (id TEXT, job_id TEXT, user_id TEXT, deleted_at TEXT, created_at TEXT);
                CREATE TABLE token_ledger (id TEXT PRIMARY KEY, user_id TEXT, delta INTEGER,
                    reason TEXT, meta_json TEXT, created_at TEXT);
                CREATE TABLE generation_trial_reservations (job_id TEXT, state TEXT, settled_at TEXT);
                CREATE TABLE videos (id TEXT PRIMARY KEY, user_id TEXT, job_id TEXT UNIQUE,
                    url TEXT, width INTEGER, height INTEGER, duration_seconds INTEGER,
                    aspect_ratio TEXT, mode TEXT, provider TEXT, prompt_original TEXT,
                    settings_json TEXT, stored_bytes INTEGER, created_at TEXT, deleted_at TEXT);
                INSERT INTO users VALUES ('owner',100,10,10,1);
            """)
        self.claims = definitions("app/services/generation_claims.py", bindings={"GenerationClaimLost": RuntimeError})
        accounting = definitions("app/services/generation_accounting.py")
        trial = definitions("app/security/trial_access.py", include={"settle_trial_generation"})
        pricing = definitions("app/services/video_pricing.py", include={"video_size"})
        profiles = definitions("app/services/ltx_video/profiles.py")
        presentation = definitions("app/services/video_presentation.py", bindings={
            **vars(profiles), "video_size": pricing.video_size})
        generation = definitions("app/services/generation_jobs.py", bindings={
            **vars(presentation), "generation_claims": self.claims,
            "settle_trial_generation": trial.settle_trial_generation})
        persistence = definitions("app/services/generation_worker_persistence.py", include={"cancel_job"},
                                  bindings={"generation_claims": self.claims})
        self.storage = definitions("app/services/video_storage.py")
        self.runtime = definitions("main.py", include={"cancel_job", "persist_job",
            "get_persisted_job_response", "_claim_video_finalization", "_release_video_finalization",
            "_refresh_video_job", "_download_video_result"}, bindings={
                "app": SimpleNamespace(post=self.post), "db": self.connect, "jobs": {},
                "require_trusted_user": self.authenticate, "HTTPException": BoundaryError,
                "generation_jobs": generation, "generation_worker_persistence": persistence,
                "generation_dispatcher": None, "refund_generation_tokens": accounting.refund_generation_tokens,
                "interrupt_comfyui_prompt": self.interrupt, "_user_model_name": str,
                "safe_json_load": lambda raw: json.loads(raw or "{}"), "video_storage": self.storage,
                "VIDEO_FINALIZATION_STALE_SECONDS": 600, "truncate_admin_text": lambda value, size: str(value)[:size],
                "ltx_video": SimpleNamespace(ComfyLtxClient=lambda *_: self,
                                             recover_missing_job_state=lambda state, _created: state),
                "LOCAL_LTX_COMFYUI_BASE_URL": "http://unused.invalid", "COMFYUI_TIMEOUT_SECONDS": 1,
                "video_download": SimpleNamespace(download_video=self.download), "MEDIA": self.directory,
                "VIDEO_DOWNLOAD_MAX_BYTES": 1024 * 1024, "openrouter_headers": lambda: {},
                "OPENROUTER_BASE_URL": "http://unused.invalid", "poll_openrouter_video": self.poll,
                "storage_resolve_under_root": lambda root, filename: root / filename,
                "video_pricing": pricing, "video_presentation": presentation,
                "_evict_videos_for_new_result": lambda *_args, **_kwargs: 0,
                "drain_video_file_deletions": lambda **_kwargs: None,
            })

    def connect(self):
        conn = sqlite3.connect(self.directory / "owned.sqlite3", timeout=.2)
        conn.row_factory = sqlite3.Row
        self.connections.append(conn)
        return conn

    def close(self):
        for conn in self.connections:
            conn.close()

    def post(self, route):
        def register(handler):
            self.routes[route] = handler
            return handler
        return register

    def authenticate(self, request):
        self.auth_calls.append(request["session_owner"])
        return {"legacy_user_id": request["session_owner"]}

    async def interrupt(self):
        self.interrupts += 1

    async def status(self, _external_id):
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")  # No SQLite writer may span this await.
        self.entered.set()
        await self.release.wait()
        return self.state.copy()

    async def poll(self, **_kwargs):
        return await self.status("controlled-cloud-prompt")

    def view_url(self, _output):
        return "http://unused.invalid/result"

    async def free_memory(self):
        self.frees += 1

    async def download(self, _url, *, target, temporary, **_kwargs):
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")  # The claim transaction has committed.
        self.downloads.append(target.name)
        sequence = len(self.downloads)
        self.download_entered.set()
        if sequence == 1:
            await self.download_release.wait()
        if self.download_error and sequence == 1:
            raise self.download_error
        if target.parent != self.directory or temporary.parent != self.directory:
            raise AssertionError("Download escaped its owned temporary media")
        target.write_bytes(f"controlled handoff {sequence}; not a video-decode proof".encode())
        return target.stat().st_size, target

    def seed(self, *, job_id="video-owned", mode="text_to_video", provider="local_ltx", status="queued"):
        settings = {"mode": mode, "provider": provider, "comfyPromptId": "controlled-prompt",
                    "openrouterJobId": "controlled-cloud-prompt",
                    "duration": 4, "resolution": "480p", "aspectRatio": "16:9", "tokenCost": 10}
        with self.connect() as conn:
            conn.execute("INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                job_id, "owner", mode, provider, status, 15, "fixture", "", None, None,
                json.dumps(settings), datetime.now(timezone.utc).isoformat(), None, None))
            conn.execute("INSERT INTO token_ledger VALUES (?,?,?,?,?,?)", (
                "charge-" + job_id, "owner", 0, "daily_generation", json.dumps({
                    "jobId": job_id, "token_cost": 10, "daily_part": 10}), datetime.now(timezone.utc).isoformat()))
        return self.row(job_id)

    def row(self, job_id="video-owned"):
        with self.connect() as conn:
            return conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()

    def ledger(self):
        with self.connect() as conn:
            return [dict(row) for row in conn.execute("SELECT * FROM token_ledger ORDER BY id")]

    def account(self):
        with self.connect() as conn:
            return tuple(conn.execute("SELECT token_balance,daily_tokens_used,tokens_used,generation_count FROM users").fetchone())

    async def cancel(self, job_id="video-owned", owner="owner"):
        return await self.routes["/api/jobs/{job_id}/cancel"](job_id, {"session_owner": owner})


class VideoCancellationFenceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="izo-video-cancel-")
        self.h = Harness(self.temporary.name)

    def tearDown(self):
        self.h.close()
        self.temporary.cleanup()

    async def test_owned_queued_video_cancel_is_reachable_and_idempotent(self):
        self.h.seed()
        self.assertEqual((await self.h.cancel())["status"], "cancelled")
        ledger = self.h.ledger()
        self.assertEqual(len(ledger), 2)
        self.assertEqual(self.h.account(), (100, 0, 0, 0))
        self.assertEqual((await self.h.cancel())["status"], "cancelled")
        self.assertEqual(self.h.ledger(), ledger)
        self.assertEqual(self.h.auth_calls, ["owner", "owner"])
        self.assertEqual(self.h.interrupts, 0)

    async def test_foreign_owned_route_does_not_cancel_or_refund(self):
        self.h.seed()
        ledger = self.h.ledger()
        with self.assertRaises(BoundaryError) as caught:
            await self.h.cancel(owner="foreign")
        self.assertEqual(caught.exception.status_code, 404)
        self.assertEqual(self.h.row()["status"], "queued")
        self.assertEqual(self.h.ledger(), ledger)

    async def test_cancelled_video_cannot_be_claimed_by_late_finalizer(self):
        self.h.seed()
        await self.h.cancel()
        claimed, current = self.h.runtime._claim_video_finalization("video-owned")
        self.assertFalse(claimed)
        self.assertEqual(current["status"], "cancelled")

    async def test_deferred_provider_completion_cannot_revive_cancelled_video(self):
        row = self.h.seed()
        work = asyncio.create_task(self.h.runtime._refresh_video_job(row))
        try:
            await asyncio.wait_for(self.h.entered.wait(), 1)
            await self.h.cancel()
            ledger = self.h.ledger()
            self.h.release.set()
            result = await asyncio.wait_for(work, 1)
            self.assertEqual(result["status"], "cancelled")
            self.assertEqual(self.h.row()["status"], "cancelled")
            self.assertEqual(self.h.ledger(), ledger)
            self.assertEqual(self.h.account(), (100, 0, 0, 0))
            self.assertEqual(self.h.downloads, [])
            with self.h.connect() as conn:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM videos").fetchone()[0], 0)
        finally:
            self.h.release.set()
            if not work.done():
                work.cancel()
            await asyncio.gather(work, return_exceptions=True)

    async def test_all_late_provider_states_preserve_cancelled_row_and_refund(self):
        row = self.h.seed()
        await self.h.cancel()
        ledger, account, durable = self.h.ledger(), self.h.account(), tuple(self.h.row())
        self.h.release.set()
        for state in ("pending", "in_progress", "failed", "cancelled", "expired", "completed"):
            with self.subTest(provider_state=state):
                self.h.state = {"status": state}  # completed without a URL formerly refunded/wrote failed.
                current = await self.h.runtime._refresh_video_job(row)
                self.assertEqual(tuple(current), durable)
                self.assertEqual(self.h.ledger(), ledger)
                self.assertEqual(self.h.account(), account)
                self.assertEqual(self.h.downloads, [])

    async def test_late_provider_failure_cannot_refund_a_completed_result(self):
        row = self.h.seed()
        self.h.release.set()
        completed = await self.h.runtime._refresh_video_job(row)
        filename = json.loads(completed["settings_json"])["localFile"]
        media, ledger, account = (self.h.directory / filename).read_bytes(), self.h.ledger(), self.h.account()
        self.h.state = {"status": "failed", "error": "controlled late failure"}
        self.assertEqual(tuple(await self.h.runtime._refresh_video_job(row)), tuple(completed))
        self.assertEqual(self.h.ledger(), ledger)
        self.assertEqual(self.h.account(), account)
        self.assertEqual((self.h.directory / filename).read_bytes(), media)
        claimed, latest = self.h.runtime._claim_video_finalization(row["id"])
        self.assertFalse(claimed)
        self.assertEqual(tuple(latest), tuple(completed))

    async def test_provider_failure_refund_and_terminal_write_roll_back_together(self):
        row = self.h.seed()
        ledger, account = self.h.ledger(), self.h.account()
        with self.h.connect() as conn:
            conn.execute("CREATE TRIGGER refuse_failure BEFORE UPDATE OF status ON jobs "
                         "WHEN NEW.status='failed' BEGIN SELECT RAISE(ABORT,'controlled'); END")
        self.h.state = {"status": "failed", "error": "controlled"}
        self.h.release.set()
        with self.assertRaises(sqlite3.IntegrityError):
            await self.h.runtime._refresh_video_job(row)
        self.assertEqual(tuple(self.h.row()), tuple(row))
        self.assertEqual(self.h.ledger(), ledger)
        self.assertEqual(self.h.account(), account)

    async def test_pending_poll_does_not_release_another_finalizing_download(self):
        row = self.h.seed()
        self.h.release.set()
        self.h.download_release.clear()
        work = asyncio.create_task(self.h.runtime._refresh_video_job(row))
        try:
            await asyncio.wait_for(self.h.download_entered.wait(), 1)
            claimed = tuple(self.h.row())
            self.h.state = {"status": "pending"}
            self.assertEqual(tuple(await self.h.runtime._refresh_video_job(row)), claimed)
            self.assertEqual(tuple(self.h.row()), claimed)
            self.h.download_release.set()
            self.assertEqual((await asyncio.wait_for(work, 1))["status"], "completed")
            self.assertEqual(len(self.h.downloads), 1)
        finally:
            self.h.download_release.set()
            if not work.done():
                work.cancel()
            await asyncio.gather(work, return_exceptions=True)

    async def stale_download(self, *, old_error=None):
        row = self.h.seed()
        self.h.release.set()
        self.h.download_release.clear()
        self.h.download_error = old_error
        old = asyncio.create_task(self.h.runtime._refresh_video_job(row))
        try:
            await asyncio.wait_for(self.h.download_entered.wait(), 1)
            claimed = self.h.row()
            settings = json.loads(claimed["settings_json"])
            settings["finalizingAt"] = "2020-01-01T00:00:00+00:00"
            with self.h.connect() as conn:
                conn.execute("UPDATE jobs SET settings_json=? WHERE id=?", (json.dumps(settings), row["id"]))
            winner = await self.h.runtime._refresh_video_job(self.h.row())
            self.assertEqual(winner["status"], "completed")
            winner_file = json.loads(winner["settings_json"])["localFile"]
            body, ledger = (self.h.directory / winner_file).read_bytes(), self.h.ledger()
            self.assertNotEqual(self.h.downloads[0], self.h.downloads[1])
            self.h.download_release.set()
            self.assertEqual(tuple(await asyncio.wait_for(old, 1)), tuple(winner))
            self.assertEqual(tuple(self.h.row()), tuple(winner))
            self.assertEqual((self.h.directory / winner_file).read_bytes(), body)
            self.assertFalse((self.h.directory / self.h.downloads[0]).exists())
            self.assertEqual(self.h.ledger(), ledger)
            self.assertEqual(self.h.storage.download_filename(row["id"]), row["id"] + ".mp4")
            released, latest = self.h.runtime._release_video_finalization(row["id"], "late", expected=claimed)
            self.assertFalse(released)
            self.assertEqual(tuple(latest), tuple(winner))
        finally:
            self.h.download_release.set()
            if not old.done():
                old.cancel()
            await asyncio.gather(old, return_exceptions=True)

    async def test_stale_download_never_overwrites_or_deletes_winning_media(self):
        await self.stale_download()

    async def test_stale_download_failure_never_resets_completed_job(self):
        await self.stale_download(old_error=RuntimeError("controlled old download"))

    async def test_cloud_video_still_completes_once_with_original_download_contract(self):
        row = self.h.seed(provider="openrouter")
        self.h.state = {"status": "completed", "unsigned_urls": ["http://unused.invalid/cloud"]}
        self.h.release.set()
        completed = await self.h.runtime._refresh_video_job(row)
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(len(self.h.ledger()), 1)
        self.assertEqual(self.h.account(), (100, 10, 10, 1))
        self.assertEqual(self.h.frees, 0)
        self.assertEqual(tuple(await self.h.runtime._refresh_video_job(completed)), tuple(completed))
        self.assertEqual(len(self.h.downloads), 1)

    async def test_image_cancel_retains_its_existing_owner_and_financial_contract(self):
        self.h.seed(job_id="image-owned", mode="text_to_image", provider="comfyui")
        self.assertEqual((await self.h.cancel("image-owned"))["status"], "cancelled")
        ledger = self.h.ledger()
        self.assertEqual((await self.h.cancel("image-owned"))["status"], "cancelled")
        self.assertEqual(self.h.ledger(), ledger)
        self.assertEqual(self.h.account(), (100, 0, 0, 0))
        self.assertEqual(self.h.interrupts, 0)
        with self.assertRaises(BoundaryError) as caught:
            self.h.runtime._claim_video_finalization("image-owned")
        self.assertEqual(caught.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
