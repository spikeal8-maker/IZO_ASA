from __future__ import annotations

import subprocess
import sys
import uuid
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
    assert "context_index_check" in result.stdout
    assert "source_snapshot before_after=true" in result.stdout
    assert "restart-backend.ps1 -PreflightOnly" in result.stdout
    assert "runtime_listener_contract command=check-runtime-listeners.ps1" in result.stdout
    assert "caddy_runtime_integrity" in result.stdout
    assert "caddy_config_validation" in result.stdout
    assert "caddy_edge_live" in result.stdout
    assert "pytest scope=backend+tools" in result.stdout
    assert "architecture_inventory_check" in result.stdout
    assert "context_index_check" in result.stdout
    assert "frontend_lint" in result.stdout
    assert "frontend_build" in result.stdout
    assert "frontend_release_identity" in result.stdout
    assert "frontend_studio_resilience" in result.stdout
    assert "caddy_runtime_integrity" in result.stdout
    assert "caddy_config_validation" in result.stdout
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
    assert "caddy_edge_live" not in result.stdout
    assert "VERIFY_PLAN_OK mode=CI" in result.stdout


def test_full_plan_can_bind_an_exact_sha_release_receipt_without_writing_it() -> None:
    receipt = ROOT / ".runtime" / "verification" / f"plan-only-{uuid.uuid4().hex}.json"
    result = subprocess.run(
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
            "Full",
            "-RepoRoot",
            str(ROOT),
            "-PythonPath",
            sys.executable,
            "-ReceiptPath",
            str(receipt),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert receipt.name in result.stdout
    assert "exactSha=true" in result.stdout
    assert "ttlHours=4" in result.stdout
    assert not receipt.exists()


def test_quick_plan_runs_only_static_and_tool_contract_gates() -> None:
    result = _plan("Quick")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "py_compile" in result.stdout
    assert "backend_map_check" in result.stdout
    assert "architecture_inventory_check" in result.stdout
    assert "context_index_check" in result.stdout
    assert "runtime_listener_contract command=check-runtime-listeners.ps1" in result.stdout
    assert "caddy_edge_live command=check-caddy-edge.ps1" in result.stdout
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
    assert '$preflightEnvironmentNames = @("IZO_RUNTIME_PROFILE", "APP_ENV", "ENV", "MODE", "IZO_RELEASE_MANIFEST")' in source
    assert '"IZO_RELEASE_MANIFEST",\n    "DATABASE_URL",\n    "DB_GUARD_ALLOWED_PATHS"' in source
    assert '[Environment]::SetEnvironmentVariable($environmentName, $null, "Process")' in source
    assert "$preflightEnvironment[$environmentName]" in source
    assert "$testEnvironment[$environmentName]" in source
    assert "Test-SourceSnapshotEqual" in source
    assert "VERIFY_SOURCE_CONCURRENT_CHANGE" in source
    assert "[switch]$RequireStableLiveSource" in source
    assert "if ($RequireStableLiveSource)" in source
    assert "Tests use isolated temp roots" in source
    assert "VERIFY_OK" in source
    assert "architecture_inventory_check" in source
    assert "runtime_listener_contract" in source
    assert "caddy_runtime_integrity" in source
    assert "caddy_config_validation" in source
    assert "caddy_edge_live" in source
    assert "[Console]::OutputEncoding = $utf8NoBom" in source
    assert '$_.Name -match "^(?i:python' in source
    assert "function Get-PytestProcesses" in source
    assert "$pendingParents.Enqueue([int]$PID)" in source
    assert "[int]$_.ParentProcessId -eq $parentId" in source
    assert "$descendantIds.Contains([int]$_.ProcessId)" in source
    assert "$attempt -lt 50" in source
    assert "Start-Sleep -Milliseconds 100" in source
    assert '[string]$ReceiptPath = ""' in source
    assert '[string]$TestHealthOutputPath = ""' in source
    assert '"--durations=10", "--durations-min=0.1"' in source
    assert "-OutputPath $TestHealthOutputPath" in source
    assert "System.Diagnostics.ProcessStartInfo" in source
    assert "-EncodedCommand $encodedCapture" in source
    assert "$process.WaitForExit()" in source
    assert '$stepExitCode = $process.ExitCode' in source
    assert '[IO.File]::WriteAllLines($OutputPath' in source
    assert "release_verification_receipt.py" in source
    assert "VERIFY_RECEIPT_WRITTEN" in source
    assert "$duration.ToString([Globalization.CultureInfo]::InvariantCulture)" in source
    assert "--duration-seconds $durationArgument" in source
    assert "[Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($summaryJson))" in source
    assert "--summary-base64 $summaryBase64" in source


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
    assert '"tools/test_agent_package.py"' in source
    assert '"tools/test_agent_sandbox.py"' in source
    assert '"tools/test_agent_symbol.py"' in source
    assert '"tools/test_agent_enforce.py"' in source
    assert '"tools/test_frontend_release_identity.py"' in source
    assert '"tools/test_runtime_listener_contract.py"' in source
    assert '"tools/test_caddy_edge_contract.py"' in source
    assert '"tools/test_caddy_edge_integration.py"' in source
    assert '"tools/test_ci_workflow.py"' in source
    assert '"tools/test_pytest_collection_contract.py"' in source
