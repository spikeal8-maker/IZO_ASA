"""Bounded image-archive identity for the existing format-2 test installer."""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tarfile
import tempfile
from pathlib import Path

try:
    from tools.docker_test_bundle_format import (
        HASH, IMAGE, MAX_FILES, MAX_TOTAL, METADATA_LIMIT, REPOSITORY, RUNTIME, SHA, UVICORN,
        BundleError, file_hash, json_bytes, plain_path, require, safe_name,
        unique_object, validate_compose,
    )
except ModuleNotFoundError:
    from docker_test_bundle_format import (
        HASH, IMAGE, MAX_FILES, MAX_TOTAL, METADATA_LIMIT, REPOSITORY, RUNTIME, SHA, UVICORN,
        BundleError, file_hash, json_bytes, plain_path, require, safe_name,
        unique_object, validate_compose,
    )

ROLES = {"backend", "web", "guard"}
OCI = "application/vnd.oci.image."
MANIFEST_TYPES = {OCI + "manifest.v1+json", "application/vnd.docker.distribution.manifest.v2+json"}
CONFIG_TYPES = {OCI + "config.v1+json", "application/vnd.docker.container.image.v1+json"}
LAYER_TYPES = {OCI + "layer.v1.tar", OCI + "layer.v1.tar+gzip",
               "application/vnd.docker.image.rootfs.diff.tar.gzip"}


def _references(references: dict, source: str) -> None:
    require(isinstance(source, str) and SHA.fullmatch(source) is not None
            and isinstance(references, dict) and set(references) == ROLES,
            "IMAGE_REFERENCE_INVALID")
    require(all(isinstance(ref, str) and re.fullmatch(r"[a-z0-9]+(?:[._-][a-z0-9]+)*:" + source, ref)
                for ref in references.values()) and len(set(references.values())) == 3,
            "IMAGE_REFERENCE_INVALID")


def identity(manifest: dict) -> dict | None:
    if "image_identity" not in manifest:
        return None
    value = manifest["image_identity"]
    require(type(manifest.get("format")) is int and manifest["format"] == 2
            and manifest.get("profile") == RUNTIME and isinstance(value, dict)
            and set(value) == {"version", "roles"} and type(value["version"]) is int
            and value["version"] == 1 and isinstance(value["roles"], dict)
            and set(value["roles"]) == ROLES, "IMAGE_IDENTITY_SCHEMA_INVALID")
    roles = value["roles"]
    for role, item in roles.items():
        require(isinstance(item, dict) and set(item) == {"archive_ref", "config_digest", "manifest_digest"}
                and all(isinstance(item[k], str) and IMAGE.fullmatch(item[k])
                        for k in ("config_digest", "manifest_digest"))
                and item["config_digest"] == manifest["images"].get(role), "IMAGE_IDENTITY_SCHEMA_INVALID")
    require(all(len({item[k] for item in roles.values()}) == 3
                for k in ("config_digest", "manifest_digest")), "IMAGE_IDENTITY_SCHEMA_INVALID")
    _references({role: item["archive_ref"] for role, item in roles.items()}, manifest["source_sha"])
    return roles


class _HashReader:
    def __init__(self, stream):
        self.stream, self.digest, self.size = stream, hashlib.sha256(), 0

    def read(self, size):
        raw = self.stream.read(size)
        self.size += len(raw)
        require(self.size <= MAX_TOTAL, "IMAGE_ARCHIVE_TOO_LARGE")
        self.digest.update(raw)
        return raw


def _archive(path: Path, expected: dict | None) -> tuple[dict, dict]:
    path = plain_path(path)
    before = path.lstat()
    require(stat.S_ISREG(before.st_mode) and before.st_size <= MAX_TOTAL, "IMAGE_ARCHIVE_INVALID")
    metadata, sizes, seen, budget = {}, {}, set(), 0
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_NONBLOCK", 0)
    try:
        with os.fdopen(os.open(path, flags), "rb") as stream:
            opened = os.fstat(stream.fileno())
            require(stat.S_ISREG(opened.st_mode), "IMAGE_ARCHIVE_INVALID")
            reader = _HashReader(stream)
            with tarfile.open(fileobj=reader, mode="r|") as archive:
                for member in archive:
                    name = safe_name(member.name.rstrip("/") if member.isdir() else member.name)
                    require(name not in seen and len(seen) < MAX_FILES and not member.sparse,
                            "IMAGE_ARCHIVE_MEMBER_INVALID")
                    seen.add(name)
                    if member.isdir():
                        require(name in {"blobs", "blobs/sha256"}, "IMAGE_ARCHIVE_MEMBER_INVALID")
                        continue
                    blob = re.fullmatch(r"blobs/sha256/([0-9a-f]{64})", name)
                    require(member.isfile() and 0 <= member.size <= MAX_TOTAL
                            and (blob or name in {"index.json", "manifest.json", "oci-layout", "repositories"}),
                            "IMAGE_ARCHIVE_MEMBER_INVALID")
                    content = archive.extractfile(member)
                    require(content is not None, "IMAGE_ARCHIVE_INVALID")
                    digest, small = hashlib.sha256(), bytearray()
                    while chunk := content.read(1024**2):
                        digest.update(chunk)
                        if member.size <= METADATA_LIMIT:
                            small.extend(chunk)
                    require(not blob or digest.hexdigest() == blob[1], "IMAGE_BLOB_DIGEST_MISMATCH")
                    sizes[name] = member.size
                    if not blob or small.lstrip()[:1] in (b"{", b"["):
                        require(member.size <= METADATA_LIMIT, "IMAGE_METADATA_TOO_LARGE")
                        budget += len(small)
                        require(budget <= 16 * METADATA_LIMIT, "IMAGE_METADATA_TOO_LARGE")
                        metadata[name] = bytes(small)
            while reader.read(1024**2):
                pass
            final = os.fstat(stream.fileno())
        after = path.lstat()
        stamp = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns)
        require(stamp(before) == stamp(opened) == stamp(final) == stamp(after)
                and before.st_ctime_ns == after.st_ctime_ns and opened.st_ctime_ns == final.st_ctime_ns
                and reader.size == opened.st_size, "IMAGE_ARCHIVE_CHANGED")
        if expected is not None:
            require(expected == {"size": reader.size, "sha256": reader.digest.hexdigest()},
                    "IMAGE_ARCHIVE_HASH_MISMATCH")
    except (tarfile.TarError, OSError):
        raise BundleError("IMAGE_ARCHIVE_INVALID") from None
    return metadata, sizes


def _json(metadata: dict, name: str):
    require(name in metadata, "IMAGE_METADATA_MISSING")
    try:
        return json.loads(metadata[name], object_pairs_hook=unique_object)
    except (ValueError, UnicodeError):
        raise BundleError("IMAGE_METADATA_INVALID") from None


def _descriptor(item: dict, sizes: dict, types: set) -> str:
    require(isinstance(item, dict) and set(item) <= {"mediaType", "digest", "size", "annotations", "platform"}
            and isinstance(item.get("mediaType"), str) and item["mediaType"] in types and isinstance(item.get("digest"), str)
            and IMAGE.fullmatch(item["digest"]) is not None and type(item.get("size")) is int,
            "IMAGE_DESCRIPTOR_INVALID")
    name = "blobs/sha256/" + item["digest"][7:]
    require(name in sizes and sizes[name] == item["size"], "IMAGE_DESCRIPTOR_CONTENT_MISSING")
    if "platform" in item:
        require(item["platform"] == {"architecture": "amd64", "os": "linux"}, "IMAGE_PLATFORM_INVALID")
    return name


def archive_identity(path: Path, references: dict, source: str, *, expected: dict | None = None) -> dict:
    """Read both Docker/OCI views and bind every role to the same verified blobs."""
    _references(references, source)
    metadata, sizes = _archive(path, expected)
    require(_json(metadata, "oci-layout") == {"imageLayoutVersion": "1.0.0"}, "IMAGE_LAYOUT_INVALID")
    index, legacy = _json(metadata, "index.json"), _json(metadata, "manifest.json")
    require(isinstance(index, dict) and type(index.get("schemaVersion")) is int
            and index["schemaVersion"] == 2 and isinstance(index.get("manifests"), list)
            and len(index["manifests"]) == 3 and isinstance(legacy, list) and len(legacy) == 3,
            "IMAGE_ARCHIVE_ROLE_COUNT_INVALID")
    inverse, result, expected_legacy = {v: k for k, v in references.items()}, {}, {}
    for descriptor in index["manifests"]:
        name = _descriptor(descriptor, sizes, MANIFEST_TYPES)
        annotations = descriptor.get("annotations", {})
        require(isinstance(annotations, dict), "IMAGE_REFERENCE_INVALID")
        reference = annotations.get("io.containerd.image.name", "")
        require(isinstance(reference, str), "IMAGE_REFERENCE_INVALID")
        reference = reference.removeprefix("docker.io/library/")
        require(reference in inverse and isinstance(annotations.get("org.opencontainers.image.ref.name"), str)
                and annotations["org.opencontainers.image.ref.name"]
                in {source, reference, "docker.io/library/" + reference}, "IMAGE_REFERENCE_INVALID")
        role = inverse[reference]
        require(role not in result, "IMAGE_ARCHIVE_DUPLICATE_ROLE")
        image = _json(metadata, name)
        require(isinstance(image, dict) and type(image.get("schemaVersion")) is int
                and image["schemaVersion"] == 2 and image.get("mediaType") == descriptor["mediaType"]
                and isinstance(image.get("layers"), list) and 0 < len(image["layers"]) < MAX_FILES,
                "IMAGE_MANIFEST_INVALID")
        config_name = _descriptor(image.get("config"), sizes, CONFIG_TYPES)
        layer_names = [_descriptor(layer, sizes, LAYER_TYPES) for layer in image["layers"]]
        config = _json(metadata, config_name)
        require(isinstance(config, dict) and config.get("os") == "linux" and config.get("architecture") == "amd64"
                and isinstance(config.get("config"), dict), "IMAGE_PLATFORM_INVALID")
        settings, rootfs = config["config"], config.get("rootfs", {})
        labels = settings.get("Labels") or {}
        require(isinstance(labels, dict) and labels.get("org.opencontainers.image.source") == REPOSITORY
                and labels.get("org.opencontainers.image.revision") == source, "IMAGE_SOURCE_MISMATCH")
        require(isinstance(rootfs, dict) and rootfs.get("type") == "layers"
                and isinstance(rootfs.get("diff_ids"), list) and len(rootfs["diff_ids"]) == len(layer_names)
                and all(isinstance(d, str) and IMAGE.fullmatch(d) for d in rootfs["diff_ids"]),
                "IMAGE_ROOTFS_INVALID")
        for layer, diff in zip(image["layers"], rootfs["diff_ids"]):
            require(layer["mediaType"] != OCI + "layer.v1.tar" or layer["digest"] == diff,
                    "IMAGE_ROOTFS_INVALID")
        if role == "backend":
            require(settings.get("Cmd") == UVICORN and not settings.get("Entrypoint"), "RUNTIME_IMAGE_COMMAND_INVALID")
        result[role] = {"archive_ref": reference, "config_digest": image["config"]["digest"],
                        "manifest_digest": descriptor["digest"]}
        expected_legacy[reference] = (config_name, layer_names)
    actual_legacy = {}
    for row in legacy:
        require(isinstance(row, dict) and isinstance(row.get("RepoTags"), list)
                and len(row["RepoTags"]) == 1 and isinstance(row["RepoTags"][0], str), "IMAGE_LEGACY_VIEW_MISMATCH")
        reference = row["RepoTags"][0].removeprefix("docker.io/library/")
        require(reference not in actual_legacy, "IMAGE_LEGACY_VIEW_MISMATCH")
        actual_legacy[reference] = (row.get("Config"), row.get("Layers"))
    require(actual_legacy == expected_legacy and set(result) == ROLES, "IMAGE_LEGACY_VIEW_MISMATCH")
    return {"version": 1, "roles": result}


def verify_archive(root: Path, manifest: dict) -> None:
    roles = identity(manifest)
    if roles is None:
        return
    require(isinstance(manifest.get("files", {}).get("images.tar"), dict), "OFFLINE_IMAGES_MISSING")
    observed = archive_identity(root / "images.tar", {k: v["archive_ref"] for k, v in roles.items()},
                                manifest["source_sha"], expected=manifest["files"]["images.tar"])
    require(observed == manifest["image_identity"], "IMAGE_ARCHIVE_BINDING_MISMATCH")


def _inspect(docker, reference: str):
    raw = docker.run("image", "inspect", reference, optional=True)
    if raw is None:
        return None
    try:
        rows = json.loads(raw, object_pairs_hook=unique_object)
    except (ValueError, UnicodeError):
        raise BundleError("IMAGE_IDENTITY_INVALID") from None
    require(isinstance(rows, list) and len(rows) == 1 and isinstance(rows[0], dict), "IMAGE_IDENTITY_INVALID")
    return rows[0]


def _check(row: dict, role: str, manifest: dict, allowed: set, code="IMAGE_IDENTITY_INVALID") -> None:
    settings = row.get("Config") or {}
    require(isinstance(settings, dict), code)
    labels = settings.get("Labels") or {}
    require(isinstance(row.get("Id"), str) and row["Id"] in allowed and isinstance(labels, dict)
            and row.get("Os") == "linux" and row.get("Architecture") == "amd64"
            and labels.get("org.opencontainers.image.source") == manifest["repository"]
            and labels.get("org.opencontainers.image.revision") == manifest["source_sha"], code)
    descriptor = row.get("Descriptor")
    if descriptor is not None:
        require(isinstance(descriptor, dict) and descriptor.get("digest")
                == manifest["image_identity"]["roles"][role]["manifest_digest"], code)
    if role == "backend":
        require(settings.get("Cmd") == UVICORN and not settings.get("Entrypoint"), "RUNTIME_IMAGE_COMMAND_INVALID")


def resolve_images(docker, manifest: dict, *, missing_ok=False) -> dict:
    roles = identity(manifest)
    if roles is None:
        return dict(manifest["images"])
    result = {}
    for role, item in sorted(roles.items()):
        for candidate in (item["manifest_digest"], item["config_digest"]):
            row = _inspect(docker, candidate)
            if row is not None:
                _check(row, role, manifest, {candidate})
                result[role] = candidate
                break
        require(missing_ok or role in result, "OFFLINE_IMAGE_ID_NOT_FOUND")
    return result


def ensure_portable_images(docker, root: Path, manifest: dict) -> None:
    verify_archive(root, manifest)
    if set(resolve_images(docker, manifest, missing_ok=True)) != ROLES:
        with tempfile.TemporaryDirectory(prefix=".izo-image-load-", dir=root.parent) as temporary:
            private = Path(temporary)
            source = plain_path(root / "images.tar")
            flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
            flags |= getattr(os, "O_NONBLOCK", 0)
            with os.fdopen(os.open(source, flags), "rb") as incoming, (private / "images.tar").open("xb") as output:
                require(stat.S_ISREG(os.fstat(incoming.fileno()).st_mode), "IMAGE_ARCHIVE_INVALID")
                size = 0
                while chunk := incoming.read(1024**2):
                    size += len(chunk)
                    require(size <= manifest["files"]["images.tar"]["size"], "IMAGE_ARCHIVE_HASH_MISMATCH")
                    output.write(chunk)
            verify_archive(private, manifest)
            for role, item in identity(manifest).items():
                row = _inspect(docker, item["archive_ref"])
                if row is not None:
                    _check(row, role, manifest, {item["config_digest"], item["manifest_digest"]}, "IMAGE_TAG_CONFLICT")
            docker.run("load", "--input", str(private / "images.tar"), timeout=240)
    resolve_images(docker, manifest)


def runtime_compose(root: Path, manifest: dict, images: dict, *, create=False) -> Path:
    """Keep the sealed bundle immutable; a persistent sibling contains local IDs."""
    roles = identity(manifest)
    if roles is None:
        return root / "compose.json"
    root = plain_path(root)
    require(HASH.fullmatch(root.name) is not None and root.parent.name == "releases", "COMPOSE_PATH_NOT_PERSISTENT")
    require(set(images) == ROLES and all(images[role] in {item["config_digest"], item["manifest_digest"]}
                                        for role, item in roles.items()), "IMAGE_IDENTITY_INVALID")
    source = plain_path(root / "compose.json")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    with os.fdopen(os.open(source, flags), "rb") as stream:
        require(stat.S_ISREG(os.fstat(stream.fileno()).st_mode), "METADATA_NOT_REGULAR")
        raw = stream.read(METADATA_LIMIT + 1)
    require(len(raw) <= METADATA_LIMIT and manifest["files"].get("compose.json")
            == {"size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}, "PAYLOAD_HASH_MISMATCH")
    config = _json({"compose.json": raw}, "compose.json")
    validate_compose(config, manifest)
    for role, image in images.items():
        config["services"][role]["image"] = image
    validate_compose(config, {**manifest, "images": images})
    expected = json_bytes(config)
    target = plain_path(root.with_name(root.name + ".compose.json"))
    if not target.exists() and create:
        try:
            with target.open("xb") as stream:
                stream.write(expected)
                stream.flush()
                os.fsync(stream.fileno())
        except FileExistsError:
            pass
    require(target.is_file(), "RUNTIME_COMPOSE_MISSING")
    require(file_hash(target) == (len(expected), hashlib.sha256(expected).hexdigest()), "RUNTIME_COMPOSE_DRIFT")
    return target
