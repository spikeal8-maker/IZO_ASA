from __future__ import annotations

import argparse
import json
import re
from datetime import date
from pathlib import Path
from typing import Any

SEVERITIES = ("critical", "high", "moderate", "low")
BLOCKING_SEVERITIES = ("critical", "high")
STATUS_AVAILABLE = "AVAILABLE"
STATUS_UNAVAILABLE = "EXTERNAL_VERIFICATION_UNAVAILABLE"
POLICY_PASS = "PASS"
POLICY_FAIL = "FAIL"
CLASS_PRODUCTION = "production"
CLASS_DEV_ONLY = "dev-only"
_GHSA_RE = re.compile(r"(GHSA-[0-9A-Za-z-]+)")


class AuditParseError(ValueError):
    pass


def _read_text(path: Path) -> str:
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def _normalize_via_entry(value: Any) -> Any:
    if isinstance(value, str):
        return value
    if not isinstance(value, dict):
        raise AuditParseError("vulnerability via entry must be a string or object")
    keys = ("source", "name", "dependency", "title", "url", "severity", "range")
    return {key: value[key] for key in keys if key in value}


def _normalize_fix_available(value: Any) -> bool | dict[str, Any]:
    if isinstance(value, bool):
        return value
    if isinstance(value, dict):
        keys = ("name", "version", "isSemVerMajor")
        normalized = {key: value[key] for key in keys if key in value}
        if not normalized:
            raise AuditParseError("fixAvailable object has no recognized fields")
        return normalized
    raise AuditParseError("fixAvailable must be boolean or object")


def _parse_json(raw: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise AuditParseError(f"malformed npm audit JSON: {exc.msg}") from exc
    if not isinstance(payload, dict):
        raise AuditParseError("npm audit payload must be an object")
    return payload


def _advisory_id(value: Any) -> str | None:
    if not isinstance(value, dict):
        return None
    url = value.get("url")
    if isinstance(url, str):
        match = _GHSA_RE.search(url)
        if match:
            return match.group(1)
    source = value.get("source")
    if isinstance(source, (int, str)) and str(source).strip():
        return f"npm:{str(source).strip()}"
    return None


def advisory_ids(finding: dict[str, Any], *, blocking_only: bool = False) -> list[str]:
    result: set[str] = set()
    for entry in finding.get("via", []):
        if not isinstance(entry, dict):
            continue
        if blocking_only and entry.get("severity") not in BLOCKING_SEVERITIES:
            continue
        advisory = _advisory_id(entry)
        if advisory:
            result.add(advisory)
    return sorted(result)


def normalize_npm_audit_report(raw: str) -> dict[str, Any]:
    payload = _parse_json(raw)
    metadata = payload.get("metadata")
    vulnerabilities = payload.get("vulnerabilities")
    if not isinstance(metadata, dict):
        raise AuditParseError("npm audit metadata is missing")
    counts_source = metadata.get("vulnerabilities")
    if not isinstance(counts_source, dict):
        raise AuditParseError("npm audit vulnerability counts are missing")
    if not isinstance(vulnerabilities, dict):
        raise AuditParseError("npm audit vulnerabilities map is missing")

    counts: dict[str, int] = {}
    for severity in SEVERITIES:
        value = counts_source.get(severity, 0)
        if not isinstance(value, int) or value < 0:
            raise AuditParseError(f"invalid vulnerability count for {severity}")
        counts[severity] = value

    findings: list[dict[str, Any]] = []
    for package_name in sorted(vulnerabilities):
        item = vulnerabilities[package_name]
        if not isinstance(item, dict):
            raise AuditParseError(f"vulnerability entry for {package_name} must be an object")
        severity = item.get("severity")
        if severity not in SEVERITIES:
            raise AuditParseError(f"invalid severity for {package_name}")
        range_value = item.get("range", "")
        if not isinstance(range_value, str):
            raise AuditParseError(f"invalid range for {package_name}")
        via = item.get("via", [])
        if not isinstance(via, list):
            raise AuditParseError(f"invalid via for {package_name}")
        normalized_via = [_normalize_via_entry(entry) for entry in via]
        finding = {
            "package": package_name,
            "severity": severity,
            "range": range_value,
            "via": normalized_via,
            "fixAvailable": _normalize_fix_available(item.get("fixAvailable", False)),
        }
        finding["advisoryIds"] = advisory_ids(finding)
        findings.append(finding)

    return {
        "status": STATUS_AVAILABLE,
        "counts": counts,
        "findings": findings,
    }


def classify_npm_audit(
    raw: str,
    *,
    scanner_exit_code: int,
    scanner_stderr: str = "",
) -> dict[str, Any]:
    if not raw.strip():
        return {
            "status": STATUS_UNAVAILABLE,
            "counts": None,
            "findings": [],
            "reason": (scanner_stderr.strip() or f"npm audit exited {scanner_exit_code} without JSON output")[:500],
        }

    try:
        payload = _parse_json(raw)
    except AuditParseError:
        if scanner_exit_code != 0:
            return {
                "status": STATUS_UNAVAILABLE,
                "counts": None,
                "findings": [],
                "reason": (scanner_stderr.strip() or "npm audit returned malformed JSON")[:500],
            }
        raise

    if "error" in payload:
        error = payload.get("error")
        if isinstance(error, dict):
            summary = error.get("summary") or error.get("code") or "npm audit reported an external error"
        else:
            summary = "npm audit reported an external error"
        return {
            "status": STATUS_UNAVAILABLE,
            "counts": None,
            "findings": [],
            "reason": str(summary)[:500],
        }

    return normalize_npm_audit_report(raw)


def classify_production_presence(
    full_report: dict[str, Any],
    production_report: dict[str, Any],
) -> list[dict[str, Any]]:
    if full_report.get("status") != STATUS_AVAILABLE or production_report.get("status") != STATUS_AVAILABLE:
        return []
    production_packages = {
        item["package"]
        for item in production_report.get("findings", [])
        if isinstance(item, dict) and isinstance(item.get("package"), str)
    }
    classified: list[dict[str, Any]] = []
    for finding in full_report.get("findings", []):
        item = dict(finding)
        present = item["package"] in production_packages
        item["presentInProductionAudit"] = "YES" if present else "NO"
        item["runtimeOrDev"] = CLASS_PRODUCTION if present else CLASS_DEV_ONLY
        classified.append(item)
    return classified


def _exception_error(exception: Any, index: int, as_of: date) -> list[str]:
    if not isinstance(exception, dict):
        return [f"INVALID_EXCEPTION[{index}]:object"]
    errors: list[str] = []
    required_strings = (
        "package",
        "severity",
        "affectedRange",
        "classification",
        "issue",
        "owner",
        "reason",
        "remediation",
        "reviewBy",
    )
    for field in required_strings:
        value = exception.get(field)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"INVALID_EXCEPTION[{index}]:missing-{field}")
    advisories = exception.get("advisories")
    if not isinstance(advisories, list) or not advisories or not all(
        isinstance(item, str) and item.strip() for item in advisories
    ):
        errors.append(f"INVALID_EXCEPTION[{index}]:missing-advisories")
    if exception.get("severity") not in BLOCKING_SEVERITIES:
        errors.append(f"INVALID_EXCEPTION[{index}]:severity")
    if exception.get("classification") not in (CLASS_PRODUCTION, CLASS_DEV_ONLY):
        errors.append(f"INVALID_EXCEPTION[{index}]:classification")
    review_by = exception.get("reviewBy")
    if isinstance(review_by, str) and review_by.strip():
        try:
            expiry = date.fromisoformat(review_by)
        except ValueError:
            errors.append(f"INVALID_EXCEPTION[{index}]:reviewBy")
        else:
            if expiry < as_of:
                errors.append(f"EXPIRED_EXCEPTION[{index}]:{review_by}")
    return errors


def _matches_exception(finding: dict[str, Any], exception: dict[str, Any]) -> bool:
    blocking_ids = advisory_ids(finding, blocking_only=True)
    return (
        exception.get("package") == finding.get("package")
        and exception.get("severity") == finding.get("severity")
        and exception.get("affectedRange") == finding.get("range")
        and exception.get("classification") == finding.get("runtimeOrDev")
        and sorted(exception.get("advisories", [])) == blocking_ids
    )


def evaluate_npm_policy(
    full_report: dict[str, Any],
    production_report: dict[str, Any],
    policy: dict[str, Any],
    *,
    as_of: date | None = None,
) -> dict[str, Any]:
    check_date = as_of or date.today()
    violations: list[str] = []
    if full_report.get("status") != STATUS_AVAILABLE:
        violations.append("FULL_AUDIT_UNAVAILABLE")
    if production_report.get("status") != STATUS_AVAILABLE:
        violations.append("PRODUCTION_AUDIT_UNAVAILABLE")

    exceptions = policy.get("baselineExceptions")
    if not isinstance(exceptions, list):
        exceptions = []
        violations.append("INVALID_POLICY:baselineExceptions")
    for index, exception in enumerate(exceptions):
        violations.extend(_exception_error(exception, index, check_date))

    classified = classify_production_presence(full_report, production_report)
    if not violations:
        for finding in classified:
            if finding.get("severity") not in BLOCKING_SEVERITIES:
                continue
            matches = [
                exception
                for exception in exceptions
                if isinstance(exception, dict) and _matches_exception(finding, exception)
            ]
            if len(matches) != 1:
                ids = ",".join(advisory_ids(finding, blocking_only=True)) or "UNIDENTIFIED"
                violations.append(
                    "UNTRACKED_HIGH_CRITICAL:"
                    f"{finding.get('package')}:{finding.get('severity')}:{finding.get('range')}:{ids}"
                )

    return {
        "status": POLICY_PASS if not violations else POLICY_FAIL,
        "violations": violations,
        "classifiedFindings": classified,
    }


def _compact(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Normalize and enforce the reviewed npm audit baseline.")
    parser.add_argument("--full-input", required=True, type=Path)
    parser.add_argument("--production-input", required=True, type=Path)
    parser.add_argument("--full-exit-code", required=True, type=int)
    parser.add_argument("--production-exit-code", required=True, type=int)
    parser.add_argument("--full-stderr", type=Path)
    parser.add_argument("--production-stderr", type=Path)
    parser.add_argument("--policy", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)

    full_report = classify_npm_audit(
        _read_text(args.full_input),
        scanner_exit_code=args.full_exit_code,
        scanner_stderr=_read_text(args.full_stderr) if args.full_stderr else "",
    )
    production_report = classify_npm_audit(
        _read_text(args.production_input),
        scanner_exit_code=args.production_exit_code,
        scanner_stderr=_read_text(args.production_stderr) if args.production_stderr else "",
    )
    policy = _parse_json(_read_text(args.policy))
    policy_result = evaluate_npm_policy(full_report, production_report, policy)
    result = {
        "full": full_report,
        "production": production_report,
        "classifiedFindings": policy_result["classifiedFindings"],
        "policy": {
            "status": policy_result["status"],
            "violations": policy_result["violations"],
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"NPM_AUDIT_FULL_STATUS={full_report['status']}")
    print(f"NPM_AUDIT_PRODUCTION_STATUS={production_report['status']}")
    print(f"FULL_NPM_COUNTS={_compact(full_report.get('counts'))}")
    print(f"PRODUCTION_NPM_COUNTS={_compact(production_report.get('counts'))}")
    print(
        "HIGH_CLASSIFICATION="
        + _compact(
            [
                {
                    key: item[key]
                    for key in (
                        "package",
                        "severity",
                        "range",
                        "advisoryIds",
                        "fixAvailable",
                        "presentInProductionAudit",
                        "runtimeOrDev",
                    )
                }
                for item in policy_result["classifiedFindings"]
                if item.get("severity") in BLOCKING_SEVERITIES
            ]
        )
    )
    print(f"NPM_POLICY_RESULT={policy_result['status']}")
    if policy_result["violations"]:
        print(f"NPM_POLICY_VIOLATIONS={_compact(policy_result['violations'])}")
    return 0 if policy_result["status"] == POLICY_PASS else 2


if __name__ == "__main__":
    raise SystemExit(main())
