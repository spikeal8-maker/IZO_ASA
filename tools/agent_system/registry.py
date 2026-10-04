from __future__ import annotations
import contextlib
import hashlib
import json
import os
import secrets
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable, Iterator
REGISTRY_VERSION = 1
ACTIVE_STATES = {"active", "blocked-dirty"}
class AgentRegistryError(RuntimeError):
    pass
def _git(repo_root: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(repo_root), *args], text=True, capture_output=True, check=False)
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()
        raise AgentRegistryError(f"GIT_COMMAND_FAILED args={' '.join(args)} detail={detail}")
    return result.stdout.strip()
def resolve_repo_root(path: Path | str) -> Path:
    root = _git(Path(path).resolve(), "rev-parse", "--show-toplevel")
    return Path(root).resolve()
def git_common_dir(repo_root: Path) -> Path:
    repo = Path(repo_root).resolve()
    dotgit = repo / ".git"
    try:
        if dotgit.is_dir():
            git_dir = dotgit.resolve(strict=True)
        elif dotgit.is_file():
            raw = dotgit.read_text(encoding="utf-8").strip()
            if "\n" in raw or "\r" in raw or not raw.startswith("gitdir:"):
                raise AgentRegistryError("GIT_METADATA_INVALID")
            target = raw[len("gitdir:"):].strip()
            if not target:
                raise AgentRegistryError("GIT_METADATA_INVALID")
            candidate = Path(target)
            if not candidate.is_absolute():
                candidate = dotgit.parent / candidate
            git_dir = candidate.resolve(strict=True)
            if not git_dir.is_dir():
                raise AgentRegistryError("GIT_METADATA_INVALID")
        else:
            raise AgentRegistryError("GIT_METADATA_INVALID")

        commondir = git_dir / "commondir"
        if not commondir.exists():
            return git_dir
        if not commondir.is_file():
            raise AgentRegistryError("GIT_METADATA_INVALID")
        raw_common = commondir.read_text(encoding="utf-8").strip()
        if not raw_common or "\n" in raw_common or "\r" in raw_common:
            raise AgentRegistryError("GIT_METADATA_INVALID")
        common = Path(raw_common)
        if not common.is_absolute():
            common = git_dir / common
        resolved = common.resolve(strict=True)
        if not resolved.is_dir():
            raise AgentRegistryError("GIT_METADATA_INVALID")
        return resolved
    except AgentRegistryError:
        raise
    except (OSError, RuntimeError, ValueError):
        raise AgentRegistryError("GIT_METADATA_INVALID") from None
def state_root(repo_root: Path) -> Path:
    return git_common_dir(repo_root) / "izo-agent"
def registry_path(repo_root: Path) -> Path:
    return state_root(repo_root) / "registry-v1.json"
def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
def empty_registry() -> dict[str, Any]:
    return {"registryVersion": REGISTRY_VERSION, "entries": []}
def load_registry(
    repo_root: Path,
    diagnostic: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    if diagnostic:
        diagnostic("REGISTRY_COMMON_DIR_START")
    path = registry_path(repo_root)
    if diagnostic:
        diagnostic("REGISTRY_COMMON_DIR_OK")
        diagnostic("REGISTRY_FILE_CHECK_START")
    exists = path.exists()
    if diagnostic:
        diagnostic("REGISTRY_FILE_CHECK_OK")
    if not exists:
        return empty_registry()
    try:
        if diagnostic:
            diagnostic("REGISTRY_FILE_READ_START")
        source = path.read_text(encoding="utf-8")
        if diagnostic:
            diagnostic("REGISTRY_FILE_READ_OK")
        payload = json.loads(source)
        if diagnostic:
            diagnostic("REGISTRY_JSON_PARSE_OK")
    except Exception as exc:
        raise AgentRegistryError(f"REGISTRY_INVALID path={path}") from exc
    if payload.get("registryVersion") != REGISTRY_VERSION or not isinstance(payload.get("entries"), list):
        raise AgentRegistryError(f"REGISTRY_VERSION_UNSUPPORTED path={path}")
    return payload
def atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, raw_tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    tmp = Path(raw_tmp)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
def atomic_write_text(path: Path, text: str) -> None:
    atomic_write_bytes(path, text.encode("utf-8"))
def save_registry(repo_root: Path, payload: dict[str, Any]) -> None:
    if payload.get("registryVersion") != REGISTRY_VERSION:
        raise AgentRegistryError("REGISTRY_VERSION_INVALID")
    rendered = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    atomic_write_text(registry_path(repo_root), rendered)
def _powershell() -> str:
    configured = os.getenv("IZO_POWERSHELL_PATH", "").strip()
    if configured:
        return configured
    for name in ("powershell.exe", "powershell", "pwsh"):
        found = shutil.which(name)
        if found:
            return found
    raise AgentRegistryError("POWERSHELL_NOT_FOUND")
@contextlib.contextmanager
def registry_lock(repo_root: Path, command: str) -> Iterator[None]:
    helper = Path(__file__).resolve().parents[1] / "repository-operation-lock.ps1"
    runtime = repo_root / ".runtime" / "agent"
    runtime.mkdir(parents=True, exist_ok=True)
    token_file = runtime / f"registry-lock-{os.getpid()}-{secrets.token_hex(8)}.token"
    base = [_powershell(), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(helper), "-StorageScope", "common-repository", "-Kind", "agent-registry", "-RepoRoot", str(repo_root), "-OwnerProcessId", str(os.getpid())]
    acquired = subprocess.run([*base, "-Action", "acquire", "-Command", command, "-TokenOutFile", str(token_file)], text=True, capture_output=True, check=False)
    if acquired.returncode:
        token_file.unlink(missing_ok=True)
        raise AgentRegistryError((acquired.stderr or acquired.stdout).strip() or "AGENT_REGISTRY_LOCK_BUSY")
    try:
        token = token_file.read_text(encoding="ascii").strip()
        if not token:
            raise AgentRegistryError("AGENT_REGISTRY_LOCK_TOKEN_MISSING")
        yield
    finally:
        if token_file.exists():
            token = token_file.read_text(encoding="ascii").strip()
            released = subprocess.run([*base, "-Action", "release", "-Token", token], text=True, capture_output=True, check=False)
            token_file.unlink(missing_ok=True)
            if released.returncode:
                raise AgentRegistryError((released.stderr or released.stdout).strip() or "AGENT_REGISTRY_LOCK_RELEASE_FAILED")
def active_entries(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return [entry for entry in payload["entries"] if entry.get("state") in ACTIVE_STATES]
