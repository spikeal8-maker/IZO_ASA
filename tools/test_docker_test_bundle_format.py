"""Synthetic archive/integrity/policy tests. Never contact Docker or live data."""
from __future__ import annotations

import copy
import hashlib
import json
import stat
import zipfile
from pathlib import Path

import pytest

from tools.docker_test_bundle_format import (
    BundleError, OWNER, REPOSITORY, SERVICES, VOLUMES, extract, file_hash,
    inventory, json_bytes, safe_name, validate_compose, verify,
)


def make_bundle(root: Path, sha: str = "a" * 40) -> tuple[Path, str, dict]:
    root.mkdir()
    project = "izo-asa-bundle-unit001"
    m = {"format": 1, "kind": "isoas-test-bundle", "repository": REPOSITORY,
         "source_sha": sha, "tooling_sha": "b" * 40,
         "release_id": sha[:12] + "-20261027130000", "project": project, "schema": 7,
         "ports": {"web": 48614, "api": 48615}, "production_authorized": False,
         "model_execution": False, "images": {role: "sha256:" + "c" * 64 for role in SERVICES}}
    c = {"name": project, "services": {}, "volumes": {}, "networks": {}}
    for kind, names in (("volumes", VOLUMES), ("networks", {"shadow"})):
        for name in names:
            c[kind][name] = {"name": project + "_" + name, "labels": {"io.izo.bundle": OWNER}}
    for role in SERVICES:
        c["services"][role] = {"image": m["images"][role], "pull_policy": "never",
            "labels": {"io.izo.bundle": OWNER, "org.opencontainers.image.revision": sha},
            "cap_drop": ["ALL"], "security_opt": ["no-new-privileges:true"],
            "user": "101:101" if role == "web" else "10001:10001",
            "network_mode": "service:guard"}
    g = c["services"]["guard"]
    g.pop("network_mode")
    g.update(networks={"shadow": {}}, dns=["127.0.0.1"], cap_add=["NET_ADMIN", "SETUID", "SETGID"],
             ports=[{"host_ip": "127.0.0.1", "published": 48614, "target": 8080},
                    {"host_ip": "127.0.0.1", "published": 48615, "target": 8000}])
    c["services"]["backend"].update(command=["python", "/opt/izo/fixtures/docker_shadow_fixture.py"],
        environment={"APP_ENV": "test", "ENV": "test", "MODE": "test",
                     "IZO_SHADOW_FIXTURE": "controlled-comfyui-v1", "COMFYUI_BASE_URL": "http://127.0.0.1:48991",
                     "BOT_MODE": "disabled", "MAX_UPDATES_MODE": "disabled", "OPENROUTER_API_KEY": ""})
    for role in ("worker", "worker_peer"):
        c["services"][role]["command"] = ["python", "-m", "app.generation_worker"]
    (root / "compose.json").write_bytes(json_bytes(c))
    (root / "frontend").mkdir()
    (root / "frontend/index.html").write_text("test-assets", encoding="utf-8")
    m["files"] = inventory(root)
    (root / "bundle.json").write_bytes(json_bytes(m))
    return root, file_hash(root / "bundle.json")[1], m


@pytest.mark.parametrize("name", ["../x", "/x", "C:/x", "a\\b", "a//b", "a/./b", "NUL.txt", "a:stream",
                                 "x. ", "COM1", "a/$x", "a\x00b", "a\nb", ""])
def test_unsafe_portable_members_rejected(name):
    with pytest.raises(BundleError):
        safe_name(name)


@pytest.mark.parametrize("name", ["frontend/index.html", "spaced folder/hello.json", "тест/файл.txt"])
def test_portable_relative_members(name):
    assert safe_name(name) == name


def test_hash_verified_bundle_and_tamper(tmp_path):
    root, pin, manifest = make_bundle(tmp_path / "payload")
    assert verify(root, pin) == manifest
    (root / "frontend/index.html").write_text("corrupted", encoding="utf-8")
    with pytest.raises(BundleError, match="PAYLOAD_HASH_MISMATCH"):
        verify(root, pin)


def test_bad_manifest_pin_and_unlisted_file(tmp_path):
    root, pin, _ = make_bundle(tmp_path / "payload")
    with pytest.raises(BundleError, match="MANIFEST_PIN_MISMATCH"):
        verify(root, "0" * 64)
    (root / "surprise.txt").write_text("not expected")
    with pytest.raises(BundleError, match="PAYLOAD_HASH_MISMATCH"):
        verify(root, pin)


def zip_bytes(root, output):
    with zipfile.ZipFile(output, "w") as archive:
        for path in root.rglob("*"):
            if path.is_file():
                archive.write(path, path.relative_to(root).as_posix())


def test_extract_with_spaces_unicode_no_git(tmp_path):
    root, pin, m = make_bundle(tmp_path / "original")
    archive = tmp_path / "bundle.zip"
    zip_bytes(root, archive)
    target = tmp_path / "unpacked Тест with spaces"
    extract(archive, file_hash(archive)[1], target)
    assert verify(target, pin) == m
    assert not (target / ".git").exists()
    with pytest.raises(BundleError, match="EXTRACTION_DESTINATION_EXISTS"):
        extract(archive, file_hash(archive)[1], target)


@pytest.mark.parametrize("badname", ["../outside", "/outside", "a/../outside", "C:/outside", "NUL"])
def test_extractor_does_not_escape_destination(tmp_path, badname):
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr(badname, "payload")
    with pytest.raises(BundleError, match="UNSAFE_MEMBER_NAME"):
        extract(archive, file_hash(archive)[1], tmp_path / "target")
    assert not (tmp_path / "target").exists()
    assert not (tmp_path / "outside").exists()


def test_archive_duplicate_case_and_symlink(tmp_path):
    for i, members in enumerate([[("A.txt", "x"), ("a.TXT", "y")], [("symbolic", "other")]]):
        archive = tmp_path / f"bad-{i}.zip"
        with zipfile.ZipFile(archive, "w") as z:
            for name, content in members:
                info = zipfile.ZipInfo(name)
                if i:
                    info.create_system = 3
                    info.external_attr = (stat.S_IFLNK | 0o777) << 16
                z.writestr(info, content)
        with pytest.raises(BundleError):
            extract(archive, file_hash(archive)[1], tmp_path / f"target-{i}")
        assert not (tmp_path / f"target-{i}").exists()


def test_bad_archive_hash_has_no_output(tmp_path):
    archive = tmp_path / "bad.zip"
    archive.write_bytes(b"not a zip")
    with pytest.raises(BundleError, match="ARCHIVE_PIN_MISMATCH"):
        extract(archive, "0" * 64, tmp_path / "target")
    assert not (tmp_path / "target").exists()


@pytest.mark.parametrize("mutation", ["build", "privileged", "host_network", "live_provider", "credential", "public_port", "foreign_volume", "bind"])
def test_compose_dangerous_variants_blocked(tmp_path, mutation):
    root, _, m = make_bundle(tmp_path / "payload")
    c = json.loads((root / "compose.json").read_text())
    b = c["services"]["backend"]
    if mutation == "build": b["build"] = {"context": "/"}
    elif mutation == "privileged": b["privileged"] = True
    elif mutation == "host_network": b["network_mode"] = "host"
    elif mutation == "live_provider": b["environment"]["OLLAMA_BASE_URL"] = "https://outside.invalid"
    elif mutation == "credential": b["environment"]["OPENROUTER_API_KEY"] = "test-not-a-secret"
    elif mutation == "public_port": c["services"]["guard"]["ports"][0]["host_ip"] = "0.0.0.0"
    elif mutation == "foreign_volume": c["volumes"]["sqlite-data"]["name"] = "foreign-db"
    elif mutation == "bind": b["volumes"] = [{"type": "bind", "source": "/", "target": "/host"}]
    with pytest.raises(BundleError):
        validate_compose(c, m)


def test_duplicate_json_manifest_keys(tmp_path):
    root, _, _ = make_bundle(tmp_path / "payload")
    p = root / "bundle.json"
    p.write_text('{"format":1,"format":1}', encoding="utf-8")
    with pytest.raises(BundleError, match="DUPLICATE_JSON_KEY"):
        verify(root, file_hash(p)[1])
