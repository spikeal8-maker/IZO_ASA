from __future__ import annotations

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "architecture" / "contract.json"
SCRIPT = ROOT / "tools" / "check-runtime-listeners.ps1"
POWERSHELL = Path(r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe")


def _plan() -> subprocess.CompletedProcess[str]:
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
            "-RepoRoot",
            str(ROOT),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )


def _recovery_plan() -> subprocess.CompletedProcess[str]:
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
            "-AllowStoppedInstalledBackend",
            "-RepoRoot",
            str(ROOT),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )


def test_listener_contract_reserves_exact_roles_and_full_app_port() -> None:
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    listeners = {item["id"]: item for item in contract["listeners"]}

    assert {listener_id: item["port"] for listener_id, item in listeners.items()} == {
        "frontend-edge": 5173,
        "api": 8000,
        "qwen-asr": 8001,
        "comfyui": 8188,
        "ollama": 11434,
    }
    assert listeners["frontend-edge"]["required_local"] is True
    assert listeners["frontend-edge"]["process_names"] == ["caddy.exe"]
    assert listeners["frontend-edge"]["command_contains"] == ["run", "--config", "ops\\caddy\\Caddyfile"]
    assert listeners["frontend-edge"]["windows_service_fallback"] == {
        "name": "IZOCaddy",
        "arguments_contains": ["run", "--config", r"C:\IZO_ASA\config\Caddyfile", "--adapter", "caddyfile"],
    }
    assert listeners["api"]["required_local"] is True
    assert listeners["api"]["windows_service_fallback"]["name"] == "IZOBackend"
    assert listeners["qwen-asr"]["command_contains"] == ["qwen_asr_service.py", "--port", "8001"]
    assert listeners["ollama"]["windows_service_fallback"] == {
        "name": "IZOOllama",
        "arguments_contains": ["serve"],
    }
    assert contract["runtime_guards"] == {
        "full_app_process_names": ["python.exe"],
        "full_app_command_contains": ["-m", "uvicorn", "main:app"],
        "allowed_full_app_listener_ids": ["api"],
    }


def test_plan_only_is_deterministic_and_does_not_inspect_live_ports() -> None:
    first = _plan()
    second = _plan()

    assert first.returncode == 0, first.stdout + first.stderr
    assert second.returncode == 0, second.stdout + second.stderr
    assert first.stdout == second.stdout
    assert "RUNTIME_LISTENER_PLAN_ROLE id=api bind=127.0.0.1 port=8000 required=True" in first.stdout
    assert "RUNTIME_LISTENER_PLAN_ROLE id=qwen-asr bind=127.0.0.1 port=8001 required=False" in first.stdout
    assert "RUNTIME_LISTENER_PLAN_FULL_APP process=python.exe allowedPorts=8000" in first.stdout
    assert "RUNTIME_LISTENER_PLAN_OK roles=5" in first.stdout
    assert "RUNTIME_LISTENER_PRESENT" not in first.stdout


def test_recovery_plan_declares_the_stopped_backend_exception() -> None:
    result = _recovery_plan()

    assert result.returncode == 0, result.stdout + result.stderr
    assert "allowStoppedInstalledBackend=True" in result.stdout


def test_runtime_checker_is_read_only_and_fail_closed() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    for forbidden in ("Stop-Process", "Remove-Item", "Start-Process", "Set-Content", "New-Item"):
        assert forbidden not in source
    assert "Get-NetTCPConnection" in source
    assert "Get-CimInstance Win32_Process" in source
    assert "Get-CimInstance Win32_Service" in source
    assert "Get-ProcessAncestryIds" in source
    assert "service config id does not match" in source
    assert "RUNTIME_LISTENER_SERVICE_VERIFIED" in source
    assert "full application owns forbidden listener" in source
    assert "Stopped-backend listener exception requires" in source
    assert "required listener is absent" in source
    assert "listener process mismatch" in source
    assert "listener command mismatch" in source
    assert "RUNTIME_LISTENERS_OK" in source


def test_plan_rejects_contract_without_full_app_guard(tmp_path: Path) -> None:
    contract_path = tmp_path / "contract.json"
    contract_path.write_text(
        json.dumps(
            {
                "listeners": [
                    {
                        "id": "api",
                        "bind": "127.0.0.1",
                        "port": 8000,
                        "required_local": True,
                        "process_names": ["python.exe"],
                        "command_contains": ["main:app"],
                    }
                ],
                "runtime_guards": {
                    "full_app_process_names": ["python.exe"],
                    "full_app_command_contains": [],
                    "allowed_full_app_listener_ids": ["api"],
                },
            }
        ),
        encoding="utf-8",
    )

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
            "-RepoRoot",
            str(ROOT),
            "-ContractPath",
            str(contract_path),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )

    assert result.returncode != 0
    assert "contains no full-app process signature" in result.stderr
