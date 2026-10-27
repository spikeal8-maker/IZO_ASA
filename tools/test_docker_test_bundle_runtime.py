"""Fake Docker unit tests of the standalone synthetic bundle launcher."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from tools import docker_test_bundle_runtime as runtime
from tools.docker_test_bundle_format import BundleError, OWNER, json_bytes
from tools.test_docker_test_bundle_format import make_bundle


class FakeDocker:
    context = "desktop-linux"

    def __init__(self):
        self.calls = []
        self.fail_up = False

    def engine(self):
        self.calls.append("engine")
        return "engine-fingerprint"

    def compose(self, root, manifest, *args):
        self.calls.append((str(root), args))
        if self.fail_up and args[0] == "up":
            raise BundleError("DOCKER_OPERATION_FAILED")
        return ""


def fake_runtime(monkeypatch):
    monkeypatch.setattr(runtime, "owned_resources", lambda d, m: {"containers": [], "volumes": [], "networks": []})
    monkeypatch.setattr(runtime, "ensure_images", lambda *args: None)
    monkeypatch.setattr(runtime, "health", lambda d, r, m: {
        "status": "TEST_RUNTIME_VERIFIED", "source_sha": m["source_sha"],
        "release_id": m["release_id"], "containers": 5, "production_authorized": False})


def test_install_uses_persistent_copy_and_repeat_same_release(tmp_path, monkeypatch):
    fake_runtime(monkeypatch)
    root, pin, _ = make_bundle(tmp_path / "source")
    state = tmp_path / "permanent state"
    docker = FakeDocker()
    one = runtime.install(root, pin, state, docker)
    assert one["production_authorized"] is False
    persistent = state / "releases" / pin
    assert (persistent / "compose.json").is_file()
    assert not (state / "operation.lock").exists()
    root.rename(tmp_path / "moved-original")
    two = runtime.install(persistent, pin, state, docker)
    assert one == two
    assert all(Path(c[0]) == persistent for c in docker.calls if isinstance(c, tuple))
    assert json.loads((state / "active.json").read_text())["manifest_sha256"] == pin


def test_code_update_requires_explicit_authorization(tmp_path, monkeypatch):
    fake_runtime(monkeypatch)
    first, a, _ = make_bundle(tmp_path / "first", "a" * 40)
    second, b, _ = make_bundle(tmp_path / "second", "b" * 40)
    state = tmp_path / "state"
    docker = FakeDocker()
    runtime.install(first, a, state, docker)
    prior_up = sum(isinstance(c, tuple) and c[1][0] == "up" for c in docker.calls)
    with pytest.raises(BundleError, match="TEST_CODE_UPDATE_NOT_AUTHORIZED"):
        runtime.install(second, b, state, docker)
    assert json.loads((state / "active.json").read_text())["manifest_sha256"] == a
    assert sum(isinstance(c, tuple) and c[1][0] == "up" for c in docker.calls) == prior_up
    assert not (state / "operation.lock").exists()


def test_foreign_owner_lock_and_failed_install_keep_receipts(tmp_path, monkeypatch):
    fake_runtime(monkeypatch)
    root, pin, _ = make_bundle(tmp_path / "source")
    state = tmp_path / "state"
    state.mkdir()
    (state / "operation.lock").write_text("another-writer")
    with pytest.raises(BundleError, match="INSTALLATION_BUSY"):
        runtime.install(root, pin, state, FakeDocker())
    assert (state / "operation.lock").read_text() == "another-writer"
    (state / "operation.lock").unlink()
    docker = FakeDocker()
    docker.fail_up = True
    with pytest.raises(BundleError, match="TEST_INSTALL_FAILED_MANUAL_RECOVERY_REQUIRED"):
        runtime.install(root, pin, state, docker)
    assert not (state / "active.json").exists()
    assert json.loads((state / "last-failure.json").read_text())["data_restored"] is False
    assert not (state / "operation.lock").exists()


def test_bad_pin_causes_no_docker_call(tmp_path):
    root, _, _ = make_bundle(tmp_path / "source")
    docker = FakeDocker()
    with pytest.raises(BundleError, match="MANIFEST_PIN_MISMATCH"):
        runtime.install(root, "0" * 64, tmp_path / "state", docker)
    assert docker.calls == []
    assert not (tmp_path / "state").exists()


def test_no_host_overrides_or_secrets_in_docker_child(monkeypatch):
    for key in ("DOCKER_HOST", "DOCKER_CONTEXT", "COMPOSE_FILE", "HTTPS_PROXY", "API_KEY"):
        monkeypatch.setenv(key, "forbidden-value")
    calls = []

    def process(args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(args, 0, "ok", "")

    monkeypatch.setattr(subprocess, "run", process)
    assert runtime.Docker("desktop-linux").run("compose", "version") == "ok"
    args, kwargs = calls[0]
    assert args[:3] == ["docker", "--context", "desktop-linux"]
    assert all("forbidden-value" != v for v in kwargs["env"].values())
    assert not kwargs.get("shell", False)


@pytest.mark.parametrize("context", ["", "a;rm", "../outside", "аbc", "-bad"])
def test_bad_context_not_sent_to_subprocess(context):
    with pytest.raises(BundleError, match="CONTEXT_INVALID"):
        runtime.Docker(context)


def test_redacted_cli_error(capsys):
    assert runtime.main(["install", "--unexpected-secret", "do-not-reflect"]) == 2
    captured = capsys.readouterr()
    assert captured.err == "" and "do-not-reflect" not in captured.out
    assert json.loads(captured.out)["status"] == "BLOCKED"


def test_install_without_test_acknowledgement_refused(tmp_path, capsys):
    root, pin, _ = make_bundle(tmp_path / "source")
    assert runtime.main(["install", "--bundle", str(root), "--manifest-sha256", pin]) == 2
    assert json.loads(capsys.readouterr().out)["reason"] == "EXPLICIT_TEST_AUTHORIZATION_REQUIRED"


def test_foreign_named_container_not_adopted(tmp_path):
    _, _, m = make_bundle(tmp_path / "bundle")
    class InventoryDocker:
        def run(self, *args):
            if args[:2] == ("ps", "-a"):
                return "a" * 64 + "|" + m["project"] + "-backend-1"
            if args[0] == "ps":
                return ""
            if args[0] == "inspect":
                return json.dumps([{"Config": {"Labels": {"com.docker.compose.project": "foreign"}}}])
            raise AssertionError("must refuse before any other command")
    with pytest.raises(BundleError, match="FOREIGN_CONTAINER"):
        runtime.owned_resources(InventoryDocker(), m)


def test_foreign_named_volume_not_adopted(tmp_path):
    _, _, m = make_bundle(tmp_path / "bundle")
    class InventoryDocker:
        def run(self, *args):
            if args[0] == "ps": return ""
            if args[:2] == ("volume", "ls"):
                return "" if "--filter" in args else m["project"] + "_sqlite-data"
            if args[:2] == ("volume", "inspect"):
                return json.dumps([{"Labels": {"io.izo.bundle": OWNER,
                                               "com.docker.compose.project": "foreign"}}])
            raise AssertionError("must refuse before any lifecycle command")
    with pytest.raises(BundleError, match="FOREIGN_RESOURCE"):
        runtime.owned_resources(InventoryDocker(), m)


def test_update_requires_running_previous_and_no_unfinished_jobs(tmp_path, monkeypatch):
    fake_runtime(monkeypatch)
    first, a, m = make_bundle(tmp_path / "first", "a" * 40)
    second, b, _ = make_bundle(tmp_path / "second", "b" * 40)
    state, docker = tmp_path / "state", FakeDocker()
    runtime.install(first, a, state, docker)
    with pytest.raises(BundleError, match="UPDATE_REQUIRES_RUNNING_PREVIOUS_TEST_RELEASE"):
        runtime.install(second, b, state, docker, allow_update=True)
    backend = {"Id": "a" * 64, "Image": m["images"]["backend"], "State": {"Running": True},
               "Config": {"Labels": {"com.docker.compose.service": "backend"}}}
    monkeypatch.setattr(runtime, "owned_resources", lambda d, manifest: {"containers": [backend], "volumes": [], "networks": []})
    docker.run = lambda *args: json.dumps({"schema": 7, "busy": 1})
    with pytest.raises(BundleError, match="UPDATE_TEST_DATA_NOT_QUIESCENT"):
        runtime.install(second, b, state, docker, allow_update=True)
    assert json.loads((state / "active.json").read_text())["manifest_sha256"] == a
    docker.run = lambda *args: json.dumps({"schema": 7, "busy": 0})
    assert runtime.install(second, b, state, docker, allow_update=True)["manifest_sha256"] == b


def test_install_state_inside_bundle_rejected(tmp_path):
    root, pin, _ = make_bundle(tmp_path / "source")
    docker = FakeDocker()
    with pytest.raises(BundleError, match="STATE_INSIDE_BUNDLE_FORBIDDEN"):
        runtime.install(root, pin, root / "state", docker)
    assert docker.calls == []
