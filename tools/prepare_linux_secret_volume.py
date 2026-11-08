"""Prepare only the owned private secret volume for the existing Linux test beta."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import uuid
from pathlib import Path

try:
    from tools.docker_test_bundle_format import BundleError, IMAGE, REPOSITORY, SHA, require
    from tools.docker_test_bundle_runtime import Docker
except ModuleNotFoundError:
    from docker_test_bundle_format import BundleError, IMAGE, REPOSITORY, SHA, require
    from docker_test_bundle_runtime import Docker


PROJECT = "izo-asa-linux-test-a"
VOLUME = PROJECT + "-secrets-v1"
LABELS = {"org.izo.project": PROJECT, "org.izo.purpose": "protected-secrets",
          "org.izo.owner-package": "LINUX-OPENROUTER-OPERABILITY-001", "org.izo.version": "1"}
NONCE_LABEL = "org.izo.initialization-nonce"
OPERATION = "linux-secret-volume-prepare-v1"

INITIALIZE = r'''
import json,os,stat
fd=os.open('/private',os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
try:
    item=os.fstat(fd)
    if item.st_uid!=0 or item.st_gid!=0 or stat.S_IMODE(item.st_mode)!=0o755:
        raise RuntimeError('New secret volume metadata is unsafe.')
    if os.listdir(fd):
        raise RuntimeError('New secret volume is not empty.')
    os.fchmod(fd,0o700)
    os.fchown(fd,10001,10001)
    os.fsync(fd)
finally:
    os.close(fd)
print(json.dumps({'initialized_empty':True}))
'''

VALIDATE = r'''
import json,os,stat
fd=os.open('/private',os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
try:
    item=os.fstat(fd)
    if os.getuid()!=10001 or item.st_uid!=10001 or item.st_gid!=10001 or stat.S_IMODE(item.st_mode)!=0o700:
        raise RuntimeError('Existing secret volume metadata is unsafe.')
    names=os.listdir(fd)
    for name in names:
        entry=os.stat(name,dir_fd=fd,follow_symlinks=False)
        if not stat.S_ISREG(entry.st_mode) or entry.st_nlink!=1:
            raise RuntimeError('Existing secret volume entry is unsafe.')
        if entry.st_uid!=10001 or entry.st_gid!=10001 or stat.S_IMODE(entry.st_mode)!=0o600:
            raise RuntimeError('Existing secret volume entry metadata is unsafe.')
    print(json.dumps({'uid':10001,'gid':10001,'mode':'0700','entry_count':len(names)}))
finally:
    os.close(fd)
'''


def _volume(docker: Docker) -> dict | None:
    raw = docker.run("volume", "inspect", VOLUME, optional=True)
    if raw is None:
        return None
    items = json.loads(raw)
    require(isinstance(items, list) and len(items) == 1, "SECRET_VOLUME_INSPECTION_INVALID")
    item = items[0]
    labels = item.get("Labels") or {}
    require(item.get("Name") == VOLUME and item.get("Driver") == "local"
            and item.get("Scope") == "local" and not item.get("Options")
            and all(labels.get(k) == v for k, v in LABELS.items())
            and set(labels) == set(LABELS) | {NONCE_LABEL}
            and re.fullmatch(r"[0-9a-f]{32}", labels[NONCE_LABEL] or "") is not None
            and isinstance(item.get("CreatedAt"), str) and item["CreatedAt"],
            "SECRET_VOLUME_IDENTITY_MISMATCH")
    return {key: item[key] for key in ("Name", "Driver", "Scope", "CreatedAt", "Labels")}


def _oneoff(docker: Docker, image: str, *, initialize: bool) -> dict:
    nonce = uuid.uuid4().hex
    name = "izo-secret-volume-" + nonce
    labels = {"org.izo.operation": OPERATION, "org.izo.operation-id": nonce}
    args = ["create", "--name", name, "--network", "none", "--read-only", "--restart", "no",
            "--user", "0:0" if initialize else "10001:10001", "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges:true", "--pids-limit", "32", "--memory", "64m",
            "--env", "PYTHONDONTWRITEBYTECODE=1"]
    if initialize:
        args += ["--cap-add", "CHOWN"]  # Only an absent, owned, still-empty volume reaches this branch.
    for key, value in labels.items():
        args += ["--label", key + "=" + value]
    args += ["--mount", "type=volume,source=" + VOLUME + ",target=/private,volume-nocopy"
             + ("" if initialize else ",readonly"), "--entrypoint", "python", image, "-I", "-B", "-c",
             INITIALIZE if initialize else VALIDATE]
    identity = docker.run(*args)
    try:
        require(re.fullmatch(r"[0-9a-f]{64}", identity or "") is not None, "SECRET_PROBE_ID_INVALID")
        result = json.loads(docker.run("start", "--attach", identity, timeout=45))
        state = json.loads(docker.run("inspect", identity))[0]
        require(state.get("State", {}).get("ExitCode") == 0, "SECRET_VOLUME_PROBE_FAILED")
        return result
    finally:
        state = json.loads(docker.run("inspect", identity))[0]
        require(all((state.get("Config", {}).get("Labels") or {}).get(k) == v
                    for k, v in labels.items()), "SECRET_PROBE_OWNERSHIP_MISMATCH")
        docker.run("rm", "--force", identity)


def prepare(docker: Docker, image: str, source: str, *, apply: bool = False) -> dict:
    require(sys.platform == "linux", "NATIVE_LINUX_REQUIRED")
    require(IMAGE.fullmatch(image or "") is not None and SHA.fullmatch(source or "") is not None,
            "EXACT_BACKEND_SOURCE_REQUIRED")
    engine = docker.engine()
    observed = json.loads(docker.run("image", "inspect", image))[0]
    config = observed.get("Config", {})
    require(observed.get("Id") == image and observed.get("Os") == "linux"
            and observed.get("Architecture") == "amd64" and config.get("User") == "10001:10001"
            and (config.get("Labels") or {}).get("org.opencontainers.image.revision") == source
            and (config.get("Labels") or {}).get("org.opencontainers.image.source") == REPOSITORY,
            "EXACT_BACKEND_SOURCE_REQUIRED")
    existing = _volume(docker)
    created = False
    if existing is None:
        if not apply:
            return {"status": "LINUX_SECRET_VOLUME_PLANNED", "volume": VOLUME,
                    "project": PROJECT, "create_required": True, "source_sha": source, "image": image}
        require(not docker.run("ps", "-aq", "--filter", "volume=" + VOLUME), "SECRET_VOLUME_IN_USE")
        nonce = uuid.uuid4().hex
        args = ["volume", "create", "--driver", "local"]
        for key, value in {**LABELS, NONCE_LABEL: nonce}.items():
            args += ["--label", key + "=" + value]
        require(docker.run(*args, VOLUME) == VOLUME, "SECRET_VOLUME_CREATE_FAILED")
        existing = _volume(docker)
        require(existing is not None and existing["Labels"][NONCE_LABEL] == nonce,
                "SECRET_VOLUME_CREATE_COLLISION")
        require(not docker.run("ps", "-aq", "--filter", "volume=" + VOLUME), "SECRET_VOLUME_IN_USE")
        require(_oneoff(docker, image, initialize=True) == {"initialized_empty": True},
                "SECRET_VOLUME_INIT_FAILED")
        created = True
    metadata = _oneoff(docker, image, initialize=False)
    require(set(metadata) == {"uid", "gid", "mode", "entry_count"}
            and metadata["uid"] == metadata["gid"] == 10001 and metadata["mode"] == "0700"
            and type(metadata["entry_count"]) is int and metadata["entry_count"] >= 0,
            "SECRET_VOLUME_METADATA_INVALID")
    require(not created or metadata["entry_count"] == 0, "NEW_SECRET_VOLUME_NOT_EMPTY")
    require(_volume(docker) == existing, "SECRET_VOLUME_IDENTITY_CHANGED")
    return {"status": "LINUX_SECRET_VOLUME_READY", "project": PROJECT, "volume": VOLUME,
            "created": created, "source_sha": source, "image": image, "engine": engine,
            "volume_identity": existing, "metadata": metadata, "existing_material_modified": False}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--context", required=True)
    parser.add_argument("--backend-image", required=True)
    parser.add_argument("--expect-source", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    try:
        require(not args.output.exists() and not args.output.is_symlink(), "RECEIPT_ALREADY_EXISTS")
        result = prepare(Docker(args.context), args.backend_image, args.expect_source, apply=args.apply)
        descriptor = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(json.dumps(result, sort_keys=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        parent = os.open(args.output.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(parent)
        finally:
            os.close(parent)
        print(json.dumps({"status": result["status"], "volume": VOLUME, "created": result.get("created", False)}))
        return 0
    except (BundleError, OSError, ValueError, KeyError, TypeError):
        print('{"status":"LINUX_SECRET_VOLUME_UNCONFIRMED"}')
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
