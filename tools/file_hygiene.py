"""Changed-file size checks plus regression-only references over immutable Git trees.

Normal source-line limits belong to architecture/contract.json. Old debt is
reported separately; this gate neither executes application code nor rewrites it.
"""
from __future__ import annotations

import argparse
import json
import posixpath
import re
import sys
from pathlib import Path

from tools.file_hygiene_git import Change, GitTree, blob, changes, comparison_base, git
from tools.file_hygiene_markdown import problems
from tools.file_hygiene_reviews import read_reviews

DOC_LINES, DOC_BYTES = 200, 12 * 1024
NAV_LINES, NAV_BYTES = 120, 8 * 1024
TEST_BYTES, TEST_REVIEW_BYTES = 24 * 1024, 36 * 1024
CODE_EXTENSIONS = {".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts"}
FIXTURE_EXTENSIONS = {".json", ".yaml", ".yml", ".txt", ".sql", ".html"}


def category(path: str) -> str | None:
    parts = path.split("/")
    if path.startswith(("archive/", "docs/generated/", "docs/context/")):
        return None
    if any(p in {"node_modules", ".venv", ".runtime", ".git"} for p in parts):
        return None
    filename = parts[-1]
    if filename == "AGENTS.md" or path in {"AI_START_HERE.md", "backend/SYMBOL_MAP.md"}:
        return None  # Existing instruction/generator contracts still enforce their own bounds.
    if filename.endswith(".md"):
        if path == "docs/NOW.md":
            return "status"
        if filename == "README.md" or filename.endswith("-index.md") or path == "docs/IZO_ACA_Design_System_2.0-full.md":
            return "navigator"
        return "document"
    if not path.startswith(("backend/", "frontend/", "tools/", "tests/")):
        return None
    if path == "tools/test_health_audit.py":
        return None  # Executable report analyzer; the architecture source policy owns this file.
    suffix = Path(filename).suffix.lower()
    in_test_tree = bool({"tests", "test", "__tests__", "fixtures", "test_helpers"}.intersection(parts[:-1]))
    if in_test_tree and suffix in CODE_EXTENSIONS | FIXTURE_EXTENSIONS:
        return "test"
    if suffix == ".py" and (filename == "conftest.py" or filename.startswith("test_") or filename.endswith("_test.py")):
        return "test"
    if suffix in CODE_EXTENSIONS and (re.search(r"\.(test|spec)\.[a-z]+$", filename)
                                     or filename.startswith(("e2e-", "smoke-", "visual-", "test-"))):
        return "test"
    return None


def metrics(data: bytes, path: str) -> tuple[int, int]:
    try:
        return len(data.decode("utf-8").splitlines()), len(data)
    except UnicodeDecodeError as exc:
        raise ValueError("Non-UTF-8 authored file: " + path) from exc


def limits(kind: str, normal_lines: int, review_lines: int) -> tuple[int, int]:
    if kind == "navigator":
        return NAV_LINES, NAV_BYTES
    if kind == "status":
        return 140, NAV_BYTES
    if kind == "document":
        return DOC_LINES, DOC_BYTES
    return normal_lines, TEST_BYTES


def source_limits(tree: GitTree) -> tuple[int, int]:
    policy = json.loads(tree.read("architecture/contract.json"))["source_size_policy"]
    normal, soft = policy["normal_max_lines"], policy["soft_max_lines"]
    if type(normal) is not int or type(soft) is not int or not 0 < normal <= soft:
        raise ValueError("Invalid canonical source-size bounds")
    return normal, soft


def assess(repo: Path, base: str, head: str, *, comparison: str = "merge-base") -> dict[str, object]:
    origin = comparison_base(repo, base, head, comparison)
    before_tree, after_tree = GitTree(repo, origin), GitTree(repo, head)
    normal, soft = (min(a, b) for a, b in zip(source_limits(before_tree), source_limits(after_tree)))
    delta = changes(repo, origin, head)
    exceptions, errors = read_reviews(after_tree, origin, delta)
    checked = []
    for change in delta:
        kind = category(change.path)
        if kind is None or change.status.startswith("D"):
            continue
        fresh = metrics(after_tree.read(change.path), change.path)
        old_path = change.previous if change.status.startswith("R") else change.path
        # Restoring an archive or excluded/generated file creates NEW active content.
        existing = not change.status.startswith(("A", "C")) and category(old_path) == kind
        previous = metrics(before_tree.read(old_path), old_path) if existing else None
        bounds = limits(kind, normal, soft)
        checked.append({"path": change.path, "kind": kind, "lines": fresh[0],
                        "bytes": fresh[1], "previous": previous})
        if previous and any(x > y for x, y in zip(previous, bounds)):
            if any(x > y for x, y in zip(fresh, previous)):
                errors.append({"code": "LEGACY_GROWTH", "path": change.path,
                               "before": previous, "after": fresh})
        elif any(x > y for x, y in zip(fresh, bounds)):
            if kind == "test" and fresh[0] <= soft and fresh[1] <= TEST_REVIEW_BYTES:
                if len(exceptions.get(change.path, "").strip()) < 20:
                    errors.append({"code": "TEST_SIZE_REVIEW_REQUIRED", "path": change.path,
                                   "lines": fresh[0], "bytes": fresh[1]})
            else:
                errors.append({"code": "FILE_SIZE_EXCEEDED", "path": change.path,
                               "lines": fresh[0], "bytes": fresh[1], "max": bounds})
    old_problems, new_problems = problems(before_tree), problems(after_tree)
    errors.extend({"code": code, "path": path, "link": url, "resolved": target}
                  for path, url, target, code in sorted(new_problems - old_problems))
    return {"requestedBase": base, "base": origin, "head": head, "comparison": comparison,
            "checked": checked, "findings": errors, "passed": not errors,
            "historicalReferenceDebt": len(old_problems & new_problems),
            "referenceCoverage": "CommonMark/HTML links, Markdown heading IDs, explicit inline code paths; no external HTTP"}


def inventory(repo: Path, head: str) -> dict[str, object]:
    comparison_base(repo, head, head)
    tree = GitTree(repo, head)
    normal, soft = source_limits(tree)
    records = []
    for path in sorted(tree.files):
        kind = category(path)
        if kind is None:
            continue
        lines, size = metrics(tree.read(path), path)
        bounds = limits(kind, normal, soft)
        if lines > bounds[0] or size > bounds[1]:
            records.append({"path": path, "kind": kind, "lines": lines, "bytes": size, "budget": bounds})
    debts = problems(tree)
    return {"head": head, "grandfathered_over_budget": len(records),
            "by_kind": {kind: sum(x["kind"] == kind for x in records)
                        for kind in ("document", "navigator", "status", "test")},
            "largest": sorted(records, key=lambda x: x["bytes"], reverse=True)[:30],
            "historicalReferenceDebt": len(debts), "referenceDebt": sorted(debts)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--base")
    parser.add_argument("--head")
    parser.add_argument("--comparison", choices=("merge-base", "direct"), default="merge-base")
    parser.add_argument("--inventory", action="store_true")
    args = parser.parse_args(argv)
    try:
        repo = args.repo.resolve()
        if args.inventory:
            head = args.head or git(repo, "rev-parse", "HEAD").decode("ascii").strip()
            receipt = inventory(repo, head)
        else:
            if not args.base or not args.head:
                raise ValueError("--base and --head are required")
            receipt = assess(repo, args.base, args.head, comparison=args.comparison)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({"passed": False, "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    return 0 if args.inventory or receipt["passed"] else 2


if __name__ == "__main__":
    sys.exit(main())
