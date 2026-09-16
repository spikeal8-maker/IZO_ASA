"""Validate canonical context cards and generate deterministic indexes."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
REQUIRED_KEYS = (
    "status",
    "domain",
    "read_when",
    "source_paths",
    "test_paths",
    "related_domains",
    "forbidden_paths",
    "owner",
)
LIST_KEYS = REQUIRED_KEYS[2:7]
OPTIONAL_SCALAR_KEYS = (
    "context_role", "role", "scope", "audience",
    "evidence_base_sha", "evidence_package", "status_effective_when",
    "updated", "verified_source_sha",
)
ALLOWED_KEYS = set(REQUIRED_KEYS) | set(OPTIONAL_SCALAR_KEYS)
IGNORED_PATH_PARTS = {
    ".git", ".runtime", "node_modules", ".venv", "media",
    "cache", "caches", "__pycache__",
}
TOKEN_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
WINDOWS_ABSOLUTE = re.compile(r"^[A-Za-z]:")


class ContextSchemaError(RuntimeError):
    pass


@dataclass(frozen=True)
class ContextCard:
    path: str
    status: str
    domain: str
    read_when: tuple[str, ...]
    source_paths: tuple[str, ...]
    test_paths: tuple[str, ...]
    related_domains: tuple[str, ...]
    forbidden_paths: tuple[str, ...]
    owner: str
    fingerprint: str


def _schema_error(path: Path, message: str) -> ContextSchemaError:
    return ContextSchemaError(f"{path.as_posix()}: {message}")


def _parse_array(path: Path, key: str, value: str) -> tuple[str, ...]:
    try:
        payload = json.loads(value)
    except json.JSONDecodeError as exc:
        raise _schema_error(path, f"{key} must be a JSON string array") from exc
    if not isinstance(payload, list) or not all(isinstance(item, str) for item in payload):
        raise _schema_error(path, f"{key} must contain only strings")
    values = [item.strip() for item in payload]
    if not values or any(not item for item in values):
        raise _schema_error(path, f"{key} must not be empty")
    if len(values) != len(set(values)):
        raise _schema_error(path, f"{key} contains duplicate values")
    if "unknown" in values and values != ["unknown"]:
        raise _schema_error(path, f"{key} cannot mix unknown with concrete values")
    return tuple(sorted(values))


def _parse_front_matter(path: Path) -> dict[str, Any]:
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0] != "---":
        raise _schema_error(path, "canonical context card must start with front matter")
    try:
        end = lines.index("---", 1)
    except ValueError as exc:
        raise _schema_error(path, "front matter is not closed") from exc
    values: dict[str, Any] = {}
    for line in lines[1:end]:
        if not line.strip() or ":" not in line:
            raise _schema_error(path, f"invalid front matter line: {line!r}")
        key, raw = line.split(":", 1)
        key, raw = key.strip(), raw.strip()
        if key in values:
            raise _schema_error(path, f"duplicate metadata key: {key}")
        values[key] = _parse_array(path, key, raw) if key in LIST_KEYS else raw
    unknown = sorted(set(values) - ALLOWED_KEYS)
    missing = [key for key in REQUIRED_KEYS if key not in values]
    if unknown:
        raise _schema_error(path, f"unknown metadata keys: {', '.join(unknown)}")
    if missing:
        raise _schema_error(path, f"missing metadata keys: {', '.join(missing)}")
    if values["status"] != "canonical":
        raise _schema_error(path, "status must be canonical")
    for key in ("domain", "owner"):
        value = values[key]
        if not isinstance(value, str) or not TOKEN_RE.fullmatch(value):
            raise _schema_error(path, f"{key} must be a lowercase kebab-case token")
    for item in (*values["read_when"], *values["related_domains"]):
        if item != "unknown" and not TOKEN_RE.fullmatch(item):
            raise _schema_error(path, f"invalid routing/domain token: {item}")
    for key in OPTIONAL_SCALAR_KEYS:
        if key in values and (not isinstance(values[key], str) or not values[key].strip()):
            raise _schema_error(path, f"{key} must be a non-empty scalar")
    for key in ("evidence_base_sha", "verified_source_sha"):
        if key in values and not SHA_RE.fullmatch(values[key]):
            raise _schema_error(path, f"{key} must be a 40-character lowercase SHA")
    if "updated" in values and not DATE_RE.fullmatch(values["updated"]):
        raise _schema_error(path, "updated must be YYYY-MM-DD")
    return values


def _normalize_repo_path(root: Path, card_path: Path, value: str) -> str:
    if value == "unknown":
        return value
    if not value or "\\" in value or value.startswith("/") or WINDOWS_ABSOLUTE.match(value):
        raise _schema_error(card_path, f"invalid repository path: {value}")
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise _schema_error(card_path, f"invalid repository path: {value}")
    if any(part.lower() in IGNORED_PATH_PARTS for part in parts):
        raise _schema_error(card_path, f"ignored repository path is not allowed: {value}")
    candidate = root.joinpath(*parts)
    try:
        resolved = candidate.resolve(strict=True)
    except FileNotFoundError as exc:
        raise _schema_error(card_path, f"referenced path does not exist: {value}") from exc
    if resolved != root and root not in resolved.parents:
        raise _schema_error(card_path, f"repository path escapes root: {value}")
    return "/".join(parts)


def _fingerprint(metadata: dict[str, Any]) -> str:
    normalized = {
        key: list(metadata[key]) if key in LIST_KEYS else metadata[key]
        for key in sorted(metadata)
    }
    payload = json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def parse_context_card(root: Path, path: Path) -> ContextCard:
    root = root.resolve()
    path = path.resolve(strict=True)
    if path != root and root not in path.parents:
        raise _schema_error(path, "context card escapes repository root")
    metadata = _parse_front_matter(path)
    normalized: dict[str, Any] = dict(metadata)
    for key in ("source_paths", "test_paths", "forbidden_paths"):
        normalized[key] = tuple(
            sorted(_normalize_repo_path(root, path, value) for value in metadata[key])
        )
    relative = path.relative_to(root).as_posix()
    return ContextCard(
        path=relative,
        status=normalized["status"],
        domain=normalized["domain"],
        read_when=tuple(normalized["read_when"]),
        source_paths=tuple(normalized["source_paths"]),
        test_paths=tuple(normalized["test_paths"]),
        related_domains=tuple(normalized["related_domains"]),
        forbidden_paths=tuple(normalized["forbidden_paths"]),
        owner=normalized["owner"],
        fingerprint=_fingerprint(normalized),
    )


def discover_cards(root: Path) -> list[ContextCard]:
    root = root.resolve()
    context_dir = root / "docs" / "context"
    paths = sorted(context_dir.glob("*.md"))
    if not paths:
        raise ContextSchemaError("docs/context contains no canonical cards")
    cards = [parse_context_card(root, path) for path in paths]
    domains: dict[str, str] = {}
    routing: dict[str, str] = {}
    for card in cards:
        previous = domains.get(card.domain)
        if previous:
            raise ContextSchemaError(
                f"duplicate domain ownership: {card.domain} -> {previous}, {card.path}"
            )
        domains[card.domain] = card.path
        for token in card.read_when:
            previous = routing.get(token)
            if previous:
                raise ContextSchemaError(
                    f"duplicate read_when ownership: {token} -> {previous}, {card.path}"
                )
            routing[token] = card.path
    domain_names = set(domains)
    for card in cards:
        for related in card.related_domains:
            if related != "unknown" and related not in domain_names:
                raise ContextSchemaError(
                    f"{card.path}: related domain does not exist: {related}"
                )
    return sorted(cards, key=lambda item: item.domain)


def card_payload(card: ContextCard) -> dict[str, Any]:
    return {
        "path": card.path,
        "status": card.status,
        "domain": card.domain,
        "read_when": list(card.read_when),
        "source_paths": list(card.source_paths),
        "test_paths": list(card.test_paths),
        "related_domains": list(card.related_domains),
        "forbidden_paths": list(card.forbidden_paths),
        "owner": card.owner,
        "fingerprint": card.fingerprint,
    }


def build_index(root: Path) -> dict[str, Any]:
    cards = discover_cards(root)
    return {
        "schemaVersion": 1,
        "cardCount": len(cards),
        "cards": [card_payload(card) for card in cards],
    }


def render_json(index: dict[str, Any]) -> str:
    return json.dumps(index, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"


def _md(value: str) -> str:
    return value.replace("|", "\\|")


def render_markdown(index: dict[str, Any]) -> str:
    lines = [
        "# Generated context index",
        "",
        "Generated by `python tools/generate_context_index.py`. Do not edit manually.",
        "",
        "| Domain | Owner | Read when | Sources | Tests | Related | Card |",
        "|---|---|---|---:|---:|---|---|",
    ]
    for card in index["cards"]:
        lines.append(
            f"| {_md(card['domain'])} | {_md(card['owner'])} | "
            f"{_md(', '.join(card['read_when']))} | {len(card['source_paths'])} | "
            f"{len(card['test_paths'])} | {_md(', '.join(card['related_domains']))} | "
            f"`{card['path']}` |"
        )
    lines.extend(["", "## Fingerprints", ""])
    for card in index["cards"]:
        lines.append(f"- `{card['domain']}`: `{card['fingerprint']}`")
    lines.append("")
    return "\n".join(lines)


def _resolve(root: Path, value: Path) -> Path:
    return value if value.is_absolute() else root / value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    parser.add_argument(
        "--json-output", type=Path,
        default=Path("docs/generated/context-index.json"),
    )
    parser.add_argument(
        "--markdown-output", type=Path,
        default=Path("docs/generated/context-index.md"),
    )
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    try:
        index = build_index(root)
    except ContextSchemaError as exc:
        print(f"context schema error: {exc}")
        return 2
    artifacts = {
        _resolve(root, args.json_output): render_json(index),
        _resolve(root, args.markdown_output): render_markdown(index),
    }
    if args.check:
        outdated = [
            path.relative_to(root).as_posix()
            for path, expected in artifacts.items()
            if not path.is_file() or path.read_text(encoding="utf-8") != expected
        ]
        if outdated:
            for path in outdated:
                print(f"outdated: {path}")
            return 1
        print("ok: context index")
        return 0
    for path, content in artifacts.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")
        print(f"wrote {path.relative_to(root).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
