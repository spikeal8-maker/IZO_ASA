"""Safety and truthful-evidence regression tests for the disposable runner driver."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from tools import docker_clean_install as clean


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


if __name__ == "__main__":
    unittest.main()
