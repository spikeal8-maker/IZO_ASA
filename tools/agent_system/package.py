from __future__ import annotations
import argparse
import hashlib
import hmac
import json
import os
import platform
import re
import secrets
import subprocess
import sys
import tomllib
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable
from .registry import AgentRegistryError, active_entries, atomic_write_text, current_branch_from_metadata, load_registry, registry_lock, registry_path, resolve_repo_root, save_registry, token_hash
ID_RE = re.compile(r"^[A-Z0-9][A-Z0-9-]{2,79}$")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
RISK_CLASSES = {"low", "standard", "high-assurance", "release-ops"}
MANIFEST_KEYS = {"manifestVersion", "id", "baseSha", "goal", "userOutcome", "beforeScenario", "afterScenario", "nonGoals", "domain", "riskClass", "changeClass", "declaredFiles", "allowedPatterns", "forbiddenPatterns", "protectedFilesTouched", "maxProductionFiles", "maxChangedLines", "acceptance", "requiredEvidence", "targetedTests", "fileGrowthExpectations", "forbiddenOperations", "rollbackBoundary", "scopeExpansions", "sizeReviews"}
TEXT_KEYS = ("goal", "userOutcome", "beforeScenario", "afterScenario", "domain", "rollbackBoundary")
BLOCKED_ROOTS = {".git", ".runtime", "node_modules", ".venv"}
class AgentPackageError(RuntimeError):
    pass
@dataclass(frozen=True)
class ScopeExpansion:
    path: str
    reason: str
    recorded_at_utc: str
@dataclass(frozen=True)
class SizeReview:
    path: str
    rationale: str
@dataclass(frozen=True)
class TaskManifest:
    manifest_version: int
    id: str
    base_sha: str
    goal: str
    user_outcome: str
    before_scenario: str
    after_scenario: str
    non_goals: tuple[str, ...]
    domain: str
    risk_class: str
    change_class: str
    declared_files: tuple[str, ...]
    allowed_patterns: tuple[str, ...]
    forbidden_patterns: tuple[str, ...]
    protected_files_touched: tuple[str, ...]
    max_production_files: int
    max_changed_lines: int
    acceptance: tuple[str, ...]
    required_evidence: tuple[str, ...]
    targeted_tests: tuple[str, ...]
    file_growth_expectations: tuple[str, ...]
    forbidden_operations: tuple[str, ...]
    rollback_boundary: str
    scope_expansions: tuple[ScopeExpansion, ...] = ()
    size_reviews: tuple[SizeReview, ...] = ()
def _git(repo: Path, *args: str, check: bool = True) -> str:
    result = subprocess.run(["git", "-C", str(repo), *args], text=True, capture_output=True, check=False)
    if check and result.returncode:
        raise AgentPackageError(f"GIT_COMMAND_FAILED args={' '.join(args)} detail={(result.stderr or result.stdout).strip()}")
    return result.stdout.strip()
def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
def _clean_text(value: Any, key: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AgentPackageError(f"MANIFEST_FIELD_INVALID field={key}")
    return value.strip()
def normalize_scope(value: str, *, allow_subtree: bool) -> str:
    if not isinstance(value, str):
        raise AgentPackageError("MANIFEST_PATH_INVALID")
    raw = value.strip().replace("\\", "/")
    subtree = raw.endswith("/**")
    if subtree:
        if not allow_subtree:
            raise AgentPackageError(f"MANIFEST_PATH_INVALID path={value}")
        raw = raw[:-3].rstrip("/")
    if not raw or raw.startswith("/") or re.match(r"^[A-Za-z]:", raw) or any(ch in raw for ch in "*?[]"):
        raise AgentPackageError(f"MANIFEST_PATH_INVALID path={value}")
    parts = PurePosixPath(raw).parts
    if any(part in {"", ".", ".."} for part in parts):
        raise AgentPackageError(f"MANIFEST_PATH_INVALID path={value}")
    normalized = "/".join(parts)
    if any(part in BLOCKED_ROOTS for part in parts):
        raise AgentPackageError(f"MANIFEST_PATH_FORBIDDEN path={value}")
    return normalized + ("/**" if subtree else "")
def _string_list(data: dict[str, Any], key: str, *, scope: bool = False, subtree: bool = True) -> tuple[str, ...]:
    value = data.get(key)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise AgentPackageError(f"MANIFEST_FIELD_INVALID field={key}")
    cleaned = [normalize_scope(item, allow_subtree=subtree) if scope else item.strip() for item in value]
    if any(not item for item in cleaned) or len(set(cleaned)) != len(cleaned):
        raise AgentPackageError(f"MANIFEST_FIELD_INVALID field={key}")
    return tuple(cleaned)
def parse_manifest(path: Path) -> TaskManifest:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise AgentPackageError(f"MANIFEST_PARSE_FAILED path={path}") from exc
    unknown = sorted(set(data) - MANIFEST_KEYS)
    if unknown:
        raise AgentPackageError(f"MANIFEST_UNKNOWN_KEYS keys={','.join(unknown)}")
    if data.get("manifestVersion") != 1:
        raise AgentPackageError("MANIFEST_VERSION_UNSUPPORTED")
    package_id = _clean_text(data.get("id"), "id")
    if not ID_RE.fullmatch(package_id):
        raise AgentPackageError(f"MANIFEST_ID_INVALID id={package_id}")
    if path.parent.name == "tasks" and path.name != f"{package_id}.toml":
        raise AgentPackageError(f"MANIFEST_FILENAME_MISMATCH expected={package_id}.toml")
    base_sha = _clean_text(data.get("baseSha"), "baseSha")
    if not SHA_RE.fullmatch(base_sha):
        raise AgentPackageError("MANIFEST_BASE_SHA_INVALID")
    for key in TEXT_KEYS:
        _clean_text(data.get(key), key)
    if data.get("riskClass") not in RISK_CLASSES or not re.fullmatch(r"[a-z][a-z0-9-]{1,39}", str(data.get("changeClass", ""))):
        raise AgentPackageError("MANIFEST_CLASS_INVALID")
    for key in ("maxProductionFiles", "maxChangedLines"):
        if not isinstance(data.get(key), int) or data[key] < 0:
            raise AgentPackageError(f"MANIFEST_FIELD_INVALID field={key}")
    expansions_raw = data.get("scopeExpansions", [])
    if not isinstance(expansions_raw, list):
        raise AgentPackageError("MANIFEST_FIELD_INVALID field=scopeExpansions")
    expansions: list[ScopeExpansion] = []
    for item in expansions_raw:
        if not isinstance(item, dict) or set(item) != {"path", "reason", "recordedAtUtc"}:
            raise AgentPackageError("MANIFEST_SCOPE_EXPANSION_INVALID")
        expansions.append(ScopeExpansion(normalize_scope(item["path"], allow_subtree=True), _clean_text(item["reason"], "scopeExpansions.reason"), _clean_text(item["recordedAtUtc"], "scopeExpansions.recordedAtUtc")))
    reviews_raw = data.get("sizeReviews", [])
    if not isinstance(reviews_raw, list):
        raise AgentPackageError("MANIFEST_SIZE_REVIEW_INVALID")
    reviews: list[SizeReview] = []
    review_paths: set[str] = set()
    for item in reviews_raw:
        if not isinstance(item, dict) or set(item) != {"path", "rationale"}:
            raise AgentPackageError("MANIFEST_SIZE_REVIEW_INVALID")
        review_path = normalize_scope(item["path"], allow_subtree=False)
        if review_path in review_paths:
            raise AgentPackageError("MANIFEST_SIZE_REVIEW_INVALID duplicate-path")
        review_paths.add(review_path)
        reviews.append(SizeReview(review_path, _clean_text(item["rationale"], "sizeReviews.rationale")))
    return TaskManifest(1, package_id, base_sha, *(_clean_text(data[key], key) for key in ("goal", "userOutcome", "beforeScenario", "afterScenario")), _string_list(data, "nonGoals"), _clean_text(data["domain"], "domain"), data["riskClass"], data["changeClass"], _string_list(data, "declaredFiles", scope=True, subtree=False), _string_list(data, "allowedPatterns", scope=True), _string_list(data, "forbiddenPatterns", scope=True), _string_list(data, "protectedFilesTouched", scope=True, subtree=False), data["maxProductionFiles"], data["maxChangedLines"], *(_string_list(data, key) for key in ("acceptance", "requiredEvidence", "targetedTests", "fileGrowthExpectations", "forbiddenOperations")), _clean_text(data["rollbackBoundary"], "rollbackBoundary"), tuple(expansions), tuple(reviews))
def _q(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)
def _arr(name: str, values: tuple[str, ...]) -> list[str]:
    return [f"{name} = [", *[f"  {_q(item)}," for item in values], "]"]
def render_manifest(m: TaskManifest) -> str:
    lines = ["manifestVersion = 1", f"id = {_q(m.id)}", f"baseSha = {_q(m.base_sha)}", f"goal = {_q(m.goal)}", f"userOutcome = {_q(m.user_outcome)}", f"beforeScenario = {_q(m.before_scenario)}", f"afterScenario = {_q(m.after_scenario)}"]
    for name, values in (("nonGoals", m.non_goals), ("declaredFiles", m.declared_files), ("allowedPatterns", m.allowed_patterns), ("forbiddenPatterns", m.forbidden_patterns), ("protectedFilesTouched", m.protected_files_touched)):
        lines.extend(_arr(name, values))
    lines.extend([f"domain = {_q(m.domain)}", f"riskClass = {_q(m.risk_class)}", f"changeClass = {_q(m.change_class)}", f"maxProductionFiles = {m.max_production_files}", f"maxChangedLines = {m.max_changed_lines}"])
    for name, values in (("acceptance", m.acceptance), ("requiredEvidence", m.required_evidence), ("targetedTests", m.targeted_tests), ("fileGrowthExpectations", m.file_growth_expectations), ("forbiddenOperations", m.forbidden_operations)):
        lines.extend(_arr(name, values))
    lines.append(f"rollbackBoundary = {_q(m.rollback_boundary)}")
    for expansion in m.scope_expansions:
        lines.extend(["", "[[scopeExpansions]]", f"path = {_q(expansion.path)}", f"reason = {_q(expansion.reason)}", f"recordedAtUtc = {_q(expansion.recorded_at_utc)}"])
    for review in m.size_reviews:
        lines.extend(["", "[[sizeReviews]]", f"path = {_q(review.path)}", f"rationale = {_q(review.rationale)}"])
    return "\n".join(lines) + "\n"
def manifest_fingerprint(m: TaskManifest) -> str:
    return hashlib.sha256(render_manifest(m).encode("utf-8")).hexdigest()
def scope_items(m: TaskManifest) -> tuple[str, ...]:
    return tuple(dict.fromkeys((f"tasks/{m.id}.toml", *m.declared_files, *m.allowed_patterns)))
def _scope_shape(item: str) -> tuple[tuple[str, ...], bool]:
    subtree = item.endswith("/**")
    base = item[:-3] if subtree else item
    return tuple(PurePosixPath(base).parts), subtree
def scopes_overlap(a: str, b: str) -> bool:
    ap, at = _scope_shape(a)
    bp, bt = _scope_shape(b)
    if not at and not bt:
        return ap == bp
    if at and bt:
        return ap == bp[:len(ap)] or bp == ap[:len(bp)]
    tree, exact = (ap, bp) if at else (bp, ap)
    return tree == exact[:len(tree)]
def _matches(pattern: str, path: str) -> bool:
    pp, subtree = _scope_shape(pattern)
    actual, _ = _scope_shape(path)
    return actual == pp if not subtree else pp == actual[:len(pp)]
def _validate_repo(repo: Path, manifest: TaskManifest) -> None:
    base_check = subprocess.run(["git", "-C", str(repo), "cat-file", "-e", f"{manifest.base_sha}^{{commit}}"], capture_output=True)
    if base_check.returncode:
        raise AgentPackageError("BASE_SHA_UNAVAILABLE")
    origin_main = _git(repo, "rev-parse", "refs/remotes/origin/main")
    if origin_main != manifest.base_sha:
        raise AgentPackageError(f"BASE_SHA_NOT_CURRENT_MAIN expected={origin_main} manifest={manifest.base_sha}")
    if not _git(repo, "remote", "get-url", "origin"):
        raise AgentPackageError("ORIGIN_REMOTE_MISSING")
def _path_key(path: Path) -> str:
    return os.path.normcase(str(path.resolve()))
def _ownership_file(repo: Path) -> Path:
    return repo / ".runtime" / "agent" / "ownership.json"
def _read_ownership(repo: Path) -> dict[str, Any]:
    path = _ownership_file(repo)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise AgentPackageError("OWNERSHIP_FILE_MISSING_OR_INVALID") from exc
    if not isinstance(payload, dict) or not payload.get("packageId") or not payload.get("token"):
        raise AgentPackageError("OWNERSHIP_FILE_MISSING_OR_INVALID")
    return payload
def _write_ownership(repo: Path, package_id: str, token: str, owner_id: str) -> None:
    path = _ownership_file(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, json.dumps({"packageId": package_id, "token": token, "ownerInstanceId": owner_id}, indent=2) + "\n")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
def _entry_for(payload: dict[str, Any], package_id: str) -> dict[str, Any] | None:
    return next((entry for entry in payload["entries"] if entry.get("packageId") == package_id and entry.get("state") in {"active", "blocked-dirty"}), None)
def _assert_owner(
    repo: Path,
    payload: dict[str, Any],
    diagnostic: Callable[[str], None] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], TaskManifest, Path]:
    if diagnostic:
        diagnostic("OWNERSHIP_READ_START")
    ownership = _read_ownership(repo)
    if diagnostic:
        diagnostic("OWNERSHIP_READ_OK")
        diagnostic("REGISTRY_ENTRY_LOOKUP_START")
    entry = _entry_for(payload, ownership["packageId"])
    if diagnostic:
        diagnostic("REGISTRY_ENTRY_LOOKUP_OK")
        diagnostic("OWNERSHIP_TOKEN_CHECK_START")
    if entry is None or not hmac.compare_digest(
        str(entry.get("ownershipTokenHash", "")), token_hash(ownership["token"])
    ):
        raise AgentPackageError("OWNERSHIP_MISMATCH")
    if diagnostic:
        diagnostic("OWNERSHIP_TOKEN_CHECK_OK")
        diagnostic("WORKTREE_PATH_CHECK_START")
    if _path_key(Path(entry["worktreePath"])) != _path_key(repo):
        raise AgentPackageError("OWNERSHIP_WORKTREE_MISMATCH")
    if diagnostic:
        diagnostic("WORKTREE_PATH_CHECK_OK")
        diagnostic("BRANCH_QUERY_START")
    branch = current_branch_from_metadata(repo)
    if diagnostic:
        diagnostic("BRANCH_QUERY_OK")
    if entry.get("branch") != branch:
        raise AgentPackageError("OWNERSHIP_WORKTREE_MISMATCH")
    manifest_path = repo / "tasks" / f"{entry['packageId']}.toml"
    if diagnostic:
        diagnostic("MANIFEST_PARSE_START")
    manifest = parse_manifest(manifest_path)
    if diagnostic:
        diagnostic("MANIFEST_PARSE_OK")
        diagnostic("MANIFEST_FINGERPRINT_START")
    fingerprint = manifest_fingerprint(manifest)
    if diagnostic:
        diagnostic("MANIFEST_FINGERPRINT_OK")
    if fingerprint != entry.get("manifestFingerprint"):
        raise AgentPackageError("MANIFEST_REGISTRY_DRIFT")
    if diagnostic:
        diagnostic("OWNER_ASSERT_OK")
    return ownership, entry, manifest, manifest_path
def _overlap(payload: dict[str, Any], scopes: tuple[str, ...], exclude_id: str = "") -> tuple[str, str, str] | None:
    for entry in active_entries(payload):
        if entry.get("packageId") == exclude_id:
            continue
        for ours in scopes:
            for theirs in entry.get("writeOwnership", []):
                if scopes_overlap(ours, str(theirs)):
                    return str(entry.get("packageId")), ours, str(theirs)
    return None
def doctor(repo: Path) -> int:
    payload = load_registry(repo)
    result = {"ok": True, "repo": str(repo), "branch": _git(repo, "branch", "--show-current"), "head": _git(repo, "rev-parse", "HEAD"), "origin": _git(repo, "remote", "get-url", "origin"), "originMain": _git(repo, "rev-parse", "refs/remotes/origin/main"), "registry": str(registry_path(repo)), "activePackages": len(active_entries(payload)), "host": platform.node()}
    print("AGENT_DOCTOR " + json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0
def start(repo: Path, draft_path: Path, worktree_override: str = "") -> int:
    manifest = parse_manifest(draft_path.resolve())
    _validate_repo(repo, manifest)
    for owned in scope_items(manifest):
        if any(scopes_overlap(blocked, owned) for blocked in manifest.forbidden_patterns):
            raise AgentPackageError(f"MANIFEST_SCOPE_FORBIDDEN path={owned}")
    branch = f"agent/{manifest.id.lower()}"
    target = Path(worktree_override).expanduser().resolve() if worktree_override else repo.parent / f"{repo.name}-worktrees" / manifest.id.lower()
    existing_worktrees = [Path(line[len("worktree "):]).resolve() for line in _git(repo, "worktree", "list", "--porcelain").splitlines() if line.startswith("worktree ")]
    if any(target == existing or existing in target.parents or target in existing.parents for existing in existing_worktrees):
        raise AgentPackageError("WORKTREE_PATH_INSIDE_EXISTING_WORKTREE")
    created = False
    with registry_lock(repo, f"agent start {manifest.id}"):
        payload = load_registry(repo)
        if any(entry.get("packageId") == manifest.id for entry in payload["entries"]):
            raise AgentPackageError(f"DUPLICATE_PACKAGE_ID id={manifest.id}")
        collision = _overlap(payload, scope_items(manifest))
        if collision:
            raise AgentPackageError(f"SCOPE_OVERLAP owner={collision[0]} requested={collision[1]} existing={collision[2]}")
        if target.exists() or _git(repo, "show-ref", "--verify", f"refs/heads/{branch}", check=False):
            raise AgentPackageError("WORKTREE_OR_BRANCH_ALREADY_EXISTS")
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            _git(repo, "worktree", "add", "-b", branch, str(target), manifest.base_sha)
            created = True
            canonical = target / "tasks" / f"{manifest.id}.toml"
            canonical.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_text(canonical, render_manifest(manifest))
            token, owner_id = secrets.token_urlsafe(32), secrets.token_hex(16)
            _write_ownership(target, manifest.id, token, owner_id)
            now = _now()
            payload["entries"].append({"packageId": manifest.id, "manifestPath": f"tasks/{manifest.id}.toml", "manifestFingerprint": manifest_fingerprint(manifest), "branch": branch, "worktreePath": str(target), "baseSha": manifest.base_sha, "currentHeadSha": manifest.base_sha, "writeOwnership": list(scope_items(manifest)), "discoveredWriteOwnership": [], "state": "active", "ownerInstanceId": owner_id, "ownershipTokenHash": token_hash(token), "creatorHost": platform.node(), "createdAt": now, "updatedAt": now, "scopeExpansionHistory": []})
            save_registry(repo, payload)
        except Exception:
            if created:
                (target / "tasks" / f"{manifest.id}.toml").unlink(missing_ok=True)
                _ownership_file(target).unlink(missing_ok=True)
                if not _git(target, "status", "--porcelain", check=False):
                    _git(repo, "worktree", "remove", str(target), check=False)
                    _git(repo, "branch", "-D", branch, check=False)
            raise
    print(f"AGENT_PACKAGE_STARTED id={manifest.id} branch={branch} worktree={target} base={manifest.base_sha}")
    return 0
def status(repo: Path) -> int:
    payload = load_registry(repo)
    rows = []
    known_worktrees = {_path_key(Path(line[len("worktree "):])) for line in _git(repo, "worktree", "list", "--porcelain").splitlines() if line.startswith("worktree ")}
    for entry in active_entries(payload):
        worktree = Path(entry["worktreePath"])
        health = "ok" if _path_key(worktree) in known_worktrees and worktree.exists() else "STALE_OR_FOREIGN_OWNERSHIP"
        if health == "ok":
            try:
                _assert_owner(worktree, payload)
            except AgentPackageError as exc:
                health = "MANIFEST_REGISTRY_DRIFT" if str(exc) == "MANIFEST_REGISTRY_DRIFT" else "STALE_OR_FOREIGN_OWNERSHIP"
        rows.append({"packageId": entry["packageId"], "state": entry["state"], "branch": entry["branch"], "worktreePath": entry["worktreePath"], "health": health})
    print("AGENT_STATUS " + json.dumps(rows, ensure_ascii=False, sort_keys=True))
    return 0
def scope_add(repo: Path, requested: str, reason: str) -> int:
    requested = normalize_scope(requested, allow_subtree=True)
    reason = reason.strip()
    if not reason:
        raise AgentPackageError("SCOPE_REASON_REQUIRED")
    with registry_lock(repo, "agent scope-add"):
        payload = load_registry(repo)
        ownership, entry, manifest, manifest_path = _assert_owner(repo, payload)
        if any(scopes_overlap(pattern, requested) for pattern in manifest.forbidden_patterns):
            raise AgentPackageError(f"FORBIDDEN_SCOPE path={requested}")
        if any(_matches(pattern, requested) for pattern in scope_items(manifest)):
            print(f"AGENT_SCOPE_ALREADY_OWNED id={manifest.id} path={requested}")
            return 0
        collision = _overlap(payload, (requested,), exclude_id=manifest.id)
        if collision:
            raise AgentPackageError(f"SCOPE_OVERLAP owner={collision[0]} requested={requested} existing={collision[2]}")
        stamp = _now()
        updated = replace(manifest, allowed_patterns=(*manifest.allowed_patterns, requested), scope_expansions=(*manifest.scope_expansions, ScopeExpansion(requested, reason, stamp)))
        old_bytes = manifest_path.read_bytes()
        atomic_write_text(manifest_path, render_manifest(updated))
        try:
            entry["manifestFingerprint"] = manifest_fingerprint(updated)
            entry["writeOwnership"] = list(scope_items(updated))
            entry["discoveredWriteOwnership"] = list(dict.fromkeys([*entry.get("discoveredWriteOwnership", []), requested]))
            entry["scopeExpansionHistory"] = [*entry.get("scopeExpansionHistory", []), {"path": requested, "reason": reason, "recordedAtUtc": stamp}]
            entry["updatedAt"] = stamp
            entry["currentHeadSha"] = _git(repo, "rev-parse", "HEAD")
            save_registry(repo, payload)
        except Exception:
            from .registry import atomic_write_bytes
            atomic_write_bytes(manifest_path, old_bytes)
            raise
    print(f"AGENT_SCOPE_ADDED id={ownership['packageId']} path={requested}")
    return 0
def finish(repo: Path) -> int:
    with registry_lock(repo, "agent finish"):
        payload = load_registry(repo)
        ownership, entry, _manifest, _path = _assert_owner(repo, payload)
        if _git(repo, "status", "--porcelain"):
            entry["state"] = "blocked-dirty"
            entry["updatedAt"] = _now()
            save_registry(repo, payload)
            raise AgentPackageError("PACKAGE_DIRTY_OWNERSHIP_RETAINED")
        entry["state"] = "closed"
        entry["closedAt"] = entry["updatedAt"] = _now()
        entry["currentHeadSha"] = _git(repo, "rev-parse", "HEAD")
        save_registry(repo, payload)
        _ownership_file(repo).unlink(missing_ok=True)
    print(f"AGENT_PACKAGE_FINISHED id={ownership['packageId']} head={entry['currentHeadSha']}")
    return 0
def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agent")
    parser.add_argument("--repo-root", default=".")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor")
    start_p = sub.add_parser("start")
    start_p.add_argument("--manifest", required=True)
    start_p.add_argument("--worktree-path", default="")
    sub.add_parser("status")
    scope_p = sub.add_parser("scope-add")
    scope_p.add_argument("--path", required=True)
    scope_p.add_argument("--reason", required=True)
    sub.add_parser("finish")
    for name in ("context", "symbol", "env-up", "verify", "audit", "eval"):
        sub.add_parser(name)
    return parser
def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        repo = resolve_repo_root(args.repo_root)
        if args.command == "doctor":
            return doctor(repo)
        if args.command == "start":
            return start(repo, Path(args.manifest), args.worktree_path)
        if args.command == "status":
            return status(repo)
        if args.command == "scope-add":
            return scope_add(repo, args.path, args.reason)
        if args.command == "finish":
            return finish(repo)
        print(f"NOT_IMPLEMENTED command={args.command}", file=sys.stderr)
        return 3
    except (AgentPackageError, AgentRegistryError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
if __name__ == "__main__":
    raise SystemExit(main())
