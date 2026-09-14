"""Canonical agent-entry contracts for IZO_ASA.

These tests validate stable repository invariants. Runtime facts, active process
IDs and deployment state must not be hard-coded here.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

ADAPTERS = (
    ROOT / "CLAUDE.md",
    ROOT / "GEMINI.md",
    ROOT / ".github" / "copilot-instructions.md",
)
REQUIRED = (
    ROOT / "AGENTS.md",
    ROOT / "AI_START_HERE.md",
    ROOT / "docs" / "NOW.md",
    ROOT / "docs" / "current-status.md",
    ROOT / "docs" / "agent-control-plane.md",
    ROOT / "docs" / "stabilization-optimization-master-spec.md",
    ROOT / "docs" / "agent-tasks" / "AI-CANONICAL-001.md",
    ROOT / "docs" / "agent-tasks" / "AI-CANONICAL-REPAIR-001.md",
    ROOT / "docs" / "agent-tasks" / "AI-EVAL-BASELINE-DEFER-001.md",
    *ADAPTERS,
)
CANONICAL_ROUTING_DOCS = (
    ROOT / "AGENTS.md",
    ROOT / "AI_START_HERE.md",
    ROOT / "docs" / "NOW.md",
    ROOT / "docs" / "agent-control-plane.md",
)
GENERATED_EVIDENCE = (
    ROOT / "docs" / "generated" / "frontend-map.md",
    ROOT / "docs" / "generated" / "frontend-map.json",
    ROOT / "docs" / "generated" / "architecture-inventory.md",
    ROOT / "docs" / "generated" / "architecture-inventory.json",
    ROOT / "backend" / "SYMBOL_MAP.md",
)

WINDOWS_ABSOLUTE_PATH = re.compile(r"(?i)\b[A-Z]:\\")
STATUS_ROLE = "status_role: current-status-aggregator"
BACKLOG_ROLE = "backlog_role: program-router"
READING_ORDER_ROLE = "reading_order_role: sole-owner"
DEAD_GENERATED_PATHS = (
    "architecture/generated-inventory.json",
    "architecture/generated-inventory.md",
    "architecture/generated-inventory",
)


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _lines(path: Path) -> list[str]:
    return _text(path).splitlines()


def _markdown_files() -> list[Path]:
    ignored_names = {
        ".git",
        ".runtime",
        ".pytest_cache",
        "node_modules",
        ".venv",
        "__pycache__",
    }
    markdown: list[Path] = []
    for current, directories, filenames in os.walk(ROOT):
        directories[:] = [name for name in directories if name not in ignored_names]
        root = Path(current)
        markdown.extend(root / name for name in filenames if name.endswith(".md"))
    return sorted(markdown)


def _assert_unique_marker(markdown: list[Path], marker: str, expected: str) -> None:
    owners = [
        path.relative_to(ROOT).as_posix()
        for path in markdown
        if marker in _text(path)
    ]
    assert owners == [expected], f"{marker!r} must be unique, found: {owners}"


def _assert_reading_order() -> None:
    start = _text(ROOT / "AI_START_HERE.md")
    heading = "## 2. Единственный порядок чтения"
    assert heading in start
    section = start.split(heading, 1)[1].split("## 3.", 1)[0]
    sequence = (
        "Корневой `AGENTS.md`",
        "Этот `AI_START_HERE.md`",
        "`docs/NOW.md`",
        "scoped `AGENTS.md`",
        "карта из `docs/context/`",
        "Task Contract текущего package",
        "generated maps",
        "source и tests",
    )
    positions = [section.index(item) for item in sequence]
    assert positions == sorted(positions), f"invalid canonical reading order: {positions}"

    forbidden_duplicate_headings = (
        "Единственный порядок чтения",
        "Текущая иерархия знаний",
        "Единственная иерархия источников",
    )
    for path in CANONICAL_ROUTING_DOCS:
        if path.name == "AI_START_HERE.md":
            continue
        text = _text(path)
        for phrase in forbidden_duplicate_headings:
            assert phrase not in text, (
                f"{path.relative_to(ROOT)} duplicates reading-order ownership: {phrase}"
            )
        assert "AI_START_HERE.md" in text, (
            f"{path.relative_to(ROOT)} must defer to AI_START_HERE.md"
        )


def _assert_risk_classes() -> None:
    start = _text(ROOT / "AI_START_HERE.md")
    heading = "## 4. Выбери класс риска"
    assert heading in start
    section = start.split(heading, 1)[1].split("## 5.", 1)[0]
    expected = {
        "`low`": ("Документация", "targeted checks"),
        "`standard`": ("frontend/backend", "Quick"),
        "`high-assurance`": ("Auth, billing, migrations", "race/idempotency"),
        "`release-ops`": ("production data/provider/network", "разрешение владельца"),
    }
    for risk_class, evidence in expected.items():
        assert risk_class in section, f"missing risk class: {risk_class}"
        for phrase in evidence:
            assert phrase in section, (
                f"risk class {risk_class} lacks required evidence: {phrase}"
            )
    assert "запрещён третий broad scan" in section
    assert "bounded diagnosis" in section
    assert "`BLOCKED` допустим только" in section
    assert "подтверждённой внешней зависимости" in section
    assert "иначе package остаётся active" in section


def _assert_generated_evidence_paths() -> None:
    for path in GENERATED_EVIDENCE:
        assert path.is_file(), f"missing generated evidence: {path.relative_to(ROOT)}"

    routing_text = "\n".join(_text(path) for path in CANONICAL_ROUTING_DOCS)
    for dead in DEAD_GENERATED_PATHS:
        assert dead not in routing_text, f"canonical routing references dead path: {dead}"

    start = _text(ROOT / "AI_START_HERE.md")
    now = _text(ROOT / "docs" / "NOW.md")
    for path in GENERATED_EVIDENCE:
        relative = path.relative_to(ROOT).as_posix()
        assert relative in start or relative in now, (
            f"generated evidence is not routed from AI_START_HERE/NOW: {relative}"
        )


def _assert_program_and_package_status() -> None:
    program = _text(ROOT / "docs" / "agent-control-plane.md")
    assert "status: active-program" in program
    assert "canonical: true" in program
    assert "daily_context: false" in program
    assert "master_spec: docs/stabilization-optimization-master-spec.md" in program
    assert "AI-CANONICAL-REPAIR-001" in program
    assert "merge `8e15a89aae71f71eed31a0ef490228cdbc854c7d`" in program
    assert "baseline issue #71" in program

    master = _text(ROOT / "docs" / "stabilization-optimization-master-spec.md")
    assert "status: owner-directed-master-spec" in master
    assert "daily_context: false" in master
    assert "current_status_owner: docs/NOW.md" in master
    assert "agent_program: docs/agent-control-plane.md" in master
    assert "production_change_authorized: false" in master
    assert "AI-EVAL-BASELINE-001" in master
    assert "STAB-MAIN-GUARD-001" in master
    assert "AI-ENFORCE-001" in master
    assert "BOT-STABILITY ACCEPTED" in master

    first = _text(ROOT / "docs" / "agent-tasks" / "AI-CANONICAL-001.md")
    assert "status: completed" in first
    assert "record_role: completed-package-receipt" in first
    assert "merged_pr: 73" in first
    assert "merged_sha: 49a19e271e4e0e71d1fa6f871f828f0a233cfbdf" in first
    assert "deployment: none" in first

    repair = _text(
        ROOT / "docs" / "agent-tasks" / "AI-CANONICAL-REPAIR-001.md"
    )
    assert "status: completed" in repair
    assert "record_role: completed-package-receipt" in repair
    assert "final_candidate_sha: 8f1de5a167ca94a334e5df274da479cf0beab0ee" in repair
    assert "ci_run: 33312197937" in repair
    assert "merged_pr: 75" in repair
    assert "merged_sha: 8e15a89aae71f71eed31a0ef490228cdbc854c7d" in repair
    assert "completion_effective_when: closeout-source-merged-to-main" in repair
    assert "deployment: none" in repair

    amendment = _text(
        ROOT / "docs" / "agent-tasks" / "AI-EVAL-BASELINE-DEFER-001.md"
    )
    assert "status: active-program-amendment" in amendment
    assert "record_role: dependency-amendment" in amendment
    assert "ecb02bf84ae21a46711c9b38b61784147fb9fc0a" in amendment
    assert "The frozen baseline is deferred, not waived." in amendment
    assert "AI-CONTEXT-PILOT-001` (#107)" in amendment
    assert "AI-EVAL-001` (#123)" in amendment
    assert "all three receipts exist before #107 starts" in amendment

    now = _text(ROOT / "docs" / "NOW.md")
    assert "completed_package: AI-EVAL-BASELINE-DEFER-001" in now
    assert "active_package: AI-PACKAGE-001" in now
    assert "active_task_contract: github-issue-101" in now
    assert "baseline_source_sha: ecb02bf84ae21a46711c9b38b61784147fb9fc0a" in now
    assert "baseline_status: deferred-required-before-AI-CONTEXT-PILOT-001" in now
    assert "blocker: none" in now
    assert "next_candidate: STAB-MAIN-GUARD-001" in now
    assert "Активен `AI-PACKAGE-001`, issue #101." in now
    assert "deferred, not waived" in now
    assert "Запрещено активировать" in now
    assert "`AI-CONTEXT-PILOT-001` (#107)" in now
    assert "`AI-EVAL-001` (#123)" in now


def assert_agent_instruction_contracts() -> None:
    for path in REQUIRED:
        assert path.is_file(), f"missing canonical agent file: {path.relative_to(ROOT)}"

    limits = {
        ROOT / "AGENTS.md": 230,
        ROOT / "AI_START_HERE.md": 120,
        ROOT / "docs" / "NOW.md": 140,
        ROOT / "docs" / "agent-control-plane.md": 250,
        ROOT / "docs" / "agent-tasks" / "AI-CANONICAL-001.md": 120,
        ROOT / "docs" / "agent-tasks" / "AI-CANONICAL-REPAIR-001.md": 150,
        ROOT / "docs" / "agent-tasks" / "AI-EVAL-BASELINE-DEFER-001.md": 120,
    }
    for path, maximum in limits.items():
        count = len(_lines(path))
        assert count <= maximum, (
            f"{path.relative_to(ROOT)} exceeds {maximum} lines: {count}"
        )

    for adapter in ADAPTERS:
        text = _text(adapter)
        lines = text.splitlines()
        assert 4 <= len(lines) <= 20, (
            f"{adapter.name} must stay 4-20 lines, has {len(lines)}"
        )
        assert "AGENTS.md" in text, f"{adapter.name} does not point to AGENTS.md"
        assert "AI_START_HERE.md" in text, (
            f"{adapter.name} does not point to AI_START_HERE.md"
        )
        assert not WINDOWS_ABSOLUTE_PATH.search(text), (
            f"{adapter.name} must not define an absolute workspace path"
        )

    agents = _text(ROOT / "AGENTS.md")
    assert "`AI_START_HERE.md` is the sole owner" in agents
    assert "docs/NOW.md" in agents
    assert "repository-operation-lock.ps1" in agents
    assert "Do not change VPS, FRP, DNS, tunnel or AdGuard" in agents
    assert "The current executable backlog is" not in agents

    readme = _text(ROOT / "README.md")
    assert "Prototype web" not in readme
    assert "Implemented prototype scope" not in readme
    assert "docs/NOW.md" in readme
    assert "AI_START_HERE.md" in readme

    legacy_status = _text(ROOT / "docs" / "current-status.md")
    assert "superseded_by: docs/NOW.md" in legacy_status
    assert "AUTH-BOT-P0-20260723" not in legacy_status
    assert "Active package:" not in legacy_status

    markdown = _markdown_files()
    _assert_unique_marker(markdown, STATUS_ROLE, "docs/NOW.md")
    _assert_unique_marker(markdown, BACKLOG_ROLE, "docs/NOW.md")
    _assert_unique_marker(markdown, READING_ORDER_ROLE, "AI_START_HERE.md")
    _assert_reading_order()
    _assert_risk_classes()
    _assert_generated_evidence_paths()
    _assert_program_and_package_status()


def test_agent_instruction_contracts() -> None:
    assert_agent_instruction_contracts()
