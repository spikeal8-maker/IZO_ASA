"""Evidence and failure semantics for the owned runtime recovery probe; no Docker."""
from contextlib import ExitStack, redirect_stdout
from copy import deepcopy
import io
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from tools import docker_clean_recovery as recovery


def snapshot(ids=(), *, refunded=False, status="sent_to_comfyui"):
    used = 0 if refunded else 10 * len(ids)
    accounts = {name: {"id": name, "token_balance": 100, "daily_tokens_used": used if name == "owner" else 0,
                "tokens_used": used if name == "owner" else 0,
                "generation_count": len(ids) if used and name == "owner" else 0,
                "last_daily_reset": "2026-10-17"} for name in ("owner", "other")}
    jobs = [{"id": job_id, "user_id": "owner", "status": status, "progress": 0,
             "result_image_id": None, "completed_at": "2026-10-17" if refunded else None} for job_id in ids]
    ledger = []
    for job_id in ids:
        ledger.append({"id": "charge-" + job_id, "user_id": "owner", "jobId": job_id,
            "reason": "daily_generation", "delta": 0, "token_cost": 10, "daily_part": 10})
        if refunded:
            ledger.append({"id": "refund-" + job_id, "user_id": "owner", "jobId": job_id,
                "reason": "daily_generation_refund", "delta": 0, "refund_tokens": 10,
                "daily_part": 10, "cause": "startup_reconciliation"})
    return {"users": accounts, "jobs": jobs, "images": [], "ledger": ledger, "activeJobs": sum(row["status"] in recovery.ACTIVE for row in jobs)}


def provider(*, accepted=0, instance="a" * 32, sequence=0, action=None, active=False):
    return {"fixture": "controlled-comfyui-v1", "instanceId": instance,
        "control": {"sequence": sequence, "action": action, "status": "ACK" if action else "IDLE"},
        "provider": {"model_execution": False, "counts": {"accepted": accepted}, "jobs": [
            {"prompt_id": f"prompt-{number}", "state": "held", "client_sha256": "b" * 64}
            for number in range(accepted)]},
        "race": {"active": active, "status": "RUNNING" if active else "STOPPED",
                 "jobId": "job-a", "dequeuedJobId": "job-a"}}


def target():
    return {"origin": "http://127.0.0.1:48125", "sourceSha": "a" * 40,
            "project": "izo-asa-shadow-recovery", "isolatedData": True, "fakeProviderOnly": True,
            "networkEgressDenied": True, "externalEffectsDisabled": True}


def shadow():
    value = Mock(fixture=True, project=target()["project"], sha=target()["sourceSha"], web_port=48125)
    value.image_guard.return_value = {"backend": "sha256:" + "c" * 64}
    return value


class RecoveryEvidenceTests(unittest.TestCase):
    def test_key_header_is_sent_and_restored_even_when_request_raises(self):
        headers = [("User-Agent", "unit-test")]
        client = SimpleNamespace(opener=SimpleNamespace(addheaders=headers))

        def request(method, path, payload):
            self.assertEqual((method, path, payload), ("POST", "/api/generate", {}))
            self.assertEqual(client.opener.addheaders[-1], ("Idempotency-Key", "same-key"))
            raise RuntimeError("unit request failure")

        client.request = request
        with self.assertRaises(RuntimeError):
            recovery.keyed_post(client, "/api/generate", {}, "same-key")
        self.assertEqual(client.opener.addheaders, headers)

    def test_daily_refund_uses_token_metadata_and_rejects_duplicates(self):
        paid = snapshot(["job-a"])
        restored = snapshot(["job-a"], refunded=True)
        recovery.accounting(paid, ["job-a"], refunded=False)
        recovery.accounting(restored, ["job-a"], refunded=True)
        invalid = [deepcopy(restored) for _ in range(5)]
        invalid[0]["ledger"].append(deepcopy(invalid[0]["ledger"][-1]))
        invalid[1]["ledger"][-1]["refund_tokens"] = 9
        invalid[2]["ledger"][-1]["delta"] = 1
        invalid[3]["ledger"].pop(0)
        invalid[4]["ledger"][0]["user_id"] = "other"
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(recovery.RecoveryError):
                recovery.accounting(value, ["job-a"], refunded=True)

    def test_account_equality_ignores_daily_reset_metadata_only(self):
        before, after = snapshot(), snapshot()
        after["users"]["owner"]["last_daily_reset"] = "2026-10-18"
        self.assertTrue(recovery.same_accounts(before, after))
        after["users"]["other"]["tokens_used"] = 1
        self.assertFalse(recovery.same_accounts(before, after))
        self.assertEqual(recovery.error_code(RuntimeError("secret\nbody")), "RECOVERY_OPERATION_FAILED")

    def test_database_reader_is_read_only_scoped_and_redacts_metadata(self):
        original_connect = sqlite3.connect
        with tempfile.TemporaryDirectory(prefix="izo-recovery-db-") as directory:
            path = Path(directory) / "test.sqlite3"
            with original_connect(path) as connection:
                connection.executescript("""
                    CREATE TABLE users(id TEXT,token_balance INTEGER,daily_tokens_used INTEGER,
                        tokens_used INTEGER,generation_count INTEGER,last_daily_reset TEXT);
                    CREATE TABLE jobs(id TEXT,user_id TEXT,status TEXT,progress INTEGER,
                        result_image_id TEXT,completed_at TEXT);
                    CREATE TABLE images(id TEXT,job_id TEXT,user_id TEXT,deleted_at TEXT);
                    CREATE TABLE token_ledger(id TEXT,user_id TEXT,delta INTEGER,reason TEXT,meta_json TEXT);
                    INSERT INTO users VALUES('owner',100,10,10,1,'2026-10-17'),('foreign',999,0,0,0,NULL);
                    INSERT INTO jobs VALUES('job-a','owner','sent_to_comfyui',0,NULL,NULL),
                        ('job-foreign','foreign','completed',100,'image-foreign','done');
                    INSERT INTO images VALUES('image-foreign','job-foreign','foreign',NULL);
                """)
                for row_id, user, job in (("1", "owner", "job-a"), ("2", "owner", "untracked"),
                                           ("3", "foreign", "job-foreign")):
                    connection.execute("INSERT INTO token_ledger VALUES(?,?,?,?,?)", (row_id, user, 0,
                        "daily_generation", json.dumps({"jobId": job, "token_cost": 10, "daily_part": 10,
                                                       "private": "never-serialize-this-value"})))
            connection.close()
            original = path.read_bytes()

            def opened(database_uri, **kwargs):
                self.assertEqual(database_uri, "file:/home/izo/data/app.sqlite3?mode=ro")
                self.assertEqual(kwargs, {"uri": True, "timeout": 5})
                return original_connect(path.as_uri() + "?mode=ro", **kwargs)

            for ids in (["job-a"], ["job-a' OR 1=1--"]):
                output = io.StringIO()
                with patch("sqlite3.connect", side_effect=opened), patch.object(sys, "argv", [
                        "reader", json.dumps([["owner"], ids])]), redirect_stdout(output):
                    exec(compile(recovery.DATABASE_READ, "database-read-probe", "exec"), {})
                value = json.loads(output.getvalue())
                self.assertEqual(set(value["users"]), {"owner"})
                self.assertEqual(value["activeJobs"], 1)
                self.assertNotIn("never-serialize", output.getvalue())
                self.assertNotIn("foreign", output.getvalue())
                self.assertEqual(len(value["ledger"]), int(ids == ["job-a"]))
            self.assertEqual(path.read_bytes(), original)


class RecoveryActionTests(unittest.TestCase):
    def run_object(self):
        run = recovery.RecoveryRun(shadow(), Mock(), Mock())
        run.guard()
        return run

    def test_changed_source_image_blocks_lifecycle_and_signal_ack_is_instance_bound(self):
        run = self.run_object()
        run.shadow.image_guard.return_value = {"backend": "sha256:" + "d" * 64}
        with self.assertRaisesRegex(recovery.RecoveryError, "IMAGE_CHANGED"):
            run.guard()
        run.shadow.compose.assert_not_called()
        run.guard = Mock()
        run.provider = Mock(side_effect=[provider(), provider(instance="f" * 32, sequence=1, action="hold")])
        with self.assertRaisesRegex(recovery.RecoveryError, "SIGNAL_RESTARTED"):
            run.signal("hold")
        run.shadow.compose.assert_called_once_with("kill", "--signal", "SIGUSR1", "backend", timeout=20)

    def test_signal_fail_or_wrong_ack_is_not_accepted(self):
        for changed in ({"sequence": 2}, {"action": "release"}, {"status": "FAIL"}):
            run = self.run_object()
            received = provider(sequence=1, action="hold")
            received["control"].update(changed)
            run.provider = Mock(side_effect=[provider(), received])
            with self.subTest(changed=changed), self.assertRaisesRegex(recovery.RecoveryError, "CONTROL_FAILED"):
                run.signal("hold")

    def test_crash_requires_accepted_charge_before_kill_and_exactly_once_startup_refund(self):
        run, case, checkpoints = self.run_object(), {}, []
        before, charged = snapshot(), snapshot(["job-a"])
        restored = snapshot(["job-a"], refunded=True, status="failed")
        run.checkpoint = lambda: checkpoints.append(deepcopy(case))
        run.signal = Mock(return_value=provider())
        run.submit = Mock(return_value={"id": "job-a", "status": "queued", "tokenCost": 10})
        run.provider = Mock(return_value=provider(accepted=1))
        run.snapshot = Mock(side_effect=[before, charged, restored, deepcopy(restored)])
        run.backend = Mock(side_effect=[{"Id": "owned-backend"},
            {"Id": "owned-backend", "State": {"Running": False, "ExitCode": 137}}])
        run.recreate = Mock(return_value={"newContainer": "fixture-next"})
        run.flow.owner.request.return_value = {"status": "failed"}

        def killed(*args, **kwargs):
            self.assertEqual(args, ("kill", "--signal", "SIGKILL", "backend"))
            self.assertEqual(checkpoints[0]["acceptedBeforeAction"]["database"], charged)
            self.assertEqual(checkpoints[0]["acceptedBeforeAction"]["provider"]["provider"]["counts"]["accepted"], 1)

        run.shadow.compose.side_effect = killed
        run.crash(case)
        self.assertEqual(case["status"], "PASS")
        self.assertEqual(run.recreate.call_count, 2)
        self.assertEqual(case["afterSecondRestart"], restored)
        self.assertEqual(case["crash"]["exitCode"], 137)

    def test_crash_cannot_pass_from_cancel_refund_or_missing_container_death(self):
        for exit_code, cause, expected in ((0, "startup_reconciliation", "CRASH_NOT_OBSERVED"),
                                          (137, "user_cancelled", "STARTUP_REFUND_NOT_OBSERVED")):
            run, case = self.run_object(), {}
            restored = snapshot(["job-a"], refunded=True, status="failed")
            restored["ledger"][-1]["cause"] = cause
            run.snapshot = Mock(side_effect=[snapshot(), restored])
            run.held_job = Mock(return_value="job-a")
            run.backend = Mock(side_effect=[{"Id": "owned"},
                {"Id": "owned", "State": {"Running": False, "ExitCode": exit_code}}])
            run.recreate = Mock()
            run.flow.owner.request.return_value = {"status": "failed"}
            with self.subTest(exit_code=exit_code), self.assertRaisesRegex(recovery.RecoveryError, expected):
                run.crash(case)
            self.assertNotEqual(case.get("status"), "PASS")

    def test_repeated_generation_key_measures_new_ids_and_cancel_refunds(self):
        for repeated_id, expected in (("job-a", "PASS"), ("job-b", "FAIL")):
            run, case, keys = self.run_object(), {}, []

            def held(case, key):
                keys.append(key)
                case["submitted"] = {"id": "job-a", "tokenCost": 10, "status": "queued"}

            def submitted(key):
                self.assertEqual(key, keys[0])
                return {"id": repeated_id, "tokenCost": 10, "status": "queued"}

            ids = list(dict.fromkeys(("job-a", repeated_id)))
            run.held_job, run.submit = held, submitted
            run.snapshot = Mock(side_effect=[snapshot(), snapshot(ids)])
            run.cancel = Mock(return_value={"database": snapshot(ids, refunded=True, status="cancelled")})
            run.repeated(case)
            self.assertEqual(case["status"], expected)
            self.assertEqual(case["cancelReplay"], "PASS")
            self.assertNotIn(keys[0], json.dumps(case))
            run.cancel.assert_called_once_with(ids, keys[0])

    def test_cancel_sends_twice_and_waits_for_one_durable_refund(self):
        run = self.run_object()
        run.flow.owner.opener.addheaders = []
        run.flow.owner.request.return_value = {"id": "job-a", "status": "cancelled"}
        run.snapshot = Mock(return_value=snapshot(["job-a"], refunded=True, status="cancelled"))
        result = run.cancel(["job-a"], "cancel-key")
        self.assertEqual(len(result["responses"][0]), 2)
        self.assertEqual(run.flow.owner.request.call_count, 2)
        for call in run.flow.owner.request.call_args_list:
            self.assertEqual(call.args, ("POST", "/api/jobs/job-a/cancel", {}))

    def test_concurrent_acceptance_uses_real_container_probe_and_propagates_failure(self):
        run, case = self.run_object(), {}
        run.signal = Mock()
        with patch('tools.docker_clean_workers.prove_workers', side_effect=recovery.RecoveryError('RECOVERY_WORKER_NOT_OWNED')) as probe:
            with self.assertRaisesRegex(recovery.RecoveryError, 'WORKER_NOT_OWNED'):
                run.concurrent(case)
            probe.assert_called_once_with(run, case)
        run.signal.assert_not_called()

    def test_two_users_measure_inflight_and_cancel_each_with_own_auth(self):
        for wrong_owner in (False, True):
            run, case, calls = self.run_object(), {}, []
            run.user_ids = ["owner", "other"]
            charged = snapshot(["job-a", "job-b"])
            restored = snapshot(["job-a", "job-b"], refunded=True, status="cancelled")
            for value in (charged, restored):
                value["jobs"][1]["user_id"] = "other"
                for row in value["ledger"]:
                    if row["jobId"] == "job-b":
                        row["user_id"] = "other"
            for account in charged["users"].values():
                account.update(daily_tokens_used=10, tokens_used=10, generation_count=1)
            charged["jobs"][1]["status"] = "queued"
            if wrong_owner:
                charged["ledger"][-1]["user_id"] = "owner"
            run.snapshot = Mock(side_effect=[snapshot(), charged, restored])
            run.provider = Mock(return_value=provider(accepted=1))
            run.recreate = Mock(return_value={"afterContainer": "fresh-owned-backend"})
            run.flow.other.opener.addheaders = []

            def held(value):
                value.update(submitted={"id": "job-a"}, acceptedBeforeAction={"provider": provider(accepted=1)})
                return "job-a"

            def response(who, method, path, *args, **kwargs):
                calls.append((who, method, path, kwargs))
                if path == "/api/generate":
                    return {"id": "job-b", "status": "queued", "queuePosition": 1, "tokenCost": 10}
                return {"id": "job-b" if who == "other" else "job-a", "status": "cancelled" if method == "POST"
                        else charged["jobs"][int(who == "other")]["status"]}

            run.held_job = held
            for who, client in (("owner", run.flow.owner), ("other", run.flow.other)):
                client.request.side_effect = lambda *a, who=who, **kw: response(who, *a, **kw)
            run.images = run.shadow.image_guard.return_value = {name: "image-" + name for name in ("backend", "web", "guard")}
            run.shadow.containers.return_value = [{"Id": name, "Image": image, "State": {"Running": True},
                "Config": {"Labels": {"com.docker.compose.service": name}}} for name, image in run.images.items()]

            def stats(*args, **kwargs):
                self.assertFalse(any(path.endswith("/cancel") for _, _, path, _ in calls))
                self.assertEqual(set(args[5:]), set(run.images))
                return "\n".join(json.dumps({"ID": name, "CPUPerc": "0.2%", "MemUsage": "12MiB / 64MiB"}) for name in run.images)

            run.shadow.docker.side_effect = stats
            run.two_users(case)
            self.assertEqual(case["status"], "FAIL" if wrong_owner else "PASS")
            if wrong_owner:
                self.assertEqual(case["errorCode"], "RECOVERY_LEDGER_OWNER_MISMATCH")
            self.assertEqual([(who, path) for who, method, path, _ in calls if method == "POST" and path.endswith("/cancel")],
                             [("other", "/api/jobs/job-b/cancel"), ("owner", "/api/jobs/job-a/cancel")])
            self.assertEqual(case["measurement"]["queuedCount"], 1)
            self.assertTrue(recovery.same_accounts(case["baseline"], case["afterCancel"]))


class RecoveryOrchestrationTests(unittest.TestCase):
    def execute(self, *, actions=None, restart=None, close=None, measurement=None):
        flow = Mock()
        flow.register.side_effect = [{"legacy_user_id": "owner"}, {"legacy_user_id": "other"}]
        flow.close.return_value = {"sessionCleanup": "PASS"}
        if close:
            flow.close.side_effect = close
        actions = actions or [lambda case: case.update(status="PASS")] * 3
        with tempfile.TemporaryDirectory(prefix="izo-recovery-report-") as directory, ExitStack() as stack:
            path = Path(directory) / "receipt.json"
            stack.enter_context(patch.object(recovery.RecoveryRun, "guard"))
            stack.enter_context(patch.object(recovery.RecoveryRun, "provider", return_value=provider()))
            for name, action in zip(("crash", "repeated", "concurrent"), actions):
                stack.enter_context(patch.object(recovery.RecoveryRun, name, side_effect=action))
            stack.enter_context(patch.object(recovery.RecoveryRun, "two_users",
                side_effect=measurement or (lambda case: case.update(status="PASS"))))
            stack.enter_context(patch.object(recovery.RecoveryRun, "recreate", side_effect=restart,
                                            return_value={"sameVolumes": True}))
            stack.enter_context(patch.object(recovery, "ProductFlow", return_value=flow))
            comparison = stack.enter_context(patch.object(recovery, "compare_isolated", return_value={"status": "PASS"}))
            report = recovery.prove_recovery(shadow(), target(), path)
            self.assertEqual(report, json.loads(path.read_text()))
            comparison.assert_called_once()
            return report

    def test_unadmitted_target_never_constructs_http_flow(self):
        with tempfile.TemporaryDirectory(prefix="izo-recovery-admission-") as directory:
            path, unsafe = Path(directory) / "receipt.json", shadow()
            unsafe.fixture = False
            with patch.object(recovery, "ProductFlow") as flow:
                report = recovery.prove_recovery(unsafe, target(), path)
            flow.assert_not_called()
            unsafe.source_guard.assert_not_called()
            self.assertEqual(report["errorCode"], "RECOVERY_ISOLATED_FIXTURE_REQUIRED")
            self.assertEqual(report["status"], "FAIL")

    def test_failed_case_is_preserved_while_later_probes_run(self):
        def failed(_case):
            raise recovery.RecoveryError("RECOVERY_RUNTIME_CONTRACT_FAILED")

        report = self.execute(actions=[failed, lambda c: c.update(status="PASS"), lambda c: c.update(status="PASS")])
        self.assertEqual(report["status"], "FAIL")
        self.assertEqual(len(report["checks"]), 3)
        self.assertEqual(report["checks"]["D2-01"]["errorCode"], "RECOVERY_RUNTIME_CONTRACT_FAILED")
        self.assertEqual(report["checks"]["D2-03"]["status"], "PASS")

    def test_third_cleanup_failure_overrides_nominal_case_success(self):
        report = self.execute(restart=[{}, {}, recovery.RecoveryError("RECOVERY_RESTART_FAILED")])
        self.assertEqual(report["status"], "FAIL")
        self.assertEqual(report["checks"]["D2-03"]["status"], "FAIL")
        self.assertEqual(report["checks"]["D2-03"]["cleanupError"], "RECOVERY_RESTART_FAILED")

    def test_session_exception_is_redacted_and_cannot_skip_foreign_comparison_or_receipt(self):
        report = self.execute(close=RuntimeError("secret/raw/http/body"))
        self.assertEqual(report["status"], "FAIL")
        self.assertEqual(report["sessionCleanupError"], "RECOVERY_OPERATION_FAILED")
        self.assertNotIn("secret/raw", json.dumps(report))

    def test_measurement_failure_survives_three_passing_d2_cases(self):
        report = self.execute(measurement=lambda case: case.update(status="FAIL", errorCode="RECOVERY_MEASUREMENT_FAILED"))
        self.assertEqual(len(report["checks"]), 3)
        self.assertTrue(all(case["status"] == "PASS" for case in report["checks"].values()))
        self.assertEqual(report["measurements"]["D3-queue"]["errorCode"], "RECOVERY_MEASUREMENT_FAILED")
        self.assertEqual(report["status"], "FAIL")


if __name__ == "__main__":
    unittest.main()
