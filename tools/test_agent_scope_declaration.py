"""Exact scope declaration retains generated-file and ownership guards."""
from __future__ import annotations

from pathlib import Path

import pytest

from tools.agent_system.package import (
    AgentPackageError, manifest_fingerprint, parse_manifest, scope_add, start,
)
from tools.agent_system.registry import load_registry, registry_path
from tools.test_agent_package import _draft, _make_repo


def test_scope_declaration_preserves_generated_enforcement_and_atomic_guards(tmp_path: Path) -> None:
    from tools.agent_system.enforce import Evidence, validate
    from tools.agent_system.package import main

    repo, base = _make_repo(tmp_path)
    worktree = tmp_path / "wt-declare"
    start(repo, _draft(tmp_path, "PKG-DECLARE", base, allowed=["docs/generated/**"]), str(worktree))
    start(repo, _draft(tmp_path, "PKG-OTHER", base, allowed=["frontend/**"]), str(tmp_path / "other"))
    canonical = worktree / "tasks" / "PKG-DECLARE.toml"
    path = "docs/generated/context-index.json"
    evidence = Evidence((), (path,), 1, (), ())
    assert {row["code"] for row in validate(parse_manifest(canonical), evidence, worktree)} == {"GENERATED_DRIFT"}

    before_manifest = canonical.read_bytes()
    before_registry = registry_path(worktree).read_bytes()
    for blocked, error in (("docs/generated/**", "MANIFEST_PATH_INVALID"),
                           ("secrets/no.txt", "MANIFEST_PATH_FORBIDDEN|FORBIDDEN_SCOPE"),
                           ("frontend/new.tsx", "SCOPE_OVERLAP")):
        with pytest.raises(AgentPackageError, match=error):
            scope_add(worktree, blocked, "Exact declaration must retain guards", declare=True)
        assert canonical.read_bytes() == before_manifest
        assert registry_path(worktree).read_bytes() == before_registry

    assert main(["--repo-root", str(worktree), "scope-add", "--path", path,
                 "--reason", "Declare the generated output explicitly", "--declare"]) == 0
    updated = parse_manifest(canonical)
    assert path in updated.declared_files
    assert validate(updated, evidence, worktree) == []
    entry = next(row for row in load_registry(worktree)["entries"] if row["packageId"] == updated.id)
    assert entry["manifestFingerprint"] == manifest_fingerprint(updated)
    assert path in entry["discoveredWriteOwnership"]
    declared_manifest, declared_registry = canonical.read_bytes(), registry_path(worktree).read_bytes()
    scope_add(worktree, path, "Already explicitly declared", declare=True)
    assert canonical.read_bytes() == declared_manifest
    assert registry_path(worktree).read_bytes() == declared_registry
