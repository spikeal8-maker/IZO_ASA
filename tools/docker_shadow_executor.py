"""Explicit isolated Linux guest adapter; no production evidence or host settings."""
from __future__ import annotations

import hashlib
import ipaddress
import json
import platform
import re
import socket
import subprocess
import threading
import time
from pathlib import Path

OWNER = "SHADOW-TOPOLOGY-01"
PROJECT = re.compile(r"izo-asa-shadow-[a-z0-9][a-z0-9-]{2,39}")


class ExecutorError(RuntimeError):
    pass


def require(value: bool, code: str) -> None:
    if not value:
        raise ExecutorError(code)


def guest_identity() -> str:
    require(platform.system() == "Linux", "EXECUTOR_LINUX_GUEST_REQUIRED")
    try:
        with Path("/etc/machine-id").open(encoding="ascii") as source:
            value = source.read(129).strip()
    except (OSError, UnicodeError):
        raise ExecutorError("EXECUTOR_GUEST_ID_UNAVAILABLE") from None
    require(re.fullmatch(r"[0-9a-f]{32}", value) is not None, "EXECUTOR_GUEST_ID_INVALID")
    return hashlib.sha256(value.encode("ascii")).hexdigest()


class IsolatedExecutor:
    """Pin identities captured separately over the owned guest's trusted transport.

    A caller-provided identity is an admission constraint, not proof that a guest
    is physically isolated. The VM owner must establish that fact independently.
    ``run`` is the existing launcher's sanitized, shell-free command runner.
    """

    def __init__(self, run, *, context: str, engine_id: str, machine_sha256: str):
        require(isinstance(context, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", context) is not None,
                "EXECUTOR_CONTEXT_INVALID")
        require(isinstance(engine_id, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9:._-]{15,127}", engine_id) is not None,
                "EXECUTOR_ENGINE_ID_INVALID")
        require(isinstance(machine_sha256, str) and re.fullmatch(r"[0-9a-f]{64}", machine_sha256) is not None,
                "EXECUTOR_MACHINE_HASH_INVALID")
        self.run, self.context = run, context
        self.engine_id, self.machine_sha256 = engine_id, machine_sha256

    def _command(self, args, **kwargs):
        try:
            return self.run(["docker", "--context", self.context, *args], **kwargs)
        except (OSError, RuntimeError, subprocess.SubprocessError):
            raise ExecutorError("EXECUTOR_COMMAND_FAILED") from None

    def _json(self, args, *, identity_query=False):
        if not identity_query:
            self.verify()
        try:
            raw = self._command(args)
            require(isinstance(raw, str) and len(raw) <= 1_000_000, "EXECUTOR_METADATA_SIZE_INVALID")
            return json.loads(raw)
        except (ValueError, TypeError, KeyError):
            raise ExecutorError("EXECUTOR_METADATA_INVALID") from None

    def verify(self) -> dict:
        require(guest_identity() == self.machine_sha256, "EXECUTOR_GUEST_CHANGED")
        try:
            contexts = self._json(["context", "inspect", self.context], identity_query=True)
            require(isinstance(contexts, list) and len(contexts) == 1, "EXECUTOR_CONTEXT_METADATA_INVALID")
            context = contexts[0]
            require(context["Name"] == self.context and
                    context["Endpoints"]["docker"]["Host"] == "unix:///var/run/docker.sock",
                    "EXECUTOR_LOCAL_UNIX_SOCKET_REQUIRED")
            info = self._json(["info", "--format", "{{json .}}"], identity_query=True)
            require(info["ID"] == self.engine_id and info["OSType"] == "linux", "EXECUTOR_ENGINE_CHANGED")
            return {"engineId": self.engine_id, "context": self.context,
                    "machineIdentitySha256": self.machine_sha256}
        except (KeyError, TypeError, IndexError):
            raise ExecutorError("EXECUTOR_METADATA_INVALID") from None

    def docker(self, *args, **kwargs):
        validate_command(args)
        self.verify()
        return self._command(args, **kwargs)

    def gateway(self, project: str) -> str:
        require(isinstance(project, str) and PROJECT.fullmatch(project) is not None, "EXECUTOR_PROJECT_INVALID")
        self.verify()
        try:
            entries = self._json(["network", "inspect", project + "_shadow"])
            require(isinstance(entries, list) and len(entries) == 1, "EXECUTOR_NETWORK_METADATA_INVALID")
            network = entries[0]
            labels = network["Labels"]
            require(network["Name"] == project + "_shadow" and network["Driver"] == "bridge"
                    and labels.get("io.izo.owner") == OWNER
                    and labels.get("com.docker.compose.project") == project,
                    "EXECUTOR_NETWORK_NOT_OWNED")
            configs = network["IPAM"]["Config"]
            require(isinstance(configs, list) and len(configs) == 1, "EXECUTOR_GATEWAY_AMBIGUOUS")
            address = ipaddress.ip_address(configs[0]["Gateway"])
            subnet = ipaddress.ip_network(configs[0]["Subnet"])
            private = [ipaddress.ip_network(value) for value in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")]
            require(address.version == subnet.version == 4 and any(subnet.subnet_of(value) for value in private)
                    and not address.is_loopback and not address.is_link_local
                    and address in subnet and address not in (subnet.network_address, subnet.broadcast_address),
                    "EXECUTOR_GATEWAY_INVALID")
            return str(address)
        except (ValueError, KeyError, TypeError, IndexError):
            raise ExecutorError("EXECUTOR_METADATA_INVALID") from None

    def foreign_snapshot(self, project: str) -> dict:
        require(isinstance(project, str) and PROJECT.fullmatch(project) is not None, "EXECUTOR_PROJECT_INVALID")
        identity, resources = self.verify(), {}
        commands = {"container": ["ps", "-aq", "--no-trunc"], "volume": ["volume", "ls", "-q"],
                    "network": ["network", "ls", "-q", "--no-trunc"]}
        try:
            for kind, command in commands.items():
                ids = self.docker(*command).split()
                require(len(ids) <= 256 and len(set(ids)) == len(ids), "EXECUTOR_INVENTORY_LIMIT")
                entries = self._json((["inspect"] if kind == "container" else [kind, "inspect"]) + ids) if ids else []
                require(isinstance(entries, list) and len(entries) == len(ids), "EXECUTOR_INVENTORY_INVALID")
                inspected_ids = [entry["Name"] if kind == "volume" else entry["Id"] for entry in entries]
                require(set(inspected_ids) == set(ids), "EXECUTOR_INSPECTION_ID_MISMATCH")
                rows = []
                for entry in entries:
                    labels = (entry["Config"].get("Labels") if kind == "container" else entry.get("Labels")) or {}
                    if labels.get("io.izo.owner") == OWNER and labels.get("com.docker.compose.project") == project:
                        continue
                    row = {"id": entry.get("Id", entry["Name"]), "name": entry["Name"]}
                    if kind == "container":
                        state = entry["State"]
                        row.update(image=entry["Image"], started=state["StartedAt"],
                                   running=state["Running"], pid=state["Pid"])
                    rows.append(row)
                resources[kind] = sorted(rows, key=lambda row: row["id"])
            require(self.verify() == identity, "EXECUTOR_IDENTITY_CHANGED_DURING_SNAPSHOT")
            observed = {"scope": "ISOLATED_GUEST_ONLY", "identity": identity,
                        "foreignResources": resources, "productionUnchanged": "NOT_VERIFIED_HERE"}
            validate_snapshot(observed)
            return observed
        except (ValueError, KeyError, TypeError):
            raise ExecutorError("EXECUTOR_METADATA_INVALID") from None


def validate_command(args) -> None:
    require(args and all(isinstance(value, str) for value in args)
            and args[0] in {"compose", "ps", "inspect", "network", "volume", "image", "run", "exec", "rm", "stats", "info"},
            "EXECUTOR_COMMAND_NOT_ALLOWED")
    # Routing/configuration flags cannot replace the pinned context. Container
    # command payloads are opaque: their legitimate ``python -c`` is preserved.
    valued = {"--name", "--network", "--label", "--user", "--cap-drop", "--security-opt",
              "--memory", "--pids-limit", "--cpus", "--entrypoint", "--workdir", "--env", "-e", "-u", "-w"}
    boolean = {"-d", "--detach", "--rm", "--read-only", "-i", "--interactive", "-t", "--tty", "--init"}
    routing = {"--context", "--host", "--config", "--tls", "--tlsverify", "--tlscacert", "--tlscert", "--tlskey"}
    index = 1
    while index < len(args):
        value, key = args[index], args[index].split("=", 1)[0]
        require(key not in routing and not value.startswith(("-H", "-c")), "EXECUTOR_ROUTING_OVERRIDE_FORBIDDEN")
        if args[0] in {"run", "exec"}:
            if value == "--":
                require(index + 1 < len(args) and not args[index + 1].startswith("-"), "EXECUTOR_CONTAINER_REQUIRED")
                return
            if not value.startswith("-"):
                return
            require(key in valued or key in boolean, "EXECUTOR_CONTAINER_OPTION_NOT_ALLOWED")
            if key in valued and "=" not in value:
                require(index + 1 < len(args) and not args[index + 1].startswith("-"), "EXECUTOR_OPTION_VALUE_REQUIRED")
                index += 1
        index += 1
    require(args[0] not in {"run", "exec"}, "EXECUTOR_CONTAINER_REQUIRED")


def validate_snapshot(snapshot) -> None:
    require(isinstance(snapshot, dict) and snapshot.get("scope") == "ISOLATED_GUEST_ONLY"
            and isinstance(snapshot.get("identity"), dict) and isinstance(snapshot.get("foreignResources"), dict),
            "EXECUTOR_SNAPSHOTS_INCOMPLETE")
    identity, resources = snapshot["identity"], snapshot["foreignResources"]
    require(set(identity) == {"engineId", "context", "machineIdentitySha256"}
            and all(isinstance(value, str) and value for value in identity.values())
            and set(resources) == {"container", "volume", "network"}, "EXECUTOR_SNAPSHOTS_INCOMPLETE")
    require(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9:._-]{15,127}", identity["engineId"]) is not None
            and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", identity["context"]) is not None
            and re.fullmatch(r"[0-9a-f]{64}", identity["machineIdentitySha256"]) is not None,
            "EXECUTOR_SNAPSHOTS_INCOMPLETE")
    for kind, rows in resources.items():
        require(isinstance(rows, list) and len(rows) <= 256, "EXECUTOR_SNAPSHOTS_INCOMPLETE")
        seen = set()
        for row in rows:
            fields = {"id", "name", "image", "started", "running", "pid"} if kind == "container" else {"id", "name"}
            require(isinstance(row, dict) and set(row) == fields, "EXECUTOR_SNAPSHOTS_INCOMPLETE")
            require(all(isinstance(row[name], str) and 0 < len(row[name]) <= 256
                        and not any(ord(char) < 32 for char in row[name]) for name in ("id", "name")),
                    "EXECUTOR_SNAPSHOTS_INCOMPLETE")
            require(row["id"] not in seen, "EXECUTOR_DUPLICATE_SNAPSHOT_ID")
            seen.add(row["id"])
            require((re.fullmatch(r"[0-9a-f]{64}", row["id"]) is not None if kind != "volume"
                     else row["id"] == row["name"] and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,254}", row["id"]) is not None),
                    "EXECUTOR_SNAPSHOTS_INCOMPLETE")
            if kind == "container":
                require(isinstance(row["image"], str) and re.fullmatch(r"sha256:[0-9a-f]{64}", row["image"]) is not None
                        and isinstance(row["started"], str) and 0 < len(row["started"]) <= 128
                        and type(row["running"]) is bool and type(row["pid"]) is int and row["pid"] >= 0,
                        "EXECUTOR_SNAPSHOTS_INCOMPLETE")


def compare_isolated(before: dict, after: dict) -> dict:
    validate_snapshot(before)
    validate_snapshot(after)
    checks = {name: before[name] == after[name] for name in ("identity", "foreignResources")}
    return {"status": "PASS" if all(checks.values()) else "FAIL", "checks": checks,
            "scope": "ISOLATED_GUEST_ONLY", "productionUnchanged": "NOT_VERIFIED_HERE"}


class GatewayListener:
    """A temporary guest-native listener, never a host-namespace container.

    It binds only the validated owned bridge gateway at an ephemeral port. The
    unfiltered positive-control client must observe ``shadow-fixture`` before
    testing filtered clients; connection failure alone proves nothing.
    """

    def __init__(self, executor: IsolatedExecutor, project: str, *, seconds: float = 30):
        require(isinstance(seconds, (int, float)) and 0 < seconds <= 60, "EXECUTOR_LISTENER_LIFETIME_INVALID")
        self.executor, self.project, self.seconds = executor, project, seconds
        self.socket = None
        self.thread = None
        self.stop = threading.Event()
        self.accepted = 0
        self.failed = False

    def __enter__(self):
        require(self.socket is None and self.thread is None, "EXECUTOR_LISTENER_ALREADY_USED")
        gateway = self.executor.gateway(self.project)
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            server.settimeout(.2)
            server.bind((gateway, 0))
            server.listen(4)
            self.socket = server
            self.address, self.port = server.getsockname()
            self.thread = threading.Thread(target=self._serve, name="izo-owned-gateway-proof", daemon=True)
            self.thread.start()
            return self
        except Exception:
            server.close()
            self.socket = None
            raise ExecutorError("EXECUTOR_LISTENER_START_FAILED") from None

    def _serve(self):
        deadline = time.monotonic() + self.seconds
        try:
            while not self.stop.is_set() and time.monotonic() < deadline and self.accepted < 32:
                try:
                    client, _ = self.socket.accept()
                except socket.timeout:
                    continue
                with client:
                    self.accepted += 1
                    client.settimeout(.2)
                    client.sendall(b"shadow-fixture")
        except OSError:
            self.failed = not self.stop.is_set()
        finally:
            self.socket.close()

    def close(self):
        self.stop.set()
        if self.socket is not None:
            self.socket.close()
        if self.thread is not None:
            self.thread.join(timeout=1)
            require(not self.thread.is_alive(), "EXECUTOR_LISTENER_THREAD_NOT_STOPPED")
        require(not self.failed, "EXECUTOR_LISTENER_FAILED")

    def __exit__(self, *_):
        self.close()
