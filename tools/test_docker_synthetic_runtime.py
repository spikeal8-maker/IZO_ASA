"""Versioned runtime policy and persistence gates; synthetic files/fake Docker only."""
from __future__ import annotations

import contextlib
import copy
import hashlib
import io
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools import docker_test_bundle as builder
from tools import docker_test_bundle_runtime as runtime
from tools.docker_test_bundle_format import (
    ACCEPTANCE, RUNTIME, UVICORN, BundleError, bundle_profile, expected_services, expected_volumes,
    file_hash, inventory, json_bytes, validate_compose, verify,
)
from tools.test_docker_test_bundle_format import make_bundle
from tools.test_docker_test_bundle_runtime import FakeDocker, fake_runtime


def repin(root, manifest, config=None):
    if config is not None:
        (root / "compose.json").write_bytes(json_bytes(config))
    manifest["files"] = inventory(root)
    (root / "bundle.json").write_bytes(json_bytes(manifest))
    return file_hash(root / "bundle.json")[1]


def make_runtime(root, sha="a" * 40):
    root, _, manifest = make_bundle(root, sha)
    manifest.update(format=2, profile=RUNTIME)
    services, volumes = {"backend", "web", "guard"}, {"sqlite-data", "media-data"}
    manifest["images"] = {role: "sha256:" + character * 64
                          for role, character in (("backend", "c"), ("web", "d"), ("guard", "e"))}
    config = json.loads((root / "compose.json").read_text())
    config["services"] = {k: v for k, v in config["services"].items() if k in services}
    config["volumes"] = {k: v for k, v in config["volumes"].items() if k in volumes}
    for service in config["services"].values():
        service["restart"] = "no"
    backend = config["services"]["backend"]
    backend.pop("command")
    backend["environment"].pop("IZO_SHADOW_FIXTURE")
    backend["environment"].update(COMFYUI_BASE_URL="http://127.0.0.1:1", EMAIL_OTP_DEBUG_RETURN_CODE="false")
    backend["volumes"] = [{"type": "volume", "source": name, "target": target}
                          for name, target in (("sqlite-data", "/home/izo/data"), ("media-data", "/home/izo/media"))]
    config = builder.persistent_config(config, manifest["project"], sha, manifest["release_id"], manifest["images"], profile=RUNTIME)
    return root, repin(root, manifest, config), manifest


def test_v2_contract_is_explicit_and_ordinary(tmp_path):
    root, pin, manifest = make_runtime(tmp_path / "runtime")
    assert verify(root, pin) == manifest and bundle_profile(manifest) == RUNTIME
    assert expected_services(manifest) == {"backend", "web", "guard"}
    assert expected_volumes(manifest) == {"sqlite-data", "media-data"}
    backend = json.loads((root / "compose.json").read_text())["services"]["backend"]
    assert backend["command"] == ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
    assert backend["environment"]["IZO_PROCESS_ROLE"] == "combined"
    assert backend["environment"]["COMFYUI_REQUIRED"] == backend["environment"]["COMFYUI_NATIVE4B_ONLY"] == "false"
    assert backend["environment"]["COMFYUI_MOCK_FALLBACK"] == "true"
    assert "IZO_SHADOW_FIXTURE" not in backend["environment"]


@pytest.mark.parametrize("version,profile", [(1, RUNTIME), (1, ACCEPTANCE), (1, "unknown"),
    (2, None), (2, ACCEPTANCE), (2, "unknown"), (True, None), (1.0, None), (2.0, RUNTIME), (3, RUNTIME)])
def test_unknown_or_ambiguous_profile_refused(tmp_path, version, profile):
    root, _, manifest = make_bundle(tmp_path / "bundle")
    manifest["format"] = version
    if profile is not None:
        manifest["profile"] = profile
    with pytest.raises(BundleError, match="BUNDLE_PROFILE_INVALID"):
        verify(root, repin(root, manifest))


@pytest.mark.parametrize("change", ["fixture", "missing-command", "server", "worker", "ipc", "socket", "required",
    "native-only", "fallback", "maintenance", "history", "credential", "live-url", "public-port", "capability",
    "readonly-data", "data-path", "web-data", "writable-assets", "host-bind", "restart", "missing-image"])
def test_runtime_dangerous_variants_rejected(tmp_path, change):
    root, _, manifest = make_runtime(tmp_path / "bundle")
    config = json.loads((root / "compose.json").read_text())
    backend, web = config["services"]["backend"], config["services"]["web"]
    env = backend["environment"]
    if change == "fixture": backend["command"] = ["python", "/opt/izo/fixtures/docker_shadow_fixture.py"]
    elif change == "missing-command": backend.pop("command")
    elif change == "server": env["IZO_PROCESS_ROLE"] = "server"
    elif change == "worker": config["services"]["worker"] = copy.deepcopy(backend)
    elif change == "ipc": config["volumes"]["worker_ipc"] = {}
    elif change == "socket": env["IZO_WORKER_SOCKET"] = "/home/izo/worker/generation.sock"
    elif change == "required": env["COMFYUI_REQUIRED"] = "true"
    elif change == "native-only": env["COMFYUI_NATIVE4B_ONLY"] = "true"
    elif change == "fallback": env["COMFYUI_MOCK_FALLBACK"] = "false"
    elif change == "maintenance": env["IZO_DISABLE_STARTUP_STORAGE_MAINTENANCE"] = "0"
    elif change == "history": env["IZO_PREPROD_PRESERVE_HISTORY"] = "0"
    elif change == "credential": env["OPENROUTER_API_KEY"] = "synthetic-forbidden"
    elif change == "live-url": env["COMFYUI_BASE_URL"] = "https://outside.invalid"
    elif change == "public-port": config["services"]["guard"]["ports"][0]["host_ip"] = "0.0.0.0"
    elif change == "capability": backend["cap_add"] = ["NET_ADMIN"]
    elif change == "readonly-data": backend["volumes"][0]["read_only"] = True
    elif change == "data-path": backend["volumes"][0]["target"] = "/different"
    elif change == "web-data": web["volumes"].append(backend["volumes"][0])
    elif change == "writable-assets": web["volumes"][0]["read_only"] = False
    elif change == "host-bind": web["volumes"][0]["source"] = "/"
    elif change == "restart": backend["restart"] = "always"
    else: manifest["images"].pop("backend")
    with pytest.raises(BundleError):
        verify(root, repin(root, manifest, config))


def test_v1_legacy_receipts_and_v2_repeat_remain_separate(tmp_path, monkeypatch):
    fake_runtime(monkeypatch)
    for name, make, profile in (("legacy", make_bundle, ACCEPTANCE), ("runtime", make_runtime, RUNTIME)):
        root, pin, manifest = make(tmp_path / name)
        state, docker = tmp_path / (name + "-state"), FakeDocker()
        first = runtime.install(root, pin, state, docker)
        owner = json.loads((state / "owner.json").read_text())
        assert owner.get("profile", ACCEPTANCE) == first.get("profile", ACCEPTANCE) == profile
        assert ("profile" in owner) is (profile == RUNTIME)
        identities = first["volumes"]
        root.rename(tmp_path / (name + "-incoming-removed"))
        second = runtime.install(state / "releases" / pin, pin, state, docker)
        assert second == first and second["volumes"] == identities
        assert len(identities) == (2 if profile == RUNTIME else 3)
        marker = docker.volumes[manifest["project"] + "-installation"]["Labels"]
        assert marker.get("io.izo.bundle.profile", ACCEPTANCE) == profile


@pytest.mark.parametrize("reverse", [False, True])
def test_profile_switch_refused_before_any_docker_call(tmp_path, monkeypatch, reverse):
    fake_runtime(monkeypatch)
    legacy = make_bundle(tmp_path / "legacy")
    ordinary = make_runtime(tmp_path / "runtime", "b" * 40)
    first, second = (ordinary, legacy) if reverse else (legacy, ordinary)
    state, docker = tmp_path / "state", FakeDocker()
    runtime.install(first[0], first[1], state, docker)
    active, owner = (state / "active.json").read_bytes(), (state / "owner.json").read_bytes()
    calls, mutations = list(docker.calls), list(docker.mutations)
    with pytest.raises(BundleError, match="INSTALLATION_PROFILE_MISMATCH"):
        runtime.install(second[0], second[1], state, docker, allow_update=True)
    assert docker.calls == calls and docker.mutations == mutations
    assert (state / "active.json").read_bytes() == active and (state / "owner.json").read_bytes() == owner


@pytest.mark.parametrize("name", ["owner.json", "active.json"])
def test_v2_profile_cannot_be_removed_from_receipt(tmp_path, monkeypatch, name):
    fake_runtime(monkeypatch)
    root, pin, _ = make_runtime(tmp_path / "runtime")
    state, docker = tmp_path / "state", FakeDocker()
    runtime.install(root, pin, state, docker)
    value = json.loads((state / name).read_text())
    value.pop("profile")
    (state / name).write_bytes(json_bytes(value))
    calls, mutations = list(docker.calls), list(docker.mutations)
    with pytest.raises(BundleError, match="INSTALLATION_PROFILE_MISMATCH"):
        runtime.install(root, pin, state, docker)
    assert docker.calls == calls and docker.mutations == mutations


@pytest.mark.parametrize("change", ["missing", "generation", "created", "engine", "copied-state"])
def test_v2_volume_and_state_identity_gates(tmp_path, monkeypatch, change):
    fake_runtime(monkeypatch)
    root, pin, manifest = make_runtime(tmp_path / "runtime")
    state, docker = tmp_path / "state", FakeDocker()
    runtime.install(root, pin, state, docker)
    volume = manifest["project"] + "_sqlite-data"
    if change == "missing": del docker.volumes[volume]
    elif change == "generation": docker.volumes[volume]["Labels"]["io.izo.bundle.generation"] = "f" * 32
    elif change == "created": docker.volumes[volume]["CreatedAt"] = "changed"
    elif change == "engine": monkeypatch.setattr(docker, "engine", lambda: "different-engine")
    else:
        copied = tmp_path / "copied"
        runtime.shutil.copytree(state, copied)
        state = copied
    mutations = list(docker.mutations)
    with pytest.raises(BundleError, match="PERSISTENT_VOLUME_|INSTALLATION_OWNER_MISMATCH"):
        runtime.install(root, pin, state, docker)
    assert docker.mutations == mutations


def test_v2_bootstrap_once_and_busy_update_preserves_active(tmp_path, monkeypatch):
    fake_runtime(monkeypatch)
    calls = []
    monkeypatch.setattr(runtime, "initialize_empty_test_database", lambda *args: calls.append("fresh"))
    first, pin, manifest = make_runtime(tmp_path / "first")
    second, next_pin, _ = make_runtime(tmp_path / "second", "b" * 40)
    state, docker = tmp_path / "state", FakeDocker()
    runtime.install(first, pin, state, docker)
    runtime.install(first, pin, state, docker)
    assert calls == ["fresh"]
    docker.containers = [{"Id": "a" * 64, "Image": manifest["images"]["backend"], "State": {"Running": True},
                          "Config": {"Labels": {"com.docker.compose.service": "backend"}}}]
    for field in ("busy", "video_deletions", "preparing_video_publications"):
        docker.proof[field] = 1
        before = (state / "active.json").read_bytes()
        up = sum(isinstance(c, tuple) and c[1][0] == "up" for c in docker.calls)
        with pytest.raises(BundleError, match="UPDATE_TEST_DATA_NOT_QUIESCENT"):
            runtime.install(second, next_pin, state, docker, allow_update=True)
        assert (state / "active.json").read_bytes() == before
        assert sum(isinstance(c, tuple) and c[1][0] == "up" for c in docker.calls) == up
        docker.proof[field] = 0
    assert runtime.install(second, next_pin, state, docker, allow_update=True)["manifest_sha256"] == next_pin
    assert calls == ["fresh"]


def test_same_code_new_runtime_release_still_requires_idle_database(tmp_path, monkeypatch):
    fake_runtime(monkeypatch)
    first, pin, manifest = make_runtime(tmp_path / "first")
    second, _, candidate = make_runtime(tmp_path / "second")
    config = json.loads((second / "compose.json").read_text())
    old_release = candidate["release_id"]
    candidate["release_id"] = candidate["source_sha"][:12] + "-20261027130001"
    config = json.loads(json.dumps(config).replace(old_release, candidate["release_id"]))
    next_pin = repin(second, candidate, config)
    assert next_pin != pin and candidate["images"] == manifest["images"]
    state, docker = tmp_path / "state", FakeDocker()
    runtime.install(first, pin, state, docker)
    docker.containers = [{"Id": "a" * 64, "Image": manifest["images"]["backend"], "State": {"Running": True},
                          "Config": {"Labels": {"com.docker.compose.service": "backend"}}}]
    docker.proof["busy"] = 1
    with pytest.raises(BundleError, match="UPDATE_TEST_DATA_NOT_QUIESCENT"):
        runtime.install(second, next_pin, state, docker)
    assert json.loads((state / "active.json").read_text())["manifest_sha256"] == pin
    docker.proof["busy"] = 0
    assert runtime.install(second, next_pin, state, docker)["manifest_sha256"] == next_pin


@pytest.mark.parametrize("status,deletion,preparing,expected", [
    ("completed", False, False, 0), ("failed", False, False, 0), ("cancelled", False, False, 0),
    (None, False, False, 1), ("unknown-future-status", False, False, 1), ("queued", False, False, 1),
    ("completed", True, False, 1), ("completed", False, True, 1)])
def test_real_sqlite_quiescence_code_fails_closed(tmp_path, status, deletion, preparing, expected):
    path = tmp_path / "synthetic.sqlite3"
    with sqlite3.connect(path) as db:
        db.executescript("CREATE TABLE jobs(status TEXT); CREATE TABLE video_file_deletions(id INTEGER); "
                         "CREATE TABLE feed_publications(media_type TEXT,status TEXT); PRAGMA user_version=7;")
        db.execute("INSERT INTO jobs VALUES(?)", (status,))
        if deletion: db.execute("INSERT INTO video_file_deletions VALUES(1)")
        if preparing: db.execute("INSERT INTO feed_publications VALUES('video','preparing')")
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        exec(runtime.QUIESCENCE_CODE.replace("file:/home/izo/data/app.sqlite3?mode=ro", path.as_uri() + "?mode=ro"), {})
    proof = json.loads(output.getvalue())
    assert proof["schema"] == 7
    assert sum(proof[key] for key in ("busy", "video_deletions", "preparing_video_publications")) == expected
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


def test_v2_health_checks_current_guard_namespace(tmp_path, monkeypatch):
    root, _, manifest = make_runtime(tmp_path / "runtime")
    rows = [{"Id": role + "-id", "Image": manifest["images"][role],
             "State": {"Running": True, "Health": {"Status": "healthy"}},
             "Config": {"Cmd": list(UVICORN) if role == "backend" else [], "Labels": {
                 "com.docker.compose.service": role, "com.docker.compose.project.config_files": str(root / "compose.json")}},
             "HostConfig": {"NetworkMode": "container:guard-id"}} for role in ("backend", "web", "guard")]
    monkeypatch.setattr(runtime, "owned_resources", lambda *args: {"containers": rows})
    origin = "http://127.0.0.1:" + str(manifest["ports"]["web"]) + "/api/version"
    version = {"backend_commit": manifest["source_sha"], "release_id": manifest["release_id"],
               "frontend_build": manifest["release_id"], "schema_compatibility": {"min_version": 7, "max_version": 7}}
    response = SimpleNamespace(geturl=lambda: origin, read=lambda limit: json_bytes(version))
    monkeypatch.setattr(runtime, "build_opener", lambda *args: SimpleNamespace(open=lambda *args, **kwargs: contextlib.nullcontext(response)))
    assert runtime.health(None, root, manifest)["profile"] == RUNTIME
    rows[2]["Id"] = "new-guard-id"
    with pytest.raises(BundleError, match="RUNTIME_GUARD_NAMESPACE_CHANGED"):
        runtime.health(None, root, manifest)
    for item in rows[:2]: item["HostConfig"]["NetworkMode"] = "container:new-guard-id"
    assert runtime.health(None, root, manifest)["containers"] == 3
    rows[0]["Config"]["Cmd"] = ["python", "/opt/izo/fixtures/docker_shadow_fixture.py"]
    with pytest.raises(BundleError, match="RUNTIME_IMAGE_COMMAND_INVALID"):
        runtime.health(None, root, manifest)


@pytest.mark.parametrize("bad", ["command", "entrypoint"])
def test_runtime_image_default_cannot_hide_fixture(tmp_path, bad):
    root, _, manifest = make_runtime(tmp_path / "runtime")
    class Images:
        def run(self, *args, **kwargs):
            image = args[-1]
            config = {"Labels": {"org.opencontainers.image.revision": manifest["source_sha"],
                                 "org.opencontainers.image.source": manifest["repository"]}, "Cmd": list(UVICORN)}
            if image == manifest["images"]["backend"]:
                config["Cmd" if bad == "command" else "Entrypoint"] = ["fixture"]
            return json.dumps([{"Id": image, "Os": "linux", "Config": config}])
    with pytest.raises(BundleError, match="RUNTIME_IMAGE_COMMAND_INVALID"):
        runtime.ensure_images(Images(), root, manifest)


@pytest.mark.parametrize("shared", [True, False])
def test_v2_actual_volume_consumers_cannot_cross_namespace(tmp_path, shared):
    _, _, manifest = make_runtime(tmp_path / "runtime")
    project = manifest["project"]
    backend = {"Id": "a" * 64, "Config": {"Labels": {"io.izo.bundle": runtime.OWNER,
               "com.docker.compose.project": project, "com.docker.compose.service": "backend"}}}
    class Inventory:
        def run(self, *args):
            if args[:2] == ("ps", "-a"): return "a" * 64 + "|" + project + "-backend-1\n" + "f" * 64 + "|foreign"
            if args[0] == "ps": return "a" * 64
            if args[:2] == ("inspect", "--format"):
                assert "Env" not in args[2] and "Source" not in args[2]
                own = "a" * 64 + "|" + project + "_sqlite-data|" + project + "_media-data"
                return own + "\n" + "f" * 64 + "|" + project + "_sqlite-data" if shared else "a" * 64 + "|foreign-data"
            if args[0] == "inspect": return json.dumps([backend])
            raise AssertionError("Must refuse before subsequent resource operations")
    with pytest.raises(BundleError, match="SHARED_DATA_VOLUME" if shared else "RUNTIME_DATA_MOUNTS_CHANGED"):
        runtime.owned_resources(Inventory(), manifest)
