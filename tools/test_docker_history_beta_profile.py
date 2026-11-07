"""Offline history binding controls; no Docker, provider, database or server I/O."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from tools import docker_history_beta_profile as history
from tools.docker_test_bundle_format import BundleError, file_hash, json_bytes, runtime_environment, verify
from tools.test_docker_comfy_bridge_profile import (
    TEMPLATE, cli_arguments as bridge_arguments, fixture as bridge_fixture, native_effective,
)
from tools.test_docker_synthetic_runtime import repin


def fixture(tmp_path):
    values = list(bridge_fixture(tmp_path))
    bundle, _, manifest, base, base_file, frontend, _ = values
    manifest["schema"] = 8
    config = json.loads((bundle / "compose.json").read_text())
    config["services"]["backend"]["environment"].update(runtime_environment(8))
    metadata = json.loads((bundle / "frontend/release-manifest.json").read_text())
    metadata["schema_compatibility"] = {"min_version": 8, "max_version": 8}
    for root in (bundle / "frontend", frontend):
        (root / "release-manifest.json").write_bytes(json_bytes(metadata))
    values[1] = repin(bundle, manifest, config)
    base["name"] = history.PROJECT
    for kind in ("volumes", "networks"):
        for logical, item in base[kind].items():
            item["name"] = history.PROJECT + "_" + logical
    base["services"]["backend"]["depends_on"] = {
        "init-db": {"condition": "service_completed_successfully", "required": True, "restart": True},
        "guard": {"condition": "service_healthy", "required": True, "restart": True},
    }
    base_file.write_bytes(json_bytes(base))
    return tuple(values)


def parameters():
    return {"scope": history.SCOPE, "snapshot_id": history.SNAPSHOT, "schema": 8,
        "database_volume": history.DATABASE_VOLUME, "media_volume": history.MEDIA_VOLUME,
        "upstream_ip": history.UPSTREAM_IP, "upstream_port": history.UPSTREAM_PORT,
        "namespace": history.NAMESPACE, "mode": "generate-t2i-4b"}


def render(values, **changes):
    _, _, manifest, base, _, frontend, _ = values
    return history.render(base, manifest, json.loads(TEMPLATE.read_text()), frontend,
                          **(parameters() | changes))


def arguments(values):
    args = bridge_arguments(values)
    args[args.index("--namespace") + 1] = history.NAMESPACE
    args[args.index("--mode") + 1] = "generate-t2i-4b"
    return args + ["--helper-sha256", file_hash(Path(history.__file__))[1],
        "--scope", history.SCOPE, "--snapshot-id", history.SNAPSHOT, "--schema-version", "8",
        "--database-volume", history.DATABASE_VOLUME, "--media-volume", history.MEDIA_VOLUME,
        "--accept-history-bind"]


@pytest.mark.parametrize("mode", ["capabilities", "generate-t2i-4b"])
def test_history_delta_keeps_bridge_network_images_and_mount_sources(tmp_path, mode):
    values = fixture(tmp_path)
    bundle, pin, manifest, base, _, frontend, _ = values
    before = copy.deepcopy((base, manifest))
    expected = history.bridge.render(base, manifest, json.loads(TEMPLATE.read_text()), frontend,
        upstream_ip=history.UPSTREAM_IP, upstream_port=history.UPSTREAM_PORT,
        namespace=history.NAMESPACE, mode=mode)
    result = render(values, mode=mode)
    assert (base, manifest) == before and verify(bundle, pin) == manifest
    assert result["name"] == history.PROJECT
    assert set(result["services"]) == {"backend", "web", "guard", "comfy-proxy"}
    assert result["networks"] == expected["networks"]
    for role in ("guard", "web", "comfy-proxy"):
        assert result["services"][role] == expected["services"][role]
    backend = result["services"]["backend"]
    old_backend = expected["services"]["backend"]
    assert {k: v for k, v in backend.items() if k not in {"environment", "depends_on"}} == {
        k: v for k, v in old_backend.items() if k not in {"environment", "depends_on"}}
    assert backend["environment"] == old_backend["environment"] | history.HISTORY_ENV
    assert backend["depends_on"] == {k: v for k, v in old_backend["depends_on"].items() if k != "init-db"}
    assert all("init-db" not in s.get("depends_on", {}) for s in result["services"].values())
    assert result["volumes"] == {
        "sqlite-data": {"external": True, "name": history.DATABASE_VOLUME},
        "media-data": {"external": True, "name": history.MEDIA_VOLUME},
    }


@pytest.mark.parametrize("key,value,reason", [
    ("scope", "another-scope", "HISTORY_SCOPE_INVALID"),
    ("snapshot_id", "20261105T190706.420010Z", "HISTORY_SNAPSHOT_INVALID"),
    ("schema", 7, "HISTORY_SCHEMA_INVALID"),
    ("schema", 8.0, "HISTORY_SCHEMA_INVALID"),
    ("schema", True, "HISTORY_SCHEMA_INVALID"),
    ("database_volume", history.PROJECT + "_sqlite-data", "HISTORY_VOLUMES_INVALID"),
    ("database_volume", history.MEDIA_VOLUME, "HISTORY_VOLUMES_INVALID"),
    ("media_volume", history.PROJECT + "_media-data", "HISTORY_VOLUMES_INVALID"),
    ("upstream_ip", "192.168.1.113", "HISTORY_GPU_ROUTE_INVALID"),
    ("upstream_port", 8189, "HISTORY_GPU_ROUTE_INVALID"),
    ("upstream_port", 8188.0, "HISTORY_GPU_ROUTE_INVALID"),
    ("namespace", "izo-other-123456789012345", "HISTORY_GPU_ROUTE_INVALID"),
    ("mode", "generate-9b", "BRIDGE_ACTIVATION_INVALID"),
])
def test_binding_and_gpu_route_cannot_drift(tmp_path, key, value, reason):
    values = fixture(tmp_path)
    before = copy.deepcopy(values[3])
    with pytest.raises(BundleError, match=reason):
        render(values, **{key: value})
    assert values[3] == before


@pytest.mark.parametrize("change", ["project", "schema", "schema-type", "init-missing", "init-command",
    "init-env", "init-dependency", "privileged", "public-port", "writable-assets", "foreign-volume"])
def test_existing_base_security_and_initializer_checks_are_retained(tmp_path, change):
    values = fixture(tmp_path)
    base, manifest = values[3], values[2]
    backend = base["services"]["backend"]
    if change == "project": base["name"] = "izo-asa-other-project"
    elif change == "schema": manifest["schema"] = 7
    elif change == "schema-type": manifest["schema"] = 8.0
    elif change == "init-missing": del base["services"]["init-db"]
    elif change == "init-command": base["services"]["init-db"]["command"] = ["python", "-c", "wrong"]
    elif change == "init-env": base["services"]["init-db"]["environment"]["DATABASE_URL"] = "/other"
    elif change == "init-dependency": backend["depends_on"]["init-db"]["condition"] = "service_started"
    elif change == "privileged": backend["privileged"] = True
    elif change == "public-port": base["services"]["guard"]["ports"][0]["host_ip"] = "0.0.0.0"
    elif change == "writable-assets": backend["volumes"][-1]["read_only"] = False
    else: base["volumes"]["sqlite-data"]["name"] = "foreign"
    before = copy.deepcopy(base)
    with pytest.raises(BundleError): render(values)
    assert base == before


def test_cli_render_and_effective_verification_are_readonly(tmp_path, capsys):
    values = fixture(tmp_path)
    args = arguments(values)
    before = {str(p): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    assert history.main(args) == 0
    config = json.loads(capsys.readouterr().out)
    assert config == render(values)
    assert {str(p): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()} == before
    observed = tmp_path / "effective.json"
    observed.write_bytes(json_bytes(native_effective(config)))
    check = ["--check-compose", str(observed), "--check-sha256", file_hash(observed)[1],
             "--compose-version", history.bridge.COMPOSE_VERSION]
    assert history.main(args + check) == 0
    receipt = json.loads(capsys.readouterr().out)
    assert receipt["status"] == "HISTORY_BETA_COMPOSE_VERIFIED"
    assert receipt["schema_version"] == 8 and receipt["snapshot_id"] == history.SNAPSHOT
    assert receipt["runtime_verified"] is False and receipt["clone_and_seal_proof_required"] is True
    assert receipt["database_volume"] == history.DATABASE_VOLUME


@pytest.mark.parametrize("flag", ["--accept-private-http", "--accept-history-bind"])
def test_cli_requires_both_explicit_bindings(tmp_path, capsys, flag):
    args = arguments(fixture(tmp_path)); args.remove(flag)
    assert history.main(args) == 2
    assert json.loads(capsys.readouterr().out)["reason"] == "HISTORY_EXPLICIT_ACCEPTANCE_REQUIRED"


@pytest.mark.parametrize("flag", ["--helper-sha256", "--manifest-sha256", "--base-sha256", "--nginx-sha256",
    "--expect-source", "--expect-release"])
def test_cli_rejects_wrong_identity_pins(tmp_path, capsys, flag):
    args = arguments(fixture(tmp_path))
    args[args.index(flag) + 1] = "0" * (40 if flag == "--expect-source" else 64)
    assert history.main(args) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "BLOCKED"


@pytest.mark.parametrize("change", ["front-bytes", "front-schema", "bridge-helper", "images-pin", "images-mapping"])
def test_cli_retains_frontend_helper_and_selected_image_proof(tmp_path, capsys, change):
    values = list(fixture(tmp_path))
    bundle, _, manifest, _, _, frontend, _ = values
    if change == "front-bytes": (frontend / "index.html").write_text("changed")
    elif change == "front-schema":
        metadata = json.loads((frontend / "release-manifest.json").read_text())
        metadata["schema_compatibility"] = {"min_version": 7, "max_version": 8}
        for root in (frontend, bundle / "frontend"):
            (root / "release-manifest.json").write_bytes(json_bytes(metadata))
        values[1] = repin(bundle, manifest)
    elif change == "bridge-helper":
        (bundle / "docker_comfy_bridge_profile.py").write_text("unreviewed helper")
        values[1] = repin(bundle, manifest)
    args = arguments(values)
    if change.startswith("images"):
        images = tmp_path / "selected-images.json"
        mapping = dict(manifest["images"])
        if change == "images-mapping": mapping["backend"] = "sha256:" + "f" * 64
        images.write_bytes(json_bytes(mapping))
        args += ["--images", str(images), "--images-sha256", "0" * 64 if change == "images-pin" else file_hash(images)[1]]
    assert history.main(args) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "BLOCKED"


@pytest.mark.parametrize("change", ["volume", "history-flag", "snapshot", "registration", "init", "egress"])
def test_effective_history_compose_drift_is_rejected(tmp_path, capsys, change):
    values = fixture(tmp_path)
    config = native_effective(render(values))
    backend = config["services"]["backend"]
    if change == "volume": config["volumes"]["sqlite-data"]["name"] = history.PROJECT + "_sqlite-data"
    elif change == "history-flag": backend["environment"]["IZO_PREPROD_PRESERVE_HISTORY"] = "0"
    elif change == "snapshot": backend["environment"]["IZO_HISTORY_SNAPSHOT_ID"] = "wrong"
    elif change == "registration": backend["environment"]["IZO_CLOSED_BETA"] = "0"
    elif change == "init": config["services"]["init-db"] = copy.deepcopy(backend)
    else: config["services"]["guard"]["environment"]["IZO_COMFY_UPSTREAM_PORT"] = "9999"
    path = tmp_path / "observed.json"; path.write_bytes(json_bytes(config))
    args = arguments(values) + ["--check-compose", str(path), "--check-sha256", file_hash(path)[1],
                                "--compose-version", history.bridge.COMPOSE_VERSION]
    assert history.main(args) == 2
    assert json.loads(capsys.readouterr().out)["reason"] == "BRIDGE_EFFECTIVE_COMPOSE_DRIFT"
