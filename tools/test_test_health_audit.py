from __future__ import annotations

import unittest

from tools.test_health_audit import normalize


HEAD = "a" * 40


def metadata(**overrides):
    result = {
        "repository": "spikeal8-maker/IZO_ASA",
        "eventName": "pull_request",
        "workflowRun": "123",
        "workflowAttempt": 1,
        "expectedHead": HEAD,
        "exactHead": HEAD,
        "pythonVersion": "Python 3.11.9",
        "pytestVersion": "pytest 9.0.3",
        "startedAt": "2026-09-25T00:00:00+00:00",
        "durationSeconds": 716.0,
        "exitCode": 0,
    }
    result.update(overrides)
    return result


POLICY = {
    "baselineSource": "exact-head-github-ci",
    "historicalCountsAcceptedAsFreshBaseline": False,
}


class TestHealthAuditTests(unittest.TestCase):
    def test_clean_pytest_output_parses_counts_and_duration(self) -> None:
        raw = "2137 passed, 3 skipped in 621.03s (0:10:21)\n"
        receipt = normalize(raw, metadata(), POLICY)
        self.assertEqual(receipt["policy"]["status"], "PASS")
        self.assertEqual(receipt["tests"]["passed"], 2137)
        self.assertEqual(receipt["tests"]["failed"], 0)
        self.assertEqual(receipt["tests"]["skipped"], 3)
        self.assertEqual(receipt["warnings"]["total"], 0)
        self.assertEqual(receipt["timing"]["pytestSeconds"], 621.03)

    def test_same_warning_category_with_random_temp_paths_normalizes_together(self) -> None:
        raw = """=============================== warnings summary ===============================
C:\\Users\\runner\\AppData\\Local\\Temp\\abc\\site-packages\\pkg\\mod.py:10
  C:\\Users\\runner\\AppData\\Local\\Temp\\abc\\site-packages\\pkg\\mod.py:10: DeprecationWarning: old
C:\\Users\\runner\\AppData\\Local\\Temp\\xyz\\site-packages\\pkg\\mod.py:10
  C:\\Users\\runner\\AppData\\Local\\Temp\\xyz\\site-packages\\pkg\\mod.py:10: DeprecationWarning: old
-- Docs: https://docs.pytest.org/
2 passed, 2 warnings in 1.20s
"""
        receipt = normalize(raw, metadata(), POLICY)
        categories = receipt["warnings"]["categories"]
        self.assertEqual(categories, [{"category": "DeprecationWarning", "source": "site-packages/pkg/mod.py", "count": 2}])
        self.assertEqual(receipt["warnings"]["total"], 2)

    def test_synthetic_new_warning_is_visible_as_separate_category(self) -> None:
        raw = """=============================== warnings summary ===============================
tools/test_a.py:4
  tools/test_a.py:4: DeprecationWarning: old

tools/test_b.py:8
  tools/test_b.py:8: RuntimeWarning: new
-- Docs: https://docs.pytest.org/
2 passed, 2 warnings in 1.00s
"""
        receipt = normalize(raw, metadata(), POLICY)
        names = {item["category"] for item in receipt["warnings"]["categories"]}
        self.assertEqual(names, {"DeprecationWarning", "RuntimeWarning"})

    def test_cleanup_permission_error_is_detected_and_path_normalized(self) -> None:
        raw = """1 passed in 0.10s
PytestWarning: (rm_rf) unknown function scandir when removing C:\\Temp\\pytest-of-user\\garbage-123\\test_apply\\apply-secrets:
<class 'PermissionError'>: [WinError 5] denied: 'C:\\Temp\\pytest-of-user\\garbage-123\\test_apply\\apply-secrets'
"""
        receipt = normalize(raw, metadata(), POLICY)
        self.assertEqual(receipt["cleanup"]["count"], 1)
        self.assertEqual(
            receipt["cleanup"]["categories"],
            [{"errorType": "PermissionError", "owner": "apply-secrets", "normalizedPath": "<PYTEST_TEMP>/apply-secrets", "count": 1}],
        )

    def test_wrapped_powershell_cleanup_warning_is_detected(self) -> None:
        raw = """1 passed in 0.10s
python.exe : C:\\Python\\Lib\\site-packages\\_pytest\\pathlib.py:103: PytestWa
rning: (rm_rf) unknown function scandir when removing \\\\?\\C:\\Temp\\pytest
-of-admins\\garbage-123\\test_apply\\apply-secrets:
<class 'PermissionError'>: [WinError 5] denied: '\\\\?\\C:\\Temp\\pytest-of-admins\\garbage-123\\test_apply\\apply-secrets'
"""
        receipt = normalize(raw, metadata(), POLICY)
        self.assertEqual(receipt["cleanup"]["count"], 1)
        self.assertEqual(
            receipt["cleanup"]["categories"],
            [{"errorType": "PermissionError", "owner": "apply-secrets", "normalizedPath": "<PYTEST_TEMP>/apply-secrets", "count": 1}],
        )

    def test_malformed_incomplete_evidence_fails_without_fabricated_green(self) -> None:
        receipt = normalize("partial output only\n", metadata(), POLICY)
        self.assertEqual(receipt["evidenceStatus"], "UNAVAILABLE")
        self.assertEqual(receipt["policy"]["status"], "FAIL")
        self.assertIsNone(receipt["tests"]["passed"])
        self.assertIn("PYTEST_SUMMARY_UNAVAILABLE", receipt["policy"]["violations"])

    def test_duration_section_is_parsed(self) -> None:
        raw = """============================= slowest 10 durations =============================
4.25s call     backend/test_slow.py::test_a
0.80s setup    tools/test_tool.py::test_b
2 passed in 5.50s
"""
        receipt = normalize(raw, metadata(durationSeconds=7.25), POLICY)
        self.assertEqual(receipt["timing"]["fullVerificationSeconds"], 7.25)
        self.assertEqual(receipt["timing"]["slowest"][0]["nodeid"], "backend/test_slow.py::test_a")
        self.assertEqual(receipt["timing"]["slowest"][0]["seconds"], 4.25)

    def test_unknown_retry_state_is_not_zero(self) -> None:
        receipt = normalize("3 passed in 0.50s\n", metadata(), POLICY)
        self.assertEqual(receipt["retryFlakyObservability"]["status"], "NOT_OBSERVABLE")
        self.assertIsNone(receipt["retryFlakyObservability"]["retries"])

    def test_failed_test_or_exact_head_mismatch_fails_policy(self) -> None:
        failed = normalize("1 failed, 2 passed in 1.00s\n", metadata(), POLICY)
        self.assertEqual(failed["policy"]["status"], "FAIL")
        self.assertIn("TEST_FAILURES_PRESENT", failed["policy"]["violations"])

        mismatch = normalize("2 passed in 1.00s\n", metadata(exactHead="b" * 40), POLICY)
        self.assertEqual(mismatch["policy"]["status"], "FAIL")
        self.assertIn("EXACT_HEAD_MISMATCH", mismatch["policy"]["violations"])


if __name__ == "__main__":
    unittest.main()
