"""Portable image identity regressions; synthetic archives and engine responses only."""
from __future__ import annotations

import copy
import hashlib
import io
import json
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest

from tools import docker_test_bundle_runtime as runtime
from tools.docker_test_bundle_format import BundleError, REPOSITORY, UVICORN, json_bytes, verify
from tools.test_docker_synthetic_runtime import make_runtime, repin

OCI = "application/vnd.oci.image."


def digest(raw):
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def tar_bytes(files):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w") as archive:
        for name, raw in files.items():
            member = tarfile.TarInfo(name)
            member.size, member.mtime, member.mode = len(raw), 0, 0o644
            archive.addfile(member, io.BytesIO(raw))
    return output.getvalue()


def make_portable(root):
    root, _, manifest = make_runtime(root)
    blobs, index, legacy, roles, inspections = {}, [], [], {}, {}
    names = {"backend": "izo-asa-dev", "web": "izo-asa-shadow-web", "guard": "izo-asa-shadow-guard"}
    for role in sorted(names):
        reference = names[role] + ":" + manifest["source_sha"]
        layer = tar_bytes({"synthetic-" + role + ".txt": ("owned test " + role).encode()})
        layer_digest = digest(layer)
        config = {"architecture": "amd64", "os": "linux", "config": {
            "Labels": {"org.opencontainers.image.source": REPOSITORY,
                       "org.opencontainers.image.revision": manifest["source_sha"]},
            "Cmd": UVICORN if role == "backend" else ["synthetic-" + role]},
            "rootfs": {"type": "layers", "diff_ids": [layer_digest]}}
        if role == "web": config["config"]["Labels"]["org.opencontainers.image.version"] = manifest["release_id"]
        config_raw = json_bytes(config)
        config_digest = digest(config_raw)
        image = {"schemaVersion": 2, "mediaType": OCI + "manifest.v1+json",
            "config": {"mediaType": OCI + "config.v1+json", "digest": config_digest,
                       "size": len(config_raw)},
            "layers": [{"mediaType": OCI + "layer.v1.tar", "digest": layer_digest,
                        "size": len(layer)}]}
        image_raw = json_bytes(image)
        image_digest = digest(image_raw)
        for sha, raw in ((layer_digest, layer), (config_digest, config_raw), (image_digest, image_raw)):
            blobs["blobs/sha256/" + sha[7:]] = raw
        index.append({"mediaType": OCI + "manifest.v1+json", "digest": image_digest,
            "size": len(image_raw), "annotations": {
                "io.containerd.image.name": "docker.io/library/" + reference,
                "org.opencontainers.image.ref.name": manifest["source_sha"]}})
        legacy.append({"Config": "blobs/sha256/" + config_digest[7:], "RepoTags": [reference],
                       "Layers": ["blobs/sha256/" + layer_digest[7:]]})
        roles[role] = {"archive_ref": reference, "config_digest": config_digest,
                       "manifest_digest": image_digest}
        inspections[role] = {"Id": image_digest, "Os": "linux", "Architecture": "amd64",
                            "Config": config["config"], "RootFS": {"Type": "layers", "Layers": [layer_digest]},
                            "Descriptor": {"digest": image_digest, "mediaType": image["mediaType"],
                                           "size": len(image_raw)}}
    blobs.update({"index.json": json_bytes({"schemaVersion": 2, "manifests": index}),
                  "manifest.json": json_bytes(legacy),
                  "oci-layout": json_bytes({"imageLayoutVersion": "1.0.0"})})
    (root / "images.tar").write_bytes(tar_bytes(blobs))
    manifest["images"] = {role: value["config_digest"] for role, value in roles.items()}
    manifest["image_identity"] = {"version": 1, "roles": roles}
    compose = json.loads((root / "compose.json").read_text(encoding="utf-8"))
    for role, value in manifest["images"].items():
        compose["services"][role]["image"] = value
    return root, repin(root, manifest, compose), manifest, inspections, blobs


class ImageEngine:
    """Observed containerd behavior: inspect accepts manifest IDs, not config IDs."""
    def __init__(self, manifest, inspections, *, loaded=False, classic=False):
        self.rows = copy.deepcopy(inspections)
        if classic:
            for role, row in self.rows.items():
                row["Id"] = manifest["images"][role]
                row.pop("Descriptor")
        self.loaded, self.calls, self.successful_inspects, self.tags = loaded, [], [], {}

    def run(self, *args, optional=False, **kwargs):
        self.calls.append(args)
        if args[:2] == ("load", "--input"):
            assert Path(args[2]).is_file()
            self.loaded = True
            return "Loaded synthetic backend, web and guard"
        if args[:2] == ("image", "inspect"):
            rows = [row for row in self.rows.values() if self.loaded and row["Id"] == args[2]]
            if args[2] in self.tags:
                rows = [self.tags[args[2]]]
            if rows:
                self.successful_inspects.append(args[2])
                return json.dumps(rows)
            if optional:
                return None
            raise BundleError("DOCKER_OPERATION_FAILED")
        if args[0] == "compose":
            return ""
        raise AssertionError("Unexpected synthetic engine operation: " + repr(args))


def test_named_format2_archive_resolves_containerd_manifest_ids(tmp_path):
    root, pin, manifest, inspections, _ = make_portable(tmp_path / "bundle")
    before = {p.name: p.read_bytes() for p in root.iterdir() if p.is_file()}
    # The real current verifier reads the complete synthetic bundle, not a mocked path.
    assert verify(root, pin) == manifest
    engine = ImageEngine(manifest, inspections)
    assert runtime.ensure_images(engine, root, manifest) is None
    assert {row["Id"] for row in inspections.values()} <= set(engine.successful_inspects)
    assert sum(call[0] == "load" for call in engine.calls) == 1
    assert before == {p.name: p.read_bytes() for p in root.iterdir() if p.is_file()}


@pytest.mark.parametrize("classic", [False, True])
def test_existing_exact_images_do_not_load_or_retag(tmp_path, classic):
    root, _, manifest, inspections, _ = make_portable(tmp_path / "bundle")
    engine = ImageEngine(manifest, inspections, loaded=True, classic=classic)
    assert runtime.ensure_images(engine, root, manifest) is None
    assert all(call[:2] == ("image", "inspect") for call in engine.calls)
    assert set(manifest["images"]) == {"backend", "web", "guard"}


@pytest.mark.parametrize("change", ["index-missing", "index-duplicate", "blob-missing", "blob-corrupt",
                                    "descriptor-size", "legacy-config", "legacy-tag", "legacy-extra", "binding"])
def test_incomplete_conflicting_or_corrupt_archive_refused_before_load(tmp_path, change):
    root, _, manifest, inspections, blobs = make_portable(tmp_path / "bundle")
    index, legacy = json.loads(blobs["index.json"]), json.loads(blobs["manifest.json"])
    if change == "index-missing": index["manifests"] = index["manifests"][:1]
    elif change == "index-duplicate": index["manifests"][1] = index["manifests"][0]
    elif change == "blob-missing": del blobs[legacy[0]["Config"]]
    elif change == "blob-corrupt": blobs[legacy[0]["Config"]] += b" "
    elif change == "descriptor-size": index["manifests"][0]["size"] += 1
    elif change == "legacy-config": legacy[0]["Config"] = legacy[1]["Config"]
    elif change == "legacy-tag": legacy[0]["RepoTags"].append("unrelated:latest")
    elif change == "legacy-extra": legacy.append(copy.deepcopy(legacy[0]))
    elif change == "binding": manifest["image_identity"]["roles"]["web"]["manifest_digest"] = "sha256:" + "f" * 64
    blobs.update({"index.json": json_bytes(index), "manifest.json": json_bytes(legacy)})
    (root / "images.tar").write_bytes(tar_bytes(blobs))
    repin(root, manifest)
    engine = ImageEngine(manifest, inspections)
    with pytest.raises(BundleError):
        runtime.ensure_images(engine, root, manifest)
    assert engine.calls == []


@pytest.mark.parametrize("kind", ["duplicate", "parent", "symlink", "directory", "metadata-limit"])
def test_archive_member_guards_do_not_extract_or_contact_engine(tmp_path, kind):
    root, _, manifest, inspections, blobs = make_portable(tmp_path / "bundle")
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w") as archive:
        for name, raw in blobs.items():
            item = tarfile.TarInfo(name); item.size = len(raw)
            archive.addfile(item, io.BytesIO(raw))
        item = tarfile.TarInfo({"duplicate": "index.json", "parent": "../outside",
            "symlink": "repositories", "directory": "unrelated", "metadata-limit": "repositories"}[kind])
        raw = b"{}"
        if kind == "symlink": item.type, item.linkname = tarfile.SYMTYPE, "../outside"
        elif kind == "directory": item.type = tarfile.DIRTYPE
        elif kind == "metadata-limit": raw = b" " * (2 * 1024**2 + 1)
        item.size = len(raw) if item.isfile() else 0
        archive.addfile(item, io.BytesIO(raw))
    (root / "images.tar").write_bytes(output.getvalue())
    repin(root, manifest)
    engine = ImageEngine(manifest, inspections)
    with pytest.raises(BundleError):
        runtime.ensure_images(engine, root, manifest)
    assert engine.calls == [] and not (tmp_path / "outside").exists()


@pytest.mark.parametrize("change", ["null", "empty", "boolean-version", "unknown-version", "extra-role", "extra-field", "config-binding"])
def test_present_invalid_extension_is_not_legacy_fallback(tmp_path, change):
    root, _, manifest, inspections, _ = make_portable(tmp_path / "bundle")
    value = manifest["image_identity"]
    if change == "null": manifest["image_identity"] = None
    elif change == "empty": manifest["image_identity"] = {}
    elif change == "boolean-version": value["version"] = True
    elif change == "unknown-version": value["version"] = 2
    elif change == "extra-role": value["roles"]["worker"] = value["roles"]["backend"]
    elif change == "extra-field": value["fallback"] = True
    elif change == "config-binding": value["roles"]["web"]["config_digest"] = "sha256:" + "f" * 64
    engine = ImageEngine(manifest, inspections)
    with pytest.raises(BundleError, match="IMAGE_IDENTITY_SCHEMA_INVALID"):
        runtime.ensure_images(engine, root, manifest)
    assert engine.calls == []


@pytest.mark.parametrize("change", ["source", "repository", "platform", "architecture", "command", "entrypoint", "descriptor"])
def test_loaded_wrong_identity_never_falls_back_or_loads(tmp_path, change):
    root, _, manifest, inspections, _ = make_portable(tmp_path / "bundle")
    engine = ImageEngine(manifest, inspections, loaded=True)
    row = engine.rows["backend"]
    if change == "source": row["Config"]["Labels"]["org.opencontainers.image.revision"] = "b" * 40
    elif change == "repository": row["Config"]["Labels"]["org.opencontainers.image.source"] = "other/repository"
    elif change == "platform": row["Os"] = "windows"
    elif change == "architecture": row["Architecture"] = "arm64"
    elif change == "command": row["Config"]["Cmd"] = ["python", "server.py"]
    elif change == "entrypoint": row["Config"]["Entrypoint"] = ["unapproved"]
    elif change == "descriptor": row["Descriptor"]["digest"] = "sha256:" + "f" * 64
    with pytest.raises(BundleError):
        runtime.ensure_images(engine, root, manifest)
    assert not any(call[0] == "load" for call in engine.calls)


def test_named_import_refuses_foreign_tag_without_mutation(tmp_path):
    root, _, manifest, inspections, _ = make_portable(tmp_path / "bundle")
    engine = ImageEngine(manifest, inspections)
    foreign = copy.deepcopy(inspections["guard"]); foreign["Id"] = "sha256:" + "f" * 64
    reference = manifest["image_identity"]["roles"]["guard"]["archive_ref"]
    engine.tags[reference] = foreign
    before = copy.deepcopy(engine.tags)
    with pytest.raises(BundleError, match="IMAGE_TAG_CONFLICT"):
        runtime.ensure_images(engine, root, manifest)
    assert not any(call[0] == "load" for call in engine.calls)
    assert engine.tags == before and not engine.loaded


@pytest.mark.parametrize("phase", ["id-lookup", "tag-lookup"])
def test_archive_replacement_cannot_change_loaded_bytes(tmp_path, phase):
    root, _, manifest, inspections, _ = make_portable(tmp_path / "bundle")
    original = (root / "images.tar").read_bytes()
    replacement = tar_bytes({"repositories": b'{"foreign":{"latest":"unrelated"}}'})
    class ReplacingEngine(ImageEngine):
        replaced, imported = False, None
        def run(self, *args, **kwargs):
            if args[:2] == ("image", "inspect") and not self.replaced:
                is_id = args[2].startswith("sha256:")
                if is_id == (phase == "id-lookup"):
                    (root / "images.tar").write_bytes(replacement)
                    self.replaced = True
            if args[0] == "load":
                assert Path(args[2]) != root / "images.tar"
                self.imported = Path(args[2]).read_bytes()
            return super().run(*args, **kwargs)
    engine = ReplacingEngine(manifest, inspections)
    if phase == "id-lookup":
        with pytest.raises(BundleError): runtime.ensure_images(engine, root, manifest)
        assert engine.imported is None and not engine.loaded
    else:
        runtime.ensure_images(engine, root, manifest)
        assert engine.imported == original and engine.loaded
    assert engine.replaced and not list(tmp_path.glob(".izo-image-load-*"))


def persisted(root, pin, state):
    target = state / "releases" / pin
    target.parent.mkdir(parents=True)
    shutil.copytree(root, target)
    return target


def test_persistent_sibling_only_changes_verified_image_fields_and_all_commands_use_it(tmp_path):
    from tools.docker_test_bundle_images import resolve_images, runtime_compose
    root, pin, manifest, inspections, _ = make_portable(tmp_path / "bundle")
    release = persisted(root, pin, tmp_path / "state")
    engine = ImageEngine(manifest, inspections, loaded=True)
    original = (release / "compose.json").read_bytes()
    images = resolve_images(engine, manifest)
    sibling = runtime_compose(release, manifest, images, create=True)
    expected = json.loads(original)
    for role, image in images.items(): expected["services"][role]["image"] = image
    assert sibling.parent == release.parent and sibling != release / "compose.json"
    assert sibling.read_bytes() == json_bytes(expected)
    for action in ("config", "run", "up", "down", "restart"):
        runtime.Docker.compose(engine, release, manifest, action)
    commands = [call for call in engine.calls if call[0] == "compose"]
    assert len(commands) == 5
    assert all(call[call.index("-f") + 1] == str(sibling)
               and call[call.index("--project-directory") + 1] == str(release) for call in commands)
    assert (release / "compose.json").read_bytes() == original and verify(release, pin) == manifest


@pytest.mark.parametrize("change", ["image", "policy", "duplicate-key", "symlink"])
def test_derived_compose_tamper_is_never_overwritten(tmp_path, change):
    from tools.docker_test_bundle_images import resolve_images, runtime_compose
    root, pin, manifest, inspections, _ = make_portable(tmp_path / "bundle")
    release = persisted(root, pin, tmp_path / "state")
    engine = ImageEngine(manifest, inspections, loaded=True)
    sibling = runtime_compose(release, manifest, resolve_images(engine, manifest), create=True)
    config = json.loads(sibling.read_text())
    if change == "image": config["services"]["web"]["image"] = "sha256:" + "f" * 64
    elif change == "policy": config["services"]["guard"]["privileged"] = True
    if change == "duplicate-key": sibling.write_bytes(b'{"name":"foreign",' + sibling.read_bytes()[1:])
    elif change == "symlink":
        outside = tmp_path / "outside.json"; outside.write_bytes(sibling.read_bytes())
        sibling.unlink()
        try: sibling.symlink_to(outside)
        except OSError: pytest.skip("symlink privilege unavailable")
    else: sibling.write_bytes(json_bytes(config))
    before = sibling.read_bytes()
    with pytest.raises(BundleError): runtime.Docker.compose(engine, release, manifest, "up")
    assert sibling.read_bytes() == before and not any(call[0] == "compose" for call in engine.calls)


def test_two_file_bootstrap_verifies_and_extracts_without_tools_package(tmp_path):
    from tools import docker_test_bundle_format as format_module, docker_test_bundle_images as image_module
    root, pin, manifest, _, _ = make_portable(tmp_path / "bundle")
    bootstrap = tmp_path / "bootstrap"; bootstrap.mkdir()
    for module in (format_module, image_module): shutil.copyfile(module.__file__, bootstrap / Path(module.__file__).name)
    archive = tmp_path / "bundle.zip"
    with zipfile.ZipFile(archive, "w") as output:
        for path in root.rglob("*"):
            if path.is_file(): output.write(path, path.relative_to(root).as_posix())
    target = tmp_path / "extracted"
    code = "import sys; from pathlib import Path; sys.path.insert(0,sys.argv[1]); import docker_test_bundle_format as f; f.extract(Path(sys.argv[2]),sys.argv[3],Path(sys.argv[4])); print(f.verify(Path(sys.argv[4]),sys.argv[5])['image_identity']['version'])"
    run = subprocess.run([sys.executable, "-I", "-B", "-c", code, str(bootstrap), str(archive),
                          digest(archive.read_bytes())[7:], str(target), pin], capture_output=True, text=True, timeout=20)
    assert run.returncode == 0, run.stderr
    assert run.stdout.strip() == "1" and verify(target, pin) == manifest


@pytest.mark.parametrize("schema", [7, 8])
def test_health_and_previous_active_check_exact_resolved_role_ids(tmp_path, monkeypatch, schema):
    from contextlib import nullcontext
    from types import SimpleNamespace
    from tools.docker_test_bundle_images import resolve_images, runtime_compose
    root, pin, manifest, inspections, _ = make_portable(tmp_path / "bundle")
    from tools.docker_test_bundle_format import runtime_environment
    from tools.test_docker_synthetic_runtime import repin
    manifest["schema"] = schema
    config = json.loads((root / "compose.json").read_bytes())
    config["services"]["backend"]["environment"].update(runtime_environment(schema))
    pin = repin(root, manifest, config)
    state = tmp_path / "state"; release = persisted(root, pin, state)
    engine = ImageEngine(manifest, inspections, loaded=True)
    images = resolve_images(engine, manifest)
    sibling = runtime_compose(release, manifest, images, create=True)
    containers = [{"Id": role + "-container", "Image": images[role],
        "State": {"Running": True, "Health": {"Status": "healthy"}},
        "HostConfig": {"NetworkMode": "container:guard-container"},
        "Config": {"Cmd": UVICORN, "Labels": {"com.docker.compose.service": role,
                    "com.docker.compose.project.config_files": str(sibling)}}} for role in sorted(images)]
    monkeypatch.setattr(runtime, "owned_resources", lambda *args: {"containers": containers, "volumes": [], "networks": []})
    version = {"backend_commit": manifest["source_sha"], "release_id": manifest["release_id"],
               "frontend_build": manifest["release_id"], "schema_compatibility": {"min_version": schema, "max_version": schema}}
    origin = "http://127.0.0.1:" + str(manifest["ports"]["web"]) + "/api/version"
    def open_response(request, **kwargs):
        url = request.full_url
        relative = url[len(origin.removesuffix("/api/version")):]
        data = json_bytes(version) if relative == "/api/version" else (
            release / "frontend" / ("index.html" if relative == "/" else relative[1:])).read_bytes()
        return nullcontext(SimpleNamespace(geturl=lambda: url, read1=io.BytesIO(data).read1, status=200,
            read_deadline=request.izo_read_deadline))
    opener = SimpleNamespace(open=open_response, handlers=[runtime.DeadlineHTTPHandler()])
    monkeypatch.setattr(runtime, "build_opener", lambda *args: opener)
    result = runtime.health(engine, release, manifest)
    assert result["resolved_images"] == images and result["image_identity_version"] == 1
    version["schema_compatibility"] = {"min_version": 7, "max_version": 8}
    with pytest.raises(BundleError, match="RUNTIME_VERSION_MISMATCH"):
        runtime.health(engine, release, manifest)
    version["schema_compatibility"] = {"min_version": schema, "max_version": schema}
    containers[0]["Image"] = "sha256:" + "f" * 64
    with pytest.raises(BundleError, match="RUNTIME_NOT_READY"):
        runtime.health(engine, release, manifest)
    previous = {"manifest_sha256": pin}
    active = state / "active.json"; active.write_bytes(json_bytes(previous))
    monkeypatch.setattr(runtime, "check_volumes", lambda *args: None)
    with pytest.raises(BundleError, match="ACTIVE_IMAGE_DRIFT"):
        runtime.install_locked(root, pin, state, engine, manifest, {}, previous, False)
    assert active.read_bytes() == json_bytes(previous)
    assert all(call[:2] == ("image", "inspect") for call in engine.calls)
    assert manifest["images"] != images and verify(release, pin) == manifest


def test_compose_derivation_uses_same_verified_bytes_even_if_source_replaced(tmp_path, monkeypatch):
    from tools import docker_test_bundle_images as images_module
    root, pin, manifest, inspections, _ = make_portable(tmp_path / "bundle")
    release = persisted(root, pin, tmp_path / "state")
    engine = ImageEngine(manifest, inspections, loaded=True)
    mapping = images_module.resolve_images(engine, manifest)
    original = json.loads((release / "compose.json").read_bytes())
    changed = copy.deepcopy(original)
    changed["services"]["backend"]["environment"]["UNVERIFIED_EXTRA"] = "forbidden"
    parse = images_module._json
    def replace_after_hash(metadata, name):
        if name == "compose.json": (release / name).write_bytes(json_bytes(changed))
        return parse(metadata, name)
    monkeypatch.setattr(images_module, "_json", replace_after_hash)
    sibling = images_module.runtime_compose(release, manifest, mapping, create=True)
    for role, image in mapping.items(): original["services"][role]["image"] = image
    assert sibling.read_bytes() == json_bytes(original)
    with pytest.raises(BundleError, match="PAYLOAD_HASH_MISMATCH"):
        images_module.runtime_compose(release, manifest, mapping, create=True)


@pytest.mark.parametrize("changed", [False, True])
def test_archive_ctime_compares_within_each_stat_api_without_ignoring_changes(tmp_path, monkeypatch, changed):
    from types import SimpleNamespace
    from tools import docker_test_bundle_images as images_module
    root, _, manifest, _, _ = make_portable(tmp_path / "bundle")
    original, calls = images_module.os.fstat, []
    def descriptor_stat(fd):
        result = original(fd); calls.append(fd)
        values = {name: getattr(result, name) for name in ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_mode")}
        return SimpleNamespace(**values, st_ctime_ns=result.st_ctime_ns + 100 + int(changed and len(calls) > 1))
    monkeypatch.setattr(images_module.os, "fstat", descriptor_stat)
    if changed:
        with pytest.raises(BundleError, match="IMAGE_ARCHIVE_CHANGED"): images_module.verify_archive(root, manifest)
    else: images_module.verify_archive(root, manifest)
    assert len(calls) == 2
