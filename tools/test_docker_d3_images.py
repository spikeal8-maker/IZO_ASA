"""Real small archives reject corrupt/foreign images before any Docker mutation."""
from contextlib import nullcontext
from copy import deepcopy
import hashlib
import io
import json
import os
from pathlib import Path
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from tools import docker_d3_images as subject
from tools.docker_shadow_product import ProductError

SHA = "a" * 40


def members():
    files, tags, manifest, index = {}, {}, [], []
    for service, name in (("guard", "shadow-guard"), ("web", "shadow-web"), ("backend", "dev-backend")):
        config = json.dumps({"architecture": "amd64", "os": "linux", "config": {"Labels": {
            "org.opencontainers.image.revision": SHA, "org.opencontainers.image.source": subject.REPOSITORY},
            "Cmd": [service]}}).encode()
        digest = hashlib.sha256(config).hexdigest()
        config_path = "blobs/sha256/" + digest
        tag, image_id = "izo-asa-" + name + ":" + SHA, "sha256:" + digest
        tags[tag] = image_id
        layer = "blobs/sha256/" + hashlib.sha256(service.encode()).hexdigest()
        files[config_path], files[layer] = config, service.encode()
        manifest.append({"Config": config_path, "RepoTags": [tag], "Layers": [layer]})
        oci = json.dumps({"config": {"digest": image_id}, "layers": [{"digest": "sha256:" + layer.rsplit("/", 1)[1]}]}).encode()
        oci_digest = hashlib.sha256(oci).hexdigest()
        files["blobs/sha256/" + oci_digest] = oci
        index.append({"digest": "sha256:" + oci_digest, "annotations": {"io.containerd.image.name": "docker.io/library/" + tag}})
    files["manifest.json"] = json.dumps(manifest).encode()
    files["index.json"] = json.dumps({"manifests": index}).encode()
    return files, tags


def archive(path, files, extra=None):
    with tarfile.open(path, "w") as output:
        for name, data in files.items():
            item = tarfile.TarInfo(name); item.size = len(data)
            output.addfile(item, io.BytesIO(data))
        if extra is not None:
            output.addfile(extra)


def image_map(tags):
    values = {service: tags[f"izo-asa-{name}:{SHA}"] for service, name in (
        ("guard", "shadow-guard"), ("web", "shadow-web"), ("backend", "dev-backend"))}
    return {**values, "worker": values["backend"], "worker_peer": values["backend"]}


def inventory(mapping):
    return "\n".join(json.dumps({"Repository": tag.rsplit(":", 1)[0], "Tag": tag.rsplit(":", 1)[1], "ID": digest})
                     for tag, digest in mapping.items())


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.path = self.root / "images.tar"
        self.files, self.tags = members()

    def test_docker_and_oci_config_digests_must_identify_the_same_three_tested_images(self):
        archive(self.path, self.files)
        result = subject.archive_metadata(self.path, self.tags, SHA)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["images"], self.tags)
        self.assertIs(result["extracted"], False)
        self.assertEqual(list(self.root.iterdir()), [self.path])

    def test_changed_config_and_foreign_docker_or_oci_tag_are_rejected(self):
        for fault in ("config", "docker", "oci", "missing-layer"):
            files = deepcopy(self.files)
            row = json.loads(files["manifest.json"])[0]
            if fault == "config":
                files[row["Config"]] += b" "
            elif fault == "docker":
                manifest = json.loads(files["manifest.json"])
                manifest[0]["RepoTags"] = ["foreign:latest"]
                files["manifest.json"] = json.dumps(manifest).encode()
            elif fault == "oci":
                index = json.loads(files["index.json"])
                index["manifests"][0]["annotations"]["io.containerd.image.name"] = "foreign:latest"
                files["index.json"] = json.dumps(index).encode()
            else:
                del files[row["Layers"][0]]
            archive(self.path, files)
            with self.subTest(fault=fault), self.assertRaises(ProductError):
                subject.archive_metadata(self.path, self.tags, SHA)

    def test_path_traversal_duplicate_and_link_headers_are_never_extracted(self):
        for name, kind in (("../foreign", tarfile.REGTYPE), ("manifest.json", tarfile.REGTYPE),
                           ("link", tarfile.SYMTYPE), ("hardlink", tarfile.LNKTYPE)):
            extra = tarfile.TarInfo(name); extra.type = kind; extra.linkname = "/foreign"
            archive(self.path, self.files, extra)
            with self.subTest(name=name), self.assertRaises(ProductError):
                subject.archive_metadata(self.path, self.tags, SHA)
        self.assertEqual(list(self.root.iterdir()), [self.path])

    def test_fixed_browser_source_set_includes_new_io(self):
        for name in subject.RUNTIME_SOURCES:
            target = self.root / name; target.parent.mkdir(exist_ok=True)
            target.write_text("safe-local-source")
        result = subject.runtime_sources(self.root)
        self.assertEqual(len(result), 10)
        self.assertIn("tools/docker_d3_browser_io.mjs", result)

    @unittest.skipUnless(os.name == "posix", "Real POSIX symlink rejection runs in the Linux source gate")
    def test_fixed_browser_source_refuses_real_symlink(self):
        for name in subject.RUNTIME_SOURCES:
            target = self.root / name; target.parent.mkdir(exist_ok=True); target.write_text("source")
        source = self.root / "tools/docker_d3_browser_io.mjs"
        source.unlink(); source.symlink_to(self.root / "tools/docker_d3_chat_video.mjs")
        with self.assertRaises(ProductError):
            subject.runtime_sources(self.root)

    def test_atomic_private_checkpoint_and_oversized_file_checks(self):
        path = self.root / "private" / "receipt.json"
        subject.save_private(path, {"status": "FAIL"})
        subject.save_private(path, {"status": "PARTIAL"})
        self.assertEqual(json.loads(path.read_text())["status"], "PARTIAL")
        if os.name == "posix":
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertFalse(path.with_name("receipt.json.tmp").exists())
        with self.assertRaises(ProductError):
            subject.read_file(path, 2)


class LoadTests(unittest.TestCase):
    setUp = ArchiveTests.setUp

    def prepared(self, before=None):
        archive(self.path, self.files)
        for name in subject.RUNTIME_SOURCES:
            target = self.root / name; target.parent.mkdir(exist_ok=True); target.write_text("source")
        images = image_map(self.tags)
        calls = []
        prior = before or {"foreign:stable": "sha256:" + "f" * 64}
        def docker(*args, **kwargs):
            calls.append(args)
            if args[:2] == ("image", "ls"):
                loaded = any(call[:2] == ("image", "load") for call in calls)
                return inventory({**prior, **self.tags} if loaded else prior)
            return ""
        shadow = SimpleNamespace(sha=SHA, root=self.root, source_guard=Mock(), config=Mock(return_value={}),
            image_guard=Mock(return_value=images), docker=Mock(side_effect=docker))
        manifest = {"images": images, "runtimeSources": subject.runtime_sources(self.root),
                    "archive": {"name": "images.tar", **subject.digest(self.path)}}
        return shadow, manifest, images

    def test_only_admitted_archive_is_loaded_without_build_pull_or_foreign_tag_changes(self):
        shadow, manifest, images = self.prepared()
        result = subject.load_images(shadow, self.root, manifest, images, wallclock=lambda _: nullcontext())
        self.assertEqual(result["status"], "PASS")
        self.assertTrue(result["foreignImagesUnchanged"])
        self.assertEqual([call.args[:2] for call in shadow.docker.call_args_list],
                         [("image", "ls"), ("image", "load"), ("image", "ls")])

    def test_corrupt_archive_source_or_existing_image_prevents_load(self):
        for fault in ("digest", "browser-io", "collision"):
            shadow, manifest, images = self.prepared(self.tags if fault == "collision" else None)
            if fault == "digest":
                manifest["archive"]["sha256"] = "0" * 64
            elif fault == "browser-io":
                manifest["runtimeSources"].pop("tools/docker_d3_browser_io.mjs")
            with self.subTest(fault=fault), self.assertRaises(ProductError):
                subject.load_images(shadow, self.root, manifest, images, wallclock=lambda _: nullcontext())
            self.assertFalse(any(call.args[:2] == ("image", "load") for call in shadow.docker.call_args_list))
