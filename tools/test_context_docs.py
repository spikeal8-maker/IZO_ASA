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
from tools.agent_system.context import MAX_PACKET_BYTES, MAX_PACKET_LINES, build_packet
from tools.generate_context_index import discover_cards

ROOT = Path(__file__).resolve().parents[1]

def _context_docs() -> list[Path]:
    return [ROOT / card.path for card in discover_cards(ROOT)]

ADMIN_GUIDE = ROOT / "docs" / "admin-panel-guide.md"
LEGACY_ADMIN_SPEC = ROOT / "docs" / "admin-panel-product-spec.md"

CHAT_SYSTEM = ROOT / "docs" / "chat-system.md"
CHAT_ASSISTANT = ROOT / "docs" / "chat-assistant-contract.md"
CHAT_CONTEXT = ROOT / "docs" / "context" / "chat.md"
CHAT_PUBLISHING_DOCS = (
    ROOT / "README.md",
    ROOT / "AI_START_HERE.md",
    ROOT / "docs" / "NOW.md",
    CHAT_SYSTEM,
    CHAT_ASSISTANT,
    CHAT_CONTEXT,
)

PATH_PATTERN = re.compile(
    r"`((?:backend|frontend|tools|docs|ops|architecture)/[\w./\-]+\.(?:py|tsx|ts|css|md|mjs|ps1|json|html))`"
)
MARKDOWN_LINK_PATTERN = re.compile(r"\[[^\]]+\]\(([^)]+)\)")


def test_context_docs_exist_within_size_bounds() -> None:
    for doc in _context_docs():
        assert doc.is_file(), f"missing context doc: {doc.name}"
        lines = doc.read_text(encoding="utf-8").count("\n") + 1
        assert 100 <= lines <= 250, f"{doc.name} must stay 100-250 lines, has {lines}"


def test_context_index_has_unique_domains_and_routes() -> None:
    cards = discover_cards(ROOT)
    domains = [card.domain for card in cards]
    routes = [token for card in cards for token in card.read_when]
    assert len(domains) == len(set(domains))
    assert len(routes) == len(set(routes))


def test_new_context_cards_are_valid_utf8_without_question_mark_corruption() -> None:
    cards = {
        "image-generation.md": ("Назначение", "Границы"),
        "billing-payments.md": ("Назначение", "Границы"),
        "audio.md": ("Назначение", "Границы"),
        "3d.md": ("Назначение", "Границы"),
        "release-ops.md": ("Назначение", "Границы"),
    }
    for name, markers in cards.items():
        data = (ROOT / "docs" / "context" / name).read_bytes()
        text = data.decode("utf-8")
        for marker in markers:
            assert marker in text, f"{name} lacks canonical UTF-8 marker: {marker}"
        assert re.search(r"\?{4,}", text) is None, f"{name} contains suspicious question-mark corruption"


def test_slice_two_context_cards_preserve_capability_and_safety_truth() -> None:
    audio = (ROOT / "docs" / "context" / "audio.md").read_text(encoding="utf-8")
    three_d = (ROOT / "docs" / "context" / "3d.md").read_text(encoding="utf-8")
    release = (ROOT / "docs" / "context" / "release-ops.md").read_text(encoding="utf-8")
    assert "Windows System.Speech" in audio
    assert "Persistent audio history" in audio
    assert "не доказана" in audio
    assert "DISABLED / CONTRACT-ONLY" in three_d
    assert "Live provider calls = NONE" in three_d
    for marker in ("CODE COMPLETE", "PUSHED", "CANDIDATE PREPARED", "DEPLOYED", "VERIFIED", "OPERATIONALLY VERIFIED"):
        assert marker in release
    assert "Не выполнять deploy." in release
    assert "Не выполнять restart." in release


def test_large_context_packet_truncation_is_explicit_and_preserves_boundaries() -> None:
    packet = build_packet(ROOT, "admin-control-center")
    assert len(packet.encode("utf-8")) <= MAX_PACKET_BYTES
    assert len(packet.splitlines()) <= MAX_PACKET_LINES
    assert "> Canonical card truncated to packet budget." in packet
    assert "## Routing" in packet
    assert "selected domain: `admin-control-center`" in packet
    assert "## Declared boundaries" in packet
    assert "### Source paths" in packet
    assert "### Focused tests" in packet


def test_context_docs_reference_only_existing_files() -> None:
    for doc in _context_docs():
        text = doc.read_text(encoding="utf-8")
        for referenced in PATH_PATTERN.findall(text):
            assert (ROOT / referenced).exists(), f"{doc.name} references missing {referenced}"


def test_chat_docs_are_discoverable_without_duplicating_reading_order() -> None:
    start = (ROOT / "AI_START_HERE.md").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    system = CHAT_SYSTEM.read_text(encoding="utf-8")
    assistant = CHAT_ASSISTANT.read_text(encoding="utf-8")
    context = CHAT_CONTEXT.read_text(encoding="utf-8")

    assert "`/chat`, `/phone/chat`, chat models/tools/history" in start
    assert "(docs/context/chat.md)" in start
    assert "Читайте в таком порядке:" not in readme
    assert "(docs/chat-system.md)" in readme
    assert "(docs/chat-assistant-contract.md)" in readme
    assert "(chat-assistant-contract.md)" in system
    assert "(context/chat.md)" in system
    assert "(../chat-system.md)" in context
    assert "(../chat-assistant-contract.md)" in context
    assert "(chat-system.md)" in assistant
    assert "(context/chat.md)" in assistant


def test_chat_contracts_publish_evidence_and_effective_state() -> None:
    required_metadata = (
        "status:",
        "role:",
        "scope:",
        "audience:",
        "evidence_base_sha:",
        "status_effective_when: merged-to-main",
        "updated:",
    )
    for doc in (CHAT_SYSTEM, CHAT_ASSISTANT, CHAT_CONTEXT):
        text = doc.read_text(encoding="utf-8")
        for marker in required_metadata:
            assert marker in text, f"{doc.name} lacks publication metadata: {marker}"

    assistant_lines = len(CHAT_ASSISTANT.read_text(encoding="utf-8").splitlines())
    assert 150 <= assistant_lines <= 350, (
        f"assistant contract must stay reviewable, has {assistant_lines} lines"
    )


def test_local_markdown_links_in_chat_publishing_docs_resolve() -> None:
    for doc in CHAT_PUBLISHING_DOCS:
        text = doc.read_text(encoding="utf-8")
        for raw_target in MARKDOWN_LINK_PATTERN.findall(text):
            target = raw_target.strip().split("#", 1)[0]
            if not target or target.startswith(("http://", "https://", "mailto:")):
                continue
            resolved = (doc.parent / target).resolve()
            assert resolved.exists(), (
                f"{doc.relative_to(ROOT)} has broken Markdown link: {raw_target}"
            )


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