"""Readiness fault acceptance must fail closed and retain financial evidence."""
from __future__ import annotations

import copy
import io
import json
import types
import unittest
from urllib.error import HTTPError
from unittest.mock import Mock, patch

from tools import docker_clean_storage as storage

CID = "c" * 64
READY = {"httpStatus": 200, "ok": True, "ready": True}
FAILED = {"httpStatus": 503, "ok": False, "ready": False, "reasonCode": "MEDIA_NOT_WRITABLE"}


class StorageFaultTests(unittest.TestCase):
    def setUp(self):
        self.before = {"account": {"token_balance": 50, "daily_tokens_used": 0}, "ledger": {"items": []}}
        self.after = {"account": copy.deepcopy(self.before["account"]), "ledger": {"items": [
            {"id": "charge", "spentTokens": 4, "reason": "daily_generation", "jobId": "fixturejob"},
            {"id": "refund", "spentTokens": 0, "reason": "daily_generation_refund", "jobId": "fixturejob"}]}}
        self.calls, self.snapshots = [], [self.before, self.after, self.after]
        self.job_status, self.blocked, self.http_status = "error", True, None
        self.health_before, self.health_during, self.health_after = copy.deepcopy(READY), copy.deepcopy(FAILED), copy.deepcopy(READY)
        self.live, self.phase, self.guest_calls = {"ok": True}, "before", []
        self.container_ids, self.permissions_restored = [CID, CID], True
        self.owner = types.SimpleNamespace(request=self.request)
        self.flow = types.SimpleNamespace(owner=self.owner, guest=types.SimpleNamespace(request=self.guest_request),
            account_snapshot=lambda client: copy.deepcopy(self.snapshots.pop(0)))

    def guest_request(self, method, path, *args, **kwargs):
        self.guest_calls.append((method, path))
        self.assertEqual((method, path), ("GET", "/api/live"))
        return copy.deepcopy(self.live)

    def request(self, method, path, *args, **kwargs):
        self.calls.append((method, path))
        if method == "POST":
            return {"httpStatus": self.http_status} if self.http_status else {"id": "fixturejob", "tokenCost": 4}
        return {"status": self.job_status, "resultImageId": "bad-image" if self.job_status == "completed" else None}

    def run_fault(self):
        self.phase, self.evidence = "before", {}

        def call(shadow, identifier, code):
            if "chmod(0o500)" in code:
                self.phase = "fault"
                return {"blocked": self.blocked}
            if "chmod(493)" in code:
                self.phase = "recovered"
                return {"permissionsRestored": self.permissions_restored}
            return {"mode": 493}

        def health(client):
            return copy.deepcopy({"before": self.health_before,
                "fault": self.health_during, "recovered": self.health_after}[self.phase])

        with patch.object(storage, "backend_id", side_effect=list(self.container_ids)), patch.object(storage.time, "sleep"), \
             patch.object(storage, "container_call", side_effect=call) as transport, patch.object(storage, "media_health", health):
            try:
                return storage.media_fault(object(), self.flow, evidence=self.evidence)
            finally:
                if transport.called:
                    self.assertIn("chmod(493)", transport.call_args.args[2])

    def test_error_and_one_refund_are_required_and_permissions_restored(self):
        result = self.run_fault()
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["charges"], 1)
        self.assertEqual(result["refunds"], 1)
        self.assertEqual(result["readiness"], {"before": READY, "duringFault": FAILED,
            "livenessDuringFault": {"httpStatus": 200, "ok": True}, "recovered": READY, "sameContainer": True})

    def test_unestablished_fault_never_submits_generation(self):
        self.blocked = False
        with self.assertRaisesRegex(storage.StorageError, "STORAGE_FAULT_NOT_ESTABLISHED"):
            self.run_fault()
        self.assertFalse(self.calls)

    def test_false_success_or_financial_duplication_is_rejected(self):
        self.job_status = "completed"
        with self.assertRaisesRegex(storage.StorageError, "STORAGE_FAILURE_FALSE_SUCCESS"):
            self.run_fault()
        self.job_status = "error"
        self.snapshots = [self.before, copy.deepcopy(self.after)]
        self.snapshots[1]["ledger"]["items"].append({"id": "extra", "spentTokens": 4, "reason": "daily_generation"})
        with self.assertRaisesRegex(storage.StorageError, "STORAGE_FAILURE_LEDGER_INVALID"):
            self.run_fault()

    def test_http_rejection_passes_only_with_unchanged_finances(self):
        self.http_status, self.snapshots = 503, [self.before, self.before]
        result = self.run_fault()
        self.assertEqual(result["requestHttpStatus"], 503)
        self.assertEqual(result["charges"], 0)

    def test_healthy_response_during_media_failure_is_rejected_with_evidence(self):
        self.health_during = copy.deepcopy(READY)
        with self.assertRaisesRegex(storage.StorageError, "STORAGE_FAILURE_READINESS_NOT_DEGRADED"):
            self.run_fault()
        self.assertFalse(self.calls)
        self.assertEqual(self.evidence["status"], "FAIL")
        self.assertEqual(self.evidence["readiness"]["duringFault"], READY)
        self.assertEqual(self.evidence["readiness"]["recovered"], READY)

    def test_every_failure_signal_is_required_before_submitting_generation(self):
        for field, wrong in (("httpStatus", 200), ("ok", True), ("ready", True),
                             ("reasonCode", "DATABASE_NOT_READY")):
            with self.subTest(field=field):
                self.health_during = {**FAILED, field: wrong}
                self.snapshots = [self.before, self.after, self.after]
                with self.assertRaisesRegex(storage.StorageError, "STORAGE_FAILURE_READINESS_NOT_DEGRADED"):
                    self.run_fault()
                self.assertFalse(self.calls)
                self.assertEqual(self.evidence["status"], "FAIL")

    def test_liveness_does_not_get_confused_with_readiness(self):
        for live in ({"ok": False}, {"ok": True, "ready": True}):
            with self.subTest(live=live):
                self.live, self.snapshots = live, [self.before, self.after, self.after]
                with self.assertRaisesRegex(storage.StorageError, "STORAGE_LIVENESS_NOT_ALIVE"):
                    self.run_fault()
                self.assertFalse(self.calls)
                self.assertEqual(self.evidence["status"], "FAIL")

    def test_initial_unready_storage_is_not_a_valid_fault_baseline(self):
        self.health_before = copy.deepcopy(FAILED)
        with self.assertRaisesRegex(storage.StorageError, "STORAGE_INITIAL_READINESS_NOT_READY"):
            self.run_fault()
        self.assertFalse(self.calls)
        self.assertEqual(self.evidence["status"], "FAIL")

    def test_readiness_must_recover_in_the_same_container(self):
        self.health_after = copy.deepcopy(FAILED)
        with self.assertRaisesRegex(storage.StorageError, "STORAGE_READINESS_NOT_RECOVERED"):
            self.run_fault()
        self.assertEqual(self.evidence["status"], "FAIL")
        self.assertEqual(self.evidence["refunds"], 1)
        self.assertEqual(self.evidence["readiness"]["recovered"], FAILED)
        self.health_after, self.container_ids = copy.deepcopy(READY), [CID, "d" * 64]
        self.snapshots = [self.before, self.after, self.after]
        with self.assertRaisesRegex(storage.StorageError, "STORAGE_READINESS_NOT_RECOVERED"):
            self.run_fault()
        self.assertEqual(self.evidence["status"], "FAIL")
        self.assertFalse(self.evidence["readiness"]["sameContainer"])

    def test_permissions_restoration_failure_cannot_leave_a_pass_receipt(self):
        self.permissions_restored = False
        with self.assertRaisesRegex(storage.StorageError, "STORAGE_MEDIA_PERMISSIONS_NOT_RESTORED"):
            self.run_fault()
        self.assertEqual(self.evidence["status"], "FAIL")


class HealthReaderTests(unittest.TestCase):
    def setUp(self):
        self.payload = {"ok": False, "app": "izo-asa", "release_id": "fixture-release",
                        "ready": False, "reasonCode": "MEDIA_NOT_WRITABLE"}
        self.origin = "http://127.0.0.1:48125"

    def read_response(self, status, payload):
        raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        body = io.BytesIO(raw)
        body.status = status
        opener = Mock()
        if status == 200:
            opener.open.return_value = body
        else:
            opener.open.side_effect = HTTPError(self.origin + "/api/health", status, "fixture", {}, body)
        try:
            return storage.media_health(types.SimpleNamespace(origin=self.origin, opener=opener))
        finally:
            self.assertTrue(body.closed)
            request = opener.open.call_args.args[0]
            self.assertEqual(request.get_method(), "GET")
            self.assertEqual(request.full_url, self.origin + "/api/health")
            self.assertEqual(opener.open.call_args.kwargs, {"timeout": 8})

    def test_expected_503_reads_only_the_public_health_fields(self):
        self.assertEqual(self.read_response(503, self.payload), FAILED)
        worker = {**self.payload, "reasonCode": "GENERATION_WORKER_UNAVAILABLE"}
        self.assertEqual(self.read_response(503, worker), {**FAILED, "reasonCode": worker["reasonCode"]})
        healthy = {key: value for key, value in self.payload.items() if key != "reasonCode"}
        healthy.update(ok=True, ready=True)
        self.assertEqual(self.read_response(200, healthy), READY)

    def test_invalid_or_private_error_payloads_are_never_published(self):
        candidates = [b"private operator diagnostic", b"x" * 4097,
            {**self.payload, "database_path": "/private/production.sqlite3"},
            {**self.payload, "reasonCode": "/private/production.sqlite3"},
            {**self.payload, "reasonCode": ["MEDIA_NOT_WRITABLE"]},
            {**self.payload, "ok": "false"}, {**self.payload, "ready": 0},
            {"detail": "private operator diagnostic"}, [self.payload]]
        for candidate in candidates:
            with self.subTest(candidate_type=type(candidate).__name__), \
                 self.assertRaisesRegex(storage.StorageError, "^STORAGE_HEALTH_RESPONSE_INVALID$"):
                self.read_response(503, candidate)

    def test_other_http_errors_are_closed_without_reading_their_bodies(self):
        for status in (401, 403, 404, 500):
            with self.subTest(status=status):
                body = Mock()
                opener = Mock(open=Mock(side_effect=HTTPError(self.origin + "/api/health", status, "fixture", {}, body)))
                with self.assertRaisesRegex(storage.StorageError, "^STORAGE_HEALTH_HTTP_STATUS_INVALID$"):
                    storage.media_health(types.SimpleNamespace(origin=self.origin, opener=opener))
                body.read.assert_not_called()
                body.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
