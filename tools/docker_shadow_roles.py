"""Exact split-role identities for the opt-in Docker acceptance profile."""
from __future__ import annotations

import json

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
