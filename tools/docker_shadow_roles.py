"""Exact split-role identities for the opt-in Docker acceptance profile."""
from __future__ import annotations

import json
import hashlib
import re
from datetime import datetime

DATA_TARGETS = {"/home/izo/data": "sqlite-data", "/home/izo/media": "media-data"}
IPC_TARGET, IPC_VOLUME = "/home/izo/worker", "worker_ipc"
SOCKET = IPC_TARGET + "/generation.sock"
WORKERS = ("worker", "worker_peer")
COMMAND = ["python", "-m", "app.generation_worker"]
ENVIRONMENT = {"IZO_PROCESS_ROLE": "worker", "IZO_WORKER_SOCKET": SOCKET}


def require(condition, code):
    if not condition:
        try:
            from tools.docker_shadow import ShadowError
        except ModuleNotFoundError:
            from docker_shadow import ShadowError
        raise ShadowError(code)


def services(shadow):
    return {"backend", "guard", "web", *WORKERS} if getattr(shadow, "fixture", False) is True else {"backend", "guard", "web"}


def backend_targets(shadow):
    return {**DATA_TARGETS, **({IPC_TARGET: IPC_VOLUME} if getattr(shadow, "fixture", False) is True else {})}


def volume_override(backend):
    """Compose v2 !override prevents inherited IPC access in offline readers."""
    require(isinstance(backend.get("volumes"), list), "SHADOW_ROLE_OVERRIDE_VOLUMES_REQUIRED")
    return json.dumps({"services": {"backend": backend}}).replace('"volumes": [', '"volumes": !override [', 1) + "\n"


def config_guard(shadow, config):
    if getattr(shadow, "fixture", False) is not True:
        return
    rows, backend = config["services"], config["services"]["backend"]
    expected = backend_targets(shadow)
    require(set(config.get("volumes", {})) == set(expected.values()), "SHADOW_ROLE_VOLUME_SET_INVALID")
    require(all(value.get('labels', {}).get('io.izo.owner') == 'SHADOW-TOPOLOGY-01'
                and not value.get('external') and not value.get('driver_opts')
                for value in config['volumes'].values()), 'SHADOW_ROLE_VOLUME_OWNER_INVALID')
    require(backend.get("environment", {}).get("IZO_PROCESS_ROLE") == "server"
            and backend["environment"].get("IZO_WORKER_SOCKET") == SOCKET,
            "SHADOW_ROLE_SERVER_REQUIRED")
    require(len(backend.get("volumes", [])) == len(expected)
            and all(item.get("type") == "volume" and not item.get("read_only")
                    and expected.get(item.get("target")) == item.get("source") for item in backend["volumes"])
            and {item.get("target") for item in backend["volumes"]} == set(expected),
            "SHADOW_ROLE_SERVER_MOUNTS_INVALID")
    for name in WORKERS:
        worker = rows[name]
        mounts = worker.get("volumes", [])
        require(worker.get("image") == backend.get("image") and bool(worker.get("image"))
                and not worker.get("build") and worker.get("command") == COMMAND
                and worker.get("entrypoint") in (None, []) and worker.get("environment") == ENVIRONMENT
                and worker.get("user") == "10001:10001" and worker.get("read_only") is True
                and worker.get("restart") == "no" and not worker.get("ports") and not worker.get('pid')
                and not worker.get('ipc') and not worker.get('privileged') and not worker.get('devices')
                and worker.get("healthcheck", {}).get("test") == ["CMD", *COMMAND, "--health"]
                and worker.get("depends_on", {}).get("backend", {}).get("condition") == "service_started",
                "SHADOW_ROLE_WORKER_CONFIG_INVALID")
        require(len(mounts) == 1 and mounts[0].get("type") == "volume"
                and mounts[0].get("source") == IPC_VOLUME and mounts[0].get("target") == IPC_TARGET
                and not mounts[0].get("read_only"), "SHADOW_ROLE_WORKER_MOUNTS_INVALID")


def runtime_guard(shadow, container, service):
    """Called after common owner, privilege, image and guard-namespace checks."""
    if getattr(shadow, "fixture", False) is not True or service not in {"backend", *WORKERS}:
        return
    config, host = container["Config"], container["HostConfig"]
    env = dict(item.split("=", 1) for item in config["Env"])
    targets = backend_targets(shadow) if service == "backend" else {IPC_TARGET: IPC_VOLUME}
    mounts = [item for item in container["Mounts"] if item["Type"] == "volume"]
    require(len(mounts) == len(targets) and {item["Destination"] for item in mounts} == set(targets)
            and all(item.get("RW") is True and item.get("Name") == shadow.project + "_" + targets[item["Destination"]]
                    for item in mounts), "SHADOW_ROLE_RUNTIME_MOUNTS_INVALID")
    require(env.get("IZO_PROCESS_ROLE") == ("server" if service == "backend" else "worker")
            and env.get("IZO_WORKER_SOCKET") == SOCKET, "SHADOW_ROLE_RUNTIME_ENVIRONMENT_INVALID")
    if service in WORKERS:
        require(config.get("Cmd") == COMMAND and config.get("Entrypoint") in (None, [])
                and config.get("User") == "10001:10001" and host.get("ReadonlyRootfs") is True
                and not host.get('PidMode') and host.get('IpcMode', '') in {'', 'private'}
                and host.get("RestartPolicy", {}).get("Name") == "no"
                and config.get("Healthcheck", {}).get("Test") == ["CMD", *COMMAND, "--health"]
                and not any(key in env for key in ("DATABASE_URL", "DB_PATH", "MEDIA_DIR", "IZO_SECRET_DIR",
                    "IZO_SHADOW_FIXTURE", "COMFYUI_BASE_URL", "ADMIN_ONE_TIME_CODE", "BOT_TOKEN", "MAX_BOT_TOKEN")),
                "SHADOW_ROLE_RUNTIME_WORKER_INVALID")


def guard_capabilities(value):
    """Docker 28 serializes CAP_ names; legacy inspect may omit that prefix."""
    return (isinstance(value, list) and len(value) == 3 and all(isinstance(item, str) for item in value)
            and {item.removeprefix("CAP_") for item in value} == {"NET_ADMIN", "SETUID", "SETGID"})


def guard_health(health):
    """Bounded inspect diagnostics, without raw probe output or environment."""
    code = "SHADOW_GUARD_HEALTH_METADATA_INVALID"
    require(isinstance(health, dict) and isinstance(health.get("Status"), str)
            and health["Status"] in {"healthy", "unhealthy", "starting"}
            and type(health.get("FailingStreak")) is int and 0 <= health["FailingStreak"] <= 2**31 - 1
            and isinstance(health.get("Log"), list), code)
    result = {"status": health["Status"], "failingStreak": health["FailingStreak"], "lastChecks": []}
    known = {"SHADOW_KERNEL_POLICY_COMMAND_FAILED", "SHADOW_KERNEL_POLICY_MISMATCH",
        "SHADOW_KERNEL_POLICY_COUNTER_MISSING", "SHADOW_GUARD_NOT_READY",
        "SHADOW_GUARD_CAPABILITIES_REMAIN", "SHADOW_IPV6_ENABLED", "SHADOW_PRIVILEGE_DROP_FAILED"}
    for row in health["Log"][-5:]:
        require(isinstance(row, dict) and type(row.get("ExitCode")) is int
                and -1 <= row["ExitCode"] <= 255 and isinstance(row.get("Output"), str)
                and len(row["Output"]) <= 8192, code)
        times = {}
        for key in ("Start", "End"):
            value = row.get(key)
            require(isinstance(value, str) and len(value) <= 40 and re.fullmatch(
                r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?(?:Z|[+-]\d{2}:\d{2})", value), code)
            try:
                datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                require(False, code)
            times[key.lower()] = value
        try:
            output = row["Output"].encode("utf-8")
        except UnicodeError:
            require(False, code)
        require(len(output) <= 8192, code)
        text, classification = row["Output"].strip(), "UNCLASSIFIED"
        last = text.splitlines()[-1] if text else ""
        if last.removeprefix("RuntimeError: ") in known:
            classification = last.removeprefix("RuntimeError: ")
        elif re.match(r"^Health check exceeded timeout \([0-9.]+[a-zµ]+\)", text):
            classification = "DOCKER_HEALTH_TIMEOUT"
        elif last.startswith("subprocess.TimeoutExpired: "):
            classification = "PROBE_SUBPROCESS_TIMEOUT"
        else:
            try:
                value = json.loads(text)
                if (isinstance(value, dict) and set(value) == {"policy", "blockedPackets"}
                        and value["policy"] == "VERIFIED" and type(value["blockedPackets"]) is int
                        and value["blockedPackets"] >= 0 and row["ExitCode"] == 0):
                    classification = "POLICY_VERIFIED"
            except (ValueError, TypeError):
                pass
        result["lastChecks"].append({**times, "exitCode": row["ExitCode"], "outputBytes": len(output),
            "outputSha256": hashlib.sha256(output).hexdigest(), "classification": classification})
    return result


def observe_guard_health(shadow, health):
    value = {"status": "INVALID", "errorCode": "SHADOW_GUARD_HEALTH_METADATA_INVALID"}
    try:
        value = guard_health(health)
    finally:
        recorder = vars(shadow).get("_guard_health_recorder")
        if callable(recorder):
            recorder(value)


def retained_runtime(shadow, containers, images):
    """Prove the unchanged guard/web boundary around a fixture-only API recycle."""
    require(shadow.fixture is True and len(containers) == 5, "SHADOW_RETAINED_STACK_INVALID")
    rows = {row["Config"]["Labels"].get("com.docker.compose.service"): row for row in containers}
    require(set(rows) == services(shadow) and len({row["Id"] for row in containers}) == 5,
            "SHADOW_RETAINED_STACK_INVALID")
    guard, result = rows["guard"], {}
    for name, row in rows.items():
        labels, host = row["Config"]["Labels"], row["HostConfig"]
        networks, bindings = row["NetworkSettings"]["Networks"], host.get("PortBindings") or {}
        require(labels.get("io.izo.owner") == "SHADOW-TOPOLOGY-01"
                and labels.get("com.docker.compose.project") == shadow.project
                and labels.get("com.docker.compose.oneoff", "").lower() == "false"
                and row["Image"] == images[name], "SHADOW_RETAINED_IDENTITY_INVALID")
        require(host.get("CapDrop") == ["ALL"] and not host.get("Privileged")
                and "no-new-privileges:true" in host.get("SecurityOpt", []), "SHADOW_RETAINED_PRIVILEGE_INVALID")
        require(all(mount.get("Type") in {"volume", "tmpfs"} for mount in row["Mounts"]),
                "SHADOW_RETAINED_HOST_MOUNT")
        if name == "guard":
            require(set(networks) == {shadow.project + "_shadow"}, "SHADOW_RETAINED_GUARD_NETWORK_INVALID")
            require(host.get("Dns") == ["127.0.0.1"], "SHADOW_RETAINED_GUARD_DNS_INVALID")
            require(guard_capabilities(host.get("CapAdd")), "SHADOW_RETAINED_GUARD_CAPABILITIES_INVALID")
            require(len(bindings) == 2 and all(port.get("HostIp") == "127.0.0.1"
                        for ports in bindings.values() for port in ports), "SHADOW_RETAINED_GUARD_PORTS_INVALID")
            observe_guard_health(shadow, row["State"].get("Health"))
            require(row["State"].get("Health", {}).get("Status") == "healthy", "SHADOW_RETAINED_GUARD_HEALTH_INVALID")
        else:
            require(host.get("NetworkMode") == "container:" + guard["Id"] and not networks and not bindings
                    and not host.get("CapAdd"), "SHADOW_RETAINED_NAMESPACE_INVALID")
        runtime_guard(shadow, row, name)
        if name in {"guard", "web"}:
            state = row["State"]
            require(row["Config"].get("User") == ("0:0" if name == "guard" else "101:101")
                    and host.get("ReadonlyRootfs") is True and not any(mount["Type"] == "volume" for mount in row["Mounts"]),
                    "SHADOW_RETAINED_CONFIG_INVALID")
            require(state["Running"] and type(state["Pid"]) is int and state["Pid"] > 0,
                    "SHADOW_RETAINED_PROCESS_STOPPED")
            result[name] = {"containerId": row["Id"], "imageId": row["Image"], "hostPid": state["Pid"],
                "startedAt": state["StartedAt"], "restartCount": row["RestartCount"], "ports": bindings,
                "networkMode": host["NetworkMode"], "networkIds": {key: value["NetworkID"] for key, value in networks.items()}}
    return result


IPC_PROBE = r'''
import json,os,stat
from pathlib import Path
directory=Path('/home/izo/worker'); socket=directory/'generation.sock'
d,s=directory.lstat(),socket.lstat()
print(json.dumps({'directory':{'uid':d.st_uid,'gid':d.st_gid,'mode':stat.S_IMODE(d.st_mode),
 'isDirectory':stat.S_ISDIR(d.st_mode)},'socket':{'uid':s.st_uid,'gid':s.st_gid,
 'mode':stat.S_IMODE(s.st_mode),'isSocket':stat.S_ISSOCK(s.st_mode)}}))
'''


def ipc_guard(shadow, backend_id):
    raw = shadow.docker("exec", backend_id, "python", "-c", IPC_PROBE, timeout=15)
    require(isinstance(raw, str) and len(raw) <= 1024, "SHADOW_ROLE_IPC_RECEIPT_INVALID")
    value = json.loads(raw)
    require(value == {"directory": {"uid": 10001, "gid": 10001, "mode": 0o700, "isDirectory": True},
                      "socket": {"uid": 10001, "gid": 10001, "mode": 0o600, "isSocket": True}},
            "SHADOW_ROLE_IPC_PERMISSIONS_INVALID")
    return value
