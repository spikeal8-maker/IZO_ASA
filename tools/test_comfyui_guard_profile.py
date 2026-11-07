"""Canonical default-deny rendering and explicit Comfy UID policy checks."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("comfy_guard", ROOT / "ops/docker/dev/network_guard.py")
guard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(guard)
ENV = {"IZO_SHADOW_EGRESS_PROFILE": "comfyui-private-v1", "IZO_COMFY_UPSTREAM_IP": "192.168.1.112",
       "IZO_COMFY_UPSTREAM_PORT": "8188"}
DEFAULT = '''table inet izo_shadow {
    chain output {
        type filter hook output priority filter; policy drop;
        oifname "lo" accept
        ct state established,related accept
        counter drop
    }
}
'''


def test_default_rules_are_byte_identical_and_only_proxy_uid_gets_one_tuple(monkeypatch):
    assert guard.render_rules({}) == DEFAULT
    rendered = guard.render_rules(ENV)
    rule = "        meta skuid 10002 ip daddr 192.168.1.112 tcp dport 8188 accept\n"
    assert rendered == DEFAULT.replace("        counter drop\n", rule + "        counter drop\n")
    assert "skuid 10001" not in rendered and "skuid 101 " not in rendered
    for key, value in ENV.items():
        monkeypatch.setenv(key, value)
    guard.validate_policy(rendered)
    for changed in (DEFAULT, rendered.replace("10002", "10001"), rendered.replace("8188", "8189"),
                    rendered.replace("counter drop", "ip daddr 10.0.0.1 accept\n counter drop"),
                    rendered.replace("policy drop", "policy accept")):
        with pytest.raises(RuntimeError, match="SHADOW_KERNEL_POLICY_MISMATCH"):
            guard.validate_policy(changed)


@pytest.mark.parametrize("key,value", [("IZO_SHADOW_EGRESS_PROFILE", "unknown"), ("IZO_SHADOW_EGRESS_PROFILE", ""),
    ("IZO_COMFY_UPSTREAM_IP", "127.0.0.1"), ("IZO_COMFY_UPSTREAM_IP", "169.254.169.254"),
    ("IZO_COMFY_UPSTREAM_IP", "8.8.8.8"), ("IZO_COMFY_UPSTREAM_IP", "100.121.41.79"),
    ("IZO_COMFY_UPSTREAM_IP", "192.168.1.112/24"), ("IZO_COMFY_UPSTREAM_IP", "192.168.1.112;accept"),
    ("IZO_COMFY_UPSTREAM_PORT", "8188-8199"), ("IZO_COMFY_UPSTREAM_PORT", "65536"),
    ("IZO_COMFY_UPSTREAM_PORT", "0"), ("IZO_COMFY_UPSTREAM_PORT", "٨١٨٨")])
def test_unknown_profile_and_nonliteral_private_tuple_fail_before_kernel(key, value):
    with pytest.raises(RuntimeError):
        guard.render_rules({**ENV, key: value})


def test_guard_policy_readback_remains_exact_including_counter(monkeypatch):
    for key, value in ENV.items():
        monkeypatch.setenv(key, value)
    def nft(*args, **kwargs):
        return (guard.render_rules() if args[0] == "-s" else
                json.dumps({"nftables": [{"rule": {"expr": [{"counter": {"packets": 11}}]}}]}))
    monkeypatch.setattr(guard, "nft", nft)
    assert guard.policy_state() == {"policy": "VERIFIED", "blockedPackets": 11}
    monkeypatch.setattr(guard, "nft", lambda *args: DEFAULT)
    with pytest.raises(RuntimeError, match="SHADOW_KERNEL_POLICY_MISMATCH"):
        guard.policy_state()


def test_only_existing_guard_image_build_context_gains_proxy():
    dockerfile = (ROOT / "ops/docker/dev/Dockerfile.guard").read_text()
    ignored = (ROOT / "ops/docker/dev/Dockerfile.guard.dockerignore").read_text().splitlines()
    assert "COPY ops/docker/dev/comfyui_proxy.py /comfyui_proxy.py" in dockerfile
    assert "!ops/docker/dev/comfyui_proxy.py" in ignored
    assert dockerfile.count("FROM ") == 1 and "@sha256:" in dockerfile
    assert not any("backend" in item or "secret" in item for item in ignored)
