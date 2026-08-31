#!/usr/bin/env python3
"""Fixed cold-eval prompts and receipt validation for IZO_ASA agents.

The tool never runs an agent or estimates tokens. Token fields may be null and
must contain only values reported by Codex/API.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
ROUTING_FILES = {"AGENTS.md", "AI_START_HERE.md", "docs/NOW.md"}
TOKEN_FIELDS = ("inputTokens", "cachedInputTokens", "outputTokens")
PROTECTED_FULL_READS = {
    "backend/main.py",
    "frontend/src/newUi.tsx",
    "frontend/src/LegacyApp.tsx",
    "frontend/src/adminModels.tsx",
    "frontend/src/newStudioV3.css",
    "frontend/src/newUi.css",
    "frontend/src/videoStudio.css",
    "frontend/src/index.css",
}
COMMON = """Режим: АНАЛИЗ БЕЗ ИЗМЕНЕНИЙ.

- Новый чистый чат Codex в canonical IZO_ASA repository.
- Memory отключена.
- Никаких изменений, branch/commit/PR, deploy/restart или sibling worktrees.
- Никакого recursive scan и полного чтения защищённых монолитов.
- Используй AGENTS.md → AI_START_HERE.md → одну context-карту.
- Токены указывай только по данным Codex/API; иначе unknown.
- После ответа остановись.
"""

CASES: dict[str, dict[str, Any]] = {
    "chat-model-selector": {
        "title": "Desktop chat model selector",
        "limit": 8,
        "opened": ["docs/context/chat.md"],
        "anchors": [
            "frontend/src/desktopChat/DesktopChatWorkspace.tsx",
            "frontend/src/phone/features/chat/api.ts",
            "backend/app/api/routers/phone_chat.py",
            "backend/app/services/phone_chat_history.py",
        ],
        "tests": [
            "frontend/e2e-desktop-chat.mjs",
            "backend/test_phone_chat_model_catalog.py",
        ],
        "task": """Определи минимальный frontend/backend/test scope для изменения выбора
модели в desktop chat и сохранения chatModelId существующего thread.
Покажи UI owner, frontend API, backend route/service/persistence, targeted tests
и неизвестное. Открой не более 8 предметных файлов.""",
    },
    "admin-last-admin-race": {
        "title": "Last-admin race routing",
        "limit": 6,
        "opened": [
            "docs/context/admin-control-center.md",
            "docs/admin-mutation-audit.md",
        ],
        "anchors": [
            "backend/main.py",
            "backend/test_admin_actions.py",
        ],
        "tests": ["backend/test_admin_actions.py"],
        "task": """Не исправляя код, определи exact route, handler, gap ID,
существующие test nodes и недостающую characterization для гонки двух
администраторов, одновременно снимающих роли друг у друга.
Открой не более 6 предметных файлов.""",
    },
    "studio-text-to-image": {
        "title": "Current studio text-to-image routing",
        "limit": 8,
        "opened": ["docs/context/frontend-studio.md"],
        "anchors": [
            "docs/generated/frontend-map.md",
            "frontend/src/App.tsx",
            "frontend/src/newUi.tsx",
        ],
        "tests": [
            "frontend/e2e-critical-prompts.mjs",
            "frontend/e2e-generate.mjs",
        ],
        "task": """Определи минимальный frontend/backend/test scope для изменения
поведения текстового prompt в текущей студии на route `/`, не затрагивая legacy.
Покажи route entry, bounded studio section, API boundary, targeted tests и
запрещённые shortcuts. Открой не более 8 предметных файлов.""",
    },
}

FIELDS = {
    "schemaVersion", "caseId", "caseFingerprint", "runId", "startedAt",
    "agent", "model", "repoHead", "coldSession", "memoryEnabled",
    "routingFilesOpened", "subjectFilesOpened", "resultAnchors",
    "largeFilesReadFully", "broadScans", "repeatedSearches", "toolCalls",
    "testsProposed", "testsRun", "ownerCorrections", "result",
    "inputTokens", "cachedInputTokens", "outputTokens", "elapsedSeconds", "notes",
}


class InvalidReceipt(ValueError):
    pass


def case_fingerprint(case_id: str) -> str:
    payload = {
        "schemaVersion": SCHEMA_VERSION,
        "caseId": case_id,
        "common": COMMON,
        "case": CASES[case_id],
    }
    canonical = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def prompt(case_id: str) -> str:
    return f"{COMMON}\nЗадача:\n{CASES[case_id]['task']}\n"


def template(case_id: str) -> dict[str, Any]:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "caseId": case_id,
        "caseFingerprint": case_fingerprint(case_id),
        "runId": "",
        "startedAt": "",
        "agent": "Codex",
        "model": "unknown",
        "repoHead": "",
        "coldSession": True,
        "memoryEnabled": False,
        "routingFilesOpened": sorted(ROUTING_FILES),
        "subjectFilesOpened": [],
        "resultAnchors": [],
        "largeFilesReadFully": [],
        "broadScans": [],
        "repeatedSearches": 0,
        "toolCalls": 0,
        "testsProposed": [],
        "testsRun": [],
        "ownerCorrections": 0,
        "result": "partial",
        "inputTokens": None,
        "cachedInputTokens": None,
        "outputTokens": None,
        "elapsedSeconds": 0,
        "notes": "",
    }


def _paths(value: object, field: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise InvalidReceipt(f"{field} must be a string list")
    paths = [v.replace("\\", "/").strip() for v in value]
    if any(not v or re.match(r"^[A-Za-z]:/|^/", v) or ".." in Path(v).parts for v in paths):
        raise InvalidReceipt(f"{field} must contain repository-relative paths")
    if len(paths) != len(set(paths)):
        raise InvalidReceipt(f"{field} contains duplicates")
    return paths


def _strings(value: object, field: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise InvalidReceipt(f"{field} must be a string list")
    return value


def _count(value: object, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise InvalidReceipt(f"{field} must be a non-negative integer")
    return value


def _tokens(value: object, field: str) -> int | None:
    if value is None or value == "unknown":
        return None
    return _count(value, field)


def validate(data: object) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise InvalidReceipt("receipt must be a JSON object")
    missing, extra = FIELDS - data.keys(), data.keys() - FIELDS
    if missing or extra:
        raise InvalidReceipt(f"field mismatch; missing={sorted(missing)} extra={sorted(extra)}")
    if data["schemaVersion"] != SCHEMA_VERSION or data["caseId"] not in CASES:
        raise InvalidReceipt("unsupported schemaVersion or caseId")
    case_id = str(data["caseId"])
    case = CASES[case_id]

    for field in (
        "caseFingerprint", "runId", "startedAt", "agent", "model", "repoHead", "notes"
    ):
        if not isinstance(data[field], str):
            raise InvalidReceipt(f"{field} must be a string")
    if data["caseFingerprint"] != case_fingerprint(case_id):
        raise InvalidReceipt("caseFingerprint does not match the current fixed prompt")
    if not data["runId"].strip():
        raise InvalidReceipt("runId is required")
    try:
        datetime.fromisoformat(data["startedAt"].replace("Z", "+00:00"))
    except ValueError as exc:
        raise InvalidReceipt("startedAt must be ISO-8601") from exc
    if not re.fullmatch(r"[0-9a-f]{40}", data["repoHead"]):
        raise InvalidReceipt("repoHead must be a full lowercase Git SHA")
    if not isinstance(data["coldSession"], bool) or not isinstance(data["memoryEnabled"], bool):
        raise InvalidReceipt("coldSession and memoryEnabled must be booleans")

    routing = set(_paths(data["routingFilesOpened"], "routingFilesOpened"))
    subjects = _paths(data["subjectFilesOpened"], "subjectFilesOpened")
    anchors = set(_paths(data["resultAnchors"], "resultAnchors"))
    full_reads = set(_paths(data["largeFilesReadFully"], "largeFilesReadFully"))
    broad_scans = _strings(data["broadScans"], "broadScans")
    proposed = "\n".join(_strings(data["testsProposed"], "testsProposed"))
    _strings(data["testsRun"], "testsRun")
    repeated = _count(data["repeatedSearches"], "repeatedSearches")
    corrections = _count(data["ownerCorrections"], "ownerCorrections")
    for field in ("toolCalls", "elapsedSeconds"):
        _count(data[field], field)
    token_values = {field: _tokens(data[field], field) for field in TOKEN_FIELDS}
    if data["result"] not in {"pass", "partial", "fail"}:
        raise InvalidReceipt("result must be pass, partial or fail")

    violations: list[str] = []
    if data["coldSession"] is not True:
        violations.append("not-a-cold-session")
    if data["memoryEnabled"] is not False:
        violations.append("memory-enabled")
    if not ROUTING_FILES <= routing:
        violations.append("missing-routing-files")
    if len(subjects) > int(case["limit"]):
        violations.append(f"subject-file-limit:{len(subjects)}>{case['limit']}")
    missing_opened = sorted(set(case["opened"]) - set(subjects))
    if missing_opened:
        violations.append(f"missing-opened:{','.join(missing_opened)}")
    missing_anchors = sorted(set(case["anchors"]) - anchors)
    if missing_anchors:
        violations.append(f"missing-anchors:{','.join(missing_anchors)}")
    protected = sorted(full_reads & PROTECTED_FULL_READS)
    if protected:
        violations.append(f"protected-full-read:{','.join(protected)}")
    if broad_scans:
        violations.append(f"broad-scans:{len(broad_scans)}")
    if repeated:
        violations.append(f"repeated-searches:{repeated}")
    if corrections:
        violations.append(f"owner-corrections:{corrections}")
    missing_tests = [value for value in case["tests"] if value not in proposed]
    if missing_tests:
        violations.append(f"missing-test-hints:{','.join(missing_tests)}")
    if data["result"] == "pass" and violations:
        violations.append("reported-pass-with-violations")

    return {
        "caseId": case_id,
        "caseFingerprint": data["caseFingerprint"],
        "repoHead": data["repoHead"],
        "reportedResult": data["result"],
        "gatePassed": data["result"] == "pass" and not violations,
        "violations": violations,
        "subjectFiles": len(subjects),
        "toolCalls": data["toolCalls"],
        "elapsedSeconds": data["elapsedSeconds"],
        **token_values,
    }


def _read(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InvalidReceipt(f"cannot read {path}: {exc}") from exc


def summarize(directory: Path) -> dict[str, Any]:
    rows = [validate(_read(path)) for path in sorted(directory.glob("*.json"))]
    if not rows:
        raise InvalidReceipt("no JSON receipts found")
    case_ids = {row["caseId"] for row in rows}
    if len(case_ids) != len(rows):
        raise InvalidReceipt("duplicate case receipts")
    if case_ids != set(CASES):
        raise InvalidReceipt(
            f"incomplete case set; expected={sorted(CASES)} actual={sorted(case_ids)}"
        )
    repo_heads = {row["repoHead"] for row in rows}
    if len(repo_heads) != 1:
        raise InvalidReceipt(f"receipts use different repoHead values: {sorted(repo_heads)}")

    token_totals: dict[str, dict[str, int | None]] = {}
    for field in TOKEN_FIELDS:
        known = [int(row[field]) for row in rows if row[field] is not None]
        token_totals[field] = {
            "knownReceipts": len(known),
            "value": sum(known) if known else None,
        }

    return {
        "schemaVersion": SCHEMA_VERSION,
        "repoHead": rows[0]["repoHead"],
        "receiptCount": len(rows),
        "cases": rows,
        "totalSubjectFiles": sum(row["subjectFiles"] for row in rows),
        "totalToolCalls": sum(row["toolCalls"] for row in rows),
        "totalElapsedSeconds": sum(row["elapsedSeconds"] for row in rows),
        "gatesPassed": sum(row["gatePassed"] for row in rows),
        "tokenTotals": token_totals,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list")
    p = sub.add_parser("prompt"); p.add_argument("case", choices=sorted(CASES))
    t = sub.add_parser("template"); t.add_argument("case", choices=sorted(CASES)); t.add_argument("--output", type=Path)
    v = sub.add_parser("validate"); v.add_argument("receipt", type=Path)
    s = sub.add_parser("summarize"); s.add_argument("directory", type=Path)
    args = parser.parse_args(argv)

    try:
        if args.command == "list":
            for key, case in CASES.items():
                print(
                    f"{key}\t{case['title']}\tmaxSubjectFiles={case['limit']}"
                    f"\t{case_fingerprint(key)}"
                )
        elif args.command == "prompt":
            print(prompt(args.case), end="")
        elif args.command == "template":
            text = json.dumps(template(args.case), ensure_ascii=False, indent=2) + "\n"
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(text, encoding="utf-8")
                print(args.output)
            else:
                print(text, end="")
        elif args.command == "validate":
            print(json.dumps({"ok": True, **validate(_read(args.receipt))}, ensure_ascii=False, indent=2))
        elif args.command == "summarize":
            print(json.dumps(summarize(args.directory), ensure_ascii=False, indent=2))
    except InvalidReceipt as exc:
        print(f"AGENT_EVAL_INVALID: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
