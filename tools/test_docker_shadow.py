from __future__ import annotations

import copy
import json
import sqlite3
from unittest.mock import Mock

import pytest

from tools.docker_shadow import OWNER, Shadow, ShadowError, child_environment
from tools import docker_shadow_smoke

SHA = "a" * 40
PROJECT = "izo-asa-shadow-unit"


def test_ambient_credentials_proxy_and_docker_routing_are_not_inherited(monkeypatch):
    for key in ("OPENROUTER_API_KEY", "TELEGRAM_BOT_TOKEN", "HTTP_PROXY", "DOCKER_HOST",
                "IZO_DOCKER_NETWORK_MODE", "COMPOSE_FILE", "IZO_DOCKER_COMFYUI_BASE_URL"):
        monkeypatch.setenv(key, "must-not-inherit")
    env = child_environment(PROJECT, SHA, 48125, 48126)
    assert all(value != "must-not-inherit" for value in env.values())
    assert env["IZO_SOURCE_SHA"] == SHA


@pytest.mark.parametrize("project,sha,web,api", [
    ("asa-lab-dev", SHA, 48125, 48126), ("izo-asa-shadow-X", SHA, 48125, 48126),
    (PROJECT, "main", 48125, 48126), (PROJECT, SHA, 8000, 48126),
    (PROJECT, SHA, 48125, 48125), (PROJECT, SHA, 48125, 65536),
])
def test_rejects_foreign_project_refs_and_production_or_invalid_ports(project, sha, web, api):
    with pytest.raises(ShadowError):
        child_environment(project, sha, web, api)


def test_dirty_or_wrong_source_fails_before_any_docker_call():
    for head, status in [("b" * 40, ""), (SHA, " M backend/main.py")]:
        shadow = Shadow(PROJECT, SHA)
        shadow.run = Mock(side_effect=["https://github.com/spikeal8-maker/IZO_ASA.git", head, status])
        shadow.docker = Mock()
        with pytest.raises(ShadowError, match="SHADOW_SOURCE_"):
            shadow.up()
        shadow.docker.assert_not_called()


def test_wrong_repository_fails_before_docker():
    shadow = Shadow(PROJECT, SHA)
    shadow.run = Mock(return_value="https://github.com/other/IZO_ASA.git")
    shadow.docker = Mock()
    with pytest.raises(ShadowError, match="SHADOW_REPOSITORY_MISMATCH"):
        shadow.up()
    shadow.docker.assert_not_called()


def test_failed_image_build_does_not_start_or_replace_containers():
    shadow = Shadow(PROJECT, SHA)
    shadow.source_guard = Mock()
    shadow.config = Mock()
    shadow.ownership_guard = Mock()
    shadow.compose = Mock(side_effect=ShadowError("SHADOW_COMMAND_FAILED"))
    with pytest.raises(ShadowError, match="SHADOW_COMMAND_FAILED"):
        shadow.up()
    assert not any(call.args[0] == "up" for call in shadow.compose.call_args_list)


def config():
    service = {"network_mode": "service:guard", "labels": {"io.izo.owner": OWNER},
               "user": "10001:10001", "cap_drop": ["ALL"], "security_opt": ["no-new-privileges:true"],
               "depends_on": {"guard": {"condition": "service_healthy"}},
               "volumes": [{"type": "volume"}]}
    guard = {"networks": {"shadow": {}}, "labels": {"io.izo.owner": OWNER},
             "cap_drop": ["ALL"], "security_opt": ["no-new-privileges:true"],
             "healthcheck": {"test": ["CMD", "python", "/network_guard.py", "--check"]},
             "dns": ["127.0.0.1"],
             "ports": [{"host_ip": "127.0.0.1"}]}
    return {"services": {"backend": copy.deepcopy(service), "web": copy.deepcopy(service), "guard": guard},
            "networks": {"shadow": {}}}


@pytest.mark.parametrize("change", ["extra-network", "host-network", "public-port", "bind-mount", "foreign-owner", "early-app", "host-dns"])
def test_unsafe_effective_compose_is_rejected(change):
    value = config()
    backend = value["services"]["backend"]
    if change == "extra-network":
        value["networks"]["public"] = {}
    elif change == "host-network":
        backend["network_mode"] = "host"
    elif change == "public-port":
        value["services"]["guard"]["ports"][0]["host_ip"] = "0.0.0.0"
    elif change == "bind-mount":
        backend["volumes"][0]["type"] = "bind"
    elif change == "foreign-owner":
        backend["labels"]["io.izo.owner"] = "other"
    elif change == "early-app":
        backend["depends_on"]["guard"]["condition"] = "service_started"
    else:
        value["services"]["guard"].pop("dns")
    shadow = Shadow(PROJECT, SHA)
    shadow.compose = Mock(return_value=json.dumps(value))
    with pytest.raises(ShadowError, match="SHADOW_CONFIG_"):
        shadow.config()


def test_foreign_container_owner_is_not_stopped():
    shadow = Shadow(PROJECT, SHA)
    shadow.containers = Mock(return_value=[{"Config": {"Labels": {
        "io.izo.owner": "other", "com.docker.compose.service": "backend"}}}])
    shadow.docker = Mock()
    with pytest.raises(ShadowError, match="SHADOW_FOREIGN_CONTAINER"):
        shadow.ownership_guard()
    shadow.docker.assert_not_called()


def test_unlabeled_volume_name_collision_is_not_adopted():
    shadow = Shadow(PROJECT, SHA)
    shadow.containers = Mock(return_value=[])
    def docker(*args, **kwargs):
        if args[:2] == ("volume", "ls") and "--format" in args:
            return f"{PROJECT}_sqlite-data"
        if args[:2] == ("volume", "inspect"):
            return '[{"Labels":{}}]'
        return ""
    shadow.docker = Mock(side_effect=docker)
    with pytest.raises(ShadowError, match="SHADOW_RESOURCE_NAME_COLLISION"):
        shadow.ownership_guard()
    assert not any(call.args[1:2] in [("rm",), ("prune",)] for call in shadow.docker.call_args_list)


def test_compose_ignores_ambient_dotenv_and_only_addresses_named_project():
    shadow = Shadow(PROJECT, SHA)
    shadow.docker = Mock(return_value="")
    shadow.compose("down")
    args = shadow.docker.call_args.args
    assert args[0:2] == ("compose", "--env-file")
    assert args[args.index("--project-name") + 1] == PROJECT
    assert args[-1] == "down"
    assert "--volumes" not in args and "--remove-orphans" not in args


def test_storage_probe_executes_sql_and_preserves_application_rows(tmp_path, monkeypatch, capsys):
    data, media = tmp_path / "data", tmp_path / "media"
    data.mkdir()
    media.mkdir()
    with sqlite3.connect(data / "app.sqlite3") as app:
        for table in ("users", "jobs", "images"):
            app.execute(f"CREATE TABLE {table} (id INTEGER)")
            app.execute(f"INSERT INTO {table} VALUES (1)")
    def execute_fixture(shadow, container, script):
        script = script.replace("/home/izo/data", data.as_posix())
        script = script.replace("/home/izo/media", media.as_posix())
        exec(script, {})
        return json.loads(capsys.readouterr().out)
    monkeypatch.setattr(docker_shadow_smoke, "exec_json", execute_fixture)
    before = docker_shadow_smoke.fixture(None, "test", "safe-fixture", create=True)
    after = docker_shadow_smoke.fixture(None, "test", "safe-fixture", create=False)
    assert before == after
    assert after["applicationCounts"] == {"users": 1, "jobs": 1, "images": 1}


def guard_module():
    import importlib.util
    from pathlib import Path
    path = Path(__file__).resolve().parents[1] / "ops/docker/dev/network_guard.py"
    spec = importlib.util.spec_from_file_location("shadow_guard_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_stateful_policy_allows_only_loopback_and_established_replies():
    guard = guard_module()
    guard.validate_policy(guard.RULES)
    assert 'policy drop;' in guard.RULES
    assert 'oifname "lo" accept' in guard.RULES
    assert 'ct state established,related accept' in guard.RULES


@pytest.mark.parametrize("change", ["missing", "accept-default", "extra-accept", "no-counter", "wrong-hook"])
def test_missing_or_damaged_policy_fails_closed(change):
    guard = guard_module()
    text = {'missing': '', 'accept-default': guard.RULES.replace('policy drop', 'policy accept'),
            'extra-accept': guard.RULES.replace('counter drop', 'accept\n counter drop'),
            'no-counter': guard.RULES.replace('counter drop', 'drop'),
            'wrong-hook': guard.RULES.replace('hook output', 'hook input')}[change]
    with pytest.raises(RuntimeError, match='SHADOW_KERNEL_POLICY_MISMATCH'):
        guard.validate_policy(text)


def test_failed_policy_install_never_marks_ready_or_drops_into_service_loop(tmp_path, monkeypatch):
    guard = guard_module()
    monkeypatch.setattr(guard, 'READY', tmp_path / 'ready')
    monkeypatch.setattr(guard, 'nft', Mock(side_effect=RuntimeError('INSTALL_FAILED')))
    drop = Mock()
    monkeypatch.setattr(guard.os, 'setgroups', drop, raising=False)
    with pytest.raises(RuntimeError, match='INSTALL_FAILED'):
        guard.main()
    assert not guard.READY.exists()
    drop.assert_not_called()


@pytest.mark.parametrize("change", ['no-policy-check', 'root-app', 'net-admin', 'no-cap-drop', 'new-privileges'])
def test_policy_readiness_and_app_privileges_are_mandatory(change):
    value = config()
    if change == 'no-policy-check':
        value['services']['guard']['healthcheck']['test'] = ['CMD', 'true']
    elif change == 'root-app':
        value['services']['backend']['user'] = '0:0'
    elif change == 'net-admin':
        value['services']['backend']['cap_add'] = ['NET_ADMIN']
    elif change == 'no-cap-drop':
        value['services']['web']['cap_drop'] = []
    else:
        value['services']['web']['security_opt'] = []
    shadow = Shadow(PROJECT, SHA)
    shadow.compose = Mock(return_value=json.dumps(value))
    with pytest.raises(ShadowError, match='SHADOW_CONFIG_'):
        shadow.config()


def test_production_comparison_does_not_accept_missing_or_changed_baseline():
    from tools.docker_shadow_evidence import compare
    with pytest.raises(RuntimeError, match='INCOMPLETE'):
        compare({}, {})
    before = {'status': 'CAPTURED', 'versions': {'release': 'old'}, 'windows': {}, 'foreignDocker': {}}
    assert compare(before, copy.deepcopy(before))['status'] == 'PROVEN'
    after = copy.deepcopy(before)
    after['versions']['release'] = 'changed'
    assert compare(before, after)['status'] == 'FAIL'


def test_controlled_listener_really_accepts_a_local_fixture_connection():
    import socket
    import subprocess
    import sys
    process = subprocess.Popen([sys.executable, '-B', '-u', '-c',
                                docker_shadow_smoke.LISTENER_SCRIPT, '0', '127.0.0.1'],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        port = int(process.stdout.readline().strip())
        with socket.create_connection(('127.0.0.1', port), timeout=2) as client:
            assert client.recv(64) == b'shadow-fixture'
    finally:
        process.terminate()
        process.communicate(timeout=5)
