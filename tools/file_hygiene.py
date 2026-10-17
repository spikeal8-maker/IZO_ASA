"""Fast, offline, changed-file documentation and test-size gate.

Architecture contract is the sole owner of handwritten source line budgets.
Existing oversized files are grandfathered only while they do not grow.
"""
from __future__ import annotations

import argparse
import json
import posixpath
import re
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlsplit

DOC_LINES, DOC_BYTES = 200, 12 * 1024
NAV_LINES, NAV_BYTES = 120, 8 * 1024
TEST_BYTES, TEST_REVIEW_BYTES = 24 * 1024, 36 * 1024
SHA = re.compile(r"^[0-9a-f]{40}$")
LINK = re.compile(r"!?\[[^\]\n]*\]\(([^)\n]+)\)")


@dataclass(frozen=True)
class Change:
    status: str
    path: str
    previous: str | None = None


def git(repo: Path, *args: str) -> bytes:
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True)
    if result.returncode:
        raise ValueError("git command failed: " + " ".join(args[:3]) + " (" + str(result.returncode) + ")")
    return result.stdout


def blob(repo: Path, revision: str, path: str) -> bytes:
    return git(repo, "show", revision + ":" + path)


def changes(repo: Path, base: str, head: str) -> list[Change]:
    raw = git(repo, "diff", "--name-status", "-z", "-M", "-C", base, head, "--")
    fields = [x.decode("utf-8", "surrogateescape") for x in raw.split(b"\0") if x]
    out: list[Change] = []
    i = 0
    while i < len(fields):
        status = fields[i]
        i += 1
        if status.startswith(("R", "C")):
            if i + 1 >= len(fields):
                raise ValueError("truncated rename/copy record")
            previous, path = fields[i : i + 2]
            i += 2
        else:
            if i >= len(fields):
                raise ValueError("truncated diff record")
            path, previous = fields[i], None
            i += 1
        out.append(Change(status, path, previous))
    return out


def category(path: str) -> str | None:
    if path.startswith(("archive/", "docs/generated/", "docs/context/")):
        return None
    filename = posixpath.basename(path)
    if path.startswith("docs/") and filename.endswith(".md"):
        if path == "docs/NOW.md":
            return "status"
        if filename == "README.md" or filename.endswith("-index.md") or path == "docs/IZO_ACA_Design_System_2.0-full.md":
            return "navigator"
        return "document"
    if path == "README.md":
        return "navigator"
    if path == "TEST_PLAN.md":
        return "document"
    if not path.startswith(("backend/", "frontend/", "tools/", "tests/")):
        return None
    suffix = Path(filename).suffix.lower()
    if suffix == ".py" and (filename.startswith("test_") or filename.endswith("_test.py")):
        return "test"
    if suffix in {".ts", ".tsx", ".js", ".mjs"}:
        if re.search(r"\.(test|spec)\.(ts|tsx|js|mjs)$", filename) or filename.startswith(("e2e-", "smoke-", "visual-", "test-")):
            return "test"
    return None


def metrics(data: bytes, path: str) -> tuple[int, int]:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("non-UTF-8 authored source: " + path) from exc
    return len(text.splitlines()), len(data)


def limits(kind: str, normal_lines: int, review_lines: int) -> tuple[int, int]:
    if kind == "navigator":
        return NAV_LINES, NAV_BYTES
    if kind == "status":
        return 140, NAV_BYTES  # docs/NOW.md already has a separate 140-line contract.
    if kind == "document":
        return DOC_LINES, DOC_BYTES
    return normal_lines, TEST_BYTES


def links(text: str) -> set[str]:
    # Avoid treating fenced examples or inline code as actual Markdown links.
    visible = re.sub(r"(?ms)^[ \t]*(```|~~~)[^\n]*\n.*?^[ \t]*\1[ \t]*$", "", text)
    visible = re.sub(r"`[^`\n]*`", "", visible)
    return {match.group(1).strip().split(" ", 1)[0].strip("<>\"") for match in LINK.finditer(visible)}


def link_target(path: str, url: str) -> str | None:
    value = url.strip()
    if not value or value.startswith(("#", "/", "//")):
        return None
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc:
        return None
    target = posixpath.normpath(posixpath.join(posixpath.dirname(path), unquote(parsed.path)))
    return target


def reviews(repo: Path, head: str, changed: list[Change]) -> dict[str, str]:
    paths = [x.path for x in changed if x.path.startswith("tasks/") and x.path.endswith(".toml") and not x.status.startswith("D")]
    if len(paths) != 1:
        return {}
    try:
        obj = tomllib.loads(blob(repo, head, paths[0]).decode("utf-8"))
    except (ValueError, UnicodeError, tomllib.TOMLDecodeError):
        return {}
    return {x.get("path", ""): x.get("rationale", "") for x in obj.get("sizeReviews", []) if isinstance(x, dict)}


def assess(repo: Path, base: str, head: str) -> dict[str, object]:
    if not SHA.fullmatch(base) or not SHA.fullmatch(head):
        raise ValueError("base and head must be full 40-hex commit SHAs")
    for rev in (base, head):
        git(repo, "cat-file", "-e", rev + "^{commit}")
    diff = changes(repo, base, head)
    contract_before = json.loads(blob(repo, base, "architecture/contract.json"))
    contract_after = json.loads(blob(repo, head, "architecture/contract.json"))
    old_policy = contract_before["source_size_policy"]
    new_policy = contract_after["source_size_policy"]
    # Never silently loosen the current repository-wide source-line contract.
    normal = min(old_policy["normal_max_lines"], new_policy["normal_max_lines"])
    soft = min(old_policy["soft_max_lines"], new_policy["soft_max_lines"])
    tracked = set(git(repo, "ls-tree", "-r", "--name-only", "-z", head).decode("utf-8").split("\0"))
    exceptions = reviews(repo, head, diff)
    errors: list[dict[str, object]] = []
    checked: list[dict[str, object]] = []
    for change in diff:
        kind = category(change.path)
        if kind is None or change.status.startswith("D"):
            continue
        fresh = blob(repo, head, change.path)
        now_lines, now_bytes = metrics(fresh, change.path)
        # Renames compare to their actual previous path; copies are new files.
        old_path = change.previous if change.status.startswith("R") else change.path
        is_existing = not change.status.startswith(("A", "C"))
        previous = blob(repo, base, old_path) if is_existing else None
        before = metrics(previous, old_path) if previous is not None else None
        max_lines, max_bytes = limits(kind, normal, soft)
        entry = {"path": change.path, "kind": kind, "lines": now_lines, "bytes": now_bytes, "previous": before}
        checked.append(entry)

        if before is not None and (before[0] > max_lines or before[1] > max_bytes):
            if now_lines > before[0] or now_bytes > before[1]:
                errors.append({"code": "LEGACY_GROWTH", "path": change.path, "before": before, "after": [now_lines, now_bytes]})
        elif now_lines > max_lines or now_bytes > max_bytes:
            if kind == "test" and now_lines <= soft and now_bytes <= TEST_REVIEW_BYTES:
                justification = exceptions.get(change.path, "").strip()
                if len(justification) < 20:
                    errors.append({"code": "TEST_SIZE_REVIEW_REQUIRED", "path": change.path, "lines": now_lines, "bytes": now_bytes})
            else:
                errors.append({"code": "FILE_SIZE_EXCEEDED", "path": change.path, "lines": now_lines, "bytes": now_bytes, "max": [max_lines, max_bytes]})

        if kind in {"document", "navigator", "status"}:
            current_links = links(fresh.decode("utf-8"))
            former_links = links(previous.decode("utf-8")) if previous is not None else set()
            for link in sorted(current_links - former_links):
                target = link_target(change.path, link)
                if target and not (target in tracked or any(x.startswith(target.rstrip("/") + "/") for x in tracked)):
                    errors.append({"code": "BROKEN_NEW_LINK", "path": change.path, "link": link, "resolved": target})
    # Retiring/renaming a document must not silently break links in unchanged docs.
    gone = {
        change.previous if change.status.startswith("R") else change.path
        for change in diff if change.status.startswith(("D", "R"))
    }
    gone = {path for path in gone if path not in tracked}
    if gone:
        for doc in sorted(p for p in tracked if p.startswith("docs/") and p.endswith(".md")
                          and not p.startswith("docs/generated/")):
            source = blob(repo, head, doc).decode("utf-8")
            for link in links(source):
                target = link_target(doc, link)
                if target in gone:
                    errors.append({"code": "REMOVED_LINK_TARGET", "path": doc, "link": link, "removed": target})
    return {"base": base, "head": head, "checked": checked, "findings": errors, "passed": not errors}



def inventory(repo: Path, head: str) -> dict[str, object]:
    """Read-only inventory: existing debt is reported, never retroactively failed."""
    if not SHA.fullmatch(head):
        raise ValueError("head must be a full 40-hex commit SHA")
    tracked = set(git(repo, "ls-tree", "-r", "--name-only", "-z", head).decode("utf-8").split("\0"))
    policy = json.loads(blob(repo, head, "architecture/contract.json"))["source_size_policy"]
    records: list[dict[str, object]] = []
    for path in sorted(tracked):
        kind = category(path)
        if kind is None:
            continue
        lines, size = metrics(blob(repo, head, path), path)
        maximum = limits(kind, policy["normal_max_lines"], policy["soft_max_lines"])
        if lines > maximum[0] or size > maximum[1]:
            records.append({"path": path, "kind": kind, "lines": lines, "bytes": size, "budget": maximum})
    return {"head": head, "grandfathered_over_budget": len(records),
            "by_kind": {kind: sum(x["kind"] == kind for x in records)
                        for kind in ("document", "navigator", "status", "test")},
            "largest": sorted(records, key=lambda x: x["bytes"], reverse=True)[:30]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--base")
    parser.add_argument("--head")
    parser.add_argument("--inventory", action="store_true", help="report existing legacy debt without failing")
    args = parser.parse_args(argv)
    try:
        if args.inventory:
            resolved_head = args.head or git(args.repo.resolve(), "rev-parse", "HEAD").decode("ascii").strip()
            receipt = inventory(args.repo.resolve(), resolved_head)
        else:
            if not args.base or not args.head:
                raise ValueError("--base and --head are required for the changed-file gate")
            receipt = assess(args.repo.resolve(), args.base, args.head)
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(json.dumps({"passed": False, "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    return 0 if args.inventory or receipt["passed"] else 2


if __name__ == "__main__":
    sys.exit(main())
