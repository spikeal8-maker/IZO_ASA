"""Exact offline profile delta retains the actual historical/Comfy admission gates."""
import copy
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pytest

from tools import docker_openrouter_profile as profile
from tools import prepare_openrouter_egress as preparation
from tools.docker_test_bundle_format import BundleError, file_hash, json_bytes, verify
from tools.test_docker_comfy_bridge_profile import native_effective
from tools.test_docker_history_beta_profile import arguments as history_arguments, fixture as history_fixture, render as render_history
from tools.test_docker_synthetic_runtime import repin

ROOT = Path(__file__).resolve().parents[1]


def fixture(tmp_path):
    values = list(history_fixture(tmp_path))
    bundle, _, manifest = values[:3]
    for module in (profile, preparation, profile.history):
        shutil.copyfile(module.__file__, bundle / Path(module.__file__).name)
    shutil.copyfile(ROOT / "ops/docker/dev/compose.openrouter-shadow.yml", bundle / "profiles/compose.openrouter-shadow.yml")
    values[1] = repin(bundle, manifest)
    now = datetime.now(timezone.utc)
    receipt = preparation.prepare(manifest, manifest_sha256=values[1], helper_sha256=file_hash(Path(preparation.__file__))[1],
        resolver=lambda: ["8.8.8.8", "104.18.2.47"], clock=lambda: now,
        tls_verifier=lambda address: {"ipv4": address, "tls_version": "TLSv1.3", "certificate_verified": True})
    receipt_file = tmp_path / "prepared.json"
    receipt_file.write_bytes(json_bytes(receipt))
    args = history_arguments(values) + ["--openrouter-helper-sha256", file_hash(Path(profile.__file__))[1],
        "--prepare-helper-sha256", file_hash(Path(preparation.__file__))[1],
        "--preparation", str(receipt_file), "--preparation-sha256", file_hash(receipt_file)[1],
        "--accept-openrouter-egress"]
    return values, receipt, now, args


def apply(base, receipt, now, **changes):
    return profile.apply_to_history(base, receipt, **({"source_sha": receipt["source_sha"],
        "expected_prepare_helper_sha256": receipt["prepare_helper_sha256"], "now_utc": now,
        "template": json.loads((ROOT / "ops/docker/dev/compose.openrouter-shadow.yml").read_text())} | changes))


@pytest.mark.parametrize("canonical_secret_dir", [False, True])
def test_strict_delta_preserves_history_comfy_web_mounts_and_existing_security(tmp_path, canonical_secret_dir):
    values, receipt, now, _ = fixture(tmp_path)
    base = render_history(values)
    if canonical_secret_dir:
        base["services"]["backend"]["environment"]["IZO_SECRET_DIR"] = profile.SECRET_PATH
    before = copy.deepcopy((base, receipt))
    result = apply(base, receipt, now)
    assert (base, receipt) == before and verify(values[0], values[1]) == values[2]
    assert set(result["services"]) == {"backend", "web", "guard", "comfy-proxy", "openrouter-proxy"}
    assert result["services"]["comfy-proxy"] == base["services"]["comfy-proxy"]
    assert result["services"]["web"] == base["services"]["web"] and result["networks"] == base["networks"]
    assert result["volumes"] == base["volumes"] | {"secrets-data": {"external": True, "name": profile.SECRET_VOLUME}}
    backend = result["services"]["backend"]
    assert backend["environment"] == base["services"]["backend"]["environment"] | profile.BACKEND_ENV
    assert backend["volumes"] == base["services"]["backend"]["volumes"] + [profile.SECRET_MOUNT]
    assert {s["image"] for s in result["services"].values()} == set(values[2]["images"].values())
    proxy = result["services"]["openrouter-proxy"]
    assert proxy["user"] == "10003:10003" and proxy["network_mode"] == "service:guard" and proxy["read_only"]
    assert not any(k in proxy for k in ("volumes", "ports", "networks", "dns", "cap_add"))
    assert result["services"]["guard"]["environment"] == base["services"]["guard"]["environment"] | {
        "IZO_SHADOW_EGRESS_PROFILE": "comfyui-openrouter-v1", "IZO_OPENROUTER_IPV4S": "8.8.8.8,104.18.2.47"}


@pytest.mark.parametrize("name,value", [
    ("IZO_SECRET_DIR", None), ("IZO_SECRET_DIR", ""), ("IZO_SECRET_DIR", profile.SECRET_PATH + "/"),
    ("IZO_OPENROUTER_TRANSPORT", None), ("IZO_OPENROUTER_TRANSPORT", ""),
    ("IZO_OPENROUTER_TRANSPORT", profile.TRANSPORT),
])
def test_invalid_prior_secret_configuration_is_rejected(tmp_path, name, value):
    values, receipt, now, _ = fixture(tmp_path)
    base = render_history(values)
    base["services"]["backend"]["environment"]["IZO_SECRET_DIR"] = profile.SECRET_PATH
    base["services"]["backend"]["environment"][name] = value
    before = copy.deepcopy(base)
    with pytest.raises(BundleError, match="OPENROUTER_HISTORY_BACKEND_INVALID"):
        apply(base, receipt, now)
    assert base == before


@pytest.mark.parametrize("source,target", [("media-data", profile.SECRET_PATH), ("secrets-data", "/tmp/prior-secret")])
def test_canonical_secret_directory_does_not_accept_existing_secret_mount(tmp_path, source, target):
    values, receipt, now, _ = fixture(tmp_path)
    base = render_history(values)
    backend = base["services"]["backend"]
    backend["environment"]["IZO_SECRET_DIR"] = profile.SECRET_PATH
    backend["volumes"].append({"type": "volume", "source": source, "target": target})
    before = copy.deepcopy(base)
    with pytest.raises(BundleError, match="OPENROUTER_EXISTING_SECRET_MOUNT_INVALID"):
        apply(base, receipt, now)
    assert base == before


@pytest.mark.parametrize("target", [profile.SECRET_PATH, profile.SECRET_PATH + ":rw,noexec"])
def test_existing_secret_tmpfs_is_rejected_before_adding_persistent_volume(tmp_path, target):
    values, receipt, now, _ = fixture(tmp_path)
    base = render_history(values)
    base["services"]["backend"]["tmpfs"] = [target]
    before = copy.deepcopy(base)
    with pytest.raises(BundleError, match="OPENROUTER_EXISTING_SECRET_MOUNT_INVALID"):
        apply(base, receipt, now)
    assert base == before


def test_unrelated_tmpfs_is_retained(tmp_path):
    values, receipt, now, _ = fixture(tmp_path)
    base = render_history(values)
    base["services"]["backend"]["environment"]["IZO_SECRET_DIR"] = profile.SECRET_PATH
    base["services"]["backend"]["tmpfs"] = ["/tmp"]
    before = copy.deepcopy(base)
    result = apply(base, receipt, now)
    assert base == before and result["services"]["backend"]["tmpfs"] == ["/tmp"]
    assert result["services"]["backend"]["volumes"] == base["services"]["backend"]["volumes"] + [profile.SECRET_MOUNT]


def test_cli_render_and_native_normalization_are_offline_and_readonly(tmp_path, capsys):
    values, receipt, now, args = fixture(tmp_path)
    before = {str(p): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    assert profile.main(args) == 0
    result = json.loads(capsys.readouterr().out)
    assert result == apply(render_history(values), receipt, now)
    assert {str(p): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()} == before
    actual = tmp_path / "effective.json"
    actual.write_bytes(json_bytes(native_effective(result)))
    assert profile.main(args + ["--check-compose", str(actual), "--check-sha256", file_hash(actual)[1],
        "--compose-version", profile.bridge.COMPOSE_VERSION]) == 0
    proof = json.loads(capsys.readouterr().out)
    assert proof["status"] == "OPENROUTER_BETA_COMPOSE_VERIFIED" and proof["runtime_verified"] is False
    assert proof["secret_volume_initialization_required"] is True


@pytest.mark.parametrize("flag", ["--accept-openrouter-egress", "--accept-history-bind", "--accept-private-http"])
def test_all_three_explicit_boundaries_remain_required(tmp_path, capsys, flag):
    _, _, _, args = fixture(tmp_path)
    args.remove(flag)
    assert profile.main(args) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "BLOCKED"


@pytest.mark.parametrize("flag", ["--openrouter-helper-sha256", "--prepare-helper-sha256", "--preparation-sha256",
    "--helper-sha256", "--base-sha256", "--manifest-sha256", "--expect-source"])
def test_source_helper_history_and_preparation_pins_cannot_be_substituted(tmp_path, capsys, flag):
    _, _, _, args = fixture(tmp_path)
    args[args.index(flag) + 1] = "0" * (40 if flag == "--expect-source" else 64)
    assert profile.main(args) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "BLOCKED"


@pytest.mark.parametrize("change", ["volume", "history-flag", "comfy-target", "source", "privileged", "direct-network",
    "secret-env", "service", "template-mount", "template-port", "template-uid", "template-ip"])
def test_unsafe_history_input_or_overlay_mutation_is_rejected(tmp_path, change):
    values, receipt, now, _ = fixture(tmp_path)
    base = render_history(values)
    template = json.loads((ROOT / "ops/docker/dev/compose.openrouter-shadow.yml").read_text())
    backend = base["services"]["backend"]
    if change == "volume": base["volumes"]["sqlite-data"]["name"] = "foreign"
    elif change == "history-flag": backend["environment"]["IZO_PREPROD_PRESERVE_HISTORY"] = "0"
    elif change == "comfy-target": base["services"]["guard"]["environment"]["IZO_COMFY_UPSTREAM_IP"] = "192.168.1.113"
    elif change == "source": backend["labels"]["org.opencontainers.image.revision"] = "d" * 40
    elif change == "privileged": backend["privileged"] = True
    elif change == "direct-network": backend["network_mode"] = "host"
    elif change == "secret-env": backend["environment"]["IZO_SECRET_DIR"] = "/tmp"
    elif change == "service": base["services"]["worker"] = copy.deepcopy(backend)
    elif change == "template-mount": template["services"]["openrouter-proxy"]["volumes"] = [profile.SECRET_MOUNT]
    elif change == "template-port": template["services"]["openrouter-proxy"]["ports"] = ["18189:18189"]
    elif change == "template-uid": template["services"]["openrouter-proxy"]["user"] = "0:0"
    else: template["services"]["guard"]["environment"]["IZO_OPENROUTER_IPV4S"] = "8.8.4.4"
    before = copy.deepcopy(base)
    with pytest.raises(BundleError): apply(base, receipt, now, template=template)
    assert base == before


@pytest.mark.parametrize("change", ["uid", "network", "ip", "guard", "history", "secret-volume", "mount", "service"])
def test_effective_five_service_compose_comparison_has_no_broad_exemptions(tmp_path, change):
    values, receipt, now, _ = fixture(tmp_path)
    expected = apply(render_history(values), receipt, now)
    observed = native_effective(expected)
    new = observed["services"]["openrouter-proxy"]
    if change == "uid": new["user"] = "0:0"
    elif change == "network": new["network_mode"] = "host"
    elif change == "ip": new["environment"]["IZO_OPENROUTER_IPV4S"] = "8.8.4.4"
    elif change == "guard": observed["services"]["guard"]["environment"]["IZO_COMFY_UPSTREAM_PORT"] = "9999"
    elif change == "history": observed["services"]["backend"]["environment"]["IZO_PREPROD_PRESERVE_HISTORY"] = "0"
    elif change == "secret-volume": observed["volumes"]["secrets-data"]["external"] = False
    elif change == "mount": observed["services"]["web"].setdefault("volumes", []).append(profile.SECRET_MOUNT)
    else: del observed["services"]["comfy-proxy"]
    with pytest.raises(BundleError):
        profile.verify_effective(expected, observed, compose_version=profile.bridge.COMPOSE_VERSION)
