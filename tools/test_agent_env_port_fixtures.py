"""Regression tests for synthetic fixture preparation, not runtime port fallback."""
from __future__ import annotations

import errno
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools import agent_env_test_ports as ports
from tools.agent_system.env import derive_candidate_ports


class SocketWorld:
    def __init__(self, failure=None):
        self.failure = failure
        self.sockets = []
        self.events = []
        self.listen_snapshots = []

    def socket(self, family, kind):
        assert (family, kind) == (ports.socket.AF_INET, ports.socket.SOCK_STREAM)
        listener = TrackedSocket(self)
        self.sockets.append(listener)
        return listener

    def check(self, phase, port):
        self.events.append((phase, port))
        if self.failure is not None:
            self.failure(phase, port)

    def open_ports(self):
        return {item.port for item in self.sockets if item.port is not None and not item.closed}


class TrackedSocket:
    def __init__(self, world):
        self.world = world
        self.port = None
        self.closed = False
        self.options = []

    def setsockopt(self, level, option, value):
        self.options.append((level, option, value))
        self.world.check("option", None)

    def bind(self, address):
        host, port = address
        assert host == "127.0.0.1"
        self.world.check("bind", port)
        self.port = port

    def listen(self, backlog):
        assert backlog > 0
        self.world.check("listen", self.port)
        self.world.listen_snapshots.append(self.world.open_ports())

    def close(self):
        self.closed = True


def install_world(monkeypatch, failure=None):
    world = SocketWorld(failure)
    monkeypatch.setattr(ports.socket, "socket", world.socket)
    monkeypatch.setattr(ports.socket, "SO_EXCLUSIVEADDRUSE", 65530, raising=False)
    monkeypatch.setattr(ports.uuid, "uuid4", lambda: SimpleNamespace(hex="a" * 32))
    return world


def candidate_pairs(monkeypatch, pairs):
    calls = []

    def derive(package_id):
        calls.append(package_id)
        backend, frontend = pairs[int(package_id.rsplit("-", 1)[1])]
        return {"backend": backend, "frontend": frontend}

    monkeypatch.setattr(ports, "derive_candidate_ports", derive)
    return calls


def test_selected_identity_keeps_real_allocator_and_exclusive_pair_probe(monkeypatch):
    world = install_world(monkeypatch)
    selected = ports.available_package_id("PKG-PORT-PROOF")
    actual = derive_candidate_ports(selected)
    assert selected.startswith("PKG-PORT-PROOF-" + "A" * 20 + "-")
    assert max(actual.values()) < 49152
    assert [item.port for item in world.sockets] == list(actual.values())
    assert world.listen_snapshots[-1] == set(actual.values())
    assert all(item.closed for item in world.sockets)
    expected_option = (ports.socket.SOL_SOCKET, ports.socket.SO_EXCLUSIVEADDRUSE, 1)
    assert all(item.options == [expected_option] for item in world.sockets)
    assert not any(option == ports.socket.SO_REUSEADDR for item in world.sockets
                   for _level, option, _value in item.options)


@pytest.mark.parametrize("role", ("backend", "frontend"))
@pytest.mark.parametrize("phase", ("bind", "listen"))
def test_occupied_candidate_is_rejected_before_selecting_next_pair(monkeypatch, role, phase):
    failed_port = 21000 if role == "backend" else 21001

    def fail(operation, port):
        if (operation, port) == (phase, failed_port):
            raise OSError(errno.EADDRINUSE, "synthetic occupied fixture")
        if (operation, port) == ("bind", 21002):
            assert not world.open_ports(), "previous partial pair was not closed"

    world = install_world(monkeypatch, fail)
    calls = candidate_pairs(monkeypatch, [(21000, 21001), (21002, 21003)])
    selected = ports.available_package_id("PKG-OCCUPIED", max_candidates=2)
    assert selected == calls[1]
    assert len(calls) == 2
    assert world.listen_snapshots[-1] == {21002, 21003}
    assert all(item.closed for item in world.sockets)
    assert not world.open_ports()


def test_dynamic_band_and_excluded_pair_are_skipped_without_opening_sockets(monkeypatch):
    world = install_world(monkeypatch)
    calls = candidate_pairs(monkeypatch, [(49152, 49153), (21000, 21001), (49150, 49151)])
    selected = ports.available_package_id("PKG-BOUNDS", excluded_ports={21001}, max_candidates=3)
    assert selected == calls[2]
    assert [item.port for item in world.sockets] == [49150, 49151]
    assert all(item.closed for item in world.sockets)


@pytest.mark.parametrize("native_errno", (errno.EADDRINUSE, errno.EACCES))
def test_candidate_exhaustion_is_bounded_failure_and_closes_failed_socket(monkeypatch, native_errno):
    def fail(operation, _port):
        if operation == "bind":
            raise OSError(native_errno, "synthetic unavailable fixture")

    world = install_world(monkeypatch, fail)
    calls = candidate_pairs(monkeypatch, [(21000, 21001), (21002, 21003), (21004, 21005)])
    with pytest.raises(RuntimeError, match="within candidate limit"):
        ports.available_package_id("PKG-EXHAUST", max_candidates=3)
    assert len(calls) == len(world.sockets) == 3
    assert all(item.closed for item in world.sockets)


@pytest.mark.parametrize("limit", (0, -1, 257))
def test_candidate_limit_cannot_be_disabled_or_expanded(monkeypatch, limit):
    world = install_world(monkeypatch)
    calls = candidate_pairs(monkeypatch, [])
    with pytest.raises(ValueError, match="candidate limit"):
        ports.available_package_id("PKG-LIMIT", max_candidates=limit)
    assert not calls and not world.sockets


@pytest.mark.parametrize("prefix", ("PKG-VALID-PREFIX-BUT-invalid", "A" * 81))
def test_compaction_does_not_hide_invalid_original_prefix(monkeypatch, prefix):
    world = install_world(monkeypatch)
    calls = candidate_pairs(monkeypatch, [])
    with pytest.raises(ValueError, match="synthetic package prefix"):
        ports.available_package_id(prefix)
    assert not calls and not world.sockets


def test_default_limit_is_finite_even_when_every_candidate_is_outside_band(monkeypatch):
    world = install_world(monkeypatch)
    calls = candidate_pairs(monkeypatch, [(50000, 50001)] * 256)
    with pytest.raises(RuntimeError, match="within candidate limit"):
        ports.available_package_id("PKG-HIGH")
    assert len(calls) == 256
    assert not world.sockets


def test_each_selection_uses_fresh_namespace_for_same_test_prefix(monkeypatch):
    world = install_world(monkeypatch)
    namespaces = iter(("a" * 32, "b" * 32))
    monkeypatch.setattr(ports.uuid, "uuid4", lambda: SimpleNamespace(hex=next(namespaces)))
    candidate_pairs(monkeypatch, [(21000, 21001)])
    first = ports.available_package_id("PKG-WORKER")
    second = ports.available_package_id("PKG-WORKER")
    assert first == "PKG-WORKER-" + "A" * 20 + "-0"
    assert second == "PKG-WORKER-" + "B" * 20 + "-0"
    assert all(item.closed for item in world.sockets)


def test_two_prepared_packages_have_disjoint_pairs_before_either_is_started(monkeypatch):
    world = install_world(monkeypatch)
    candidate_pairs(monkeypatch, [(21000, 21001), (21002, 21003)])
    first = ports.available_package_id("PKG-FIRST")
    first_ports = ports.derive_candidate_ports(first)
    second = ports.available_package_id("PKG-SECOND", excluded_ports=first_ports.values())
    second_ports = ports.derive_candidate_ports(second)
    assert set(first_ports.values()).isdisjoint(second_ports.values())
    assert all(item.closed for item in world.sockets)


def test_option_failure_closes_socket_and_selection_fails_explicitly(monkeypatch):
    def fail(operation, _port):
        if operation == "option":
            raise OSError(errno.EACCES, "synthetic option failure")

    world = install_world(monkeypatch, fail)
    candidate_pairs(monkeypatch, [(21000, 21001)])
    with pytest.raises(RuntimeError, match="within candidate limit"):
        ports.available_package_id("PKG-OPTION", max_candidates=1)
    assert len(world.sockets) == 1 and world.sockets[0].closed


def test_unexpected_probe_error_propagates_without_trying_another_candidate(monkeypatch):
    def fail(operation, _port):
        if operation == "bind":
            raise RuntimeError("synthetic programming error")

    world = install_world(monkeypatch, fail)
    calls = candidate_pairs(monkeypatch, [(21000, 21001), (21002, 21003)])
    with pytest.raises(RuntimeError, match="synthetic programming error"):
        ports.available_package_id("PKG-BUG", max_candidates=2)
    assert len(calls) == 1
    assert world.sockets[0].closed


def test_lifecycle_prepares_identity_once_and_propagates_actual_start_failure(tmp_path, monkeypatch):
    from tools import test_agent_env_lifecycle as lifecycle_tests

    events = []
    selected = "PKG-PREPARED-IDENTITY"
    contract = object()

    def choose(prefix):
        events.append(("choose", prefix))
        return selected

    def fixture(path, package_id):
        events.append(("fixture", package_id))
        assert path == tmp_path
        return tmp_path, contract

    def start(path, *, environment, production_contract):
        events.append(("start", path))
        assert environment == {} and production_contract is contract
        raise lifecycle_tests.lifecycle.EnvironmentLifecycleError("PORT_IN_USE")

    monkeypatch.setattr(lifecycle_tests, "_available_package_id", choose)
    monkeypatch.setattr(lifecycle_tests, "_single", fixture)
    monkeypatch.setattr(lifecycle_tests.lifecycle, "env_up", start)
    monkeypatch.setattr(lifecycle_tests, "_cleanup", lambda *_: events.append(("cleanup", None)))
    with pytest.raises(lifecycle_tests.lifecycle.EnvironmentLifecycleError, match="PORT_IN_USE"):
        lifecycle_tests.test_env_up_status_idempotent_down_and_cleanup(tmp_path)
    assert events == [("choose", "PKG-LIFE"), ("fixture", selected),
                      ("start", tmp_path), ("cleanup", None)]


def test_longest_fixture_identity_supports_native_atomic_diagnostic_paths(tmp_path, monkeypatch):
    from tools import test_agent_env_lifecycle as lifecycle_tests
    from tools.agent_system import registry

    install_world(monkeypatch)
    prefix = "PKG-RUNTIME-CREDENTIAL-CONVERGENCE"

    def last_candidate(package_id):
        if not package_id.endswith("-255"):
            return {"backend": 50000, "frontend": 50001}
        return derive_candidate_ports(package_id)

    monkeypatch.setattr(ports, "derive_candidate_ports", last_candidate)
    selected = ports.available_package_id(prefix)
    assert selected == prefix[:16] + "-" + "A" * 20 + "-255"
    assert len(selected) <= 41
    worktree, _contract = lifecycle_tests._single(tmp_path, selected)
    identity = lifecycle_tests.load_environment_identity(worktree)
    assert identity.package_id == selected
    paths = lifecycle_tests.derive_environment_paths(identity)
    startup = paths.state_root / ("lease-startup-" + "b" * 32 + ".json")
    diagnostic = lifecycle_tests.lifecycle._startup_diagnostic_path(startup)
    temporary_paths = []
    original = registry.tempfile.mkstemp

    def capture_temp(*args, **kwargs):
        descriptor, path = original(*args, **kwargs)
        temporary_paths.append(Path(path))
        return descriptor, path

    monkeypatch.setattr(registry.tempfile, "mkstemp", capture_temp)
    lifecycle_tests.lifecycle._write_startup_diagnostic(diagnostic, "HOLDER_ENTERED", os.getpid())
    assert lifecycle_tests.lifecycle._read_startup_diagnostic(diagnostic) == ("HOLDER_ENTERED", os.getpid())
    assert len(temporary_paths) == 1 and not temporary_paths[0].exists()
    if os.name == "nt":
        assert len(str(diagnostic)) < 248
        assert len(str(temporary_paths[0])) < 260


def test_concurrent_fixture_cleans_first_holder_when_second_start_fails(tmp_path, monkeypatch):
    from tools import test_agent_env_lifecycle as lifecycle_tests

    events = []
    package_ids = iter(("PKG-PREPARED-A", "PKG-PREPARED-B"))
    contract = object()
    monkeypatch.setattr(lifecycle_tests, "_make_control_repo", lambda _path: (tmp_path, "0" * 40))
    monkeypatch.setattr(lifecycle_tests, "_add_package", lambda _root, _base, _id, path: path)
    monkeypatch.setattr(lifecycle_tests, "_contract", lambda _path: contract)
    monkeypatch.setattr(lifecycle_tests, "_available_package_id", lambda *_args, **_kwargs: next(package_ids))

    def start(path, *, environment, production_contract):
        events.append(("start", path.name))
        assert environment == {} and production_contract is contract
        if path.name == "b":
            raise lifecycle_tests.lifecycle.EnvironmentLifecycleError("PORT_IN_USE")
        return {}

    monkeypatch.setattr(lifecycle_tests.lifecycle, "env_up", start)
    monkeypatch.setattr(lifecycle_tests, "_cleanup", lambda path, _contract: events.append(("cleanup", path.name)))
    with pytest.raises(lifecycle_tests.lifecycle.EnvironmentLifecycleError, match="PORT_IN_USE"):
        lifecycle_tests.test_two_packages_run_concurrently_and_down_is_isolated(tmp_path)
    assert events == [("start", "a"), ("start", "b"), ("cleanup", "a"), ("cleanup", "b")]
