"""Real SQLite ownership/transaction regressions; no provider or app startup."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from contextvars import Context
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest

from app.services import generation_claims as claims, generation_jobs as jobs
from app.services.generation_worker import GenerationClaimLost
from app.database.connection import open_sqlite


NOW = "2026-10-17T12:00:00+00:00"


class ClaimDatabase:
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="izo-claim-")
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "owned.sqlite3"
        with closing(self.open()) as conn, conn:
            conn.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE users (id TEXT PRIMARY KEY, token_balance INTEGER DEFAULT 100,
                    tokens_used INTEGER DEFAULT 0, generation_count INTEGER DEFAULT 0,
                    daily_tokens_used INTEGER DEFAULT 0, openrouter_monthly_tokens_used INTEGER DEFAULT 0);
                INSERT INTO users (id) VALUES ('user_1'),('user_2');
                CREATE TABLE jobs (id TEXT PRIMARY KEY, user_id TEXT, mode TEXT, provider TEXT,
                    status TEXT, progress INTEGER, prompt_original TEXT, prompt_translated TEXT,
                    result_image_id TEXT, error_message TEXT, settings_json TEXT, created_at TEXT,
                    started_at TEXT, completed_at TEXT);
                CREATE TABLE images (id TEXT PRIMARY KEY, user_id TEXT, job_id TEXT, url TEXT,
                    thumbnail_url TEXT, width INTEGER, height INTEGER, settings_json TEXT,
                    mode TEXT, provider TEXT, prompt_original TEXT, prompt_translated TEXT,
                    is_favorite INTEGER, created_at TEXT, deleted_at TEXT);
                CREATE TABLE image_sources (id TEXT PRIMARY KEY, image_id TEXT, user_id TEXT,
                    source_image_id TEXT, source_kind TEXT, role TEXT, slot_index INTEGER,
                    thumb_url TEXT, thumb_width INTEGER, thumb_height INTEGER, thumb_bytes INTEGER,
                    is_favorite INTEGER, library_deleted_at TEXT, availability_status TEXT,
                    availability_checked_at TEXT, unavailable_at TEXT, children_json TEXT, created_at TEXT);
                CREATE TABLE token_ledger (id TEXT PRIMARY KEY, user_id TEXT, delta INTEGER,
                    reason TEXT, meta_json TEXT, created_at TEXT);
                CREATE TABLE generation_trial_reservations (job_id TEXT PRIMARY KEY, state TEXT, settled_at TEXT);
            """)

    def open(self):
        return open_sqlite(self.path, timeout_seconds=2, busy_timeout_ms=2000)

    def connect(self):
        return claims.connection(self.open)

    def persist(self, job, request=None, *, conn=None):
        data = vars(request) if request is not None else job.get("request", {})
        def write(connection):
            jobs.persist_runtime_job(connection, job, request_data=deepcopy(data), now_iso=NOW)
        if conn is not None:
            write(conn)
        else:
            with closing(self.connect()) as own, own:
                write(own)

    def read_job(self, job_id, user_id):
        with closing(self.connect()) as conn:
            return jobs.get_persisted_job_response(conn, job_id, user_id, model_display_name=str)

    def seed(self, job_id="job_1", user_id="user_1", provider="comfyui", *, charge=0):
        request = dict(mode="text_to_image", provider=provider, prompt="owned", seed=42,
                       width=704, height=960, modelProfile="local_flux_klein", loras=[])
        job = dict(id=job_id, userId=user_id, mode=request["mode"], provider=provider,
                   request=request, status="queued", progress=0, tokenCost=charge, createdAt=NOW)
        self.persist(job)
        if charge:
            with closing(self.open()) as conn, conn:
                conn.execute("UPDATE users SET token_balance=token_balance-?, tokens_used=tokens_used+?, "
                             "generation_count=generation_count+1 WHERE id=?", (charge, charge, user_id))
                conn.execute("INSERT INTO token_ledger VALUES (?,?,?,?,?,?)", ("charge-"+job_id, user_id,
                    -charge, "generation", json.dumps({"jobId": job_id, "token_cost": charge}), NOW))
        return job

    def scope(self, job):
        return claims.claim_job(self.connect, job["id"], job["userId"], now_iso=NOW)

    def state(self, job_id="job_1"):
        with closing(self.open()) as conn:
            return dict(conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())

    def counts(self):
        with closing(self.open()) as conn:
            return {table: conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                    for table in ("images", "image_sources", "token_ledger")}


class GenerationClaimTests(ClaimDatabase, unittest.TestCase):
    def test_two_real_connections_claim_one_job_and_do_not_hold_writer_during_provider_wait(self):
        job = self.seed()
        barrier = threading.Barrier(2)
        def contender():
            barrier.wait(timeout=2)
            with self.scope(job) as acquired:
                if acquired:
                    with closing(self.open()) as other, other:
                        other.execute("UPDATE users SET token_balance=99 WHERE id='user_2'")
                return acquired
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _index: contender(), range(2)))
        self.assertEqual(sorted(results), [False, True])
        self.assertEqual(self.state()["status"], "running")

    def test_unbound_writer_cannot_resurrect_claimed_or_terminal_job(self):
        job = self.seed()
        with self.scope(job) as acquired:
            self.assertTrue(acquired)
            job.update(status="completed")
            self.persist(job)
        before = self.state()
        job.update(status="running")
        with self.assertRaisesRegex(GenerationClaimLost, "GENERATION_CLAIM_REQUIRED"):
            self.persist(job)
        self.assertEqual(self.state(), before)
        self.assertNotIn(claims.METADATA_KEY, json.dumps(self.read_job("job_1", "user_1")))

    def test_cancelled_failed_and_completed_rows_fence_the_old_worker_before_effects(self):
        for status in ("cancelled", "failed", "completed"):
            with self.subTest(status=status):
                job = self.seed("job_"+status)
                with self.scope(job):
                    with closing(self.open()) as other, other:
                        other.execute("UPDATE jobs SET status=? WHERE id=?", (status, job["id"]))
                    with self.assertRaisesRegex(GenerationClaimLost, "GENERATION_CLAIM_LOST"):
                        with claims.transaction(self.connect):
                            self.fail("late side effect was admitted")
                self.assertEqual(self.counts()["images"], 0)

    def test_wrong_token_or_owner_cannot_write(self):
        job = self.seed()
        with self.scope(job):
            with closing(self.open()) as conn, conn:
                data = json.loads(self.state()["settings_json"])
                data[claims.METADATA_KEY]["token"] = "other-owner-token"
                conn.execute("UPDATE jobs SET settings_json=? WHERE id=?", (json.dumps(data), job["id"]))
            job.update(status="uploading")
            with self.assertRaisesRegex(GenerationClaimLost, "GENERATION_CLAIM_LOST"):
                self.persist(job)
        with closing(self.open()) as conn, conn:
            with self.assertRaises(LookupError):
                with claims.authorize_cancellation(conn, "job_1", "user_2"):
                    self.fail("foreign owner was admitted")

    def test_nested_connections_join_one_commit_and_cursor_keeps_borrowed_owner(self):
        job = self.seed()
        published = []
        with self.scope(job), claims.transaction(self.connect):
            with closing(self.connect()) as conn, conn:
                cursor = conn.execute("INSERT INTO images (id,user_id,job_id) VALUES ('image','user_1','job_1')")
                self.assertIs(cursor.connection, conn)
                claims.after_commit(lambda: published.append("image"))
            with closing(self.open()) as observer:
                self.assertEqual(observer.execute("SELECT count(*) FROM images").fetchone()[0], 0)
            self.assertEqual(published, [])
            job.update(status="completed", resultImageId="image")
            self.persist(job)
        self.assertEqual(published, ["image"])
        self.assertEqual(self.counts()["images"], 1)
        self.assertEqual(self.state()["status"], "completed")

    def test_failure_after_multiple_writes_rolls_back_every_row_and_after_commit_action(self):
        job = self.seed()
        published = []
        with self.scope(job):
            with self.assertRaisesRegex(RuntimeError, "disk index failed"):
                with claims.transaction(self.connect):
                    with closing(self.connect()) as conn, conn:
                        conn.execute("INSERT INTO images (id) VALUES ('image')")
                        conn.execute("INSERT INTO token_ledger (id) VALUES ('adjustment')")
                    claims.after_commit(lambda: published.append("image"))
                    raise RuntimeError("disk index failed")
        self.assertEqual(self.counts(), {"images": 0, "image_sources": 0, "token_ledger": 0})
        self.assertEqual(self.state()["status"], "running")
        self.assertEqual(published, [])

    def test_nested_context_and_direct_sql_cannot_commit_before_terminal_write(self):
        for operation in (lambda c: c.commit(), lambda c: c.cursor().connection.commit(),
                          lambda c: c.execute("COMMIT"), lambda c: c.executescript("SELECT 1;")):
            job = self.seed("job_"+str(id(operation)))
            with self.scope(job):
                with self.assertRaises((RuntimeError, sqlite3.DatabaseError)):
                    with claims.transaction(self.connect):
                        with closing(self.connect()) as conn, conn:
                            conn.execute("INSERT INTO images (id) VALUES ('uncommitted')")
                            operation(conn)
            self.assertEqual(self.counts()["images"], 0)

    def test_authorized_cancel_is_atomic_and_old_worker_cannot_override_it(self):
        job = self.seed()
        def cancel():
            with closing(self.open()) as conn, conn:
                with claims.authorize_cancellation(conn, "job_1", "user_1"):
                    cancelled = {**job, "status": "cancelled"}
                    self.persist(cancelled, conn=conn)
        with self.scope(job):
            Context().run(cancel)
            with self.assertRaises(GenerationClaimLost):
                self.persist({**job, "status": "completed"})
        self.assertEqual(self.state()["status"], "cancelled")

    def test_media_recovery_only_accepts_completed_or_legacy_missing_job(self):
        job = self.seed()
        with closing(self.open()) as conn, conn:
            for status in ("queued", "running", "failed", "cancelled", "completed"):
                conn.execute("UPDATE jobs SET status=? WHERE id=?", (status, job["id"]))
                self.assertEqual(claims.can_recover_media(conn, job["id"]), status == "completed")
            self.assertTrue(claims.can_recover_media(conn, "job_missing_legacy"))


if __name__ == "__main__":
    unittest.main()
