from __future__ import annotations
import ctypes
import json
import os
import signal
import socket
import threading
import time
from dataclasses import replace
from pathlib import Path

import pytest

from tools.agent_system import env_lifecycle as lifecycle
from tools.agent_system.env import (
    CONTRACT_ID,
    build_environment_plan,
    derive_candidate_ports,
    derive_environment_paths,
    load_environment_identity,
)
from tools.test_agent_env import _add_package, _known_contract, _make_control_repo

TIMEOUT = 5.0


def _contract(tmp_path: Path):
    known = _known_contract(tmp_path)
    return replace(known, status="UNKNOWN", media_status="UNKNOWN", media_roots=())


def _single(tmp_path: Path, package_id: str = "PKG-LIFE"):
    control, base = _make_control_repo(tmp_path)
    worktree = _add_package(control, base, package_id, tmp_path / package_id.lower())
    return worktree, _contract(tmp_path)


def _wait(predicate, timeout: float = TIMEOUT) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def _terminate_owned_test_holder(pid: int) -> None:
    if os.name == "nt":
        handle = ctypes.windll.kernel32.OpenProcess(0x0001, False, pid)
        if not handle:
            raise RuntimeError("test holder process is unavailable")
        try:
            if not ctypes.windll.kernel32.TerminateProcess(handle, 73):
                raise RuntimeError("test holder termination failed")
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    else:
        os.kill(pid, signal.SIGTERM)
    assert _wait(lambda: not lifecycle._pid_alive(pid))


def _listener(port: int):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    sock.bind((lifecycle.LOOPBACK, port))
    sock.listen(8)
    sock.settimeout(0.2)
    stop = threading.Event()

    def serve() -> None:
        while not stop.is_set():
            try:
                conn, _ = sock.accept()
            except (OSError, socket.timeout):
                continue
            with conn:
                try:
                    conn.recv(512)
                    conn.sendall(b"FOREIGN\n")
                except OSError:
                    pass

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    return sock, stop, thread


def _close_listener(sock, stop, thread) -> None:
    stop.set()
    sock.close()
    thread.join(timeout=1)


def _can_bind(port: int) -> bool:
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    try:
        probe.bind((lifecycle.LOOPBACK, port))
        return True
    except OSError:
        return False
    finally:
        probe.close()


def _cleanup(worktree: Path, contract) -> None:
    try:
        status = lifecycle.environment_status(worktree)["status"]
        if status == "ACTIVE":
            lifecycle.env_down(worktree, production_contract=contract)
        elif status == "STALE":
            lifecycle.env_down(
                worktree, recover_stale=True, production_contract=contract
            )
    except Exception:
        pass


def test_env_up_status_idempotent_down_and_cleanup(tmp_path: Path) -> None:
    worktree, contract = _single(tmp_path)
    try:
        first = lifecycle.env_up(
            worktree, environment={}, production_contract=contract
        )
        assert first["status"] == "ACTIVE"
        assert lifecycle.environment_status(worktree)["status"] == "ACTIVE"
        second = lifecycle.env_up(
            worktree, environment={}, production_contract=contract
        )
        assert second["result"] == "ALREADY_ACTIVE"
        assert second["pid"] == first["pid"]
        assert second["ports"] == first["ports"]

        identity = load_environment_identity(worktree)
        paths = derive_environment_paths(identity)
        state = json.loads(paths.environment_state_path.read_text(encoding="utf-8"))
        assert state["state"] == "active"
        assert state["ports"]["reserved"] is True
        assert state["portLease"]["pid"] == first["pid"]
        assert state["databaseInitialization"] == "NOT_STARTED"

        down = lifecycle.env_down(worktree, production_contract=contract)
        assert down == {"status": "STOPPED", "cleanup": "PASS"}
        assert lifecycle.environment_status(worktree)["status"] == "STOPPED"
        assert not (paths.environment_root / "db").exists()
        assert not paths.media_root.exists()
        assert not paths.secret_root.exists()
        assert paths.environment_state_path.is_file()
        assert paths.receipt_path.is_file()
        stopped = json.loads(paths.receipt_path.read_text(encoding="utf-8"))
        assert stopped["state"] == "stopped"
        assert stopped["cleanup"] == "PASS"
        assert stopped["databaseInitialization"] == "NOT_STARTED"
        assert lifecycle.env_down(
            worktree, production_contract=contract
        )["status"] == "ALREADY_STOPPED"
    finally:
        _cleanup(worktree, contract)


@pytest.mark.parametrize("name", ("DATABASE_URL", "MEDIA_DIR", "IZO_SECRET_DIR"))
def test_env_up_rejects_ambient_paths_without_value_leak(
    tmp_path: Path, name: str
) -> None:
    worktree, contract = _single(tmp_path)
    value = r"C:\never\leak\this-path"
    with pytest.raises(lifecycle.EnvironmentLifecycleError) as captured:
        lifecycle.env_up(
            worktree,
            environment={name: value},
            production_contract=contract,
        )
    assert str(captured.value) == f"AMBIENT_PATH_VARIABLE_PRESENT variable={name}"
    assert value not in str(captured.value)


def test_port_collision_and_partial_reservation_leave_foreign_listener(
    tmp_path: Path,
) -> None:
    package_id = "PKG-COLLISION"
    worktree, contract = _single(tmp_path, package_id)
    ports = derive_candidate_ports(package_id)
    foreign, stop, thread = _listener(ports["frontend"])
    try:
        with pytest.raises(lifecycle.EnvironmentLifecycleError, match="PORT_IN_USE"):
            lifecycle.env_up(
                worktree, environment={}, production_contract=contract
            )
        assert lifecycle._exchange(ports["frontend"], "PING") == "FOREIGN"
        assert _can_bind(ports["backend"])
    finally:
        _close_listener(foreign, stop, thread)
        _cleanup(worktree, contract)


def test_crash_becomes_stale_and_requires_explicit_recovery(tmp_path: Path) -> None:
    worktree, contract = _single(tmp_path, "PKG-CRASH")
    up = lifecycle.env_up(worktree, environment={}, production_contract=contract)
    _terminate_owned_test_holder(int(up["pid"]))
    assert _wait(lambda: lifecycle.environment_status(worktree)["status"] == "STALE")
    with pytest.raises(
        lifecycle.EnvironmentLifecycleError,
        match="ENVIRONMENT_STALE_RECOVERY_REQUIRED",
    ):
        lifecycle.env_down(worktree, production_contract=contract)
    recovered = lifecycle.env_down(
        worktree, recover_stale=True, production_contract=contract
    )
    assert recovered["status"] == "STOPPED"
    assert recovered["recoveredStale"] is True
    assert lifecycle.environment_status(worktree)["status"] == "STOPPED"


def test_stale_recovery_refuses_foreign_port_occupant(tmp_path: Path) -> None:
    package_id = "PKG-STALE-FOREIGN"
    worktree, contract = _single(tmp_path, package_id)
    up = lifecycle.env_up(worktree, environment={}, production_contract=contract)
    _terminate_owned_test_holder(int(up["pid"]))
    backend = int(up["ports"]["backend"])
    frontend = int(up["ports"]["frontend"])
    assert _wait(
        lambda: not lifecycle._port_open(backend)
        and not lifecycle._port_open(frontend)
    )
    foreign, stop, thread = _listener(backend)
    try:
        assert lifecycle.environment_status(worktree)["status"] == "STALE"
        with pytest.raises(
            lifecycle.EnvironmentLifecycleError,
            match="STALE_PORT_FOREIGN_OCCUPANT",
        ):
            lifecycle.env_down(
                worktree, recover_stale=True, production_contract=contract
            )
        assert lifecycle._exchange(backend, "PING") == "FOREIGN"
    finally:
        _close_listener(foreign, stop, thread)
    assert lifecycle.env_down(
        worktree, recover_stale=True, production_contract=contract
    )["status"] == "STOPPED"


def test_live_pid_without_matching_lease_fails_closed(tmp_path: Path) -> None:
    worktree, contract = _single(tmp_path, "PKG-REUSED")
    plan = build_environment_plan(
        worktree, environment={}, production_contract=contract
    )
    identity = load_environment_identity(worktree)
    paths = derive_environment_paths(identity)
    for directory in lifecycle._runtime_dirs(paths):
        directory.mkdir(parents=True, exist_ok=True)
    ports = dict(plan["ports"])
    ports["reserved"] = True
    active = {
        **plan,
        "state": "active",
        "ports": ports,
        "portLease": {"pid": os.getpid(), "leaseId": "not-ours", "startedAt": "x"},
    }
    paths.environment_state_path.write_text(
        json.dumps({"documentType": "environment-state", **active}),
        encoding="utf-8",
    )
    paths.receipt_path.write_text(
        json.dumps({"documentType": "environment-receipt", **active}),
        encoding="utf-8",
    )
    with pytest.raises(
        lifecycle.EnvironmentLifecycleError, match="FOREIGN_OR_REUSED_PROCESS"
    ):
        lifecycle.environment_status(worktree)


def test_two_packages_run_concurrently_and_down_is_isolated(tmp_path: Path) -> None:
    control, base = _make_control_repo(tmp_path)
    a = _add_package(control, base, "PKG-LIFE-A", tmp_path / "a")
    b = _add_package(control, base, "PKG-LIFE-B", tmp_path / "b")
    contract = _contract(tmp_path)
    up_a = lifecycle.env_up(a, environment={}, production_contract=contract)
    up_b = lifecycle.env_up(b, environment={}, production_contract=contract)
    try:
        assert lifecycle.environment_status(a)["status"] == "ACTIVE"
        assert lifecycle.environment_status(b)["status"] == "ACTIVE"
        assert set(up_a["ports"].values()).isdisjoint(set(up_b["ports"].values()))
        b_pid = up_b["pid"]
        b_ports = dict(up_b["ports"])
        b_paths = derive_environment_paths(load_environment_identity(b))

        lifecycle.env_down(a, production_contract=contract)
        status_b = lifecycle.environment_status(b)
        assert status_b["status"] == "ACTIVE"
        assert status_b["pid"] == b_pid
        assert status_b["ports"] == b_ports
        assert b_paths.environment_state_path.is_file()

        lifecycle.env_down(b, production_contract=contract)
        assert lifecycle.environment_status(a)["status"] == "STOPPED"
        assert lifecycle.environment_status(b)["status"] == "STOPPED"
    finally:
        _cleanup(a, contract)
        _cleanup(b, contract)


def test_env_up_preserves_real_provider_credential_guard(tmp_path: Path) -> None:
    worktree, contract = _single(tmp_path, "PKG-CREDENTIAL-GUARD")
    secret_value = "should-not-leak-provider-secret"
    with pytest.raises(
        lifecycle.EnvironmentLifecycleError,
        match="REAL_PROVIDER_CREDENTIAL_PRESENT",
    ) as captured:
        lifecycle.env_up(
            worktree,
            environment={"OPENROUTER_API_KEY": secret_value},
            production_contract=contract,
        )
    assert secret_value not in str(captured.value)

class _NeverReadyProcess:
    def __init__(self, *, pid: int = 4242, exit_code: int | None = None) -> None:
        self.pid = pid
        self.exit_code = exit_code
        self.terminated = False
        self.wait_timeouts: list[float] = []

    def poll(self):
        return self.exit_code

    def terminate(self) -> None:
        self.terminated = True

    def wait(self, timeout: float):
        self.wait_timeouts.append(timeout)
        return 0


def _fake_startup_clock(monkeypatch: pytest.MonkeyPatch) -> dict[str, float]:
    clock = {"now": 0.0}
    monkeypatch.setattr(lifecycle, "STARTUP_TIMEOUT_SECONDS", 0.15)
    monkeypatch.setattr(lifecycle.time, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(
        lifecycle.time,
        "sleep",
        lambda seconds: clock.__setitem__("now", clock["now"] + seconds),
    )
    return clock


@pytest.mark.parametrize(
    ("recorded_stage", "expected_stage"),
    ((None, "PRE_HOLDER_ENTRY"), ("HOLDER_ENTERED", "HOLDER_ENTERED")),
)
def test_wait_startup_timeout_reports_bounded_stage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    recorded_stage: str | None,
    expected_stage: str,
) -> None:
    startup = tmp_path / "lease-startup-test.json"
    diagnostic_path = lifecycle._startup_diagnostic_path(startup)
    if recorded_stage is not None:
        lifecycle._write_startup_diagnostic(diagnostic_path, recorded_stage, 4242)
        assert set(json.loads(diagnostic_path.read_text(encoding="utf-8"))) == {"stage", "pid"}
    process = _NeverReadyProcess()
    clock = _fake_startup_clock(monkeypatch)

    with pytest.raises(lifecycle.EnvironmentLifecycleError) as captured:
        lifecycle._wait_startup(process, startup)

    assert str(captured.value) == "PORT_LEASE_START_TIMEOUT"
    diagnostic = capsys.readouterr().err.strip()
    for field in (
        f"stage={expected_stage}", "processAlive=true", "pid=4242", "elapsedMs="
    ):
        assert field in diagnostic
    assert diagnostic.startswith("PORT_LEASE_START_DIAGNOSTIC ")
    assert process.terminated is True
    assert process.wait_timeouts == [2]
    assert clock["now"] >= 0.15


def test_wait_startup_child_exit_preserves_public_error_and_reports_stage(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    startup = tmp_path / "lease-startup-test.json"
    diagnostic_path = lifecycle._startup_diagnostic_path(startup)
    lifecycle._write_startup_diagnostic(
        diagnostic_path, "IDENTITY_OK", 4242
    )
    process = _NeverReadyProcess(exit_code=17)

    with pytest.raises(lifecycle.EnvironmentLifecycleError) as captured:
        lifecycle._wait_startup(process, startup)

    assert str(captured.value) == "PORT_LEASE_START_FAILED"
    diagnostic = capsys.readouterr().err.strip()
    assert "stage=IDENTITY_OK" in diagnostic
    assert "processAlive=false" in diagnostic
    assert "pid=4242" in diagnostic
    assert "exitCode=17" in diagnostic
    assert process.terminated is False


def test_wait_startup_ready_removes_diagnostic_temp_file(tmp_path: Path) -> None:
    startup = tmp_path / "lease-startup-test.json"
    diagnostic_path = lifecycle._startup_diagnostic_path(startup)
    startup.write_text(
        json.dumps({"status": "READY", "pid": 4242}),
        encoding="utf-8",
    )
    lifecycle._write_startup_diagnostic(
        diagnostic_path, "READY_WRITTEN", 4242
    )
    process = _NeverReadyProcess()

    payload = lifecycle._wait_startup(process, startup)

    assert payload == {"status": "READY", "pid": 4242}
    assert not diagnostic_path.exists()
    assert process.terminated is False
