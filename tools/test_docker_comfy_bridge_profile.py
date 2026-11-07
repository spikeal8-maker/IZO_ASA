"""Pinned native Compose rendering is offline and leaves sealed format2 unchanged."""
from __future__ import annotations

import copy
import hashlib
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
MODES = ("capabilities", "generate-t2i-4b")
NATIVE_VERSION = "2.40.3+ds1-0ubuntu1~24.04.1"


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
@pytest.mark.parametrize("mode", MODES)
def test_untrusted_base_changes_rejected_before_profile(tmp_path, change, mode):
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
        render(base, manifest, frontend, mode=mode)


@pytest.mark.parametrize("change", ["backend-env", "guard-env", "proxy-command", "proxy-uid", "proxy-env",
    "proxy-volume", "proxy-port", "proxy-network", "proxy-caps", "proxy-health", "proxy-resource", "fourth-image"])
@pytest.mark.parametrize("mode", MODES)
def test_profile_cannot_add_destinations_mounts_credentials_or_override_commands(tmp_path, change, mode):
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
        render(base, manifest, frontend, template, mode=mode)


@pytest.mark.parametrize("mode", MODES)
def test_renderer_and_strict_effective_check_are_readonly_and_detect_drift(tmp_path, capsys, mode):
    values = fixture(tmp_path); args = cli_arguments(values)
    args[args.index("--mode") + 1] = mode
    before = {str(p): file_hash(p) for p in tmp_path.rglob("*") if p.is_file()}
    assert bridge.main(args) == 0
    config = json.loads(capsys.readouterr().out)
    assert before == {str(p): file_hash(p) for p in tmp_path.rglob("*") if p.is_file()}
    effective = tmp_path / "effective.json"
    effective.write_bytes(json_bytes(config))
    checks = ["--compose-version", NATIVE_VERSION, "--check-compose", str(effective), "--check-sha256", file_hash(effective)[1]]
    assert bridge.main(args + checks) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "BRIDGE_COMPOSE_VERIFIED"
    config["services"]["backend"]["environment"]["COMFYUI_MOCK_FALLBACK"] = "true"
    effective.write_bytes(json_bytes(config)); checks[-1] = file_hash(effective)[1]
    assert bridge.main(args + checks) == 2
    assert json.loads(capsys.readouterr().out)["reason"] == "BRIDGE_EFFECTIVE_COMPOSE_DRIFT"


@pytest.mark.parametrize("change", ["base-pin", "source", "release", "assets", "nginx", "no-opt-in", "bundle-profile"])
@pytest.mark.parametrize("mode", MODES)
def test_cli_pins_release_bytes_base_config_and_explicit_operator_opt_in(tmp_path, capsys, change, mode):
    values = fixture(tmp_path); args = cli_arguments(values)
    args[args.index("--mode") + 1] = mode
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


@pytest.mark.parametrize("mode", MODES)
def test_bad_local_image_mapping_namespace_and_address_refused(tmp_path, mode):
    _, _, manifest, base, _, frontend, _ = fixture(tmp_path)
    for arguments in ({"images": {**manifest["images"], "guard": "sha256:" + "f" * 64}},
                      {"namespace": "../foreign"}, {"upstream_ip": "169.254.169.254"},
                      {"mode": "unrestricted"}, {"upstream_port": 0}):
        with pytest.raises(BundleError):
            render(base, manifest, frontend, **({"mode": mode} | arguments))


DELETE = object()


def native_effective(config, change="all"):
    result = copy.deepcopy(config)
    for role, service in result["services"].items():
        if change in {"all", "entrypoint"}: service["entrypoint"] = None
        if change in {"all", "command"} and role in {"guard", "web"}: service["command"] = None
        if change in {"all", "bind"}:
            for mount in service.get("volumes", []):
                if mount["type"] == "bind": mount["bind"] = {}
        if change in {"all", "dependency"} and role in {"backend", "web", "init-db"}:
            service.setdefault("depends_on", {}).setdefault("guard", {"condition": "service_started", "required": True, "restart": True})
        if change in {"all", "ports"} and role == "guard":
            for port in service["ports"]:
                port.setdefault("protocol", "tcp"); port.setdefault("mode", "ingress"); port["published"] = str(port["published"])
    if change in {"all", "ipam"}: result["networks"]["shadow"]["ipam"] = {}
    return result


def effective_pair(tmp_path, mode):
    _, _, manifest, base, _, frontend, _ = fixture(tmp_path)
    expected = render(base, manifest, frontend, mode=mode)
    return expected, native_effective(expected)


def replace_path(document, path, value):
    parts = [int(part) if part.isdecimal() else part for part in path.split(".")] if path else []
    if not parts: return value
    target = document
    for key in parts[:-1]: target = target[key]
    if value is DELETE: target.pop(parts[-1], None)
    else: target[parts[-1]] = value
    return document


def rejected(expected, observed):
    with pytest.raises(BundleError, match="BRIDGE_EFFECTIVE_COMPOSE_DRIFT"):
        bridge.verify_effective(expected, observed, compose_version=NATIVE_VERSION)


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("change", ["exact", "entrypoint", "command", "bind", "ipam", "dependency", "ports", "all", "native-input"])
def test_pinned_native_defaults_and_exact_json_preserve_both_inputs(tmp_path, mode, change):
    expected, _ = effective_pair(tmp_path, mode)
    if change == "native-input": expected = native_effective(expected)
    observed = native_effective(expected, change)
    before = json_bytes(expected), json_bytes(observed)
    assert bridge.verify_effective(expected, observed, compose_version=NATIVE_VERSION) is None
    assert (json_bytes(expected), json_bytes(observed)) == before


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("side", ["expected", "observed"])
@pytest.mark.parametrize("path", ["", "services", "services.backend", "services.backend.volumes", "services.backend.volumes.0",
    "services.backend.volumes.2.bind", "services.backend.depends_on", "services.guard.ports", "services.guard.ports.0",
    "networks", "networks.shadow", "networks.shadow.ipam"])
@pytest.mark.parametrize("value", [None, False, 0, 0.0, [], "invalid"])
def test_hostile_effective_structures_raise_bundle_error(tmp_path, mode, side, path, value):
    expected, observed = effective_pair(tmp_path, mode)
    if side == "expected": expected = replace_path(expected, path, value)
    else: observed = replace_path(observed, path, value)
    rejected(expected, observed)


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("path,value", [
    ("services.web.read_only", 1), ("services.web.read_only", 1.0), ("services.comfy-proxy.pids_limit", 32.0),
    ("services.guard.command", []), ("services.web.entrypoint", []), ("services.backend.command", None),
    ("services.comfy-proxy.command", None), ("services.backend.network_mode", "host"), ("services.unexpected", {}),
    ("services.comfy-proxy.ports", ["18188:18188"]), ("services.web.image", "sha256:" + "f" * 64),
    ("services.backend.environment.COMFYUI_MOCK_FALLBACK", "true"), ("networks.shadow.driver", "host"),
    ("services.backend.volumes.2.bind", DELETE), ("services.backend.volumes.2.bind.propagation", "rshared"),
    *(("services.backend.volumes.2.bind.create_host_path", value) for value in [True, 0, 0.0, None]),
    *(("services.backend.volumes.2." + key, value) for key, value in [
        ("source", "/untrusted"), ("target", "/untrusted"), ("read_only", False), ("read_only", 1), ("read_only", 1.0), ("type", "volume")]),
    *(("services.backend.depends_on.guard." + key, value) for key in ["required", "restart"] for value in [False, 0, 1, 1.0]),
    ("services.backend.depends_on.guard.condition", "service_healthy"), ("services.backend.depends_on.guard.extra", True),
    ("services.backend.depends_on.guard", None), ("services.backend.depends_on.guard", []),
    ("services.backend.depends_on.comfy-proxy", DELETE), ("services.backend.depends_on.other", {}),
    ("services.comfy-proxy.depends_on.guard", DELETE), ("services.comfy-proxy.depends_on.guard.condition", "service_started"),
    ("services.guard.depends_on", {"guard": {"condition": "service_started", "required": True, "restart": True}}),
    ("services.guard.ports.0.mode", "host"), ("services.guard.ports.0.protocol", "udp"), ("services.guard.ports.0.target", 1),
    ("services.guard.ports.0.host_ip", "0.0.0.0"), ("services.guard.ports.0.extra", True),
    *(("services.guard.ports.0.published", value) for value in ["048614", "+48614", " 48614", "48614 ", "48614-48615", 48614.0, True, None]),
])
def test_effective_security_types_and_explicit_identity_remain_rejected(tmp_path, mode, path, value):
    expected, observed = effective_pair(tmp_path, mode)
    paths = [path]
    if path.startswith(("services.backend.depends_on.guard", "services.backend.depends_on.other")):
        paths += [path.replace("backend", role, 1) for role in ["web", "init-db"]]
    if path.startswith("services.guard.ports.0."): paths.append(path.replace(".0.", ".1.", 1))
    for target in paths: rejected(expected, replace_path(copy.deepcopy(observed), target, value))


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("role", ["backend", "web", "init-db"])
@pytest.mark.parametrize("change", ["expected-guard", "removed-guard", "network-mode", "protocol", "mode",
    "extra-port", "removed-port", "reverse-ports", "other-service", False, True, 0, -1, 65536, 0.0, 48614.0])
def test_conversions_require_exact_expected_dependency_and_port_context(tmp_path, mode, role, change):
    expected, observed = effective_pair(tmp_path, mode)
    wanted, actual = expected["services"][role], observed["services"][role]
    ports, actual_ports = expected["services"]["guard"]["ports"], observed["services"]["guard"]["ports"]
    if change in ["expected-guard", "removed-guard"]: wanted.setdefault("depends_on", {})["guard"] = {"condition": "service_healthy", "required": True, "restart": True}
    if change == "removed-guard": actual["depends_on"].pop("guard")
    if change == "network-mode": wanted["network_mode"] = actual["network_mode"] = "host"
    if change in ["protocol", "mode"]: ports[0][change] = "udp" if change == "protocol" else "host"
    if change == "extra-port": actual_ports.append(copy.deepcopy(actual_ports[0]))
    if change == "removed-port": actual_ports.pop()
    if change == "reverse-ports": actual_ports.reverse()
    if change == "other-service": wanted["ports"], actual["ports"] = copy.deepcopy(ports), copy.deepcopy(actual_ports)
    if type(change) is not str: ports[0]["published"], actual_ports[0]["published"] = change, str(change)
    rejected(expected, observed)


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("version", [None, False, 0, "", "2.40.3", "v" + NATIVE_VERSION, "2.40.4",
    NATIVE_VERSION + "\n", "2.40.3+ds1-0ubuntu2~24.04.1"])
def test_effective_comparator_requires_exact_supported_version(tmp_path, mode, version):
    expected, _ = effective_pair(tmp_path, mode)
    with pytest.raises(BundleError, match="BRIDGE_COMPOSE_VERSION_UNSUPPORTED"):
        bridge.verify_effective(expected, expected, compose_version=version)


@pytest.mark.parametrize("mode", MODES)
def test_cli_native_check_pins_raw_json_and_remains_readonly(tmp_path, capsys, mode):
    arguments = cli_arguments(fixture(tmp_path)); arguments[arguments.index("--mode") + 1] = mode
    assert bridge.main(arguments) == 0
    candidate = capsys.readouterr().out.encode(); effective = tmp_path / "native-effective.json"
    effective.write_bytes(json.dumps(native_effective(json.loads(candidate)), separators=(",", ":")).encode() + b"\n")
    checks = ["--compose-version", NATIVE_VERSION, "--check-compose", str(effective), "--check-sha256", file_hash(effective)[1]]
    before = {str(path): file_hash(path) for path in tmp_path.rglob("*") if path.is_file()}
    assert bridge.main(arguments + checks) == 0
    receipt = json.loads(capsys.readouterr().out)
    assert receipt["status"] == "BRIDGE_COMPOSE_VERIFIED" and receipt["mode"] == mode and receipt["production_authorized"] is False
    assert receipt["compose_sha256"] == hashlib.sha256(candidate).hexdigest()
    assert receipt["effective_compose_sha256"] == checks[-1] != receipt["compose_sha256"]
    assert receipt["compose_version"] == NATIVE_VERSION and receipt["comparison_profile"] == "compose-2.40.3-ubuntu24.04-json-v1"
    assert before == {str(path): file_hash(path) for path in tmp_path.rglob("*") if path.is_file()}
    effective.write_bytes(effective.read_bytes() + b"\n")
    assert bridge.main(arguments + checks) == 2
    assert json.loads(capsys.readouterr().out)["reason"] == "BRIDGE_FILE_PIN_MISMATCH"


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("extra,reason", [
    *(([flag, value], "BRIDGE_EFFECTIVE_CHECK_REQUIRED") for flag, value in [
        ("--compose-version", NATIVE_VERSION), ("--compose-version", ""), ("--check-sha256", ""), ("--check-sha256", "0" * 64)]),
    (["--check-compose", "unused.json", "--check-sha256", "0" * 64], "BRIDGE_COMPOSE_VERSION_REQUIRED"),
    *((["--check-compose", "unused.json", "--check-sha256", "0" * 64, "--compose-version", version], "BRIDGE_COMPOSE_VERSION_UNSUPPORTED")
        for version in ["", "2.40.3", "v" + NATIVE_VERSION, "2.40.4", NATIVE_VERSION + "\n", "2.40.3+ds1-0ubuntu2~24.04.1"]),
])
def test_cli_check_flags_require_exact_argument_context(tmp_path, capsys, mode, extra, reason):
    arguments = cli_arguments(fixture(tmp_path)); arguments[arguments.index("--mode") + 1] = mode
    assert bridge.main(arguments + extra) == 2
    assert json.loads(capsys.readouterr().out)["reason"] == reason
