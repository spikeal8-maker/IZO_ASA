"""Integrity and policy for isolated TEST bundles; never a production trust root."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import shutil
import stat
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

OWNER = "DOCKER-TEST-BUNDLE-001"
REPOSITORY = "spikeal8-maker/IZO_ASA"
SHA = re.compile(r"[0-9a-f]{40}")
HASH = re.compile(r"[0-9a-f]{64}")
IMAGE = re.compile(r"sha256:[0-9a-f]{64}")
PROJECT = re.compile(r"izo-asa-bundle-[a-z0-9][a-z0-9-]{2,30}")
SERVICES = {"backend", "web", "guard", "worker", "worker_peer"}
VOLUMES = {"sqlite-data", "media-data", "worker_ipc"}
MAX_TOTAL = 8 * 1024**3
MAX_FILES = 6000
METADATA_LIMIT = 2 * 1024**2


class BundleError(RuntimeError):
    """Only fixed diagnostic codes; never subprocess output or file contents."""


def require(condition: bool, code: str) -> None:
    if not condition:
        raise BundleError(code)


def json_bytes(value: dict) -> bytes:
    return (json.dumps(value, sort_keys=True, ensure_ascii=True, indent=2) + "\n").encode()


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def load_json(path: Path) -> dict:
    require(path.is_file() and not path.is_symlink(), "METADATA_NOT_REGULAR")
    with path.open("rb") as stream:
        raw = stream.read(METADATA_LIMIT + 1)
    require(len(raw) <= METADATA_LIMIT, "METADATA_TOO_LARGE")
    try:
        value = json.loads(raw, object_pairs_hook=unique_object)
    except (ValueError, UnicodeError):
        raise BundleError("METADATA_INVALID_JSON") from None
    require(isinstance(value, dict), "METADATA_NOT_OBJECT")
    return value


def safe_name(name: str) -> str:
    require(isinstance(name, str) and 0 < len(name) <= 240, "UNSAFE_MEMBER_NAME")
    parts = name.split("/")
    reserved = {"CON", "PRN", "AUX", "NUL", *[f"COM{i}" for i in range(10)],
                *[f"LPT{i}" for i in range(10)]}
    require(not any(c in name for c in "\\:$\x00") and not any(ord(c) < 32 for c in name),
            "UNSAFE_MEMBER_NAME")
    require(not PurePosixPath(name).is_absolute() and all(
        p not in {"", ".", ".."} and p == p.rstrip(". ")
        and p.split(".")[0].upper() not in reserved for p in parts), "UNSAFE_MEMBER_NAME")
    return name


def plain_path(path: Path) -> Path:
    require(not any(p.is_symlink() or (hasattr(p, "is_junction") and p.is_junction())
                    for p in (path, *path.parents)), "SYMLINK_PATH_FORBIDDEN")
    require("$" not in str(path), "INTERPOLATED_PATH_FORBIDDEN")
    return path.absolute()


def file_hash(path: Path, limit: int = MAX_TOTAL) -> tuple[int, str]:
    path = plain_path(path)
    first = path.lstat()
    require(stat.S_ISREG(first.st_mode) and first.st_size <= limit, "FILE_TYPE_OR_SIZE_INVALID")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_NONBLOCK", 0)
    with os.fdopen(os.open(path, flags), "rb") as stream:
        opened = os.fstat(stream.fileno())
        require(stat.S_ISREG(opened.st_mode), "FILE_TYPE_OR_SIZE_INVALID")
        digest, count = hashlib.sha256(), 0
        while chunk := stream.read(min(1024**2, limit - count + 1)):
            count += len(chunk)
            require(count <= limit, "FILE_TOO_LARGE")
            digest.update(chunk)
        final = os.fstat(stream.fileno())
    last = path.lstat()
    identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns)
    require(identity(first) == identity(opened) == identity(final) == identity(last)
            and first.st_ctime_ns == last.st_ctime_ns and opened.st_ctime_ns == final.st_ctime_ns
            and count == opened.st_size, "FILE_CHANGED_DURING_READ")
    return count, digest.hexdigest()


def inventory(root: Path) -> dict:
    result, folded, total = {}, set(), 0
    for path in sorted(root.rglob("*")):
        plain_path(path)
        if path.is_dir():
            continue
        name = safe_name(path.relative_to(root).as_posix())
        require(name.casefold() not in folded, "CASE_COLLISION")
        folded.add(name.casefold())
        if name == "bundle.json":
            continue
        size, digest = file_hash(path)
        total += size
        require(len(result) < MAX_FILES and total <= MAX_TOTAL, "BUNDLE_LIMIT_EXCEEDED")
        result[name] = {"size": size, "sha256": digest}
    return result


def validate_compose(config: dict, manifest: dict) -> None:
    project, release = manifest["project"], manifest["release_id"]
    require(set(config) == {"name", "services", "volumes", "networks"}
            and config["name"] == project and set(config["services"]) == SERVICES
            and set(config["volumes"]) == VOLUMES and set(config["networks"]) == {"shadow"},
            "COMPOSE_SHAPE_INVALID")
    for kind in ("volumes", "networks"):
        for name, settings in config[kind].items():
            require(set(settings) <= {"name", "labels", "driver", "internal"}
                    and settings["name"] == project + "_" + name
                    and settings["labels"].get("io.izo.bundle") == OWNER
                    and settings.get("driver", "local" if kind == "volumes" else "bridge")
                    == ("local" if kind == "volumes" else "bridge"), "RESOURCE_POLICY_INVALID")
    forbidden = {"build", "env_file", "extends", "devices", "volumes_from", "container_name",
                 "pid", "ipc", "uts", "privileged", "post_start", "pre_stop", "develop", "entrypoint"}
    for name, service in config["services"].items():
        require(not forbidden.intersection(service) and service["image"] == manifest["images"][name]
                and service.get("pull_policy") == "never"
                and service["labels"].get("io.izo.bundle") == OWNER
                and service["labels"].get("org.opencontainers.image.revision") == manifest["source_sha"]
                and service.get("cap_drop") == ["ALL"]
                and "no-new-privileges:true" in service.get("security_opt", []), "SERVICE_POLICY_INVALID")
        if name in {"guard", "web"}:
            require("command" not in service, "ENTRY_COMMAND_FORBIDDEN")
        if name in {"worker", "worker_peer"}:
            require(service.get("command") == ["python", "-m", "app.generation_worker"],
                    "WORKER_COMMAND_INVALID")
        if name == "guard":
            require(set(service.get("networks", {})) == {"shadow"}
                    and not service.get("network_mode") and service.get("dns") == ["127.0.0.1"]
                    and set(service.get("cap_add", [])) == {"NET_ADMIN", "SETUID", "SETGID"},
                    "GUARD_POLICY_INVALID")
            observed = {(p.get("host_ip"), int(p["published"]), int(p["target"]))
                        for p in service.get("ports", [])}
            require(observed == {("127.0.0.1", manifest["ports"]["web"], 8080),
                                  ("127.0.0.1", manifest["ports"]["api"], 8000)}, "PORT_POLICY_INVALID")
        else:
            require(service.get("network_mode") == "service:guard" and not service.get("networks")
                    and not service.get("ports") and not service.get("cap_add")
                    and service.get("user") in {"10001:10001", "101:101"}, "APP_POLICY_INVALID")
        for mount in service.get("volumes", []):
            if mount["type"] == "bind":
                target = "/usr/share/nginx/html" if name == "web" else (
                    "/opt/izo/.runtime/releases/frontend/" + release)
                require(name in {"web", "backend"} and mount["source"] == "./frontend"
                        and mount["target"] == target and mount.get("read_only") is True
                        and mount.get("bind", {}).get("create_host_path") is False, "BIND_POLICY_INVALID")
            else:
                require(mount["type"] == "volume" and mount["source"] in VOLUMES,
                        "MOUNT_POLICY_INVALID")
    backend = config["services"]["backend"]
    env = backend["environment"]
    require(backend["command"] == ["python", "/opt/izo/fixtures/docker_shadow_fixture.py"]
            and all(env.get(k) == "test" for k in ("APP_ENV", "ENV", "MODE"))
            and env.get("IZO_SHADOW_FIXTURE") == "controlled-comfyui-v1"
            and env.get("COMFYUI_BASE_URL") == "http://127.0.0.1:48991"
            and env.get("BOT_MODE") == env.get("MAX_UPDATES_MODE") == "disabled",
            "TEST_PROFILE_REQUIRED")
    for key, value in env.items():
        if re.search(r"(?:SECRET|PASSWORD|TOKEN|API_KEY|ADMIN_ONE_TIME_CODE)$", key):
            require(value == "", "NONEMPTY_CREDENTIAL_FORBIDDEN")
        if key.endswith("BASE_URL") and key != "COMFYUI_BASE_URL":
            require(value == "http://127.0.0.1:1", "LIVE_PROVIDER_FORBIDDEN")


def verify(root: Path, pin: str) -> dict:
    require(HASH.fullmatch(pin or "") is not None, "MANIFEST_PIN_REQUIRED")
    root = plain_path(root)
    path = root / "bundle.json"
    plain_path(path)
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    with os.fdopen(os.open(path, flags | getattr(os, "O_NONBLOCK", 0)), "rb") as stream:
        require(stat.S_ISREG(os.fstat(stream.fileno()).st_mode), "METADATA_NOT_REGULAR")
        raw = stream.read(METADATA_LIMIT + 1)
    require(len(raw) <= METADATA_LIMIT, "METADATA_TOO_LARGE")
    require(hmac.compare_digest(hashlib.sha256(raw).hexdigest(), pin), "MANIFEST_PIN_MISMATCH")
    try:
        m = json.loads(raw, object_pairs_hook=unique_object)
    except (ValueError, UnicodeError):
        raise BundleError("METADATA_INVALID_JSON") from None
    require(isinstance(m, dict), "METADATA_NOT_OBJECT")
    require(m.get("format") == 1 and m.get("kind") == "isoas-test-bundle"
            and m.get("repository") == REPOSITORY and m.get("production_authorized") is False
            and m.get("model_execution") is False and m.get("schema") == 7,
            "TEST_MANIFEST_INVALID")
    require(SHA.fullmatch(m.get("source_sha", "")) is not None
            and SHA.fullmatch(m.get("tooling_sha", "")) is not None
            and PROJECT.fullmatch(m.get("project", "")) is not None, "BUNDLE_IDENTITY_INVALID")
    require(re.fullmatch(m["source_sha"][:12] + r"-[0-9]{14}", m.get("release_id", "")) is not None,
            "RELEASE_ID_INVALID")
    require(set(m.get("ports", {})) == {"api", "web"}
            and all(type(p) is int and 20000 <= p <= 65535 for p in m["ports"].values())
            and m["ports"]["api"] != m["ports"]["web"], "PORT_POLICY_INVALID")
    require(set(m.get("images", {})) == SERVICES
            and all(IMAGE.fullmatch(v) for v in m["images"].values()), "IMAGE_ID_INVALID")
    require(isinstance(m.get("files"), dict) and len(m["files"]) <= MAX_FILES,
            "INVENTORY_INVALID")
    require(inventory(root) == m["files"], "PAYLOAD_HASH_MISMATCH")
    validate_compose(load_json(root / "compose.json"), m)
    return m


def extract(archive: Path, digest: str, destination: Path) -> None:
    require(HASH.fullmatch(digest or "") is not None, "ARCHIVE_PIN_REQUIRED")
    archive, destination = plain_path(archive), plain_path(destination)
    require(not destination.exists(), "EXTRACTION_DESTINATION_EXISTS")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".izo-extract-", dir=destination.parent) as temporary:
        # Authenticate the bytes of a private snapshot, never reopen an unpinned ZIP.
        pinned = Path(temporary) / "pinned.zip"
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        with os.fdopen(os.open(archive, flags | getattr(os, "O_NONBLOCK", 0)), "rb") as reader:
            require(stat.S_ISREG(os.fstat(reader.fileno()).st_mode), "ARCHIVE_NOT_REGULAR")
            hashed, count = hashlib.sha256(), 0
            with pinned.open("xb") as writer:
                while chunk := reader.read(1024**2):
                    count += len(chunk)
                    require(count <= MAX_TOTAL, "ARCHIVE_LIMIT_EXCEEDED")
                    hashed.update(chunk)
                    writer.write(chunk)
        require(hmac.compare_digest(hashed.hexdigest(), digest), "ARCHIVE_PIN_MISMATCH")
        with zipfile.ZipFile(pinned) as z:
            infos = z.infolist()
            require(0 < len(infos) <= MAX_FILES and sum(i.file_size for i in infos) <= MAX_TOTAL,
                    "ARCHIVE_LIMIT_EXCEEDED")
            names = [safe_name(i.filename) for i in infos]
            require(len({n.casefold() for n in names}) == len(names), "ARCHIVE_DUPLICATE_MEMBER")
            require(all(not i.is_dir() and stat.S_IFMT(i.external_attr >> 16) in {0, stat.S_IFREG}
                        and not i.flag_bits & 1 for i in infos), "ARCHIVE_SPECIAL_MEMBER")
            target = Path(temporary) / "payload"
            target.mkdir()
            for info, name in zip(infos, names):
                path = target / name
                path.parent.mkdir(parents=True, exist_ok=True)
                with z.open(info) as reader, path.open("xb") as writer:
                    shutil.copyfileobj(reader, writer, 1024**2)
                require(path.stat().st_size == info.file_size, "ARCHIVE_SIZE_MISMATCH")
            target.rename(destination)
