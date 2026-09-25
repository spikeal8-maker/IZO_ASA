from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any


SHA_RE = re.compile(r"^[0-9a-f]{40}$")
COUNT_RE = re.compile(
    r"\b(?P<count>\d+)\s+(?P<kind>passed|failed|skipped|xfailed|xpassed|warnings|rerun|reruns)\b"
)
SUMMARY_DURATION_RE = re.compile(r"\bin\s+(?P<seconds>\d+(?:\.\d+)?)s(?:\s|$)")
DURATION_LINE_RE = re.compile(
    r"^\s*(?P<seconds>\d+(?:\.\d+)?)s\s+(?P<phase>setup|call|teardown)\s+(?P<nodeid>.+?)\s*$"
)
WARNING_CATEGORY_RE = re.compile(
    r":\s*(?P<category>[A-Za-z_][A-Za-z0-9_.]*(?:Warning))(?::|\s*$)"
)
SOURCE_COUNT_RE = re.compile(r"^(?P<source>.+?):\s*(?P<count>\d+)\s+warnings?\s*$")
SOURCE_LINE_RE = re.compile(r"^(?P<source>.+?):(?P<line>\d+)\s*$")
ERROR_TYPE_RE = re.compile(r"<class ['\"](?P<error>[A-Za-z_][A-Za-z0-9_.]*Error)['\"]>")


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _normalize_source(value: str) -> str:
    source = value.strip().replace("\\", "/")
    lowered = source.lower()
    for marker in ("/site-packages/", "/backend/", "/tools/"):
        index = lowered.rfind(marker)
        if index >= 0:
            return source[index + 1 :]
    source = re.sub(r"^[A-Za-z]:/[^/]+/[^/]+/", "<ABS>/", source)
    source = re.sub(
        r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}",
        "<UUID>",
        source,
    )
    return source


def _warning_section(lines: list[str]) -> list[str]:
    start = None
    for index, line in enumerate(lines):
        if "warnings summary" in line.lower():
            start = index + 1
            break
    if start is None:
        return []
    end = len(lines)
    for index in range(start, len(lines)):
        stripped = lines[index].strip()
        if stripped.startswith("-- Docs:") or "short test summary info" in stripped.lower():
            end = index
            break
    return lines[start:end]


def _split_blocks(lines: list[str]) -> list[list[str]]:
    blocks: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        if not line.strip():
            if current:
                blocks.append(current)
                current = []
            continue
        current.append(line)
    if current:
        blocks.append(current)
    return blocks


def _parse_warning_categories(lines: list[str], total: int) -> dict[str, Any]:
    section = _warning_section(lines)
    if total > 0 and not section:
        return {
            "categories": [
                {
                    "category": "UNATTRIBUTED_WARNING",
                    "source": "<UNATTRIBUTED>",
                    "count": total,
                }
            ],
            "parsedCount": total,
            "unattributedCount": total,
            "sectionPresent": False,
        }

    aggregate: Counter[tuple[str, str]] = Counter()
    for block in _split_blocks(section):
        category = None
        for line in block:
            match = WARNING_CATEGORY_RE.search(line)
            if match:
                category = match.group("category")
                break
        if category is None:
            continue

        found_source = False
        for line in block:
            if line[:1].isspace():
                continue
            count_match = SOURCE_COUNT_RE.match(line.strip())
            if count_match:
                aggregate[(category, _normalize_source(count_match.group("source")))] += int(
                    count_match.group("count")
                )
                found_source = True
                continue
            line_match = SOURCE_LINE_RE.match(line.strip())
            if line_match:
                aggregate[(category, _normalize_source(line_match.group("source")))] += 1
                found_source = True
        if not found_source:
            aggregate[(category, "<UNKNOWN_SOURCE>")] += 1

    parsed = sum(aggregate.values())
    if parsed < total:
        aggregate[("UNATTRIBUTED_WARNING", "<UNATTRIBUTED>")] += total - parsed
        parsed = total

    categories = [
        {"category": category, "source": source, "count": count}
        for (category, source), count in sorted(aggregate.items())
    ]
    return {
        "categories": categories,
        "parsedCount": parsed,
        "unattributedCount": sum(
            item["count"] for item in categories if item["category"] == "UNATTRIBUTED_WARNING"
        ),
        "sectionPresent": bool(section),
    }


def _normalize_cleanup_path(lines: list[str]) -> tuple[str, str]:
    joined = " ".join(lines).replace("\\", "/").lower()
    if "apply-secrets" in joined:
        return "<PYTEST_TEMP>/apply-secrets", "apply-secrets"
    if "pytest-of-" in joined:
        return "<PYTEST_TEMP>/unknown", "pytest-temp"
    return "<UNKNOWN_TEMP_PATH>", "unknown"


def _parse_cleanup(lines: list[str]) -> dict[str, Any]:
    aggregate: Counter[tuple[str, str, str]] = Counter()
    for index, line in enumerate(lines):
        if "PytestWarning: (rm_rf)" not in line:
            continue
        window = lines[index : min(index + 5, len(lines))]
        error_type = "CleanupError"
        for candidate in window:
            match = ERROR_TYPE_RE.search(candidate)
            if match:
                error_type = match.group("error")
                break
        normalized_path, owner = _normalize_cleanup_path(window)
        aggregate[(error_type, owner, normalized_path)] += 1
    categories = [
        {
            "errorType": error_type,
            "owner": owner,
            "normalizedPath": normalized_path,
            "count": count,
        }
        for (error_type, owner, normalized_path), count in sorted(aggregate.items())
    ]
    return {"count": sum(item["count"] for item in categories), "categories": categories}


def _parse_slowest(lines: list[str]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    in_section = False
    for line in lines:
        lowered = line.lower()
        if "slowest" in lowered and "durations" in lowered:
            in_section = True
            continue
        if not in_section:
            continue
        match = DURATION_LINE_RE.match(line)
        if match:
            result.append(
                {
                    "seconds": float(match.group("seconds")),
                    "phase": match.group("phase"),
                    "nodeid": match.group("nodeid"),
                }
            )
            continue
        if result and (not line.strip() or line.startswith("=")):
            break
    return result


def _parse_summary(lines: list[str]) -> tuple[dict[str, Any], float] | None:
    for line in reversed(lines):
        duration_match = SUMMARY_DURATION_RE.search(line)
        if not duration_match:
            continue
        counts: dict[str, Any] = {
            kind: 0 for kind in ("passed", "failed", "skipped", "xfailed", "xpassed", "warnings")
        }
        observed = False
        retry_count = None
        for match in COUNT_RE.finditer(line):
            observed = True
            kind = match.group("kind")
            value = int(match.group("count"))
            if kind in ("rerun", "reruns"):
                retry_count = value
            else:
                counts[kind] = value
        if observed and ("passed" in line or "failed" in line):
            counts["retries"] = retry_count
            return counts, float(duration_match.group("seconds"))
    return None


def normalize(raw_output: str, metadata: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    lines = raw_output.splitlines()
    violations: list[str] = []

    expected_head = str(metadata.get("expectedHead") or "").lower()
    exact_head = str(metadata.get("exactHead") or "").lower()
    if not SHA_RE.fullmatch(expected_head) or exact_head != expected_head:
        violations.append("EXACT_HEAD_MISMATCH")

    required_metadata = (
        "workflowRun",
        "workflowAttempt",
        "pythonVersion",
        "pytestVersion",
        "startedAt",
        "durationSeconds",
        "exitCode",
    )
    for key in required_metadata:
        if metadata.get(key) is None or metadata.get(key) == "":
            violations.append(f"METADATA_MISSING_{key.upper()}")

    if policy.get("baselineSource") != "exact-head-github-ci":
        violations.append("POLICY_BASELINE_SOURCE_INVALID")
    if policy.get("historicalCountsAcceptedAsFreshBaseline") is not False:
        violations.append("POLICY_HISTORICAL_BASELINE_MUST_BE_FALSE")

    parsed_summary = _parse_summary(lines)
    if parsed_summary is None:
        test_counts = {
            "passed": None,
            "failed": None,
            "skipped": None,
            "xfailed": None,
            "xpassed": None,
        }
        pytest_duration = None
        warnings_total = None
        retry_observability = {"status": "UNKNOWN", "retries": None}
        violations.append("PYTEST_SUMMARY_UNAVAILABLE")
    else:
        counts, pytest_duration = parsed_summary
        test_counts = {
            "passed": counts["passed"],
            "failed": counts["failed"],
            "skipped": counts["skipped"],
            "xfailed": counts["xfailed"],
            "xpassed": counts["xpassed"],
        }
        warnings_total = counts["warnings"]
        if counts["retries"] is None:
            retry_observability = {"status": "NOT_OBSERVABLE", "retries": None}
        else:
            retry_observability = {"status": "OBSERVABLE", "retries": counts["retries"]}
        if counts["failed"] > 0:
            violations.append("TEST_FAILURES_PRESENT")

    if metadata.get("exitCode") != 0:
        violations.append("FULL_VERIFICATION_FAILED")

    if warnings_total is None:
        warning_info = {
            "total": None,
            "categories": [],
            "parsedCount": None,
            "unattributedCount": None,
            "sectionPresent": False,
        }
    else:
        parsed_warnings = _parse_warning_categories(lines, warnings_total)
        if parsed_warnings["parsedCount"] > warnings_total:
            violations.append("WARNING_COUNT_INCONSISTENT")
        warning_info = {"total": warnings_total, **parsed_warnings}

    cleanup_info = _parse_cleanup(lines)
    slowest = _parse_slowest(lines)

    evidence_status = "AVAILABLE" if "PYTEST_SUMMARY_UNAVAILABLE" not in violations else "UNAVAILABLE"
    policy_status = "PASS" if not violations else "FAIL"

    return {
        "schemaVersion": 1,
        "baselineSource": policy.get("baselineSource"),
        "evidenceStatus": evidence_status,
        "exactHead": exact_head or None,
        "tests": test_counts,
        "warnings": warning_info,
        "cleanup": cleanup_info,
        "timing": {
            "pytestSeconds": pytest_duration,
            "fullVerificationSeconds": metadata.get("durationSeconds"),
            "slowest": slowest,
        },
        "retryFlakyObservability": retry_observability,
        "metadata": {
            "repository": metadata.get("repository"),
            "eventName": metadata.get("eventName"),
            "workflowRun": metadata.get("workflowRun"),
            "workflowAttempt": metadata.get("workflowAttempt"),
            "pythonVersion": metadata.get("pythonVersion"),
            "pytestVersion": metadata.get("pytestVersion"),
            "startedAt": metadata.get("startedAt"),
            "durationSeconds": metadata.get("durationSeconds"),
            "exitCode": metadata.get("exitCode"),
        },
        "policy": {
            "slice": "baseline-only",
            "status": policy_status,
            "violations": sorted(set(violations)),
            "warningToleranceEnforced": False,
            "cleanupToleranceEnforced": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Normalize pytest output into test-health evidence")
    subparsers = parser.add_subparsers(dest="command", required=True)
    normalize_parser = subparsers.add_parser("normalize")
    normalize_parser.add_argument("--raw-output", required=True, type=Path)
    normalize_parser.add_argument("--metadata", required=True, type=Path)
    normalize_parser.add_argument("--policy", required=True, type=Path)
    normalize_parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    setup_violations: list[str] = []
    try:
        metadata: dict[str, Any] = json.loads(_read_text(args.metadata))
    except Exception:
        metadata = {}
        setup_violations.append("METADATA_UNAVAILABLE")
    try:
        policy: dict[str, Any] = json.loads(_read_text(args.policy))
    except Exception:
        policy = {}
        setup_violations.append("POLICY_UNAVAILABLE")
    try:
        raw = _read_text(args.raw_output)
    except Exception:
        raw = ""
        setup_violations.append("RAW_OUTPUT_UNAVAILABLE")

    receipt = normalize(raw, metadata, policy)
    if setup_violations:
        receipt["evidenceStatus"] = "UNAVAILABLE"
        receipt["policy"]["status"] = "FAIL"
        receipt["policy"]["violations"] = sorted(
            set(receipt["policy"]["violations"] + setup_violations)
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        "TEST_HEALTH_POLICY="
        + receipt["policy"]["status"]
        + " TESTS="
        + json.dumps(receipt["tests"], sort_keys=True)
        + " WARNINGS="
        + str(receipt["warnings"]["total"])
        + " CLEANUP="
        + str(receipt["cleanup"]["count"])
    )
    return 0 if receipt["policy"]["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
