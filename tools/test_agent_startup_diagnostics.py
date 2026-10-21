"""Port lease startup diagnostics and bounded child cleanup regressions."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from tools.agent_system import env_lifecycle as lifecycle
from tools.agent_system.env import derive_environment_paths, load_environment_identity
from tools.test_agent_env_lifecycle import _single


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
        self.exit_code = -15

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
    stderr = capsys.readouterr().err
    diagnostic, cleanup = stderr.strip().splitlines()
    for field in (
        f"stage={expected_stage}", "processAliveBeforeTerminate=true",
        "pid=4242", "elapsedMs="
    ):
        assert field in diagnostic
    assert diagnostic.startswith("PORT_LEASE_START_DIAGNOSTIC ")
    assert cleanup == (
        "PORT_LEASE_CLEANUP_DIAGNOSTIC processAliveAfterTerminate=false"
    )
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


@pytest.mark.parametrize(
    ("case", "expected_type"),
    (("unavailable", "PermissionError"), ("missing", "FileNotFoundError"),
     ("empty", "JSONDecodeError"), ("malformed", "JSONDecodeError"),
     ("unicode", "UnicodeDecodeError"), ("non-object", "ValueError")),
)
def test_startup_json_read_failure_reports_observed_metadata_without_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
    case: str, expected_type: str,
) -> None:
    secret = "TEST_PRIVATE_STARTUP_CONTENT"
    startup = tmp_path / "private-path" / "lease-startup-test.json"
    startup.parent.mkdir()
    data = {"empty": b"", "malformed": ('{"secret":"' + secret).encode(),
            "unicode": b"\xff" + secret.encode(), "non-object": json.dumps([secret]).encode()}
    startup.write_bytes(data.get(case, secret.encode()))
    lifecycle._write_startup_diagnostic(
        lifecycle._startup_diagnostic_path(startup), "SOCKETS_BOUND", 4242
    )
    read_text = Path.read_text

    def controlled_read(path, *args, **kwargs):
        if path == startup and case == "unavailable":
            error = PermissionError(13, secret, str(startup))
            error.winerror = 32
            raise error
        if path == startup and case == "missing":
            path.unlink()
        return read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", controlled_read)
    with pytest.raises(lifecycle.EnvironmentLifecycleError) as captured:
        lifecycle._wait_startup(_NeverReadyProcess(), startup)
    assert str(captured.value) == "ENVIRONMENT_STATE_INVALID"
    stderr = capsys.readouterr().err
    prefix = "PORT_LEASE_STARTUP_READ_DIAGNOSTIC "
    assert stderr.startswith(prefix)
    fields = json.loads(stderr[len(prefix):])
    assert fields == {
        "exception_type": expected_type,
        "errno": 13 if case == "unavailable" else 2 if case == "missing" else None,
        "winerror": 32 if case == "unavailable" else None,
        "file_exists": case != "missing",
        "file_size": None if case == "missing" else len(data.get(case, secret.encode())),
        "holder_pid": 4242, "holder_alive": True, "startup_stage": "SOCKETS_BOUND",
    }
    assert secret not in stderr and str(tmp_path) not in stderr and "private-path" not in stderr


def test_startup_json_diagnostic_unobservable_metadata_remains_unknown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    startup = tmp_path / "lease-startup-test.json"
    stat = Path.stat

    def unavailable_stat(path, *args, **kwargs):
        if path == startup:
            raise PermissionError(13, "PRIVATE_ERROR_TEXT", str(startup))
        return stat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", unavailable_stat)
    lifecycle._report_startup_read_error(startup, _NeverReadyProcess(exit_code=17), PermissionError(13))
    stderr = capsys.readouterr().err
    fields = json.loads(stderr.split(" ", 1)[1])
    assert fields["file_exists"] is None and fields["file_size"] is None
    assert fields["startup_stage"] is None and fields["holder_alive"] is False
    assert "PRIVATE_ERROR_TEXT" not in stderr and str(tmp_path) not in stderr


def test_invalid_startup_json_env_up_terminates_its_child_and_removes_startup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    worktree, contract = _single(tmp_path, "PKG-INVALID-STARTUP")
    children: list[subprocess.Popen] = []
    startups: list[Path] = []

    def spawn_invalid(repo, identity, paths, backend, frontend, lease_id):
        startup = paths.state_root / f"lease-startup-{lease_id}.json"
        command = "import pathlib,sys,time;pathlib.Path(sys.argv[1]).write_text('{invalid');time.sleep(30)"
        child = subprocess.Popen([sys.executable, "-c", command, str(startup)])
        children.append(child)
        startups.append(startup)
        return child, startup

    monkeypatch.setattr(lifecycle, "_spawn_holder", spawn_invalid)
    try:
        with pytest.raises(lifecycle.EnvironmentLifecycleError, match="^ENVIRONMENT_STATE_INVALID$"):
            lifecycle.env_up(worktree, environment={}, production_contract=contract)
        assert len(children) == 1 and children[0].poll() is not None
        assert not startups[0].exists()
        paths = derive_environment_paths(load_environment_identity(worktree))
        assert not paths.environment_state_path.exists()
        assert not paths.database_path.exists()
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
                child.wait(timeout=2)
