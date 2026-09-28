import hashlib, os, shutil, stat, tempfile
from pathlib import Path
_REPARSE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
_OWNER_ID = "izo.agent-env.external-secret-store.v1"
class ExternalSecretStoreError(RuntimeError): pass
def _lstat(path: Path):
    try:
        return os.lstat(path)
    except FileNotFoundError: return None
def is_reparse_point(path: Path) -> bool:
    info = _lstat(path)
    attrs = int(getattr(info, "st_file_attributes", 0) or 0) if info else 0
    return bool(info and (stat.S_ISLNK(info.st_mode) or attrs & _REPARSE))
def canonical_external_secret_store(environment_root: Path) -> tuple[Path, Path, Path]:
    environment = Path(environment_root).resolve()
    name = hashlib.sha256(str(environment).encode()).hexdigest()[:24]
    parent = Path(tempfile.gettempdir()).expanduser().resolve() / "izo-asa-agent-secrets"
    return parent, parent / name, parent / f".{name}.owner"
def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
def _assert_prewrite_path_safe(environment_root: Path, parent: Path, leaf: Path, production_roots) -> None:
    worktree = Path(environment_root).resolve().parents[2]
    roots = tuple(Path(value).expanduser().resolve(strict=False) for value in production_roots)
    candidates = (parent.parent, parent, leaf)
    if any(_is_within(candidate, worktree) for candidate in candidates):
        raise ExternalSecretStoreError("RUNTIME_SECRET_STORE_PATH_REJECTED")
    if any(_is_within(candidate, root) for candidate in candidates for root in roots):
        raise ExternalSecretStoreError("RUNTIME_SECRET_STORE_PATH_REJECTED")
def _owner(environment_root: Path, package_id: str, lease_id: str) -> str:
    return "|".join((_OWNER_ID, package_id, str(Path(environment_root).resolve().parents[2]), lease_id))
def _owned(marker: Path, environment_root: Path, package_id: str, lease_id: str | None = None) -> bool:
    if _lstat(marker) is None or is_reparse_point(marker):
        return False
    try:
        value = marker.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return False
    parts = value.split("|")
    lease = lease_id or (parts[3] if len(parts) == 4 else "")
    return len(parts) == 4 and bool(parts[3]) and value == _owner(environment_root, package_id, lease)
def _remove_reparse(path: Path) -> None:
    info = _lstat(path)
    if stat.S_ISLNK(info.st_mode):
        os.unlink(path)
    elif int(getattr(info, "st_file_attributes", 0) or 0) & _REPARSE:
        os.rmdir(path)
    else:
        raise ExternalSecretStoreError("RUNTIME_SECRET_STORE_REPARSE_POINT")
def prepare_external_secret_store(environment_root: Path, package_id: str, lease_id: str, *, allow_existing: bool, production_roots) -> Path:
    parent, leaf, marker = canonical_external_secret_store(environment_root)
    _assert_prewrite_path_safe(environment_root, parent, leaf, production_roots)
    if _lstat(parent) is not None and is_reparse_point(parent):
        raise ExternalSecretStoreError("RUNTIME_SECRET_STORE_REPARSE_POINT")
    parent.mkdir(parents=True, exist_ok=True)
    if is_reparse_point(parent):
        raise ExternalSecretStoreError("RUNTIME_SECRET_STORE_REPARSE_POINT")
    if _lstat(leaf) is not None:
        if is_reparse_point(leaf):
            raise ExternalSecretStoreError("RUNTIME_SECRET_STORE_REPARSE_POINT")
        if not leaf.is_dir() or not allow_existing or not _owned(marker, environment_root, package_id, lease_id):
            raise ExternalSecretStoreError("RUNTIME_SECRET_STORE_OWNERSHIP_INVALID")
    else:
        if _lstat(marker) is not None:
            raise ExternalSecretStoreError("RUNTIME_SECRET_STORE_OWNERSHIP_INVALID")
        leaf.mkdir()
        if is_reparse_point(parent) or is_reparse_point(leaf):
            raise ExternalSecretStoreError("RUNTIME_SECRET_STORE_REPARSE_POINT")
        try:
            with marker.open("x", encoding="utf-8") as handle:
                handle.write(_owner(environment_root, package_id, lease_id))
        except FileExistsError:
            raise ExternalSecretStoreError("RUNTIME_SECRET_STORE_OWNERSHIP_INVALID") from None
    resolved = leaf.resolve(strict=True)
    worktree = Path(environment_root).resolve().parents[2]
    production = (Path(value).expanduser().resolve(strict=False) for value in production_roots)
    if resolved != leaf or resolved.is_relative_to(worktree) or any(resolved.is_relative_to(root) for root in production):
        raise ExternalSecretStoreError("RUNTIME_SECRET_STORE_PATH_REJECTED")
    if any(leaf.iterdir()):
        raise ExternalSecretStoreError("RUNTIME_SECRET_STORE_NOT_EMPTY")
    return leaf
def remove_external_secret_store(environment_root: Path, package_id: str) -> None:
    parent, leaf, marker = canonical_external_secret_store(environment_root)
    if _lstat(parent) is None:
        return
    if is_reparse_point(parent):
        raise ExternalSecretStoreError("RUNTIME_SECRET_STORE_REPARSE_POINT")
    if _lstat(leaf) is not None:
        if is_reparse_point(leaf):
            _remove_reparse(leaf)
        elif not leaf.is_dir() or not _owned(marker, environment_root, package_id):
            raise ExternalSecretStoreError("RUNTIME_SECRET_STORE_OWNERSHIP_INVALID")
        elif leaf.resolve(strict=True) != leaf:
            raise ExternalSecretStoreError("RUNTIME_SECRET_STORE_PATH_REJECTED")
        else:
            shutil.rmtree(leaf)
    if _lstat(marker) is not None:
        if is_reparse_point(marker):
            _remove_reparse(marker)
        elif _owned(marker, environment_root, package_id):
            marker.unlink()
        else:
            raise ExternalSecretStoreError("RUNTIME_SECRET_STORE_OWNERSHIP_INVALID")
