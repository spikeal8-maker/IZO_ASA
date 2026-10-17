"""Select the existing Windows job only when the changed scope needs it.

Unknown paths are application changes. This routing is not a merge permission.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from tools.file_hygiene_git import GitTree, changes, comparison_base

PORTABLE_EXACT = {
    "tools/file_hygiene.py", "tools/file_hygiene_git.py", "tools/file_hygiene_markdown.py",
    "tools/file_hygiene_reviews.py", "tools/file_hygiene_requirements.txt", "tools/ci_scope.py",
    "tools/test_file_hygiene.py", "tools/test_file_hygiene_regressions.py",
    "tools/test_file_hygiene_markdown.py", "tools/test_file_hygiene_policy.py",
    "tools/test_ci_scope.py", "tools/test_source_alignment.py",
    ".github/workflows/file-hygiene.yml",
}


TOOLING_INSTALL_STEP = '      - name: Install file hygiene tooling\n        run: |\n          python -m pip install --only-binary=:all: --require-hashes -r tools/file_hygiene_requirements.txt\n\n'


def application_body(source: str) -> str | None:
    """Ignore only the exact hash-pinned tooling install, never arbitrary step edits."""
    if source.count(TOOLING_INSTALL_STEP) > 1:
        return None
    parts = source.replace(TOOLING_INSTALL_STEP, "").split("    steps:\n", 1)
    return parts[1] if len(parts) == 2 else None


def portable(path: str) -> bool:
    return (path.endswith(".md") or (path.startswith("tasks/") and path.endswith(".toml"))
            or path in PORTABLE_EXACT)


def route(repo: Path, base: str, head: str, comparison: str = "merge-base") -> dict:
    actual_base = comparison_base(repo, base, head, comparison)
    before, after = GitTree(repo, actual_base), GitTree(repo, head)
    changed = changes(repo, actual_base, head)
    paths = sorted({p for item in changed for p in (item.path, item.previous) if p})
    required = []
    for path in paths:
        if portable(path):
            continue
        if path == ".github/workflows/ci.yml" and path in before.files and path in after.files:
            # Preserve every existing application step; tooling installation is shared.
            old = application_body(before.read(path).decode("utf-8"))
            new = application_body(after.read(path).decode("utf-8"))
            if old is not None and old == new:
                continue
        required.append(path)
    return {"requestedBase": base, "base": actual_base, "head": head,
            "comparison": comparison, "paths": paths, "applicationRequired": bool(required),
            "applicationPaths": required}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--comparison", choices=("merge-base", "direct"), default="merge-base")
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    args = parser.parse_args()
    result = route(args.repo, args.base, args.head, args.comparison)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as handle:
            handle.write("application_required=" + str(result["applicationRequired"]).lower() + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
