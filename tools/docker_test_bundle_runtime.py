"""Git-free installer for an explicitly authorized synthetic test bundle only."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, build_opener

sys.dont_write_bytecode = True
try:
    from tools.docker_test_bundle_format import (
        BundleError, OWNER, SERVICES, VOLUMES, json_bytes, load_json, plain_path, require, verify,
    )
except ModuleNotFoundError:
    from docker_test_bundle_format import (
        BundleError, OWNER, SERVICES, VOLUMES, json_bytes, load_json, plain_path, require, verify,
    )

HOST_KEYS = {"PATH", "SystemRoot", "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP",
             "USERPROFILE", "APPDATA", "LOCALAPPDATA", "HOME", "ProgramData", "ProgramFiles",
             "SystemDrive", "HOMEDRIVE", "HOMEPATH", "XDG_RUNTIME_DIR"}


def clean_environment() -> dict:
    # Windows os.environ normalizes keys to uppercase; SystemRoot must survive
    # the allowlist so child Python processes can initialize Winsock providers.
    if os.name == "nt":
        allowed = {key.upper() for key in HOST_KEYS}
        return {key: value for key, value in os.environ.items() if key.upper() in allowed}
    return {key: value for key, value in os.environ.items() if key in HOST_KEYS}


class Docker:
    def __init__(self, context: str):
        require(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", context) is not None,
                "CONTEXT_INVALID")
        self.context = context

    def run(self, *args: str, timeout: int = 30, optional: bool = False) -> str | None:
        try:
            result = subprocess.run(["docker", "--context", self.context, *args],
                                    env=clean_environment(), capture_output=True, text=True,
                                    encoding="utf-8", errors="replace", timeout=timeout, check=False)
        except (OSError, subprocess.TimeoutExpired):
            raise BundleError("DOCKER_OPERATION_UNAVAILABLE") from None
        if optional and result.returncode:
            return None
        require(result.returncode == 0, "DOCKER_OPERATION_FAILED")
        require(len(result.stdout) <= 4 * 1024**2, "DOCKER_RESPONSE_TOO_LARGE")
        return result.stdout.strip()

    def engine(self) -> str:
        info = json.loads(self.run("info", "--format", "{{json .}}"))
        require(info.get("OSType") == "linux" and info.get("ID"), "LINUX_ENGINE_REQUIRED")
        self.run("compose", "version", "--short")
        return hashlib.sha256(info["ID"].encode()).hexdigest()

    def compose(self, root: Path, m: dict, *args: str) -> str:
        return self.run("compose", "--env-file", os.devnull, "--project-name", m["project"],
                        "--project-directory", str(root), "-f", str(root / "compose.json"),
                        *args, timeout=240)


def owned_resources(docker: Docker, m: dict) -> dict:
    project = m["project"]
    rows = docker.run("ps", "-a", "--no-trunc", "--format", "{{.ID}}|{{.Names}}")
    marked = set(docker.run("ps", "-aq", "--no-trunc", "--filter",
                            "label=com.docker.compose.project=" + project).split())
    ids = set(marked)
    for line in rows.splitlines():
        identity, name = line.split("|", 1)
        if name == project or name.startswith((project + "-", project + "_")):
            ids.add(identity)
    containers = json.loads(docker.run("inspect", *sorted(ids))) if ids else []
    for item in containers:
        labels = item["Config"].get("Labels") or {}
        require(labels.get("io.izo.bundle") == OWNER
                and labels.get("com.docker.compose.project") == project
                and labels.get("com.docker.compose.service") in SERVICES, "FOREIGN_CONTAINER")
    resources = {"containers": containers}
    for kind, expected in (("volume", VOLUMES), ("network", {"shadow"})):
        all_names = set(docker.run(kind, "ls", "--format", "{{.Name}}").splitlines())
        wanted = {project + "_" + name for name in expected}
        marked_names = set(docker.run(kind, "ls", "--filter",
                                     "label=com.docker.compose.project=" + project,
                                     "--format", "{{.Name}}").splitlines())
        candidates = wanted.intersection(all_names) | marked_names
        require(candidates <= wanted, "UNEXPECTED_PROJECT_RESOURCE")
        observed = json.loads(docker.run(kind, "inspect", *sorted(candidates))) if candidates else []
        for item in observed:
            labels = item.get("Labels") or {}
            require(labels.get("io.izo.bundle") == OWNER
                    and labels.get("com.docker.compose.project") == project, "FOREIGN_RESOURCE")
        resources[kind + "s"] = observed
    return resources


def claim_volume(docker: Docker, name: str, labels: dict, code: str) -> None:
    # Engine serializes create by volume name; reuse preserves the first labels.
    docker.run("volume", "create", "--driver", "local",
               *[arg for key, value in labels.items() for arg in ("--label", key + "=" + value)], name)
    item = json.loads(docker.run("volume", "inspect", name))[0]
    require(item["Name"] == name and item["Driver"] == "local" and item["Scope"] == "local"
            and not item.get("Options") and item.get("Labels") == labels, code)


@contextmanager
def engine_lock(docker: Docker, owner: dict):
    name = owner["project"] + "-operation-lock"
    labels = {"io.izo.bundle": OWNER, "io.izo.bundle.nonce": uuid.uuid4().hex}
    require(docker.run("volume", "inspect", name, optional=True) is None, "INSTALLATION_BUSY")
    claim_volume(docker, name, labels, "INSTALLATION_BUSY")
    try:
        claim_volume(docker, owner["project"] + "-installation", {
            "io.izo.bundle": OWNER, "io.izo.bundle.installation": owner["id"],
            "io.izo.bundle.state": owner["state"], "io.izo.bundle.engine": owner["engine"],
        }, "INSTALLATION_OWNER_MISMATCH")
        yield
    finally:
        item = json.loads(docker.run("volume", "inspect", name))[0]
        require(item.get("Labels") == labels, "LOCK_OWNER_MISMATCH")
        docker.run("volume", "rm", name)


def volume_identity(resources: dict, m: dict, owner: dict) -> dict:
    rows = resources["volumes"]
    require({v["Name"] for v in rows} == {m["project"] + "_" + v for v in VOLUMES},
            "PERSISTENT_VOLUME_MISSING")
    result = {}
    for item in rows:
        labels = item.get("Labels") or {}
        generation = labels.get("io.izo.bundle.generation", "")
        require(labels.get("io.izo.bundle.installation") == owner["id"]
                and re.fullmatch(r"[0-9a-f]{32}", generation) is not None
                and item.get("Driver") == item.get("Scope") == "local"
                and isinstance(item.get("CreatedAt"), str) and item["CreatedAt"], "PERSISTENT_VOLUME_DRIFT")
        result[item["Name"]] = {"generation": generation, "created": item["CreatedAt"]}
    return result


def check_volumes(resources: dict, previous: dict | None, m: dict, owner: dict) -> None:
    if previous:
        require(volume_identity(resources, m, owner) == previous.get("volumes"), "PERSISTENT_VOLUME_DRIFT")
    else:
        require(not any(resources.values()), "UNRECEIPTED_EXISTING_RESOURCES")


def ensure_images(docker: Docker, root: Path, m: dict) -> None:
    missing = [image for image in set(m["images"].values())
               if docker.run("image", "inspect", image, optional=True) is None]
    if missing:
        require("images.tar" in m["files"], "OFFLINE_IMAGES_MISSING")
        docker.run("load", "--input", str(root / "images.tar"), timeout=240)
    for image in sorted(set(m["images"].values())):
        values = json.loads(docker.run("image", "inspect", image))
        require(len(values) == 1, "IMAGE_IDENTITY_INVALID")
        item = values[0]
        labels = item["Config"].get("Labels") or {}
        require(item["Id"] == image and item.get("Os") == "linux"
                and labels.get("org.opencontainers.image.revision") == m["source_sha"]
                and labels.get("org.opencontainers.image.source") == m["repository"],
                "IMAGE_IDENTITY_INVALID")


def health(docker: Docker, root: Path, m: dict) -> dict:
    current = owned_resources(docker, m)
    rows = current["containers"]
    require(len(rows) == len(SERVICES) and {x["Config"]["Labels"]["com.docker.compose.service"]
                                          for x in rows} == SERVICES, "SERVICE_COUNT_INVALID")
    for item in rows:
        role = item["Config"]["Labels"]["com.docker.compose.service"]
        require(item["State"]["Running"] and item["State"].get("Health", {}).get("Status") == "healthy"
                and item["Image"] == m["images"][role], "RUNTIME_NOT_READY")
        paths = item["Config"]["Labels"].get("com.docker.compose.project.config_files", "").split(",")
        require(len(paths) == 1 and Path(paths[0]).resolve() == (root / "compose.json").resolve()
                and Path(paths[0]).is_file(), "COMPOSE_PATH_NOT_PERSISTENT")
    opener = build_opener(ProxyHandler({}))
    origin = "http://127.0.0.1:" + str(m["ports"]["web"])
    with opener.open(origin + "/api/version", timeout=8) as response:
        require(response.geturl() == origin + "/api/version", "REDIRECT_FORBIDDEN")
        version = json.loads(response.read(65537))
    require(version.get("backend_commit") == m["source_sha"]
            and version.get("release_id") == m["release_id"]
            and version.get("frontend_build") == m["release_id"]
            and version.get("schema_compatibility") == {"min_version": 7, "max_version": 7},
            "RUNTIME_VERSION_MISMATCH")
    return {"status": "TEST_RUNTIME_VERIFIED", "source_sha": m["source_sha"],
            "release_id": m["release_id"], "containers": len(rows), "production_authorized": False}


def wait_health(docker: Docker, root: Path, manifest: dict, *, timeout: float = 20.0) -> dict:
    """Wait for transient startup readiness only; identity/ownership errors fail now."""
    deadline = time.monotonic() + timeout
    while True:
        try:
            return health(docker, root, manifest)
        except BundleError as error:
            if str(error) != "RUNTIME_NOT_READY":
                raise
        except HTTPError as error:
            status = error.code
            error.close()
            if status not in {502, 503, 504}:
                raise BundleError("HEALTH_HTTP_STATUS_INVALID") from None
        except URLError as error:
            if getattr(error.reason, "winerror", None) == 10106:
                raise BundleError("HEALTH_NETWORK_INITIALIZATION_FAILED") from None
        except (TimeoutError, ConnectionError):
            pass
        if time.monotonic() >= deadline:
            raise BundleError("TEST_READINESS_TIMEOUT")
        time.sleep(0.5)


def initialize_empty_test_database(docker: Docker, root: Path, manifest: dict) -> None:
    """Run canonical migrations only in a newly owned, empty synthetic database."""
    docker.compose(root, manifest, "up", "-d", "--wait", "--wait-timeout", "60",
                   "--no-build", "--pull", "never", "guard")
    code = """import os,sqlite3
from pathlib import Path
p=Path(os.environ['DATABASE_URL'])
assert os.environ['APP_ENV']=='test' and os.environ['ENV']=='test' and os.environ['MODE']=='test'
assert str(p)=='/home/izo/data/app.sqlite3'
if p.exists():
    c=sqlite3.connect('file:'+str(p)+'?mode=ro',uri=True)
    assert c.execute('PRAGMA user_version').fetchone()[0]==0
    assert c.execute(\"SELECT count(*) FROM sqlite_master WHERE type='table'\").fetchone()[0]==0
    c.close()
import main
main.db_guard_preflight()
main.init_db()
c=sqlite3.connect('file:'+str(p)+'?mode=ro',uri=True)
assert c.execute('PRAGMA user_version').fetchone()[0]==7
assert c.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
assert not c.execute('PRAGMA foreign_key_check').fetchone()
c.close()
print('FRESH_TEST_SCHEMA_7_VERIFIED')
"""
    output = docker.compose(root, manifest, "run", "--rm", "--no-deps", "-T", "--entrypoint",
                            "python", "backend", "-c", code)
    require(output.splitlines()[-1:] == ["FRESH_TEST_SCHEMA_7_VERIFIED"], "FRESH_SCHEMA_INITIALIZATION_FAILED")


def atomic_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(".writing")
    with temporary.open("xb") as stream:
        stream.write(json_bytes(value))
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def install(bundle: Path, pin: str, state: Path, docker: Docker, *, allow_update: bool = False) -> dict:
    m = verify(bundle, pin)
    bundle, state = plain_path(bundle), plain_path(state)
    require(state != bundle and not state.is_relative_to(bundle), "STATE_INSIDE_BUNDLE_FORBIDDEN")
    fingerprint = docker.engine()
    before = owned_resources(docker, m)
    state.mkdir(parents=True, exist_ok=True)
    lock = state / "operation.lock"
    require(not lock.exists(), "INSTALLATION_BUSY")
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise BundleError("INSTALLATION_BUSY") from None
    os.close(fd)
    try:
        expected = {"project": m["project"], "engine": fingerprint, "test_only": True,
                    "state": hashlib.sha256(os.path.normcase(str(state)).encode()).hexdigest()}
        if (state / "owner.json").exists():
            owner = load_json(state / "owner.json")
            require({k: v for k, v in owner.items() if k != "id"} == expected
                    and re.fullmatch(r"[0-9a-f]{32}", owner.get("id", "")) is not None,
                    "INSTALLATION_OWNER_MISMATCH")
        else:
            require(set(p.name for p in state.iterdir()) == {"operation.lock"}
                    and not any(before.values()), "INSTALLATION_NOT_FRESH")
            owner = {**expected, "id": uuid.uuid4().hex}
            atomic_json(state / "owner.json", owner)
        previous = load_json(state / "active.json") if (state / "active.json").is_file() else None
        check_volumes(before, previous, m, owner)
        with engine_lock(docker, owner):
            return install_locked(bundle, pin, state, docker, m, owner, previous, allow_update)
    finally:
        lock.unlink()


def install_locked(bundle: Path, pin: str, state: Path, docker: Docker, m: dict,
                   owner: dict, previous: dict | None, allow_update: bool) -> dict:
    before = owned_resources(docker, m)
    check_volumes(before, previous, m, owner)
    if previous:
        old_root = state / "releases" / previous["manifest_sha256"]
        old = verify(old_root, previous["manifest_sha256"])
        require(old["project"] == m["project"] and old["schema"] == m["schema"],
                "UPDATE_SCHEMA_UNSUPPORTED")
        changed = old["source_sha"] != m["source_sha"] or old["images"] != m["images"]
        require(not changed or allow_update, "TEST_CODE_UPDATE_NOT_AUTHORIZED")
        for item in before["containers"]:
            role = item["Config"]["Labels"]["com.docker.compose.service"]
            require(item["Image"] == old["images"][role], "ACTIVE_IMAGE_DRIFT")
        if changed:
            backend = [x for x in before["containers"]
                       if x["Config"]["Labels"]["com.docker.compose.service"] == "backend"]
            require(len(backend) == 1 and backend[0]["State"]["Running"],
                    "UPDATE_REQUIRES_RUNNING_PREVIOUS_TEST_RELEASE")
            code = ("import sqlite3,json; d=sqlite3.connect('file:/home/izo/data/app.sqlite3?mode=ro',uri=True); "
                    "print(json.dumps({'schema':d.execute('PRAGMA user_version').fetchone()[0],"
                    "'busy':d.execute(\"SELECT count(*) FROM jobs WHERE status NOT IN "
                    "('completed','failed','cancelled')\").fetchone()[0]}))")
            proof = json.loads(docker.run("exec", backend[0]["Id"], "python", "-c", code))
            require(proof == {"schema": 7, "busy": 0}, "UPDATE_TEST_DATA_NOT_QUIESCENT")
    releases = state / "releases"
    releases.mkdir(exist_ok=True)
    target = releases / pin
    if not target.exists():
        with tempfile.TemporaryDirectory(prefix=".prepare-", dir=releases) as tmp:
            staging = Path(tmp) / "bundle"
            shutil.copytree(bundle, staging, symlinks=True)
            verify(staging, pin)
            staging.rename(target)
    verify(target, pin)
    ensure_images(docker, target, m)
    check_volumes(owned_resources(docker, m), previous, m, owner)
    docker.compose(target, m, "config", "--quiet")
    stage = "fresh-schema" if previous is None else "compose-up"
    try:
        if previous is None:
            for volume in sorted(VOLUMES):
                claim_volume(docker, m["project"] + "_" + volume, {
                    "io.izo.bundle": OWNER, "com.docker.compose.project": m["project"],
                    "com.docker.compose.volume": volume, "io.izo.bundle.installation": owner["id"],
                    "io.izo.bundle.generation": uuid.uuid4().hex,
                }, "PERSISTENT_VOLUME_DRIFT")
        volumes = volume_identity(owned_resources(docker, m), m, owner)
        if previous is None:
            initialize_empty_test_database(docker, target, m)
        stage = "compose-up"
        docker.compose(target, m, "up", "-d", "--wait", "--wait-timeout", "180", "--no-build", "--pull", "never")
        stage = "readiness"
        result = wait_health(docker, target, m)
        require(volume_identity(owned_resources(docker, m), m, owner) == volumes,
                "PERSISTENT_VOLUME_DRIFT")
    except Exception as error:
        reason = str(error) if isinstance(error, BundleError) else type(error).__name__
        if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{1,100}", reason) is None:
            reason = "INSTALL_STAGE_FAILED"
        atomic_json(state / "last-failure.json", {"status": "FAILED_TEST_INSTALL", "candidate": pin,
                    "previous": previous, "stage": stage, "reason": reason,
                    "data_restored": False, "manual_recovery_required": True})
        raise BundleError("TEST_INSTALL_FAILED_MANUAL_RECOVERY_REQUIRED") from None
    receipt = {**result, "manifest_sha256": pin, "project": m["project"],
               "engine": owner["engine"], "volumes": volumes}
    atomic_json(state / "active.json", receipt)
    return receipt


class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        raise BundleError("ARGUMENTS_INVALID")


def main(argv=None) -> int:
    try:
        parser = SafeParser(description=__doc__)
        parser.add_argument("action", choices=("verify", "install"))
        parser.add_argument("--bundle", type=Path, default=Path(__file__).resolve().parent)
        parser.add_argument("--manifest-sha256", required=True)
        parser.add_argument("--context")
        parser.add_argument("--state-dir", type=Path)
        parser.add_argument("--test-only", action="store_true")
        parser.add_argument("--allow-code-update", action="store_true")
        a = parser.parse_args(argv)
        if a.action == "verify":
            m = verify(a.bundle, a.manifest_sha256)
            result = {"status": "BUNDLE_VERIFIED", "source_sha": m["source_sha"], "production_authorized": False}
        else:
            require(a.test_only and a.context and a.state_dir, "EXPLICIT_TEST_AUTHORIZATION_REQUIRED")
            result = install(a.bundle, a.manifest_sha256, a.state_dir, Docker(a.context),
                             allow_update=a.allow_code_update)
        print(json.dumps(result, sort_keys=True))
        return 0
    except (BundleError, OSError, ValueError, KeyError, TypeError) as error:
        code = str(error) if isinstance(error, BundleError) else "BUNDLE_OPERATION_FAILED"
        print(json.dumps({"status": "BLOCKED", "reason": code, "production_authorized": False}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
