"""CTX-001 contracts: scoped context docs and the generated frontend map.

Keeps the context documents honest (size bounds, referenced files exist), makes
the frontend map impossible to forget, and runs the canonical agent-entry
contracts in the existing Quick gate.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from test_agent_instructions import assert_agent_instruction_contracts

ROOT = Path(__file__).resolve().parents[1]

CONTEXT_DOCS = [
    ROOT / "docs" / "context" / "admin-control-center.md",
    ROOT / "docs" / "context" / "backend-auth-bots.md",
    ROOT / "docs" / "context" / "frontend-studio.md",
    ROOT / "docs" / "context" / "video-gallery-feed.md",
]
ADMIN_GUIDE = ROOT / "docs" / "admin-panel-guide.md"
LEGACY_ADMIN_SPEC = ROOT / "docs" / "admin-panel-product-spec.md"

PATH_PATTERN = re.compile(
    r"`((?:backend|frontend|tools|docs|ops|architecture)/[\w./\-]+\.(?:py|tsx|ts|css|md|mjs|ps1|json|html))`"
)


def test_context_docs_exist_within_size_bounds() -> None:
    for doc in CONTEXT_DOCS:
        assert doc.is_file(), f"missing context doc: {doc.name}"
        lines = doc.read_text(encoding="utf-8").count("\n") + 1
        assert 100 <= lines <= 250, f"{doc.name} must stay 100-250 lines, has {lines}"


def test_context_docs_reference_only_existing_files() -> None:
    for doc in CONTEXT_DOCS:
        text = doc.read_text(encoding="utf-8")
        for referenced in PATH_PATTERN.findall(text):
            assert (ROOT / referenced).exists(), f"{doc.name} references missing {referenced}"


def test_admin_guide_is_canonical_and_routed() -> None:
    guide = ADMIN_GUIDE.read_text(encoding="utf-8")
    assert "status: canonical" in guide
    assert "document_role: admin-current-guide" in guide
    for referenced in PATH_PATTERN.findall(guide):
        assert (ROOT / referenced).exists(), f"admin guide references missing {referenced}"
    for route in (
        "/admin/dashboard",
        "/admin/crm",
        "/admin/models/openrouter/text",
        "/admin/notifications",
        "/admin/social",
        "/admin/tariffs",
        "/admin/payments",
        "/admin/mail",
        "/admin/bots",
        "/admin/logs",
    ):
        assert route in guide, f"admin guide lacks current route: {route}"

    context_path = "docs/context/admin-control-center.md"
    assert context_path in guide
    assert context_path in (ROOT / "AI_START_HERE.md").read_text(encoding="utf-8")
    assert context_path in (ROOT / "docs" / "NOW.md").read_text(encoding="utf-8")

    legacy = LEGACY_ADMIN_SPEC.read_text(encoding="utf-8")
    assert "status: historical" in legacy
    assert "superseded_by: docs/admin-panel-guide.md" in legacy


def test_frontend_map_files_exist_and_parse() -> None:
    json_path = ROOT / "docs" / "generated" / "frontend-map.json"
    md_path = ROOT / "docs" / "generated" / "frontend-map.md"
    assert json_path.is_file() and md_path.is_file()
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["version"] == 1
    assert payload["routes"], "frontend map must contain route groups"
    entries = {route["entry"] for route in payload["routes"]}
    assert "frontend/src/newUi.tsx" in entries
    for route in payload["routes"]:
        for referenced in [route["entry"], *route["components"], *route["css"], *route["tests"]]:
            if referenced.endswith((".tsx", ".ts", ".css", ".mjs", ".html")):
                assert (ROOT / referenced).exists(), f"frontend map references missing {referenced}"
    for shell in payload["static_shells"]:
        assert (ROOT / shell["shell"]).exists()


def test_frontend_map_check_is_wired_into_verification() -> None:
    verify = (ROOT / "tools" / "verify.ps1").read_text(encoding="utf-8")
    assert "generate_frontend_map.mjs" in verify
    assert 'Invoke-NativeStep -Name "frontend_map_check"' in verify
    assert verify.count('"frontend_map_check"') >= 1


def test_canonical_agent_entry_is_wired_into_quick_gate() -> None:
    assert_agent_instruction_contracts()
