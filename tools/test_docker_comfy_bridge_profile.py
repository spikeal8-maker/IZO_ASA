"""Pinned native Compose rendering is offline and leaves sealed format2 unchanged."""
from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path

import pytest

from tools import docker_comfy_bridge_profile as bridge
from tools.docker_test_bundle import copy_comfy_profile_assets
from tools.docker_test_bundle_format import BundleError, file_hash, json_bytes, verify
from tools.test_docker_synthetic_runtime import repin
from tools.test_docker_test_bundle_images import make_portable

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "ops/docker/dev/compose.comfyui-shadow.yml"
NAMESPACE = "izo-unit-1234567890abcdef"


def fixture(tmp_path):
    bundle, _, manifest, _, _ = make_portable(tmp_path / "bundle")
    manifest["tooling_sha"] = manifest["source_sha"]
    (bundle / "frontend/release-manifest.json").write_bytes(json_bytes({
        "git_sha": manifest["source_sha"], "release_id": manifest["release_id"], "dirty": False}))
    copy_comfy_profile_assets(ROOT, bundle)
    manifest_pin = repin(bundle, manifest)
    base = json.loads((bundle / "compose.json").read_text())
    instance = tmp_path / "instance"
    instance.mkdir()
    old_release = "f" * 12 + "-20261025120000"
    old_frontend = str(instance / ("frontend-" + old_release))
    for role, service in base["services"].items():
        service["labels"]["org.opencontainers.image.revision"] = "f" * 40
        service["restart"] = "unless-stopped"
        for mount in service.get("volumes", []):
            if mount["type"] == "bind":
                mount["source"] = old_frontend
                if role != "web":
                    mount["target"] = "/opt/izo/.runtime/releases/frontend/" + old_release
    backend, web, guard = (base["services"][k] for k in ("backend", "web", "guard"))
    backend["environment"]["IZO_RELEASE_MANIFEST"] = "/opt/izo/.runtime/releases/frontend/" + old_release + "/release-manifest.json"
    backend["environment"].update(TRUSTED_HOSTS="localhost,127.0.0.1,private.invalid",
        CORS_ALLOWED_ORIGINS="https://private.invalid", TRUSTED_COOKIE_SECURE="true", TRUSTED_COOKIE_SAMESITE="lax")
    guard.update(user="0:0", read_only=True, tmpfs=["/tmp"],
                 sysctls={"net.ipv6.conf.all.disable_ipv6": "1"},
                 healthcheck={"test": ["CMD", "python", "/network_guard.py", "--check"]})
    web["read_only"] = True
    nginx = instance / "nginx.conf"
    nginx.write_text("events {}\nhttp {}\n")
    web["volumes"].append({"type": "bind", "source": str(nginx), "target": "/etc/nginx/nginx.conf",
                            "read_only": True, "bind": {"create_host_path": False}})
    base["services"]["init-db"] = copy.deepcopy(backend)
    base["services"]["init-db"].update(command=["python", "-c", "purpose='empty-test-only'"], restart="no")
    base["services"]["init-db"]["labels"]["io.izo.role"] = "empty-test-schema-init"
    base_file = instance / "docker-compose.yml"
    base_file.write_bytes(json_bytes(base))
    frontend = instance / ("frontend-" + manifest["release_id"])
    shutil.copytree(bundle / "frontend", frontend)
    return bundle, manifest_pin, manifest, base, base_file, frontend, nginx


def render(base, manifest, frontend, template=None, **kwargs):
    arguments = {"upstream_ip": "192.168.1.112", "upstream_port": 8188, "namespace": NAMESPACE, "mode": "capabilities"}
    return bridge.render(base, manifest, template or json.loads(TEMPLATE.read_text()), frontend, **(arguments | kwargs))


def cli_arguments(values):
    bundle, pin, manifest, base, base_file, frontend, nginx = values
    return ["--bundle", str(bundle), "--manifest-sha256", pin, "--base-compose", str(base_file),
        "--base-sha256", file_hash(base_file)[1], "--frontend", str(frontend),
        "--expect-source", manifest["source_sha"], "--expect-release", manifest["release_id"],
        "--upstream-ip", "192.168.1.112", "--upstream-port", "8188", "--namespace", NAMESPACE,
        "--mode", "capabilities", "--accept-private-http", "--nginx-sha256", file_hash(nginx)[1]]


def test_native_shape_and_release_chain_preserved_with_exact_profile_delta(tmp_path):
    bundle, pin, manifest, base, _, frontend, _ = fixture(tmp_path)
    prior = copy.deepcopy(base)
    result = render(base, manifest, frontend)
    assert base == prior and verify(bundle, pin) == manifest
    assert result["volumes"] == base["volumes"] and result["networks"] == base["networks"]
    assert set(result["services"]) == {"backend", "web", "guard", "init-db", "comfy-proxy"}
    assert {s["image"] for s in result["services"].values()} == set(manifest["images"].values())
    for role, service in result["services"].items():
        assert service["labels"]["org.opencontainers.image.revision"] == manifest["source_sha"]
        if role in {"backend", "init-db"}:
            assert manifest["release_id"] in service["environment"]["IZO_RELEASE_MANIFEST"]
    for field in ("TRUSTED_HOSTS", "CORS_ALLOWED_ORIGINS", "TRUSTED_COOKIE_SECURE", "TRUSTED_COOKIE_SAMESITE"):
        assert result["services"]["backend"]["environment"][field] == base["services"]["backend"]["environment"][field]
    assert result["services"]["init-db"]["command"] == base["services"]["init-db"]["command"]
    assert result["services"]["init-db"]["environment"]["COMFYUI_BASE_URL"] == "http://127.0.0.1:1"
    assert result["services"]["backend"]["environment"]["COMFYUI_NATIVE4B_ONLY"] == "true"
    assert result["services"]["comfy-proxy"]["environment"]["IZO_COMFY_MODE"] == "capabilities"
    assert "comfy-proxy" not in json.loads((bundle / "compose.json").read_text())["services"]
    assert manifest["model_execution"] is False and manifest["production_authorized"] is False


@pytest.mark.parametrize("change", ["command", "user", "privileged", "egress", "secret", "bind", "guard-command",
    "guard-env", "guard-uid", "namespace", "port", "unknown-service", "image", "init-command"])
def test_untrusted_base_changes_rejected_before_profile(tmp_path, change):
    _, _, manifest, base, _, frontend, _ = fixture(tmp_path)
    backend, guard = base["services"]["backend"], base["services"]["guard"]
    if change == "command": backend["command"] = ["sh", "-c", "unsafe"]
    if change == "user": backend["user"] = "10002:10002"
    if change == "privileged": backend["privileged"] = True
    if change == "egress": backend["network_mode"] = "host"
    if change == "secret": backend["environment"]["OPENROUTER_API_KEY"] = "forbidden"
    if change == "bind": backend["volumes"].append({"type": "bind", "source": "/var/run/docker.sock", "target": "/socket"})
    if change == "guard-command": guard["command"] = ["sleep", "infinity"]
    if change == "guard-env": guard["environment"] = {"IZO_SHADOW_EGRESS_PROFILE": "comfyui-private-v1"}
    if change == "guard-uid": guard["user"] = "10002:10002"
    if change == "namespace": base["volumes"]["sqlite-data"]["name"] = "foreign_sqlite-data"
    if change == "port": guard["ports"][0]["host_ip"] = "0.0.0.0"
    if change == "unknown-service": base["services"]["foreign"] = copy.deepcopy(backend)
    if change == "image": backend["image"] = "untrusted:latest"
    if change == "init-command": base["services"]["init-db"]["command"] = ["python", "unsafe.py"]
    with pytest.raises(BundleError):
        render(base, manifest, frontend)


@pytest.mark.parametrize("change", ["backend-env", "guard-env", "proxy-command", "proxy-uid", "proxy-env",
    "proxy-volume", "proxy-port", "proxy-network", "proxy-caps", "proxy-health", "proxy-resource", "fourth-image"])
def test_profile_cannot_add_destinations_mounts_credentials_or_override_commands(tmp_path, change):
    _, _, manifest, base, _, frontend, _ = fixture(tmp_path)
    template = json.loads(TEMPLATE.read_text()); services = template["services"]
    service = services["comfy-proxy"]
    if change == "backend-env": services["backend"]["environment"]["HTTPS_PROXY"] = "http://outside"
    if change == "guard-env": services["guard"]["environment"]["IZO_COMFY_UPSTREAM_IP"] = "10.1.1.1"
    if change == "proxy-command": service["command"] = ["sh", "-c", "unsafe"]
    if change == "proxy-uid": service["user"] = "0:0"
    if change == "proxy-env": service["environment"]["AUTHORIZATION"] = "secret"
    if change == "proxy-volume": service["volumes"] = ["sqlite-data:/data"]
    if change == "proxy-port": service["ports"] = ["0.0.0.0:18188:18188"]
    if change == "proxy-network": service["network_mode"] = "host"
    if change == "proxy-caps": service["cap_add"] = ["NET_ADMIN"]
    if change == "proxy-health": service["healthcheck"]["test"] = ["CMD-SHELL", "unsafe"]
    if change == "proxy-resource": service["pids_limit"] = -1
    if change == "fourth-image": service["image"] = "sha256:" + "f" * 64
    with pytest.raises(BundleError):
        render(base, manifest, frontend, template)


def test_renderer_and_strict_effective_check_are_readonly_and_detect_drift(tmp_path, capsys):
    values = fixture(tmp_path); args = cli_arguments(values)
    before = {str(p): file_hash(p) for p in tmp_path.rglob("*") if p.is_file()}
    assert bridge.main(args) == 0
    config = json.loads(capsys.readouterr().out)
    assert before == {str(p): file_hash(p) for p in tmp_path.rglob("*") if p.is_file()}
    effective = tmp_path / "effective.json"
    effective.write_bytes(json_bytes(config))
    checks = ["--check-compose", str(effective), "--check-sha256", file_hash(effective)[1]]
    assert bridge.main(args + checks) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "BRIDGE_COMPOSE_VERIFIED"
    config["services"]["backend"]["environment"]["COMFYUI_MOCK_FALLBACK"] = "true"
    effective.write_bytes(json_bytes(config)); checks[-1] = file_hash(effective)[1]
    assert bridge.main(args + checks) == 2
    assert json.loads(capsys.readouterr().out)["reason"] == "BRIDGE_EFFECTIVE_COMPOSE_DRIFT"


@pytest.mark.parametrize("change", ["base-pin", "source", "release", "assets", "nginx", "no-opt-in", "bundle-profile"])
def test_cli_pins_release_bytes_base_config_and_explicit_operator_opt_in(tmp_path, capsys, change):
    values = fixture(tmp_path); args = cli_arguments(values)
    bundle, _, manifest, _, base_file, frontend, nginx = values
    if change == "base-pin": base_file.write_bytes(base_file.read_bytes() + b"\n")
    if change == "source": args[args.index("--expect-source") + 1] = "f" * 40
    if change == "release": args[args.index("--expect-release") + 1] = "f" * 12 + "-20261025120000"
    if change == "assets": (frontend / "assets/index-unit.js").write_text("tampered")
    if change == "nginx": nginx.write_text("tampered")
    if change == "no-opt-in": args.remove("--accept-private-http")
    if change == "bundle-profile":
        manifest["model_execution"] = True
        args[args.index("--manifest-sha256") + 1] = repin(bundle, manifest)
    assert bridge.main(args) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "BLOCKED"


def test_bad_local_image_mapping_namespace_and_address_refused(tmp_path):
    _, _, manifest, base, _, frontend, _ = fixture(tmp_path)
    for arguments in ({"images": {**manifest["images"], "guard": "sha256:" + "f" * 64}},
                      {"namespace": "../foreign"}, {"upstream_ip": "169.254.169.254"},
                      {"mode": "unrestricted"}, {"upstream_port": 0}):
        with pytest.raises(BundleError):
            render(base, manifest, frontend, **arguments)
