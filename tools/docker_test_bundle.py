"""Build/extract a synthetic Docker test ZIP; no production release authority."""
from __future__ import annotations

import argparse
import copy
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path

sys.dont_write_bytecode = True
try:
    from tools.docker_test_bundle_format import (
        BundleError, IMAGE, OWNER, PROJECT, REPOSITORY, SHA, extract, file_hash,
        inventory, json_bytes, plain_path, require, validate_compose, verify,
    )
    from tools.docker_test_bundle_runtime import Docker, SafeParser, clean_environment
except ModuleNotFoundError:
    from docker_test_bundle_format import (
        BundleError, IMAGE, OWNER, PROJECT, REPOSITORY, SHA, extract, file_hash,
        inventory, json_bytes, plain_path, require, validate_compose, verify,
    )
    from docker_test_bundle_runtime import Docker, SafeParser, clean_environment


def git(root: Path, *args: str) -> str:
    try:
        r = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=30, check=False,
                           env=clean_environment())
    except (OSError, subprocess.TimeoutExpired):
        raise BundleError("GIT_UNAVAILABLE_AT_BUILD") from None
    require(r.returncode == 0, "GIT_SOURCE_INVALID")
    return r.stdout.strip()


def source_guard(root: Path, sha: str) -> None:
    require(SHA.fullmatch(sha or "") is not None, "SOURCE_SHA_INVALID")
    require(re.search(r"[/:]spikeal8-maker/IZO_ASA(?:\.git)?$", git(root, "remote", "get-url", "origin"))
            is not None and git(root, "rev-parse", "HEAD") == sha
            and not git(root, "status", "--porcelain"), "CLEAN_EXACT_SOURCE_REQUIRED")


def persistent_config(config: dict, project: str, sha: str, release: str, images: dict) -> dict:
    effective = {"name", "services", "networks", "volumes"}
    require(not (set(config) - effective - {k for k in config if k.startswith("x-")}),
            "UNSUPPORTED_COMPOSE_SECTION")
    # Compose may retain x-* YAML extension templates after resolving anchors.
    # They are not runtime services and must not carry mutable tags into the ZIP.
    result = {key: copy.deepcopy(config[key]) for key in effective}
    for service, settings in result["services"].items():
        settings.pop("build", None)
        for default in ("entrypoint", "command"):
            if settings.get(default) is None:
                settings.pop(default, None)  # Explicit null means use the image default.
        settings["image"] = images[service]
        settings["pull_policy"] = "never"
        settings.setdefault("labels", {}).update({"io.izo.bundle": OWNER,
                                                   "org.opencontainers.image.revision": sha})
    for kind in ("volumes", "networks"):
        for name, settings in result[kind].items():
            if kind == "networks" and settings.get("ipam") == {}:
                settings.pop("ipam")  # Docker Compose emits an empty default IPAM object.
            settings["name"] = project + "_" + name
            settings.setdefault("labels", {})["io.izo.bundle"] = OWNER
    for role, target in (("backend", "/opt/izo/.runtime/releases/frontend/" + release),
                         ("web", "/usr/share/nginx/html")):
        result["services"][role].setdefault("volumes", []).append({
            "type": "bind", "source": "./frontend", "target": target,
            "read_only": True, "bind": {"create_host_path": False}})
    result["services"]["backend"]["environment"]["IZO_RELEASE_MANIFEST"] = (
        "/opt/izo/.runtime/releases/frontend/" + release + "/release-manifest.json")
    return result


def release_metadata(source: Path, assets: Path, sha: str, release: str, built: str,
                     python_version: str) -> dict:
    name = "_izo_test_bundle_identity"
    spec = importlib.util.spec_from_file_location(name, source / "backend/app/release_identity.py")
    require(spec is not None and spec.loader is not None, "RELEASE_IDENTITY_MODULE_MISSING")
    module = importlib.util.module_from_spec(spec)
    prior = sys.modules.get(name)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
        count, asset_hash = module.frontend_asset_manifest(assets)
        text = (source / "ops/docker/dev/Dockerfile.web").read_text(encoding="utf-8")
        node = re.search(r"^FROM node:([0-9]+\.[0-9]+\.[0-9]+)[-@]", text, re.MULTILINE)
        require(node is not None, "DECLARED_NODE_VERSION_MISSING")
        metadata = {"manifest_version": 1, "release_id": release, "git_sha": sha, "dirty": False,
                    "built_at": built, "frontend_asset_manifest_hash": asset_hash,
                    "frontend_asset_count": count, "python_version": python_version,
                    "node_version": node.group(1), "schema_compatibility": {"min_version": 7, "max_version": 7}}
        module.parse_release_manifest(metadata)
        return metadata
    finally:
        if prior is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = prior


def build(source: Path, sha: str, project: str, web: int, api: int, output: Path,
          docker: Docker, *, embed_images: bool = True) -> dict:
    source = plain_path(source)
    output = plain_path(output)
    tool_root = Path(__file__).resolve().parents[1]
    tooling_sha = git(tool_root, "rev-parse", "HEAD")
    source_guard(tool_root, tooling_sha)
    source_guard(source, sha)
    require(PROJECT.fullmatch(project or "") is not None and web != api
            and all(type(p) is int and 20000 <= p <= 65535 for p in (web, api)), "BUNDLE_PARAMETERS_INVALID")
    require(not output.exists() and not output.with_suffix(".receipt.json").exists(), "BUILD_OUTPUT_EXISTS")
    output.parent.mkdir(parents=True, exist_ok=True)
    require(shutil.disk_usage(output.parent).free >= 12 * 1024**3, "BUILD_DISK_RESERVE_REQUIRED")
    docker.engine()
    env = {**clean_environment(), "IZO_SOURCE_SHA": sha, "IZO_COMPOSE_PROJECT": project,
           "IZO_SHADOW_WEB_PORT": str(web), "IZO_SHADOW_API_PORT": str(api)}
    args = ["docker", "--context", docker.context, "compose", "--env-file", os.devnull,
            "--project-name", project]
    for name in ("compose.yml", "compose.shadow.yml", "compose.acceptance.yml"):
        args.extend(["-f", str(source / "ops/docker/dev" / name)])
    rendered = subprocess.run(args + ["config", "--format", "json"], env=env,
                              capture_output=True, text=True, encoding="utf-8", timeout=30)
    require(rendered.returncode == 0, "SOURCE_COMPOSE_RENDER_FAILED")
    config = json.loads(rendered.stdout)
    images = {}
    for role, settings in config["services"].items():
        image = json.loads(docker.run("image", "inspect", settings["image"]))[0]
        labels = image["Config"].get("Labels") or {}
        require(IMAGE.fullmatch(image["Id"]) is not None and image.get("Os") == "linux"
                and image.get("Architecture") == "amd64"
                and labels.get("org.opencontainers.image.revision") == sha
                and labels.get("org.opencontainers.image.source") == REPOSITORY,
                "SOURCE_IMAGE_MISMATCH")
        images[role] = image["Id"]
    now = datetime.now(timezone.utc)
    release = sha[:12] + "-" + now.strftime("%Y%m%d%H%M%S")
    manifest = {"format": 1, "kind": "isoas-test-bundle", "repository": REPOSITORY,
                "source_sha": sha, "tooling_sha": tooling_sha, "release_id": release,
                "project": project, "ports": {"web": web, "api": api}, "schema": 7,
                "images": images, "production_authorized": False, "model_execution": False}
    config = persistent_config(config, project, sha, release, images)
    validate_compose(config, manifest)
    with tempfile.TemporaryDirectory(prefix=".izo-pack-", dir=output.parent) as temporary:
        staging = Path(temporary) / "payload"
        staging.mkdir()
        (staging / "compose.json").write_bytes(json_bytes(config))
        export = docker.run("create", "--name", project + "-export-" + uuid.uuid4().hex[:8],
                            "--label", "io.izo.bundle=" + OWNER, "--network", "none", "--read-only",
                            "--entrypoint", "/bin/true", images["web"])
        try:
            docker.run("cp", export + ":/usr/share/nginx/html", str(staging / "frontend"), timeout=60)
        finally:
            item = json.loads(docker.run("inspect", export))[0]
            require(item["Config"]["Labels"].get("io.izo.bundle") == OWNER, "EXPORT_OWNER_MISMATCH")
            docker.run("rm", export)
        python_version = docker.run("run", "--rm", "--network", "none", "--read-only", "--user", "10001:10001",
                                    "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true",
                                    "--entrypoint", "python", images["backend"], "-c",
                                    "import platform; print(platform.python_version())")
        metadata = release_metadata(source, staging / "frontend", sha, release, now.isoformat(), python_version)
        (staging / "frontend/release-manifest.json").write_bytes(json_bytes(metadata))
        for name in ("docker_test_bundle_format.py", "docker_test_bundle_runtime.py"):
            shutil.copyfile(Path(__file__).parent / name, staging / name)
        (staging / "install.cmd").write_text('@echo off\r\npython -B "%~dp0docker_test_bundle_runtime.py" install %*\r\n', encoding="ascii")
        (staging / "install.sh").write_text('#!/bin/sh\nexec python3 -B "$(dirname "$0")/docker_test_bundle_runtime.py" install "$@"\n', encoding="ascii")
        if embed_images:
            docker.run("save", "--output", str(staging / "images.tar"), *sorted(set(images.values())), timeout=240)
        manifest["files"] = inventory(staging)
        (staging / "bundle.json").write_bytes(json_bytes(manifest))
        pin = file_hash(staging / "bundle.json")[1]
        verify(staging, pin)
        source_guard(source, sha)
        source_guard(tool_root, tooling_sha)
        staged_zip = Path(temporary) / "package.zip"
        with zipfile.ZipFile(staged_zip, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as z:
            for file in sorted(staging.rglob("*")):
                if file.is_file():
                    z.write(file, file.relative_to(staging).as_posix())
        size, digest = file_hash(staged_zip)
        staged_zip.rename(output)
    receipt = {"status": "TEST_BUNDLE_BUILT", "source_sha": sha, "tooling_sha": tooling_sha,
               "release_id": release, "project": project, "archive_sha256": digest, "archive_bytes": size,
               "manifest_sha256": pin, "images_embedded": embed_images, "production_authorized": False}
    output.with_suffix(".receipt.json").write_bytes(json_bytes(receipt))
    return receipt


def main(argv=None) -> int:
    try:
        p = SafeParser(description=__doc__)
        sub = p.add_subparsers(dest="action", required=True)
        b = sub.add_parser("build")
        b.add_argument("--source", type=Path, required=True)
        b.add_argument("--sha", required=True)
        b.add_argument("--project", required=True)
        b.add_argument("--web-port", type=int, required=True)
        b.add_argument("--api-port", type=int, required=True)
        b.add_argument("--context", required=True)
        b.add_argument("--output", type=Path, required=True)
        b.add_argument("--without-images", action="store_true")
        e = sub.add_parser("extract")
        e.add_argument("--archive", type=Path, required=True)
        e.add_argument("--sha256", required=True)
        e.add_argument("--destination", type=Path, required=True)
        a = p.parse_args(argv)
        if a.action == "build":
            result = build(a.source, a.sha, a.project, a.web_port, a.api_port, a.output,
                           Docker(a.context), embed_images=not a.without_images)
        else:
            extract(a.archive, a.sha256, a.destination)
            result = {"status": "ARCHIVE_EXTRACTED", "production_authorized": False}
        print(json.dumps(result, sort_keys=True))
        return 0
    except (BundleError, OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired) as error:
        code = str(error) if isinstance(error, BundleError) else "BUNDLE_BUILD_FAILED"
        print(json.dumps({"status": "BLOCKED", "reason": code, "production_authorized": False}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
