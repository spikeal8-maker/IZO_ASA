"""Admission/receipt counterexamples; no browser, child processes or listening ports."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from tools import docker_d3_phone_ui as ui


SOURCE = "a" * 40


def expected():
    return {"schema": "izo-d3-phone-ui/v1", "sourceSha": SOURCE, "jobIdentity": "123.1.phone_ui",
            "runId": "b" * 32, "helperSha256": "c" * 64, "buildIndexSha256": "d" * 64,
            "runnerSha256": "e" * 64}


def browser_receipt(identity=None):
    cases = []
    for name in ui.CASE_NAMES:
        case = {"case": name, "status": "PASS"}
        if name.endswith("spa-unmount"):
            case.update(signalAborted=True, furtherReads=0)
        else:
            case.update(sameJobId="phone-ui-owned-image", generatedRequests=0)
            if name.endswith("recovery-retry"):
                case["recoveryRetried"] = True
                case["pollingRetried"] = True
        cases.append(case)
    return {**(identity or expected()), "status": "PASS", "browserCleanup": "PASS", "serverCleanup": "PASS",
            "proof": {"status": "PASS", "evidenceClass": "mocked-api-real-phone-ui",
                "installedAcceptance": "NOT_VERIFIED", "uiCancellation": "NOT_SUPPORTED",
                "modelExecution": False, "acceleratorExecution": False, "cases": cases}}


def process_receipt():
    return {"status": "PASS", "scope": "PRIVATE_LINUX_SUBREAPER", "nodeReturncode": 0, "timedOut": False,
            "cleanup": {"status": "PASS", "childrenAtShutdown": 0, "remainingChildren": 0,
                        "remainingUnknown": False, "overflow": False, "errors": []}}


class ReceiptTests(unittest.TestCase):
    def test_exact_ten_cases_and_identity_pass(self):
        self.assertEqual(ui.validate_browser(browser_receipt(), expected())["status"], "PASS")

    def test_case_count_duplicate_skip_foreign_and_boolean_counter_fail(self):
        changes = [lambda cases: cases.pop(), lambda cases: cases.append(cases[0]),
                   lambda cases: cases.__setitem__(1, deepcopy(cases[0])),
                   lambda cases: cases[0].update(status="SKIP"),
                   lambda cases: cases[0].update(sameJobId="foreign"),
                   lambda cases: cases[0].update(generatedRequests=False),
                   lambda cases: cases[2].update(furtherReads=1),
                   lambda cases: cases[2].update(signalAborted=False),
                   lambda cases: cases[4].update(recoveryRetried=False),
                   lambda cases: cases[4].update(pollingRetried=False)]
        for change in changes:
            with self.subTest(change=changes.index(change)):
                value = browser_receipt()
                change(value["proof"]["cases"])
                with self.assertRaises(ui.UiFailure):
                    ui.validate_browser(value, expected())

    def test_every_source_job_run_and_hash_link_is_required(self):
        for key in expected():
            with self.subTest(key=key):
                value = browser_receipt()
                value[key] = "foreign"
                with self.assertRaisesRegex(ui.UiFailure, "IDENTITY_MISMATCH"):
                    ui.validate_browser(value, expected())

    def test_cannot_claim_installed_model_or_cancel_evidence(self):
        for key, value in {"evidenceClass": "installed", "modelExecution": True, "acceleratorExecution": True,
                           "installedAcceptance": "PASS", "uiCancellation": "PASS"}.items():
            with self.subTest(key=key):
                receipt = browser_receipt()
                receipt["proof"][key] = value
                with self.assertRaisesRegex(ui.UiFailure, "PROOF_INVALID"):
                    ui.validate_browser(receipt, expected())

    def test_browser_and_preview_cleanup_are_required(self):
        for key in ("browserCleanup", "serverCleanup"):
            receipt = browser_receipt()
            receipt[key] = "FAIL"
            with self.assertRaisesRegex(ui.UiFailure, "EXECUTION_FAILED"):
                ui.validate_browser(receipt, expected())

    def test_no_child_cleanup_counterexample_can_pass(self):
        ui.validate_process(process_receipt())
        for key, value in {"status": "FAIL", "childrenAtShutdown": 1, "remainingChildren": 1,
                           "remainingUnknown": True, "overflow": True, "errors": ["failure"]}.items():
            with self.subTest(key=key):
                receipt = process_receipt()
                receipt["cleanup"][key] = value
                with self.assertRaisesRegex(ui.UiFailure, "PROCESS_FAILED"):
                    ui.validate_process(receipt)
        receipt = process_receipt()
        receipt["nodeReturncode"] = False
        with self.assertRaises(ui.UiFailure):
            ui.validate_process(receipt)
        for value in (None, "PROCESS_GROUP_ONLY"):
            receipt = process_receipt()
            if value is None:
                receipt.pop("scope")
            else:
                receipt["scope"] = value
            with self.assertRaises(ui.UiFailure):
                ui.validate_process(receipt)


@unittest.skipUnless(sys.platform == "linux", "Hosted Linux owned-file admission uses O_NOFOLLOW and uid")
class OwnedRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "checkout"
        self.output = Path(self.temp.name) / "result"
        for relative, data in {"frontend/phoneJobRecovery.ui.mjs": "owned-helper",
                               "frontend/dist/index.html": f'<meta name="izo-release" content="{SOURCE}">',
                               "tools/docker_d3_phone_ui.mjs": "owned-runner",
                               "tools/docker_d3_process.py": "owned-supervisor"}.items():
            target = self.root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(data)
        self.environment = {"GITHUB_SHA": SOURCE, "GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "1",
                            "GITHUB_JOB": "phone_ui", "RUNNER_TEMP": self.temp.name}
        for operation in (patch.object(ui, "EXPECTED_HELPER_SHA", ui.digest(b"owned-helper")),
                          patch.object(ui, "require_ci")):
            operation.start()  # Unit fixture only; supervisor below never spawns.
            self.addCleanup(operation.stop)
        self.calls = []

    def supervise(self, command, payload, **kwargs):
        self.calls.append((command, payload, kwargs))
        identity = json.loads(payload)
        ui.save(self.output / "phone-ui-browser.json", browser_receipt(identity))
        return process_receipt()

    def invoke(self, **kwargs):
        return ui.run(self.root, self.output, SOURCE, self.environment, supervisor=self.supervise, **kwargs)

    def test_fixed_command_payload_and_absolute_work_budget(self):
        times = iter((10, 20, 21))
        receipt = self.invoke(clock=lambda: next(times))
        self.assertEqual(receipt["status"], "PASS")
        self.assertEqual(len(self.calls), 1)
        command, raw, options = self.calls[0]
        self.assertEqual(command, ["node", str(self.root / "tools/docker_d3_phone_ui.mjs")])
        self.assertEqual(options, {"cwd": self.root, "timeout": 130})
        self.assertEqual(json.loads(raw)["sourceSha"], SOURCE)
        self.assertEqual(json.loads((self.output / "phone-ui.json").read_text())["status"], "PASS")

    def test_preparation_time_can_exhaust_work_without_launch(self):
        times = iter((0, 141, 142))
        receipt = self.invoke(clock=lambda: next(times))
        self.assertEqual(receipt["errorCode"], "D3_PHONE_UI_DEADLINE_EXCEEDED")
        self.assertEqual(self.calls, [])

    def test_build_and_helper_mismatch_keep_failure_receipt_without_launch(self):
        for relative in ("frontend/dist/index.html", "frontend/phoneJobRecovery.ui.mjs"):
            with self.subTest(path=relative):
                target = self.root / relative
                before = target.read_bytes()
                target.write_bytes(b"foreign")
                receipt = self.invoke()
                self.assertEqual(receipt["status"], "FAIL")
                self.assertTrue((self.output / "phone-ui.json").is_file())
                self.assertEqual(self.calls, [])
                (self.output / "phone-ui.json").unlink()
                self.output.rmdir()
                target.write_bytes(before)

    def test_existing_output_is_not_borrowed(self):
        self.output.mkdir()
        marker = self.output / "foreign.txt"
        marker.write_text("preserve")
        self.assertEqual(self.invoke()["status"], "FAIL")
        self.assertEqual(marker.read_text(), "preserve")
        self.assertFalse((self.output / "phone-ui.json").exists())
        self.assertEqual(self.calls, [])

    def test_files_are_bounded_regular_private_and_never_symlink_followed(self):
        target = Path(self.temp.name) / "receipt.json"
        target.write_bytes(b"a" * (ui.LIMIT + 1))
        with self.assertRaises(ui.UiFailure):
            ui.bounded_file(target, ui.LIMIT)
        target.write_bytes(b"{}")
        target.chmod(0o644)
        with self.assertRaises(ui.UiFailure):
            ui.bounded_file(target, ui.LIMIT, private=True)
        link = Path(self.temp.name) / "link"
        link.symlink_to(target)
        with self.assertRaises(OSError):
            ui.bounded_file(link, ui.LIMIT)
        self.assertEqual(target.read_bytes(), b"{}")


class CiScopeTests(unittest.TestCase):
    def test_only_hosted_linux_nonroot_environment_admits(self):
        env = {"GITHUB_ACTIONS": "true", "RUNNER_ENVIRONMENT": "github-hosted"}
        with patch.object(ui.sys, "platform", "linux"), patch.object(ui.os, "getuid", return_value=1001, create=True):
            ui.require_ci(env)
            for value in ({}, {**env, "RUNNER_ENVIRONMENT": "self-hosted"}):
                with self.assertRaises(ui.UiFailure):
                    ui.require_ci(value)
        with patch.object(ui.sys, "platform", "linux"), patch.object(ui.os, "getuid", return_value=0, create=True):
            with self.assertRaises(ui.UiFailure):
                ui.require_ci(env)


if __name__ == "__main__":
    unittest.main()
