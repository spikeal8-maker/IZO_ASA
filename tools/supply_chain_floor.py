from __future__ import annotations

import argparse
import json
import re
from datetime import date
from pathlib import Path
from typing import Any

STATUS_AVAILABLE = "AVAILABLE"
STATUS_UNAVAILABLE = "EXTERNAL_VERIFICATION_UNAVAILABLE"
POLICY_PASS = "PASS"
POLICY_FAIL = "FAIL"
LICENSE_APPROVED = "approved"
LICENSE_NEEDS_REVIEW = "needs-review"
LICENSE_FORBIDDEN = "forbidden"
PYTHON_BLOCKING_SEVERITIES = {"high", "critical"}
SECRET_FINDING_EXIT_CODE = 23


class FloorParseError(ValueError):
    pass


def _read_text(path: Path | None) -> str:
    if path is None or not path.is_file():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def _json_object(raw: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise FloorParseError(f"malformed JSON: {exc.msg}") from exc
    if not isinstance(value, dict):
        raise FloorParseError("expected JSON object")
    return value


def _json_array(raw: str) -> list[Any]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise FloorParseError(f"malformed JSON: {exc.msg}") from exc
    if not isinstance(value, list):
        raise FloorParseError("expected JSON array")
    return value


def _unavailable(reason: str) -> dict[str, Any]:
    return {"status": STATUS_UNAVAILABLE, "reason": reason[:500], "findings": []}


def _canonical_python_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value.strip().lower())


def _normalize_severity(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    return normalized if normalized in {"low", "moderate", "medium", "high", "critical"} else None


def classify_python_audit(raw: str, *, scanner_exit_code: int, scanner_stderr: str = "") -> dict[str, Any]:
    if not raw.strip():
        return _unavailable(scanner_stderr.strip() or f"pip-audit exited {scanner_exit_code} without JSON output")
    if scanner_exit_code not in (0, 1):
        return _unavailable(scanner_stderr.strip() or f"pip-audit exited {scanner_exit_code}")
    try:
        dependencies = _json_array(raw)
    except FloorParseError as exc:
        return _unavailable(scanner_stderr.strip() or str(exc))

    findings: list[dict[str, Any]] = []
    resolved: list[dict[str, str]] = []
    for item in dependencies:
        if not isinstance(item, dict):
            raise FloorParseError("pip-audit dependency entry must be an object")
        name = item.get("name")
        version = item.get("version")
        vulns = item.get("vulns")
        if not isinstance(name, str) or not isinstance(version, str) or not isinstance(vulns, list):
            raise FloorParseError("pip-audit dependency entry is missing name/version/vulns")
        resolved.append({"package": name, "installedVersion": version})
        for vuln in vulns:
            if not isinstance(vuln, dict) or not isinstance(vuln.get("id"), str):
                raise FloorParseError(f"invalid pip-audit vulnerability for {name}")
            aliases = vuln.get("aliases", [])
            fixes = vuln.get("fix_versions", [])
            if not isinstance(aliases, list) or not all(isinstance(value, str) for value in aliases):
                raise FloorParseError(f"invalid aliases for {name}")
            if not isinstance(fixes, list) or not all(isinstance(value, str) for value in fixes):
                raise FloorParseError(f"invalid fix_versions for {name}")
            findings.append(
                {
                    "package": name,
                    "installedVersion": version,
                    "advisoryIds": sorted(set([vuln["id"], *aliases])),
                    "severity": _normalize_severity(vuln.get("severity")),
                    "fixVersions": sorted(set(fixes)),
                    "dependencyRelation": None,
                }
            )

    return {
        "status": STATUS_AVAILABLE,
        "resolved": sorted(resolved, key=lambda item: (_canonical_python_name(item["package"]), item["installedVersion"])),
        "findings": sorted(findings, key=lambda item: (_canonical_python_name(item["package"]), item["installedVersion"], item["advisoryIds"])),
    }


def _parse_date(value: Any) -> date | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _validate_python_exception(value: Any, index: int, *, as_of: date) -> list[str]:
    if not isinstance(value, dict):
        return [f"INVALID_PYTHON_EXCEPTION[{index}]:object"]
    violations: list[str] = []
    for field in ("package", "installedVersion", "severity", "issue", "owner", "reason", "remediation", "reviewBy"):
        if not isinstance(value.get(field), str) or not value[field].strip():
            violations.append(f"INVALID_PYTHON_EXCEPTION[{index}]:missing-{field}")
    ids = value.get("advisoryIds")
    if not isinstance(ids, list) or not ids or not all(isinstance(item, str) and item.strip() for item in ids):
        violations.append(f"INVALID_PYTHON_EXCEPTION[{index}]:missing-advisoryIds")
    review = _parse_date(value.get("reviewBy"))
    if review is None:
        violations.append(f"INVALID_PYTHON_EXCEPTION[{index}]:reviewBy")
    elif review < as_of:
        violations.append(f"EXPIRED_PYTHON_EXCEPTION[{index}]:{value.get('reviewBy')}")
    return violations


def _python_exception_matches(finding: dict[str, Any], exception: dict[str, Any]) -> bool:
    severity = finding.get("severity") or "unknown"
    return (
        _canonical_python_name(str(exception.get("package", "")))
        == _canonical_python_name(str(finding.get("package", "")))
        and exception.get("installedVersion") == finding.get("installedVersion")
        and exception.get("severity") == severity
        and sorted(exception.get("advisoryIds", [])) == sorted(finding.get("advisoryIds", []))
    )


def evaluate_python_policy(report: dict[str, Any], policy: dict[str, Any], *, as_of: date) -> dict[str, Any]:
    violations: list[str] = []
    if report.get("status") != STATUS_AVAILABLE:
        violations.append("PYTHON_AUDIT_UNAVAILABLE")

    config = policy.get("pythonAudit", {})
    exceptions = config.get("baselineExceptions", [])
    if not isinstance(exceptions, list):
        exceptions = []
        violations.append("INVALID_POLICY:pythonAudit.baselineExceptions")
    for index, exception in enumerate(exceptions):
        violations.extend(_validate_python_exception(exception, index, as_of=as_of))

    if report.get("status") == STATUS_AVAILABLE:
        for finding in report.get("findings", []):
            severity = finding.get("severity")
            if severity not in PYTHON_BLOCKING_SEVERITIES and severity is not None:
                continue
            matches = [
                exception
                for exception in exceptions
                if isinstance(exception, dict) and _python_exception_matches(finding, exception)
            ]
            if len(matches) != 1:
                ids = ",".join(finding.get("advisoryIds", [])) or "UNIDENTIFIED"
                if severity is None:
                    violations.append(
                        f"PYTHON_SEVERITY_UNKNOWN_REVIEW_REQUIRED:{finding.get('package')}:{finding.get('installedVersion')}:{ids}"
                    )
                else:
                    violations.append(
                        f"UNTRACKED_PYTHON_HIGH_CRITICAL:{finding.get('package')}:{finding.get('installedVersion')}:{severity}:{ids}"
                    )

    return {"status": POLICY_PASS if not violations else POLICY_FAIL, "violations": violations}


def _npm_key_name_version(key: str, metadata: dict[str, Any]) -> tuple[str, str]:
    version = metadata.get("version") if isinstance(metadata.get("version"), str) else ""
    if key.startswith("@"):
        split_at = key.rfind("@")
        if split_at > 0:
            return key[:split_at], version or key[split_at + 1 :]
    if "@" in key:
        name, suffix = key.rsplit("@", 1)
        return name, version or suffix
    return key, version


def normalize_frontend_licenses(raw: str, package_json_raw: str, *, scanner_exit_code: int, scanner_stderr: str = "") -> dict[str, Any]:
    if scanner_exit_code != 0 or not raw.strip():
        return _unavailable(scanner_stderr.strip() or f"frontend license scanner exited {scanner_exit_code}")
    try:
        scanner = _json_object(raw)
        package_json = _json_object(package_json_raw)
    except FloorParseError as exc:
        return _unavailable(scanner_stderr.strip() or str(exc))

    expected: dict[str, str] = {}
    for package_name in package_json.get("dependencies", {}):
        expected[package_name] = "production"
    for package_name in package_json.get("devDependencies", {}):
        if package_name in expected:
            raise FloorParseError(f"frontend package is both production and dev/test: {package_name}")
        expected[package_name] = "dev/test"

    by_name: dict[str, dict[str, Any]] = {}
    for key, metadata in scanner.items():
        if not isinstance(key, str) or not isinstance(metadata, dict):
            continue
        name, version = _npm_key_name_version(key, metadata)
        if name in expected:
            by_name[name] = {
                "package": name,
                "resolvedVersion": version,
                "license": metadata.get("licenses") if isinstance(metadata.get("licenses"), str) else "UNKNOWN",
                "classification": expected[name],
                "ecosystem": "frontend",
            }

    normalized: list[dict[str, Any]] = []
    for name in sorted(expected):
        normalized.append(by_name.get(name, {
            "package": name,
            "resolvedVersion": "",
            "license": "UNKNOWN",
            "classification": expected[name],
            "ecosystem": "frontend",
        }))
    return {"status": STATUS_AVAILABLE, "findings": normalized}


def _direct_requirement_names(raw: str) -> list[str]:
    names: list[str] = []
    for raw_line in raw.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        match = re.match(r"([A-Za-z0-9_.-]+)(?:\[[^\]]+\])?", line)
        if not match:
            raise FloorParseError(f"unsupported direct requirement line: {raw_line}")
        names.append(match.group(1))
    return names


def normalize_backend_licenses(raw: str, requirements_raw: str, *, scanner_exit_code: int, scanner_stderr: str = "") -> dict[str, Any]:
    if scanner_exit_code != 0 or not raw.strip():
        return _unavailable(scanner_stderr.strip() or f"backend license scanner exited {scanner_exit_code}")
    try:
        scanner = _json_array(raw)
    except FloorParseError as exc:
        return _unavailable(scanner_stderr.strip() or str(exc))

    expected = _direct_requirement_names(requirements_raw)
    by_name: dict[str, dict[str, Any]] = {}
    for item in scanner:
        if not isinstance(item, dict):
            continue
        name = item.get("Name")
        if isinstance(name, str):
            by_name[_canonical_python_name(name)] = item

    normalized: list[dict[str, Any]] = []
    for declared_name in sorted(expected, key=_canonical_python_name):
        item = by_name.get(_canonical_python_name(declared_name), {})
        normalized.append({
            "package": declared_name,
            "resolvedVersion": item.get("Version") if isinstance(item.get("Version"), str) else "",
            "license": item.get("License") if isinstance(item.get("License"), str) and item.get("License") else "UNKNOWN",
            "classification": "unknown",
            "ecosystem": "backend",
        })
    return {"status": STATUS_AVAILABLE, "findings": normalized}


def _validate_license_review(value: Any, index: int, *, as_of: date) -> list[str]:
    if not isinstance(value, dict):
        return [f"INVALID_LICENSE_REVIEW[{index}]:object"]
    violations: list[str] = []
    for field in ("ecosystem", "package", "resolvedVersion", "license", "classification", "issue", "owner", "reason", "reviewBy"):
        if not isinstance(value.get(field), str) or not value[field].strip():
            violations.append(f"INVALID_LICENSE_REVIEW[{index}]:missing-{field}")
    review = _parse_date(value.get("reviewBy"))
    if review is None:
        violations.append(f"INVALID_LICENSE_REVIEW[{index}]:reviewBy")
    elif review < as_of:
        violations.append(f"EXPIRED_LICENSE_REVIEW[{index}]:{value.get('reviewBy')}")
    return violations


def _license_review_matches(finding: dict[str, Any], review: dict[str, Any]) -> bool:
    return all(review.get(field) == finding.get(field) for field in ("ecosystem", "package", "resolvedVersion", "license", "classification"))


def evaluate_license_policy(frontend: dict[str, Any], backend: dict[str, Any], policy: dict[str, Any], *, as_of: date) -> dict[str, Any]:
    violations: list[str] = []
    if frontend.get("status") != STATUS_AVAILABLE:
        violations.append("FRONTEND_LICENSE_SCAN_UNAVAILABLE")
    if backend.get("status") != STATUS_AVAILABLE:
        violations.append("BACKEND_LICENSE_SCAN_UNAVAILABLE")

    config = policy.get("licenses", {})
    approved = config.get("approvedExpressions", [])
    forbidden = config.get("forbiddenExpressions", [])
    reviews = config.get("reviews", [])
    if not isinstance(approved, list) or not all(isinstance(item, str) for item in approved):
        approved = []
        violations.append("INVALID_POLICY:licenses.approvedExpressions")
    if not isinstance(forbidden, list) or not all(isinstance(item, str) for item in forbidden):
        forbidden = []
        violations.append("INVALID_POLICY:licenses.forbiddenExpressions")
    if not isinstance(reviews, list):
        reviews = []
        violations.append("INVALID_POLICY:licenses.reviews")
    for index, review in enumerate(reviews):
        violations.extend(_validate_license_review(review, index, as_of=as_of))

    classified: list[dict[str, Any]] = []
    for report in (frontend, backend):
        if report.get("status") != STATUS_AVAILABLE:
            continue
        for finding in report.get("findings", []):
            item = dict(finding)
            license_value = item.get("license")
            if license_value in forbidden:
                item["policyClass"] = LICENSE_FORBIDDEN
                violations.append(f"FORBIDDEN_LICENSE:{item.get('ecosystem')}:{item.get('package')}:{license_value}")
            elif license_value in approved:
                item["policyClass"] = LICENSE_APPROVED
            else:
                item["policyClass"] = LICENSE_NEEDS_REVIEW
                matches = [review for review in reviews if isinstance(review, dict) and _license_review_matches(item, review)]
                if len(matches) != 1:
                    violations.append(
                        f"LICENSE_REVIEW_REQUIRED:{item.get('ecosystem')}:{item.get('package')}:{item.get('classification')}:{license_value}"
                    )
                else:
                    item["reviewIssue"] = matches[0]["issue"]
                    item["reviewBy"] = matches[0]["reviewBy"]
            classified.append(item)

    return {
        "status": POLICY_PASS if not violations else POLICY_FAIL,
        "violations": violations,
        "findings": sorted(classified, key=lambda item: (item.get("ecosystem", ""), item.get("package", ""))),
    }


def classify_secret_scan(raw: str, *, scanner_exit_code: int, scanner_stderr: str = "") -> dict[str, Any]:
    if scanner_exit_code not in (0, SECRET_FINDING_EXIT_CODE):
        return _unavailable(scanner_stderr.strip() or f"gitleaks exited {scanner_exit_code}")
    if not raw.strip():
        return _unavailable(scanner_stderr.strip() or "gitleaks produced no JSON report")
    try:
        findings = _json_array(raw)
    except FloorParseError as exc:
        return _unavailable(scanner_stderr.strip() or str(exc))

    safe: list[dict[str, Any]] = []
    for finding in findings:
        if not isinstance(finding, dict):
            raise FloorParseError("gitleaks finding must be an object")
        safe.append({
            "RuleID": finding.get("RuleID"),
            "Description": finding.get("Description"),
            "File": finding.get("File"),
            "StartLine": finding.get("StartLine"),
            "EndLine": finding.get("EndLine"),
            "Commit": finding.get("Commit"),
            "Fingerprint": finding.get("Fingerprint"),
        })
    return {"status": STATUS_AVAILABLE, "findings": safe}


def evaluate_secret_policy(report: dict[str, Any], *, synthetic_test: str) -> dict[str, Any]:
    violations: list[str] = []
    if report.get("status") != STATUS_AVAILABLE:
        violations.append("SECRET_SCAN_UNAVAILABLE")
    elif report.get("findings"):
        violations.append(f"CHANGED_SCOPE_SECRET_FINDINGS:{len(report['findings'])}")
    if synthetic_test != "PASS":
        violations.append("SYNTHETIC_SECRET_REDACTION_TEST_FAILED")
    return {"status": POLICY_PASS if not violations else POLICY_FAIL, "violations": violations}


def _compact(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Normalize maintained scanner output and enforce the remaining supply-chain floor.")
    parser.add_argument("--python-audit", required=True, type=Path)
    parser.add_argument("--python-exit-code", required=True, type=int)
    parser.add_argument("--python-stderr", type=Path)
    parser.add_argument("--frontend-licenses", required=True, type=Path)
    parser.add_argument("--frontend-license-exit-code", required=True, type=int)
    parser.add_argument("--frontend-license-stderr", type=Path)
    parser.add_argument("--frontend-package-json", required=True, type=Path)
    parser.add_argument("--backend-licenses", required=True, type=Path)
    parser.add_argument("--backend-license-exit-code", required=True, type=int)
    parser.add_argument("--backend-license-stderr", type=Path)
    parser.add_argument("--backend-requirements", required=True, type=Path)
    parser.add_argument("--secret-report", required=True, type=Path)
    parser.add_argument("--secret-exit-code", required=True, type=int)
    parser.add_argument("--secret-stderr", type=Path)
    parser.add_argument("--synthetic-secret-test", required=True, choices=("PASS", "FAIL"))
    parser.add_argument("--policy", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--secret-safe-output", required=True, type=Path)
    args = parser.parse_args(argv)

    policy = _json_object(_read_text(args.policy))
    today = date.today()
    python_report = classify_python_audit(_read_text(args.python_audit), scanner_exit_code=args.python_exit_code, scanner_stderr=_read_text(args.python_stderr))
    frontend_licenses = normalize_frontend_licenses(
        _read_text(args.frontend_licenses),
        _read_text(args.frontend_package_json),
        scanner_exit_code=args.frontend_license_exit_code,
        scanner_stderr=_read_text(args.frontend_license_stderr),
    )
    backend_licenses = normalize_backend_licenses(
        _read_text(args.backend_licenses),
        _read_text(args.backend_requirements),
        scanner_exit_code=args.backend_license_exit_code,
        scanner_stderr=_read_text(args.backend_license_stderr),
    )
    secret_report = classify_secret_scan(_read_text(args.secret_report), scanner_exit_code=args.secret_exit_code, scanner_stderr=_read_text(args.secret_stderr))

    python_policy = evaluate_python_policy(python_report, policy, as_of=today)
    license_policy = evaluate_license_policy(frontend_licenses, backend_licenses, policy, as_of=today)
    secret_policy = evaluate_secret_policy(secret_report, synthetic_test=args.synthetic_secret_test)
    violations = [*python_policy["violations"], *license_policy["violations"], *secret_policy["violations"]]
    result = {
        "pythonAudit": python_report,
        "pythonPolicy": python_policy,
        "frontendLicenses": frontend_licenses,
        "backendLicenses": backend_licenses,
        "licensePolicy": license_policy,
        "secretScan": secret_report,
        "secretPolicy": secret_policy,
        "policy": {"status": POLICY_PASS if not violations else POLICY_FAIL, "violations": violations},
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.secret_safe_output.write_text(json.dumps(secret_report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"PYTHON_AUDIT_STATUS={python_report['status']}")
    print(f"PYTHON_FINDINGS={_compact(python_report.get('findings', []))}")
    print(f"FRONTEND_LICENSES={_compact([item for item in license_policy['findings'] if item.get('ecosystem') == 'frontend'])}")
    print(f"BACKEND_LICENSES={_compact([item for item in license_policy['findings'] if item.get('ecosystem') == 'backend'])}")
    print(f"LICENSE_POLICY_RESULT={license_policy['status']}")
    print(f"SECRET_SCAN_STATUS={secret_report['status']}")
    print(f"SECRET_SCAN_FINDINGS={len(secret_report.get('findings', []))}")
    print(f"SUPPLY_CHAIN_FLOOR_POLICY={result['policy']['status']}")
    if violations:
        print(f"SUPPLY_CHAIN_FLOOR_VIOLATIONS={_compact(violations)}")
    return 0 if not violations else 2


if __name__ == "__main__":
    raise SystemExit(main())
