from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from tools.generate_context_index import (
    ContextSchemaError,
    build_index,
    discover_cards,
    render_json,
    render_markdown,
)
from tools.agent_system.context import (
    MAX_PACKET_BYTES,
    MAX_PACKET_LINES,
    ContextPacketError,
    build_packet,
    _select_card,
)

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "generate_context_index.py"


def _card_text(
    domain: str,
    read_when: list[str],
    *,
    source_paths: list[str] | None = None,
    test_paths: list[str] | None = None,
    related_domains: list[str] | None = None,
    forbidden_paths: list[str] | None = None,
    owner: str = "test-owner",
    body: str = "# Context\n",
    extra_metadata: dict[str, str] | None = None,
) -> str:
    import json

    metadata = {
        "status": "canonical",
        "domain": domain,
        "read_when": read_when,
        "source_paths": source_paths or ["unknown"],
        "test_paths": test_paths or ["unknown"],
        "related_domains": related_domains or ["unknown"],
        "forbidden_paths": forbidden_paths or ["unknown"],
        "owner": owner,
    }
    metadata.update(extra_metadata or {})
    lines = ["---"]
    for key, value in metadata.items():
        rendered = json.dumps(value, ensure_ascii=False, separators=(",", ":")) if isinstance(value, list) else value
        lines.append(f"{key}: {rendered}")
    lines.extend(["---", "", body.rstrip("\n")])
    return "\n".join(lines) + "\n"


def _write_card(root: Path, name: str, text: str) -> Path:
    path = root / "docs" / "context" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_repository_context_index_is_deterministic_and_current() -> None:
    first = build_index(ROOT)
    second = build_index(ROOT)
    assert first == second
    assert first["schemaVersion"] == 1
    assert first["cardCount"] == 8
    assert {card["domain"] for card in first["cards"]} == {
        "admin-control-center",
        "admin-models",
        "backend-auth-bots",
        "billing-payments",
        "chat",
        "frontend-studio",
        "image-generation",
        "video-gallery-feed",
    }
    assert render_json(first) == render_json(second)
    assert render_markdown(first) == render_markdown(second)
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--check"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ok: context index" in result.stdout


def test_missing_declared_path_fails_but_explicit_unknown_is_allowed(tmp_path: Path) -> None:
    _write_card(
        tmp_path,
        "missing.md",
        _card_text("missing", ["missing-route"], source_paths=["src/missing.py"]),
    )
    with pytest.raises(ContextSchemaError, match="referenced path does not exist"):
        discover_cards(tmp_path)

    card = tmp_path / "docs" / "context" / "missing.md"
    card.write_text(
        _card_text("missing", ["missing-route"], source_paths=["unknown"]),
        encoding="utf-8",
    )
    cards = discover_cards(tmp_path)
    assert cards[0].source_paths == ("unknown",)


def test_duplicate_domain_and_read_when_ownership_fail_closed(tmp_path: Path) -> None:
    _write_card(tmp_path, "one.md", _card_text("one", ["shared-route"]))
    _write_card(tmp_path, "two.md", _card_text("two", ["shared-route"]))
    with pytest.raises(ContextSchemaError, match="duplicate read_when ownership"):
        discover_cards(tmp_path)

    second = tmp_path / "docs" / "context" / "two.md"
    second.write_text(_card_text("one", ["second-route"]), encoding="utf-8")
    with pytest.raises(ContextSchemaError, match="duplicate domain ownership"):
        discover_cards(tmp_path)


def test_fingerprint_ignores_body_and_unrelated_repo_changes_but_tracks_metadata(tmp_path: Path) -> None:
    card = _write_card(tmp_path, "one.md", _card_text("one", ["route-one"]))
    first = discover_cards(tmp_path)[0].fingerprint
    (tmp_path / "README.md").write_text("unrelated\n", encoding="utf-8")
    assert discover_cards(tmp_path)[0].fingerprint == first

    text = card.read_text(encoding="utf-8").replace("# Context", "# Context changed")
    card.write_text(text, encoding="utf-8")
    assert discover_cards(tmp_path)[0].fingerprint == first

    text = card.read_text(encoding="utf-8").replace(
        'read_when: ["route-one"]',
        'read_when: ["route-two"]',
    )
    card.write_text(text, encoding="utf-8")
    assert discover_cards(tmp_path)[0].fingerprint != first


def test_schema_rejects_unknown_key_and_path_traversal(tmp_path: Path) -> None:
    card = _write_card(tmp_path, "one.md", _card_text("one", ["route-one"]))
    text = card.read_text(encoding="utf-8").replace("owner: test-owner", "owner: test-owner\nsurprise: true")
    card.write_text(text, encoding="utf-8")
    with pytest.raises(ContextSchemaError, match="unknown metadata keys"):
        discover_cards(tmp_path)

    card.write_text(
        _card_text("one", ["route-one"], source_paths=["../escape.py"]),
        encoding="utf-8",
    )
    with pytest.raises(ContextSchemaError, match="invalid repository path"):
        discover_cards(tmp_path)

def test_generator_check_detects_output_drift(tmp_path: Path) -> None:
    _write_card(tmp_path, "one.md", _card_text("one", ["route-one"]))
    outputs = [
        "--json-output", "docs/generated/context-index.json",
        "--markdown-output", "docs/generated/context-index.md",
    ]
    generated = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(tmp_path), *outputs],
        text=True, capture_output=True, timeout=30, check=False,
    )
    assert generated.returncode == 0, generated.stdout + generated.stderr
    checked = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(tmp_path), *outputs, "--check"],
        text=True, capture_output=True, timeout=30, check=False,
    )
    assert checked.returncode == 0, checked.stdout + checked.stderr
    json_path = tmp_path / "docs" / "generated" / "context-index.json"
    json_path.write_text(json_path.read_text(encoding="utf-8") + "drift\n", encoding="utf-8")
    stale = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(tmp_path), *outputs, "--check"],
        text=True, capture_output=True, timeout=30, check=False,
    )
    assert stale.returncode == 1
    assert "outdated: docs/generated/context-index.json" in stale.stdout


def test_fingerprint_tracks_source_paths_and_optional_metadata(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.py").write_text("a = 1\n", encoding="utf-8")
    (src / "b.py").write_text("b = 1\n", encoding="utf-8")
    card = _write_card(
        tmp_path, "one.md",
        _card_text("one", ["route-one"], source_paths=["src/a.py"],
                   extra_metadata={"updated": "2026-09-16"}),
    )
    first = discover_cards(tmp_path)[0].fingerprint
    card.write_text(
        _card_text("one", ["route-one"], source_paths=["src/b.py"],
                   extra_metadata={"updated": "2026-09-16"}),
        encoding="utf-8",
    )
    assert discover_cards(tmp_path)[0].fingerprint != first
    card.write_text(
        _card_text("one", ["route-one"], source_paths=["src/a.py"],
                   extra_metadata={"updated": "2026-09-17"}),
        encoding="utf-8",
    )
    assert discover_cards(tmp_path)[0].fingerprint != first

def test_ignored_repository_paths_fail_closed(tmp_path: Path) -> None:
    ignored = tmp_path / "node_modules"
    ignored.mkdir()
    (ignored / "x.py").write_text("x = 1\n", encoding="utf-8")
    _write_card(
        tmp_path, "one.md",
        _card_text("one", ["route-one"], source_paths=["node_modules/x.py"]),
    )
    with pytest.raises(ContextSchemaError, match="ignored repository path"):
        discover_cards(tmp_path)


def test_all_canonical_domains_route_and_new_packets_stay_bounded() -> None:
    domains = (
        "chat",
        "admin-models",
        "frontend-studio",
        "backend-auth-bots",
        "video-gallery-feed",
        "admin-control-center",
        "image-generation",
        "billing-payments",
    )
    for domain in domains:
        packet = build_packet(ROOT, domain)
        assert f"selected domain: `{domain}`" in packet
        assert len(packet.encode("utf-8")) <= MAX_PACKET_BYTES
        assert len(packet.splitlines()) <= MAX_PACKET_LINES

    chat = build_packet(ROOT, "chat")
    assert chat == build_packet(ROOT, "chat")
    assert "repo: `spikeal8-maker/IZO_ASA`" in chat
    assert "frontend/src/desktopChat/DesktopChatWorkspace.tsx" in chat
    assert "backend/app/api/routers/phone_chat.py" in chat
    assert "backend/main.py" in chat and "do not full-read automatically" in chat

    admin_alias = build_packet(ROOT, "openrouter-models")
    assert "selected domain: `admin-models`" in admin_alias
    assert "read_when match: openrouter-models -> admin-models" in admin_alias

    image_alias = build_packet(ROOT, "text-to-image")
    assert "selected domain: `image-generation`" in image_alias
    assert "read_when match: text-to-image -> image-generation" in image_alias
    assert "backend/app/services/generation_jobs.py" in image_alias
    assert "backend/test_generation_protection.py" in image_alias

    billing_alias = build_packet(ROOT, "checkout")
    assert "selected domain: `billing-payments`" in billing_alias
    assert "read_when match: checkout -> billing-payments" in billing_alias
    assert "backend/app/billing/contracts.py" in billing_alias
    assert "backend/test_billing_yookassa_provider.py" in billing_alias


def test_context_router_fails_closed_on_ambiguous_cross_route() -> None:
    index = {
        "cards": [
            {"domain": "one", "read_when": ["one"]},
            {"domain": "two", "read_when": ["one"]},
        ]
    }
    with pytest.raises(ContextPacketError, match="ambiguous context route: one"):
        _select_card(index, "one")


def test_context_packet_unknown_domain_lists_current_domains() -> None:
    expected = (
        "admin-control-center, admin-models, backend-auth-bots, billing-payments, "
        "chat, frontend-studio, image-generation, video-gallery-feed"
    )
    with pytest.raises(ContextPacketError, match=f"available: {expected}"):
        build_packet(ROOT, "not-a-domain")


def test_context_runtime_has_no_pilot_allowlist_or_broad_repo_scan() -> None:
    source = (ROOT / "tools" / "agent_system" / "context.py").read_text(encoding="utf-8")
    assert "PILOT_DOMAINS" not in source
    assert ".rglob(" not in source
    assert "os.walk" not in source
