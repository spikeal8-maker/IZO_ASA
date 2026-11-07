"""Read-only Docker preflight tests with synthetic, non-mutating command results."""
from __future__ import annotations

import subprocess

import pytest

from tools.docker_delivery_probe import (
    DockerReader, ProbeError, clean_child_environment, probe_target,
)


class FakeDocker:
    def __init__(self, *, foreign: bool = False, unavailable: bool = False, owned: bool = False):
        self.commands: list[tuple[str, ...]] = []
        self.envs: list[dict[str, str]] = []
        self.foreign = foreign
        self.unavailable = unavailable
        self.owned = owned
        self.containers = ["a" * 64 + "|isoas-backend-1"] if foreign else []
        self.volumes: list[str] = []
        self.networks: list[str] = []
        self.server_type = "linux"
        self.large = False

    def __call__(self, command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        self.commands.append(tuple(command))
        self.envs.append(kwargs["env"])
        assert command[:3] == ["docker", "--context", "desktop-linux"]
        assert kwargs["capture_output"] is True and kwargs["check"] is False
        assert kwargs["timeout"] == 12
        parts = tuple(command[3:])
        if self.unavailable:
            return subprocess.CompletedProcess(command, 1, "", "private secret omitted")
        result = ""
        if parts == ("info", "--format", "{{.ID}}|{{.OSType}}|{{.ServerVersion}}"):
            result = "engine-synthetic|"+self.server_type+"|29.8.2"
        elif parts == ("compose", "version", "--short"):
            result = "v5.6.0"
        elif parts[:2] == ("ps", "-a"):
            # Docker performs label filtering; unrelated CI resources are omitted.
            result = "\n".join(self.containers if "--filter" not in parts or self.owned else [])
        elif parts[:2] == ("volume", "ls"):
            result = "\n".join(self.volumes if "--filter" not in parts or self.owned else [])
        elif parts[:2] == ("network", "ls"):
            result = "\n".join(self.networks if "--filter" not in parts or self.owned else [])
        elif parts[:3] == ("inspect", "--format", "{{json .Config.Labels}}"):
            result = ('{"com.docker.compose.project":"isoas","io.isoas.project":"ISOAS"}'
                      if self.owned else '{"com.docker.compose.project":"other","io.isoas.project":"OTHER"}'
                      if self.foreign else '{}')
        elif len(parts) == 5 and parts[:3] in {
            ("volume", "inspect", "--format"), ("network", "inspect", "--format")
        }:
            result = ('{"com.docker.compose.project":"isoas","io.isoas.project":"ISOAS"}'
                      if self.owned else '{"com.docker.compose.project":"other","io.isoas.project":"OTHER"}'
                      if self.foreign else '{}')
        else:
            raise AssertionError(f"unexpected reader command shape: {parts!r}")
        if self.large and parts[:2] == ("volume", "ls"):
            result = "z" * 270000
        return subprocess.CompletedProcess(command, 0, result, "")


def test_empty_windows_linux_target_with_explicit_context() -> None:
    runner = FakeDocker()
    result = probe_target("desktop-linux", "isoas", runner=runner)
    assert result.has_installation is False
    assert result.server_version == "29.8.2"
    assert result.compose_version == "5.6.0"
    assert len(result.engine_fingerprint) == 64
    assert result.owned_containers == result.owned_volumes == result.owned_networks == 0
    assert all(command[0] == "docker" for command in runner.commands)


def test_process_environment_discards_host_override_proxy_and_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COMPOSE_PROJECT_NAME", "malicious")
    monkeypatch.setenv("DOCKER_HOST", "tcp://foreign")
    monkeypatch.setenv("DOCKER_CONTEXT", "foreign")
    monkeypatch.setenv("HTTP_PROXY", "http://private-token")
    monkeypatch.setenv("OPENROUTER_API_KEY", "do-not-print")
    runner = FakeDocker()
    probe_target("desktop-linux", "isoas", runner=runner)
    for env in runner.envs:
        assert "DOCKER_HOST" not in env
        assert "DOCKER_CONTEXT" not in env
        assert "COMPOSE_PROJECT_NAME" not in env
        assert "HTTP_PROXY" not in env
        assert "OPENROUTER_API_KEY" not in env
    assert clean_child_environment({"PATH": "ok", "COMPOSE_FILE": "private"}) == {"PATH": "ok"}


@pytest.mark.parametrize("context,project", [
    ("../host", "isoas"), ("desktop-linux;docker rm all", "isoas"),
    ("desktop-linux", "asa-lab-dev"), ("desktop-linux", "isoas;rm"),
    ("desktop-linux", "ISOAS"), ("desktop-linux", "isoas привет"),
    ("desktop-linux", "isoas\na"), ("", "isoas"),
])
def test_invalid_identity_fails_before_subprocess(context: str, project: str) -> None:
    runner = FakeDocker()
    with pytest.raises(ProbeError, match="INVALID_"):
        probe_target(context, project, runner=runner)
    assert runner.commands == []


@pytest.mark.parametrize("command", [
    ("run", "--rm", "python:latest"),
    ("compose", "up", "-d"),
    ("volume", "rm", "isoas_sqlite-data"),
    ("system", "prune", "-f"),
    ("exec", "-it", "isoas-backend-1", "sh"),
    ("network", "connect", "bridge", "isoas-backend-1"),
    ("ps", "-a", "--filter", "label=com.docker.compose.project=foo;rm", "--format", "{{.ID}}|{{.Names}}"),
])
def test_reader_has_explicit_read_only_command_allowlist(command: tuple[str, ...]) -> None:
    runner = FakeDocker()
    reader = DockerReader("desktop-linux", runner=runner)
    with pytest.raises(ProbeError, match="FORBIDDEN_DOCKER_COMMAND"):
        reader.read(*command)
    assert not runner.commands


def test_foreign_container_with_reserved_namespace_refuses_ownership() -> None:
    runner = FakeDocker(foreign=True)
    with pytest.raises(ProbeError, match="OWNERSHIP_CONFLICT"):
        probe_target("desktop-linux", "isoas", runner=runner)


def test_foreign_volume_with_reserved_namespace_refuses_ownership() -> None:
    runner = FakeDocker(foreign=True)
    runner.containers = []
    runner.volumes = ["isoas_sqlite-data"]
    with pytest.raises(ProbeError, match="OWNERSHIP_CONFLICT"):
        probe_target("desktop-linux", "isoas", runner=runner)


def test_foreign_network_with_reserved_namespace_refuses_ownership() -> None:
    runner = FakeDocker(foreign=True)
    runner.containers = []
    runner.networks = ["isoas_default"]
    with pytest.raises(ProbeError, match="OWNERSHIP_CONFLICT"):
        probe_target("desktop-linux", "isoas", runner=runner)


def test_ci_namespace_does_not_collide_with_canonical_isoas() -> None:
    runner = FakeDocker()
    runner.containers = ["a" * 64 + "|isoas-ci-123-1-backend"]
    runner.volumes = ["isoas-ci-123-1_sqlite-data"]
    runner.networks = ["isoas-ci-123-1_default"]
    result = probe_target("desktop-linux", "isoas", runner=runner)
    assert result.has_installation is False


def test_engine_unavailable_is_fail_closed_without_private_stderr() -> None:
    runner = FakeDocker(unavailable=True)
    with pytest.raises(ProbeError) as raised:
        probe_target("desktop-linux", "isoas", runner=runner)
    assert str(raised.value) == "TARGET_UNAVAILABLE"
    assert "private" not in str(raised.value)


def test_wrong_engine_os_is_rejected() -> None:
    runner = FakeDocker()
    runner.server_type = "windows"
    with pytest.raises(ProbeError, match="TARGET_OSTYPE_UNSUPPORTED"):
        probe_target("desktop-linux", "isoas", runner=runner)


def test_oversized_engine_output_refused_without_echo() -> None:
    runner = FakeDocker()
    runner.large = True
    with pytest.raises(ProbeError, match="TARGET_RESPONSE_TOO_LARGE"):
        probe_target("desktop-linux", "isoas", runner=runner)


def test_existing_owned_stack_recognized_without_mutations() -> None:
    runner = FakeDocker(owned=True)
    runner.containers = ["a" * 64 + "|isoas-backend-1"]
    runner.volumes = ["isoas_sqlite-data", "isoas_media-data"]
    runner.networks = ["isoas_private"]
    result = probe_target("desktop-linux", "isoas", runner=runner)
    assert result.has_installation
    assert (result.owned_containers, result.owned_volumes, result.owned_networks) == (1, 2, 1)
    assert all("--no-trunc" in cmd for cmd in runner.commands if cmd[3:5] == ("ps", "-a"))
    assert not any(x in cmd for cmd in runner.commands for x in ("up", "rm", "restart", "prune"))


def test_truncated_resource_identity_is_fail_closed() -> None:
    runner = FakeDocker(owned=True)
    runner.containers = ["a" * 12 + "|isoas-backend-1"]
    with pytest.raises(ProbeError, match="TARGET_METADATA_INVALID"):
        probe_target("desktop-linux", "isoas", runner=runner)
