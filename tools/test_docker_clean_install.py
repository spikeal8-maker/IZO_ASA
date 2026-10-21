"""Safety and truthful-evidence regression tests for the disposable runner driver."""
from contextlib import ExitStack
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from tools import docker_clean_install as clean
from tools.docker_shadow_product import HttpClient, ProductError


class AdmissionAndCleanupTests(unittest.TestCase):
    def test_shared_or_wrong_repository_runner_never_admitted(self):
        good = {"GITHUB_ACTIONS": "true", "GITHUB_REPOSITORY": clean.REPOSITORY,
                "GITHUB_SHA": "a" * 40, "RUNNER_ENVIRONMENT": "github-hosted"}
        with patch.object(clean.platform, "system", return_value="Linux"), \
                patch.object(clean.platform, "machine", return_value="x86_64"):
            for changed in ({"RUNNER_ENVIRONMENT": "self-hosted"}, {"GITHUB_ACTIONS": "false"},
                            {"GITHUB_REPOSITORY": "other/project"}, {"GITHUB_SHA": "c" * 40}):
                with self.subTest(changed=changed), patch.dict(os.environ, {**good, **changed}, clear=True):
                    with self.assertRaisesRegex(clean.AcceptanceError, "DISPOSABLE_RUNNER_REQUIRED"):
                        clean.host_admission("a" * 40, "b" * 40, Path("/tmp/evidence"))

    def test_existing_attempt_evidence_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as temp:
            evidence = Path(temp) / "prior-attempt"
            evidence.mkdir()
            marker = evidence / "receipt.json"
            marker.write_text('{"status":"FAIL"}')
            env = {"GITHUB_ACTIONS": "true", "GITHUB_REPOSITORY": clean.REPOSITORY,
                   "GITHUB_SHA": "a" * 40, "RUNNER_ENVIRONMENT": "github-hosted", "RUNNER_TEMP": temp}
            with patch.dict(os.environ, env, clear=True), \
                    patch.object(clean.platform, "system", return_value="Linux"), \
                    patch.object(clean.platform, "machine", return_value="x86_64"):
                with self.assertRaisesRegex(clean.AcceptanceError, "PREVIOUS_EVIDENCE_EXISTS"):
                    clean.host_admission("a" * 40, "b" * 40, evidence)
            self.assertEqual(json.loads(marker.read_text())["status"], "FAIL")

    def test_cleanup_refuses_resources_without_fresh_admission(self):
        shadow = Mock()
        with self.assertRaisesRegex(clean.AcceptanceError, "CLEANUP_NOT_ADMITTED"):
            clean.cleanup_owned(shadow, False)
        self.assertEqual(shadow.mock_calls, [])

    def test_foreign_ownership_blocks_project_deletion(self):
        shadow = Mock()
        shadow.ownership_guard.side_effect = RuntimeError("SHADOW_FOREIGN_VOLUME")
        with self.assertRaisesRegex(RuntimeError, "SHADOW_FOREIGN_VOLUME"):
            clean.cleanup_owned(shadow, True)
        shadow.compose.assert_not_called()

    def test_old_owned_volume_is_not_a_fresh_install(self):
        with patch.object(clean, "owned_inventory", return_value={"containers": [], "volumes": ["old"]}):
            with self.assertRaisesRegex(clean.AcceptanceError, "PROJECT_NOT_FRESH"):
                clean.require_fresh(Mock())


class EvidenceTests(unittest.TestCase):
    def test_browser_success_cannot_hide_failed_signup_session_cleanup(self):
        signup = Mock()
        signup.credentials = [(signup.owner, "fixture@example.invalid", "in-memory-only")]
        signup.close.return_value = {"sessionCleanup": "FAIL", "failedSessions": 1}
        with tempfile.TemporaryDirectory() as temp:
            destination = Path(temp)
            (destination / "browser.json").write_text('{"status":"PASS"}')
            with patch.object(clean, "ProductFlow", return_value=signup), \
                    patch.object(clean.subprocess, "run", return_value=Mock(returncode=0)):
                with self.assertRaisesRegex(clean.AcceptanceError, "BROWSER_SIGNUP_CLEANUP_FAILED"):
                    clean.browser(Mock(sha="a" * 40), destination, {"origin": "http://127.0.0.1:48001"})
            saved = json.loads((destination / "signup-cleanup.json").read_text())
            self.assertEqual(saved["sessionCleanup"], "FAIL")

    def test_initial_failure_is_saved_without_a_successful_scenario(self):
        shadow = Mock(sha="a" * 40, project="izo-asa-shadow-failed", web_port=48001, api_port=48002)
        shadow.source_guard.side_effect = RuntimeError("raw password=must-not-be-recorded")
        with tempfile.TemporaryDirectory() as temp:
            destination = Path(temp) / "run-1"
            report = clean.execute_run(shadow, destination, build=True, base="b" * 40, host={})
            text = (destination / "receipt.json").read_text()
            self.assertEqual(report["status"], "FAIL")
            self.assertEqual(report["failedStage"], "admission")
            self.assertNotIn("must-not-be-recorded", text)
            self.assertFalse(any(row["status"] == "PASS" for row in report["checks"].values()))
            shadow.compose.assert_not_called()

    def test_provider_requires_actual_completed_wire_jobs(self):
        evidence = {"fixture": "controlled-comfyui-v1", "provider": {
            "counts": {"accepted": 3}, "jobs": [{"state": "completed"}] * 3, "model_execution": False}}
        with patch.object(clean, "inside_backend", return_value=evidence):
            self.assertEqual(clean.provider_receipt(Mock(), 3), evidence)
            evidence["provider"]["jobs"][0] = {"state": "held"}
            with self.assertRaisesRegex(clean.AcceptanceError, "WIRE_NOT_PROVEN"):
                clean.provider_receipt(Mock(), 3)
            evidence["provider"].update(counts={}, jobs=[])
            self.assertEqual(clean.provider_receipt(Mock(), 0), evidence)

    def test_logs_remove_headers_credentials_and_fixture_emails(self):
        raw = 'Authorization: Bearer short-value\n{"password": "with spaces secret"}\n' \
              'Cookie: first=one; second=two\nuser shadow@example.invalid\nERROR database unavailable'
        safe = clean.redact_logs(raw)
        for secret in ("short-value", "with spaces secret", "first=one", "second=two", "shadow@example.invalid"):
            self.assertNotIn(secret, safe)
        self.assertIn("ERROR database unavailable", safe)


class ApiLatencyTests(unittest.TestCase):
    def flow(self, gallery_body, *, healthy=True):
        client = HttpClient("http://127.0.0.1:48001")
        def respond(request, **_options):
            route = request.full_url.removeprefix(client.origin)
            body = gallery_body if route == "/api/gallery" else json.dumps({
                "ok": True, "ready": healthy, "route": route}).encode()
            response = io.BytesIO(body)
            response.status = 200
            return response
        client.opener = Mock()
        client.opener.open.side_effect = respond
        return Mock(owner=client, guest=client), client

    def test_real_http_client_accepts_gallery_array_and_records_twelve_samples(self):
        flow, client = self.flow(b'[{"id":"fixture-image"}]')
        samples = clean.api_samples(flow)
        self.assertEqual(len(samples), 12)
        self.assertEqual(client.opener.open.call_count, 12)
        for route in ("/api/health", "/api/me-v2", "/api/gallery", "/api/feed"):
            self.assertEqual(sum(row["route"] == route for row in samples), 3)
        self.assertTrue(all(row["items"] == 1 for row in samples if row["route"] == "/api/gallery"))
        self.assertNotIn("fixture-image", json.dumps(samples))
        self.assertTrue(all(row["milliseconds"] >= 0 and row["httpStatus"] == 200 for row in samples))

    def test_invalid_gallery_shapes_fail_without_exposing_response(self):
        for body in (b'{"private":"sensitive"}', b'not-json-sensitive', b'null',
                     b'"sensitive"', b'["sensitive"]', b'\xff'):
            with self.subTest(body=body):
                flow, _client = self.flow(body)
                with self.assertRaises(clean.AcceptanceError) as raised:
                    clean.api_samples(flow)
                self.assertEqual(str(raised.exception), "ACCEPTANCE_GALLERY_SAMPLE_INVALID")

    def test_default_product_json_contract_and_health_readiness_remain_strict(self):
        flow, client = self.flow(b'[]')
        with self.assertRaisesRegex(ProductError, "PRODUCT_RESPONSE_INVALID"):
            client.request("GET", "/api/gallery")
        flow, _client = self.flow(b'[]', healthy=False)
        with self.assertRaisesRegex(clean.AcceptanceError, "ACCEPTANCE_API_NOT_READY"):
            clean.api_samples(flow)


class ExtendedEvidenceTests(unittest.TestCase):
    def boundaries(self, stack):
        flow = Mock(checks={"auth": {"status": "PASS"}})
        flow.run.return_value = flow.checks
        flow.verify_persistence.return_value = {"status": "PASS"}
        flow.guest.request.return_value = {"ok": True, "ready": True}
        flow.owner.request.side_effect = lambda _method, route, **_options: b'[]' if route == "/api/gallery" else {}
        flow.close.return_value = {"sessionCleanup": "PASS"}

        def factory(project, sha, web_port=48125, api_port=48126, **_options):
            shadow = Mock(project=project, sha=sha, web_port=web_port, api_port=api_port)
            shadow.config.return_value = {"services": {}}
            shadow.executor.foreign_snapshot.return_value = {"containers": []}
            shadow.compose.return_value = "unit fixture log"
            shadow.run.return_value = json.dumps({"ID": "unit-engine", "ServerVersion": "unit", "NCPU": 2, "MemTotal": 4096})
            return shadow

        def browser(_shadow, directory, _attestation):
            clean.save(directory / "browser.json", {"status": "PASS"})
            (directory / "unit.png").write_bytes(b"unit screenshot boundary")
            return {"status": "PASS"}

        patches = {"Shadow": {"side_effect": factory}, "ProductFlow": {"return_value": flow},
            "require_fresh": {}, "browser": {"side_effect": browser},
            "prove": {"side_effect": lambda _shadow, path, **_options: clean.save(path, {"status": "PASS"})},
            "provider_receipt": {"side_effect": lambda _shadow, count: {"provider": {"counts": {"accepted": count}}}},
            "storage": {"return_value": {"media": {"fixture.png": "stable-digest"}}},
            "telemetry": {"return_value": {}}, "compare_isolated": {"return_value": {"status": "PASS"}},
            "cleanup_owned": {"return_value": {"status": "PASS"}}}
        installed = {name: stack.enter_context(patch.object(clean, name, **options)) for name, options in patches.items()}
        return factory, flow, installed["cleanup_owned"]

    def test_extended_setup_exception_preserves_d1_but_fails_saved_run(self):
        with tempfile.TemporaryDirectory() as temporary, ExitStack() as stack:
            factory, _flow, cleanup = self.boundaries(stack)
            stack.enter_context(patch.object(clean, "extended_probes", side_effect=RuntimeError("raw capability=private")))
            directory = Path(temporary) / "run"
            report = clean.execute_run(factory("izo-asa-shadow-unit", "a" * 40), directory,
                                       build=False, base="b" * 40, host={}, extended=True)
            self.assertEqual((report["D1Status"], report["status"]), ("PASS", "FAIL"))
            self.assertEqual(report["failedStage"], "D2-D3")
            self.assertEqual(json.loads((directory / "receipt.json").read_text()), report)
            self.assertNotIn("capability=private", json.dumps(report))
            cleanup.assert_called_once()

    @staticmethod
    def measured(shadow, status="FAIL"):
        passed = lambda: {"status": "PASS"}
        session = lambda: {"sessionCleanup": "PASS"}
        checks = {key: {"status": "PASS", "cleanupRestart": {
            "beforeContainer": "1" * 64, "afterContainer": "2" * 64}}
            for key in ("D2-01", "D2-02", "D2-03", "D3-queue")}
        if status == "FAIL":
            checks["D2-02"].update(status="FAIL", errorCode="RECOVERY_DUPLICATE_GENERATION_CHARGED")
            checks["D2-03"]["status"] = "PARTIAL"
        return {"status": status, "results": {
            "storage": {"status": "PASS", "sourceSha": shadow.sha, "sourceProject": shadow.project,
                "checks": {key: passed() for key in ("D2-04", "D2-05", "D2-06")},
                "cleanup": passed(), "foreignComparison": passed(), "sessionCleanup": session(),
                "sourceQuiescence": passed(), "sourceUnchanged": "PASS"},
            "recovery": {"status": status, "sourceSha": shadow.sha, "project": shadow.project,
                "checks": {key: checks[key] for key in ("D2-01", "D2-02", "D2-03")},
                "measurements": {"D3-queue": checks["D3-queue"]},
                "sessionCleanup": session(), "foreignResources": passed()},
            "features": {"status": "PARTIAL" if status == "FAIL" else "PASS", "sourceSha": shadow.sha,
                "project": shadow.project, "checks": {"chatHistory": {"status": "PASS", "threadCleanup": "PASS"}}},
            "admin": {"status": "PASS", "sourceSha": shadow.sha, "project": shadow.project + "-admin",
                "cleanup": passed(), "foreignResources": passed(), "acceptance": {"status": "PASS",
                    "sourceSha": shadow.sha, "project": shadow.project + "-admin", "cleanup": session(),
                    "checks": {"modelEconomics": {"status": "PASS", "settingCleanup": "PASS", "accountInvariance": "PASS"}}}}}}

    def main_result(self, statuses=("FAIL",) * 3, *, extended=True, change=None, stop=None, at=1):
        with tempfile.TemporaryDirectory() as temporary, ExitStack() as stack:
            _factory, flow, cleanup = self.boundaries(stack)
            directory = Path(temporary) / "evidence"
            host = {"runId": "42", "attempt": "1", "machineIdentitySha256": "c" * 64}
            observed = []

            def probe(shadow, _flow, _attestation, _directory):
                self.assertEqual(flow.verify_persistence.call_count, len(observed) + 1)
                value = self.measured(shadow, statuses[len(observed)])
                if change is not None and len(observed) + 1 == at:
                    value = change(value)
                observed.append(value)
                return value

            if stop == "d1":
                flow.run.side_effect = clean.AcceptanceError("UNIT_D1_FAILED")
            if stop == "session":
                flow.close.side_effect = clean.AcceptanceError("UNIT_SESSION_FAILED")
            if stop == "cleanup":
                cleanup.side_effect = clean.AcceptanceError("UNIT_CLEANUP_FAILED")
            if stop == "foreign":
                stack.enter_context(patch.object(clean, "compare_isolated", return_value={"status": "FAIL"}))
            stack.enter_context(patch.object(clean, "host_admission", return_value=host))
            stack.enter_context(patch.object(clean, "ports", return_value=(48125, 48126)))
            probes = stack.enter_context(patch.object(clean, "extended_probes", side_effect=probe))
            runs = stack.enter_context(patch.object(clean, "execute_run", wraps=clean.execute_run))
            arguments = ["docker-clean", "--source-sha", "a" * 40, "--base-sha", "b" * 40,
                         "--evidence-dir", str(directory), "--replica", "1"]
            stack.enter_context(patch.object(sys, "argv", arguments + (["--extended"] if extended else [])))
            with patch("sys.stdout", new=io.StringIO()):
                code = clean.main()
            summary = json.loads((directory / "summary.json").read_text())
            receipts = [json.loads((directory / f"run-{n}/receipt.json").read_text())
                        for n in range(1, summary["completedFixtureRuns"] + 1)]
            self.assertEqual(len(list(directory.glob("run-*/receipt.json"))), len(receipts))
            self.assertEqual(len({row["project"] for row in receipts}), len(receipts))
            self.assertEqual([call.kwargs["build"] for call in runs.call_args_list],
                             [True] + [False] * (len(receipts) - 1))
            self.assertTrue(all(call.kwargs["build"] is False for call in clean.prove.call_args_list))
            if extended:
                self.assertEqual(summary["extended"]["status"], "FAIL" if code else "PASS")
                for number, (entry, receipt) in enumerate(zip(summary["extended"]["runs"], receipts), 1):
                    self.assertEqual(entry, {"project": receipt["project"], "receipt": f"run-{number}/receipt.json",
                        "result": receipt.get("extended", {"status": "NOT_RUN"})})
                    self.assertEqual(receipt["sourceSha"], "a" * 40)
                self.assertEqual(len(summary["extended"]["runs"]), len(receipts))
            return code, summary, receipts, probes.call_count

    def test_three_d1_results_survive_a_measured_d2_failure_in_summary(self):
        code, summary, receipts, calls = self.main_result()
        self.assertEqual((code, summary["D1Status"], summary["status"]), (1, "PASS", "FAIL"))
        self.assertEqual([row["status"] for row in summary["runs"]], ["FAIL"] * 3)
        self.assertEqual((summary["completedFixtureRuns"], calls), (3, 3))
        for receipt in receipts:
            self.assertEqual((receipt["D1Status"], receipt["failedStage"]), ("PASS", "D2-D3"))
            self.assertEqual(receipt["extended"]["results"]["features"]["status"], "PARTIAL")
            self.assertEqual(receipt["extended"]["results"]["recovery"]["checks"]["D2-03"]["status"], "PARTIAL")

    def test_earlier_measurement_failure_cannot_be_hidden_by_later_passes(self):
        code, summary, receipts, calls = self.main_result(("FAIL", "PASS", "PASS"))
        self.assertEqual((code, summary["status"], summary["extended"]["status"], calls), (1, "FAIL", "FAIL", 3))
        self.assertEqual([row["status"] for row in receipts], ["FAIL", "PASS", "PASS"])
        self.assertEqual([row["D1Status"] for row in receipts], ["PASS"] * 3)

    def test_default_mode_retains_three_d1_runs_and_stops_on_first_failure(self):
        for stop, count, code in ((None, 3, 0), ("d1", 1, 1)):
            with self.subTest(stop=stop):
                result, summary, _receipts, calls = self.main_result(extended=False, stop=stop)
                self.assertEqual((result, summary["completedFixtureRuns"], calls), (code, count, 0))
                self.assertEqual(summary["extended"], {"status": "NOT_RUN"})

    def test_outer_d1_and_cleanup_failures_never_start_another_fixture(self):
        for stop in ("d1", "session", "cleanup", "foreign"):
            with self.subTest(stop=stop):
                code, summary, receipts, _calls = self.main_result(stop=stop)
                self.assertEqual((code, len(receipts), summary["D1Status"]), (1, 1, "FAIL"))
                self.assertEqual(summary["extended"]["status"], "FAIL")

    def test_incomplete_or_unbound_extended_result_stops_and_keeps_prior_receipt(self):
        def replace_leaf(value):
            value["results"]["storage"] = {"status": "FAIL", "errorCode": "UNIT_INVOCATION_FAILED"}
            return value
        def wrong_source(value):
            value["results"]["recovery"]["sourceSha"] = "b" * 40
            return value
        for change in (lambda _: None, lambda _: {"status": "FAIL"}, lambda _: {"status": "PASS"}, replace_leaf, wrong_source):
            with self.subTest(change=change):
                code, summary, receipts, calls = self.main_result(change=change, at=2)
                self.assertEqual((code, len(receipts), calls), (1, 2, 2))
                self.assertEqual(summary["status"], "FAIL")
                self.assertEqual(receipts[0]["extended"]["results"]["features"]["status"], "PARTIAL")

    def test_incomplete_last_result_cannot_make_three_outer_passes_successful(self):
        code, summary, receipts, calls = self.main_result(("PASS",) * 3, change=lambda _: {"status": "PASS"}, at=3)
        self.assertEqual((code, len(receipts), calls, summary["status"]), (1, 3, 3, "FAIL"))
        self.assertEqual([row["status"] for row in receipts], ["PASS"] * 3)

    def test_nested_cleanup_failures_are_not_classified_as_repeatable_measurements(self):
        paths = (
            ("storage", "cleanup", "status"), ("storage", "foreignComparison", "status"),
            ("storage", "sessionCleanup", "sessionCleanup"), ("storage", "sourceQuiescence", "status"),
            ("storage", "sourceUnchanged"), ("recovery", "sessionCleanup", "sessionCleanup"),
            ("recovery", "foreignResources", "status"), ("features", "checks", "chatHistory", "threadCleanup"),
            ("admin", "cleanup", "status"), ("admin", "foreignResources", "status"),
            ("admin", "acceptance", "cleanup", "sessionCleanup"),
            ("admin", "acceptance", "checks", "modelEconomics", "settingCleanup"),
            ("admin", "acceptance", "checks", "modelEconomics", "accountInvariance"),
            ("recovery", "checks", "D2-01", "cleanupRestart"),
            ("recovery", "measurements", "D3-queue", "cleanupRestart"))
        for path in paths:
            def corrupt(value):
                node = value["results"]
                for key in path[:-1]:
                    node = node[key]
                node[path[-1]] = "FAIL"
                return value
            with self.subTest(path=path):
                code, summary, receipts, calls = self.main_result(change=corrupt)
                self.assertEqual((code, len(receipts), calls), (1, 1, 1))
                self.assertEqual(summary["status"], "FAIL")

    def test_session_exception_cannot_skip_owned_cleanup_or_claim_d1_pass(self):
        with tempfile.TemporaryDirectory() as temporary, ExitStack() as stack:
            factory, flow, cleanup = self.boundaries(stack)
            flow.close.side_effect = RuntimeError("private session payload")
            directory = Path(temporary) / "run"
            report = clean.execute_run(factory("izo-asa-shadow-unit", "a" * 40), directory,
                                       build=False, base="b" * 40, host={})
            self.assertEqual((report["D1Status"], report["status"]), ("FAIL", "FAIL"))
            self.assertEqual(report["sessionCleanup"]["sessionCleanup"], "FAIL")
            cleanup.assert_called_once()
            self.assertEqual(report["foreignResources"]["status"], "PASS")
            self.assertEqual(json.loads((directory / "receipt.json").read_text()), report)
            self.assertNotIn("private session payload", json.dumps(report))


if __name__ == "__main__":
    unittest.main()
