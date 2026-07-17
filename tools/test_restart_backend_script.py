from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "restart-backend.ps1"
POWERSHELL = Path(r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe")


def _fake_repo(tmp_path: Path) -> Path:
    backend = tmp_path / "backend"
    backend.mkdir()
    (backend / "main.py").write_text("app = object()\n", encoding="utf-8")
    return tmp_path


def _run_script(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            str(POWERSHELL),
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(SCRIPT),
            *args,
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )


def test_restart_script_validate_only_imports_without_listener_or_mutation(tmp_path: Path) -> None:
    repo = _fake_repo(tmp_path)

    result = _run_script(
        "-ValidateOnly",
        "-RepoRoot",
        str(repo),
        "-PythonPath",
        sys.executable,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "BACKEND_RESTART_VALIDATE_OK" in result.stdout
    assert not (repo / "logs").exists()


def test_restart_script_relative_file_invocation_resolves_repository_root() -> None:
    result = subprocess.run(
        [
            str(POWERSHELL),
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(SCRIPT.relative_to(ROOT)),
            "-ValidateOnly",
            "-PythonPath",
            sys.executable,
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "BACKEND_RESTART_VALIDATE_OK" in result.stdout
    assert "root=" in result.stdout


def test_restart_script_rejects_public_bind_before_any_restart(tmp_path: Path) -> None:
    repo = _fake_repo(tmp_path)

    result = _run_script(
        "-ValidateOnly",
        "-RepoRoot",
        str(repo),
        "-PythonPath",
        sys.executable,
        "-BindAddress",
        "0.0.0.0",
    )

    assert result.returncode != 0
    assert "restricted to 127.0.0.1" in result.stderr


def test_restart_script_rejects_missing_backend_entrypoint(tmp_path: Path) -> None:
    result = _run_script(
        "-ValidateOnly",
        "-RepoRoot",
        str(tmp_path),
        "-PythonPath",
        sys.executable,
    )

    assert result.returncode != 0
    assert "Backend entrypoint not found" in result.stderr


def test_restart_script_rejects_explicit_missing_python(tmp_path: Path) -> None:
    repo = _fake_repo(tmp_path)

    result = _run_script(
        "-ValidateOnly",
        "-RepoRoot",
        str(repo),
        "-PythonPath",
        str(tmp_path / "missing-python.exe"),
    )

    assert result.returncode != 0
    assert "Requested Python executable was not found" in result.stderr


def test_actual_restart_requires_release_manifest_before_listener_mutation(tmp_path: Path) -> None:
    repo = _fake_repo(tmp_path)

    result = _run_script(
        "-RepoRoot",
        str(repo),
        "-PythonPath",
        sys.executable,
    )

    assert result.returncode != 0
    assert "ReleaseManifestPath is required" in result.stderr


def test_restart_script_checks_exact_listener_command_health_and_logs() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "Expected exactly one listener" in source
    assert "uvicorn\\s+main:app" in source
    assert "--host\\s+" in source
    assert "--port\\s+" in source
    assert '"--no-proxy-headers")' in source
    assert "RequireProxyIsolation" in source
    assert "ProxyHeadersDisabled" in source
    assert "Get-CimInstance Win32_Process" in source
    assert "/api/health" in source
    assert 'Properties.Name -contains "ready"' in source
    assert '[int]$HealthProbeTimeoutSeconds = 10' in source
    assert "Invoke-RestMethod -Uri $Uri -TimeoutSec $TimeoutSeconds" in source
    assert source.count("-TimeoutSeconds $HealthProbeTimeoutSeconds") == 4
    assert "RedirectStandardOutput" in source
    assert "RedirectStandardError" in source
    assert "BACKEND_RESTART_FAILED" in source
    assert "backend\\.venv\\Scripts\\python.exe" in source
    assert "Test-BackendReleaseIdentity" in source
    assert "assert_release_schema_compatible" in source
    assert "PRAGMA user_version" in source
    assert "BACKEND_RESTART_ROLLBACK_OK" in source
    assert "BACKEND_COLD_START" in source
    assert "AllowColdStart" in source
    assert "active-backend.json" in source
    assert "RuntimeLauncherProcessId" in source
    assert "RuntimeLauncherExecutablePath" in source
    assert '$runtimeOwnership = "windows-venv-child"' in source
    assert "GetFileName($actualPython)" in source
    assert 'ProcessId=$($process.ParentProcessId)' in source
    assert "Assert-BackendCommand -CommandLine ([string]$launcherProcess.CommandLine)" in source
    assert "$newState.RuntimeLauncherProcessId -ne $newProcess.Id" in source
    assert "launcher_process_id = $newState.RuntimeLauncherProcessId" in source
    assert "runtime_ownership = $newState.RuntimeOwnership" in source
    assert "listener_python = $newState.ExecutablePath" in source
    assert "$inspectedCandidate.RuntimeLauncherProcessId -eq $newProcess.Id" in source
    assert "Stop-Process -Id $newState.ProcessId -Force" in source


def test_restart_script_preflight_modes_return_before_stop() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    validate_index = source.index("if ($ValidateOnly)")
    preflight_index = source.index("if ($PreflightOnly)")
    release_preflight_index = source.index("Get-ProductionReleaseContract")
    stop_index = source.index("Stop-Process -Id $oldState.ProcessId")

    assert validate_index < preflight_index < stop_index
    assert release_preflight_index < stop_index
