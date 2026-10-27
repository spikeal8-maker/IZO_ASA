from __future__ import annotations

import copy
import json
from datetime import date
from pathlib import Path

import pytest

from tools.supply_chain_audit import (
    AuditParseError,
    CLASS_DEV_ONLY,
    CLASS_PRODUCTION,
    POLICY_FAIL,
    POLICY_PASS,
    STATUS_AVAILABLE,
    STATUS_UNAVAILABLE,
    classify_npm_audit,
    evaluate_npm_policy,
    normalize_npm_audit_report,
)


ROOT = Path(__file__).resolve().parents[1]
POLICY = json.loads((ROOT / "tools" / "fixtures" / "npm-reviewed-policy-20260923.json").read_text(encoding="utf-8"))
REVIEW_DATE = date(2026, 9, 23)


def _via(advisory: str, severity: str, source: int) -> dict:
    return {
        "source": source,
        "name": advisory.lower(),
        "dependency": advisory.lower(),
        "title": f"{advisory} test advisory",
        "url": f"https://github.com/advisories/{advisory}",
        "severity": severity,
        "range": "<99",
    }


def _report(*, counts: dict[str, int] | None = None, vulnerabilities: dict | None = None) -> str:
    counts = counts or {"critical": 0, "high": 0, "moderate": 0, "low": 0, "total": 0}
    return json.dumps(
        {
            "auditReportVersion": 2,
            "vulnerabilities": vulnerabilities or {},
            "metadata": {"vulnerabilities": counts},
        }
    )


def _historical_full_report() -> dict:
    raw = _report(
        counts={"critical": 0, "high": 3, "moderate": 1, "low": 0, "total": 4},
        vulnerabilities={
            "baseline-browser-mapping": {
                "severity": "moderate",
                "range": ">=2.0.0 <2.11.0",
                "via": [_via("GHSA-w5vr-8v7q-w6rv", "moderate", 1193686)],
                "fixAvailable": True,
            },
            "browserslist": {
                "severity": "high",
                "range": "<=4.28.6",
                "via": [
                    _via("GHSA-c83g-rgw3-j3cx", "high", 1153171),
                    _via("GHSA-73wf-gq98-2v4g", "high", 1153172),
                ],
                "fixAvailable": True,
            },
            "nanoid": {
                "severity": "high",
                "range": "<=3.3.17",
                "via": [
                    _via("GHSA-28wg-ghj8-5hjv", "high", 1138811),
                    _via("GHSA-2v37-7h3g-55p8", "high", 1139427),
                ],
                "fixAvailable": True,
            },
            "postcss": {
                "severity": "high",
                "range": "<=8.5.22",
                "via": [
                    _via("GHSA-fxqj-rqcc-2cmp", "moderate", 1130709),
                    _via("GHSA-r28c-9q8g-f849", "high", 1139510),
                ],
                "fixAvailable": True,
            },
        },
    )
    return classify_npm_audit(raw, scanner_exit_code=1)


def _clean_report() -> dict:
    return classify_npm_audit(_report(), scanner_exit_code=0)


def _single_finding(
    package: str,
    *,
    severity: str,
    affected_range: str,
    advisory: str,
) -> dict:
    raw = _report(
        counts={
            "critical": 1 if severity == "critical" else 0,
            "high": 1 if severity == "high" else 0,
            "moderate": 0,
            "low": 0,
            "total": 1,
        },
        vulnerabilities={
            package: {
                "severity": severity,
                "range": affected_range,
                "via": [_via(advisory, severity, 999999)],
                "fixAvailable": True,
            }
        },
    )
    return classify_npm_audit(raw, scanner_exit_code=1)


def test_clean_result_is_available_with_zero_counts_and_no_findings() -> None:
    result = normalize_npm_audit_report(_report())
    assert result == {
        "status": STATUS_AVAILABLE,
        "counts": {"critical": 0, "high": 0, "moderate": 0, "low": 0},
        "findings": [],
    }


def test_normalization_includes_advisory_ids_and_fix_available() -> None:
    raw = _report(
        counts={"critical": 1, "high": 1, "moderate": 0, "low": 0, "total": 2},
        vulnerabilities={
            "z-high": {
                "severity": "high",
                "range": "<2.0.0",
                "via": ["shared-parent"],
                "fixAvailable": True,
            },
            "a-critical": {
                "severity": "critical",
                "range": ">=1 <1.4.2",
                "via": [_via("GHSA-aaaa-bbbb-cccc", "critical", 123)],
                "fixAvailable": False,
            },
        },
    )
    result = normalize_npm_audit_report(raw)
    assert [item["package"] for item in result["findings"]] == ["a-critical", "z-high"]
    assert result["findings"][0]["advisoryIds"] == ["GHSA-aaaa-bbbb-cccc"]
    assert result["findings"][1]["fixAvailable"] is True


def test_fix_available_supports_boolean_and_object_shapes() -> None:
    raw = _report(
        counts={"critical": 0, "high": 2, "moderate": 0, "low": 0, "total": 2},
        vulnerabilities={
            "boolean-fix": {
                "severity": "high",
                "range": "<2",
                "via": [],
                "fixAvailable": True,
            },
            "object-fix": {
                "severity": "high",
                "range": "<3",
                "via": [],
                "fixAvailable": {
                    "name": "object-fix",
                    "version": "3.0.0",
                    "isSemVerMajor": True,
                    "extra": "ignored",
                },
            },
        },
    )
    result = normalize_npm_audit_report(raw)
    findings = {item["package"]: item for item in result["findings"]}
    assert findings["boolean-fix"]["fixAvailable"] is True
    assert findings["object-fix"]["fixAvailable"] == {
        "name": "object-fix",
        "version": "3.0.0",
        "isSemVerMajor": True,
    }


def test_malformed_json_is_rejected_when_scanner_claims_success() -> None:
    with pytest.raises(AuditParseError, match="malformed npm audit JSON"):
        classify_npm_audit("{broken", scanner_exit_code=0)


def test_scanner_unavailable_is_explicit_and_policy_fails_closed() -> None:
    unavailable = classify_npm_audit(
        "",
        scanner_exit_code=1,
        scanner_stderr="network name resolution failed",
    )
    assert unavailable["status"] == STATUS_UNAVAILABLE
    result = evaluate_npm_policy(unavailable, _clean_report(), POLICY, as_of=REVIEW_DATE)
    assert result["status"] == POLICY_FAIL
    assert "FULL_AUDIT_UNAVAILABLE" in result["violations"]


def test_npm_error_payload_is_external_verification_unavailable() -> None:
    result = classify_npm_audit(
        json.dumps({"error": {"code": "ENETUNREACH", "summary": "registry unavailable"}}),
        scanner_exit_code=1,
    )
    assert result["status"] == STATUS_UNAVAILABLE
    assert result["counts"] is None
    assert result["findings"] == []
    assert result["reason"] == "registry unavailable"


def test_nonzero_exit_with_valid_vulnerability_report_is_data_not_failure() -> None:
    result = _single_finding(
        "known-high",
        severity="high",
        affected_range="<5",
        advisory="GHSA-1111-2222-3333",
    )
    assert result["status"] == STATUS_AVAILABLE
    assert result["counts"]["high"] == 1


def test_historical_reviewed_baseline_passes_and_moderate_needs_no_high_exception() -> None:
    result = evaluate_npm_policy(_historical_full_report(), _clean_report(), POLICY, as_of=REVIEW_DATE)
    assert result["status"] == POLICY_PASS
    assert len(POLICY["baselineExceptions"]) == 3
    moderate = next(item for item in result["classifiedFindings"] if item["package"] == "baseline-browser-mapping")
    assert moderate["severity"] == "moderate"
    assert moderate["runtimeOrDev"] == CLASS_DEV_ONLY


@pytest.mark.parametrize(
    ("severity", "package", "advisory"),
    [
        ("high", "synthetic-new-high", "GHSA-1111-2222-3333"),
        ("critical", "synthetic-new-critical", "GHSA-4444-5555-6666"),
    ],
)
def test_synthetic_new_high_or_critical_fails(severity: str, package: str, advisory: str) -> None:
    current = _historical_full_report()
    synthetic = _single_finding(package, severity=severity, affected_range="<1", advisory=advisory)
    current["findings"].extend(synthetic["findings"])
    current["counts"][severity] += 1
    result = evaluate_npm_policy(current, _clean_report(), POLICY, as_of=REVIEW_DATE)
    assert result["status"] == POLICY_FAIL
    assert any(item.startswith(f"UNTRACKED_HIGH_CRITICAL:{package}:") for item in result["violations"])


@pytest.mark.parametrize("field", ["issue", "owner", "reviewBy"])
def test_missing_required_exception_field_fails(field: str) -> None:
    policy = copy.deepcopy(POLICY)
    del policy["baselineExceptions"][0][field]
    result = evaluate_npm_policy(_historical_full_report(), _clean_report(), policy, as_of=REVIEW_DATE)
    assert result["status"] == POLICY_FAIL
    assert any(f"missing-{field}" in item for item in result["violations"])


def test_expired_exception_fails() -> None:
    policy = copy.deepcopy(POLICY)
    policy["baselineExceptions"][0]["reviewBy"] = "2026-09-22"
    result = evaluate_npm_policy(_historical_full_report(), _clean_report(), policy, as_of=REVIEW_DATE)
    assert result["status"] == POLICY_FAIL
    assert any(item.startswith("EXPIRED_EXCEPTION") for item in result["violations"])


def test_production_and_dev_classification_is_deterministic() -> None:
    full = _single_finding(
        "production-high",
        severity="high",
        affected_range="<2",
        advisory="GHSA-aaaa-1111-2222",
    )
    dev = _single_finding(
        "dev-high",
        severity="high",
        affected_range="<3",
        advisory="GHSA-bbbb-3333-4444",
    )
    full["findings"].extend(dev["findings"])
    full["counts"]["high"] = 2
    production = _single_finding(
        "production-high",
        severity="high",
        affected_range="<2",
        advisory="GHSA-aaaa-1111-2222",
    )
    policy = {
        "baselineExceptions": [
            {
                "package": "production-high",
                "severity": "high",
                "affectedRange": "<2",
                "advisories": ["GHSA-aaaa-1111-2222"],
                "classification": CLASS_PRODUCTION,
                "issue": "#1",
                "owner": "owner",
                "reason": "reviewed",
                "remediation": "upgrade",
                "reviewBy": "2026-10-23",
            },
            {
                "package": "dev-high",
                "severity": "high",
                "affectedRange": "<3",
                "advisories": ["GHSA-bbbb-3333-4444"],
                "classification": CLASS_DEV_ONLY,
                "issue": "#2",
                "owner": "owner",
                "reason": "reviewed",
                "remediation": "upgrade",
                "reviewBy": "2026-10-23",
            },
        ]
    }
    result = evaluate_npm_policy(full, production, policy, as_of=REVIEW_DATE)
    assert result["status"] == POLICY_PASS
    classifications = {item["package"]: item for item in result["classifiedFindings"]}
    assert classifications["production-high"]["presentInProductionAudit"] == "YES"
    assert classifications["production-high"]["runtimeOrDev"] == CLASS_PRODUCTION
    assert classifications["dev-high"]["presentInProductionAudit"] == "NO"
    assert classifications["dev-high"]["runtimeOrDev"] == CLASS_DEV_ONLY
