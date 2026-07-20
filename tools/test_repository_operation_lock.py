"""REL-LOCK-001 contract tests: single-flight repository operations.

The lock helper serializes release/verification work. These tests use
temporary lock roots (never the production runtime state) except the
fail-fast test, which holds the real full-verify lock briefly so a second
``verify.ps1 -Mode Full`` refuses before running any pytest/build step.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "tools" / "repository-operation-lock.ps1"
POWERSHELL = "powershell"


def _run(arguments: list[str], env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", *arguments],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )


def _acquire_cli(root: Path, kind: str, token_file: Path) -> subprocess.CompletedProcess[str]:
    return _run(
        [
            "-File", str(HELPER),
            "-Action", "acquire",
            "-Kind", kind,
            "-RepoRoot", str(root),
            "-Command", "pytest-contract",
            "-TokenOutFile", str(token_file),
        ]
    )


def _release_cli(root: Path, kind: str, token: str) -> subprocess.CompletedProcess[str]:
    return _run(
        [
            "-File", str(HELPER),
            "-Action", "release",
            "-Kind", kind,
            "-RepoRoot", str(root),
            "-Token", token,
        ]
    )


def _write_owner(lock_path: Path, owner_pid: int, owner_start: str, token: str = "manual") -> None:
    lock_path.mkdir(parents=True)
    (lock_path / "owner.json").write_text(
        json.dumps(
            {
                "lock_version": 1,
                "kind": lock_path.name,
                "operation_id": "manual-test",
                "owner_pid": owner_pid,
                "owner_process_start_utc": owner_start,
                "command": "manual-test",
                "acquired_at_utc": "2026-07-20T00:00:00.0000000Z",
                "reentry_token": token,
            }
        ),
        encoding="utf-8",
    )


def _dead_pid() -> int:
    probe = subprocess.run(
        ["cmd", "/c", "exit 0"], capture_output=True, text=True, timeout=30
    )
    assert probe.returncode == 0
    # A PID far above the interactive range that is extremely unlikely to be
    # live; verified dead before use.
    for candidate in range(4_190_000, 4_190_400, 4):
        alive = subprocess.run(
            [
                POWERSHELL, "-NoProfile", "-NonInteractive", "-Command",
                f"if (Get-Process -Id {candidate} -ErrorAction SilentlyContinue) {{ exit 1 }} else {{ exit 0 }}",
            ],
            capture_output=True,
            timeout=60,
        )
        if alive.returncode == 0:
            return candidate
    raise AssertionError("No verifiably dead PID candidate found")


def test_concurrent_acquire_has_exactly_one_winner(tmp_path: Path) -> None:
    token_a = tmp_path / "a.token"
    token_b = tmp_path / "b.token"
    commands = []
    for token_file in (token_a, token_b):
        commands.append(
            subprocess.Popen(
                [
                    POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                    "-File", str(HELPER),
                    "-Action", "acquire",
                    "-Kind", "test-concurrent",
                    "-RepoRoot", str(tmp_path),
                    "-Command", "pytest-concurrent",
                    "-TokenOutFile", str(token_file),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        )
    results = [process.wait(timeout=120) for process in commands]
    winners = [code for code in results if code == 0]
    losers = [code for code in results if code != 0]
    assert len(winners) == 1, f"expected one winner, exit codes: {results}"
    assert len(losers) == 1
    loser_stderr = ""
    for process in commands:
        assert process.stderr is not None
        loser_stderr += process.stderr.read()
    assert "REPOSITORY_OPERATION_LOCK_BUSY" in loser_stderr
    assert (tmp_path / ".runtime" / "locks" / "test-concurrent" / "owner.json").exists()


def test_second_full_verify_fails_fast_without_running_steps(tmp_path: Path) -> None:
    token_file = tmp_path / "verify.token"
    acquired = _acquire_cli(ROOT, "full-verify", token_file)
    assert acquired.returncode == 0, acquired.stderr
    token = token_file.read_text(encoding="ascii")
    try:
        started = time.monotonic()
        verify = _run(["-File", str(ROOT / "tools" / "verify.ps1"), "-Mode", "Full"])
        duration = time.monotonic() - started
        assert verify.returncode != 0
        combined = verify.stdout + verify.stderr
        assert "REPOSITORY_OPERATION_LOCK_BUSY" in combined
        assert "VERIFY_STEP_START" not in combined
        assert duration < 60, f"lock refusal must be fast, took {duration:.1f}s"
    finally:
        released = _release_cli(ROOT, "full-verify", token)
        assert released.returncode == 0, released.stderr


def test_stale_lock_with_dead_pid_is_recovered(tmp_path: Path) -> None:
    lock_path = tmp_path / ".runtime" / "locks" / "test-stale"
    _write_owner(lock_path, _dead_pid(), "2026-07-19T00:00:00.0000000Z")
    token_file = tmp_path / "stale.token"
    acquired = _acquire_cli(tmp_path, "test-stale", token_file)
    assert acquired.returncode == 0, acquired.stderr
    owner = json.loads((lock_path / "owner.json").read_text(encoding="utf-8-sig"))
    assert owner["operation_id"] != "manual-test"


def test_pid_reuse_with_different_start_time_is_not_the_owner(tmp_path: Path) -> None:
    lock_path = tmp_path / ".runtime" / "locks" / "test-reuse"
    # Live PID (this pytest process) but a fabricated start time: a reused PID
    # must not be treated as the original owner.
    _write_owner(lock_path, os.getpid(), "1999-01-01T00:00:00.0000000Z")
    token_file = tmp_path / "reuse.token"
    acquired = _acquire_cli(tmp_path, "test-reuse", token_file)
    assert acquired.returncode == 0, acquired.stderr
    owner = json.loads((lock_path / "owner.json").read_text(encoding="utf-8-sig"))
    assert owner["operation_id"] != "manual-test"


def test_live_owner_is_never_stolen(tmp_path: Path) -> None:
    token_file = tmp_path / "live.token"
    first = _acquire_cli(tmp_path, "test-live", token_file)
    assert first.returncode == 0, first.stderr
    second = _acquire_cli(tmp_path, "test-live", tmp_path / "second.token")
    assert second.returncode != 0
    assert "REPOSITORY_OPERATION_LOCK_BUSY" in second.stderr
    original = json.loads(
        (tmp_path / ".runtime" / "locks" / "test-live" / "owner.json").read_text(encoding="utf-8-sig")
    )
    assert original["reentry_token"] == token_file.read_text(encoding="ascii")


def test_exception_inside_holder_releases_the_lock(tmp_path: Path) -> None:
    script = (
        f". '{HELPER}'; "
        f"$handle = Lock-IzoRepositoryOperation -RepoRoot '{tmp_path}' -Kind 'test-exception'; "
        "try { throw 'boom' } finally { Unlock-IzoRepositoryOperation -Handle $handle }"
    )
    holder = _run(["-Command", script])
    assert holder.returncode != 0
    assert not (tmp_path / ".runtime" / "locks" / "test-exception").exists()


def test_reentrant_holder_does_not_deadlock_or_release_the_outer_lock(tmp_path: Path) -> None:
    token_file = tmp_path / "reentrant.token"
    acquired = _acquire_cli(tmp_path, "test-reentrant", token_file)
    assert acquired.returncode == 0, acquired.stderr
    token = token_file.read_text(encoding="ascii")
    child_env = dict(os.environ)
    child_env["IZO_REPO_LOCK_TOKEN_TEST_REENTRANT"] = token
    script = (
        f". '{HELPER}'; "
        f"$handle = Lock-IzoRepositoryOperation -RepoRoot '{tmp_path}' -Kind 'test-reentrant'; "
        "if (-not $handle.Reentrant) { exit 3 }; "
        "Unlock-IzoRepositoryOperation -Handle $handle; exit 0"
    )
    child = _run(["-Command", script], env=child_env)
    assert child.returncode == 0, child.stderr
    lock_path = tmp_path / ".runtime" / "locks" / "test-reentrant"
    assert lock_path.exists(), "re-entrant exit must not release the outer lock"
    released = _release_cli(tmp_path, "test-reentrant", token)
    assert released.returncode == 0, released.stderr
    assert not lock_path.exists()


def test_release_with_foreign_token_is_refused(tmp_path: Path) -> None:
    token_file = tmp_path / "foreign.token"
    acquired = _acquire_cli(tmp_path, "test-foreign", token_file)
    assert acquired.returncode == 0, acquired.stderr
    refused = _release_cli(tmp_path, "test-foreign", "not-the-owner-token")
    assert refused.returncode != 0
    assert (tmp_path / ".runtime" / "locks" / "test-foreign").exists()
    token = token_file.read_text(encoding="ascii")
    released = _release_cli(tmp_path, "test-foreign", token)
    assert released.returncode == 0, released.stderr


def test_entrypoints_are_wired_to_the_lock() -> None:
    verify = (ROOT / "tools" / "verify.ps1").read_text(encoding="utf-8")
    publisher = (ROOT / "tools" / "publish-frontend-release.ps1").read_text(encoding="utf-8")
    launcher = (ROOT / "start-public.bat").read_text(encoding="utf-8")

    lock_index = verify.index('Lock-IzoRepositoryOperation')
    assert verify.index('-Kind "full-verify"') > lock_index
    assert lock_index < verify.index("VERIFY_STEP_START name=$Name") or lock_index < verify.index("Invoke-NativeStep `")
    assert "Unlock-IzoRepositoryOperation -Handle $operationLock" in verify

    assert '-Kind "public-release"' in publisher
    assert '-Kind "full-verify"' in publisher
    assert "SetEnvironmentVariable($fullVerifyLock.TokenVariable" in publisher
    assert "Unlock-IzoRepositoryOperation -Handle $publicReleaseLock" in publisher

    assert "-Action acquire -Kind public-release" in launcher
    assert "-Action release -Kind public-release" in launcher
    assert launcher.count("call :release_lock") >= 8
    assert launcher.index("-Action acquire -Kind public-release") < launcher.index("publish-frontend-release.ps1")
