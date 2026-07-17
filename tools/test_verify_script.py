from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "verify.ps1"
POWERSHELL = Path(r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe")


def _plan(mode: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            str(POWERSHELL),
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(SCRIPT),
            "-PlanOnly",
            "-Mode",
            mode,
            "-RepoRoot",
            str(ROOT),
            "-PythonPath",
            sys.executable,
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )


def test_relative_file_invocation_resolves_repository_root() -> None:
    result = subprocess.run(
        [
            str(POWERSHELL),
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(SCRIPT.relative_to(ROOT)),
            "-PlanOnly",
            "-Mode",
            "Quick",
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
    assert "root=" in result.stdout
    assert "VERIFY_PLAN_OK mode=Quick" in result.stdout


def test_full_plan_contains_every_local_gate_without_execution() -> None:
    result = _plan("Full")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "VERIFY_PLAN mode=Full" in result.stdout
    assert "py_compile" in result.stdout
    assert "backend_map_check" in result.stdout
    assert "architecture_inventory_check" in result.stdout
    assert "source_snapshot before_after=true" in result.stdout
    assert "restart-backend.ps1 -PreflightOnly" in result.stdout
    assert "runtime_listener_contract command=check-runtime-listeners.ps1" in result.stdout
    assert "pytest scope=backend+tools" in result.stdout
    assert "architecture_inventory_check" in result.stdout
    assert "frontend_lint" in result.stdout
    assert "frontend_build" in result.stdout
    assert "frontend_release_identity" in result.stdout
    assert "frontend_studio_resilience" in result.stdout
    assert "VERIFY_PLAN_OK mode=Full" in result.stdout


def test_ci_plan_is_deterministic_and_omits_live_runtime_checks() -> None:
    result = _plan("CI")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "pytest scope=backend+tools" in result.stdout
    assert "frontend_lint" in result.stdout
    assert "frontend_build" in result.stdout
    assert "frontend_release_identity" in result.stdout
    assert "frontend_studio_resilience" in result.stdout
    assert "source_snapshot" not in result.stdout
    assert "backend_preflight" not in result.stdout
    assert "runtime_listener_contract" not in result.stdout
    assert "VERIFY_PLAN_OK mode=CI" in result.stdout


def test_quick_plan_runs_only_static_and_tool_contract_gates() -> None:
    result = _plan("Quick")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "py_compile" in result.stdout
    assert "backend_map_check" in result.stdout
    assert "architecture_inventory_check" in result.stdout
    assert "runtime_listener_contract command=check-runtime-listeners.ps1" in result.stdout
    assert "pytest scope=tool-contracts" in result.stdout
    assert "frontend_lint" not in result.stdout
    assert "frontend_build" not in result.stdout
    assert "frontend_release_identity" not in result.stdout
    assert "VERIFY_PLAN_OK mode=Quick" in result.stdout


def test_verify_script_has_no_process_or_file_deletion_commands() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "Stop-Process" not in source
    assert "Remove-Item" not in source
    assert "-PreflightOnly" in source
    assert "Test-SourceSnapshotEqual" in source
    assert "VERIFY_SOURCE_CONCURRENT_CHANGE" in source
    assert "[switch]$RequireStableLiveSource" in source
    assert "if ($RequireStableLiveSource)" in source
    assert "Tests use isolated temp roots" in source
    assert "VERIFY_OK" in source
    assert "architecture_inventory_check" in source
    assert "runtime_listener_contract" in source
    assert "[Console]::OutputEncoding = $utf8NoBom" in source
    assert '$_.Name -match "^(?i:python' in source


def test_verify_script_defaults_to_full_mode() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert '[string]$Mode = "Full"' in source
    assert '$projectPython = Join-Path $backendDirectory ".venv\\Scripts\\python.exe"' in source
    assert '-DefaultPath $projectPython' in source
    assert 'C:\\Program Files\\Python311\\python.exe' not in source
    assert '$fullTests = @("-m", "pytest", "-q", "backend", "tools")' in source
    assert '$usesLiveChecks = $Mode -ne "CI"' in source
    assert '"tools/test_backup_restore.py"' in source
    assert '"tools/test_generate_architecture_inventory.py"' in source
    assert '"tools/test_frontend_release_identity.py"' in source
    assert '"tools/test_runtime_listener_contract.py"' in source
    assert '"tools/test_ci_workflow.py"' in source
    assert '"tools/test_pytest_collection_contract.py"' in source
