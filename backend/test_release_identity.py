from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.app.release_identity import (
    ReleaseIdentityError,
    assert_release_schema_compatible,
    expected_project_python,
    frontend_asset_manifest,
    load_runtime_release_identity,
    parse_release_manifest,
    release_manifest_errors,
)


GIT_SHA = "a" * 40
RELEASE_ID = f"{GIT_SHA[:12]}-20260717220000"


def valid_manifest() -> dict[str, object]:
    return {
        "manifest_version": 1,
        "release_id": RELEASE_ID,
        "git_sha": GIT_SHA,
        "dirty": False,
        "built_at": "2026-07-17T19:00:00+00:00",
        "frontend_asset_manifest_hash": "sha256:" + "b" * 64,
        "frontend_asset_count": 12,
        "python_version": "3.11.9",
        "node_version": "24.14.1",
        "schema_compatibility": {"min_version": 1, "max_version": 1},
    }


def _runtime_layout(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    repo_root = tmp_path / "repo"
    backend_root = repo_root / "backend"
    manifest_path = repo_root / ".runtime" / "releases" / "frontend" / RELEASE_ID / "release-manifest.json"
    manifest_path.parent.mkdir(parents=True)
    (manifest_path.parent / "index.html").write_text("<html>release</html>\n", encoding="utf-8")
    asset_count, asset_hash = frontend_asset_manifest(manifest_path.parent)
    payload = valid_manifest()
    payload["frontend_asset_count"] = asset_count
    payload["frontend_asset_manifest_hash"] = asset_hash
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    python_path = expected_project_python(backend_root)
    python_path.parent.mkdir(parents=True)
    python_path.write_bytes(b"test executable")
    return repo_root, backend_root, manifest_path, python_path


def test_manifest_parser_returns_exact_public_identity() -> None:
    identity = parse_release_manifest(valid_manifest())

    assert identity.managed is True
    assert identity.release_id == RELEASE_ID
    assert identity.frontend_build_id == RELEASE_ID
    assert identity.public_payload() == {
        "release_id": RELEASE_ID,
        "build": RELEASE_ID,
        "backend_commit": GIT_SHA,
        "frontend_build": RELEASE_ID,
        "built_at": "2026-07-17T19:00:00+00:00",
        "frontend_asset_manifest_hash": "sha256:" + "b" * 64,
        "python_version": "3.11.9",
        "node_version": "24.14.1",
        "schema_compatibility": {"min_version": 1, "max_version": 1},
    }


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("manifest_version", 2, "RELEASE_MANIFEST_VERSION_UNSUPPORTED"),
        ("release_id", "latest", "RELEASE_ID_INVALID"),
        ("git_sha", "abc", "RELEASE_GIT_SHA_INVALID"),
        ("dirty", True, "DIRTY_RELEASE_FORBIDDEN"),
        ("built_at", "2026-07-17", "RELEASE_BUILT_AT_INVALID"),
        ("frontend_asset_manifest_hash", "sha256:nope", "FRONTEND_ASSET_MANIFEST_HASH_INVALID"),
        ("frontend_asset_count", 0, "FRONTEND_ASSET_COUNT_INVALID"),
        ("python_version", "3.11", "PYTHON_VERSION_INVALID"),
        ("node_version", "v24", "NODE_VERSION_INVALID"),
        ("schema_compatibility", {"min_version": 2, "max_version": 1}, "SCHEMA_COMPATIBILITY_INVALID"),
    ],
)
def test_manifest_validation_fails_closed_with_stable_codes(field: str, value: object, code: str) -> None:
    payload = valid_manifest()
    payload[field] = value

    assert code in release_manifest_errors(payload)
    with pytest.raises(ReleaseIdentityError) as error:
        parse_release_manifest(payload)
    assert code in error.value.codes
    assert str(value) not in str(error.value)


def test_manifest_requires_release_id_commit_prefix() -> None:
    payload = valid_manifest()
    payload["release_id"] = "b" * 12 + "-20260717220000"

    with pytest.raises(ReleaseIdentityError) as error:
        parse_release_manifest(payload)

    assert error.value.codes == ("RELEASE_ID_GIT_SHA_MISMATCH",)


def test_development_without_manifest_is_explicitly_unmanaged(tmp_path: Path) -> None:
    identity = load_runtime_release_identity(
        environment={"APP_ENV": "test"},
        repo_root=tmp_path,
        backend_root=tmp_path / "backend",
        python_executable=Path("python"),
        python_version="3.11.9",
    )

    assert identity.managed is False
    assert identity.release_id == "unmanaged"
    assert identity.frontend_build_id == "unknown"


def test_production_requires_manifest_exact_app_env_and_project_venv(tmp_path: Path) -> None:
    with pytest.raises(ReleaseIdentityError) as error:
        load_runtime_release_identity(
            environment={"IZO_RUNTIME_PROFILE": "production", "APP_ENV": "development"},
            repo_root=tmp_path,
            backend_root=tmp_path / "backend",
            python_executable=Path("python"),
            python_version="3.11.9",
        )

    assert error.value.codes == ("APP_ENV_MUST_BE_PRODUCTION", "RELEASE_MANIFEST_REQUIRED")


def test_production_accepts_canonical_manifest_and_exact_project_python(tmp_path: Path) -> None:
    repo_root, backend_root, manifest_path, python_path = _runtime_layout(tmp_path)

    identity = load_runtime_release_identity(
        environment={
            "IZO_RUNTIME_PROFILE": "production",
            "APP_ENV": "production",
            "IZO_RELEASE_MANIFEST": str(manifest_path),
        },
        repo_root=repo_root,
        backend_root=backend_root,
        python_executable=python_path,
        python_version="3.11.9",
    )

    assert identity.release_id == RELEASE_ID


def test_production_rejects_manifest_outside_runtime_and_global_python(tmp_path: Path) -> None:
    repo_root, backend_root, manifest_path, _ = _runtime_layout(tmp_path)
    outside = repo_root / "release-manifest.json"
    outside.write_text(manifest_path.read_text(encoding="utf-8"), encoding="utf-8")

    with pytest.raises(ReleaseIdentityError) as outside_error:
        load_runtime_release_identity(
            environment={"APP_ENV": "production", "IZO_RELEASE_MANIFEST": str(outside)},
            repo_root=repo_root,
            backend_root=backend_root,
            python_executable=Path("C:/Python/python.exe"),
            python_version="3.11.9",
        )
    assert "RELEASE_MANIFEST_OUTSIDE_RUNTIME" in outside_error.value.codes

    with pytest.raises(ReleaseIdentityError) as python_error:
        load_runtime_release_identity(
            environment={"APP_ENV": "production", "IZO_RELEASE_MANIFEST": str(manifest_path)},
            repo_root=repo_root,
            backend_root=backend_root,
            python_executable=Path("C:/Python/python.exe"),
            python_version="3.11.9",
        )
    assert "PYTHON_EXECUTABLE_OUTSIDE_PROJECT_VENV" in python_error.value.codes


def test_production_rejects_runtime_version_mismatch(tmp_path: Path) -> None:
    repo_root, backend_root, manifest_path, python_path = _runtime_layout(tmp_path)

    with pytest.raises(ReleaseIdentityError) as error:
        load_runtime_release_identity(
            environment={"APP_ENV": "production", "IZO_RELEASE_MANIFEST": str(manifest_path)},
            repo_root=repo_root,
            backend_root=backend_root,
            python_executable=python_path,
            python_version="3.11.8",
        )
    assert error.value.codes == ("PYTHON_VERSION_MISMATCH",)


def test_production_rejects_asset_tampering_and_directory_mismatch(tmp_path: Path) -> None:
    repo_root, backend_root, manifest_path, python_path = _runtime_layout(tmp_path)
    (manifest_path.parent / "index.html").write_text("tampered\n", encoding="utf-8")

    with pytest.raises(ReleaseIdentityError) as tamper_error:
        load_runtime_release_identity(
            environment={"APP_ENV": "production", "IZO_RELEASE_MANIFEST": str(manifest_path)},
            repo_root=repo_root,
            backend_root=backend_root,
            python_executable=python_path,
            python_version="3.11.9",
        )
    assert "FRONTEND_ASSET_MANIFEST_HASH_MISMATCH" in tamper_error.value.codes

    wrong_directory = manifest_path.parent.parent / ("a" * 12 + "-20260717220001")
    wrong_directory.mkdir()
    wrong_manifest = wrong_directory / "release-manifest.json"
    wrong_manifest.write_text(manifest_path.read_text(encoding="utf-8"), encoding="utf-8")
    (wrong_directory / "index.html").write_text("<html>release</html>\n", encoding="utf-8")
    with pytest.raises(ReleaseIdentityError) as directory_error:
        load_runtime_release_identity(
            environment={"APP_ENV": "production", "IZO_RELEASE_MANIFEST": str(wrong_manifest)},
            repo_root=repo_root,
            backend_root=backend_root,
            python_executable=python_path,
            python_version="3.11.9",
        )
    assert "RELEASE_DIRECTORY_ID_MISMATCH" in directory_error.value.codes


def test_managed_release_enforces_schema_compatibility() -> None:
    identity = parse_release_manifest(valid_manifest())

    assert_release_schema_compatible(identity, 1)
    with pytest.raises(ReleaseIdentityError) as error:
        assert_release_schema_compatible(identity, 2)
    assert error.value.codes == ("SCHEMA_VERSION_INCOMPATIBLE",)
