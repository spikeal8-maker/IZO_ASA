from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from tools.test_health_audit import (
    _evaluate_non_regression,
    _validate_debt_reviews,
    normalize,
)


ROOT = Path(__file__).resolve().parents[1]
HEAD = "a" * 40
NON_REGRESSION_POLICY = json.loads(
    (ROOT / "architecture" / "test-health-policy.json").read_text(encoding="utf-8")
)


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




class TestHealthNonRegressionPolicy(unittest.TestCase):
    def warning_baseline(self) -> dict:
        baseline = NON_REGRESSION_POLICY["acceptedBaseline"]["warnings"]
        return {
            "total": baseline["total"],
            "categories": [
                {
                    "category": item["category"],
                    "source": item["source"],
                    "count": item["count"],
                }
                for item in baseline["categories"]
            ],
        }

    def cleanup_baseline(self) -> dict:
        baseline = NON_REGRESSION_POLICY["acceptedBaseline"]["cleanup"]
        return {
            "count": baseline["total"],
            "categories": [
                {
                    "errorType": item["errorType"],
                    "owner": item["owner"],
                    "normalizedPath": item["normalizedPath"],
                    "count": item["count"],
                }
                for item in baseline["categories"]
            ],
        }

    def test_accepted_97_warning_and_1_cleanup_baseline_passes(self) -> None:
        policy = copy.deepcopy(NON_REGRESSION_POLICY)
        violations = _validate_debt_reviews(policy, metadata())
        violations += _evaluate_non_regression(
            self.warning_baseline(), self.cleanup_baseline(), policy
        )
        self.assertEqual(violations, [])

    def test_warning_count_decrease_passes(self) -> None:
        warnings = self.warning_baseline()
        warnings["total"] -= 1
        warnings["categories"][0]["count"] -= 1
        self.assertEqual(
            _evaluate_non_regression(warnings, self.cleanup_baseline(), NON_REGRESSION_POLICY),
            [],
        )

    def test_new_warning_category_fails(self) -> None:
        warnings = self.warning_baseline()
        warnings["total"] += 1
        warnings["categories"].append(
            {"category": "RuntimeWarning", "source": "tools/new_source.py", "count": 1}
        )
        violations = _evaluate_non_regression(
            warnings, self.cleanup_baseline(), NON_REGRESSION_POLICY
        )
        self.assertIn("NEW_WARNING_CATEGORY_SOURCE", violations)

    def test_existing_warning_source_count_increase_fails(self) -> None:
        warnings = self.warning_baseline()
        warnings["total"] += 1
        warnings["categories"][0]["count"] += 1
        violations = _evaluate_non_regression(
            warnings, self.cleanup_baseline(), NON_REGRESSION_POLICY
        )
        self.assertIn("WARNING_CATEGORY_SOURCE_COUNT_INCREASE", violations)

    def test_warning_total_above_97_fails(self) -> None:
        warnings = self.warning_baseline()
        warnings["total"] = 98
        violations = _evaluate_non_regression(
            warnings, self.cleanup_baseline(), NON_REGRESSION_POLICY
        )
        self.assertIn("WARNING_TOTAL_ABOVE_BASELINE", violations)

    def test_cleanup_one_and_zero_pass(self) -> None:
        self.assertEqual(
            _evaluate_non_regression(
                self.warning_baseline(), self.cleanup_baseline(), NON_REGRESSION_POLICY
            ),
            [],
        )
        self.assertEqual(
            _evaluate_non_regression(
                self.warning_baseline(), {"count": 0, "categories": []}, NON_REGRESSION_POLICY
            ),
            [],
        )

    def test_cleanup_count_two_fails(self) -> None:
        cleanup = self.cleanup_baseline()
        cleanup["count"] = 2
        cleanup["categories"][0]["count"] = 2
        violations = _evaluate_non_regression(
            self.warning_baseline(), cleanup, NON_REGRESSION_POLICY
        )
        self.assertIn("CLEANUP_TOTAL_ABOVE_BASELINE", violations)
        self.assertIn("CLEANUP_CATEGORY_COUNT_INCREASE", violations)

    def test_new_cleanup_owner_or_type_fails(self) -> None:
        cleanup = {
            "count": 1,
            "categories": [
                {
                    "errorType": "PermissionError",
                    "owner": "other-owner",
                    "normalizedPath": "<PYTEST_TEMP>/other",
                    "count": 1,
                }
            ],
        }
        violations = _evaluate_non_regression(
            self.warning_baseline(), cleanup, NON_REGRESSION_POLICY
        )
        self.assertIn("NEW_CLEANUP_CATEGORY_OWNER", violations)

    def test_missing_debt_issue_fails(self) -> None:
        policy = copy.deepcopy(NON_REGRESSION_POLICY)
        del policy["acceptedBaseline"]["warnings"]["categories"][0]["issue"]
        violations = _validate_debt_reviews(policy, metadata())
        self.assertIn("DEBT_ISSUE_MISSING", violations)

    def test_expired_review_by_fails(self) -> None:
        policy = copy.deepcopy(NON_REGRESSION_POLICY)
        policy["debtReviews"]["#162"]["reviewBy"] = "2026-09-24"
        violations = _validate_debt_reviews(policy, metadata())
        self.assertIn("DEBT_REVIEW_EXPIRED_162", violations)

    def test_retry_not_observable_remains_null(self) -> None:
        receipt = normalize("3 passed in 0.50s\n", metadata(), POLICY)
        self.assertEqual(receipt["retryFlakyObservability"], {"status": "NOT_OBSERVABLE", "retries": None})


if __name__ == "__main__":
    unittest.main()
