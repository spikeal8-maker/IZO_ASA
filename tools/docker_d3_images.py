"""Transfer only the three exact images from completed disposable D1/D2 installs.

The existing install result stays FAIL/PARTIAL when D3 is incomplete. This module
admits the individual D1/D2 evidence without changing that acceptance result.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tarfile

from tools.docker_clean_install import REPOSITORY, completed_extended
from tools.docker_shadow_product import require

MAX_ARCHIVE = 2 * 1024**3
RUNTIME_SOURCES = (
    "tools/docker_d3_chat_video.mjs", "tools/docker_d3_browser_contracts.mjs",
    "tools/docker_d3_browser_io.mjs", "tools/docker_d3_chat_video.py", "tools/docker_d3_process.py",
    "tools/docker_d3_phone_recovery.mjs", "tools/docker_d3_phone_watch.py",
    "tools/docker_d3_phone_ui.py", "tools/docker_d3_phone_ui.mjs", "frontend/phoneJobRecovery.ui.mjs",
)


def read_file(path, limit):
    path = Path(path)
    require(path.absolute() == path.resolve(), "D3_HANDOFF_SYMLINK_REJECTED")
    info = path.lstat()
    require(stat.S_ISREG(info.st_mode) and 0 <= info.st_size <= limit, "D3_HANDOFF_FILE_INVALID")
    with path.open("rb") as source:
        data = source.read(limit + 1)
    require(len(data) <= limit, "D3_HANDOFF_FILE_BOUND")
    return data


def read_json(path, limit=2 * 1024**2):
    return json.loads(read_file(path, limit))


def digest(path, limit=MAX_ARCHIVE):
    info = Path(path).lstat()
    require(stat.S_ISREG(info.st_mode) and 0 < info.st_size <= limit, "D3_HANDOFF_ARCHIVE_BOUND")
    hashed, count = hashlib.sha256(), 0
    with Path(path).open("rb") as source:
        while chunk := source.read(1024**2):
            count += len(chunk)
            require(count <= limit, "D3_HANDOFF_ARCHIVE_BOUND")
            hashed.update(chunk)
    require(count == info.st_size, "D3_HANDOFF_ARCHIVE_CHANGED")
    return {"sha256": hashed.hexdigest(), "bytes": count}


def runtime_sources(root):
    return {name: hashlib.sha256(read_file(Path(root) / name, 64 * 1024)).hexdigest()
            for name in RUNTIME_SOURCES}


def save_private(path, value):
    """Atomic checkpoints in an already caller-owned directory; no raw command output."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(path.name + ".tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(value, output, ensure_ascii=False, indent=2, allow_nan=False)
            output.write("\n")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def read_installations(directory, source_sha, base_sha, run_id, attempt, replica):
    summary = read_json(Path(directory) / "summary.json")
    require(summary.get("repository") == REPOSITORY and summary.get("sourceSha") == source_sha
            and summary.get("baseSha") == base_sha and summary.get("replica") == replica
            and type(summary.get("replica")) is int and type(summary.get("completedFixtureRuns")) is int
            and summary["completedFixtureRuns"] == 3 and summary.get("D1Status") == "PASS",
            "D3_HANDOFF_INSTALL_SUMMARY_INVALID")
    reports, proofs = [], []
    for number in (1, 2, 3):
        name = f"run-{number}/receipt.json"
        raw = read_file(Path(directory) / name, 2 * 1024**2)
        row = json.loads(raw)
        require(completed_extended(row) and row.get("sourceSha") == row.get("checkoutSha") == source_sha
                and row.get("D1Status") == "PASS" and all(row["checks"][f"D1-{n:02}"]["status"] == "PASS"
                    for n in range(1, 9)), "D3_HANDOFF_INSTALL_NOT_COMPLETE")
        host = row["host"]
        require(host == summary["host"] and host["runId"] == run_id and host["attempt"] == attempt
                and host["runnerEnvironment"] == "github-hosted", "D3_HANDOFF_INSTALL_RUN_CHANGED")
        for section, numbers in (("recovery", (1, 2, 3)), ("storage", (4, 5, 6))):
            result = row["extended"]["results"][section]
            require(result["status"] == "PASS" and all(result["checks"][f"D2-{n:02}"]["status"] == "PASS"
                    for n in numbers), "D3_HANDOFF_D2_NOT_ACCEPTED")
        require(row["resourcesBeforeRecreate"]["images"] == row["resourcesAfterRecreate"]["images"],
                "D3_HANDOFF_IMAGES_CHANGED")
        reports.append(row)
        proofs.append({"path": name, "sha256": hashlib.sha256(raw).hexdigest()})
    require(len({row["project"] for row in reports}) == 3 and all(
            row["resourcesAfterRecreate"]["images"] == reports[0]["resourcesAfterRecreate"]["images"]
            for row in reports), "D3_HANDOFF_FRESH_INSTALLS_REQUIRED")
    return reports, proofs


def references(source_sha, images):
    require(set(images) == {"guard", "web", "backend", "worker", "worker_peer"}
            and all(isinstance(value, str) and re.fullmatch(r"sha256:[a-f0-9]{64}", value)
                    for value in images.values())
            and images["backend"] == images["worker"] == images["worker_peer"], "D3_HANDOFF_IMAGE_IDS_INVALID")
    return {f"izo-asa-{name}:{source_sha}": images[service] for service, name in (
        ("guard", "shadow-guard"), ("web", "shadow-web"), ("backend", "dev-backend"))}


def archive_metadata(path, expected, source_sha):
    """Read headers/configs without extracting layers or allowing foreign image tags.

    Moby v28 exports a Docker manifest and an OCI index. Admit both representations
    against the same exact config digests; do not execute an archive-provided path.
    """
    with tarfile.open(path, mode="r:") as archive:
        members = {}
        for member in archive:
            name = member.name.rstrip("/")
            parts = PurePosixPath(name).parts
            require(0 < len(members) + 1 <= 512 and (member.isfile() or member.isdir()),
                    "D3_HANDOFF_TAR_TYPE_INVALID")
            require(name and not name.startswith("/") and ".." not in parts and "\\" not in name
                    and name not in members and member.size <= MAX_ARCHIVE, "D3_HANDOFF_TAR_PATH_INVALID")
            members[name] = member
        require(len(members) <= 512, "D3_HANDOFF_TAR_COUNT_INVALID")
        def raw(name, limit=256 * 1024):
            item = members.get(name)
            require(item is not None and item.isfile() and item.size <= limit, "D3_HANDOFF_TAR_METADATA_INVALID")
            with archive.extractfile(item) as source:
                return source.read(limit + 1)
        manifest = json.loads(raw("manifest.json"))
        require(isinstance(manifest, list) and len(manifest) == 3, "D3_HANDOFF_MANIFEST_INVALID")
        found, configs = {}, {}
        for entry in manifest:
            tags, layers = entry.get("RepoTags"), entry.get("Layers")
            require(isinstance(tags, list) and len(tags) == 1 and tags[0] in expected and tags[0] not in found
                    and isinstance(layers, list) and 0 < len(layers) <= 64 and len(set(layers)) == len(layers),
                    "D3_HANDOFF_FOREIGN_IMAGE_REJECTED")
            config_bytes = raw(entry["Config"])
            image_id = "sha256:" + hashlib.sha256(config_bytes).hexdigest()
            config = json.loads(config_bytes)
            labels = config.get("config", {}).get("Labels", {})
            require(image_id == expected[tags[0]] and config.get("os") == "linux"
                    and config.get("architecture") == "amd64"
                    and labels.get("org.opencontainers.image.revision") == source_sha
                    and labels.get("org.opencontainers.image.source") == REPOSITORY,
                    "D3_HANDOFF_CONFIG_DIGEST_OR_SOURCE_INVALID")
            require(all(name in members and members[name].isfile() for name in layers),
                    "D3_HANDOFF_LAYER_MISSING")
            found[tags[0]], configs[image_id] = image_id, set(layers)
        require(found == expected, "D3_HANDOFF_IMAGE_SET_CHANGED")
        if "index.json" in members:
            descriptors = json.loads(raw("index.json")).get("manifests")
            require(isinstance(descriptors, list) and len(descriptors) == 3, "D3_HANDOFF_OCI_INDEX_INVALID")
            seen = set()
            for item in descriptors:
                tag = item.get("annotations", {}).get("io.containerd.image.name", "")
                tag = tag.removeprefix("docker.io/library/")
                require(tag in expected and tag not in seen and re.fullmatch(
                        r"sha256:[a-f0-9]{64}", str(item.get("digest"))), "D3_HANDOFF_OCI_TAG_INVALID")
                blob = raw("blobs/sha256/" + item["digest"][7:])
                require(hashlib.sha256(blob).hexdigest() == item["digest"][7:], "D3_HANDOFF_OCI_DIGEST_INVALID")
                oci = json.loads(blob)
                require(oci.get("config", {}).get("digest") == expected[tag]
                        and isinstance(oci.get("layers"), list)
                        and all(not layer.get("urls") for layer in oci["layers"]), "D3_HANDOFF_OCI_CONFIG_INVALID")
                seen.add(tag)
        return {"status": "PASS", "images": found, "members": len(members), "extracted": False}


def image_inventory(shadow):
    raw = shadow.docker("image", "ls", "--no-trunc", "--format", "{{json .}}")
    require(isinstance(raw, str) and len(raw) <= 1024**2, "D3_HANDOFF_INVENTORY_BOUND")
    rows = raw.splitlines()
    require(len(rows) <= 512, "D3_HANDOFF_INVENTORY_BOUND")
    result = {}
    for line in rows:
        row = json.loads(line)
        require(re.fullmatch(r"sha256:[a-f0-9]{64}", str(row.get("ID"))), "D3_HANDOFF_INVENTORY_INVALID")
        image_ref = row["Repository"] + ":" + row["Tag"] if row["Repository"] != "<none>" else row["ID"]
        require(image_ref not in result, "D3_HANDOFF_INVENTORY_DUPLICATE")
        result[image_ref] = row["ID"]
    return result


def export_images(shadow, directory, reports, proofs, base_sha, *, wallclock):
    require(len(reports) == len(proofs) == 3, "D3_HANDOFF_THREE_INSTALLS_REQUIRED")
    selected = reports[-1]
    expected = selected["resourcesAfterRecreate"]["images"]
    tags = references(shadow.sha, expected)
    host = selected["host"]
    require(shadow.executor.engine_id == host["engineId"]
            and shadow.executor.machine_sha256 == host["machineIdentitySha256"], "D3_HANDOFF_EXPORT_HOST_CHANGED")
    directory, archive = Path(directory), Path(directory) / "images.partial.tar"
    require(not archive.exists(), "D3_HANDOFF_ARCHIVE_ALREADY_EXISTS")
    with wallclock(180):
        shadow.source_guard()
        require(shadow.image_guard(shadow.config()) == expected, "D3_HANDOFF_EXPORT_IMAGES_CHANGED")
        shadow.docker("image", "save", "--output", str(archive), *sorted(tags), timeout=120)
        archive.chmod(0o600)
        metadata = {**digest(archive), "name": "images.tar"}
        admitted = archive_metadata(archive, tags, shadow.sha)
        require(shadow.image_guard(shadow.config()) == expected, "D3_HANDOFF_EXPORT_IMAGES_CHANGED")
        shadow.source_guard()
        require(not (directory / "images.tar").exists(), "D3_HANDOFF_ARCHIVE_ALREADY_EXISTS")
        archive.replace(directory / "images.tar")
        value = {"version": 1, "status": "PASS", "evidenceClass": "EXACT_TESTED_IMAGE_TRANSFER",
            "repository": REPOSITORY, "sourceSha": shadow.sha, "baseSha": base_sha,
            "runId": host["runId"], "attempt": host["attempt"], "replica": 1,
            "selectedProject": selected["project"], "images": expected, "installReceipts": proofs,
            "archive": metadata, "archiveAdmission": admitted, "runtimeSources": runtime_sources(shadow.root)}
        save_private(directory / "handoff.json", value)
    return value


def load_images(shadow, directory, manifest, images, *, wallclock):
    tags = references(shadow.sha, images)
    with wallclock(180):
        shadow.source_guard()
        require(manifest.get("images") == images and manifest.get("runtimeSources") == runtime_sources(shadow.root),
                "D3_HANDOFF_SOURCE_FILES_CHANGED")
        metadata = manifest.get("archive", {})
        require(metadata.get("name") == "images.tar", "D3_HANDOFF_ARCHIVE_NAME_INVALID")
        archive = Path(directory) / "images.tar"
        require(digest(archive) == {key: metadata.get(key) for key in ("sha256", "bytes")},
                "D3_HANDOFF_ARCHIVE_DIGEST_INVALID")
        admitted = archive_metadata(archive, tags, shadow.sha)
        before = image_inventory(shadow)
        require(not (set(tags) & set(before)) and not (set(images.values()) & set(before.values())),
                "D3_HANDOFF_IMAGE_NAME_COLLISION")
        shadow.docker("image", "load", "--quiet", "--input", str(archive), timeout=120)
        after = image_inventory(shadow)
        require(all(after.get(key) == value for key, value in before.items())
                and {key: value for key, value in after.items() if key not in before} == tags,
                "D3_HANDOFF_FOREIGN_IMAGE_CHANGED")
        require(shadow.image_guard(shadow.config()) == images, "D3_HANDOFF_LOADED_IDS_CHANGED")
        shadow.source_guard()
        return {"status": "PASS", "archive": metadata, "archiveAdmission": admitted, "images": images,
                "foreignImagesUnchanged": True, "build": False, "pull": False,
                "imageCleanup": "DISPOSABLE_RUNNER_LIFECYCLE"}
