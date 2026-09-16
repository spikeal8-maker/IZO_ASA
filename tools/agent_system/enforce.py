from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .package import (
    AgentPackageError,
    TaskManifest,
    _assert_owner,
    _matches,
    normalize_scope,
    parse_manifest,
    scope_items,
)
from .registry import load_registry, registry_lock
from tools.architecture_size_contract import evaluate_size_delta, measurement_paths

SHA_RE = re.compile(r"^[0-9a-f]{40}$")
MANIFEST_RE = re.compile(r"^tasks/[A-Z0-9][A-Z0-9-]{2,79}\.toml$")
GENERATED_PREFIXES = ("docs/generated/",)
GENERATED_EXACT = {"backend/SYMBOL_MAP.md"}
HIGH_IMPACT_EXACT = {
    ".gitignore",
    ".node-version",
    ".python-version",
    "AGENTS.md",
    "AI_START_HERE.md",
    "CLAUDE.md",
    "GEMINI.md",
    "pytest.ini",
}
DEPENDENCY_NAMES = {
    "package.json",
    "package-lock.json",
    "npm-shrinkwrap.json",
    "pyproject.toml",
    "poetry.lock",
    "uv.lock",
    "pdm.lock",
}


class EnforcementError(RuntimeError):
    def __init__(self, code: str, *, path: str = "", detail: str = "") -> None:
        self.code, self.path, self.detail = code, path, detail
        super().__init__(code)


@dataclass(frozen=True)
class Change:
    status: str
    paths: tuple[str, ...]
@dataclass(frozen=True)
class Evidence:
    changes: tuple[Change, ...]
    paths: tuple[str, ...]
    changed_lines: int
    binary_paths: tuple[str, ...]
    untracked_paths: tuple[str, ...]


def _run(repo: Path, *args: str, text: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        text=text,
        capture_output=True,
        check=False,
    )


def _git_text(repo: Path, *args: str) -> str:
    result = _run(repo, *args)
    if result.returncode:
        raise EnforcementError("GIT_EVIDENCE_FAILED", detail=(result.stderr or result.stdout).strip())
    return result.stdout.strip()


def _git_bytes(repo: Path, *args: str) -> bytes:
    result = _run(repo, *args, text=False)
    if result.returncode:
        detail = (result.stderr or result.stdout).decode("utf-8", "replace").strip()
        raise EnforcementError("GIT_EVIDENCE_FAILED", detail=detail)
    return result.stdout


def _ensure_commit(repo: Path, sha: str, *, fetch_missing: bool = False) -> None:
    if not SHA_RE.fullmatch(sha):
        raise EnforcementError("BASE_SHA_UNAVAILABLE", detail="invalid-sha")
    result = _run(repo, "cat-file", "-e", f"{sha}^{{commit}}")
    if result.returncode and fetch_missing:
        fetched = _run(repo, "fetch", "--no-tags", "--depth=1", "origin", sha)
        if not fetched.returncode:
            result = _run(repo, "cat-file", "-e", f"{sha}^{{commit}}")
    if result.returncode:
        raise EnforcementError("BASE_SHA_UNAVAILABLE", detail=sha)


def _path(raw: bytes | str) -> str:
    value = raw.decode("utf-8", "surrogateescape") if isinstance(raw, bytes) else raw
    try:
        return normalize_scope(value, allow_subtree=False)
    except AgentPackageError as exc:
        raise EnforcementError("PATH_INVALID", path=value, detail=str(exc)) from exc


def _diff_tail(base: str, *, ci: bool) -> list[str]:
    return [base, "HEAD", "--"] if ci else [base, "--"]


def _changes(repo: Path, base: str, *, ci: bool) -> list[Change]:
    raw = _git_bytes(repo, "diff", "--name-status", "-z", "-M", "-C", *_diff_tail(base, ci=ci))
    tokens = [item for item in raw.split(b"\0") if item]
    result: list[Change] = []
    index = 0
    while index < len(tokens):
        status = tokens[index].decode("ascii", "replace")
        index += 1
        if status[:1] in {"R", "C"}:
            if index + 1 >= len(tokens):
                raise EnforcementError("GIT_EVIDENCE_FAILED", detail="truncated-rename-copy")
            old_path, new_path = _path(tokens[index]), _path(tokens[index + 1])
            paths = (old_path, new_path) if status.startswith("R") else (new_path,)
            index += 2
        else:
            if index >= len(tokens):
                raise EnforcementError("GIT_EVIDENCE_FAILED", detail="truncated-path")
            paths = (_path(tokens[index]),)
            index += 1
        result.append(Change(status, paths))
    return result


def _numstat(repo: Path, base: str, *, ci: bool) -> tuple[int, set[str]]:
    raw = _git_bytes(repo, "diff", "--numstat", "-M", "-C", *_diff_tail(base, ci=ci))
    total, binaries = 0, set()
    for line in raw.splitlines():
        fields = line.split(b"\t", 2)
        if len(fields) != 3:
            continue
        added, deleted, raw_path = fields
        path = _path(raw_path)
        if added == b"-" or deleted == b"-":
            continue
        if _is_generated(path):
            continue
        try:
            total += int(added) + int(deleted)
        except ValueError as exc:
            raise EnforcementError("GIT_EVIDENCE_FAILED", path=path, detail="invalid-numstat") from exc
    binary_raw = _git_bytes(repo, "diff", "--numstat", "--no-renames", *_diff_tail(base, ci=ci))
    for line in binary_raw.splitlines():
        fields = line.split(b"\t", 2)
        if len(fields) == 3 and (fields[0] == b"-" or fields[1] == b"-"):
            binaries.add(_path(fields[2]))
    return total, binaries


def _untracked(repo: Path) -> list[str]:
    raw = _git_bytes(repo, "ls-files", "--others", "--exclude-standard", "-z")
    return [_path(item) for item in raw.split(b"\0") if item]


def _untracked_lines(repo: Path, path: str) -> tuple[int, bool]:
    if _escapes_repo(repo, path):
        raise EnforcementError("PATH_ESCAPE", path=path)
    data = (repo / Path(*PurePosixPath(path).parts)).read_bytes()
    if b"\0" in data[:8192]:
        return 0, True
    lines = data.count(b"\n") + (1 if data and not data.endswith(b"\n") else 0)
    return lines, False


def collect_evidence(repo: Path, base: str, *, ci: bool) -> Evidence:
    _ensure_commit(repo, base)
    changes = _changes(repo, base, ci=ci)
    changed_lines, binary = _numstat(repo, base, ci=ci)
    untracked: list[str] = []
    if not ci:
        untracked = _untracked(repo)
        for path in untracked:
            lines, is_binary = _untracked_lines(repo, path)
            if not _is_generated(path):
                changed_lines += lines
            if is_binary:
                binary.add(path)
            changes.append(Change("?", (path,)))
    paths = tuple(dict.fromkeys(path for change in changes for path in change.paths))
    return Evidence(
        tuple(changes),
        paths,
        changed_lines,
        tuple(sorted(binary)),
        tuple(untracked),
    )


def _is_generated(path: str) -> bool:
    return path in GENERATED_EXACT or path.startswith(GENERATED_PREFIXES)


def _is_dependency(path: str) -> bool:
    name = PurePosixPath(path).name.lower()
    return name in DEPENDENCY_NAMES or (name.startswith("requirements") and name.endswith(".txt"))


def _is_high_impact(path: str) -> bool:
    pure = PurePosixPath(path)
    lower_parts = tuple(part.lower() for part in pure.parts)
    name = pure.name.lower()
    if path in HIGH_IMPACT_EXACT or path.startswith(".github/workflows/"):
        return True
    if len(pure.parts) == 1 and name.endswith(".bat"):
        return True
    if _is_dependency(path) or path.startswith("architecture/") or path.startswith("ops/"):
        return True
    if "migrations" in lower_parts or "migration" in lower_parts:
        return True
    if name.startswith("migrat") or name in {"schema.sql", "schema.py", ".env.example", "env.example"}:
        return True
    return False


def _is_production(path: str) -> bool:
    pure = PurePosixPath(path)
    name = pure.name.lower()
    if path.startswith("frontend/src/") or path.startswith("frontend/public/"):
        return True
    if path == "frontend/index.html" or path.startswith("backend/static/"):
        return True
    if path == "backend/main.py" or path.startswith("backend/app/"):
        return True
    if path.startswith("backend/") and pure.suffix == ".py":
        return not (name.startswith("test_") or name == "conftest.py")
    return False


def _escapes_repo(repo: Path, path: str) -> bool:
    candidate = repo / Path(*PurePosixPath(path).parts)
    if not candidate.exists() and not candidate.is_symlink():
        return False
    try:
        candidate.resolve().relative_to(repo.resolve())
        return False
    except ValueError:
        return True


def validate(manifest: TaskManifest, evidence: Evidence, repo: Path) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    owned = scope_items(manifest)
    declared = set(manifest.declared_files)
    for path in evidence.paths:
        if _escapes_repo(repo, path):
            findings.append({"code": "PATH_ESCAPE", "path": path})
            continue
        if any(_matches(pattern, path) for pattern in manifest.forbidden_patterns):
            findings.append({"code": "FORBIDDEN_PATH", "path": path})
            continue
        if not any(_matches(pattern, path) for pattern in owned):
            code = "GENERATED_DRIFT" if _is_generated(path) else "UNDECLARED_PATH"
            findings.append({"code": code, "path": path})
            continue
        if _is_generated(path) and path not in declared:
            findings.append({"code": "GENERATED_DRIFT", "path": path})
            continue
        if _is_high_impact(path) and path not in declared:
            findings.append({"code": "HIGH_IMPACT_CHANGE_UNDECLARED", "path": path})
    production = sorted({path for path in evidence.paths if _is_production(path)})
    if len(production) > manifest.max_production_files:
        findings.append({
            "code": "FILE_BUDGET_EXCEEDED",
            "detail": f"actual={len(production)} max={manifest.max_production_files}",
        })
    if evidence.changed_lines > manifest.max_changed_lines:
        findings.append({
            "code": "LOC_BUDGET_EXCEEDED",
            "detail": f"actual={evidence.changed_lines} max={manifest.max_changed_lines}",
        })
    return findings



ARCHITECTURE_CONTRACT = "architecture/contract.json"

def _size_policy_findings(repo: Path, manifest: TaskManifest, evidence: Evidence) -> list[dict[str, str]]:
    base_result = _run(repo, "show", f"{manifest.base_sha}:{ARCHITECTURE_CONTRACT}")
    candidate_contract = repo / ARCHITECTURE_CONTRACT
    if base_result.returncode:
        if candidate_contract.exists():
            raise EnforcementError("ARCHITECTURE_SIZE_CONTRACT_INVALID", path=ARCHITECTURE_CONTRACT, detail="base contract unavailable")
        return []
    try:
        base_policy = json.loads(base_result.stdout)
        candidate_policy = json.loads(candidate_contract.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EnforcementError("ARCHITECTURE_SIZE_CONTRACT_INVALID", path=ARCHITECTURE_CONTRACT, detail=str(exc)) from exc
    changed = set(evidence.paths)
    added = {
        change.paths[-1] for change in evidence.changes
        if change.paths and change.status[:1] in {"A", "C", "?"}
    }
    base_paths, candidate_paths = measurement_paths(base_policy, changed, added)
    base_texts: dict[str, str] = {}
    candidate_texts: dict[str, str] = {}
    for path in sorted(base_paths):
        result = _run(repo, "show", f"{manifest.base_sha}:{path}")
        if result.returncode:
            raise EnforcementError("ARCHITECTURE_SIZE_CONTRACT_INVALID", path=path, detail="base source unavailable")
        base_texts[path] = result.stdout
    for path in sorted(candidate_paths):
        candidate = repo / Path(*PurePosixPath(path).parts)
        if candidate.is_file() and not _escapes_repo(repo, path):
            try:
                candidate_texts[path] = candidate.read_text(encoding="utf-8")
            except UnicodeDecodeError as exc:
                raise EnforcementError("ARCHITECTURE_SIZE_CONTRACT_INVALID", path=path, detail="handwritten source is not UTF-8 text") from exc
    reviews = {item.path: item.rationale for item in manifest.size_reviews}
    return evaluate_size_delta(
        base_policy, candidate_policy, changed_paths=changed, added_paths=added,
        base_texts=base_texts, candidate_texts=candidate_texts,
        change_class=manifest.change_class, size_reviews=reviews,
    )

def _ci_manifest(repo: Path, target_base: str) -> tuple[TaskManifest, Evidence]:
    _ensure_commit(repo, target_base, fetch_missing=True)
    ancestor = _run(repo, "merge-base", "--is-ancestor", target_base, "HEAD")
    if ancestor.returncode:
        raise EnforcementError("BASE_SHA_NOT_ANCESTOR", detail=target_base)
    evidence = collect_evidence(repo, target_base, ci=True)
    candidates = sorted(
        path for path in evidence.paths
        if MANIFEST_RE.fullmatch(path) and (repo / Path(*PurePosixPath(path).parts)).is_file()
    )
    if len(candidates) != 1:
        raise EnforcementError("PACKAGE_MANIFEST_UNRESOLVED", detail=f"candidates={candidates}")
    manifest = parse_manifest(repo / candidates[0])
    if manifest.base_sha != target_base:
        raise EnforcementError(
            "BASE_SHA_TARGET_DRIFT",
            path=candidates[0],
            detail=f"manifest={manifest.base_sha} target={target_base}",
        )
    return manifest, evidence


def _local_manifest(repo: Path) -> tuple[TaskManifest, Evidence]:
    with registry_lock(repo, "agent enforce local"):
        payload = load_registry(repo)
        _ownership, _entry, manifest, _path = _assert_owner(repo, payload)
    _ensure_commit(repo, manifest.base_sha)
    return manifest, collect_evidence(repo, manifest.base_sha, ci=False)


def _receipt(mode: str, repo: Path, manifest: TaskManifest, evidence: Evidence,
             findings: list[dict[str, str]]) -> dict[str, object]:
    production = sorted({path for path in evidence.paths if _is_production(path)})
    scope_expansion = [
        {
            "reason": "UNDECLARED_PATH",
            "observedImpact": item.get("path", ""),
            "proposedPathOrSubtree": item.get("path", ""),
        }
        for item in findings if item.get("code") == "UNDECLARED_PATH"
    ]
    return {
        "mode": mode,
        "packageId": manifest.id,
        "baseSha": manifest.base_sha,
        "headSha": _git_text(repo, "rev-parse", "HEAD"),
        "changedPaths": list(evidence.paths),
        "changedFileCount": len(evidence.paths),
        "productionFiles": production,
        "productionFileCount": len(production),
        "changedLines": evidence.changed_lines,
        "binaryPaths": list(evidence.binary_paths),
        "untrackedPaths": list(evidence.untracked_paths),
        "findings": findings,
        "SCOPE_EXPANSION_REQUIRED": scope_expansion,
    }


def run_local(repo: Path) -> int:
    manifest, evidence = _local_manifest(repo)
    findings = validate(manifest, evidence, repo)
    if not any(item.get("code") == "PATH_ESCAPE" for item in findings):
        findings.extend(_size_policy_findings(repo, manifest, evidence))
    receipt = _receipt("local", repo, manifest, evidence, findings)
    stream = sys.stderr if findings else sys.stdout
    print(("ENFORCE_FAIL " if findings else "ENFORCE_OK ") + json.dumps(receipt, sort_keys=True), file=stream)
    return 2 if findings else 0
def run_ci(repo: Path, target_base: str) -> int:
    manifest, evidence = _ci_manifest(repo, target_base)
    findings = validate(manifest, evidence, repo)
    if not any(item.get("code") == "PATH_ESCAPE" for item in findings):
        findings.extend(_size_policy_findings(repo, manifest, evidence))
    receipt = _receipt("ci", repo, manifest, evidence, findings)
    stream = sys.stderr if findings else sys.stdout
    print(("ENFORCE_FAIL " if findings else "ENFORCE_OK ") + json.dumps(receipt, sort_keys=True), file=stream)
    return 2 if findings else 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agent-enforce")
    parser.add_argument("--repo-root", default=".")
    sub = parser.add_subparsers(dest="mode", required=True)
    sub.add_parser("local")
    ci = sub.add_parser("ci")
    ci.add_argument("--target-base", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    repo = Path(args.repo_root).resolve()
    try:
        return run_local(repo) if args.mode == "local" else run_ci(repo, args.target_base)
    except (EnforcementError, AgentPackageError) as exc:
        code = exc.code if isinstance(exc, EnforcementError) else str(exc).split()[0]
        payload = {"code": code, "detail": str(exc)}
        if isinstance(exc, EnforcementError) and exc.path:
            payload["path"] = exc.path
        print("ENFORCE_FAIL " + json.dumps(payload, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
