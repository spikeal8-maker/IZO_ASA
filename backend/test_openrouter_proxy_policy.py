"""Static and pure-function safety tests for candidate-only OpenRouter networking."""
from __future__ import annotations

import ast
import importlib.util
import ipaddress
from pathlib import Path
import pytest

ROOT=Path(__file__).resolve().parents[1]
PROXY=ROOT/"ops/docker/dev/openrouter_https_proxy.py"
GUARD=ROOT/"ops/docker/dev/openrouter_network_guard.py"
COMPOSE=ROOT/"ops/docker/dev/compose.openrouter-shadow.yml"


def _const(path, name):
    tree=ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id==name for t in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError("constant not found: "+name)


def test_guard_only_allows_tunnel_to_single_proxy_address():
    rules=_const(GUARD,"RULES")
    assert "policy drop" in rules
    assert rules.count("ip daddr 10.249.211.3 tcp dport 3128 accept")==1
    assert "counter drop" in rules
    assert "ip6 daddr" not in rules
    assert "0.0.0.0/0" not in rules
    assert "ct state established,related accept" in rules


def test_proxy_does_not_support_wildcard_or_insecure_target():
    code=PROXY.read_text(encoding="utf-8")
    assert 'UPSTREAM = "openrouter.ai"' in code
    assert 'UPSTREAM_PORT = 443' in code
    assert 'CONNECT openrouter.ai:443 HTTP/1.1' in code
    assert "403 Forbidden" in code
    assert "is_global" in code
    assert "CONNECT " in code and "127.0.0.1" not in code


def test_candidate_compose_keeps_web_and_backend_behind_guard():
    c=COMPOSE.read_text(encoding="utf-8")
    assert "10.249.211.0/24" in c
    assert "10.249.211.2" in c
    assert "10.249.211.3" in c
    assert "https://openrouter.ai/api/v1" in c
    assert "http://10.249.211.3:3128" in c
    assert "network_mode: host" not in c
    assert "privileged: true" not in c
    assert "OPENROUTER_API_KEY:" not in c


def test_proxy_rejects_non_openrouter_hostname(monkeypatch):
    namespace={}
    exec(compile(PROXY.read_text(encoding="utf-8"),str(PROXY),"exec"),namespace)
    for bad in ("localhost","127.0.0.1","openrouter.ai.evil.tld","openrouter.ai:8080","https://openrouter.ai"):
        with pytest.raises(ValueError):
            namespace["allowed_resolved_addresses"](bad)
