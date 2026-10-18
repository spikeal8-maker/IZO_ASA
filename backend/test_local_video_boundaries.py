"""Real video functions/SQLite with fake I/O; this is not a media decode proof."""
from __future__ import annotations

import __future__
import ast
import asyncio
from collections.abc import Mapping
from contextlib import contextmanager, suppress
from contextvars import ContextVar
import copy
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import secrets
import sqlite3
from statistics import fmean
import sys
import tempfile
from types import ModuleType, SimpleNamespace
from typing import Protocol
import unittest
from unittest.mock import patch
import uuid

ROOT = Path(__file__).resolve().parent
CANARY = "owned-private-canary"
DIAGNOSTICS = (
    f"ConnectError https://ltx.invalid/private/{CANARY}?token=fixture-token",
    f"/srv/private/{CANARY}/workflow.json",
    f"C:\\private\\{CANARY}\\model.gguf",
)


def definitions(path, *, include=None, bindings=None):
    """Compile actual owned definitions without importing main or starting its app."""
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
    kinds = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Assign, ast.AnnAssign)
    nodes = [node for node in tree.body if isinstance(node, kinds)]
    def names(node):
        if hasattr(node, "name"):
            return {node.name}
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        return {target.id for target in targets if isinstance(target, ast.Name)}
    if include is not None:
        nodes = [node for node in nodes if names(node) & set(include)]
        if set().union(*(names(node) for node in nodes)) != set(include):
            raise AssertionError("Requested production definitions are missing")
    module = ModuleType("_local_video_contract_" + path.replace("/", "_").replace(".", "_"))
    namespace = module.__dict__
    namespace.update(ContextVar=ContextVar, contextmanager=contextmanager, json=json, asyncio=asyncio, copy=copy, dataclass=dataclass,
        datetime=datetime, timezone=timezone, Path=Path, re=re, secrets=secrets,
        sqlite3=sqlite3, fmean=fmean, Mapping=Mapping, Protocol=Protocol, uuid=uuid, suppress=suppress)
    namespace.update({key: value for key, value in (bindings or {}).items() if not key.startswith("__")})
    previous = sys.modules.get(module.__name__)
    sys.modules[module.__name__] = module  # dataclasses resolves its own module during definition.
    try:
        exec(compile(ast.Module(body=nodes, type_ignores=[]), str(ROOT / path), "exec",
                     flags=__future__.annotations.compiler_flag), namespace)
    finally:
        if previous is None:
            sys.modules.pop(module.__name__)
        else:
            sys.modules[module.__name__] = previous
    return SimpleNamespace(**namespace)


generation_accounting = definitions("app/services/generation_accounting.py")
video_storage = definitions("app/services/video_storage.py")


class BoundaryError(Exception):
    """The HTTP exception factory boundary, without an ASGI/server dependency."""
    def __init__(self, status_code, detail):
        super().__init__(detail)
        self.status_code, self.detail = status_code, detail


class FakeLtxClient:
    def __init__(self, harness):
        self.harness, self.prompts, self.polls, self.frees = harness, [], [], 0
        self.ready = {"ready": True, "device": "controlled protocol; no GPU"}
        self.state = {"status": "pending"}
        self.failure = None

    async def readiness(self):
        return self.ready

    async def submit(self, prompt, *, client_id):
        with self.harness.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")  # No writer transaction may span this provider await.
        self.prompts.append((client_id, copy.deepcopy(prompt)))
        if self.failure is not None:
            raise self.failure
        return "owned-comfy-prompt"

    async def status(self, prompt_id):
        self.polls.append(prompt_id)
        return copy.deepcopy(self.state)

    async def free_memory(self):
        self.frees += 1

    def view_url(self, output):
        return "http://ltx.invalid/view?filename=" + output["filename"]


class VideoHarness:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.database = self.directory / "owned.sqlite3"
        self.media = self.directory / "media"
        self.media.mkdir()
        self.workflow = self.directory / "workflow.json"
        self.workflow.write_bytes((ROOT / "workflows/ltx23_t2v_api.json").read_bytes())
        self.downloads, self.download_failure = [], None
        with self.connect() as conn:
            conn.executescript("""
                CREATE TABLE users (id TEXT PRIMARY KEY, plan TEXT, role TEXT,
                    token_balance INTEGER, daily_tokens_used INTEGER, tokens_used INTEGER, generation_count INTEGER);
                CREATE TABLE jobs (id TEXT PRIMARY KEY, user_id TEXT, mode TEXT, provider TEXT,
                    status TEXT, progress INTEGER, prompt_original TEXT, settings_json TEXT,
                    created_at TEXT, started_at TEXT, completed_at TEXT, error_message TEXT);
                CREATE TABLE token_ledger (id TEXT PRIMARY KEY, user_id TEXT, delta INTEGER,
                    reason TEXT, meta_json TEXT, created_at TEXT);
                CREATE TABLE videos (id TEXT PRIMARY KEY, user_id TEXT, job_id TEXT UNIQUE, url TEXT,
                    width INTEGER, height INTEGER, duration_seconds INTEGER, aspect_ratio TEXT,
                    mode TEXT, provider TEXT, prompt_original TEXT, settings_json TEXT, stored_bytes INTEGER,
                    created_at TEXT, deleted_at TEXT, is_favorite INTEGER DEFAULT 0);
                CREATE TABLE video_file_deletions (id TEXT PRIMARY KEY, video_id TEXT, job_id TEXT,
                    filename TEXT, attempts INTEGER, last_error TEXT, created_at TEXT);
                INSERT INTO users VALUES ('owner','mini','user',100,0,0,0);
            """)
        profiles = definitions("app/services/ltx_video/profiles.py")
        workflow = definitions("app/services/ltx_video/workflow.py", bindings=vars(profiles))
        self.client = FakeLtxClient(self)
        orchestration = definitions("app/services/ltx_video/orchestration.py", bindings={
            **vars(profiles), "build_ltx_prompt": workflow.build_ltx_prompt,
            "ComfyLtxClient": lambda *_args: self.client})
        self.ltx = SimpleNamespace(**(vars(profiles) | vars(orchestration)))
        pricing = definitions("app/services/video_pricing.py")
        self.presentation = definitions("app/services/video_presentation.py", bindings={
            **vars(profiles), "video_size": pricing.video_size})
        generation = definitions("app/services/generation_jobs.py", include={
            "public_generation_error_message", "PUBLIC_SERVER_ERROR", "_PRIVATE_ERROR_DETAILS"})
        self.phone = definitions("app/services/phone_jobs.py", bindings={
            "public_generation_error_message": generation.public_generation_error_message,
            "public_video_error_message": self.presentation.public_video_error_message})
        names = {"_generate_local_ltx_video", "_refresh_video_job", "_claim_video_finalization",
            "_release_video_finalization", "_backfill_completed_video_gallery", "_video_job_payload",
            "_video_storage_reservation", "_evict_videos_for_new_result", "_queue_video_file_deletion",
            "drain_video_file_deletions"}
        self.runtime = definitions("main.py", include=names, bindings={
            "db": self.connect, "MEDIA": self.media, "ltx_video": self.ltx,
            "LOCAL_LTX_WORKFLOW_API_PATH": self.workflow, "LOCAL_LTX_COMFYUI_BASE_URL": "http://ltx.invalid",
            "COMFYUI_TIMEOUT_SECONDS": 3, "HTTPException": BoundaryError,
            "charge_generation_tokens": self.charge, "refund_generation_tokens": generation_accounting.refund_generation_tokens,
            "video_storage": video_storage, "video_pricing": pricing, "video_presentation": self.presentation,
            "VIDEO_FINALIZATION_STALE_SECONDS": 600, "safe_json_load": lambda value: json.loads(value or "{}"),
            "truncate_admin_text": lambda value, limit: str(value)[:limit],
            "_row_get": lambda row, key: row[key] if row is not None and key in row.keys() else None,
            "_feed_publication_ready": lambda _row: False,
            "storage_resolve_under_root": self.resolve,
            "gallery_quota_for_user": lambda *_args: {"video_slots": 10, "video_enabled": True},
            "_download_video_result": self.download,
        })
        self.profile = profiles.resolve_local_ltx_profile("local/ltx-2.3-fast-q3")

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.database, timeout=.2)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def resolve(self, root, filename):
        target = (root / filename).resolve()
        return target if target.parent == root.resolve() else None

    def charge(self, conn, owner, cost, job_id, _req, _billing):
        conn.execute("UPDATE users SET daily_tokens_used=daily_tokens_used+?,tokens_used=tokens_used+?,"
                     "generation_count=generation_count+1 WHERE id=?", (cost, cost, owner))
        conn.execute("INSERT INTO token_ledger VALUES (?,?,?,?,?,?)", (uuid.uuid4().hex, owner, 0,
            "daily_generation", json.dumps({"jobId": job_id, "token_cost": cost, "daily_part": cost}),
            datetime.now(timezone.utc).isoformat()))
        return {"new_balance": 100}

    async def download(self, _url, job_id, *, use_openrouter_auth=True):
        self.downloads.append((job_id, use_openrouter_auth))
        if self.download_failure:
            raise self.download_failure
        # The download contract hands off an owned file. Decode is a separate installed gate.
        path = self.media / (job_id + ".mp4")
        path.write_bytes(b"owned file handoff for metadata characterization")
        return path.name, path.stat().st_size

    def row(self, job_id):
        with self.connect() as conn:
            return conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()

    def financial(self):
        with self.connect() as conn:
            return {"users": [tuple(row) for row in conn.execute("SELECT * FROM users ORDER BY id")],
                    "ledger": [tuple(row) for row in conn.execute("SELECT * FROM token_ledger ORDER BY id")]}

    async def submit(self, **values):
        req = SimpleNamespace(mode="text_to_video", model=self.profile.model_id, prompt="Owned abstract landscape",
            duration=2, resolution="480p", aspectRatio="16:9", generateAudio=False)
        vars(req).update(values)
        return await self.runtime._generate_local_ltx_video(req, user_id="owner", profile=self.profile)

    async def complete(self, **values):
        started = await self.submit(**values)
        self.client.state = {"status": "completed", "output": {"filename": "owned.mp4"}}
        result = await self.runtime._refresh_video_job(self.row(started["id"]))
        return started, result


class LocalVideoBoundaries(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="izo-local-video-")
        self.addCleanup(self.temporary.cleanup)
        self.h = VideoHarness(self.temporary.name)

    def assert_private(self, value):
        encoded = json.dumps(value, ensure_ascii=False)
        self.assertNotIn(CANARY, encoded)
        self.assertNotIn("ltx.invalid", encoded)
        self.assertNotIn("fixture-token", encoded)

    async def test_finalization_dimensions_match_the_submitted_workflow_for_all_aspects(self):
        for aspect, expected in (("16:9", (832, 480)), ("9:16", (480, 832)), ("1:1", (640, 640))):
            with self.subTest(aspect=aspect):
                started, row = await self.h.complete(aspectRatio=aspect)
                latent = next(node["inputs"] for node in self.h.client.prompts[-1][1].values()
                              if node["class_type"] == "EmptyLTXVLatentVideo")
                self.assertEqual((latent["width"], latent["height"]), expected)
                self.assertEqual(row["status"], "completed")
                with self.h.connect() as conn:
                    video = conn.execute("SELECT * FROM videos WHERE job_id=?", (started["id"],)).fetchone()
                self.assertEqual((video["width"], video["height"]), expected)
                self.assertEqual(self.h.downloads[-1], (started["id"], False))

    async def test_backfill_uses_ltx_dimensions_and_preserves_single_charge(self):
        started, _ = await self.h.complete()
        before = self.h.financial()
        with self.h.connect() as conn:
            conn.execute("DELETE FROM videos WHERE job_id=?", (started["id"],))
            self.assertEqual(self.h.runtime._backfill_completed_video_gallery(conn, "owner"), 1)
            self.assertEqual(self.h.runtime._backfill_completed_video_gallery(conn, "owner"), 0)
            value = conn.execute("SELECT width,height FROM videos WHERE job_id=?", (started["id"],)).fetchone()
        self.assertEqual(tuple(value), (832, 480))
        self.assertEqual(self.h.financial(), before)
        self.assertEqual(len(self.h.client.prompts), 1)

    async def test_existing_local_geometry_repair_does_not_change_favorite_media_or_money(self):
        started, row = await self.h.complete()
        before, media = self.h.financial(), (self.h.media / json.loads(row["settings_json"])["localFile"]).read_bytes()
        with self.h.connect() as conn:
            conn.execute("UPDATE videos SET width=853,is_favorite=1 WHERE job_id=?", (started["id"],))
            self.assertEqual(self.h.runtime._backfill_completed_video_gallery(conn, "owner"), 0)
            self.assertEqual(self.h.runtime._backfill_completed_video_gallery(conn, "owner"), 0)
            value = conn.execute("SELECT width,height,is_favorite FROM videos WHERE job_id=?", (started["id"],)).fetchone()
        self.assertEqual(tuple(value), (832, 480, 1))
        self.assertEqual(self.h.financial(), before)
        self.assertEqual((self.h.media / json.loads(row["settings_json"])["localFile"]).read_bytes(), media)
        self.assertEqual(len(self.h.client.prompts), 1)

    async def test_geometry_repair_rejects_foreign_deleted_cloud_and_unknown_profile_rows(self):
        started, row = await self.h.complete()
        before = self.h.financial()
        changes = (
            ("videos", "user_id", "foreign"), ("jobs", "user_id", "foreign"),
            ("videos", "deleted_at", "2026-01-01T00:00:00Z"),
            ("videos", "provider", "openrouter"), ("jobs", "provider", "openrouter"),
            ("settings", "localLtxProfile", "unregistered"), ("settings", "resolution", "720p"),
        )
        with self.h.connect() as conn:
            for table, field, value in changes:
                with self.subTest(table=table, field=field):
                    conn.execute("SAVEPOINT unchanged_video")
                    conn.execute("UPDATE videos SET width=853 WHERE job_id=?", (started["id"],))
                    if table == "settings":
                        settings = {**json.loads(row["settings_json"]), field: value}
                        conn.execute("UPDATE jobs SET settings_json=? WHERE id=?", (json.dumps(settings), started["id"]))
                    else:
                        key = "id" if table == "jobs" else "job_id"
                        conn.execute(f"UPDATE {table} SET {field}=? WHERE {key}=?", (value, started["id"]))
                    original = tuple(conn.execute("SELECT * FROM videos").fetchone())
                    self.assertEqual(self.h.runtime._backfill_completed_video_gallery(conn, "owner"), 0)
                    self.assertEqual(tuple(conn.execute("SELECT * FROM videos").fetchone()), original)
                    conn.execute("ROLLBACK TO unchanged_video")
                    conn.execute("RELEASE unchanged_video")
        self.assertEqual(self.h.financial(), before)
        self.assertEqual(len(self.h.client.prompts), 1)

    def test_cloud_geometry_and_error_presentation_remain_unchanged(self):
        pricing = definitions("app/services/video_pricing.py")
        for resolution in ("480p", "720p", "1080p"):
            for aspect in ("16:9", "9:16", "1:1"):
                settings = {"resolution": resolution, "aspectRatio": aspect}
                self.assertEqual(self.h.presentation.output_size(settings, provider="openrouter"),
                    pricing.video_size({"supportedSizes": []}, resolution, aspect))
        self.assertEqual(self.h.presentation.public_video_error_message("Измените настройки.", provider="openrouter"),
                         "Измените настройки.")
        self.assertIn("исходное изображение", self.h.presentation.public_video_error_message("400 Bad Request"))

    async def test_readiness_diagnostics_do_not_cross_the_submit_boundary_or_charge(self):
        before = self.h.financial()
        for diagnostic in DIAGNOSTICS:
            with self.subTest(diagnostic=diagnostic):
                self.h.client.ready = {"ready": False, "error": diagnostic}
                with self.assertRaises(BoundaryError) as caught:
                    await self.h.submit()
                self.assertEqual(caught.exception.status_code, 503)
                self.assert_private(caught.exception.detail)
        self.assertEqual(self.h.financial(), before)
        self.assertEqual(self.h.client.prompts, [])
        with self.h.connect() as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM jobs").fetchone()[0], 0)

    async def test_admin_readiness_keeps_private_diagnostics(self):
        before = self.h.financial()
        self.h.client.ready = {"ready": False, "error": DIAGNOSTICS[0]}
        result = await self.h.ltx.admin_runtime_status(client=self.h.client, enabled=True,
            base_url="http://ltx.invalid", open_db=self.h.connect)
        self.assertEqual(result["video"]["error"], DIAGNOSTICS[0])
        self.assertEqual(result["video"]["base_url"], "http://ltx.invalid")
        self.assertEqual(self.h.financial(), before)

    async def test_unrecognized_exception_details_cannot_claim_a_safe_validation_message(self):
        for error in (self.h.ltx.LocalLtxRequestError(422, DIAGNOSTICS[1]), BoundaryError(403, DIAGNOSTICS[2])):
            with self.subTest(error=type(error).__name__):
                self.h.client.failure = error
                with self.assertRaises(BoundaryError) as caught:
                    await self.h.submit()
                self.assertEqual(caught.exception.status_code, 502)
                self.assert_private(caught.exception.detail)
        self.assertEqual(len(self.h.client.prompts), 2)
        self.assertEqual(len(self.h.financial()["ledger"]), 4)

    async def test_submit_failure_is_private_and_refunded_once_without_provider_retry(self):
        self.h.client.failure = RuntimeError(DIAGNOSTICS[0])
        with self.assertRaises(BoundaryError) as caught:
            await self.h.submit()
        self.assertEqual(caught.exception.status_code, 502)
        self.assert_private(caught.exception.detail)
        self.assertEqual(len(self.h.client.prompts), 1)
        job_id = self.h.client.prompts[0][0]
        row = self.h.row(job_id)
        self.assertEqual(row["status"], "failed")
        self.assert_private(self.h.runtime._video_job_payload(row))
        await self.h.runtime._refresh_video_job(row)
        with self.h.connect() as conn:
            self.assertFalse(generation_accounting.refund_generation_tokens(conn, job_id, reason="repeat"))
            self.assertEqual(conn.execute("SELECT daily_tokens_used FROM users WHERE id='owner'").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT count(*) FROM token_ledger").fetchone()[0], 2)
        self.assertEqual(len(self.h.client.prompts), 1)

    async def test_workflow_read_failure_is_private_before_any_charge_or_submit(self):
        before = self.h.financial()
        with patch.object(Path, "read_text", side_effect=PermissionError(DIAGNOSTICS[1])):
            with self.assertRaises(BoundaryError) as caught:
                await self.h.submit()
        self.assertEqual(caught.exception.status_code, 502)
        self.assert_private(caught.exception.detail)
        self.assertEqual(self.h.financial(), before)
        self.assertEqual(self.h.client.prompts, [])

    async def test_safe_validation_and_concurrency_contracts_remain_actionable(self):
        for values in ({"generateAudio": True}, {"duration": 6}, {"aspectRatio": "4:3"}):
            with self.subTest(values=values):
                with self.assertRaises(BoundaryError) as caught:
                    await self.h.submit(**values)
                self.assertEqual(caught.exception.status_code, 422)
                self.assertTrue(caught.exception.detail)
        await self.h.submit()
        before = self.h.financial()
        with self.assertRaises(BoundaryError) as caught:
            await self.h.submit()
        self.assertEqual(caught.exception.status_code, 409)
        self.assertIn("уже выполняет", caught.exception.detail)
        self.assertEqual(self.h.financial(), before)
        self.assertEqual(len(self.h.client.prompts), 1)

    async def test_historical_private_errors_are_safe_in_video_and_phone_history(self):
        started = await self.h.submit()
        for diagnostic in DIAGNOSTICS:
            with self.subTest(diagnostic=diagnostic):
                with self.h.connect() as conn:
                    conn.execute("UPDATE jobs SET status='failed',error_message=? WHERE id=?", (diagnostic, started["id"]))
                    phone = self.h.phone.list_phone_jobs(conn, "owner", active_only=False)
                self.assert_private(self.h.runtime._video_job_payload(self.h.row(started["id"])))
                self.assert_private(phone)

    async def test_terminal_provider_error_is_private_and_refund_is_idempotent(self):
        started = await self.h.submit()
        self.h.client.state = {"status": "failed", "error": DIAGNOSTICS[2]}
        result = await self.h.runtime._refresh_video_job(self.h.row(started["id"]))
        self.assertEqual(result["status"], "failed")
        self.assert_private(self.h.runtime._video_job_payload(result))
        with self.h.connect() as conn:
            self.assert_private(self.h.phone.list_phone_jobs(conn, "owner", active_only=False))
        before = self.h.financial()
        await self.h.runtime._refresh_video_job(result)
        self.assertEqual(self.h.financial(), before)
        self.assertEqual(len(self.h.client.prompts), 1)
        self.assertEqual(len(before["ledger"]), 2)

    async def test_download_retry_keeps_diagnostics_private_and_does_not_resubmit(self):
        started = await self.h.submit()
        self.h.client.state = {"status": "completed", "output": {"filename": "owned.mp4"}}
        for error in (OSError(DIAGNOSTICS[1]), BoundaryError(502, DIAGNOSTICS[2])):
            self.h.download_failure = error
            with self.assertRaises(BoundaryError) as caught:
                await self.h.runtime._refresh_video_job(self.h.row(started["id"]))
            self.assertEqual(caught.exception.status_code, 502)
            self.assert_private(caught.exception.detail)
        pending = self.h.row(started["id"])
        self.assertEqual(pending["status"], "pending")
        self.assertIn(CANARY, json.loads(pending["settings_json"])["finalizingError"])
        self.assert_private(self.h.runtime._video_job_payload(pending))
        with self.h.connect() as conn:
            self.assert_private(self.h.phone.list_phone_jobs(conn, "owner", active_only=True))
        self.h.download_failure = None
        result = await self.h.runtime._refresh_video_job(pending)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(len(self.h.client.prompts), 1)
        self.assertEqual(len(self.h.financial()["ledger"]), 1)


if __name__ == "__main__":
    unittest.main()
