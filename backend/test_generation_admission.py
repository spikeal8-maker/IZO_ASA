"""Real SQLite admission regressions; no backend startup, socket or provider I/O."""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import copy
from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import uuid

from app.security.trial_access import gate_detail
from app.services import generation_admission as admission, generation_jobs
from app.services.generation_accounting import refund_generation_tokens
from app.services.generation_recovery import reconcile_stale_generation_jobs


def now():
    return datetime.now(timezone.utc).isoformat()


class Request(SimpleNamespace):
    def __init__(self, **changes):
        data = dict(mode="text_to_image", provider="comfyui", prompt="admission fixture",
                    width=704, height=704, resolutionId="square", modelProfile="local_flux_klein",
                    seed=42, steps=4, cfg=1, negativePrompt="", inputImage1=None,
                    inputImages=[], outpaint=None)
        super().__init__(**(data | changes))

    def model_dump(self):
        return copy.deepcopy(vars(self))


class WakeQueue:
    def __init__(self, connect):
        self.items, self.connect, self.lock = [], connect, threading.Lock()

    def qsize(self):
        with self.lock:
            return len(self.items)

    async def put(self, job_id):
        with closing(self.connect()) as conn:
            if conn.execute("SELECT id FROM jobs WHERE id=?", (job_id,)).fetchone() is None:
                raise AssertionError("wake happened before commit")
        with self.lock:
            self.items.append(job_id)


class AdmissionTests(unittest.TestCase):
    def setUp(self):
        root = tempfile.TemporaryDirectory(prefix="izo-admission-")
        self.addCleanup(root.cleanup)
        self.database = Path(root.name) / "owned.sqlite3"
        self.calls, self.jobs, self.barrier = [], {}, None
        with closing(self.connect()) as conn, conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript("""
                CREATE TABLE users (id TEXT PRIMARY KEY, plan TEXT, token_balance INTEGER,
                    tokens_used INTEGER DEFAULT 0, generation_count INTEGER DEFAULT 0,
                    daily_tokens_used INTEGER DEFAULT 0, openrouter_monthly_tokens_used INTEGER DEFAULT 0);
                CREATE TABLE jobs (id TEXT PRIMARY KEY, user_id TEXT, mode TEXT NOT NULL,
                    provider TEXT NOT NULL, status TEXT NOT NULL, progress INTEGER NOT NULL,
                    prompt_original TEXT, prompt_translated TEXT, result_image_id TEXT,
                    error_message TEXT, settings_json TEXT NOT NULL, created_at TEXT NOT NULL,
                    started_at TEXT, completed_at TEXT);
                CREATE TABLE images (id TEXT PRIMARY KEY, user_id TEXT, job_id TEXT,
                    url TEXT, thumbnail_url TEXT, width INTEGER, height INTEGER, settings_json TEXT,
                    created_at TEXT, deleted_at TEXT);
                CREATE TABLE token_ledger (id TEXT PRIMARY KEY, user_id TEXT NOT NULL, delta INTEGER NOT NULL,
                    reason TEXT NOT NULL, meta_json TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE TABLE account_verifications (internal_user_id TEXT PRIMARY KEY, status TEXT, required_at TEXT);
                CREATE TABLE generation_trial_reservations (job_id TEXT PRIMARY KEY,
                    internal_user_id TEXT, source TEXT, state TEXT, reserved_at TEXT, settled_at TEXT);
                INSERT INTO users (id,plan,token_balance) VALUES ('owner','mini',100),('other','mini',100);
            """)
        self.wakes = WakeQueue(self.connect)
        self.runtime = admission.AdmissionRuntime(
            connect=self.connect, jobs=self.jobs, queue=self.wakes,
            require_generation_social_verification=self.social, plan_order=["mini"],
            resolution_id_for_size=lambda w, h: "square" if (w, h) == (704, 704) else None,
            normalize_resolution_ids=lambda ids: ids, get_tariff_config=lambda: {"mini": {"allowed_resolutions": ["square"]}},
            config_ui_resolution_ids=["square"], openrouter_generation_modes={"text_to_image", "edit"},
            fetch_openrouter_image_capabilities=self.capabilities, resolve_openrouter_model=lambda req: "fixture",
            get_openrouter_config=lambda: {}, openrouter_model_allowed=lambda *args: True,
            supported_resolution_ids_from_capability=lambda cap: ["square"],
            estimate_openrouter_billing=self.billing, estimate_token_cost=lambda req: 7,
            validate_edit_request=lambda req: None, outpaint_padding=lambda value: value,
            validate_generation_media_inputs=self.media, ensure_rate_limit=self.rate,
            charge_generation_tokens=self.charge, record_event_log=self.event,
        )

    def connect(self):
        conn = sqlite3.connect(self.database, timeout=5)
        conn.row_factory = sqlite3.Row
        return conn

    def social(self, trusted, req):
        self.calls.append("social")
        with closing(self.connect()) as conn:
            detail = gate_detail(conn, trusted["internal_user_id"], now=now(),
                                 mode=req.mode, provider=req.provider, model_profile=req.modelProfile)
        if detail:
            raise admission.AdmissionError(403, detail)

    async def capabilities(self):
        self.calls.append("capability")
        return [{"id": "fixture", "modes": ["text_to_image", "edit"], "maxInputReferences": 4}]

    async def billing(self, req, cap):
        self.calls.append("quote")
        return {"chargedTokens": 9, "provider": "fixture"}

    def media(self, req, user):
        self.calls.append("media")
        if self.barrier is not None:
            self.barrier.wait(timeout=5)

    def rate(self, user):
        self.calls.append("rate")

    def charge(self, conn, user, cost, job_id, req, billing):
        self.assertTrue(conn.in_transaction)
        self.calls.append("charge")
        conn.execute("UPDATE users SET token_balance=token_balance-?, tokens_used=tokens_used+?, "
                     "generation_count=generation_count+1 WHERE id=?", (cost, cost, user))
        conn.execute("INSERT INTO token_ledger VALUES (?,?,?,?,?,?)",
                     (uuid.uuid4().hex, user, -cost, "generation", json.dumps({"jobId": job_id, "token_cost": cost}), now()))
        balance = conn.execute("SELECT token_balance FROM users WHERE id=?", (user,)).fetchone()[0]
        return dict(used_daily=False, new_balance=balance, daily_part=0, balance_part=cost,
                    daily_tokens_used=0, daily_tokens_limit=0, daily_tokens_remaining=0)

    def event(self, name, **data):
        self.assertEqual(name, "generation_started")
        self.calls.append("event")

    def accept(self, key="same-key", req=None, user="owner", runtime=None):
        trusted = dict(legacy_user_id=user, internal_user_id="i-" + user, session_id="owned-session")
        return asyncio.run(admission.admit(req or Request(), trusted, key, runtime or self.runtime))

    def state(self):
        with closing(self.connect()) as conn:
            return {
                "jobs": [dict(row) for row in conn.execute("SELECT * FROM jobs ORDER BY id")],
                "ledger": [dict(row) for row in conn.execute("SELECT * FROM token_ledger ORDER BY id")],
                "users": [dict(row) for row in conn.execute("SELECT * FROM users ORDER BY id")],
                "trials": [dict(row) for row in conn.execute("SELECT * FROM generation_trial_reservations ORDER BY job_id")],
            }

    def assert_denied(self, expected, **kwargs):
        with self.assertRaises(admission.AdmissionError) as caught:
            self.accept(**kwargs)
        self.assertEqual(caught.exception.status_code, expected)
        return caught.exception

    def pending_trial(self, consumed=4):
        with closing(self.connect()) as conn, conn:
            conn.execute("INSERT INTO account_verifications VALUES ('i-owner','pending',?)", (now(),))
            for index in range(consumed):
                conn.execute("INSERT INTO generation_trial_reservations VALUES (?, 'i-owner','registered','consumed',?,?)",
                             ("old-" + str(index), now(), now()))

    def test_replay_is_original_response_before_trial_rate_and_provider_preflight(self):
        req = Request(provider="openrouter", modelProfile="fixture")
        accepted = self.accept(req=req)
        self.assertEqual(accepted["tokenCost"], 9)
        before, calls = self.state(), list(self.calls)
        blocked = replace(self.runtime,
            require_generation_social_verification=lambda *args: self.fail("trial rerun"),
            ensure_rate_limit=lambda *args: self.fail("rate rerun"),
            fetch_openrouter_image_capabilities=lambda: self.fail("provider preflight rerun"))
        self.assertEqual(self.accept(req=req, runtime=blocked), accepted)
        self.assertEqual(self.state(), before)
        self.assertEqual(self.calls, calls)
        self.assertEqual(self.wakes.items, [accepted["id"]])
        self.assertEqual(calls.count("charge"), 1)
        self.assertEqual(calls.count("event"), 1)

    def test_changed_payload_is_conflict_but_key_is_owner_scoped(self):
        first = self.accept()
        before = self.state()
        self.assert_denied(409, req=Request(seed=43))
        self.assertEqual(self.state(), before)
        other = self.accept(user="other")
        self.assertNotEqual(first["id"], other["id"])
        self.assertEqual([r["token_balance"] for r in self.state()["users"]], [93, 93])
        self.assertEqual({row["user_id"] for row in self.state()["ledger"]}, {"owner", "other"})

    def test_request_key_is_not_persisted_or_public_and_ids_fit_existing_text_links(self):
        key = "request-secret-fixture-opaque"
        accepted = self.accept(key, Request(_generationAdmission={"acceptedResponse": {"secret": "forged"}},
                                            _workerClaim={"version": 1, "token": "forged"}))
        job_id = accepted["id"]
        self.assertRegex(job_id, r"^job_request_[0-9a-f]{64}$")
        self.assertEqual(len(job_id), 76)
        serialized = json.dumps(self.state()) + json.dumps(accepted) + json.dumps(self.jobs)
        self.assertNotIn(key, serialized)
        self.assertNotIn("forged", serialized)
        with closing(self.connect()) as conn, conn:
            conn.execute("INSERT INTO images VALUES ('image', 'owner', ?, '/image', '/thumb', 704, 704, '{}', ?, NULL)",
                         (job_id, now()))
            response = generation_jobs.get_persisted_job_response(conn, job_id, "owner", model_display_name=str)
            self.assertEqual(response["resultUrl"], "/image")
            self.assertIsNone(generation_jobs.get_persisted_job_response(conn, job_id, "other", model_display_name=str))
        self.assertNotIn(generation_jobs.ADMISSION_METADATA_KEY, json.dumps(response))

    def test_missing_header_preserves_new_job_behavior_and_invalid_header_has_no_effect(self):
        first, second = self.accept(None), self.accept(None)
        self.assertNotEqual(first["id"], second["id"])
        self.assertRegex(first["id"], r"^job_[0-9]{8}_[0-9]{6}_[0-9a-f]{6}$")
        before = self.state()
        for key in ("", "has space", "x" * 129, "line\nbreak", "ключ"):
            with self.subTest(key=repr(key)):
                self.assert_denied(400, key=key)
        self.assertEqual(self.state(), before)

    def test_job_and_charge_roll_back_if_persistence_fails_then_retry_accepts_once(self):
        before = self.state()
        real = generation_jobs.persist_runtime_job
        def fail_after_write(*args, **kwargs):
            real(*args, **kwargs)
            raise RuntimeError("OWNED_PERSIST_FAILURE")
        with patch.object(generation_jobs, "persist_runtime_job", side_effect=fail_after_write):
            with self.assertRaisesRegex(RuntimeError, "OWNED_PERSIST_FAILURE"):
                self.accept()
        self.assertEqual(self.state(), before)
        self.assertEqual(self.wakes.items, [])
        self.assertEqual(self.jobs, {})
        self.assertNotIn("event", self.calls)
        accepted = self.accept()
        self.assertEqual(len(self.state()["ledger"]), 1)
        self.assertEqual(self.wakes.items, [accepted["id"]])

    def test_trial_reservation_and_job_roll_back_together(self):
        self.pending_trial()
        before = self.state()
        with patch.object(generation_jobs, "persist_runtime_job", side_effect=RuntimeError("OWNED_WRITE_FAILURE")):
            with self.assertRaisesRegex(RuntimeError, "OWNED_WRITE_FAILURE"):
                self.accept()
        self.assertEqual(self.state(), before)
        self.assertEqual(self.wakes.items, [])
        accepted = self.accept()
        self.assertEqual(accepted["trialAccess"]["trial_generations_reserved"], 1)
        self.assertEqual(len(self.state()["ledger"]), 0)
        self.assertEqual(self.accept(), accepted)  # The fifth attempt now exhausts the trial.

    def test_charge_exception_rolls_back_its_debit_and_ledger(self):
        before = self.state()
        def failed_charge(*args):
            self.charge(*args)
            raise RuntimeError("OWNED_CHARGE_FAILURE")
        with self.assertRaisesRegex(RuntimeError, "OWNED_CHARGE_FAILURE"):
            self.accept(runtime=replace(self.runtime, charge_generation_tokens=failed_charge))
        self.assertEqual(self.state(), before)
        self.assertEqual((self.wakes.items, self.jobs), ([], {}))

    def test_preflight_error_after_competing_acceptance_replays_that_receipt(self):
        req, winner = Request(provider="openrouter", modelProfile="fixture"), []
        async def failed_capability():
            winner.append(await admission.admit(req,
                {"legacy_user_id": "owner", "internal_user_id": "i-owner"}, "same-key", self.runtime))
            raise RuntimeError("OWNED_PREFLIGHT_FAILURE")
        result = self.accept(req=req, runtime=replace(self.runtime, fetch_openrouter_image_capabilities=failed_capability))
        self.assertEqual(result, winner[0])
        self.assertEqual(len(self.state()["ledger"]), 1)
        self.assertEqual(self.wakes.items, [result["id"]])
        self.assertEqual(self.calls.count("event"), 1)

    def test_metadata_survives_terminal_compaction_and_cannot_be_replaced_by_request_or_caller(self):
        req = Request(inputImage1="data:image/png;base64,YWJj")
        accepted = self.accept(req=req)
        original = json.loads(self.state()["jobs"][0]["settings_json"])[generation_jobs.ADMISSION_METADATA_KEY]
        job = self.jobs[accepted["id"]]
        for status in ("running", "cancelled", "completed"):
            job.update(status=status, completedAt=now() if status != "running" else None)
            with closing(self.connect()) as conn, conn:
                generation_jobs.persist_runtime_job(conn, job, now_iso=now(),
                    request_data=req.model_dump() | {generation_jobs.ADMISSION_METADATA_KEY: {"forged": True}},
                    admission_metadata={"forgedAgain": True})
            stored = json.loads(self.state()["jobs"][0]["settings_json"])
            self.assertEqual(stored[generation_jobs.ADMISSION_METADATA_KEY], original)
            self.assertEqual(self.accept(req=req), accepted)
        self.assertTrue(stored["inputImage1"].startswith("[data-image-omitted:"))
        self.assertNotIn(generation_jobs.ADMISSION_METADATA_KEY, self.jobs[accepted["id"]])

    def test_restart_recovery_refunds_without_reaccepting_or_erasing_mapping(self):
        accepted = self.accept()
        with closing(self.connect()) as conn, conn:
            report = reconcile_stale_generation_jobs(conn, completed_at=now(), refund_job=refund_generation_tokens)
        self.assertEqual((report.failed, report.refunds_created), (1, 1))
        before = self.state()
        fresh_wakes = WakeQueue(self.connect)
        restarted = replace(self.runtime, jobs={}, queue=fresh_wakes)
        self.assertEqual(self.accept(runtime=restarted), accepted)
        self.assertEqual(self.state(), before)
        self.assertEqual(fresh_wakes.items, [])
        self.assertEqual(restarted.jobs, {})
        with closing(self.connect()) as conn:
            current = generation_jobs.get_persisted_job_response(conn, accepted["id"], "owner", model_display_name=str)
        self.assertEqual(current["status"], "failed")
        self.assertEqual(accepted["status"], "queued")

    def test_missing_corrupt_or_owner_mismatched_metadata_fails_closed(self):
        accepted = self.accept()
        valid = json.loads(self.state()["jobs"][0]["settings_json"])
        missing_field = copy.deepcopy(valid)
        del missing_field[generation_jobs.ADMISSION_METADATA_KEY]["acceptedResponse"]["tokenBalance"]
        for malformed in ("{}", "not-json", "[]", json.dumps(missing_field)):
            with self.subTest(malformed=malformed):
                with closing(self.connect()) as conn, conn:
                    conn.execute("UPDATE jobs SET settings_json=?", (malformed,))
                before = self.state()
                self.assert_denied(409)
                self.assertEqual(self.state(), before)
        with closing(self.connect()) as conn, conn:
            conn.execute("UPDATE jobs SET settings_json=?, user_id='other'", (json.dumps(valid),))
        self.assert_denied(409)
        self.assertEqual(self.wakes.items, [accepted["id"]])

    def race(self, key):
        self.barrier = threading.Barrier(2)
        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(self.accept, key) for _ in range(2)]
                return [future.result(timeout=10) for future in futures]
        finally:
            self.barrier = None

    def test_two_connections_race_repeatedly_charge_and_wake_exactly_once(self):
        for index in range(5):
            with self.subTest(repetition=index):
                first, second = self.race("race-" + str(index))
                self.assertEqual(first, second)
                state = self.state()
                self.assertEqual(len(state["jobs"]), index + 1)
                self.assertEqual(len(state["ledger"]), index + 1)
                self.assertEqual(self.wakes.items.count(first["id"]), 1)
                self.assertEqual(self.calls.count("rate"), index + 1)
                self.assertEqual(self.calls.count("event"), index + 1)

    def test_two_connections_race_for_last_trial_returns_original_not_denial(self):
        self.pending_trial()
        first, second = self.race("trial-race")
        self.assertEqual(first, second)
        state = self.state()
        self.assertEqual(len(state["jobs"]), 1)
        self.assertEqual(len(state["trials"]), 5)
        self.assertEqual(len(state["ledger"]), 0)
        self.assertEqual(self.wakes.items, [first["id"]])
        self.assertEqual(self.calls.count("rate"), 1)
        self.assertEqual(self.calls.count("event"), 1)
        self.assertEqual(self.accept("trial-race"), first)
        self.assert_denied(403, key="new-after-exhaustion")

    def test_preflight_rejections_keep_validation_and_billing_boundaries(self):
        for req, runtime, expected in (
            (Request(width=705), self.runtime, 422),
            (Request(mode="outpaint"), self.runtime, 422),
            (Request(provider="openrouter", mode="faceswap"), self.runtime, 501),
            (Request(), replace(self.runtime, get_tariff_config=lambda: {"mini": {"allowed_resolutions": []}}), 403),
        ):
            with self.subTest(expected=expected, req=req):
                before = self.state()
                self.assert_denied(expected, req=req, runtime=runtime)
                self.assertEqual(self.state(), before)
        self.assertEqual(self.wakes.items, [])

    def test_post_commit_event_failure_does_not_repeat_acceptance(self):
        def broken_event(*args, **kwargs):
            raise RuntimeError("OWNED_AUDIT_TRANSPORT_FAILURE")
        runtime = replace(self.runtime, record_event_log=broken_event)
        accepted = self.accept(runtime=runtime)
        self.assertEqual(self.accept(), accepted)
        self.assertEqual(len(self.state()["ledger"]), 1)
        self.assertEqual(self.wakes.items, [accepted["id"]])

    def test_claimed_admission_preserves_receipt_and_rejects_late_persistence(self):
        from app.services import generation_claims as claims
        accepted = self.accept()
        job = copy.deepcopy(self.jobs[accepted["id"]])
        original = json.loads(self.state()["jobs"][0]["settings_json"])[generation_jobs.ADMISSION_METADATA_KEY]
        with claims.claim_job(self.connect, job["id"], "owner", now_iso=now()) as owned:
            self.assertTrue(owned)
            with closing(self.connect()) as conn, conn:
                job.update(status="completed", completedAt=now())
                generation_jobs.persist_runtime_job(conn, job, request_data=Request().model_dump(), now_iso=now())
            stored = json.loads(self.state()["jobs"][0]["settings_json"])
            self.assertEqual(stored[generation_jobs.ADMISSION_METADATA_KEY], original)
            self.assertEqual(self.accept(), accepted)
            before = self.state()
            with closing(self.connect()) as conn, conn:
                with self.assertRaises(claims.GenerationClaimLost):
                    generation_jobs.persist_runtime_job(conn, job | {"status": "running"},
                                                        request_data={}, now_iso=now())
            self.assertEqual(self.state(), before)
        self.assertNotIn(stored[claims.METADATA_KEY]["token"], json.dumps(job) + json.dumps(accepted))

    def test_legacy_claim_requires_bound_writer_but_authorized_cancel_retains_token(self):
        from app.services import generation_claims as claims
        accepted = self.accept(None)
        job = copy.deepcopy(self.jobs[accepted["id"]])
        with claims.claim_job(self.connect, job["id"], "owner", now_iso=now()) as owned:
            self.assertTrue(owned)
        token = json.loads(self.state()["jobs"][0]["settings_json"])[claims.METADATA_KEY]
        data = {"prompt": "unbound write"}
        with closing(self.connect()) as conn, conn:
            with self.assertRaises(claims.GenerationClaimLost):
                generation_jobs.persist_runtime_job(conn, job | {"status": "cancelled"}, request_data=data, now_iso=now())
            self.assertEqual(data, {"prompt": "unbound write"})  # Fence runs before overlay.
            with claims.authorize_cancellation(conn, job["id"], "owner"):
                generation_jobs.persist_runtime_job(conn, job | {"status": "cancelled"},
                    request_data=Request().model_dump() | {claims.METADATA_KEY: {"token": "forged"}}, now_iso=now())
        row = self.state()["jobs"][0]
        self.assertEqual(row["status"], "cancelled")
        self.assertEqual(json.loads(row["settings_json"])[claims.METADATA_KEY], token)
        with closing(self.connect()) as conn:
            public = generation_jobs.get_persisted_job_response(conn, job["id"], "owner", model_display_name=str)
        self.assertNotIn(token["token"], json.dumps(public))


if __name__ == "__main__":
    unittest.main()
