"""Opt-in egress grants one extra UID only; accepted Comfy/default remain exact."""
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("openrouter_guard_test", ROOT / "ops/docker/dev/network_guard.py")
guard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(guard)
COMFY = {"IZO_SHADOW_EGRESS_PROFILE": "comfyui-private-v1",
         "IZO_COMFY_UPSTREAM_IP": "192.168.1.112", "IZO_COMFY_UPSTREAM_PORT": "8188"}
OPENROUTER = COMFY | {"IZO_SHADOW_EGRESS_PROFILE": "comfyui-openrouter-v1",
                     "IZO_OPENROUTER_IPV4S": "8.8.8.8,104.18.2.47"}


def test_default_and_private_comfy_policy_are_byte_identical():
    assert guard.render_rules({}) == guard.RULES
    old = guard.RULES.replace("        counter drop\n",
        "        meta skuid 10002 ip daddr 192.168.1.112 tcp dport 8188 accept\n        counter drop\n")
    assert guard.render_rules(COMFY) == old


def test_combined_policy_has_only_reviewed_uid_destination_tuples():
    rules = guard.render_rules(OPENROUTER)
    grant = [line.strip() for line in rules.splitlines() if "meta skuid" in line]
    assert grant == ["meta skuid 10002 ip daddr 192.168.1.112 tcp dport 8188 accept",
                     "meta skuid 10003 ip daddr 8.8.8.8 tcp dport 443 accept",
                     "meta skuid 10003 ip daddr 104.18.2.47 tcp dport 443 accept"]
    assert "policy drop;" in rules and "ct state established,related accept" in rules
    assert rules.count("counter drop") == 1 and "udp" not in rules and "ip6" not in rules
    assert "skuid 10001" not in rules and "skuid 101 " not in rules


@pytest.mark.parametrize("value", ["", "8.8.8.8,8.8.8.8", "104.18.2.47,8.8.8.8", " 8.8.8.8",
    "127.0.0.1", "192.168.1.112", "169.254.169.254", "100.64.0.1", "192.0.0.9",
    "224.0.0.1", "240.1.2.3", "0.0.0.0", "203.0.113.1", "::1", "openrouter.ai",
    "8.8.8.8 tcp dport 80 accept", "1.1.1.1,2.2.2.2,3.3.3.3,4.4.4.4,5.5.5.5,6.6.6.6,7.7.7.7,8.8.8.8,9.9.9.9"])
def test_invalid_or_unbounded_target_sets_fail_before_kernel_mutation(value):
    with pytest.raises(RuntimeError, match="SHADOW_OPENROUTER_TARGET_INVALID"):
        guard.render_rules(OPENROUTER | {"IZO_OPENROUTER_IPV4S": value})


@pytest.mark.parametrize("env", [
    {"IZO_OPENROUTER_IPV4S": "8.8.8.8"}, COMFY | {"IZO_OPENROUTER_IPV4S": "8.8.8.8"},
    OPENROUTER | {"IZO_SHADOW_EGRESS_PROFILE": "openrouter"},
    OPENROUTER | {"IZO_COMFY_UPSTREAM_IP": "8.8.8.8"},
])
def test_no_implicit_profile_or_comfy_target_expansion(env):
    with pytest.raises(RuntimeError):
        guard.render_rules(env)


def test_live_policy_readback_rejects_an_extra_accept(monkeypatch):
    for name, value in OPENROUTER.items():
        monkeypatch.setenv(name, value)
    expected = guard.render_rules()
    guard.validate_policy(expected)
    with pytest.raises(RuntimeError, match="SHADOW_KERNEL_POLICY_MISMATCH"):
        guard.validate_policy(expected.replace("counter drop", "meta skuid 10001 accept\n        counter drop"))
