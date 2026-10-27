"""Offline checks of rendering and canonical release metadata reuse."""
from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path

import pytest

from tools import docker_test_bundle as build
from tools.docker_test_bundle_format import BundleError, validate_compose
from tools.test_docker_test_bundle_format import make_bundle


def test_persistent_config_removes_build_and_uses_relative_readonly_assets(tmp_path):
    root, _, m = make_bundle(tmp_path / "bundle")
    source = json.loads((root / "compose.json").read_text())
    source["services"]["backend"]["build"] = {"context": "source-checkout"}
    snapshot = copy.deepcopy(source)
    result = build.persistent_config(source, m["project"], m["source_sha"], m["release_id"], m["images"])
    assert source == snapshot
    assert "build" not in result["services"]["backend"]
    assert result["services"]["backend"]["volumes"][0]["source"] == "./frontend"
    assert result["services"]["web"]["volumes"][0]["read_only"] is True
    assert "source-checkout" not in json.dumps(result)
    validate_compose(result, m)


@pytest.mark.parametrize("target_hash", [False, True])
def test_existing_release_identity_uses_host_or_exact_target_assets(tmp_path, target_hash):
    source = tmp_path / "source"
    (source / "backend/app").mkdir(parents=True)
    (source / "ops/docker/dev").mkdir(parents=True)
    shutil.copyfile(Path(__file__).resolve().parents[1] / "backend/app/release_identity.py",
                    source / "backend/app/release_identity.py")
    (source / "ops/docker/dev/Dockerfile.web").write_text("FROM node:24.14.1-bookworm-slim@sha256:test\n")
    assets = tmp_path / "assets"
    assets.mkdir()
    for name in (("AZ.js", "az.js.other", "aZ.js.other") if target_hash else ("index.html",)):
        (assets / name).write_text("controlled asset", encoding="utf-8")
    evidence = (3, "sha256:" + "d" * 64) if target_hash else None
    result = build.release_metadata(source, assets, "a" * 40, "a" * 12 + "-20261027130000",
                                    "2026-10-27T13:00:00+00:00", "3.11.9", target_assets=evidence)
    assert result["frontend_asset_count"] == (3 if target_hash else 1)
    assert result["frontend_asset_manifest_hash"].startswith("sha256:")
    if target_hash: assert result["frontend_asset_manifest_hash"] == evidence[1]
    assert result["python_version"] == "3.11.9" and result["node_version"] == "24.14.1"
    assert result["schema_compatibility"] == {"min_version": 7, "max_version": 7}


def test_source_guard_rejects_wrong_repository_dirty_and_wrong_sha(tmp_path, monkeypatch):
    for origin, head, dirty in [("https://github.com/other/repo", "a" * 40, ""),
                                 ("https://github.com/spikeal8-maker/IZO_ASA.git", "b" * 40, ""),
                                 ("https://github.com/spikeal8-maker/IZO_ASA.git", "a" * 40, " M file")]:
        def fake_git(root, *args):
            return origin if args[0] == "remote" else head if args[0] == "rev-parse" else dirty
        monkeypatch.setattr(build, "git", fake_git)
        with pytest.raises(BundleError, match="CLEAN_EXACT_SOURCE_REQUIRED"):
            build.source_guard(tmp_path, "a" * 40)


def test_compose_extensions_removed_but_unknown_effective_sections_rejected(tmp_path):
    root, _, m = make_bundle(tmp_path / "bundle")
    config = json.loads((root / "compose.json").read_text())
    config["x-worker"] = {"image": "mutable:tag"}
    config["networks"]["shadow"]["ipam"] = {}
    for service in config["services"].values():
        service["entrypoint"] = None
    config["services"]["guard"]["command"] = None
    result = build.persistent_config(config, m["project"], m["source_sha"], m["release_id"], m["images"])
    assert "x-worker" not in result and "mutable:tag" not in json.dumps(result)
    validate_compose(result, m)
    config["include"] = ["outside.yml"]
    with pytest.raises(BundleError, match="UNSUPPORTED_COMPOSE_SECTION"):
        build.persistent_config(config, m["project"], m["source_sha"], m["release_id"], m["images"])
