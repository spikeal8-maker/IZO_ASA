"""Real SQLite receipt matching plus mocked normal-flow checkpoints; no installed runtime claim."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock, patch

from tools import docker_d3_image_ledger as subject
from tools import docker_d3_image_modes as modes
from tools import docker_d3_ledger as reader_source
from tools import test_docker_d3_image_modes as existing
from tools.docker_shadow_product import ProductError

OWNER = [existing.OWNED_ID, "owned-internal"]
CONTEXT = {"sourceSha": existing.ATTESTATION["sourceSha"], "project": existing.ATTESTATION["project"],
    "api": {"containerId": "c" * 64, "imageId": "sha256:" + "d" * 64, "hostPid": 123,
            "startedAt": "2026-10-18T00:00:00.000000000Z", "restartCount": 0}}
PRIVATE = "private-canary /srv/private/provider.key token=do-not-emit"


class ImageLedgerTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.database = self.root / "unit.sqlite3"
        self.writer = sqlite3.connect(self.database)
        self.addCleanup(self.writer.close)
        self.writer.executescript("""
            CREATE TABLE users(id TEXT PRIMARY KEY,internal_user_id TEXT,token_balance INTEGER,
                daily_tokens_used INTEGER,tokens_used INTEGER,generation_count INTEGER,last_daily_reset TEXT);
            CREATE TABLE jobs(id TEXT PRIMARY KEY,user_id TEXT,mode TEXT,provider TEXT,status TEXT);
            CREATE TABLE token_ledger(id TEXT PRIMARY KEY,user_id TEXT,delta INTEGER,reason TEXT,meta_json TEXT,created_at TEXT);
        """)
        self.writer.execute("INSERT INTO users VALUES (?,?,100,0,0,0,'2026-10-18')", OWNER)
        namespace = {}
        exec(reader_source.QUERY, namespace)
        self.capture = namespace["capture"]

    def row(self, ledger_id, metadata, *, delta=0, reason="generation"):
        self.writer.execute("INSERT INTO token_ledger VALUES (?,?,?,?,?,'2026-10-18T00:00:00Z')",
                            (ledger_id, OWNER[0], delta, reason, json.dumps(metadata)))

    def snapshot(self, jobs=()):
        self.writer.commit()
        connection = sqlite3.connect(self.database.as_uri() + "?mode=ro", uri=True)
        try:
            value = self.capture(connection, OWNER, list(jobs))
            self.assertEqual(connection.execute("PRAGMA query_only").fetchone()[0], 1)
            with self.assertRaises(sqlite3.OperationalError):
                connection.execute("UPDATE users SET token_balance=0")
            return {**value, **deepcopy(CONTEXT)}
        finally:
            connection.close()

    def complete(self, mode="edit", index=1, main=1, daily=0):
        job, cost = f"job-owned-{index}", main + daily
        self.writer.execute("INSERT INTO jobs VALUES (?,?,?,'comfyui','completed')", (job, OWNER[0], mode))
        self.row(f"charge-{index}", {"jobId": job, "mode": mode, "provider": "comfyui", "private": PRIVATE,
            "token_cost": cost, "daily_part": daily, "balance_part": main}, delta=-main,
            reason="daily_generation" if daily == cost else "generation")
        self.writer.execute("UPDATE users SET token_balance=token_balance-?,daily_tokens_used=daily_tokens_used+?,"
                            "tokens_used=tokens_used+?,generation_count=generation_count+1", (main, daily, cost))
        balance, used = self.writer.execute("SELECT token_balance,daily_tokens_used FROM users").fetchone()
        return {"id": job, "mode": mode, "provider": "comfyui", "tokenCost": cost,
                "tokenBalance": balance, "dailyTokensUsed": used, "mainBalanceTokenPart": main, "dailyTokenPart": daily}, {
            "singleCharge": True, "fullJobLedgerLinkage": "NOT_VERIFIED", "tokenCost": cost,
            "mode": mode, "provider": "comfyui", "mainBalanceDebit": main, "dailyBudgetDebit": daily, "refundDelta": 0}

    def metadata(self, ledger_id, **updates):
        old = json.loads(self.writer.execute("SELECT meta_json FROM token_ledger WHERE id=?", (ledger_id,)).fetchone()[0])
        old.update(updates)
        self.writer.execute("UPDATE token_ledger SET meta_json=? WHERE id=?", (json.dumps(old), ledger_id))

    def chain(self):
        values = [self.snapshot()]
        for index, mode in enumerate(modes.MODES, 1):
            started, _ = self.complete(mode, index)
            values.append(self.snapshot([started["id"]]))
        return values

    def run_series(self, values, *, callback=None, checkpoint=None, directory=None):
        flow, responses, public, provider = existing.ImageModeEvidenceTests().prepared_series()
        private = callback if callback is not None else Mock(side_effect=values)
        output = directory if directory is not None else self.root / "receipts"
        result = subject.prove_image_modes_private(flow, existing.SOURCE, output,
            attestation=existing.ATTESTATION, provider_receipt=provider,
            private_ledger=private, checkpoint=checkpoint)
        return result, flow, private, output

    def test_all_three_modes_use_four_reads_and_immutable_exact_id_chain(self):
        checkpoints = []
        result, _flow, private, directory = self.run_series(self.chain(), checkpoint=checkpoints.append)
        self.assertEqual([call.args[0] for call in private.call_args_list],
                         [[], ["job-owned-1"], ["job-owned-2"], ["job-owned-3"]])
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["fullJobLedgerLinkage"], "NOT_VERIFIED")
        proof = result["privateLedger"]
        self.assertEqual((proof["status"], proof["fullJobLedgerLinkage"]), ("PASS", "PASS"))
        for index, mode in enumerate(modes.MODES):
            case = proof["modes"][mode]
            self.assertEqual(case["jobIdSha256"], subject.identifier_sha(f"job-owned-{index + 1}"))
            self.assertEqual(case["beforeSnapshotSha256"], proof["snapshots"][index]["sha256"])
            self.assertEqual(case["afterSnapshotSha256"], proof["snapshots"][index + 1]["sha256"])
            self.assertEqual(result["modes"][mode]["accounting"]["fullJobLedgerLinkage"], "NOT_VERIFIED")
        for reference in [*proof["snapshots"], proof["receipt"]]:
            data = (directory / reference["receipt"]).read_bytes()
            self.assertEqual(reference["sha256"], hashlib.sha256(data).hexdigest())
            self.assertLessEqual(len(data), subject.LIMIT)
            self.assertNotIn(PRIVATE.encode(), data)
            self.assertNotIn(OWNER[0].encode(), data)
            self.assertNotIn(b"job-owned-", data)
        self.assertEqual(len(list(directory.iterdir())), 5)
        self.assertEqual(checkpoints[0]["privateLedger"]["modes"], {})
        self.assertEqual(checkpoints[-1], result)

    def test_same_public_prefix_acceptance_cannot_substitute_full_job(self):
        before = self.snapshot()
        started, public = self.complete()
        impostor = started["id"][:10] + "foreign-suffix"
        self.assertEqual(impostor[:10], started["id"][:10])
        self.metadata("charge-1", jobId=impostor)
        # Characterization: the unchanged public/summary boundary cannot distinguish these two IDs.
        legacy = existing.ImageModeEvidenceTests().snapshots()
        self.assertTrue(modes.settlement(*legacy)["singleCharge"])
        with self.assertRaisesRegex(ProductError, "SINGLE_CHARGE_NOT_PROVEN"):
            subject.settle_image_ledger(before, self.snapshot([started["id"]]), started, public)

    def test_daily_then_mixed_partitions_bind_actual_counters(self):
        previous = self.snapshot()
        for index, (main, daily) in enumerate(((0, 3), (2, 1), (1, 0)), 1):
            started, public = self.complete(modes.MODES[index - 1], index, main, daily)
            after = self.snapshot([started["id"]])
            result = subject.settle_image_ledger(previous, after, started, public)
            self.assertEqual((result["mainBalanceDebit"], result["dailyBudgetDebit"]), (main, daily))
            self.assertEqual(result["priorRowsUnchanged"], index - 1)
            previous = after

    def test_duplicate_refund_and_zero_extra_operations_all_fail(self):
        before = self.snapshot()
        started, public = self.complete()
        for reason in ("generation", "generation_refund", "free_chat", "chat_refund", "payment_grant"):
            with self.subTest(reason=reason):
                self.row("extra", {"jobId": started["id"]} if reason.startswith("generation") else {}, reason=reason)
                with self.assertRaisesRegex(ProductError, "SINGLE_CHARGE_NOT_PROVEN"):
                    subject.settle_image_ledger(before, self.snapshot([started["id"]]), started, public)
                self.writer.execute("DELETE FROM token_ledger WHERE id='extra'")

    def test_previous_raw_metadata_digest_must_remain_unchanged(self):
        self.row("prior", {"private": PRIVATE}, reason="payment_grant")
        before = self.snapshot()
        started, public = self.complete()
        self.metadata("prior", private="changed unseen metadata")
        with self.assertRaisesRegex(ProductError, "PRIOR_ROWS_CHANGED"):
            subject.settle_image_ledger(before, self.snapshot([started["id"]]), started, public)

    def test_previously_charged_full_job_cannot_be_reused_for_next_mode(self):
        first, _ = self.complete()
        before = self.snapshot([first["id"]])
        second, public = self.complete("paint", 2)
        after = self.snapshot([second["id"]])
        first_hash, second_hash = subject.identifier_sha(first["id"]), subject.identifier_sha(second["id"])
        after["requestedJobSha256"] = [first_hash]
        after["jobs"] = {first_hash: after["jobs"][second_hash]}
        after["ledger"][-1]["jobSha256"] = first_hash
        with self.assertRaisesRegex(ProductError, "PRIOR_ROWS_CHANGED"):
            subject.settle_image_ledger(before, after, {**second, "id": first["id"]}, public)

    def test_account_and_public_projections_cannot_override_real_private_debit(self):
        before = self.snapshot()
        started, public = self.complete(main=1, daily=2)
        after = self.snapshot([started["id"]])
        for key in ("token_balance", "daily_tokens_used", "tokens_used", "generation_count"):
            with self.subTest(account=key):
                changed = deepcopy(after); changed["account"][key] += 1
                with self.assertRaisesRegex(ProductError, "ACCOUNT_MISMATCH"):
                    subject.settle_image_ledger(before, changed, started, public)
        for key in ("tokenCost", "mainBalanceDebit", "dailyBudgetDebit", "refundDelta"):
            with self.subTest(public=key):
                changed = {**public, key: True}
                with self.assertRaisesRegex(ProductError, "PUBLIC_MISMATCH"):
                    subject.settle_image_ledger(before, after, started, changed)
        with self.assertRaisesRegex(ProductError, "ACCOUNT_MISMATCH"):
            subject.settle_image_ledger(before, after, {**started, "tokenBalance": 100}, public)

    def test_charge_mode_provider_partition_and_links_are_exact(self):
        before = self.snapshot()
        started, public = self.complete()
        after = self.snapshot([started["id"]])
        for key, value in (("mode", "paint"), ("provider", "local_ltx"), ("tokenCost", True),
                           ("dailyPart", 1), ("refundTokens", 0), ("requestSha256", "e" * 64),
                           ("chargedLedgerSha256", "e" * 64), ("reason", "generation_refund")):
            with self.subTest(field=key):
                changed = deepcopy(after); changed["ledger"][0][key] = value
                with self.assertRaises(ProductError):
                    subject.settle_image_ledger(before, changed, started, public)

    def test_owner_api_reset_active_and_time_changes_fail_closed(self):
        before = self.snapshot()
        started, public = self.complete()
        after = self.snapshot([started["id"]])
        for variant in ("owner", "api", "source", "day", "active", "time", "state"):
            with self.subTest(variant=variant):
                changed = deepcopy(after)
                if variant == "owner": changed["ownerSha256"][0] = "e" * 64
                elif variant == "api": changed["api"]["hostPid"] += 1
                elif variant == "source": changed["sourceSha"] = "e" * 40
                elif variant == "day": changed["account"]["last_daily_reset"] = "2026-10-19"
                elif variant == "active": changed["activeOwnedJobs"] = 1
                elif variant == "time": changed["capturedAt"] = before["capturedAt"] - 1
                else: changed["jobs"][subject.identifier_sha(started["id"])]["status"] = "failed"
                with self.assertRaises(ProductError):
                    subject.settle_image_ledger(before, changed, started, public)

    def test_second_mode_mismatch_preserves_completed_image_and_failed_snapshot(self):
        values = self.chain()
        wrong = subject.identifier_sha("job-owned-impostor")
        values[2]["ledger"][1]["jobSha256"] = wrong
        callback, checkpoints = Mock(side_effect=values), []
        with self.assertRaisesRegex(ProductError, "SINGLE_CHARGE_NOT_PROVEN"):
            self.run_series(values, callback=callback, checkpoint=checkpoints.append)
        final = checkpoints[-1]
        self.assertEqual(final["status"], "FAIL")
        self.assertEqual(final["modes"]["edit"]["status"], "PASS")
        self.assertEqual(final["modes"]["paint"]["status"], "FAIL")
        self.assertEqual(final["modes"]["paint"]["imageId"], "image-2")
        self.assertNotIn("faceswap", final["modes"])
        self.assertEqual(callback.call_count, 3)
        proof = json.loads((self.root / "receipts" / "receipt.json").read_text())
        self.assertEqual(len(proof["snapshots"]), 3)
        self.assertEqual(proof["status"], "FAIL")
        self.assertEqual(tuple(proof["modes"]), ("edit",))

    def test_callback_alias_mutation_cannot_rewrite_previously_captured_rows(self):
        values = self.chain()
        values[2]["ledger"][0]["rowSha256"] = "e" * 64
        shared, pending = {}, iter(values)
        def callback(_jobs):
            shared.clear(); shared.update(deepcopy(next(pending)))
            return shared
        with self.assertRaisesRegex(ProductError, "PRIOR_ROWS_CHANGED"):
            self.run_series(values, callback=callback)
        saved = json.loads((self.root / "receipts" / "01-edit.json").read_text())
        self.assertEqual(saved["ledger"][0]["rowSha256"], values[1]["ledger"][0]["rowSha256"])

    def test_missing_failed_or_active_baseline_never_starts_application_work(self):
        active = self.snapshot(); active["activeOwnedJobs"] = 1
        for index, callback in enumerate((None, Mock(side_effect=RuntimeError(PRIVATE)), Mock(return_value=active))):
            with self.subTest(index=index):
                flow, provider = existing.owned_flow(), Mock()
                with self.assertRaises(ProductError) as caught:
                    subject.prove_image_modes_private(flow, existing.SOURCE, self.root / f"case-{index}",
                        attestation=existing.ATTESTATION, provider_receipt=provider, private_ledger=callback)
                self.assertNotIn(PRIVATE, str(caught.exception))
                provider.assert_not_called()
                for client in flow.clients: client.request.assert_not_called()

    def test_late_stale_or_unsafe_receipt_never_becomes_pass(self):
        baseline = self.snapshot()
        for variant in ("late", "stale", "extra", "api_private"):
            value = deepcopy(baseline)
            if variant == "stale": value["capturedAt"] -= 60
            elif variant == "extra": value["rawProviderError"] = PRIVATE
            elif variant == "api_private": value["api"]["startedAt"] = PRIVATE
            with self.subTest(variant=variant), patch.object(subject.time, "monotonic", side_effect=[0, 8 if variant == "late" else 0]):
                flow, provider = existing.owned_flow(), Mock()
                with self.assertRaises(ProductError) as caught:
                    subject.prove_image_modes_private(flow, existing.SOURCE, self.root / variant,
                        attestation=existing.ATTESTATION, provider_receipt=provider, private_ledger=lambda _jobs: value)
                self.assertNotIn(PRIVATE, str(caught.exception))
                provider.assert_not_called(); flow.owner.request.assert_not_called()
                for path in (self.root / variant).glob("*.json"):
                    self.assertNotIn(PRIVATE, path.read_text())

    def test_callback_cannot_mutate_empty_baseline_request_to_include_a_job(self):
        started, _ = self.complete()
        value = self.snapshot([started["id"]])
        def callback(jobs):
            jobs.append(started["id"])
            return value
        flow, provider = existing.owned_flow(), Mock()
        with self.assertRaisesRegex(ProductError, "IDENTITY_MISMATCH"):
            subject.prove_image_modes_private(flow, existing.SOURCE, self.root / "mutated",
                attestation=existing.ATTESTATION, provider_receipt=provider, private_ledger=callback)
        provider.assert_not_called(); flow.owner.request.assert_not_called()

    def test_oversized_safe_wire_shape_stops_before_generation_or_snapshot_write(self):
        started, _ = self.complete()
        row = self.snapshot([started["id"]])["ledger"][0]
        value = self.snapshot()
        value["ledger"] = [{**deepcopy(row), "idSha256": hashlib.sha256(str(index).encode()).hexdigest(),
                            "delta": 10 ** 1100} for index in range(64)]
        flow, provider = existing.owned_flow(), Mock()
        with self.assertRaisesRegex(ProductError, "RECEIPT_LIMIT"):
            subject.prove_image_modes_private(flow, existing.SOURCE, self.root / "large",
                attestation=existing.ATTESTATION, provider_receipt=provider, private_ledger=lambda _jobs: value)
        provider.assert_not_called(); flow.owner.request.assert_not_called()
        self.assertEqual([path.name for path in (self.root / "large").iterdir()], ["receipt.json"])

    def test_final_checkpoint_failure_overwrites_no_snapshots_and_cannot_leave_pass_summary(self):
        def checkpoint(value):
            if value["privateLedger"]["status"] == "PASS":
                raise OSError(PRIVATE)
        with self.assertRaisesRegex(ProductError, "CHECKPOINT_FAILED"):
            self.run_series(self.chain(), checkpoint=checkpoint)
        summary = json.loads((self.root / "receipts" / "receipt.json").read_text())
        self.assertEqual(summary["status"], "FAIL")
        self.assertEqual(len(summary["snapshots"]), 4)
        for reference in summary["snapshots"]:
            self.assertEqual(reference["sha256"], hashlib.sha256((self.root / "receipts" / reference["receipt"]).read_bytes()).hexdigest())

    def test_existing_output_directory_is_untouched(self):
        directory = self.root / "existing"
        directory.mkdir()
        marker = directory / "receipt.json"
        marker.write_text("owned-other-result")
        callback = Mock()
        with self.assertRaises(ProductError):
            self.run_series([], callback=callback, directory=directory)
        callback.assert_not_called()
        self.assertEqual(marker.read_text(), "owned-other-result")
        self.assertEqual(len(list(directory.iterdir())), 1)


if __name__ == "__main__":
    unittest.main()
