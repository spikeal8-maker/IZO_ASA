"""Use the existing TaskManifest parser; never implement a weaker approval schema."""
from __future__ import annotations

import tempfile
from pathlib import Path

from tools.file_hygiene_git import Change, GitTree


def read_reviews(tree: GitTree, base: str, changes: list[Change]) -> tuple[dict[str, str], list[dict]]:
    from tools.agent_system.package import AgentPackageError, parse_manifest

    paths = [c.path for c in changes if c.path.startswith("tasks/")
             and c.path.endswith(".toml") and not c.status.startswith("D")]
    candidates, errors = [], []
    with tempfile.TemporaryDirectory(prefix="izo-manifest-check-") as folder:
        for path in paths:
            local = Path(folder) / "tasks" / Path(path).name
            local.parent.mkdir(exist_ok=True)
            local.write_bytes(tree.read(path))
            try:
                item = parse_manifest(local)
            except AgentPackageError:
                errors.append({"code": "MANIFEST_INVALID", "path": path})
                continue
            if item.base_sha == base:
                candidates.append((path, item))
            elif item.size_reviews:
                errors.append({"code": "SIZE_REVIEW_BASE_MISMATCH", "path": path})
    if len(candidates) > 1:
        from tools.agent_system.enforce import EnforcementError, _ci_source_branch, _git_text
        selected = []
        try:
            if tree.revision == _git_text(tree.repo, "rev-parse", "HEAD"):
                branch = _ci_source_branch(tree.repo)
                selected = [(path, item) for path, item in candidates
                            if path == f"tasks/{item.id}.toml" and branch == f"agent/{item.id.lower()}"]
        except EnforcementError:
            pass
        candidates = selected
        if len(candidates) != 1:
            errors.append({"code": "AMBIGUOUS_CURRENT_MANIFEST"})
    if len(candidates) != 1 or errors:
        return {}, errors
    item = candidates[0][1]
    reviews = {}
    for review in item.size_reviews:
        declared = review.path in item.declared_files or any(
            review.path.startswith(pattern[:-2]) for pattern in item.allowed_patterns if pattern.endswith("/**"))
        forbidden = any(review.path == pattern or (pattern.endswith("/**") and
                        review.path.startswith(pattern[:-2])) for pattern in item.forbidden_patterns)
        if not declared or forbidden:
            errors.append({"code": "SIZE_REVIEW_OUTSIDE_SCOPE", "path": review.path})
        else:
            reviews[review.path] = review.rationale
    return reviews, errors
