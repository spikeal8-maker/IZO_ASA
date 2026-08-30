"""Canonical agent-entry contracts for IZO_ASA.

These checks intentionally validate only stable repository invariants. Runtime
facts, active process IDs and deployment state must not be hard-coded here.
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
    *ADAPTERS,
)
WINDOWS_ABSOLUTE_PATH = re.compile(r"(?i)\b[A-Z]:\\")
STATUS_ROLE = "status_role: current-status-aggregator"
BACKLOG_ROLE = "backlog_role: program-router"


def _lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


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
    return markdown


def assert_agent_instruction_contracts() -> None:
    for path in REQUIRED:
        assert path.is_file(), f"missing canonical agent file: {path.relative_to(ROOT)}"

    start_lines = _lines(ROOT / "AI_START_HERE.md")
    now_lines = _lines(ROOT / "docs" / "NOW.md")
    assert len(start_lines) <= 120, f"AI_START_HERE.md exceeds 120 lines: {len(start_lines)}"
    assert len(now_lines) <= 140, f"docs/NOW.md exceeds 140 lines: {len(now_lines)}"

    for adapter in ADAPTERS:
        text = adapter.read_text(encoding="utf-8")
        lines = text.splitlines()
        assert 4 <= len(lines) <= 20, f"{adapter.name} must stay 4-20 lines, has {len(lines)}"
        assert "AGENTS.md" in text, f"{adapter.name} does not point to AGENTS.md"
        assert "AI_START_HERE.md" in text, f"{adapter.name} does not point to AI_START_HERE.md"
        assert not WINDOWS_ABSOLUTE_PATH.search(text), (
            f"{adapter.name} must not define an absolute workspace path"
        )

    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert "docs/NOW.md" in agents
    assert "AI_START_HERE.md" in agents
    assert "The current executable backlog is" not in agents
    assert "repository-operation-lock.ps1" in agents

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "Prototype web" not in readme
    assert "Implemented prototype scope" not in readme
    assert "docs/NOW.md" in readme
    assert "AI_START_HERE.md" in readme

    legacy_status = (ROOT / "docs" / "current-status.md").read_text(encoding="utf-8")
    assert "superseded_by: docs/NOW.md" in legacy_status
    assert "AUTH-BOT-P0-20260723" not in legacy_status
    assert "Active package:" not in legacy_status

    markdown = _markdown_files()
    status_owners = [
        path.relative_to(ROOT).as_posix()
        for path in markdown
        if STATUS_ROLE in path.read_text(encoding="utf-8")
    ]
    backlog_owners = [
        path.relative_to(ROOT).as_posix()
        for path in markdown
        if BACKLOG_ROLE in path.read_text(encoding="utf-8")
    ]
    assert status_owners == ["docs/NOW.md"], (
        f"current-status aggregator must be unique, found: {status_owners}"
    )
    assert backlog_owners == ["docs/NOW.md"], (
        f"program router must be unique, found: {backlog_owners}"
    )


def test_agent_instruction_contracts() -> None:
    assert_agent_instruction_contracts()
