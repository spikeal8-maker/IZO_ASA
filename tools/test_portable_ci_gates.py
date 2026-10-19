"""Negative scope cases use the real canonical engine and disposable Git state."""
from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.portable_ci_gates import GateError, execute, normalized_secret, run_scope, verify_checkout
from tools.supply_chain_floor import evaluate_secret_policy


class PortableGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="izo-portable-tests-")
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)
        self.git("init", "-q")
        self.git("config", "user.name", "Isolated gate fixture")
        self.git("config", "user.email", "fixture@example.invalid")
        self.git("remote", "add", "origin", "https://github.com/spikeal8-maker/IZO_ASA.git")
        self.put("README.md", "# Test fixture\n")
        self.base = self.commit()

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.repo), *args], check=True,
                              capture_output=True, text=True).stdout.strip()

    def put(self, path, content):
        dest = self.repo / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")

    def commit(self):
        self.git("add", "-A")
        self.git("commit", "-qm", "isolated fixture")
        return self.git("rev-parse", "HEAD")

    def manifest(self, *, forbidden=False):
        data = {
            "manifestVersion": 1, "id": "PORTABLE-TEST-001", "baseSha": self.base,
            "goal": "Verify canonical scope", "userOutcome": "Unscoped files fail",
            "beforeScenario": "A forbidden document is modified", "afterScenario": "The real gate rejects it",
            "domain": "documentation", "riskClass": "low", "changeClass": "documentation",
            "nonGoals": ["Production changes"], "declaredFiles": ["docs/allowed.md"],
            "allowedPatterns": [], "forbiddenPatterns": ["docs/outside.md"] if forbidden else [],
            "protectedFilesTouched": [], "maxProductionFiles": 0, "maxChangedLines": 100,
            "acceptance": ["Correct scope result"], "requiredEvidence": ["Real canonical receipt"],
            "targetedTests": ["Scope fixture"], "fileGrowthExpectations": ["Short fixture"],
            "forbiddenOperations": ["deploy"], "rollbackBoundary": "Remove only this fixture",
        }
        self.put("tasks/PORTABLE-TEST-001.toml", "\n".join(k + " = " + json.dumps(v) for k, v in data.items()) + "\n")

    def test_missing_manifest_cannot_pass(self):
        self.put("docs/outside.md", "# Undeclared\n")
        self.commit()
        result = run_scope(self.repo, self.base)
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["receipt"]["code"], "PACKAGE_MANIFEST_UNRESOLVED")

    def test_forbidden_and_undeclared_documents_fail(self):
        for forbidden, expected in ((False, "UNDECLARED_PATH"), (True, "FORBIDDEN_PATH")):
            with self.subTest(forbidden=forbidden):
                self.manifest(forbidden=forbidden)
                self.put("docs/outside.md", "# Outside scope\n")
                self.commit()
                result = run_scope(self.repo, self.base)
                self.assertEqual(result["status"], "FAIL")
                self.assertIn(expected, {finding["code"] for finding in result["receipt"]["findings"]})

    def test_valid_exact_scope_passes_canonical_engine(self):
        self.manifest()
        self.put("docs/allowed.md", "# Allowed\n")
        head = self.commit()
        verify_checkout(self.repo, self.base, head)
        result = run_scope(self.repo, self.base)
        self.assertEqual(result["status"], "PASS", result)
        self.assertEqual(result["receipt"]["headSha"], head)

    def test_malformed_or_unbound_success_receipts_cannot_pass(self):
        valid = {"mode": "ci", "packageId": "PORTABLE-TEST-001", "baseSha": self.base,
                 "headSha": self.base, "findings": []}
        cases = [("ENFORCE_OK", {}), ("ENFORCE_FAIL", {}), ("ENFORCE_FAIL", valid)]
        cases.extend(("ENFORCE_OK", {**valid, key: value}) for key, value in (
            ("mode", "local"), ("packageId", ""), ("baseSha", "b" * 40),
            ("headSha", "c" * 40), ("findings", None), ("findings", {}), ("findings", ""),
            ("findings", [{"code": "UNDECLARED_PATH"}]),
        ))
        cases.append(("ENFORCE_OK", {key: value for key, value in valid.items() if key != "findings"}))
        for prefix, receipt in cases:
            with self.subTest(prefix=prefix, receipt=receipt), patch(
                    "tools.portable_ci_gates.command", return_value=subprocess.CompletedProcess(
                        [], 0, prefix + " " + json.dumps(receipt), "")):
                with self.assertRaisesRegex(GateError, "CANONICAL_SCOPE_RECEIPT_INVALID"):
                    run_scope(self.repo, self.base, self.base)

    def test_wrong_head_and_dirty_checkout_fail_before_scanner(self):
        self.manifest()
        head = self.commit()
        with patch("tools.portable_ci_gates.run_secrets") as scanner:
            self.assertEqual(execute(self.repo, self.base, self.base)["error"], "CHECKOUT_SHA_MISMATCH")
            self.put("docs/uncommitted.md", "# Dirty\n")
            self.assertEqual(execute(self.repo, self.base, head)["error"], "CHECKOUT_NOT_CLEAN")
            scanner.assert_not_called()

    def test_real_normalizer_removes_secret_fields_and_findings_fail(self):
        raw = json.dumps([{"RuleID": "fixture", "File": "docs/a.md", "StartLine": 1,
                           "Secret": "sensitive fixture", "Match": "private fixture"}])
        report = normalized_secret(raw, 23)
        self.assertNotIn("sensitive fixture", json.dumps(report))
        self.assertNotIn("private fixture", json.dumps(report))
        self.assertEqual(evaluate_secret_policy(report, synthetic_test="PASS")["status"], "FAIL")

    def test_missing_malformed_and_failed_scans_do_not_become_clean(self):
        for raw, code in (("", 0), ("invalid JSON", 0), ("[]", 2)):
            with self.subTest(raw=raw, code=code):
                report = normalized_secret(raw, code)
                self.assertEqual(evaluate_secret_policy(report, synthetic_test="PASS")["status"], "FAIL")
        with self.assertRaises(GateError):
            normalized_secret("[]", 23)

    def test_download_failure_preserves_failed_result(self):
        self.manifest()
        head = self.commit()
        with patch("tools.portable_ci_gates.install_scanner", side_effect=GateError("SCANNER_DOWNLOAD_UNAVAILABLE")):
            result = execute(self.repo, self.base, head)
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["scope"]["status"], "PASS")
        self.assertEqual(result["error"], "SCANNER_DOWNLOAD_UNAVAILABLE")


if __name__ == "__main__":
    unittest.main()
