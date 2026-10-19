"""Durable worker ownership, expiry and recovery using independent SQLite writers."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from copy import deepcopy
from dataclasses import replace
import json
import threading
import time
import unittest

from app.services import generation_accounting as accounting, generation_claims as claims
from app.services import generation_leases as leases, generation_recovery as recovery
from app.services.generation_worker import GenerationClaimLost
from test_generation_claims import ClaimDatabase, NOW


class DurableLeaseTests(ClaimDatabase, unittest.TestCase):
    def metadata(self, job_id="job_1"):
        return json.loads(self.state(job_id)["settings_json"])[claims.METADATA_KEY]

    def expire(self, *, now=None):
        return leases.expire(self.connect, accounting.refund_generation_tokens, now=now)

    def financial(self):
        with closing(self.open()) as conn:
            user = dict(conn.execute("SELECT * FROM users WHERE id='user_1'").fetchone())
            refunds = [json.loads(row[0]) for row in conn.execute(
                "SELECT meta_json FROM token_ledger WHERE reason='generation_refund'")]
        return user, refunds

    def test_two_connections_compete_for_oldest_durable_request_without_python_queue(self):
        self.seed("job_a", charge=7)
        self.seed("job_b", "user_2")
        barrier = threading.Barrier(2)
        def contender(worker):
            barrier.wait(timeout=2)
            return leases.claim_next(self.connect, worker)
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(contender, ("a" * 32, "b" * 32)))
        grants = [value for value in outcomes if value is not None]
        self.assertEqual(len(grants), 1)
        claim, job = grants[0]
        self.assertEqual((claim.job_id, job["id"], job["request"]["prompt"]), ("job_a", "job_a", "owned"))
        self.assertEqual(job["tokenCost"], 7)
        self.assertNotIn(claims.METADATA_KEY, job["request"])
        self.assertEqual(self.state("job_b")["status"], "queued")
        # The worker grant has committed and holds no writer across provider I/O.
        with closing(self.open()) as other, other:
            other.execute("UPDATE users SET token_balance=99 WHERE id='user_2'")
        self.assertEqual(leases.DurableWakeQueue(self.connect).qsize(), 1)

    def test_renew_and_provider_command_preserve_fence_and_do_not_double_charge(self):
        self.seed(charge=7)
        claim, job = leases.claim_next(self.connect, "a" * 32, lease_seconds=2)
        before = self.metadata()
        leases.renew(self.connect, claim, lease_seconds=30)
        leases.command_started(self.connect, claim)
        after = self.metadata()
        self.assertEqual(after["token"], before["token"])
        self.assertGreater(after["leaseUntil"], before["leaseUntil"])
        self.assertEqual(after["providerCommands"], 1)
        with claims.bind_claim(claim), claims.transaction(self.connect):
            job.update(status="completed", resultImageId="owned-result")
            self.persist(job)
        self.assertEqual(self.counts()["token_ledger"], 1)
        self.assertEqual(self.expire(now=time.time() + 100), [])
        self.assertNotIn(claims.METADATA_KEY, json.dumps(self.read_job("job_1", "user_1")))

    def test_expiry_refunds_once_releases_trial_and_blocks_stale_completion(self):
        self.seed(charge=7)
        with closing(self.open()) as conn, conn:
            conn.execute("INSERT INTO generation_trial_reservations VALUES ('job_1','reserved',NULL)")
        claim, job = leases.claim_next(self.connect, "a" * 32)
        leases.command_started(self.connect, claim)
        leases.abandon(self.connect, claim)
        self.assertEqual(self.expire(), ["job_1"])
        self.assertEqual(self.expire(), [])
        self.assertIsNone(leases.claim_next(self.connect, "b" * 32))
        with claims.bind_claim(claim):
            with self.assertRaises(GenerationClaimLost), claims.transaction(self.connect):
                self.fail("late media/accounting finalization was admitted")
            job.update(status="completed", resultImageId="late")
            with self.assertRaises(GenerationClaimLost):
                self.persist(job)
        user, refunds = self.financial()
        self.assertEqual((user["token_balance"], user["tokens_used"], user["generation_count"]), (100, 0, 0))
        self.assertEqual([item["reason"] for item in refunds], ["worker_lease_expired"])
        self.assertEqual(self.state()["status"], "failed")
        self.assertIsNone(self.state()["result_image_id"])
        self.assertEqual(self.metadata()["lossReason"], "worker_connection_lost")
        with closing(self.open()) as conn:
            self.assertEqual(conn.execute("SELECT state FROM generation_trial_reservations").fetchone()[0], "released")

    def test_heartbeat_deadline_and_invalid_deadlines_fail_closed(self):
        for index, deadline in enumerate((0, float("nan"), float("inf"), "future", True)):
            with self.subTest(deadline=deadline):
                job_id = f"job_{index}"
                self.seed(job_id)
                claim, _job = leases.claim_next(self.connect, "a" * 32)
                metadata = self.metadata(job_id)
                metadata["leaseUntil"] = deadline
                settings = json.loads(self.state(job_id)["settings_json"])
                settings[claims.METADATA_KEY] = metadata
                with closing(self.open()) as conn, conn:
                    conn.execute("UPDATE jobs SET settings_json=? WHERE id=?", (json.dumps(settings), job_id))
                with self.assertRaises(GenerationClaimLost):
                    leases.command_started(self.connect, claim)
                self.assertEqual(self.expire(), [job_id])
                self.assertEqual(self.metadata(job_id)["lossReason"], "worker_heartbeat_expired")

    def test_foreign_worker_or_token_cannot_renew_dispatch_or_revoke_the_owner(self):
        self.seed()
        claim, _job = leases.claim_next(self.connect, "a" * 32)
        before = self.metadata()
        for impostor in (replace(claim, worker_id="b" * 32), replace(claim, token="wrong"),
                         replace(claim, user_id="user_2")):
            with self.subTest(impostor=impostor.worker_id):
                with self.assertRaises(GenerationClaimLost):
                    leases.renew(self.connect, impostor)
                with self.assertRaises(GenerationClaimLost):
                    leases.command_started(self.connect, impostor)
                leases.abandon(self.connect, impostor)
        self.assertEqual(self.metadata(), before)

    def test_server_restart_preserves_queued_payload_but_fails_uncertain_active_job_once(self):
        self.seed("job_active", charge=7)
        leases.claim_next(self.connect, "a" * 32)
        queued = self.seed("job_queued", "user_2")
        queued["request"].update(prompt="durable after restart", initImage="data:image/png;base64,owned")
        self.persist(queued)
        before = deepcopy(self.state("job_queued"))
        for expected in (1, 0):
            with closing(self.open()) as conn, conn:
                report = recovery.reconcile_stale_generation_jobs(conn, completed_at=NOW,
                    refund_job=accounting.refund_generation_tokens, preserve_queued=True)
            self.assertEqual(report.failed, expected)
            self.assertEqual(report.refunds_created, expected)
        self.assertEqual(self.state("job_queued"), before)
        claim, restored = leases.claim_next(self.connect, "b" * 32)
        self.assertEqual(claim.job_id, "job_queued")
        self.assertEqual(restored["request"]["prompt"], "durable after restart")
        self.assertEqual(restored["request"]["initImage"], "data:image/png;base64,owned")
        self.assertEqual(len(self.financial()[1]), 1)

    def test_combined_restart_retains_existing_fail_and_refund_queued_policy(self):
        self.seed(charge=7)
        with closing(self.open()) as conn, conn:
            report = recovery.reconcile_stale_generation_jobs(conn, completed_at=NOW,
                refund_job=accounting.refund_generation_tokens)
        self.assertEqual((report.checked, report.failed, report.refunds_created), (1, 1, 1))
        self.assertEqual(self.state()["status"], "failed")


if __name__ == "__main__":
    unittest.main()
