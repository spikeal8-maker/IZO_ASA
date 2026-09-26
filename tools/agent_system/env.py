"""Plan-only isolated environment contract for active agent packages.
Slice 1 deliberately does not start applications, bind ports, probe providers, or
implement lifecycle. It only derives and validates a deterministic planned
environment from the existing package registry/ownership identity.
"""
from __future__ import annotations
import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PureWindowsPath
from typing import Mapping
from .package import AgentPackageError, ID_RE, _assert_owner
from .registry import (
    AgentRegistryError,
    active_entries,
    atomic_write_text,
    load_registry,
    resolve_repo_root,
)
SCHEMA_VERSION = 1
CONTRACT_ID = "izo.agent-env.plan.v1"
PROVIDER_MODE = "isolated"
SECRET_MODE = "fake-only"
PLANNED_STATE = "planned"
PORT_BASE = 20000
PORT_PAIR_COUNT = 20000
PORT_MAX = PORT_BASE + (PORT_PAIR_COUNT * 2) - 1
PRODUCTION_PROMOTER = Path("ops/release/promote-project-release.ps1")
WINDOWS_ABSOLUTE = re.compile(r"^[A-Za-z]:[\\/]")
DATABASE_ROOT_PATTERN = re.compile(
    r"\$database\.StartsWith\('([^']+)'", re.IGNORECASE
)
SECRET_ROOT_PATTERN = re.compile(
    r"Set-ServiceEnvironmentValue\s+-Document\s+\$xml\s+-Name\s+'IZO_SECRET_DIR'"
    r"\s+-Value\s+'([^']+)'",
    re.IGNORECASE | re.DOTALL,
)
EXTERNAL_PROVIDERS = ("telegram", "max", "openrouter", "smtp", "vk-social", "payments")
LOCAL_PROVIDERS = ("comfyui", "ollama", "qwen")
CREDENTIAL_CLASSIFICATIONS = {
    "OPENROUTER_API_KEY": "openrouter-credential",
    "TELEGRAM_BOT_TOKEN": "telegram-credential",
    "TELEGRAM_WEBHOOK_SECRET": "telegram-credential",
    "MAX_BOT_TOKEN": "max-credential",
    "MAX_WEBHOOK_SECRET": "max-credential",
    "SMTP_USERNAME": "smtp-credential",
    "SMTP_PASSWORD": "smtp-credential",
    "SMTP_TOKEN": "smtp-credential",
    "VK_ACCESS_TOKEN": "vk-credential",
    "VK_TOKEN": "vk-credential",
    "VK_API_KEY": "vk-credential",
    "VK_SECRET": "vk-credential",
    "VK_SERVICE_TOKEN": "vk-credential",
    "YOOKASSA_SHOP_ID": "payment-credential",
    "YOOKASSA_SECRET_KEY": "payment-credential",
    "PAYMENT_PROVIDER_TOKEN": "payment-credential",
}
CREDENTIAL_PREFIXES = ("OPENROUTER", "TELEGRAM", "MAX", "SMTP", "VK", "YOOKASSA")
CREDENTIAL_MARKERS = ("TOKEN", "KEY", "SECRET", "PASSWORD", "USERNAME", "CREDENTIAL")
class EnvironmentContractError(RuntimeError):
    """Fail-closed environment contract violation."""
@dataclass(frozen=True)
class EnvironmentIdentity:
    package_id: str
    base_sha: str
    worktree_path: Path
    branch: str
@dataclass(frozen=True)
class EnvironmentPaths:
    environment_root: Path
    database_path: Path
    media_root: Path
    secret_root: Path
    state_root: Path
    @property
    def environment_state_path(self) -> Path:
        return self.state_root / "environment.json"
    @property
    def receipt_path(self) -> Path:
        return self.state_root / "environment-receipt.json"
@dataclass(frozen=True)
class ProductionPathContract:
    status: str
    database_status: str
    media_status: str
    secret_status: str
    database_roots: tuple[str, ...]
    media_roots: tuple[str, ...]
    secret_roots: tuple[str, ...]
    source_files: tuple[str, ...]
    @property
    def all_roots(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys((*self.database_roots, *self.media_roots, *self.secret_roots))
        )
def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
def _normalize_contract_root(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if WINDOWS_ABSOLUTE.match(raw):
        path = str(PureWindowsPath(raw))
        if len(path) > 3:
            path = path.rstrip("\\/")
        return path
    return str(Path(raw).expanduser().resolve(strict=False))
def discover_production_path_contract(repo_root: Path | str) -> ProductionPathContract:
    """Read production-sensitive roots from tracked release contracts.

    The release contract constrains live SQLite root families and pins the
    production secret root. It does not currently define an exact/canonical
    MEDIA_DIR, so media remains UNKNOWN and default planning fails closed.
    """
    repo = resolve_repo_root(repo_root)
    promoter = repo / PRODUCTION_PROMOTER
    try:
        source = promoter.read_text(encoding="utf-8")
    except OSError:
        return ProductionPathContract(
            "UNKNOWN", "UNKNOWN", "UNKNOWN", "UNKNOWN", (), (), (), (str(PRODUCTION_PROMOTER),)
        )
    database_roots = tuple(
        dict.fromkeys(
            root
            for match in DATABASE_ROOT_PATTERN.findall(source)
            if (root := _normalize_contract_root(match))
        )
    )
    secret_match = SECRET_ROOT_PATTERN.search(source)
    secret_exact = _normalize_contract_root(secret_match.group(1)) if secret_match else ""
    database_status = "KNOWN" if database_roots else "UNKNOWN"
    # Fail closed: the tracked release contract has no canonical current
    # MEDIA_DIR, so DB root families must not be relabeled as media evidence.
    media_roots: tuple[str, ...] = ()
    media_status = "UNKNOWN"
    secret_roots = tuple(dict.fromkeys((*(database_roots or ()), *((secret_exact,) if secret_exact else ()))))
    secret_status = "KNOWN" if secret_exact and secret_roots else "UNKNOWN"
    overall = (
        "KNOWN"
        if database_status == media_status == secret_status == "KNOWN"
        else "UNKNOWN"
    )
    return ProductionPathContract(
        overall,
        database_status,
        media_status,
        secret_status,
        database_roots,
        media_roots,
        secret_roots,
        (PRODUCTION_PROMOTER.as_posix(),),
    )
def load_environment_identity(repo_root: Path | str) -> EnvironmentIdentity:
    """Resolve the active package solely through the existing ownership/registry."""
    repo = resolve_repo_root(repo_root)
    try:
        payload = load_registry(repo)
        _ownership, entry, manifest, _manifest_path = _assert_owner(repo, payload)
    except (AgentPackageError, AgentRegistryError) as exc:
        raise EnvironmentContractError(
            f"PACKAGE_OWNERSHIP_INVALID reason={str(exc)}"
        ) from None
    if entry.get("state") != "active":
        raise EnvironmentContractError(
            f"PACKAGE_OWNERSHIP_NOT_ACTIVE packageId={manifest.id}"
        )
    return EnvironmentIdentity(
        package_id=manifest.id,
        base_sha=manifest.base_sha,
        worktree_path=repo,
        branch=str(entry["branch"]),
    )
def derive_environment_paths(identity: EnvironmentIdentity) -> EnvironmentPaths:
    root = identity.worktree_path / ".runtime" / "agent-env" / identity.package_id
    return EnvironmentPaths(
        environment_root=root,
        database_path=root / "db" / "app.sqlite3",
        media_root=root / "media",
        secret_root=root / "secrets",
        state_root=root / "state",
    )
def derive_candidate_ports(package_id: str) -> dict[str, int]:
    """Stable candidate pair; never binds, reserves, probes, or random-falls back."""
    if not ID_RE.fullmatch(str(package_id or "")):
        raise EnvironmentContractError(f"PACKAGE_ID_INVALID packageId={package_id!r}")
    digest = hashlib.sha256(f"{CONTRACT_ID}:{package_id}".encode("utf-8")).digest()
    slot = int.from_bytes(digest[:8], "big") % PORT_PAIR_COUNT
    backend = PORT_BASE + (slot * 2)
    frontend = backend + 1
    if not (1024 <= backend < frontend <= 65535) or frontend > PORT_MAX:
        raise EnvironmentContractError("PORT_MODEL_OUT_OF_RANGE")
    return {"backend": backend, "frontend": frontend}
def _is_windows_path(value: str) -> bool:
    return bool(WINDOWS_ABSOLUTE.match(value))
def _is_within(candidate: str | Path, root: str | Path) -> bool:
    candidate_text = str(candidate)
    root_text = str(root)
    candidate_windows = _is_windows_path(candidate_text)
    root_windows = _is_windows_path(root_text)
    if candidate_windows or root_windows:
        if not (candidate_windows and root_windows):
            return False
        candidate_parts = tuple(part.casefold() for part in PureWindowsPath(candidate_text).parts)
        root_parts = tuple(part.casefold() for part in PureWindowsPath(root_text).parts)
        return candidate_parts[: len(root_parts)] == root_parts
    candidate_path = Path(candidate_text).expanduser().resolve(strict=False)
    root_path = Path(root_text).expanduser().resolve(strict=False)
    try:
        candidate_path.relative_to(root_path)
        return True
    except ValueError:
        return False
def _require_known_production_contract(contract: ProductionPathContract) -> None:
    if contract.status != "KNOWN":
        raise EnvironmentContractError(
            "PRODUCTION_PATH_STATUS_UNKNOWN "
            f"database={contract.database_status} media={contract.media_status} "
            f"secrets={contract.secret_status}"
        )
def _reject_production_path(
    kind: str, candidate: Path, contract: ProductionPathContract
) -> None:
    for root in contract.all_roots:
        if _is_within(candidate, root):
            raise EnvironmentContractError(
                f"PRODUCTION_{kind.upper()}_PATH_REJECTED rootClass=known-production"
            )
def _resolve_inside_worktree(candidate: Path, worktree: Path, *, kind: str) -> Path:
    worktree_resolved = worktree.resolve(strict=True)
    lexical = Path(os.path.abspath(str(candidate)))
    try:
        lexical_relative = lexical.relative_to(worktree_resolved)
    except ValueError:
        raise EnvironmentContractError(f"{kind.upper()}_PATH_OUTSIDE_WORKTREE") from None
    if ".git" in lexical_relative.parts:
        raise EnvironmentContractError(f"{kind.upper()}_PATH_INSIDE_GIT")
    resolved = lexical.resolve(strict=False)
    try:
        resolved.relative_to(worktree_resolved)
    except ValueError:
        raise EnvironmentContractError(f"{kind.upper()}_SYMLINK_ESCAPE") from None
    return resolved
def validate_environment_paths(
    identity: EnvironmentIdentity,
    paths: EnvironmentPaths,
    production_contract: ProductionPathContract,
) -> None:
    """Validate canonical layout, production boundaries and symlink containment."""
    _require_known_production_contract(production_contract)
    for root in production_contract.all_roots:
        if _is_within(identity.worktree_path, root):
            raise EnvironmentContractError("WORKTREE_INSIDE_PRODUCTION_ROOT")
    for kind, candidate in (
        ("environment", paths.environment_root),
        ("database", paths.database_path),
        ("media", paths.media_root),
        ("secret", paths.secret_root),
        ("state", paths.state_root),
    ):
        _reject_production_path(kind, candidate, production_contract)
    resolved_paths: dict[str, Path] = {}
    for kind, candidate in (
        ("environment", paths.environment_root),
        ("database", paths.database_path),
        ("media", paths.media_root),
        ("secret", paths.secret_root),
        ("state", paths.state_root),
    ):
        resolved_paths[kind] = _resolve_inside_worktree(
            candidate, identity.worktree_path, kind=kind
        )
    expected = derive_environment_paths(identity)
    for kind, actual, canonical in (
        ("environment", paths.environment_root, expected.environment_root),
        ("database", paths.database_path, expected.database_path),
        ("media", paths.media_root, expected.media_root),
        ("secret", paths.secret_root, expected.secret_root),
        ("state", paths.state_root, expected.state_root),
    ):
        if Path(os.path.abspath(str(actual))) != Path(os.path.abspath(str(canonical))):
            raise EnvironmentContractError(f"{kind.upper()}_LAYOUT_MISMATCH")
    environment_resolved = resolved_paths["environment"]
    for kind in ("database", "media", "secret", "state"):
        try:
            resolved_paths[kind].relative_to(environment_resolved)
        except ValueError:
            raise EnvironmentContractError(
                f"{kind.upper()}_PATH_OUTSIDE_ENVIRONMENT_ROOT"
            ) from None
def _credential_classification(name: str) -> str:
    upper = name.upper()
    for prefix in CREDENTIAL_PREFIXES:
        if upper.startswith(prefix + "_") or upper == prefix:
            return f"{prefix.lower()}-credential"
    return "external-provider-credential"
def inspect_provider_credentials(
    environment: Mapping[str, str] | None = None,
) -> list[dict[str, object]]:
    source = os.environ if environment is None else environment
    upper_source = {str(key).upper(): str(value) for key, value in source.items()}
    names = set(CREDENTIAL_CLASSIFICATIONS)
    for name in upper_source:
        if (
            any(name == prefix or name.startswith(prefix + "_") for prefix in CREDENTIAL_PREFIXES)
            and any(marker in name for marker in CREDENTIAL_MARKERS)
        ):
            names.add(name)
    inventory: list[dict[str, object]] = []
    for name in sorted(names):
        present = bool(upper_source.get(name, "").strip())
        inventory.append(
            {
                "credentialName": name,
                "present": present,
                "classification": CREDENTIAL_CLASSIFICATIONS.get(
                    name, _credential_classification(name)
                ),
            }
        )
    return inventory
def _assert_fake_only_credentials(inventory: list[dict[str, object]]) -> None:
    present = [str(item["credentialName"]) for item in inventory if item["present"]]
    if present:
        raise EnvironmentContractError(
            "REAL_PROVIDER_CREDENTIAL_PRESENT credentialName=" + ",".join(sorted(present))
        )
def provider_policy() -> dict[str, dict[str, object]]:
    policy: dict[str, dict[str, object]] = {}
    for name in EXTERNAL_PROVIDERS:
        policy[name] = {
            "mode": "disabled/fake",
            "localEndpointAllowed": False,
            "externalInternetAllowed": False,
        }
    for name in LOCAL_PROVIDERS:
        policy[name] = {
            "mode": "local-configurable",
            "localEndpointAllowed": True,
            "externalInternetAllowed": False,
        }
    return policy
def _assert_port_candidates_unique(
    repo_root: Path, package_id: str, ports: Mapping[str, int]
) -> None:
    payload = load_registry(repo_root)
    ours = {int(ports["backend"]), int(ports["frontend"])}
    for entry in active_entries(payload):
        other_id = str(entry.get("packageId") or "")
        if not other_id or other_id == package_id:
            continue
        other = derive_candidate_ports(other_id)
        overlap = ours.intersection({other["backend"], other["frontend"]})
        if overlap:
            rendered = ",".join(str(port) for port in sorted(overlap))
            raise EnvironmentContractError(
                f"PORT_CANDIDATE_COLLISION packageId={other_id} ports={rendered}"
            )
def build_environment_plan(
    repo_root: Path | str,
    *,
    environment: Mapping[str, str] | None = None,
    production_contract: ProductionPathContract | None = None,
    timestamp: str | None = None,
) -> dict[str, object]:
    identity = load_environment_identity(repo_root)
    paths = derive_environment_paths(identity)
    contract = production_contract or discover_production_path_contract(identity.worktree_path)
    validate_environment_paths(identity, paths, contract)
    credentials = inspect_provider_credentials(environment)
    _assert_fake_only_credentials(credentials)
    ports = derive_candidate_ports(identity.package_id)
    _assert_port_candidates_unique(identity.worktree_path, identity.package_id, ports)
    stamp = timestamp or utc_now()
    return {
        "schemaVersion": SCHEMA_VERSION,
        "contractId": CONTRACT_ID,
        "packageId": identity.package_id,
        "baseSha": identity.base_sha,
        "worktreePath": str(identity.worktree_path),
        "environmentRoot": str(paths.environment_root),
        "databasePath": str(paths.database_path),
        "mediaRoot": str(paths.media_root),
        "secretRoot": str(paths.secret_root),
        "secretMode": SECRET_MODE,
        "providerMode": PROVIDER_MODE,
        "providers": provider_policy(),
        "ports": {
            "backend": ports["backend"],
            "frontend": ports["frontend"],
            "deterministic": True,
            "reserved": False,
        },
        "productionPathGuard": {
            "status": "PASS",
            "database": "PASS",
            "media": "PASS",
            "secrets": "PASS",
            "symlinkEscape": "PASS",
            "sources": list(contract.source_files),
        },
        "credentials": credentials,
        "state": PLANNED_STATE,
        "createdAt": stamp,
        "updatedAt": stamp,
    }
def _safe_json(payload: Mapping[str, object]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
def write_planned_environment(
    repo_root: Path | str,
    *,
    environment: Mapping[str, str] | None = None,
    production_contract: ProductionPathContract | None = None,
    timestamp: str | None = None,
) -> dict[str, object]:
    """Persist only the planned layout and sanitized state/receipt documents."""
    identity = load_environment_identity(repo_root)
    contract = production_contract or discover_production_path_contract(identity.worktree_path)
    plan = build_environment_plan(
        identity.worktree_path,
        environment=environment,
        production_contract=contract,
        timestamp=timestamp,
    )
    paths = derive_environment_paths(identity)
    for directory in (
        paths.environment_root / "db",
        paths.media_root,
        paths.secret_root,
        paths.state_root,
    ):
        directory.mkdir(parents=True, exist_ok=True)
    # Re-resolve after creation so pre-existing directory links cannot escape.
    validate_environment_paths(identity, paths, contract)
    state_document = {"documentType": "environment-state", **plan}
    receipt_document = {"documentType": "environment-receipt", **plan}
    atomic_write_text(paths.environment_state_path, _safe_json(state_document))
    atomic_write_text(paths.receipt_path, _safe_json(receipt_document))
    return receipt_document
