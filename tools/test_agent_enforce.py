from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tools.agent_system.enforce import (
    Change,
    Evidence,
    EnforcementError,
    _ci_manifest,
    _ensure_commit,
    _is_high_impact,
    _is_production,
    _path,
    collect_evidence,
    run_ci,
    run_local,
    validate,
)
from tools.agent_system.package import AgentPackageError, TaskManifest, render_manifest, start


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(repo), *args], text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout.strip()
def _repo(tmp_path: Path) -> tuple[Path, str]:
    remote = tmp_path / "remote.git"
    repo = tmp_path / "control"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    subprocess.run(["git", "init", "-b", "main", str(repo)], check=True, capture_output=True)
    _git(repo, "config", "user.email", "enforce@example.invalid")
    _git(repo, "config", "user.name", "Enforce Test")
    (repo / ".gitignore").write_text(".runtime/\n", encoding="utf-8")
    (repo / "src").mkdir()
    (repo / "src" / "a.txt").write_text("a\n", encoding="utf-8")
    (repo / "src" / "delete.txt").write_text("delete\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "initial")
    _git(repo, "remote", "add", "origin", str(remote))
    _git(repo, "push", "-u", "origin", "main")
    _git(repo, "fetch", "origin", "main")
    return repo, _git(repo, "rev-parse", "HEAD")


def _manifest(*, package_id: str = "PKG-ENFORCE", base: str = "a" * 40,
              declared: tuple[str, ...] = ("src/change.txt",),
              allowed: tuple[str, ...] = (), forbidden: tuple[str, ...] = ("secret/**",),
              max_files: int = 0, max_lines: int = 1000) -> TaskManifest:
    return TaskManifest(
        1, package_id, base, "goal", "outcome", "before", "after", ("none",),
        "test-domain", "standard", "architecture", declared, allowed, forbidden, (),
        max_files, max_lines, ("pass",), ("tests",), ("test",), ("bounded",),
        ("deploy", "direct-main"), "revert test package",
    )
def _evidence(*paths: str, lines: int = 0) -> Evidence:
    return Evidence(tuple(Change("M", (path,)) for path in paths), tuple(paths), lines, (), ())


def _write_candidate(repo: Path, manifest: TaskManifest, *paths: str) -> None:
    tasks = repo / "tasks"
    tasks.mkdir(exist_ok=True)
    (tasks / f"{manifest.id}.toml").write_text(render_manifest(manifest), encoding="utf-8")
    for item in paths:
        path = repo / item
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("change\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "candidate")


def test_scope_forbidden_generated_and_high_impact_rules(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    manifest = _manifest(
        declared=("src/ok.txt", ".github/workflows/ci.yml"),
        allowed=("src/**", ".github/**", "docs/generated/**"),
    )
    assert validate(manifest, _evidence("src/ok.txt", lines=1), repo) == []
    assert validate(manifest, _evidence("other.txt"), repo)[0]["code"] == "UNDECLARED_PATH"
    assert validate(manifest, _evidence("secret/key.txt"), repo)[0]["code"] == "FORBIDDEN_PATH"
    assert validate(manifest, _evidence("docs/generated/map.md"), repo)[0]["code"] == "GENERATED_DRIFT"
    assert validate(manifest, _evidence(".github/workflows/other.yml"), repo)[0]["code"] == "HIGH_IMPACT_CHANGE_UNDECLARED"
    assert validate(manifest, _evidence(".github/workflows/ci.yml"), repo) == []
def test_file_and_line_budgets_fail_only_above_boundary(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    manifest = _manifest(allowed=("frontend/src/**",), max_files=1, max_lines=5)
    one = _evidence("frontend/src/A.tsx", lines=5)
    assert not any(item["code"] in {"FILE_BUDGET_EXCEEDED", "LOC_BUDGET_EXCEEDED"} for item in validate(manifest, one, repo))
    two = _evidence("frontend/src/A.tsx", "frontend/src/B.tsx", lines=6)
    codes = {item["code"] for item in validate(manifest, two, repo)}
    assert {"FILE_BUDGET_EXCEEDED", "LOC_BUDGET_EXCEEDED"} <= codes


def test_rename_requires_old_and_new_but_copy_is_destination_write(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    manifest = _manifest(declared=("src/new.txt",))
    renamed = Evidence((Change("R100", ("src/old.txt", "src/new.txt")),),
                       ("src/old.txt", "src/new.txt"), 0, (), ())
    findings = validate(manifest, renamed, repo)
    assert {item.get("path") for item in findings if item["code"] == "UNDECLARED_PATH"} == {"src/old.txt"}
    copied = Evidence((Change("C100", ("src/new.txt",)),), ("src/new.txt",), 0, (), ())
    assert validate(manifest, copied, repo) == []


def test_classifiers_and_windows_path_normalization() -> None:
    assert _is_production("backend/main.py")
    assert _is_production("backend/app/service.py")
    assert not _is_production("backend/test_api.py")
    assert _is_production("frontend/src/App.tsx")
    assert not _is_production("frontend/e2e-ui.mjs")
    assert _is_high_impact("frontend/package-lock.json")
    assert _is_high_impact(".github/workflows/ci.yml")
    assert _is_high_impact("backend/migrations/001.py")
    assert _is_high_impact("CLAUDE.md")
    assert _is_high_impact("start-public.bat")
    assert not _is_high_impact("README.md")
    assert _path(r"tools\agent_system\enforce.py") == "tools/agent_system/enforce.py"
def test_collect_local_evidence_includes_rename_delete_untracked_and_binary(tmp_path: Path) -> None:
    repo, base = _repo(tmp_path)
    _git(repo, "mv", "src/a.txt", "src/b.txt")
    (repo / "src" / "delete.txt").unlink()
    (repo / "src" / "new.txt").write_text("one\ntwo\n", encoding="utf-8")
    (repo / "src" / "blob.bin").write_bytes(b"abc\x00def")
    evidence = collect_evidence(repo, base, ci=False)
    assert {"src/a.txt", "src/b.txt", "src/delete.txt", "src/new.txt", "src/blob.bin"} <= set(evidence.paths)
    assert {"src/new.txt", "src/blob.bin"} <= set(evidence.untracked_paths)
    assert "src/blob.bin" in evidence.binary_paths
    assert evidence.changed_lines >= 3


def test_ci_mode_resolves_one_manifest_without_runtime_registry(tmp_path: Path) -> None:
    repo, base = _repo(tmp_path)
    manifest = _manifest(base=base)
    _write_candidate(repo, manifest, "src/change.txt")
    assert not (repo / ".runtime").exists()
    assert run_ci(repo, base) == 0


def test_rename_line_budget_uses_git_rename_detection(tmp_path: Path) -> None:
    repo, base = _repo(tmp_path)
    _git(repo, "mv", "src/a.txt", "src/b.txt")
    evidence = collect_evidence(repo, base, ci=False)
    assert evidence.changed_lines == 0


def test_generated_lines_are_excluded_from_changed_line_budget(tmp_path: Path) -> None:
    repo, base = _repo(tmp_path)
    path = repo / "docs" / "generated" / "map.md"
    path.parent.mkdir(parents=True)
    path.write_text("one\ntwo\n", encoding="utf-8")
    evidence = collect_evidence(repo, base, ci=False)
    assert "docs/generated/map.md" in evidence.paths
    assert evidence.changed_lines == 0


def test_undeclared_path_reports_scope_expansion_guidance(tmp_path: Path, capsys) -> None:
    repo, base = _repo(tmp_path)
    manifest = _manifest(base=base)
    _write_candidate(repo, manifest, "src/change.txt", "src/extra.txt")
    assert run_ci(repo, base) == 2
    error = capsys.readouterr().err
    assert "SCOPE_EXPANSION_REQUIRED" in error
    assert "src/extra.txt" in error


def test_ci_rejects_manifest_target_drift(tmp_path: Path) -> None:
    repo, base = _repo(tmp_path)
    manifest = _manifest(base="0" * 40)
    _write_candidate(repo, manifest, "src/change.txt")
    with pytest.raises(EnforcementError, match="BASE_SHA_TARGET_DRIFT") as exc:
        _ci_manifest(repo, base)
    assert exc.value.code == "BASE_SHA_TARGET_DRIFT"
def test_ci_rejects_zero_and_multiple_current_manifests(tmp_path: Path) -> None:
    repo, base = _repo(tmp_path)
    (repo / "src" / "plain.txt").write_text("x\n", encoding="utf-8")
    _git(repo, "add", "."); _git(repo, "commit", "-m", "no manifest")
    with pytest.raises(EnforcementError, match="PACKAGE_MANIFEST_UNRESOLVED"):
        _ci_manifest(repo, base)
    for package_id in ("PKG-ONE", "PKG-TWO"):
        manifest = _manifest(package_id=package_id, base=base)
        tasks = repo / "tasks"; tasks.mkdir(exist_ok=True)
        (tasks / f"{package_id}.toml").write_text(render_manifest(manifest), encoding="utf-8")
    _git(repo, "add", "."); _git(repo, "commit", "-m", "two manifests")
    with pytest.raises(EnforcementError, match="PACKAGE_MANIFEST_UNRESOLVED"):
        _ci_manifest(repo, base)


def test_historical_unchanged_manifest_is_not_current_candidate(tmp_path: Path) -> None:
    repo, _base = _repo(tmp_path)
    tasks = repo / "tasks"; tasks.mkdir(exist_ok=True)
    historical = _manifest(package_id="PKG-HISTORY", base="0" * 40)
    (tasks / "PKG-HISTORY.toml").write_text(render_manifest(historical), encoding="utf-8")
    _git(repo, "add", "."); _git(repo, "commit", "-m", "historical manifest")
    _git(repo, "push", "origin", "main")
    base = _git(repo, "rev-parse", "HEAD")
    current = _manifest(package_id="PKG-CURRENT", base=base)
    _write_candidate(repo, current, "src/change.txt")
    manifest, _evidence_value = _ci_manifest(repo, base)
    assert manifest.id == "PKG-CURRENT"


def test_local_mode_reuses_package_ownership_and_token(tmp_path: Path) -> None:
    repo, base = _repo(tmp_path)
    manifest = _manifest(base=base)
    draft = tmp_path / "draft.toml"
    draft.write_text(render_manifest(manifest), encoding="utf-8")
    worktree = tmp_path / "worktree"
    assert start(repo, draft, str(worktree)) == 0
    path = worktree / "src" / "change.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("bounded\n", encoding="utf-8")
    assert run_local(worktree) == 0
    (worktree / ".runtime" / "agent" / "ownership.json").unlink()
    with pytest.raises(Exception):
        run_local(worktree)
def test_dependency_change_requires_exact_declared_intent(tmp_path: Path) -> None:
    repo = tmp_path / "repo"; repo.mkdir()
    broad = _manifest(allowed=("frontend/**",), declared=())
    findings = validate(broad, _evidence("frontend/package.json"), repo)
    assert any(item["code"] == "HIGH_IMPACT_CHANGE_UNDECLARED" for item in findings)
    exact = _manifest(declared=("frontend/package.json",))
    assert validate(exact, _evidence("frontend/package.json"), repo) == []


def test_exact_base_fetch_is_bounded_and_non_ancestor_fails(tmp_path: Path) -> None:
    repo, _base = _repo(tmp_path)
    remote = Path(_git(repo, "remote", "get-url", "origin"))
    writer = tmp_path / "writer"
    subprocess.run(["git", "clone", "-b", "main", str(remote), str(writer)], check=True, capture_output=True)
    _git(writer, "config", "user.email", "writer@example.invalid")
    _git(writer, "config", "user.name", "Writer")
    (writer / "remote.txt").write_text("remote\n", encoding="utf-8")
    _git(writer, "add", "."); _git(writer, "commit", "-m", "remote")
    remote_sha = _git(writer, "rev-parse", "HEAD")
    _git(writer, "push", "origin", "main")
    missing = subprocess.run(["git", "-C", str(repo), "cat-file", "-e", f"{remote_sha}^{{commit}}"], capture_output=True)
    assert missing.returncode != 0
    _ensure_commit(repo, remote_sha, fetch_missing=True)
    with pytest.raises(EnforcementError, match="BASE_SHA_NOT_ANCESTOR"):
        _ci_manifest(repo, remote_sha)


def test_missing_base_fails_without_substitution(tmp_path: Path) -> None:
    repo, _base = _repo(tmp_path)
    with pytest.raises(EnforcementError, match="BASE_SHA_UNAVAILABLE"):
        collect_evidence(repo, "f" * 40, ci=False)


def test_untracked_symlink_escape_fails_before_file_read(tmp_path: Path) -> None:
    repo, base = _repo(tmp_path)
    outside = tmp_path / "outside-untracked.txt"; outside.write_text("secret\n", encoding="utf-8")
    link = repo / "outside-link.txt"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlink creation unavailable on this Windows runner")
    with pytest.raises(EnforcementError, match="PATH_ESCAPE"):
        collect_evidence(repo, base, ci=False)


def test_symlink_escape_fails_safe_when_supported(tmp_path: Path) -> None:
    repo = tmp_path / "repo"; repo.mkdir()
    outside = tmp_path / "outside.txt"; outside.write_text("x\n", encoding="utf-8")
    link = repo / "escape.txt"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlink creation unavailable on this Windows runner")
    manifest = _manifest(declared=("escape.txt",))
    findings = validate(manifest, _evidence("escape.txt"), repo)
    assert any(item["code"] == "PATH_ESCAPE" for item in findings)
