from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from backend.app.database import migrations
from backend.app.release_identity import frontend_asset_manifest as runtime_asset_manifest
from tools.build_release_manifest import (
    build_manifest,
    frontend_asset_inventory,
    normalize_runtime_version,
)
from tools import build_release_manifest as manifest_builder


def _release(tmp_path: Path) -> Path:
    release = tmp_path / "release"
    assets = release / "assets"
    assets.mkdir(parents=True)
    (release / "index.html").write_text("<html>release</html>\n", encoding="utf-8")
    (assets / "index-abc.js").write_text("console.log('release')\n", encoding="utf-8")
    return release


def test_release_contract_covers_current_database_schema() -> None:
    root = Path(__file__).resolve().parents[1]
    contract = json.loads(
        (root / "architecture" / "contract.json").read_text(encoding="utf-8")
    )
    current_schema_version = max(
        value.version
        for value in vars(migrations).values()
        if isinstance(value, migrations.MigrationDefinition)
    )

    assert (
        contract["release_contract"]["schema_compatibility"]["max_version"]
        == current_schema_version
    )


def test_asset_inventory_is_deterministic_and_excludes_release_metadata(tmp_path: Path) -> None:
    release = _release(tmp_path)

    first_rows, first_hash = frontend_asset_inventory(release)
    (release / "release.json").write_text("{}\n", encoding="utf-8")
    (release / "release-manifest.json").write_text("{}\n", encoding="utf-8")
    second_rows, second_hash = frontend_asset_inventory(release)

    assert first_rows == second_rows
    assert first_hash == second_hash
    assert first_hash.startswith("sha256:")
    assert [row["path"] for row in first_rows] == ["assets/index-abc.js", "index.html"]
    runtime_count, runtime_hash = runtime_asset_manifest(release)
    assert runtime_count == len(first_rows)
    assert runtime_hash == first_hash


def test_asset_hash_changes_when_frontend_content_changes(tmp_path: Path) -> None:
    release = _release(tmp_path)
    _, before = frontend_asset_inventory(release)

    (release / "assets" / "index-abc.js").write_text("console.log('changed')\n", encoding="utf-8")
    _, after = frontend_asset_inventory(release)

    assert after != before


def test_release_git_commands_trust_the_exact_candidate_worktree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["cwd"] = kwargs["cwd"]
        return subprocess.CompletedProcess(command, 0, stdout="clean\n", stderr="")

    monkeypatch.setattr(manifest_builder.subprocess, "run", fake_run)

    assert manifest_builder._run(tmp_path, "git", "status", "--porcelain") == "clean"
    assert captured["command"] == [
        "git",
        "-c",
        f"safe.directory={tmp_path}",
        "status",
        "--porcelain",
    ]
    assert captured["cwd"] == tmp_path


def test_manifest_has_exact_required_release_fields(tmp_path: Path) -> None:
    release = _release(tmp_path)
    manifest = build_manifest(
        release_path=release,
        release_id="a" * 12 + "-20260717220000",
        git_sha="a" * 40,
        built_at="2026-07-17T19:00:00+00:00",
        python_version="3.11.9",
        node_version="v24.14.1",
        schema_min_version=1,
        schema_max_version=1,
    )

    assert manifest == {
        "manifest_version": 1,
        "release_id": "a" * 12 + "-20260717220000",
        "git_sha": "a" * 40,
        "dirty": False,
        "built_at": "2026-07-17T19:00:00+00:00",
        "frontend_asset_manifest_hash": manifest["frontend_asset_manifest_hash"],
        "frontend_asset_count": 2,
        "python_version": "3.11.9",
        "node_version": "24.14.1",
        "schema_compatibility": {"min_version": 1, "max_version": 1},
    }
    assert json.dumps(manifest, sort_keys=True) == json.dumps(manifest, sort_keys=True)


@pytest.mark.parametrize("value", ["", "3.11", "version-3.11.9", "24.14.1.0"])
def test_runtime_version_normalization_rejects_non_exact_versions(value: str) -> None:
    with pytest.raises(ValueError):
        normalize_runtime_version(value)


def test_manifest_rejects_dirty_identity_shapes_before_writing(tmp_path: Path) -> None:
    release = _release(tmp_path)

    with pytest.raises(ValueError, match="full lowercase commit"):
        build_manifest(
            release_path=release,
            release_id="a" * 12 + "-20260717220000",
            git_sha="a" * 12,
            built_at="2026-07-17T19:00:00+00:00",
            python_version="3.11.9",
            node_version="24.14.1",
            schema_min_version=1,
            schema_max_version=1,
        )


def test_manifest_rejects_release_id_for_another_commit(tmp_path: Path) -> None:
    release = _release(tmp_path)

    with pytest.raises(ValueError, match="commit prefix"):
        build_manifest(
            release_path=release,
            release_id="b" * 12 + "-20260717220000",
            git_sha="a" * 40,
            built_at="2026-07-17T19:00:00+00:00",
            python_version="3.11.9",
            node_version="24.14.1",
            schema_min_version=1,
            schema_max_version=1,
        )
