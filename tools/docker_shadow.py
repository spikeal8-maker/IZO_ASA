"""Owned, exact-source Docker Shadow lifecycle; never a production launcher."""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import tempfile
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
                 api_port: int = 48126, root: Path = ROOT, *, fixture: bool = False,
                 executor_context: str | None = None, engine_id: str | None = None,
                 machine_sha256: str | None = None):
        self.project, self.sha, self.root = project, sha, root.resolve()
        self.web_port, self.api_port = web_port, api_port
        self.env = child_environment(project, sha, web_port, api_port)
        if type(fixture) is not bool:
            raise ShadowError("SHADOW_FIXTURE_MODE_INVALID")
        self.fixture, self.executor = fixture, None
        identity = (executor_context, engine_id, machine_sha256)
        if any(value is not None for value in identity):
            if not all(isinstance(value, str) and value for value in identity):
                raise ShadowError("SHADOW_EXECUTOR_IDENTITY_REQUIRED")
            from tools.docker_shadow_executor import IsolatedExecutor
            self.executor = IsolatedExecutor(self.run, context=executor_context,
                                             engine_id=engine_id, machine_sha256=machine_sha256)
        self.files = [self.root / "ops/docker/dev" / name
                      for name in ("compose.yml", "compose.shadow.yml")]
        if fixture:
            self.files.append(self.root / "ops/docker/dev/compose.acceptance.yml")

    def run(self, args: list[str], *, capture: bool = True, timeout: int = 60) -> str:
        result = subprocess.run(args, cwd=self.root, env=self.env, text=True,
                                capture_output=capture, timeout=timeout, check=False)
        if result.returncode:
            # Command output is not echoed: Docker config/inspect may contain sensitive state.
            raise ShadowError(f"SHADOW_COMMAND_FAILED command={args[0]} exit={result.returncode}")
        return (result.stdout or "").strip()

    def docker(self, *args: str, **kwargs) -> str:
        if self.executor is not None:
            return self.executor.docker(*args, **kwargs)
        return self.run(["docker", "--context", "desktop-linux", *args], **kwargs)

    def compose(self, *args: str, override: Path | None = None, **kwargs) -> str:
        command = ["compose", "--env-file", os.devnull, "--project-name", self.project]
        for path in self.files:
            command.extend(["-f", str(path)])
        if override is not None:
            command.extend(["-f", str(override)])
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
                valid_network = valid_network and service.get("dns") == ["127.0.0.1"]
            else:
                valid_network = service.get("network_mode") == "service:guard" and not service.get("networks")
                valid_network = valid_network and service.get("depends_on", {}).get("guard", {}).get("condition") == "service_healthy"
            if not valid_network:
                raise ShadowError("SHADOW_CONFIG_NETWORK_INVALID")
            if name == "guard":
                if service.get("healthcheck", {}).get("test") != ["CMD", "python", "/network_guard.py", "--check"]:
                    raise ShadowError("SHADOW_CONFIG_POLICY_INVALID")
            elif (service.get("user") not in {"10001:10001", "101:101"}
                  or service.get("cap_add")):
                raise ShadowError("SHADOW_CONFIG_PRIVILEGE_INVALID")
            if service.get("cap_drop") != ["ALL"] or "no-new-privileges:true" not in service.get("security_opt", []):
                raise ShadowError("SHADOW_CONFIG_PRIVILEGE_INVALID")
            if service["labels"].get("io.izo.owner") != OWNER:
                raise ShadowError("SHADOW_CONFIG_OWNER_INVALID")
            if any(port.get("host_ip") != "127.0.0.1" for port in service.get("ports", [])):
                raise ShadowError("SHADOW_CONFIG_PORT_INVALID")
            if any(v["type"] != "volume" for v in service.get("volumes", [])):
                raise ShadowError("SHADOW_CONFIG_MOUNT_INVALID")
        if self.fixture:
            backend = services["backend"]
            environment = backend.get("environment", {})
            expected = {"IZO_SHADOW_FIXTURE": "controlled-comfyui-v1",
                        "COMFYUI_BASE_URL": "http://127.0.0.1:48991",
                        "COMFYUI_MOCK_FALLBACK": "false"}
            if (any(environment.get(key) != value for key, value in expected.items())
                    or backend.get("command") != ["python", "/opt/izo/fixtures/docker_shadow_fixture.py"]):
                raise ShadowError("SHADOW_FIXTURE_CONFIG_INVALID")
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

    def image_guard(self, config: dict) -> dict[str, str]:
        """Read image identity before lifecycle mutation and return immutable IDs."""
        images = {}
        for service, settings in config["services"].items():
            reference = settings.get("image")
            if not isinstance(reference, str) or not reference:
                raise ShadowError("SHADOW_IMAGE_REFERENCE_INVALID")
            try:
                entries = json.loads(self.docker("image", "inspect", reference))
                if not isinstance(entries, list) or len(entries) != 1:
                    raise ValueError
                image = entries[0]
                image_id = image["Id"]
                labels = image["Config"]["Labels"]
                if (labels.get("org.opencontainers.image.revision") != self.sha
                        or labels.get("org.opencontainers.image.source") != "spikeal8-maker/IZO_ASA"):
                    raise ShadowError("SHADOW_IMAGE_SOURCE_MISMATCH")
                if not isinstance(image_id, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", image_id):
                    raise ValueError
            except (ValueError, KeyError, TypeError, AttributeError):
                raise ShadowError("SHADOW_IMAGE_METADATA_INVALID") from None
            images[service] = image_id
        return images

    def up(self, *, build: bool = True, recreate: bool = False) -> None:
        self.source_guard()
        config = self.config()
        self.ownership_guard()
        if build:
            # Keep cold Node/pip builds from competing for Desktop's memory.
            # A failed build must leave the currently running stack untouched.
            for service in ("backend", "guard", "web"):
                self.compose("build", service, capture=False, timeout=1200)
        images = self.image_guard(config)
        # A long build may overlap local edits. Never start them with an old SHA.
        self.source_guard()
        args = ["up", "-d", "--wait", "--wait-timeout", "180", "--no-build", "--pull", "never"]
        if recreate:
            args.append("--force-recreate")
        # Tags are mutable even after inspection. Compose receives only the
        # verified local IDs, and cannot pull replacements from a registry.
        with tempfile.TemporaryDirectory(prefix="izo-shadow-images-") as directory:
            override = Path(directory) / "images.json"
            override.write_text(json.dumps({"services": {
                service: {"image": image_id, "pull_policy": "never"}
                for service, image_id in images.items()
            }}), encoding="utf-8")
            self.compose(*args, override=override, capture=False, timeout=1200)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("config", "up", "status", "down", "recreate", "smoke"))
    parser.add_argument("--project", required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--web-port", type=int, default=48125)
    parser.add_argument("--api-port", type=int, default=48126)
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--fixture", action="store_true")
    parser.add_argument("--isolated-linux", action="store_true")
    parser.add_argument("--executor-context")
    parser.add_argument("--engine-id")
    parser.add_argument("--machine-sha256")
    args = parser.parse_args()
    try:
        identity = (args.executor_context, args.engine_id, args.machine_sha256)
        if args.isolated_linux != all(value is not None for value in identity):
            raise ShadowError("SHADOW_EXECUTOR_IDENTITY_REQUIRED")
        if not args.isolated_linux and any(value is not None for value in identity):
            raise ShadowError("SHADOW_EXECUTOR_MODE_REQUIRED")
        shadow = Shadow(args.project, args.source_sha, args.web_port, args.api_port,
                        fixture=args.fixture, executor_context=args.executor_context,
                        engine_id=args.engine_id, machine_sha256=args.machine_sha256)
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
