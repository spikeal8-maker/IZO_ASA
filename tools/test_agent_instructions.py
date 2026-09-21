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
    ROOT / "docs" / "generated" / "context-index.md",
    ROOT / "docs" / "generated" / "context-index.json",
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
SCOPED_POLICIES = (
    ROOT / "backend" / "AGENTS.md",
    ROOT / "frontend" / "AGENTS.md",
    ROOT / "ops" / "AGENTS.md",
    ROOT / "docs" / "AGENTS.md",
)
CORE_POLICY_MAX_BYTES = 16 * 1024
ROOT_POLICY_MAX_BYTES = 5000
SCOPED_POLICY_MAX_BYTES = 4000


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


def _nearest_agent_policy(relative: str) -> Path:
    parts = Path(relative).parts
    for depth in range(len(parts) - 1, 0, -1):
        candidate = ROOT.joinpath(*parts[:depth], "AGENTS.md")
        if candidate.is_file():
            return candidate
    return ROOT / "AGENTS.md"


def _assert_scoped_policies() -> None:
    expected = {
        "backend/main.py": ROOT / "backend" / "AGENTS.md",
        "frontend/src/newUi.tsx": ROOT / "frontend" / "AGENTS.md",
        "ops/caddy/Caddyfile": ROOT / "ops" / "AGENTS.md",
        "docs/context/chat.md": ROOT / "docs" / "AGENTS.md",
        "tools/verify.ps1": ROOT / "AGENTS.md",
    }
    for relative, policy in expected.items():
        assert _nearest_agent_policy(relative) == policy, relative

    forbidden_markers = (
        STATUS_ROLE, BACKLOG_ROLE, READING_ORDER_ROLE,
        "active_package:", "next_candidate:",
    )
    for policy in SCOPED_POLICIES:
        assert policy.is_file(), f"missing scoped policy: {policy.relative_to(ROOT)}"
        text = _text(policy)
        assert "Root `AGENTS.md`" in text
        assert "`AI_START_HERE.md`" in text
        assert not WINDOWS_ABSOLUTE_PATH.search(text)
        assert len(_lines(policy)) <= 80, f"scoped policy too large: {policy.relative_to(ROOT)}"
        assert len(text.encode("utf-8")) <= SCOPED_POLICY_MAX_BYTES
        for marker in forbidden_markers:
            assert marker not in text, f"{policy.relative_to(ROOT)} claims canonical role: {marker}"

    ownership_markers = {
        "backend/main.py": ROOT / "backend" / "AGENTS.md",
        "LegacyApp.tsx": ROOT / "frontend" / "AGENTS.md",
        "production-release-runbook.md": ROOT / "ops" / "AGENTS.md",
    }
    policy_set = (ROOT / "AGENTS.md", *SCOPED_POLICIES)
    for marker, owner in ownership_markers.items():
        owners = [path for path in policy_set if marker in _text(path)]
        assert owners == [owner], f"semantic rule ownership drift for {marker}: {owners}"


def _assert_program_and_package_status() -> None:
    program = _text(ROOT / "docs" / "agent-control-plane.md")
    assert "status: active-program" in program
    assert "canonical: true" in program
    assert "daily_context: false" in program
    assert "master_spec: docs/stabilization-optimization-master-spec.md" in program
    assert "AI-CANONICAL-REPAIR-001" in program
    assert "merge `8e15a89aae71f71eed31a0ef490228cdbc854c7d`" in program
    assert "baseline issue #71" in program
    assert "### 1.1. GitHub-first execution" in program
    assert "GitHub является канонической source/integration surface" in program
    assert "remote executor/tool не блокирует repository-only работу" in program
    assert "`EXTERNAL_VERIFICATION_UNAVAILABLE`" in program
    assert "Network-dependent supply-chain scanning" in program

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
    assert "FULL PROGRAM COMPLETE" in master
    assert "production IZO application runs in Docker" in master
    assert "## PHASE 12 — mandatory production-container readiness/shadow" in master
    assert "## PHASE 13 — mandatory production Docker" in master
    assert "DOCKER-DEV-001" in master
    assert "первым обязательным Docker-этапом пути к production Docker" in master
    dependency_order = (
        "AI-EVAL-001",
        "CONTAINER-READY-001",
        "CONTAINER-SHADOW-001",
        "CONTAINER-PRODUCTION-001",
    )
    dependency_positions = [master.rindex(item) for item in dependency_order]
    assert dependency_positions == sorted(dependency_positions)
    for stale in (
        "PHASE 12 — optional",
        "PHASE 13 — optional",
        "Production Docker не требуется для достижения основной цели.",
        "optional CONTAINER-READY/SHADOW",
        "optional production containerization",
    ):
        assert stale not in master

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
    assert "updated: 2026-09-21" in now
    assert "source_main_at_status_update: b6a8a74c19a1d72dfac2d913d17e0f7c60020c24" in now
    assert "last_verified_main: b6a8a74c19a1d72dfac2d913d17e0f7c60020c24" in now
    assert "completed_package: STAB-PRODUCT-CONTRACT-001" in now
    assert "active_package: STAB-SUPPLY-CHAIN-001" in now
    assert "active_task_contract: github-issue-111" in now
    assert "baseline_source_sha: ecb02bf84ae21a46711c9b38b61784147fb9fc0a" in now
    assert "baseline_status: completed-point-A-accepted" in now
    assert "\nblocker:" not in now
    assert "blocker: shared-host-gh-write-credential-visible" not in now
    assert "next_candidate: STAB-TEST-HEALTH-001" in now
    assert "Completed: `STAB-PRODUCT-CONTRACT-001` (#110)." in now
    assert "Active: `STAB-SUPPLY-CHAIN-001` (#111)." in now
    assert "Next: `STAB-TEST-HEALTH-001` (#112)." in now
    assert "Architecture checkpoint after #108-#110: PASS;" in now
    assert "routes/workers/tables 251/8/65" in now
    assert "product-flow count 14" in now
    assert "active_package: STAB-PRODUCT-CONTRACT-001" not in now
    assert "active_task_contract: github-issue-110" not in now
    assert "Active: `STAB-PRODUCT-CONTRACT-001` (#110)." not in now
    for context_card in (
        "docs/context/3d.md",
        "docs/context/admin-control-center.md",
        "docs/context/admin-models.md",
        "docs/context/audio.md",
        "docs/context/backend-auth-bots.md",
        "docs/context/billing-payments.md",
        "docs/context/chat.md",
        "docs/context/frontend-studio.md",
        "docs/context/image-generation.md",
        "docs/context/release-ops.md",
        "docs/context/video-gallery-feed.md",
    ):
        assert context_card in now
    assert "docs/generated/product-flow-map.md" in now
    assert "critical product-flow + supply-chain + test-health floor" not in now
    assert "scoped/bounded context tooling" not in now
    assert "Frozen baseline — completed point A" in now
    assert "84,968 input tokens" in now
    assert "63,241 to 3,643" in now
    assert "broad tool calls from 21 to 0" in now
    assert "blocked until credential-isolation regression #139" not in now
    assert "#139 restores a deterministic coding context" not in now
    assert "cold-executor-and-coding-credential-isolation-required" not in now


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

    core_paths = (ROOT / "AGENTS.md", ROOT / "AI_START_HERE.md", ROOT / "docs" / "NOW.md")
    core_bytes = sum(len(_text(path).encode("utf-8")) for path in core_paths)
    assert core_bytes <= CORE_POLICY_MAX_BYTES, f"core mandatory policy is {core_bytes} bytes"
    assert len(_text(ROOT / "AGENTS.md").encode("utf-8")) <= ROOT_POLICY_MAX_BYTES
    _assert_scoped_policies()

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
