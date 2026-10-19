"""Real read-only SQLite fixtures reject false full-ID accounting evidence.

Database writes create only temporary unit-test fixtures, never installed users.
Docker, application handlers, models, and hosted CI are not run here.
"""
from contextlib import nullcontext
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from tools import docker_d3_ledger as subject
from tools.docker_clean_install import save
from tools.docker_shadow_product import ProductError, ProductFlow

OWNER = ["owned-user", "owned-internal"]
IMAGE, VIDEO = "job_123456_owned-image", "video_20261018_owned-video"
PRIVATE = "private-prompt cookie=value https://private.invalid/secret"
CONTEXT = {"sourceSha": "a" * 40, "project": "izo-asa-shadow-d3-ledger", "api": {
    "containerId": "b" * 64, "imageId": "sha256:" + "c" * 64, "hostPid": 1234,
    "startedAt": "2026-10-18T00:00:00Z", "restartCount": 0}}


def browser():
    def accounting(cost, balance, daily):
        return {"status": "PASS", "tokenCost": cost, "mainBalanceDebit": balance,
                "dailyBudgetDebit": daily, "refundDelta": 0}
    return {"status": "PASS", "image": {"jobId": IMAGE, "tokenCost": 2}, "checks": {
        "chat": {"firstRequestId": "first-request", "secondRequestId": "second-request",
                 "failedRequestId": "failed-request"},
        "chatImage": {"jobId": IMAGE, "requestId": "image-request", "accounting": accounting(2, 0, 2)},
        "video": {"jobId": VIDEO, "tokenCost": 3, "accounting": accounting(3, 2, 1)}}}


class LedgerDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "owned-unit.sqlite3"
        self.writer = sqlite3.connect(self.path)
        self.addCleanup(self.writer.close)
        self.writer.executescript("""
            CREATE TABLE users(id TEXT PRIMARY KEY,internal_user_id TEXT,token_balance INTEGER,
                daily_tokens_used INTEGER,tokens_used INTEGER,generation_count INTEGER,last_daily_reset TEXT);
            CREATE TABLE jobs(id TEXT PRIMARY KEY,user_id TEXT,mode TEXT,provider TEXT,status TEXT);
            CREATE TABLE token_ledger(id TEXT PRIMARY KEY,user_id TEXT,delta INTEGER,reason TEXT,meta_json TEXT,created_at TEXT);
        """)
        self.writer.execute("INSERT INTO users VALUES (?,?,1000,3,3,1,'2026-10-18')", OWNER)
        self.row("prior-charge", {"jobId": "prior-job", "token_cost": 3, "private": PRIVATE})
        self.writer.commit()
        namespace = {}
        exec(subject.QUERY, namespace)
        self.capture = namespace["capture"]

    def row(self, identifier, meta, *, reason="daily_generation", delta=0, user=OWNER[0]):
        self.writer.execute("INSERT INTO token_ledger VALUES (?,?,?,?,?,'2026-10-18T00:00:00Z')",
                            (identifier, user, delta, reason, json.dumps(meta)))

    def snapshot(self, jobs=(), owner=OWNER):
        self.writer.commit()
        conn = sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True)
        try:
            result = self.capture(conn, list(owner), list(jobs))
            self.assertEqual(conn.execute("PRAGMA query_only").fetchone()[0], 1)
            with self.assertRaises(sqlite3.OperationalError):
                conn.execute("UPDATE users SET token_balance=0")
            return {**result, **deepcopy(CONTEXT)}
        finally:
            conn.close()

    def completed(self):
        before = self.snapshot()
        for job, mode, provider in ((IMAGE, "text_to_image", "comfyui"), (VIDEO, "text_to_video", "local_ltx")):
            self.writer.execute("INSERT INTO jobs VALUES (?,?,?,?,'completed')", (job, OWNER[0], mode, provider))
        for name in ("first", "second", "failed", "image"):
            self.row("chat-" + name, {"request_id": name + "-request", "mode": "phone_chat", "provider": "local",
                "token_cost": 0.0, "daily_part": 0, "balance_part": 0}, reason="free_chat")
        self.row("chat-failure-refund", {"request_id": "failed-request", "charged_ledger_id": "chat-failed",
                                       "daily_part": 0, "balance_part": 0}, reason="chat_refund")
        self.row("image-charge", {"jobId": IMAGE, "mode": "text_to_image", "provider": "comfyui",
            "token_cost": 2, "daily_part": 2, "balance_part": 0})
        self.row("video-charge", {"jobId": VIDEO, "mode": "text_to_video", "provider": "local_ltx",
            "token_cost": 3, "daily_part": 1, "balance_part": 2}, reason="generation", delta=-2)
        self.writer.execute("UPDATE users SET token_balance=998,daily_tokens_used=6,tokens_used=8,generation_count=3")
        return before

    def replace_meta(self, identifier, **updates):
        row = self.writer.execute("SELECT meta_json FROM token_ledger WHERE id=?", (identifier,)).fetchone()
        meta = json.loads(row[0]); meta.update(updates)
        self.writer.execute("UPDATE token_ledger SET meta_json=? WHERE id=?", (json.dumps(meta), identifier))

    def test_read_only_real_rows_tie_two_exact_jobs_to_mixed_and_daily_debits(self):
        before = self.completed()
        after = self.snapshot([IMAGE, VIDEO])
        receipt = subject.settle_private_ledger(before, after, browser())
        self.assertEqual(receipt["status"], "PASS")
        self.assertEqual(receipt["accountDebit"], {"mainBalance": 2, "dailyBudget": 3, "tokensUsed": 5})
        self.assertEqual(receipt["zeroTokenChatRefunds"], 1)
        self.assertEqual(receipt["priorRowsUnchanged"], 1)
        self.assertEqual(receipt["jobs"]["image"]["jobIdSha256"], subject.identifier_sha(IMAGE))
        for source in (before, after, receipt):
            self.assertNotIn(PRIVATE, json.dumps(source))
            self.assertNotIn(IMAGE, json.dumps(source))
            self.assertNotIn("image-charge", json.dumps(source))

    def test_single_image_mode_reads_keep_full_ids_and_do_not_expand_two_job_bound(self):
        for mode in ("edit", "paint", "faceswap"):
            job = "job_common_" + mode
            self.writer.execute("INSERT INTO jobs VALUES (?,?,?,'comfyui','completed')", (job, OWNER[0], mode))
            self.row("charge-" + mode, {"jobId": job, "mode": mode, "provider": "comfyui",
                                      "token_cost": 2, "daily_part": 2, "balance_part": 0})
            snapshot = subject.validated(self.snapshot([job]))
            self.assertEqual(snapshot["requestedJobSha256"], [subject.identifier_sha(job)])
            self.assertEqual(snapshot["jobs"][subject.identifier_sha(job)]["mode"], mode)
            charged = next(row for row in snapshot["ledger"] if row["jobSha256"] == subject.identifier_sha(job))
            self.assertEqual(charged["mode"], mode)
        with self.assertRaisesRegex(RuntimeError, "PRIVATE_LEDGER_INVALID"):
            self.snapshot(["job_common_" + mode for mode in ("edit", "paint", "faceswap")])

    def test_same_public_ten_character_prefix_cannot_substitute_another_full_job(self):
        before = self.completed()
        impostor = IMAGE[:10] + "_different-full-id"
        self.assertEqual(IMAGE[:10], impostor[:10])
        self.replace_meta("image-charge", jobId=impostor)
        with self.assertRaisesRegex(ProductError, "SINGLE_CHARGE_NOT_PROVEN"):
            subject.settle_private_ledger(before, self.snapshot([IMAGE, VIDEO]), browser())

    def test_duplicate_exact_charge_and_exact_generation_refund_both_fail(self):
        before = self.completed()
        for reason in ("daily_generation", "daily_generation_refund"):
            self.row("extra", {"jobId": IMAGE, "token_cost": 2, "daily_part": 2, "balance_part": 0}, reason=reason)
            with self.subTest(reason=reason), self.assertRaisesRegex(ProductError, "SINGLE_CHARGE_NOT_PROVEN"):
                subject.settle_private_ledger(before, self.snapshot([IMAGE, VIDEO]), browser())
            self.writer.execute("DELETE FROM token_ledger WHERE id='extra'")

    def test_foreign_owner_and_foreign_owned_job_never_enter_snapshot(self):
        self.completed()
        self.writer.execute("UPDATE jobs SET user_id='foreign-user' WHERE id=?", (VIDEO,))
        for jobs, owner in (([IMAGE, VIDEO], OWNER), ([], [OWNER[0], "foreign-internal"])):
            with self.subTest(owner=owner), self.assertRaisesRegex(RuntimeError, "PRIVATE_LEDGER_INVALID"):
                self.snapshot(jobs, owner)

    def test_changed_prior_metadata_is_rejected_even_when_public_projection_is_identical(self):
        before = self.completed()
        self.replace_meta("prior-charge", private="different-private-value")
        with self.assertRaisesRegex(ProductError, "PRIOR_ROWS_CHANGED"):
            subject.settle_private_ledger(before, self.snapshot([IMAGE, VIDEO]), browser())

    def test_boolean_cost_or_extra_private_field_cannot_be_written_as_valid_evidence(self):
        sample = self.snapshot()
        boolean = deepcopy(sample); boolean["ledger"][0]["tokenCost"] = True
        extra = {**sample, "rawProviderError": PRIVATE}
        for item in (boolean, extra):
            with self.subTest(kind="boolean" if item is boolean else "extra"), self.assertRaises(ProductError) as error:
                subject.validated(item)
            self.assertNotIn(PRIVATE, str(error.exception))

    def test_extra_grant_is_rejected_even_if_generation_debits_are_correct(self):
        before = self.completed()
        self.row("unexpected-grant", {}, reason="payment_grant", delta=100)
        with self.assertRaisesRegex(ProductError, "EXTRA_OPERATIONS"):
            subject.settle_private_ledger(before, self.snapshot([IMAGE, VIDEO]), browser())

    def test_actual_balance_and_public_per_job_debit_are_independent_gates(self):
        before = self.completed()
        after = self.snapshot([IMAGE, VIDEO])
        changed = deepcopy(after); changed["account"]["token_balance"] += 1
        with self.assertRaisesRegex(ProductError, "PRIVATE_ACCOUNT_DEBIT_MISMATCH"):
            subject.settle_private_ledger(before, changed, browser())
        public = browser(); public["checks"]["video"]["accounting"]["mainBalanceDebit"] = 1
        with self.assertRaisesRegex(ProductError, "PRIVATE_PUBLIC_ACCOUNTING_MISMATCH"):
            subject.settle_private_ledger(before, after, public)

    def test_zero_chat_refund_must_reference_the_exact_failed_reservation(self):
        before = self.completed()
        self.replace_meta("chat-failure-refund", charged_ledger_id="chat-first")
        with self.assertRaisesRegex(ProductError, "PRIVATE_CHAT_REFUND_MISMATCH"):
            subject.settle_private_ledger(before, self.snapshot([IMAGE, VIDEO]), browser())

    def test_query_rejects_truncation_oversized_metadata_and_conflicting_id_aliases(self):
        for number in range(64):
            self.row("over-limit-" + str(number), {})
        with self.assertRaisesRegex(RuntimeError, "PRIVATE_LEDGER_INVALID"):
            self.snapshot()
        self.writer.execute("DELETE FROM token_ledger WHERE id LIKE 'over-limit-%'")
        for patch in ({"private": PRIVATE * 500}, {"jobId": "one-job", "job_id": "another-job"}):
            self.writer.execute("UPDATE token_ledger SET meta_json='{}' WHERE id='prior-charge'")
            self.replace_meta("prior-charge", **patch)
            with self.subTest(patch=tuple(patch)), self.assertRaisesRegex(RuntimeError, "PRIVATE_LEDGER_INVALID"):
                self.snapshot()

    def test_saved_after_evidence_and_completed_image_survive_failed_full_id_proof(self):
        before = self.completed()
        self.replace_meta("image-charge", jobId=IMAGE[:10] + "_wrong-full-id")
        after = self.snapshot([IMAGE, VIDEO])
        original = {"status": "PASS", "image": {"jobId": IMAGE}, "browser": browser()}
        run = Mock(return_value=original)
        reader = Mock(side_effect=[before, after])
        directory = Path(self.directory.name) / "evidence"
        with patch.object(subject, "private_ledger_reader", return_value=reader):
            result = subject.prove_browser_ledger(SimpleNamespace(sha=CONTEXT["sourceSha"], project=CONTEXT["project"]),
                {}, object(), directory, browser_probe=run, api_identity=Mock(), wallclock=lambda _: nullcontext(), save=save)
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["image"]["jobId"], IMAGE)
        run.assert_called_once_with()
        self.assertEqual([call.args[0] for call in reader.call_args_list], [[], [IMAGE, VIDEO]])
        for name in ("before", "after"):
            content = (directory / (name + ".json")).read_bytes()
            self.assertEqual(result["privateLedger"][name]["sha256"], hashlib.sha256(content).hexdigest())
            self.assertNotIn(PRIVATE.encode(), content)
        self.assertEqual(json.loads((directory / "receipt.json").read_text())["status"], "FAIL")


class CallbackAdmissionTests(unittest.TestCase):
    def setup_reader(self):
        flow = object.__new__(ProductFlow)
        flow.project, flow.source_sha = CONTEXT["project"], CONTEXT["sourceSha"]
        flow.origin = "http://127.0.0.1:48181"
        flow.owner = SimpleNamespace(origin=flow.origin, request=Mock(return_value=dict(zip(
            ("legacy_user_id", "internal_user_id"), OWNER))))
        shadow = SimpleNamespace(project=flow.project, sha=flow.source_sha, web_port=48181, fixture=True,
            config=Mock(return_value={"services": {"backend": {"environment": {
                "IZO_SHADOW_FIXTURE": "controlled-chat-video-v1"}}}}), docker=Mock())
        admission = Mock(return_value=deepcopy(CONTEXT["api"]))
        clock = Mock(side_effect=lambda seconds: nullcontext())
        reader = subject.private_ledger_reader(shadow, {}, flow, api_identity=admission, wallclock=clock)
        return reader, shadow, admission, clock

    def test_each_read_rechecks_exact_api_identity_before_any_docker_exec(self):
        reader, shadow, admission, clock = self.setup_reader()
        admission.return_value = {**CONTEXT["api"], "hostPid": 9876}
        with self.assertRaisesRegex(ProductError, "PRIVATE_LEDGER_API_CHANGED"):
            reader([IMAGE, VIDEO])
        shadow.docker.assert_not_called()
        self.assertEqual(admission.call_count, 2)
        clock.assert_called_once_with(8)

    def test_more_than_two_exact_jobs_cannot_start_a_probe(self):
        reader, shadow, admission, clock = self.setup_reader()
        with self.assertRaisesRegex(ProductError, "PRIVATE_LEDGER_JOB_BOUND"):
            reader([IMAGE, VIDEO, "third-job"])
        shadow.docker.assert_not_called(); clock.assert_not_called()
        self.assertEqual(admission.call_count, 1)

    def test_oversized_wire_output_is_not_returned_or_echoed(self):
        reader, shadow, _admission, _clock = self.setup_reader()
        shadow.docker.return_value = PRIVATE * 2000
        with self.assertRaisesRegex(ProductError, "PRIVATE_LEDGER_RECEIPT_LIMIT") as error:
            reader([])
        self.assertNotIn(PRIVATE, str(error.exception))
        self.assertEqual(shadow.docker.call_args.kwargs["timeout"], 8)

    def test_browser_is_never_started_without_a_private_baseline(self):
        run = Mock()
        reader = Mock(side_effect=ProductError("D3_PRIVATE_LEDGER_API_CHANGED"))
        with tempfile.TemporaryDirectory() as temporary, patch.object(subject, "private_ledger_reader", return_value=reader):
            with self.assertRaisesRegex(ProductError, "PRIVATE_LEDGER_API_CHANGED"):
                subject.prove_browser_ledger(SimpleNamespace(sha=CONTEXT["sourceSha"], project=CONTEXT["project"]),
                    {}, object(), Path(temporary) / "evidence", browser_probe=run, api_identity=Mock(),
                    wallclock=lambda _: nullcontext(), save=save)
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
