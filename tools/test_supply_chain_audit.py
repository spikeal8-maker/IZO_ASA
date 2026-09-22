from __future__ import annotations

import json

import pytest

from tools.supply_chain_audit import (
    AuditParseError,
    STATUS_AVAILABLE,
    STATUS_UNAVAILABLE,
    classify_npm_audit,
    normalize_npm_audit_report,
)


def _report(*, counts: dict[str, int] | None = None, vulnerabilities: dict | None = None) -> str:
    counts = counts or {"critical": 0, "high": 0, "moderate": 0, "low": 0, "total": 0}
    return json.dumps(
        {
            "auditReportVersion": 2,
            "vulnerabilities": vulnerabilities or {},
            "metadata": {"vulnerabilities": counts},
        }
    )


def test_clean_result_is_available_with_zero_counts_and_no_findings() -> None:
    result = normalize_npm_audit_report(_report())

    assert result == {
        "status": STATUS_AVAILABLE,
        "counts": {"critical": 0, "high": 0, "moderate": 0, "low": 0},
        "findings": [],
    }


def test_high_and_critical_findings_are_normalized_deterministically() -> None:
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
                "via": [
                    {
                        "source": 123,
                        "name": "a-critical",
                        "dependency": "a-critical",
                        "title": "critical advisory",
                        "url": "https://example.invalid/advisory/123",
                        "severity": "critical",
                        "range": "<1.4.2",
                        "ignored": "not normalized",
                    }
                ],
                "fixAvailable": False,
            },
        },
    )

    result = normalize_npm_audit_report(raw)

    assert [item["package"] for item in result["findings"]] == ["a-critical", "z-high"]
    assert result["findings"][0]["severity"] == "critical"
    assert result["findings"][0]["via"][0]["source"] == 123
    assert "ignored" not in result["findings"][0]["via"][0]
    assert result["findings"][1]["severity"] == "high"


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


def test_scanner_unavailable_is_explicit_and_does_not_fabricate_counts() -> None:
    result = classify_npm_audit(
        "",
        scanner_exit_code=1,
        scanner_stderr="network name resolution failed",
    )

    assert result["status"] == STATUS_UNAVAILABLE
    assert result["counts"] is None
    assert result["findings"] == []
    assert "network name resolution failed" in result["reason"]


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
    raw = _report(
        counts={"critical": 0, "high": 1, "moderate": 0, "low": 0, "total": 1},
        vulnerabilities={
            "known-high": {
                "severity": "high",
                "range": "<5",
                "via": [],
                "fixAvailable": False,
            }
        },
    )

    result = classify_npm_audit(raw, scanner_exit_code=1)

    assert result["status"] == STATUS_AVAILABLE
    assert result["counts"]["high"] == 1
    assert result["findings"][0]["package"] == "known-high"
