from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

SEVERITIES = ("critical", "high", "moderate", "low")
STATUS_AVAILABLE = "AVAILABLE"
STATUS_UNAVAILABLE = "EXTERNAL_VERIFICATION_UNAVAILABLE"


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
        findings.append(
            {
                "package": package_name,
                "severity": severity,
                "range": range_value,
                "via": [_normalize_via_entry(entry) for entry in via],
                "fixAvailable": _normalize_fix_available(item.get("fixAvailable", False)),
            }
        )

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


def _compact(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Normalize npm audit JSON without remediating dependencies.")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--scanner-exit-code", required=True, type=int)
    parser.add_argument("--scanner-stderr", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)

    raw = _read_text(args.input)
    stderr = _read_text(args.scanner_stderr) if args.scanner_stderr else ""
    result = classify_npm_audit(
        raw,
        scanner_exit_code=args.scanner_exit_code,
        scanner_stderr=stderr,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"NPM_AUDIT_STATUS={result['status']}")
    print(f"NPM_COUNTS={_compact(result.get('counts'))}")
    print(f"NPM_FINDINGS={_compact(result.get('findings', []))}")
    if result["status"] == STATUS_UNAVAILABLE:
        print(f"NPM_AUDIT_REASON={_compact(result.get('reason', ''))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
