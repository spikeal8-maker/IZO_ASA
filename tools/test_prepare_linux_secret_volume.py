"""Owned-volume admission never changes existing secret material or foreign resources."""
from __future__ import annotations

import copy
import builtins
import json

import pytest

from tools import prepare_linux_secret_volume as subject
from tools.docker_test_bundle_format import BundleError


IMAGE = "sha256:" + "a" * 64
SOURCE = "b" * 40


class DockerFixture:
    def __init__(self, *, existing=False):
        self.calls = []
        self.image = {"Id": IMAGE, "Os": "linux", "Architecture": "amd64", "Config": {
            "User": "10001:10001", "Labels": {"org.opencontainers.image.revision": SOURCE,
            "org.opencontainers.image.source": subject.REPOSITORY}}}
        self.volume = self.make_volume() if existing else None
        self.metadata = {"uid": 10001, "gid": 10001, "mode": "0700", "entry_count": 0}
        self.containers = {}
        self.collision = False
        self.fail_start = False
        self.attached = ""

    def make_volume(self):
        return {"Name": subject.VOLUME, "Driver": "local", "Scope": "local", "Options": None,
                "CreatedAt": "2026-11-08T13:00:00Z", "Labels": {
                **subject.LABELS, subject.NONCE_LABEL: "c" * 32}}

    def engine(self):
        return "d" * 64

    def run(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if args[:2] == ("image", "inspect"):
            return json.dumps([self.image])
        if args[:2] == ("volume", "inspect"):
            return None if self.volume is None else json.dumps([self.volume])
        if args[:2] == ("volume", "create"):
            self.volume = self.make_volume()
            if not self.collision:
                labels = dict(args[i + 1].split("=", 1) for i, item in enumerate(args) if item == "--label")
                self.volume["Labels"] = labels
            return subject.VOLUME
        if args[:2] == ("ps", "-aq"):
            return self.attached
        if args[0] == "create":
            identity = format(len(self.containers) + 1, "064x")
            self.containers[identity] = {"Config": {"Labels": dict(
                args[i + 1].split("=", 1) for i, item in enumerate(args) if item == "--label")},
                "State": {"ExitCode": 0}, "initialize": "CHOWN" in args}
            return identity
        if args[:2] == ("start", "--attach"):
            if self.fail_start:
                raise BundleError("FIXTURE_START_FAILED")
            return json.dumps({"initialized_empty": True} if self.containers[args[2]]["initialize"] else self.metadata)
        if args[0] == "inspect":
            return json.dumps([self.containers[args[1]]])
        if args[:2] == ("rm", "--force"):
            del self.containers[args[2]]
            return args[2]
        raise AssertionError("Unexpected fixture operation")


@pytest.fixture(autouse=True)
def native_linux(monkeypatch):
    # Pure host planning contract runs on Windows CI without invoking Docker or POSIX calls.
    monkeypatch.setattr(subject.sys, "platform", "linux")


def test_absent_plan_is_read_only_and_requires_explicit_apply():
    docker = DockerFixture()
    result = subject.prepare(docker, IMAGE, SOURCE)
    assert result["status"] == "LINUX_SECRET_VOLUME_PLANNED"
    assert result["create_required"] is True and docker.volume is None
    assert all(args[0] != "create" and args[:2] != ("volume", "create") for args, _ in docker.calls)


def test_new_owned_empty_volume_initialized_once_then_read_only_validated():
    docker = DockerFixture()
    result = subject.prepare(docker, IMAGE, SOURCE, apply=True)
    assert result["status"] == "LINUX_SECRET_VOLUME_READY" and result["created"] is True
    assert result["existing_material_modified"] is False and result["metadata"]["entry_count"] == 0
    creates = [args for args, _ in docker.calls if args[0] == "create"]
    assert len(creates) == 2
    init, validate = creates
    assert init[init.index("--user") + 1] == "0:0" and init[init.index("--cap-add") + 1] == "CHOWN"
    assert validate[validate.index("--user") + 1] == "10001:10001" and "--cap-add" not in validate
    for args in creates:
        assert args[args.index("--network") + 1] == "none" and "--read-only" in args
        assert args[args.index("--cap-drop") + 1] == "ALL" and "no-new-privileges:true" in args
        mounts = [args[i + 1] for i, arg in enumerate(args) if arg == "--mount"]
        assert len(mounts) == 1 and subject.VOLUME in mounts[0] and "volume-nocopy" in mounts[0]
        assert IMAGE in args and "/var/run/docker.sock" not in str(args)
        assert "-I" in args and "-B" in args
    assert "readonly" in validate[validate.index("--mount") + 1]
    assert not docker.containers


@pytest.mark.parametrize("apply", [False, True])
def test_existing_volume_only_validated_without_chmod_chown_or_create(apply):
    docker = DockerFixture(existing=True)
    docker.metadata["entry_count"] = 3
    before = copy.deepcopy(docker.volume)
    result = subject.prepare(docker, IMAGE, SOURCE, apply=apply)
    assert result["created"] is False and docker.volume == before
    creates = [args for args, _ in docker.calls if args[0] == "create"]
    assert len(creates) == 1 and "CHOWN" not in creates[0]
    assert subject.INITIALIZE not in creates[0] and subject.VALIDATE in creates[0]
    assert not any(args[:2] == ("volume", "create") for args, _ in docker.calls)


@pytest.mark.parametrize("damage", ["label", "extra-label", "driver", "options", "name", "nonce"])
def test_foreign_or_ambiguous_volume_rejected_without_container_or_mutation(damage):
    docker = DockerFixture(existing=True)
    if damage == "label":
        docker.volume["Labels"]["org.izo.project"] = "foreign"
    elif damage == "extra-label":
        docker.volume["Labels"]["foreign"] = "value"
    elif damage == "nonce":
        docker.volume["Labels"][subject.NONCE_LABEL] = ""
    elif damage == "driver":
        docker.volume["Driver"] = "nfs"
    elif damage == "options":
        docker.volume["Options"] = {"device": "/foreign"}
    else:
        docker.volume["Name"] = "foreign-volume"
    before = copy.deepcopy(docker.volume)
    with pytest.raises(BundleError, match="IDENTITY_MISMATCH"):
        subject.prepare(docker, IMAGE, SOURCE, apply=True)
    assert docker.volume == before and not docker.containers
    assert not any(args[0] == "create" for args, _ in docker.calls)


def test_creation_collision_never_initializes_an_existing_volume():
    docker = DockerFixture()
    docker.collision = True
    with pytest.raises(BundleError, match="COLLISION"):
        subject.prepare(docker, IMAGE, SOURCE, apply=True)
    assert not any(args[0] == "create" for args, _ in docker.calls)


@pytest.mark.parametrize("damage", ["uid", "gid", "mode", "entry_count"])
def test_bad_existing_metadata_fails_without_repair(damage):
    docker = DockerFixture(existing=True)
    docker.metadata[damage] = "0755" if damage == "mode" else -1
    with pytest.raises(BundleError, match="METADATA_INVALID"):
        subject.prepare(docker, IMAGE, SOURCE, apply=True)
    assert not docker.containers
    assert not any("CHOWN" in args for args, _ in docker.calls)


def test_new_volume_must_still_be_empty_after_initialization():
    docker = DockerFixture()
    docker.metadata["entry_count"] = 1
    with pytest.raises(BundleError, match="NOT_EMPTY"):
        subject.prepare(docker, IMAGE, SOURCE, apply=True)
    assert not docker.containers


def test_probe_failure_removes_only_its_owned_container():
    docker = DockerFixture(existing=True)
    docker.fail_start = True
    with pytest.raises(BundleError, match="FIXTURE_START_FAILED"):
        subject.prepare(docker, IMAGE, SOURCE, apply=True)
    assert not docker.containers
    assert not any(args[:2] == ("volume", "rm") for args, _ in docker.calls)


@pytest.mark.parametrize("field,value", [("Id", "sha256:" + "f" * 64), ("Os", "windows"), ("Architecture", "arm64")])
def test_image_pin_is_checked_before_any_volume_operation(field, value):
    docker = DockerFixture()
    docker.image[field] = value
    with pytest.raises(BundleError, match="EXACT_BACKEND_SOURCE"):
        subject.prepare(docker, IMAGE, SOURCE, apply=True)
    assert not any(args[0] == "volume" for args, _ in docker.calls)


def test_new_volume_cannot_be_initialized_while_attached():
    docker = DockerFixture()
    docker.attached = "foreign-fixture-container"
    with pytest.raises(BundleError, match="IN_USE"):
        subject.prepare(docker, IMAGE, SOURCE, apply=True)
    assert docker.volume is None


def test_changed_source_label_cannot_prepare_a_volume():
    docker = DockerFixture()
    docker.image["Config"]["Labels"]["org.opencontainers.image.revision"] = "f" * 40
    with pytest.raises(BundleError, match="EXACT_BACKEND_SOURCE"):
        subject.prepare(docker, IMAGE, SOURCE, apply=True)
    assert not any(args[0] == "volume" for args, _ in docker.calls)


@pytest.mark.parametrize("initialize", [False, True])
def test_unsafe_volume_gates_survive_python_optimization(initialize):
    from types import SimpleNamespace

    mutations = []
    fake_os = SimpleNamespace(O_RDONLY=0, O_DIRECTORY=0, O_NOFOLLOW=0,
        open=lambda *_args: 7, close=lambda _fd: None, getuid=lambda: 0,
        fstat=lambda _fd: SimpleNamespace(st_uid=10001 if initialize else 0,
            st_gid=10001 if initialize else 0, st_mode=0o40700 if initialize else 0o40755),
        listdir=lambda _fd: [], fsync=lambda _fd: None,
        fchmod=lambda *_args: mutations.append("chmod"), fchown=lambda *_args: mutations.append("chown"))
    ordinary_import = builtins.__import__
    def controlled_import(name, *args, **kwargs):
        return fake_os if name == "os" else ordinary_import(name, *args, **kwargs)
    namespace = {"__builtins__": {**vars(builtins), "__import__": controlled_import}}
    code = compile(subject.INITIALIZE if initialize else subject.VALIDATE, "volume-safety-gate", "exec", optimize=2)
    with pytest.raises(RuntimeError, match="metadata is unsafe"):
        exec(code, namespace)
    assert mutations == []
