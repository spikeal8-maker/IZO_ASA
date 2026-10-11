from __future__ import annotations

import copy
import json
from unittest.mock import Mock

import pytest

from tools.docker_shadow import OWNER, Shadow, ShadowError, child_environment

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


def config():
    service = {"networks": {"shadow": {}}, "labels": {"io.izo.owner": OWNER},
               "ports": [{"host_ip": "127.0.0.1"}], "volumes": [{"type": "volume"}]}
    return {"services": {"backend": copy.deepcopy(service), "web": copy.deepcopy(service)},
            "networks": {"shadow": {"internal": True}}}


@pytest.mark.parametrize("change", ["external-network", "host-network", "public-port", "bind-mount", "foreign-owner"])
def test_unsafe_effective_compose_is_rejected(change):
    value = config()
    backend = value["services"]["backend"]
    if change == "external-network":
        value["networks"]["shadow"]["internal"] = False
    elif change == "host-network":
        backend["network_mode"] = "host"
    elif change == "public-port":
        backend["ports"][0]["host_ip"] = "0.0.0.0"
    elif change == "bind-mount":
        backend["volumes"][0]["type"] = "bind"
    else:
        backend["labels"]["io.izo.owner"] = "other"
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
