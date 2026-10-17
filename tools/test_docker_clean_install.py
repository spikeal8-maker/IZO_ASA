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

    def test_three_d1_results_survive_a_measured_d2_failure_in_summary(self):
        with tempfile.TemporaryDirectory() as temporary, ExitStack() as stack:
            self.boundaries(stack)
            directory = Path(temporary) / "evidence"
            host = {"runId": "42", "attempt": "1", "machineIdentitySha256": "c" * 64}
            failed = {"status": "FAIL", "results": {"recovery": {"status": "FAIL",
                      "checks": {"D2-02": {"status": "FAIL", "errorCode": "RECOVERY_DUPLICATE_GENERATION_CHARGED"}}}}}
            stack.enter_context(patch.object(clean, "host_admission", return_value=host))
            stack.enter_context(patch.object(clean, "ports", return_value=(48125, 48126)))
            extended = stack.enter_context(patch.object(clean, "extended_probes", return_value=failed))
            stack.enter_context(patch.object(sys, "argv", ["docker-clean", "--source-sha", "a" * 40,
                "--base-sha", "b" * 40, "--evidence-dir", str(directory), "--replica", "1", "--extended"]))
            self.assertEqual(clean.main(), 1)
            summary = json.loads((directory / "summary.json").read_text())
            self.assertEqual((summary["D1Status"], summary["status"]), ("PASS", "FAIL"))
            self.assertEqual([row["status"] for row in summary["runs"]], ["PASS", "PASS", "FAIL"])
            self.assertEqual(summary["extended"], failed)
            self.assertEqual(json.loads((directory / "run-3/receipt.json").read_text())["extended"], failed)
            extended.assert_called_once()

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
