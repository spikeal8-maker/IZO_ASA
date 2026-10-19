"""Reject false orchestration evidence; these observations are not Docker proof."""
from contextlib import nullcontext
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import signal
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from tools import docker_d3_orchestration as subject
from tools.docker_shadow_product import ProductError

SHA = "a" * 40
PRIVATE = "private-cookie-provider-error-must-not-reach-receipt"


def observations():
    """Minimal complete reports, including the intentionally PARTIAL D3 result."""
    rows = []
    for replica in (1, 2):
        images = {name: "sha256:" + format(replica * 10 + number, "064x")
                  for number, name in enumerate(("guard", "web", "backend"))}
        images.update(worker=images["backend"], worker_peer=images["backend"])
        for index in (1, 2, 3):
            project = f"izo-asa-shadow-d3-r{replica}-i{index}"
            storage = {"status": "PASS", "sourceSha": SHA, "sourceProject": project,
                "checks": {f"D2-{n:02}": {"status": "PASS"} for n in (4, 5, 6)},
                "cleanup": {"status": "PASS"}, "sessionCleanup": {"sessionCleanup": "PASS"},
                "foreignComparison": {"status": "PASS"}, "sourceQuiescence": {"status": "PASS"},
                "sourceUnchanged": "PASS"}
            recovery = {"status": "PASS", "sourceSha": SHA, "project": project,
                "checks": {f"D2-{n:02}": {"status": "PASS", "cleanupRestart": {
                    "beforeContainer": "before", "afterContainer": "after"}} for n in (1, 2, 3)},
                "measurements": {"D3-queue": {"status": "PASS", "cleanupRestart": {
                    "beforeContainer": "before", "afterContainer": "after"}}},
                "sessionCleanup": {"sessionCleanup": "PASS"}, "foreignResources": {"status": "PASS"}}
            features = {"status": "PARTIAL", "sourceSha": SHA, "project": project,
                "checks": {"chatHistory": {"threadCleanup": "PASS"}}}
            admin = {"status": "PASS", "sourceSha": SHA, "project": project + "-admin",
                "cleanup": {"status": "PASS"}, "foreignResources": {"status": "PASS"},
                "acceptance": {"status": "PASS", "sourceSha": SHA, "project": project + "-admin",
                    "cleanup": {"sessionCleanup": "PASS"}, "checks": {"modelEconomics": {
                        "settingCleanup": "PASS", "accountInvariance": "PASS"}}}}
            rows.append({"status": "FAIL", "failedStage": "D2-D3", "sourceSha": SHA, "checkoutSha": SHA,
                "project": project, "D1Status": "PASS", "checks": {
                    f"D1-{n:02}": {"status": "PASS"} for n in range(1, 9)},
                "host": {"machineIdentitySha256": str(replica) * 64, "bootIdentitySha256": str(replica + 2) * 64,
                    "engineId": f"owned-engine-{replica}", "runnerName": f"GitHub Actions {replica}",
                    "runnerEnvironment": "github-hosted", "runId": "17", "attempt": "1"},
                "resourcesBeforeRecreate": {"images": deepcopy(images)},
                "resourcesAfterRecreate": {"images": deepcopy(images)},
                "cleanup": {"status": "PASS"}, "sessionCleanup": {"sessionCleanup": "PASS"},
                "foreignResources": {"status": "PASS"}, "extended": {"status": "FAIL", "results": {
                    "storage": storage, "recovery": recovery, "features": features, "admin": admin}}})
    return rows


def process_receipt():
    return {"status": "PASS", "timedOut": False, "nodeReturncode": 0, "scope": "PRIVATE_LINUX_SUBREAPER",
            "cleanup": {"status": "PASS", "childrenAtShutdown": 0, "remainingChildren": 0}}


def provider_receipt():
    return {"fixture": subject.MARKER, "instanceId": "b" * 32, "lifetimeSeconds": 300,
            "provider": {"model_execution": False, "jobs": [], "d3": {
                "profile": subject.MARKER, "modelExecution": False, "acceleratorExecution": False, "chat": []}}}


class AdmissionTests(unittest.TestCase):
    def test_six_complete_reports_select_one_tested_vm_images_without_promoting_partial(self):
        rows = observations()
        self.assertTrue(all(subject.completed_extended(row) for row in rows))
        self.assertEqual(subject.admit_attempts(rows, SHA, rows[0]["project"]),
                         rows[0]["resourcesBeforeRecreate"]["images"])
        self.assertTrue(all(row["status"] == "FAIL" for row in rows))

    def test_incomplete_cleanup_individual_d1_and_measured_d2_failure_are_rejected(self):
        faults = (
            lambda row: row["sessionCleanup"].update(sessionCleanup="FAIL"),
            lambda row: row["checks"]["D1-08"].update(status="FAIL"),
            lambda row: row["extended"]["results"]["recovery"]["checks"]["D2-03"].update(status="FAIL"),
            lambda row: row["extended"]["results"]["storage"]["checks"]["D2-06"].update(status="FAIL"),
            lambda row: row["extended"]["results"]["recovery"]["checks"]["D2-02"].pop("cleanupRestart"),
        )
        for fault in faults:
            rows = observations()
            fault(rows[2])
            with self.subTest(fault=fault), self.assertRaises(ProductError):
                subject.admit_attempts(rows, SHA, rows[0]["project"])

    def test_same_source_is_not_enough_for_image_or_run_identity(self):
        for field in ("source", "image", "attempt", "project", "boot", "runner", "host"):
            rows = observations()
            if field == "source":
                rows[0]["checkoutSha"] = "c" * 40
            elif field == "image":
                rows[0]["resourcesAfterRecreate"]["images"]["backend"] = "sha256:" + "d" * 64
            elif field == "attempt":
                rows[0]["host"]["attempt"] = "2"
            elif field == "project":
                rows[0]["project"] = rows[1]["project"]
            elif field == "host":
                rows[0]["host"]["engineId"] = "different-engine-within-one-vm"
            else:
                key = "bootIdentitySha256" if field == "boot" else "runnerName"
                for row in rows[3:]:
                    row["host"][key] = rows[0]["host"][key]
            with self.subTest(field=field), self.assertRaises(ProductError):
                subject.admit_attempts(rows, SHA, rows[0]["project"])

    def test_golden_machine_and_engine_ids_can_repeat_with_distinct_boot_and_runner(self):
        rows = observations()
        for row in rows:
            row["host"]["machineIdentitySha256"] = "e" * 64
            row["host"]["engineId"] = "same-golden-image-engine"
        self.assertEqual(subject.admit_attempts(rows, SHA, rows[0]["project"]),
                         rows[0]["resourcesBeforeRecreate"]["images"])

    def test_missing_sixth_installation_or_unknown_selected_project_cannot_start(self):
        rows = observations()
        for values, selected in ((rows[:-1], rows[0]["project"]), (rows, "izo-asa-shadow-unknown")):
            with self.subTest(selected=selected), self.assertRaises(ProductError):
                subject.admit_attempts(values, SHA, selected)


class ProfileTests(unittest.TestCase):
    def subject(self, actual):
        shadow = object.__new__(subject.D3Shadow)
        shadow.active, shadow.files = True, [Path("base.yml"), Path("admin.yml"), Path("d3.yml")]
        shadow.compose = Mock(return_value=json.dumps(actual))
        return shadow

    def test_exact_overlay_keeps_original_admission_and_restores_file_stack(self):
        baseline = {"services": {"backend": {"environment": {"IZO_SHADOW_FIXTURE": "controlled-comfyui-v1"}}}}
        actual = deepcopy(baseline)
        actual["services"]["backend"]["environment"].update(subject.DELTA)
        shadow = self.subject(actual)
        original = shadow.files
        def admitted(instance):
            self.assertEqual(instance.files, original[:-1])
            return baseline
        with patch.object(subject.CapturedAdminShadow, "config", autospec=True, side_effect=admitted) as guard:
            self.assertEqual(shadow.config(), actual)
            guard.assert_called_once_with(shadow)
        self.assertIs(shadow.files, original)

    def test_extra_profile_environment_mount_or_network_fails_before_up(self):
        baseline = {"services": {"backend": {"environment": {}}}, "networks": {"shadow": {}}}
        for field in ("environment", "volumes", "network"):
            actual = deepcopy(baseline)
            actual["services"]["backend"]["environment"].update(subject.DELTA)
            if field == "environment":
                actual["services"]["backend"]["environment"]["BOT_TOKEN"] = PRIVATE
            elif field == "volumes":
                actual["services"]["backend"]["volumes"] = [{"type": "bind", "source": "/foreign"}]
            else:
                actual["networks"]["extra"] = {}
            shadow = self.subject(actual)
            original = shadow.files
            with self.subTest(field=field), patch.object(subject.CapturedAdminShadow, "config", return_value=baseline):
                with self.assertRaisesRegex(ProductError, "D3_UNAPPROVED_PROFILE_CHANGE"):
                    shadow.config()
            self.assertIs(shadow.files, original)
            self.assertEqual(shadow.compose.call_count, 1)


class ReaderTests(unittest.TestCase):
    def test_private_reader_rechecks_same_api_and_never_accepts_another_process(self):
        expected = {"environment": {"IZO_SHADOW_FIXTURE": subject.MARKER}}
        shadow = SimpleNamespace(config=Mock(return_value={"services": {"backend": expected}}), docker=Mock())
        identity = {"containerId": "owned", "hostPid": 100, "imageId": "sha256:" + "a" * 64}
        for changed in ({**identity, "hostPid": 101}, {**identity, "containerId": "recreated"}):
            shadow.docker.reset_mock()
            with self.subTest(changed=changed), patch.object(subject, "api_identity", side_effect=[identity, changed]), \
                    patch.object(subject, "wallclock", return_value=nullcontext()):
                reader = subject.fixed_provider_reader(shadow, {})
                with self.assertRaisesRegex(ProductError, "D3_PROVIDER_API_CHANGED"):
                    reader()
                shadow.docker.assert_not_called()

    def test_fixed_path_whole_utf8_bound_and_marker_fail_closed(self):
        expected = {"environment": {"IZO_SHADOW_FIXTURE": subject.MARKER}}
        shadow = SimpleNamespace(config=Mock(return_value={"services": {"backend": expected}}), docker=Mock())
        identity = {"containerId": "owned"}
        valid = provider_receipt()
        for raw, error in ((json.dumps(valid), None), ("я" * 32769, "D3_PROVIDER_RECEIPT_LIMIT"),
                           (json.dumps({**valid, "fixture": "controlled-audio-v1"}), "D3_PROVIDER_PROFILE_CHANGED")):
            shadow.docker.return_value = raw
            with self.subTest(error=error), patch.object(subject, "api_identity", return_value=identity), \
                    patch.object(subject, "wallclock", return_value=nullcontext()) as deadline:
                reader = subject.fixed_provider_reader(shadow, {})
                if error:
                    with self.assertRaisesRegex(ProductError, error):
                        reader()
                else:
                    self.assertEqual(reader(), valid)
                deadline.assert_called_once_with(8)
                shadow.docker.assert_called_with("exec", "owned", "python", "-c", subject.READ_RECEIPT, timeout=8)

    @unittest.skipUnless(hasattr(signal, "setitimer"), "Linux/POSIX wall-clock deadline")
    def test_real_nested_wallclock_interrupts_and_leaves_no_alarm(self):
        started = time.monotonic()
        with self.assertRaises(subject.BudgetExpired):
            with subject.wallclock(.02):
                with subject.wallclock(.2):
                    time.sleep(.3)
        self.assertLess(time.monotonic() - started, .2)
        self.assertEqual(signal.getitimer(signal.ITIMER_REAL), (0.0, 0.0))


class CleanupAndCheckpointTests(unittest.TestCase):
    def test_browser_success_without_owned_child_cleanup_is_not_accepted(self):
        self.assertTrue(subject.browser_process(process_receipt()))
        for key, value in (("timedOut", True), ("nodeReturncode", 1), ("nodeReturncode", False),
                           ("scope", "NODE_PROCESS_GROUP"), ("cleanup", {"status": "PASS"}), ("status", "FAIL")):
            row = process_receipt()
            row[key] = value
            with self.subTest(key=key, value=value):
                self.assertFalse(subject.browser_process(row))
        for key in ("childrenAtShutdown", "remainingChildren"):
            for value in (1, False):
                row = process_receipt()
                row["cleanup"][key] = value
                with self.subTest(key=key, value=value):
                    self.assertFalse(subject.browser_process(row))

    def test_cleaned_late_video_failure_may_supply_image_but_is_never_a_pass(self):
        row = process_receipt()
        row.update(status="FAIL", nodeReturncode=1)
        self.assertTrue(subject.browser_cleaned(row))
        self.assertFalse(subject.browser_process(row))
        row["cleanup"]["remainingChildren"] = 1
        self.assertFalse(subject.browser_cleaned(row))
        self.assertFalse(subject.browser_cleaned(None))

    def test_late_failure_retains_finished_modes_but_overwrites_provisional_pass(self):
        for error in (RuntimeError(PRIVATE), subject.BudgetExpired()):
            with tempfile.TemporaryDirectory() as temporary, patch.object(subject, "wallclock", return_value=nullcontext()):
                directory, report = Path(temporary), {"checks": {}}
                def action():
                    report["checks"]["imageModes"] = {"status": "PASS", "modes": {"edit": {"status": "PASS"}}}
                    raise error
                row = subject.checkpoint_step(report, directory, "imageModes", 1, action)
                self.assertEqual(row["status"], "FAIL")
                self.assertEqual(row["modes"]["edit"]["status"], "PASS")
                saved = (directory / "receipt.json").read_text()
                self.assertNotIn(PRIVATE, saved)
                self.assertEqual(json.loads(saved)["checks"]["imageModes"]["status"], "FAIL")

    def test_all_controlled_steps_passing_still_leaves_overall_d3_partial(self):
        rows = observations()
        executor = subject.IsolatedExecutor(Mock(), context="default", engine_id="owned-engine-id-123",
                                            machine_sha256="a" * 64)
        seed = SimpleNamespace(executor=executor, fixture=True, sha=SHA)
        with tempfile.TemporaryDirectory() as temporary, patch.object(subject, "run_admin", return_value={"status": "PASS"}), \
                patch.object(subject, "run_generation", return_value={"status": "PASS"}), \
                patch.object(subject, "run_audio", return_value={"status": "PASS"}):
            report = subject.rehearse_d3(seed, Path(temporary) / "output", attempts=rows, selected_project=rows[0]["project"])
        self.assertEqual(report["controlledScenarios"], "PASS")
        self.assertEqual(report["status"], "PARTIAL")
        self.assertEqual(report["D1AssertionsRequired"], 48)
        self.assertTrue(report["remainingAcceptance"])


class PhoneMatrixReceiptTests(unittest.TestCase):
    def generation(self):
        job, url = "owned-full-phone-job", "/api/media/owned.png"
        identity = {"sourceSha": SHA, "project": "izo-asa-shadow-d3-owned", "runId": "b" * 32}
        phone = {**identity, "status": "PASS", "uiCancellation": "NOT_SUPPORTED", "jobId": job,
            "newGenerationRequests": 0, "imageId": "owned-image", "imageUrl": url,
            "decoded": {"url": url, "complete": True, "width": 64, "height": 64},
            "statuses": {key: "processing" for key in ("initialStatus", "reloadedStatus", "returnedStatus")},
            "observations": {"sameJobAfterReload": True, "spaSignalAborted": True,
                "pollsAfterUnmount": 0, "imageSubmits": 0, "videoSubmits": 0}}
        watch = {**identity, "status": "PASS", "cleanup": "PASS", "threadAlive": False,
            "fullJobOwnerVerified": True, "wasHeld": True, "newGenerationRequests": 0,
            "releaseSeconds": 12, "jobId": job,
            "clientSha256": hashlib.sha256(("onenode-backend-" + job).encode()).hexdigest(),
            "holdAck": {"sequence": 1, "action": "hold", "status": "ACK"},
            "releaseAck": {"sequence": 2, "action": "release", "status": "ACK"}}
        browser = {**identity, "status": "PASS", "image": {"jobId": job, "id": "owned-image", "url": url},
                   "checks": {"chatImage": {"phoneActive": phone}}}
        return {"status": "PASS", "checks": {"chatVideo": {
            "status": "PASS", "browser": browser, "phoneWatch": watch, "process": process_receipt()}}}

    def rehearse(self, generation):
        rows = observations()
        executor = subject.IsolatedExecutor(Mock(), context="default", engine_id="owned-engine-id-123",
                                            machine_sha256="a" * 64)
        seed = SimpleNamespace(executor=executor, fixture=True, sha=SHA)
        with tempfile.TemporaryDirectory() as temporary, patch.object(subject, "run_admin", return_value={"status": "PASS"}), \
                patch.object(subject, "run_generation", return_value=generation), \
                patch.object(subject, "run_audio", return_value={"status": "PASS"}):
            directory = Path(temporary) / "output"
            report = subject.rehearse_d3(seed, directory, attempts=rows, selected_project=rows[0]["project"])
            self.assertEqual(json.loads((directory / "receipt.json").read_text()), report)
        return report

    def test_verified_active_resume_is_separate_from_cancel_and_late_video_failure(self):
        for late_failure in (False, True):
            with self.subTest(late_failure=late_failure):
                generation = self.generation()
                if late_failure:
                    generation["status"] = "FAIL"
                    video = generation["checks"]["chatVideo"]
                    video.update(status="FAIL", errorCode="D3_LTX_PROVIDER_MEDIA_MISMATCH")
                    video["browser"]["status"] = "FAIL"
                    video["process"].update(status="FAIL", nodeReturncode=1)
                report = self.rehearse(generation)
                self.assertEqual(report["phoneAcceptance"], {"activeResume": "PASS", "uiCancellation": "NOT_SUPPORTED"})
                self.assertEqual(report["status"], "FAIL" if late_failure else "PARTIAL")
                self.assertEqual(report["controlledScenarios"], "FAIL" if late_failure else "PASS")
                self.assertEqual(report["remainingAcceptance"], ["real selected models/audio", "video publication restart",
                    "remaining bounded admin audit findings", "target capacity and Windows factory route"])
                self.assertEqual(report["profiles"]["generation"], generation)
                self.assertEqual(report["D1AssertionsRequired"], 48)

    def test_missing_malformed_unjoined_or_unclean_phone_proof_remains_outstanding(self):
        faults = (
            lambda video: video.clear(),
            lambda video: video.update(browser={"checks": PRIVATE}),
            lambda video: video["phoneWatch"].update(cleanup="FAIL"),
            lambda video: video["phoneWatch"].update(threadAlive=True),
            lambda video: video["process"]["cleanup"].update(remainingChildren=1),
            lambda video: video["browser"]["checks"]["chatImage"]["phoneActive"].update(jobId="different-full-id"),
        )
        for index, fault in enumerate(faults):
            with self.subTest(fault=index):
                generation = self.generation()
                fault(generation["checks"]["chatVideo"])
                report = self.rehearse(generation)
                self.assertEqual(report["phoneAcceptance"], {"activeResume": "NOT_VERIFIED", "uiCancellation": "NOT_SUPPORTED"})
                self.assertIn("Phone active browser resume", report["remainingAcceptance"])
                self.assertNotIn("Phone active browser resume/cancel", report["remainingAcceptance"])
                self.assertEqual(report["status"], "PARTIAL")
                self.assertNotIn(PRIVATE, json.dumps(report["phoneAcceptance"]))

    def test_publication_gap_requires_pass_inside_existing_image_profile(self):
        for status, proof in (("PASS", {"status": "PASS"}), ("FAIL", {"status": "PASS"}),
                              ("PASS", {"status": "FAIL"}), ("PASS", None), ("NOT_RUN", {})):
            with self.subTest(status=status, proof=proof):
                generation = self.generation()
                generation["checks"]["imageProfile"] = {"status": status, "publicationPersistence": proof}
                report = self.rehearse(generation)
                self.assertEqual("video publication restart" in report["remainingAcceptance"],
                                 not (status == "PASS" and proof == {"status": "PASS"}))
                self.assertEqual(report["status"], "PARTIAL")
                self.assertEqual(report["D1AssertionsRequired"], 48)


class MiniGrantTests(unittest.TestCase):
    def clients(self, *, actor=None, before=None, audit=None, slots=1):
        owner = Mock(side_effect=[{"internal_user_id": "owner"}, {"videoSlots": slots}])
        entry = {"id": "audit-id", "actor_internal_user_id": "admin", "target_internal_user_id": "owner",
                 "action": "admin_change_plan", "after": {"plan": "mini"}}
        admin = Mock(side_effect=[{"ok": True}, actor or {"internal_user_id": "admin", "account": {"role": "admin"}},
            before or {"total": 0, "items": []}, {"ok": True, "internal_user_id": "owner", "plan": "mini"},
            audit or {"total": 1, "items": [entry]}])
        return SimpleNamespace(owner=SimpleNamespace(request=owner)), SimpleNamespace(request=admin)

    def test_one_normal_grant_uses_nested_role_and_returns_only_safe_audit_identity(self):
        flow, admin = self.clients()
        row = subject.grant_owned_mini(flow, admin, PRIVATE)
        self.assertEqual(row["status"], "PASS")
        self.assertEqual(row["auditId"], "audit-id")
        grants = [call for call in admin.request.call_args_list if call.args[1].endswith("/plan-v2")]
        self.assertEqual(len(grants), 1)
        self.assertEqual(grants[0].args[2]["duration_days"], 1)
        self.assertEqual(grants[0].args[1], "/api/admin/users/owner/plan-v2")
        self.assertNotIn(PRIVATE, json.dumps(row))

    def test_wrong_actor_role_or_preexisting_grant_cannot_mutate_account(self):
        for params in ({"actor": {"internal_user_id": "admin", "role": "admin", "account": {"role": "user"}}},
                       {"actor": {"internal_user_id": "owner", "account": {"role": "admin"}}},
                       {"before": {"total": 1, "items": [{"id": "earlier"}]}}):
            flow, admin = self.clients(**params)
            with self.subTest(params=params), self.assertRaises(ProductError):
                subject.grant_owned_mini(flow, admin, PRIVATE)
            self.assertFalse(any(call.args[1].endswith("/plan-v2") for call in admin.request.call_args_list))

    def test_false_slot_or_wrong_target_audit_prevents_success(self):
        for params in ({"slots": True}, {"slots": 0}, {"audit": {"total": 1, "items": [{
                "id": "audit-id", "actor_internal_user_id": "admin", "target_internal_user_id": "foreign",
                "action": "admin_change_plan", "after": {"plan": "mini"}}]}}):
            flow, admin = self.clients(**params)
            with self.subTest(params=params), self.assertRaises(ProductError):
                subject.grant_owned_mini(flow, admin, PRIVATE)


if __name__ == "__main__":
    unittest.main()
