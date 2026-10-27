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
    monkeypatch.setattr(runtime, "initialize_empty_test_database", lambda *args: None)
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


def test_only_first_install_bootstraps_canonical_empty_database(tmp_path, monkeypatch):
    fake_runtime(monkeypatch)
    calls = []
    monkeypatch.setattr(runtime, "initialize_empty_test_database", lambda d, r, m: calls.append(m["source_sha"]))
    root, pin, manifest = make_bundle(tmp_path / "source")
    state, docker = tmp_path / "state", FakeDocker()
    runtime.install(root, pin, state, docker)
    runtime.install(root, pin, state, docker)
    assert calls == [manifest["source_sha"]]


def test_bootstrap_is_guarded_and_uses_existing_init_db(tmp_path):
    root, _, manifest = make_bundle(tmp_path / "source")
    class BootstrapDocker:
        def __init__(self): self.calls = []
        def compose(self, directory, m, *args):
            self.calls.append(args)
            return "FRESH_TEST_SCHEMA_7_VERIFIED" if args[0] == "run" else ""
    docker = BootstrapDocker()
    runtime.initialize_empty_test_database(docker, root, manifest)
    assert docker.calls[0][0] == "up" and docker.calls[0][-1] == "guard"
    assert docker.calls[1][:4] == ("run", "--rm", "--no-deps", "-T")
    code = docker.calls[1][-1]
    assert "main.db_guard_preflight()" in code and "main.init_db()" in code
    assert "==0" in code and "==7" in code and "sqlite_master" in code
    assert "PRAGMA user_version=" not in code and "DROP TABLE" not in code


def test_wait_readiness_allows_only_transient_startup(monkeypatch, tmp_path):
    events = iter([BundleError('RUNTIME_NOT_READY'), runtime.URLError('private network detail'), {'status': 'TEST_RUNTIME_VERIFIED'}])
    sleeps = []
    def health(*args):
        event = next(events)
        if isinstance(event, Exception): raise event
        return event
    monkeypatch.setattr(runtime, 'health', health)
    monkeypatch.setattr(runtime.time, 'monotonic', lambda: 0)
    monkeypatch.setattr(runtime.time, 'sleep', sleeps.append)
    assert runtime.wait_health(FakeDocker(), tmp_path, {})['status'] == 'TEST_RUNTIME_VERIFIED'
    assert sleeps == [0.5, 0.5]


@pytest.mark.parametrize('code', ['RUNTIME_VERSION_MISMATCH', 'FOREIGN_CONTAINER', 'COMPOSE_PATH_NOT_PERSISTENT'])
def test_wait_readiness_never_retries_identity_or_ownership(code, monkeypatch, tmp_path):
    calls = []
    def health(*args):
        calls.append(True)
        raise BundleError(code)
    monkeypatch.setattr(runtime, 'health', health)
    monkeypatch.setattr(runtime.time, 'sleep', lambda value: pytest.fail('permanent error must not sleep'))
    with pytest.raises(BundleError, match=code):
        runtime.wait_health(FakeDocker(), tmp_path, {})
    assert calls == [True]


def test_wait_readiness_has_bounded_deadline(monkeypatch, tmp_path):
    clock = iter([0.0, 21.0])
    monkeypatch.setattr(runtime.time, 'monotonic', lambda: next(clock))
    monkeypatch.setattr(runtime.time, 'sleep', lambda value: pytest.fail('deadline reached'))
    def unready(*args): raise BundleError('RUNTIME_NOT_READY')
    monkeypatch.setattr(runtime, 'health', unready)
    with pytest.raises(BundleError, match='TEST_READINESS_TIMEOUT'):
        runtime.wait_health(FakeDocker(), tmp_path, {})


@pytest.mark.parametrize('status,allowed', [(502, True), (503, True), (504, True), (401, False), (404, False)])
def test_wait_http_status_policy(status, allowed, monkeypatch, tmp_path):
    from io import BytesIO
    body = BytesIO(b'private response')
    error = runtime.HTTPError('http://127.0.0.1', status, 'private detail', {}, body)
    events = iter([error, {'status': 'TEST_RUNTIME_VERIFIED'}])
    def health(*args):
        event = next(events)
        if isinstance(event, Exception): raise event
        return event
    monkeypatch.setattr(runtime, 'health', health)
    monkeypatch.setattr(runtime.time, 'monotonic', lambda: 0)
    monkeypatch.setattr(runtime.time, 'sleep', lambda value: None)
    if allowed:
        assert runtime.wait_health(FakeDocker(), tmp_path, {})['status'] == 'TEST_RUNTIME_VERIFIED'
    else:
        with pytest.raises(BundleError, match='HEALTH_HTTP_STATUS_INVALID'):
            runtime.wait_health(FakeDocker(), tmp_path, {})
    assert body.closed


def test_failure_receipt_reports_stage_and_safe_reason(tmp_path, monkeypatch):
    fake_runtime(monkeypatch)
    root, pin, _ = make_bundle(tmp_path / 'source')
    state = tmp_path / 'state'
    def bad_identity(*args): raise BundleError('RUNTIME_VERSION_MISMATCH')
    monkeypatch.setattr(runtime, 'health', bad_identity)
    with pytest.raises(BundleError, match='TEST_INSTALL_FAILED_MANUAL_RECOVERY_REQUIRED'):
        runtime.install(root, pin, state, FakeDocker())
    failure = json.loads((state / 'last-failure.json').read_text())
    assert failure['stage'] == 'readiness' and failure['reason'] == 'RUNTIME_VERSION_MISMATCH'
    assert failure['manual_recovery_required'] is True and failure['data_restored'] is False
    assert not (state / 'active.json').exists()
    assert not (state / 'operation.lock').exists()


@pytest.mark.parametrize('platform', ['nt', 'posix'])
def test_environment_key_case_matches_platform_without_leaking_credentials(platform, monkeypatch):
    from types import SimpleNamespace
    env = {'PATH': 'safe-path', 'SYSTEMROOT': 'safe-windows-root', 'SystemRoot': 'safe-mixed-root',
           'PROGRAMFILES': 'safe-programs', 'DOCKER_HOST': 'forbidden',
           'COMPOSE_FILE': 'forbidden', 'HTTPS_PROXY': 'forbidden',
           'OPENROUTER_API_KEY': 'forbidden'}
    monkeypatch.setattr(runtime, 'os', SimpleNamespace(name=platform, environ=env))
    result = runtime.clean_environment()
    assert result['PATH'] == 'safe-path'
    assert 'forbidden' not in result.values()
    if platform == 'nt':
        assert result['SYSTEMROOT'] == 'safe-windows-root'
        assert result['PROGRAMFILES'] == 'safe-programs'
    else:
        assert 'SYSTEMROOT' not in result and 'PROGRAMFILES' not in result
    assert result['SystemRoot'] == 'safe-mixed-root'


def test_windows_socket_provider_failure_is_not_a_transient_startup(monkeypatch, tmp_path):
    failure = OSError(10106, 'private system detail')
    failure.winerror = 10106
    def health(*args): raise runtime.URLError(failure)
    monkeypatch.setattr(runtime, 'health', health)
    monkeypatch.setattr(runtime.time, 'sleep', lambda value: pytest.fail('permanent environment error'))
    with pytest.raises(BundleError, match='HEALTH_NETWORK_INITIALIZATION_FAILED'):
        runtime.wait_health(FakeDocker(), tmp_path, {})
