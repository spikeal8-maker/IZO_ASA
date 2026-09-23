from __future__ import annotations

import copy
import json
from datetime import date
from pathlib import Path

from tools.supply_chain_floor import (
    LICENSE_APPROVED,
    LICENSE_NEEDS_REVIEW,
    POLICY_FAIL,
    POLICY_PASS,
    STATUS_AVAILABLE,
    STATUS_UNAVAILABLE,
    classify_python_audit,
    classify_secret_scan,
    evaluate_license_policy,
    evaluate_python_policy,
    evaluate_secret_policy,
    normalize_backend_licenses,
    normalize_frontend_licenses,
)

ROOT = Path(__file__).resolve().parents[1]
POLICY = json.loads((ROOT / "architecture" / "security-policy.json").read_text(encoding="utf-8"))
TODAY = date(2026, 9, 23)


def _python_report(*, severity: str | None = None) -> dict:
    return {
        "status": STATUS_AVAILABLE,
        "findings": [{
            "package": "demo",
            "installedVersion": "1.0.0",
            "advisoryIds": ["CVE-2026-0001", "GHSA-aaaa-bbbb-cccc"],
            "severity": severity,
            "fixVersions": ["1.0.1"],
            "dependencyRelation": None,
        }],
    }


def _license_report(ecosystem: str, license_value: str, classification: str = "production") -> dict:
    return {
        "status": STATUS_AVAILABLE,
        "findings": [{
            "package": "demo",
            "resolvedVersion": "1.0.0",
            "license": license_value,
            "classification": classification,
            "ecosystem": ecosystem,
        }],
    }


def test_clean_python_report_passes() -> None:
    raw = json.dumps([{"name": "fastapi", "version": "0.136.3", "vulns": []}])
    report = classify_python_audit(raw, scanner_exit_code=0)
    assert report["status"] == STATUS_AVAILABLE
    assert report["findings"] == []
    assert evaluate_python_policy(report, POLICY, as_of=TODAY)["status"] == POLICY_PASS


def test_synthetic_new_python_high_and_critical_fail() -> None:
    for severity in ("high", "critical"):
        result = evaluate_python_policy(_python_report(severity=severity), POLICY, as_of=TODAY)
        assert result["status"] == POLICY_FAIL
        assert any(item.startswith("UNTRACKED_PYTHON_HIGH_CRITICAL:") for item in result["violations"])


def test_python_unknown_severity_is_not_guessed_and_requires_review() -> None:
    result = evaluate_python_policy(_python_report(severity=None), POLICY, as_of=TODAY)
    assert result["status"] == POLICY_FAIL
    assert any(item.startswith("PYTHON_SEVERITY_UNKNOWN_REVIEW_REQUIRED:") for item in result["violations"])


def test_python_scanner_unavailable_fails_closed() -> None:
    report = classify_python_audit("", scanner_exit_code=127, scanner_stderr="registry unavailable")
    assert report["status"] == STATUS_UNAVAILABLE
    result = evaluate_python_policy(report, POLICY, as_of=TODAY)
    assert result["status"] == POLICY_FAIL
    assert "PYTHON_AUDIT_UNAVAILABLE" in result["violations"]


def test_approved_license_passes() -> None:
    result = evaluate_license_policy(_license_report("frontend", "MIT"), {"status": STATUS_AVAILABLE, "findings": []}, POLICY, as_of=TODAY)
    assert result["status"] == POLICY_PASS
    assert result["findings"][0]["policyClass"] == LICENSE_APPROVED


def test_unknown_new_production_license_requires_explicit_review() -> None:
    result = evaluate_license_policy(_license_report("frontend", "LicenseRef-Custom"), {"status": STATUS_AVAILABLE, "findings": []}, POLICY, as_of=TODAY)
    assert result["status"] == POLICY_FAIL
    assert result["findings"][0]["policyClass"] == LICENSE_NEEDS_REVIEW
    assert any(item.startswith("LICENSE_REVIEW_REQUIRED:") for item in result["violations"])


def test_expired_license_review_fails() -> None:
    policy = copy.deepcopy(POLICY)
    policy["licenses"]["reviews"] = [{
        "ecosystem": "frontend",
        "package": "demo",
        "resolvedVersion": "1.0.0",
        "license": "LicenseRef-Custom",
        "classification": "production",
        "issue": "#999",
        "owner": "spikeal8-maker",
        "reason": "reviewed baseline",
        "reviewBy": "2026-09-22",
    }]
    result = evaluate_license_policy(_license_report("frontend", "LicenseRef-Custom"), {"status": STATUS_AVAILABLE, "findings": []}, policy, as_of=TODAY)
    assert result["status"] == POLICY_FAIL
    assert any(item.startswith("EXPIRED_LICENSE_REVIEW") for item in result["violations"])


def test_frontend_classification_comes_from_package_json_sections() -> None:
    scanner = json.dumps({"react@19.2.7": {"licenses": "MIT"}, "vite@8.0.16": {"licenses": "MIT"}})
    package_json = json.dumps({"dependencies": {"react": "^19.2.7"}, "devDependencies": {"vite": "^8.0.16"}})
    report = normalize_frontend_licenses(scanner, package_json, scanner_exit_code=0)
    classes = {item["package"]: item["classification"] for item in report["findings"]}
    assert classes == {"react": "production", "vite": "dev/test"}


def test_backend_direct_dependencies_are_unknown_when_requirements_has_no_context_marker() -> None:
    scanner = json.dumps([{"Name": "fastapi", "Version": "0.136.3", "License": "MIT"}])
    report = normalize_backend_licenses(scanner, "fastapi==0.136.3\n", scanner_exit_code=0)
    assert report["findings"][0]["classification"] == "unknown"


def test_secret_finding_fails_and_normalized_output_contains_no_secret_fields() -> None:
    raw = json.dumps([{
        "RuleID": "github-pat",
        "Description": "GitHub Personal Access Token",
        "File": "demo.txt",
        "StartLine": 1,
        "EndLine": 1,
        "Commit": "abc",
        "Fingerprint": "fingerprint",
        "Secret": "ghp_FAKE_SHOULD_NEVER_SURVIVE",
        "Match": "ghp_FAKE_SHOULD_NEVER_SURVIVE",
        "Line": "token=ghp_FAKE_SHOULD_NEVER_SURVIVE",
    }])
    report = classify_secret_scan(raw, scanner_exit_code=23)
    assert report["status"] == STATUS_AVAILABLE
    assert "FAKE_SHOULD_NEVER_SURVIVE" not in json.dumps(report)
    result = evaluate_secret_policy(report, synthetic_test="PASS")
    assert result["status"] == POLICY_FAIL
    assert result["violations"] == ["CHANGED_SCOPE_SECRET_FINDINGS:1"]


def test_clean_secret_scan_and_synthetic_redaction_test_pass() -> None:
    report = classify_secret_scan("[]", scanner_exit_code=0)
    assert evaluate_secret_policy(report, synthetic_test="PASS")["status"] == POLICY_PASS


def test_secret_scanner_unavailable_fails() -> None:
    report = classify_secret_scan("[]", scanner_exit_code=127, scanner_stderr="tool unavailable")
    assert report["status"] == STATUS_UNAVAILABLE
    result = evaluate_secret_policy(report, synthetic_test="PASS")
    assert result["status"] == POLICY_FAIL
    assert "SECRET_SCAN_UNAVAILABLE" in result["violations"]


def test_failed_synthetic_redaction_test_fails_even_when_real_scope_is_clean() -> None:
    report = classify_secret_scan("[]", scanner_exit_code=0)
    result = evaluate_secret_policy(report, synthetic_test="FAIL")
    assert result["status"] == POLICY_FAIL
    assert "SYNTHETIC_SECRET_REDACTION_TEST_FAILED" in result["violations"]
