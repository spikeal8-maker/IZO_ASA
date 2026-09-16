from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from tools.agent_system.package import (
    AgentPackageError,
    finish,
    manifest_fingerprint,
    parse_manifest,
    render_manifest,
    scope_add,
    scopes_overlap,
    start,
    status,
)
from tools.agent_system.registry import (
    atomic_write_bytes,
    load_registry,
    registry_path,
    token_hash,
)

ROOT = Path(__file__).resolve().parents[1]
POWERSHELL = Path(r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe")
LOCK_HELPER = ROOT / "tools" / "repository-operation-lock.ps1"


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout.strip()


def _make_repo(tmp_path: Path) -> tuple[Path, str]:
    remote = tmp_path / "remote.git"
    repo = tmp_path / "control"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    subprocess.run(["git", "init", "-b", "main", str(repo)], check=True, capture_output=True)
    _git(repo, "config", "user.email", "agent-test@example.invalid")
    _git(repo, "config", "user.name", "Agent Test")
    (repo / ".gitignore").write_text(".runtime/\n", encoding="utf-8")
    (repo / "README.md").write_text("test\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "initial")
    _git(repo, "remote", "add", "origin", str(remote))
    _git(repo, "push", "-u", "origin", "main")
    _git(repo, "fetch", "origin", "main")
    return repo, _git(repo, "rev-parse", "HEAD")


def _manifest_text(package_id: str, base_sha: str, *, declared: list[str] | None = None, allowed: list[str] | None = None) -> str:
    declared = declared or [f"src/{package_id.lower()}.txt"]
    allowed = allowed or []
    values = {
        "manifestVersion": 1,
        "id": package_id,
        "baseSha": base_sha,
        "goal": "Test package lifecycle.",
        "userOutcome": "One writer owns one bounded scope.",
        "beforeScenario": "No shared package ownership exists.",
        "afterScenario": "Shared ownership exists.",
        "nonGoals": ["product behavior"],
        "domain": "test-domain",
        "riskClass": "standard",
        "changeClass": "architecture",
        "declaredFiles": declared,
        "allowedPatterns": allowed,
        "forbiddenPatterns": ["secrets/**"],
        "protectedFilesTouched": [],
        "maxProductionFiles": 0,
        "maxChangedLines": 100,
        "acceptance": ["tests pass"],
        "requiredEvidence": ["focused tests"],
        "targetedTests": ["tools/test_agent_package.py"],
        "fileGrowthExpectations": ["bounded"],
        "forbiddenOperations": ["deploy", "direct-main"],
        "rollbackBoundary": "Remove test package state.",
    }
    lines: list[str] = []
    for key in ("manifestVersion", "id", "baseSha", "goal", "userOutcome", "beforeScenario", "afterScenario"):
        value = values[key]
        lines.append(f"{key} = {json.dumps(value)}" if isinstance(value, str) else f"{key} = {value}")
    for key in ("nonGoals", "declaredFiles", "allowedPatterns", "forbiddenPatterns", "protectedFilesTouched"):
        rendered = ", ".join(json.dumps(item) for item in values[key])
        lines.append(f"{key} = [{rendered}]")
    for key in ("domain", "riskClass", "changeClass"):
        lines.append(f"{key} = {json.dumps(values[key])}")
    lines.extend(["maxProductionFiles = 0", "maxChangedLines = 100"])
    for key in ("acceptance", "requiredEvidence", "targetedTests", "fileGrowthExpectations", "forbiddenOperations"):
        rendered = ", ".join(json.dumps(item) for item in values[key])
        lines.append(f"{key} = [{rendered}]")
    lines.append(f"rollbackBoundary = {json.dumps(values['rollbackBoundary'])}")
    return "\n".join(lines) + "\n"


def _draft(tmp_path: Path, package_id: str, base_sha: str, *, declared: list[str] | None = None, allowed: list[str] | None = None) -> Path:
    path = tmp_path / f"{package_id}.draft.toml"
    path.write_text(_manifest_text(package_id, base_sha, declared=declared, allowed=allowed), encoding="utf-8")
    return path


def _ownership(worktree: Path) -> dict[str, str]:
    return json.loads((worktree / ".runtime" / "agent" / "ownership.json").read_text(encoding="utf-8"))


def test_manifest_roundtrip_and_strict_validation(tmp_path: Path) -> None:
    _, base = _make_repo(tmp_path / "repo with spaces")
    draft = _draft(tmp_path, "PKG-ONE", base, declared=[r"frontend\src\one.tsx"])
    manifest = parse_manifest(draft)
    assert manifest.declared_files == ("frontend/src/one.tsx",)
    canonical = tmp_path / "tasks" / "PKG-ONE.toml"
    canonical.parent.mkdir()
    canonical.write_text(render_manifest(manifest), encoding="utf-8")
    parsed = parse_manifest(canonical)
    assert parsed == manifest
    assert manifest_fingerprint(parsed) == manifest_fingerprint(manifest)

    bad = tmp_path / "bad.toml"
    bad.write_text(draft.read_text(encoding="utf-8") + "unexpected = true\n", encoding="utf-8")
    with pytest.raises(AgentPackageError, match="MANIFEST_UNKNOWN_KEYS"):
        parse_manifest(bad)

    traversal = tmp_path / "traversal.toml"
    traversal.write_text(_manifest_text("PKG-TWO", base, declared=["../outside.txt"]), encoding="utf-8")
    with pytest.raises(AgentPackageError, match="MANIFEST_PATH_INVALID"):
        parse_manifest(traversal)

    blocked = tmp_path / "blocked.toml"
    blocked.write_text(_manifest_text("PKG-THREE", base, declared=["backend/.venv/pyvenv.cfg"]), encoding="utf-8")
    with pytest.raises(AgentPackageError, match="MANIFEST_PATH_FORBIDDEN"):
        parse_manifest(blocked)


def test_manifest_filename_and_overlap_semantics(tmp_path: Path) -> None:
    _, base = _make_repo(tmp_path / "repo")
    tasks = tmp_path / "tasks"
    tasks.mkdir()
    wrong = tasks / "WRONG.toml"
    wrong.write_text(_manifest_text("PKG-ONE", base), encoding="utf-8")
    with pytest.raises(AgentPackageError, match="MANIFEST_FILENAME_MISMATCH"):
        parse_manifest(wrong)

    assert scopes_overlap("frontend/src/a.tsx", "frontend/src/a.tsx")
    assert scopes_overlap("frontend/src/**", "frontend/src/a.tsx")
    assert scopes_overlap("frontend/**", "frontend/src/**")
    assert not scopes_overlap("frontend/src/a.tsx", "frontend/src/b.tsx")
    assert not scopes_overlap("frontend/**", "backend/**")


def test_start_creates_canonical_manifest_and_shared_registry(tmp_path: Path) -> None:
    repo, base = _make_repo(tmp_path)
    control_status = _git(repo, "status", "--porcelain")
    draft = _draft(tmp_path, "PKG-ONE", base)
    worktree = tmp_path / "worktrees" / "pkg-one"
    assert start(repo, draft, str(worktree)) == 0

    assert _git(repo, "status", "--porcelain") == control_status
    canonical = worktree / "tasks" / "PKG-ONE.toml"
    assert canonical.is_file()
    manifest = parse_manifest(canonical)
    registry = load_registry(worktree)
    entry = registry["entries"][0]
    assert entry["packageId"] == "PKG-ONE"
    assert Path(entry["worktreePath"]).resolve() == worktree.resolve()
    assert entry["manifestFingerprint"] == manifest_fingerprint(manifest)
    assert registry_path(repo) == registry_path(worktree)

    ownership = _ownership(worktree)
    raw_registry = registry_path(repo).read_text(encoding="utf-8")
    assert ownership["token"] not in raw_registry
    assert entry["ownershipTokenHash"] == token_hash(ownership["token"])


def test_start_rejects_overlapping_scope_and_allows_non_overlap(tmp_path: Path) -> None:
    repo, base = _make_repo(tmp_path)
    first = _draft(tmp_path, "PKG-ONE", base, allowed=["frontend/src/**"])
    start(repo, first, str(tmp_path / "wt-one"))

    forbidden = _draft(tmp_path, "PKG-BLOCKED", base, declared=["secrets/token.txt"])
    with pytest.raises(AgentPackageError, match="MANIFEST_SCOPE_FORBIDDEN"):
        start(repo, forbidden, str(tmp_path / "wt-blocked"))

    overlap = _draft(tmp_path, "PKG-TWO", base, declared=["frontend/src/button.tsx"])
    with pytest.raises(AgentPackageError, match="SCOPE_OVERLAP"):
        start(repo, overlap, str(tmp_path / "wt-two"))

    safe = _draft(tmp_path, "PKG-THREE", base, declared=["backend/app/service.py"])
    start(repo, safe, str(tmp_path / "wt-three"))
    assert len([entry for entry in load_registry(repo)["entries"] if entry["state"] == "active"]) == 2


def test_scope_add_updates_manifest_and_registry_and_collision_is_atomic(tmp_path: Path) -> None:
    repo, base = _make_repo(tmp_path)
    first_wt = tmp_path / "wt-one"
    second_wt = tmp_path / "wt-two"
    start(repo, _draft(tmp_path, "PKG-ONE", base), str(first_wt))
    start(repo, _draft(tmp_path, "PKG-TWO", base, allowed=["frontend/src/**"]), str(second_wt))

    canonical = first_wt / "tasks" / "PKG-ONE.toml"
    scope_add(first_wt, "docs/context/**", "Needed after bounded discovery")
    updated = parse_manifest(canonical)
    assert "docs/context/**" in updated.allowed_patterns
    assert updated.scope_expansions[-1].reason == "Needed after bounded discovery"
    entry = next(entry for entry in load_registry(first_wt)["entries"] if entry["packageId"] == "PKG-ONE")
    assert entry["manifestFingerprint"] == manifest_fingerprint(updated)
    assert "docs/context/**" in entry["writeOwnership"]

    before_manifest = canonical.read_bytes()
    before_registry = registry_path(first_wt).read_bytes()
    with pytest.raises(AgentPackageError, match="SCOPE_OVERLAP"):
        scope_add(first_wt, "frontend/src/new.tsx", "Would collide")
    assert canonical.read_bytes() == before_manifest
    assert registry_path(first_wt).read_bytes() == before_registry


def test_atomic_write_failure_preserves_previous_bytes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "registry.json"
    target.write_bytes(b"old\n")

    def fail_replace(_src: Path | str, _dst: Path | str) -> None:
        raise OSError("synthetic replace failure")

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(OSError, match="synthetic replace failure"):
        atomic_write_bytes(target, b"new\n")
    assert target.read_bytes() == b"old\n"
    assert not list(tmp_path.glob(".registry.json.*.tmp"))


@pytest.mark.skipif(not POWERSHELL.exists(), reason="common-repository lock contract is exercised on Windows CI")
def test_common_repository_lock_contends_across_sibling_worktrees(tmp_path: Path) -> None:
    repo, base = _make_repo(tmp_path)
    first = tmp_path / "first"
    second = tmp_path / "second"
    _git(repo, "worktree", "add", "-b", "first", str(first), base)
    _git(repo, "worktree", "add", "-b", "second", str(second), base)
    token_file = tmp_path / "lock.token"
    acquire = subprocess.run(
        [str(POWERSHELL), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(LOCK_HELPER), "-Action", "acquire", "-StorageScope", "common-repository", "-RepoRoot", str(first), "-Kind", "agent-test", "-TokenOutFile", str(token_file)],
        text=True, capture_output=True, timeout=60, check=False,
    )
    assert acquire.returncode == 0, acquire.stderr
    try:
        competing = subprocess.run(
            [str(POWERSHELL), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(LOCK_HELPER), "-Action", "acquire", "-StorageScope", "common-repository", "-RepoRoot", str(second), "-Kind", "agent-test", "-TokenOutFile", str(tmp_path / "other.token")],
            text=True, capture_output=True, timeout=60, check=False,
        )
        assert competing.returncode != 0
        assert "REPOSITORY_OPERATION_LOCK_BUSY" in competing.stderr
    finally:
        release = subprocess.run(
            [str(POWERSHELL), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(LOCK_HELPER), "-Action", "release", "-StorageScope", "common-repository", "-RepoRoot", str(first), "-Kind", "agent-test", "-Token", token_file.read_text(encoding="ascii")],
            text=True, capture_output=True, timeout=60, check=False,
        )
        assert release.returncode == 0, release.stderr


def test_finish_rejects_foreign_token_and_dirty_worktree_keeps_ownership(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo, base = _make_repo(tmp_path)
    worktree = tmp_path / "wt"
    start(repo, _draft(tmp_path, "PKG-ONE", base), str(worktree))
    ownership_file = worktree / ".runtime" / "agent" / "ownership.json"
    original = json.loads(ownership_file.read_text(encoding="utf-8"))
    ownership_file.write_text(json.dumps({**original, "token": "foreign"}), encoding="utf-8")
    assert status(worktree) == 0
    assert "STALE_OR_FOREIGN_OWNERSHIP" in capsys.readouterr().out
    with pytest.raises(AgentPackageError, match="OWNERSHIP_MISMATCH"):
        finish(worktree)

    ownership_file.write_text(json.dumps(original), encoding="utf-8")
    (worktree / "dirty.txt").write_text("dirty", encoding="utf-8")
    with pytest.raises(AgentPackageError, match="PACKAGE_DIRTY_OWNERSHIP_RETAINED"):
        finish(worktree)
    entry = load_registry(worktree)["entries"][0]
    assert entry["state"] == "blocked-dirty"
    assert ownership_file.exists()


def test_parallel_overlapping_start_has_one_winner(tmp_path: Path) -> None:
    repo, base = _make_repo(tmp_path)
    first = _draft(tmp_path, "PKG-ONE", base, allowed=["shared/**"])
    second = _draft(tmp_path, "PKG-TWO", base, allowed=["shared/**"])
    barrier = threading.Barrier(2)
    results: list[str] = []

    def run(draft: Path, target: Path) -> None:
        barrier.wait()
        try:
            start(repo, draft, str(target))
            results.append("ok")
        except (AgentPackageError, RuntimeError) as exc:
            results.append(str(exc))

    threads = [
        threading.Thread(target=run, args=(first, tmp_path / "wt-one")),
        threading.Thread(target=run, args=(second, tmp_path / "wt-two")),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=120)
    assert not any(thread.is_alive() for thread in threads)
    assert results.count("ok") == 1, results
    assert any("SCOPE_OVERLAP" in result or "REPOSITORY_OPERATION_LOCK_BUSY" in result for result in results if result != "ok")


def test_size_review_roundtrip_and_duplicate_paths_fail(tmp_path: Path) -> None:
    _repo, base = _make_repo(tmp_path / "repo")
    review = '\n[[sizeReviews]]\npath = "tools/large.py"\nrationale = "Cohesive temporary module with decomposition follow-up."\n'
    draft = tmp_path / "review.toml"
    draft.write_text(_manifest_text("PKG-SIZE", base) + review, encoding="utf-8")
    manifest = parse_manifest(draft)
    assert len(manifest.size_reviews) == 1
    assert manifest.size_reviews[0].path == "tools/large.py"
    canonical = tmp_path / "tasks" / "PKG-SIZE.toml"
    canonical.parent.mkdir()
    canonical.write_text(render_manifest(manifest), encoding="utf-8")
    assert parse_manifest(canonical) == manifest
    duplicate = tmp_path / "duplicate.toml"
    duplicate.write_text(_manifest_text("PKG-SIZE", base) + review + review, encoding="utf-8")
    with pytest.raises(AgentPackageError, match="MANIFEST_SIZE_REVIEW_INVALID"):
        parse_manifest(duplicate)
