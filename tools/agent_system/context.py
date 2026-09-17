"""Deterministic bounded context packets for the pilot domains."""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any

from tools.generate_context_index import ContextSchemaError, build_index

MAX_PACKET_BYTES = 32 * 1024
MAX_PACKET_LINES = 250
INDEX_PATH = Path("docs/generated/context-index.json")
GENERATED_EVIDENCE = (
    "docs/generated/context-index.md",
    "docs/generated/frontend-map.md",
    "docs/generated/architecture-inventory.md",
    "backend/SYMBOL_MAP.md",
)
PILOT_DOMAINS = {"chat", "admin-models"}
HOTSPOTS = {
    "backend/main.py",
    "frontend/src/newUi.tsx",
    "frontend/src/LegacyApp.tsx",
    "frontend/src/adminModels.tsx",
}

class ContextPacketError(RuntimeError):
    pass

def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()
        raise ContextPacketError(f"git {' '.join(args)} failed: {detail}")
    return result.stdout.strip()


def _current_index(root: Path) -> dict[str, Any]:
    expected = build_index(root)
    path = root / INDEX_PATH
    if not path.is_file():
        raise ContextPacketError(f"missing generated context index: {INDEX_PATH.as_posix()}")
    try:
        generated = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise ContextPacketError("generated context index is unreadable") from exc
    if generated != expected:
        raise ContextPacketError("generated context index is stale; run generate_context_index.py")
    return generated

def _select_card(index: dict[str, Any], requested: str) -> tuple[dict[str, Any], str]:
    requested = requested.strip().lower()
    if not requested:
        raise ContextPacketError("context domain is required")
    pilot_cards = [card for card in index["cards"] if card["domain"] in PILOT_DOMAINS]
    exact = [card for card in pilot_cards if card["domain"] == requested]
    if exact:
        return exact[0], f"exact domain match: {requested}"
    routed = [card for card in pilot_cards if requested in card["read_when"]]
    if len(routed) == 1:
        card = routed[0]
        return card, f"read_when match: {requested} -> {card['domain']}"
    if len(routed) > 1:
        raise ContextPacketError(f"ambiguous context route: {requested}")
    available = ", ".join(sorted(PILOT_DOMAINS))
    raise ContextPacketError(f"unknown context domain: {requested}; available: {available}")


def _nearest_policies(card: dict[str, Any]) -> list[str]:
    roots = {path.split("/", 1)[0] for path in card["source_paths"] if path != "unknown"}
    mapping = {
        "backend": "backend/AGENTS.md",
        "frontend": "frontend/AGENTS.md",
        "docs": "docs/AGENTS.md",
        "ops": "ops/AGENTS.md",
        "tools": "tools/AGENTS.md",
    }
    policies = [mapping[root] for root in sorted(roots) if root in mapping]
    return policies or ["AGENTS.md"]

def _warnings(card: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    if "unknown" in card["forbidden_paths"]:
        warnings.append("forbidden boundaries are partially unknown; do not broaden scope implicitly")
    hotspots = sorted(set(card["source_paths"]) & HOTSPOTS)
    if hotspots:
        warnings.append(
            "hotspots are routing pointers only; do not full-read automatically: " + ", ".join(hotspots)
        )
    return warnings


def _identity(root: Path) -> dict[str, str]:
    branch = _git(root, "branch", "--show-current") or "detached"
    remote = _git(root, "remote", "get-url", "origin")
    slug = remote.removesuffix(".git").replace("git@github.com:", "").replace("https://github.com/", "")
    return {
        "repo": slug,
        "branch": branch,
        "head": _git(root, "rev-parse", "HEAD"),
        "originMain": _git(root, "rev-parse", "refs/remotes/origin/main"),
    }


def _list_block(lines: list[str], title: str, values: list[str]) -> None:
    lines.extend([f"### {title}"])
    lines.extend(f"- `{value}`" for value in values)
    lines.append("")


def _render_packet(root: Path, requested: str, card: dict[str, Any], reason: str) -> str:
    identity = _identity(root)
    policies = _nearest_policies(card)
    warnings = _warnings(card)
    card_path = root / card["path"]
    card_text = card_path.read_text(encoding="utf-8").rstrip()
    lines = [
        "# Agent bounded context packet",
        "",
        "## Identity",
        f"- repo: `{identity['repo']}`",
        f"- branch: `{identity['branch']}`",
        f"- HEAD: `{identity['head']}`",
        f"- origin/main: `{identity['originMain']}`",
        "",
        "## Routing",
        f"- requested: `{requested}`",
        f"- selected domain: `{card['domain']}`",
        f"- reason: {reason}",
        f"- owner: `{card['owner']}`",
        f"- card: `{card['path']}`",
        "- global policy: `AGENTS.md`",
        "- nearest scoped policies: " + ", ".join(f"`{path}`" for path in policies),
        "",
        "## Declared boundaries",
        "",
    ]
    _list_block(lines, "Source paths", card["source_paths"])
    _list_block(lines, "Focused tests", card["test_paths"])
    _list_block(lines, "Related domains", card["related_domains"])
    _list_block(lines, "Forbidden paths", card["forbidden_paths"])
    lines.extend(["## Generated evidence", ""])
    for path in GENERATED_EVIDENCE:
        if (root / path).is_file():
            lines.append(f"- `{path}`")
    lines.append("")
    lines.append("## Warnings")
    if warnings:
        lines.extend(f"- {warning}" for warning in warnings)
    else:
        lines.append("- none")
    lines.extend(["", "## Canonical context card", "", card_text, ""])
    packet = "\n".join(lines)
    byte_count = len(packet.encode("utf-8"))
    line_count = len(packet.splitlines())
    if byte_count > MAX_PACKET_BYTES or line_count > MAX_PACKET_LINES:
        raise ContextPacketError(
            f"context packet exceeds budget: {byte_count}/{MAX_PACKET_BYTES} bytes, "
            f"{line_count}/{MAX_PACKET_LINES} lines; compact the canonical card"
        )
    return packet


def build_packet(root: Path, requested: str) -> str:
    root = root.resolve()
    try:
        index = _current_index(root)
    except ContextSchemaError as exc:
        raise ContextPacketError(str(exc)) from exc
    card, reason = _select_card(index, requested)
    return _render_packet(root, requested, card, reason)

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agent context")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--domain", required=True)
    args = parser.parse_args(argv)
    try:
        packet = build_packet(Path(args.repo_root), args.domain)
    except ContextPacketError as exc:
        print(f"CONTEXT_PACKET_ERROR {exc}")
        return 2
    print(packet, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
