"""Fail-closed, read-only Docker target inventory for one ISOAS installation.

No Docker resource lifecycle, executable shell, host configuration, service,
secrets, media or database access is possible through this interface.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from dataclasses import dataclass
from typing import Callable

CONTEXT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
PROJECT = re.compile(r"^isoas(?:-[a-z0-9][a-z0-9-]{1,46})?$")
IDENTIFIER = re.compile(r"^[0-9a-f]{64}$")
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
VERSION = re.compile(r"^v?[0-9]+\.[0-9]+\.[0-9]+(?:[-+][A-Za-z0-9.-]+)?$")
HOST_KEYS = frozenset({
    "PATH", "SystemRoot", "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP",
    "USERPROFILE", "APPDATA", "LOCALAPPDATA", "HOME", "HOMEDRIVE",
    "HOMEPATH", "SystemDrive", "XDG_RUNTIME_DIR", "XDG_CONFIG_HOME",
})
INFO = ("info", "--format", "{{.ID}}|{{.OSType}}|{{.ServerVersion}}")
COMPOSE = ("compose", "version", "--short")
PS = ("ps", "-a", "--no-trunc", "--format", "{{.ID}}|{{.Names}}")
NAME_FORMAT = "{{.Name}}"


class ProbeError(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class TargetInfo:
    context: str
    installation: str
    server_version: str
    compose_version: str
    engine_fingerprint: str
    owned_containers: int
    owned_volumes: int
    owned_networks: int

    @property
    def has_installation(self) -> bool:
        return bool(self.owned_containers or self.owned_volumes or self.owned_networks)


def clean_child_environment(source: dict[str, str] | None = None) -> dict[str, str]:
    source = dict(os.environ) if source is None else source
    # Never inherit DOCKER_*, COMPOSE_*, proxies, provider keys or credentials.
    return {key: value for key, value in source.items() if key in HOST_KEYS}


def _safe_read_command(args: tuple[str, ...]) -> bool:
    if args in {INFO, COMPOSE, PS}:
        return True
    if len(args) == 7 and args[:4] == ("ps", "-a", "--no-trunc", "--filter") and args[5:] == (
        "--format", "{{.ID}}|{{.Names}}"
    ):
        name = args[4].removeprefix("label=com.docker.compose.project=")
        return args[4].startswith("label=com.docker.compose.project=") and PROJECT.fullmatch(name) is not None
    if len(args) == 4 and args[0] in {"volume", "network"} and args[1:] == (
        "ls", "--format", NAME_FORMAT
    ):
        return True
    if len(args) == 6 and args[0] in {"volume", "network"} and args[1:3] == (
        "ls", "--filter"
    ) and args[4:] == ("--format", NAME_FORMAT):
        name = args[3].removeprefix("label=com.docker.compose.project=")
        return args[3].startswith("label=com.docker.compose.project=") and PROJECT.fullmatch(name) is not None
    if len(args) == 4 and args[:3] == ("inspect", "--format", "{{json .Config.Labels}}"):
        return IDENTIFIER.fullmatch(args[3]) is not None
    if len(args) == 5 and args[0] in {"volume", "network"} and args[1:3] == (
        "inspect", "--format"
    ) and args[3] == "{{json .Labels}}":
        return NAME.fullmatch(args[4]) is not None
    return False


class DockerReader:
    def __init__(
        self,
        context: str,
        *,
        runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    ):
        if not isinstance(context, str) or CONTEXT.fullmatch(context) is None:
            raise ProbeError("INVALID_CONTEXT")
        self.context = context
        self.runner = runner

    def read(self, *args: str) -> str:
        if not _safe_read_command(args):
            raise ProbeError("FORBIDDEN_DOCKER_COMMAND")
        command = ["docker", "--context", self.context, *args]
        try:
            result = self.runner(
                command,
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=12, check=False, env=clean_child_environment(),
            )
        except (OSError, subprocess.TimeoutExpired):
            raise ProbeError("TARGET_UNAVAILABLE") from None
        if result.returncode != 0 or not isinstance(result.stdout, str):
            raise ProbeError("TARGET_UNAVAILABLE")
        if len(result.stdout.encode("utf-8")) > 256 * 1024:
            raise ProbeError("TARGET_RESPONSE_TOO_LARGE")
        return result.stdout.strip()

    def labels(self, kind: str, identity: str) -> dict[str, str]:
        if kind == "container":
            if IDENTIFIER.fullmatch(identity) is None:
                raise ProbeError("TARGET_METADATA_INVALID")
            raw = self.read("inspect", "--format", "{{json .Config.Labels}}", identity)
        elif kind in {"volume", "network"}:
            if NAME.fullmatch(identity) is None:
                raise ProbeError("TARGET_METADATA_INVALID")
            raw = self.read(kind, "inspect", "--format", "{{json .Labels}}", identity)
        else:
            raise ProbeError("TARGET_METADATA_INVALID")
        try:
            value = json.loads(raw)
        except (ValueError, TypeError):
            raise ProbeError("TARGET_METADATA_INVALID") from None
        if not isinstance(value, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in value.items()
        ):
            raise ProbeError("TARGET_METADATA_INVALID")
        return value


def _name_reserved(name: str, installation: str) -> bool:
    if installation == "isoas" and name.startswith("isoas-ci-"):
        return False  # Canonically isolated disposable CI installation.
    return name == installation or name.startswith(installation + "-") or name.startswith(installation + "_")


def _names(raw: str) -> set[str]:
    items = raw.splitlines()
    if any(NAME.fullmatch(item) is None for item in items):
        raise ProbeError("TARGET_METADATA_INVALID")
    return set(items)


def _labels_owned(labels: dict[str, str], installation: str) -> bool:
    return labels.get("com.docker.compose.project") == installation and labels.get("io.isoas.project") == "ISOAS"


def probe_target(
    context: str,
    installation: str,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> TargetInfo:
    if not isinstance(installation, str) or PROJECT.fullmatch(installation) is None:
        raise ProbeError("INVALID_INSTALLATION")
    reader = DockerReader(context, runner=runner)
    identity = reader.read(*INFO).split("|")
    if (len(identity) != 3 or not identity[0] or len(identity[0]) > 128
            or not VERSION.fullmatch(identity[2])):
        raise ProbeError("TARGET_METADATA_INVALID")
    if identity[1] != "linux":
        raise ProbeError("TARGET_OSTYPE_UNSUPPORTED")
    compose = reader.read(*COMPOSE)
    if VERSION.fullmatch(compose) is None:
        raise ProbeError("TARGET_METADATA_INVALID")

    container_ids: dict[str, str] = {}
    marked_ps = (
        "ps", "-a", "--no-trunc", "--filter", f"label=com.docker.compose.project={installation}",
        "--format", "{{.ID}}|{{.Names}}",
    )
    for args in (PS, marked_ps):
        for line in reader.read(*args).splitlines():
            values = line.split("|", 1)
            if (len(values) != 2 or IDENTIFIER.fullmatch(values[0]) is None
                    or NAME.fullmatch(values[1]) is None):
                raise ProbeError("TARGET_METADATA_INVALID")
            if args == marked_ps or _name_reserved(values[1], installation):
                if values[0] in container_ids and container_ids[values[0]] != values[1]:
                    raise ProbeError("TARGET_METADATA_INVALID")
                container_ids[values[0]] = values[1]
    for identifier in sorted(container_ids):
        if not _labels_owned(reader.labels("container", identifier), installation):
            raise ProbeError("OWNERSHIP_CONFLICT")

    counts: dict[str, int] = {}
    for kind in ("volume", "network"):
        all_names = _names(reader.read(kind, "ls", "--format", NAME_FORMAT))
        marked = _names(reader.read(
            kind, "ls", "--filter", f"label=com.docker.compose.project={installation}",
            "--format", NAME_FORMAT,
        ))
        candidates = sorted({name for name in all_names if _name_reserved(name, installation)} | marked)
        for name in candidates:
            if not _labels_owned(reader.labels(kind, name), installation):
                raise ProbeError("OWNERSHIP_CONFLICT")
        counts[kind] = len(candidates)

    return TargetInfo(
        context=context,
        installation=installation,
        server_version=identity[2],
        compose_version=compose.lstrip("v"),
        engine_fingerprint=hashlib.sha256(identity[0].encode("utf-8")).hexdigest(),
        owned_containers=len(container_ids),
        owned_volumes=counts["volume"],
        owned_networks=counts["network"],
    )
