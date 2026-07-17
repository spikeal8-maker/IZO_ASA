"""Immutable release identity loading and production runtime validation.

The module is safe to import. It reads a manifest only when the caller asks it
to and never imports the FastAPI application, opens SQLite, touches media, or
starts a process.
"""

from __future__ import annotations

import json
import hashlib
import os
import platform
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
RELEASE_ID = re.compile(r"^[0-9a-f]{12}-[0-9]{14}$")
SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
RUNTIME_VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
PRODUCTION_NAMES = {"production", "prod", "live"}
RELEASE_METADATA_FILES = {"release.json", "release-manifest.json"}


class ReleaseIdentityError(RuntimeError):
    """Secret-free, stable release validation failure."""

    def __init__(self, *codes: str):
        unique_codes = tuple(dict.fromkeys(code for code in codes if code))
        self.codes = unique_codes or ("RELEASE_IDENTITY_INVALID",)
        super().__init__("Unsafe release identity: " + ",".join(self.codes))


@dataclass(frozen=True)
class SchemaCompatibility:
    min_version: int
    max_version: int

    def as_dict(self) -> dict[str, int]:
        return {
            "min_version": self.min_version,
            "max_version": self.max_version,
        }


@dataclass(frozen=True)
class ReleaseIdentity:
    managed: bool
    manifest_version: int | None
    release_id: str
    git_sha: str | None
    dirty: bool | None
    built_at: str | None
    frontend_asset_manifest_hash: str | None
    frontend_asset_count: int | None
    python_version: str
    node_version: str | None
    schema_compatibility: SchemaCompatibility | None

    @classmethod
    def unmanaged(cls, *, python_version: str | None = None) -> "ReleaseIdentity":
        return cls(
            managed=False,
            manifest_version=None,
            release_id="unmanaged",
            git_sha=None,
            dirty=None,
            built_at=None,
            frontend_asset_manifest_hash=None,
            frontend_asset_count=None,
            python_version=python_version or platform.python_version(),
            node_version=None,
            schema_compatibility=None,
        )

    @property
    def frontend_build_id(self) -> str:
        return self.release_id if self.managed else "unknown"

    def public_payload(self) -> dict[str, Any]:
        return {
            "release_id": self.release_id,
            "build": self.release_id,
            "backend_commit": self.git_sha,
            "frontend_build": self.frontend_build_id,
            "built_at": self.built_at,
            "frontend_asset_manifest_hash": self.frontend_asset_manifest_hash,
            "python_version": self.python_version,
            "node_version": self.node_version,
            "schema_compatibility": (
                self.schema_compatibility.as_dict()
                if self.schema_compatibility is not None
                else None
            ),
        }


def _production_requested(environment: Mapping[str, str]) -> bool:
    values = (
        environment.get("IZO_RUNTIME_PROFILE", ""),
        environment.get("APP_ENV", ""),
        environment.get("ENV", ""),
        environment.get("MODE", ""),
    )
    return any(value.strip().lower() in PRODUCTION_NAMES for value in values)


def _valid_built_at(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def release_manifest_errors(payload: Any) -> tuple[str, ...]:
    if not isinstance(payload, dict):
        return ("RELEASE_MANIFEST_OBJECT_REQUIRED",)

    errors: list[str] = []
    if payload.get("manifest_version") != 1:
        errors.append("RELEASE_MANIFEST_VERSION_UNSUPPORTED")
    release_id = str(payload.get("release_id", ""))
    git_sha = str(payload.get("git_sha", ""))
    valid_release_id = RELEASE_ID.fullmatch(release_id) is not None
    valid_git_sha = GIT_SHA.fullmatch(git_sha) is not None
    if not valid_release_id:
        errors.append("RELEASE_ID_INVALID")
    if not valid_git_sha:
        errors.append("RELEASE_GIT_SHA_INVALID")
    if valid_release_id and valid_git_sha and not release_id.startswith(git_sha[:12] + "-"):
        errors.append("RELEASE_ID_GIT_SHA_MISMATCH")
    if payload.get("dirty") is not False:
        errors.append("DIRTY_RELEASE_FORBIDDEN")
    if not _valid_built_at(payload.get("built_at")):
        errors.append("RELEASE_BUILT_AT_INVALID")
    if not SHA256.fullmatch(str(payload.get("frontend_asset_manifest_hash", ""))):
        errors.append("FRONTEND_ASSET_MANIFEST_HASH_INVALID")
    asset_count = payload.get("frontend_asset_count")
    if not isinstance(asset_count, int) or isinstance(asset_count, bool) or asset_count <= 0:
        errors.append("FRONTEND_ASSET_COUNT_INVALID")
    if not RUNTIME_VERSION.fullmatch(str(payload.get("python_version", ""))):
        errors.append("PYTHON_VERSION_INVALID")
    if not RUNTIME_VERSION.fullmatch(str(payload.get("node_version", ""))):
        errors.append("NODE_VERSION_INVALID")

    schema = payload.get("schema_compatibility")
    if not isinstance(schema, dict):
        errors.append("SCHEMA_COMPATIBILITY_INVALID")
    else:
        minimum = schema.get("min_version")
        maximum = schema.get("max_version")
        if (
            not isinstance(minimum, int)
            or isinstance(minimum, bool)
            or not isinstance(maximum, int)
            or isinstance(maximum, bool)
            or minimum <= 0
            or maximum < minimum
        ):
            errors.append("SCHEMA_COMPATIBILITY_INVALID")
    return tuple(errors)


def parse_release_manifest(payload: Any) -> ReleaseIdentity:
    errors = release_manifest_errors(payload)
    if errors:
        raise ReleaseIdentityError(*errors)
    schema = payload["schema_compatibility"]
    return ReleaseIdentity(
        managed=True,
        manifest_version=1,
        release_id=str(payload["release_id"]),
        git_sha=str(payload["git_sha"]),
        dirty=False,
        built_at=str(payload["built_at"]),
        frontend_asset_manifest_hash=str(payload["frontend_asset_manifest_hash"]),
        frontend_asset_count=int(payload["frontend_asset_count"]),
        python_version=str(payload["python_version"]),
        node_version=str(payload["node_version"]),
        schema_compatibility=SchemaCompatibility(
            min_version=int(schema["min_version"]),
            max_version=int(schema["max_version"]),
        ),
    )


def expected_project_python(backend_root: Path) -> Path:
    suffix = Path("Scripts/python.exe") if os.name == "nt" else Path("bin/python")
    return (backend_root / ".venv" / suffix).resolve()


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def frontend_asset_manifest(release_root: Path) -> tuple[int, str]:
    """Return the deterministic asset count/hash used by release manifests."""

    digest = hashlib.sha256()
    count = 0
    try:
        for path in sorted(release_root.rglob("*")):
            if path.is_symlink():
                raise ReleaseIdentityError("FRONTEND_RELEASE_SYMLINK_FORBIDDEN")
            if not path.is_file() or path.name in RELEASE_METADATA_FILES:
                continue
            relative = path.relative_to(release_root).as_posix()
            file_digest = hashlib.sha256()
            size = 0
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    size += len(chunk)
                    file_digest.update(chunk)
            digest.update(relative.encode("utf-8"))
            digest.update(b"\0")
            digest.update(str(size).encode("ascii"))
            digest.update(b"\0")
            digest.update(file_digest.hexdigest().encode("ascii"))
            digest.update(b"\n")
            count += 1
    except ReleaseIdentityError:
        raise
    except (OSError, UnicodeError, ValueError):
        raise ReleaseIdentityError("FRONTEND_ASSET_INVENTORY_UNREADABLE") from None
    return count, "sha256:" + digest.hexdigest()


def assert_release_schema_compatible(identity: ReleaseIdentity, schema_version: int) -> None:
    if not identity.managed:
        return
    schema = identity.schema_compatibility
    if (
        schema is None
        or isinstance(schema_version, bool)
        or not isinstance(schema_version, int)
        or not schema.min_version <= schema_version <= schema.max_version
    ):
        raise ReleaseIdentityError("SCHEMA_VERSION_INCOMPATIBLE")


def load_runtime_release_identity(
    *,
    environment: Mapping[str, str],
    repo_root: Path,
    backend_root: Path,
    python_executable: Path,
    python_version: str | None = None,
) -> ReleaseIdentity:
    """Load the release manifest and fail closed for a production runtime."""

    requested = _production_requested(environment)
    errors: list[str] = []
    if requested and environment.get("APP_ENV", "").strip().lower() != "production":
        errors.append("APP_ENV_MUST_BE_PRODUCTION")

    raw_path = environment.get("IZO_RELEASE_MANIFEST", "").strip()
    if not raw_path:
        if requested:
            errors.append("RELEASE_MANIFEST_REQUIRED")
        if errors:
            raise ReleaseIdentityError(*errors)
        return ReleaseIdentity.unmanaged(python_version=python_version)

    manifest_path = Path(raw_path).expanduser().resolve()
    allowed_root = (repo_root / ".runtime" / "releases" / "frontend").resolve()
    if not _is_within(manifest_path, allowed_root):
        errors.append("RELEASE_MANIFEST_OUTSIDE_RUNTIME")
    if manifest_path.name != "release-manifest.json":
        errors.append("RELEASE_MANIFEST_NAME_INVALID")
    if not manifest_path.is_file():
        errors.append("RELEASE_MANIFEST_NOT_FOUND")
    if errors:
        raise ReleaseIdentityError(*errors)

    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise ReleaseIdentityError("RELEASE_MANIFEST_UNREADABLE") from None
    identity = parse_release_manifest(payload)
    if manifest_path.parent.name != identity.release_id:
        errors.append("RELEASE_DIRECTORY_ID_MISMATCH")
    asset_count, asset_hash = frontend_asset_manifest(manifest_path.parent)
    if asset_count != identity.frontend_asset_count:
        errors.append("FRONTEND_ASSET_COUNT_MISMATCH")
    if asset_hash != identity.frontend_asset_manifest_hash:
        errors.append("FRONTEND_ASSET_MANIFEST_HASH_MISMATCH")

    actual_version = python_version or platform.python_version()
    if identity.python_version != actual_version:
        errors.append("PYTHON_VERSION_MISMATCH")
    expected_python = expected_project_python(backend_root)
    if requested and not expected_python.is_file():
        errors.append("PROJECT_VENV_REQUIRED")
    if requested and python_executable.resolve() != expected_python:
        errors.append("PYTHON_EXECUTABLE_OUTSIDE_PROJECT_VENV")
    if errors:
        raise ReleaseIdentityError(*errors)
    return identity
