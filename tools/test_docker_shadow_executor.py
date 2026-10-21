from __future__ import annotations

import copy
import hashlib
import json
import socket
from unittest.mock import Mock

import pytest

from tools import docker_shadow_executor as module
from tools.docker_shadow_executor import ExecutorError, GatewayListener, IsolatedExecutor, compare_isolated

MACHINE = "a" * 64
ENGINE = "01234567-89ab-cdef-0123-456789abcdef"
PROJECT = "izo-asa-shadow-adapter-test"


def context():
    return [{"Name": "isolated-test", "Endpoints": {"docker": {"Host": "unix:///var/run/docker.sock"}}}]


def info():
    return {"ID": ENGINE, "OSType": "linux"}


def executor(monkeypatch, *, context_value=None, info_value=None):
    monkeypatch.setattr(module, "guest_identity", lambda: MACHINE)
    calls = []
    def run(args, **kwargs):
        calls.append((args, kwargs))
        if args[3:5] == ["context", "inspect"]:
            return json.dumps(context() if context_value is None else context_value)
        if args[3] == "info":
            return json.dumps(info() if info_value is None else info_value)
        return "fixture-output"
    value = IsolatedExecutor(run, context="isolated-test", engine_id=ENGINE, machine_sha256=MACHINE)
    return value, calls


@pytest.mark.parametrize("field,value", [("context", "../default"), ("context", "--help"),
    ("engine_id", "latest"), ("engine_id", ""), ("engine_id", "secret\nvalue"),
    ("machine_sha256", "main"), ("machine_sha256", "A" * 64)])
def test_invalid_explicit_identity_fails_without_commands(field, value):
    run = Mock()
    settings = dict(context="isolated-test", engine_id=ENGINE, machine_sha256=MACHINE)
    settings[field] = value
    with pytest.raises(ExecutorError):
        IsolatedExecutor(run, **settings)
    run.assert_not_called()


def test_guest_mismatch_fails_before_any_docker_command(monkeypatch):
    value, calls = executor(monkeypatch)
    monkeypatch.setattr(module, "guest_identity", lambda: "b" * 64)
    with pytest.raises(ExecutorError, match="EXECUTOR_GUEST_CHANGED"):
        value.docker("compose", "up")
    assert calls == []


@pytest.mark.parametrize("endpoint", ["tcp://127.0.0.1:2375", "ssh://isolated", "npipe:////./pipe/dockerDesktopLinuxEngine", "unix:///tmp/docker.sock"])
def test_other_endpoint_never_runs_requested_operation(monkeypatch, endpoint):
    meta = context()
    meta[0]["Endpoints"]["docker"]["Host"] = endpoint
    value, calls = executor(monkeypatch, context_value=meta)
    with pytest.raises(ExecutorError, match="EXECUTOR_LOCAL_UNIX_SOCKET_REQUIRED"):
        value.docker("compose", "down")
    assert len(calls) == 1 and calls[0][0][3] == "context"


@pytest.mark.parametrize("metadata", [{"ID": "different-engine", "OSType": "linux"},
    {"ID": ENGINE, "OSType": "windows"}, {}, None, []])
def test_wrong_engine_or_metadata_never_runs_lifecycle(monkeypatch, metadata):
    value, calls = executor(monkeypatch, info_value=metadata if metadata is not None else "invalid")
    with pytest.raises(ExecutorError):
        value.docker("compose", "up")
    assert all("compose" not in args for args, _ in calls)


def test_every_requested_command_rechecks_machine_context_engine(monkeypatch):
    value, calls = executor(monkeypatch)
    assert value.docker("compose", "up", timeout=20) == "fixture-output"
    assert value.docker("compose", "down") == "fixture-output"
    assert [args[3] for args, _ in calls] == ["context", "info", "compose"] * 2
    assert calls[2][1] == {"timeout": 20}
    # A changed daemon is rejected before the next requested command.
    value.run = Mock(side_effect=[json.dumps(context()), json.dumps({"ID": "new-engine", "OSType": "linux"})])
    with pytest.raises(ExecutorError):
        value.docker("compose", "up")
    assert value.run.call_count == 2


def network():
    return [{"Name": PROJECT + "_shadow", "Driver": "bridge", "Labels": {
        "io.izo.owner": module.OWNER, "com.docker.compose.project": PROJECT},
        "IPAM": {"Config": [{"Gateway": "172.28.0.1", "Subnet": "172.28.0.0/16"}]}}]


def test_gateway_requires_matching_owned_network(monkeypatch):
    value, _ = executor(monkeypatch)
    value.run = Mock(side_effect=[json.dumps(context()), json.dumps(info())] * 2 + [json.dumps(network())])
    assert value.gateway(PROJECT) == "172.28.0.1"


@pytest.mark.parametrize("change", ["owner", "project", "driver", "public", "outside-subnet", "loopback", "ambiguous"])
def test_unsafe_gateway_metadata_rejected_before_listener(monkeypatch, change):
    entry = network()
    item = entry[0]
    if change == "owner": item["Labels"]["io.izo.owner"] = "foreign"
    if change == "project": item["Labels"]["com.docker.compose.project"] = "asa-lab"
    if change == "driver": item["Driver"] = "host"
    if change == "public": item["IPAM"]["Config"] = [{"Gateway": "1.1.1.1", "Subnet": "1.1.1.0/24"}]
    if change == "outside-subnet": item["IPAM"]["Config"][0]["Gateway"] = "172.29.0.1"
    if change == "loopback": item["IPAM"]["Config"] = [{"Gateway": "127.0.0.1", "Subnet": "127.0.0.0/8"}]
    if change == "ambiguous": item["IPAM"]["Config"] *= 2
    value, _ = executor(monkeypatch)
    value.run = Mock(side_effect=[json.dumps(context()), json.dumps(info())] * 2 + [json.dumps(entry)])
    with pytest.raises(ExecutorError):
        with GatewayListener(value, PROJECT):
            pytest.fail("unsafe listener started")


def assert_listener_closed(listener):
    assert not listener.thread.is_alive()
    with pytest.raises(OSError):
        socket.create_connection((listener.address, listener.port), timeout=.3)
    with socket.socket() as probe:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        else:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        probe.bind((listener.address, listener.port))


@pytest.mark.parametrize("fail", [False, True])
def test_owned_native_listener_positive_control_and_cleanup_even_exception(fail):
    # Only this test's loopback listener is created; no Docker/guest/network operations.
    value = Mock()
    value.gateway.return_value = "127.0.0.1"
    listener = GatewayListener(value, PROJECT)
    try:
        with listener:
            with socket.create_connection((listener.address, listener.port), timeout=.3) as client:
                assert client.recv(64) == b"shadow-fixture"
            assert listener.accepted == 1
            if fail:
                raise ValueError("test-exception")
    except ValueError:
        assert fail
    assert_listener_closed(listener)
    listener.close()
    value.gateway.assert_called_once_with(PROJECT)


def test_listener_expires_without_waiting_for_caller():
    value = Mock()
    value.gateway.return_value = "127.0.0.1"
    with GatewayListener(value, PROJECT, seconds=.1) as listener:
        listener.thread.join(timeout=1)
        assert not listener.thread.is_alive()
    assert_listener_closed(listener)


def test_live_listener_cannot_be_displaced_by_reuse_socket():
    value = Mock()
    value.gateway.return_value = "127.0.0.1"
    with GatewayListener(value, PROJECT) as listener:
        with socket.socket() as contender:
            contender.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            with pytest.raises(OSError):
                contender.bind((listener.address, listener.port))
        with socket.create_connection((listener.address, listener.port), timeout=.3) as client:
            assert client.recv(64) == b"shadow-fixture"
    assert_listener_closed(listener)


def snapshot():
    return {"scope": "ISOLATED_GUEST_ONLY", "identity": {"engineId": ENGINE,
        "context": "isolated-test", "machineIdentitySha256": MACHINE},
        "foreignResources": {"container": [], "volume": [], "network": []}}


def test_snapshot_comparison_never_claims_production_evidence():
    before = snapshot()
    assert compare_isolated(before, copy.deepcopy(before))["status"] == "PASS"
    after = copy.deepcopy(before)
    after["foreignResources"]["volume"].append({"id": "foreign", "name": "foreign"})
    assert compare_isolated(before, after)["status"] == "FAIL"
    assert compare_isolated(before, before)["productionUnchanged"] == "NOT_VERIFIED_HERE"
    with pytest.raises(ExecutorError):
        compare_isolated({"scope": "ISOLATED_GUEST_ONLY", "identity": {}, "foreignResources": {}}, before)


def test_foreign_inventory_excludes_only_this_project_and_never_exposes_config(monkeypatch):
    value, _ = executor(monkeypatch)
    foreign = {"Id": "a" * 64, "Name": "other", "Image": "sha256:" + "a" * 64,
        "Config": {"Env": ["SECRET=must-not-appear"], "Labels": {"io.izo.owner": module.OWNER,
            "com.docker.compose.project": "izo-asa-shadow-other"}},
        "State": {"StartedAt": "timestamp", "Running": True, "Pid": 43}}
    own = copy.deepcopy(foreign)
    own["Id"], own["Name"] = "b" * 64, "own"
    own["Config"]["Labels"]["com.docker.compose.project"] = PROJECT
    def run(args, **kwargs):
        tail = args[3:]
        if tail[0] == "context": return json.dumps(context())
        if tail[0] == "info": return json.dumps(info())
        if tail == ["ps", "-aq", "--no-trunc"]: return foreign["Id"] + "\n" + own["Id"]
        if tail[0] == "inspect": return json.dumps([foreign, own])
        if "ls" in tail: return ""
        pytest.fail("unexpected command")
    value.run = run
    observed = value.foreign_snapshot(PROJECT)
    assert len(observed["foreignResources"]["container"]) == 1
    assert observed["foreignResources"]["container"][0]["id"] == foreign["Id"]
    assert "SECRET" not in json.dumps(observed) and "must-not-appear" not in json.dumps(observed)
    assert compare_isolated(observed, observed)["productionUnchanged"] == "NOT_VERIFIED_HERE"


def test_machine_identity_requires_linux_and_reads_only_bounded_content(monkeypatch, tmp_path):
    monkeypatch.setattr(module.platform, "system", lambda: "Windows")
    with pytest.raises(ExecutorError, match="LINUX_GUEST_REQUIRED"):
        module.guest_identity()
    path = tmp_path / "own-machine-id"
    path.write_text("b" * 32 + "\n", encoding="ascii")
    monkeypatch.setattr(module.platform, "system", lambda: "Linux")
    monkeypatch.setattr(module, "Path", lambda _: path)
    assert module.guest_identity() == hashlib.sha256(("b" * 32).encode()).hexdigest()
    path.write_text("b" * 1000, encoding="ascii")
    with pytest.raises(ExecutorError, match="GUEST_ID_INVALID"):
        module.guest_identity()
    path.unlink()  # No open test handle remains on Windows.
    with pytest.raises(ExecutorError, match="GUEST_ID_UNAVAILABLE"):
        module.guest_identity()


def test_command_and_malformed_json_failures_publish_no_sensitive_details(monkeypatch):
    value, calls = executor(monkeypatch)
    value.run = Mock(side_effect=OSError(13, "secret-content C:/private/path"))
    with pytest.raises(ExecutorError) as observed:
        value.docker("compose", "up")
    assert str(observed.value) == "EXECUTOR_COMMAND_FAILED"
    value.run = Mock(return_value="secret-content invalid-json")
    with pytest.raises(ExecutorError) as observed:
        value.docker("compose", "up")
    assert str(observed.value) == "EXECUTOR_METADATA_INVALID"
    assert "secret" not in str(observed.value)


@pytest.mark.parametrize("args", [("--context", "other", "compose", "up"), ("--host=tcp://other", "ps"),
    ("ps", "--context=other"), ("compose", "-cother", "up"), ("run", "--host", "other", "image"),
    ("exec", "--config", "private", "container", "python"), ("run", "--unknown", "image")])
def test_requested_routing_overrides_fail_before_any_command(monkeypatch, args):
    value, calls = executor(monkeypatch)
    with pytest.raises(ExecutorError):
        value.docker(*args)
    assert calls == []


@pytest.mark.parametrize("args", [("exec", "--user", "10001:10001", "container", "python", "-c", "print('fixture')"),
    ("run", "--rm", "--network", PROJECT + "_shadow", "--memory=64m", "image", "python", "-c", "print('fixture')")])
def test_container_payload_python_flags_remain_opaque(monkeypatch, args):
    value, calls = executor(monkeypatch)
    assert value.docker(*args) == "fixture-output"
    assert calls[-1][0][3:] == list(args)


@pytest.mark.parametrize("bad", [{}, None, "invalid", {"id": "volume", "name": "volume", "Config": "private"}])
def test_identical_malformed_resource_rows_cannot_pass(bad):
    value = snapshot()
    value["foreignResources"]["volume"] = [bad]
    with pytest.raises(ExecutorError):
        compare_isolated(value, copy.deepcopy(value))


def test_inventory_inspect_must_cover_exact_requested_ids(monkeypatch):
    value, _ = executor(monkeypatch)
    def run(args, **kwargs):
        tail = args[3:]
        if tail[0] == "context": return json.dumps(context())
        if tail[0] == "info": return json.dumps(info())
        if tail == ["ps", "-aq", "--no-trunc"]: return "requested-foreign"
        if tail[0] == "inspect": return json.dumps([{"Id": "different", "Name": "different"}])
        pytest.fail("unexpected command")
    value.run = run
    with pytest.raises(ExecutorError, match="INSPECTION_ID_MISMATCH"):
        value.foreign_snapshot(PROJECT)


def test_duplicate_snapshot_ids_and_invalid_identity_fail_closed():
    value = snapshot()
    value["foreignResources"]["volume"] = [{"id": "volume", "name": "volume"}] * 2
    with pytest.raises(ExecutorError, match="DUPLICATE_SNAPSHOT_ID"):
        compare_isolated(value, value)
    value = snapshot()
    value["identity"]["machineIdentitySha256"] = "UNKNOWN"
    with pytest.raises(ExecutorError, match="SNAPSHOTS_INCOMPLETE"):
        compare_isolated(value, value)
