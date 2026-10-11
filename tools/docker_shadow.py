"""Owned, exact-source Docker Shadow lifecycle; never a production launcher."""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OWNER = "SHADOW-TOPOLOGY-01"
PROJECT = re.compile(r"^izo-asa-shadow-[a-z0-9][a-z0-9-]{2,39}$")
SHA = re.compile(r"^[0-9a-f]{40}$")
HOST_ENV = ("PATH", "SystemRoot", "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP",
            "USERPROFILE", "APPDATA", "LOCALAPPDATA", "HOME", "ProgramData", "ProgramFiles",
            "ProgramW6432", "CommonProgramFiles", "SystemDrive", "HOMEDRIVE", "HOMEPATH")


class ShadowError(RuntimeError):
    pass


def child_environment(project: str, sha: str, web_port: int, api_port: int) -> dict[str, str]:
    if not PROJECT.fullmatch(project) or not SHA.fullmatch(sha):
        raise ShadowError("SHADOW_IDENTITY_INVALID")
    if web_port == api_port or any(not 20000 <= p <= 65535 for p in (web_port, api_port)):
        raise ShadowError("SHADOW_PORT_INVALID")
    return {**{k: os.environ[k] for k in HOST_ENV if k in os.environ},
            "IZO_COMPOSE_PROJECT": project, "IZO_SOURCE_SHA": sha,
            "IZO_SHADOW_WEB_PORT": str(web_port), "IZO_SHADOW_API_PORT": str(api_port)}


class Shadow:
    def __init__(self, project: str, sha: str, web_port: int = 48125,
                 api_port: int = 48126, root: Path = ROOT):
        self.project, self.sha, self.root = project, sha, root.resolve()
        self.web_port, self.api_port = web_port, api_port
        self.env = child_environment(project, sha, web_port, api_port)
        self.files = [self.root / "ops/docker/dev" / name
                      for name in ("compose.yml", "compose.shadow.yml")]

    def run(self, args: list[str], *, capture: bool = True, timeout: int = 60) -> str:
        result = subprocess.run(args, cwd=self.root, env=self.env, text=True,
                                capture_output=capture, timeout=timeout, check=False)
        if result.returncode:
            # Command output is not echoed: Docker config/inspect may contain sensitive state.
            raise ShadowError(f"SHADOW_COMMAND_FAILED command={args[0]} exit={result.returncode}")
        return (result.stdout or "").strip()

    def docker(self, *args: str, **kwargs) -> str:
        return self.run(["docker", "--context", "desktop-linux", *args], **kwargs)

    def compose(self, *args: str, **kwargs) -> str:
        command = ["compose", "--env-file", os.devnull, "--project-name", self.project]
        for path in self.files:
            command.extend(["-f", str(path)])
        return self.docker(*command, *args, **kwargs)

    def source_guard(self) -> None:
        origin = self.run(["git", "remote", "get-url", "origin"])
        if not re.search(r"[/:]spikeal8-maker/IZO_ASA(?:\.git)?$", origin):
            raise ShadowError("SHADOW_REPOSITORY_MISMATCH")
        if self.run(["git", "rev-parse", "HEAD"]) != self.sha:
            raise ShadowError("SHADOW_SOURCE_MISMATCH")
        if self.run(["git", "status", "--porcelain"]):
            raise ShadowError("SHADOW_SOURCE_DIRTY")

    def config(self) -> dict:
        config = json.loads(self.compose("config", "--format", "json"))
        services = config["services"]
        if set(services) != {"backend", "web", "guard"} or set(config["networks"]) != {"shadow"}:
            raise ShadowError("SHADOW_CONFIG_NETWORK_INVALID")
        for name, service in services.items():
            if name == "guard":
                valid_network = set(service.get("networks", {})) == {"shadow"} and not service.get("network_mode")
            else:
                valid_network = service.get("network_mode") == "service:guard" and not service.get("networks")
                valid_network = valid_network and service.get("depends_on", {}).get("guard", {}).get("condition") == "service_healthy"
            if not valid_network:
                raise ShadowError("SHADOW_CONFIG_NETWORK_INVALID")
            if service["labels"].get("io.izo.owner") != OWNER:
                raise ShadowError("SHADOW_CONFIG_OWNER_INVALID")
            if any(port.get("host_ip") != "127.0.0.1" for port in service.get("ports", [])):
                raise ShadowError("SHADOW_CONFIG_PORT_INVALID")
            if any(v["type"] != "volume" for v in service.get("volumes", [])):
                raise ShadowError("SHADOW_CONFIG_MOUNT_INVALID")
        return config

    def containers(self) -> list[dict]:
        ids = self.docker("ps", "-aq", "--filter", f"label=com.docker.compose.project={self.project}").split()
        return json.loads(self.docker("inspect", *ids)) if ids else []

    def ownership_guard(self) -> None:
        for container in self.containers():
            labels = container["Config"].get("Labels", {})
            if labels.get("io.izo.owner") != OWNER or labels.get("com.docker.compose.service") not in {"backend", "web", "guard"}:
                raise ShadowError("SHADOW_FOREIGN_CONTAINER")
        for kind in ("volume", "network"):
            ids = self.docker(kind, "ls", "-q", "--filter", f"label=com.docker.compose.project={self.project}").split()
            if ids:
                for resource in json.loads(self.docker(kind, "inspect", *ids)):
                    if resource.get("Labels", {}).get("io.izo.owner") != OWNER:
                        raise ShadowError(f"SHADOW_FOREIGN_{kind.upper()}")
        # Reject an unlabeled resource squatting on a Compose-generated name too.
        expected = [("volume", f"{self.project}_{name}") for name in ("sqlite-data", "media-data")]
        expected.append(("network", f"{self.project}_shadow"))
        for kind, name in expected:
            names = self.docker(kind, "ls", "--format", "{{.Name}}").splitlines()
            if name in names:
                item = json.loads(self.docker(kind, "inspect", name))[0]
                labels = item.get("Labels") or {}
                if labels.get("io.izo.owner") != OWNER or labels.get("com.docker.compose.project") != self.project:
                    raise ShadowError("SHADOW_RESOURCE_NAME_COLLISION")

    def up(self, *, build: bool = True, recreate: bool = False) -> None:
        self.source_guard()
        self.config()
        self.ownership_guard()
        if build:
            # Keep cold Node/pip builds from competing for Desktop's memory.
            # A failed build must leave the currently running stack untouched.
            for service in ("backend", "guard", "web"):
                self.compose("build", service, capture=False, timeout=1200)
        args = ["up", "-d", "--wait", "--wait-timeout", "180", "--no-build"]
        if recreate:
            args.append("--force-recreate")
        self.compose(*args, capture=False, timeout=1200)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("config", "up", "status", "down", "recreate", "smoke"))
    parser.add_argument("--project", required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--web-port", type=int, default=48125)
    parser.add_argument("--api-port", type=int, default=48126)
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args()
    try:
        shadow = Shadow(args.project, args.source_sha, args.web_port, args.api_port)
        if args.action == "config":
            shadow.config()
        elif args.action in {"up", "recreate"}:
            shadow.up(build=args.action == "up", recreate=args.action == "recreate")
        elif args.action == "smoke":
            try:
                from tools.docker_shadow_smoke import prove
            except ModuleNotFoundError:
                from docker_shadow_smoke import prove
            receipt = args.receipt or ROOT / ".runtime/shadow" / f"{args.project}.json"
            prove(shadow, receipt)
        else:
            shadow.config()
            shadow.ownership_guard()
            if args.action == "down":
                shadow.compose("down", capture=False)
            else:
                print(shadow.compose("ps", "--format", "json"))
        print(f"SHADOW_OK action={args.action} project={args.project} source={args.source_sha}")
        return 0
    except (RuntimeError, subprocess.TimeoutExpired, ValueError, KeyError, OSError) as exc:
        print(f"SHADOW_FAILED {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
