from __future__ import annotations

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
START = ROOT / "tools" / "start-local-test-stack.ps1"
STOP = ROOT / "tools" / "stop-local-test-stack.ps1"


def test_local_test_launcher_isolated_from_live_data_and_providers() -> None:
    source = START.read_text(encoding="utf-8")

    assert r'.runtime\local-test' in source
    assert 'DATABASE_URL = "sqlite:///$databaseUrlPath"' in source
    assert "MEDIA_DIR = $mediaPath" in source
    assert "IZO_SECRET_DIR = $secretRoot" in source
    assert 'BOT_UPDATES_MODE = "disabled"' in source
    assert 'MAX_UPDATES_MODE = "disabled"' in source
    assert 'TELEGRAM_POLLING_ENABLED = "false"' in source
    assert 'MAX_POLLING_ENABLED = "false"' in source
    assert 'TELEGRAM_BOT_TOKEN = " "' in source
    assert 'MAX_BOT_TOKEN = " "' in source
    assert 'MAX_API_BASE_URL = "http://127.0.0.1:9"' in source
    assert 'BILLING_SIMULATOR_ENABLED = "true"' in source
    assert 'EMAIL_PROVIDER = "mock"' in source
    assert 'COMFYUI_MOCK_FALLBACK = "true"' in source
    assert "backend\\onenode.sqlite3" not in source
    assert "backend\\media" not in source
    assert "start-public" not in source
    assert "frpc" not in source.lower()
    assert "Real bot login capability leaked" in source


def test_local_test_launcher_blocks_every_machine_local_env_fallback() -> None:
    source = START.read_text(encoding="utf-8")
    env_path = ROOT / "backend" / ".env"
    if not env_path.exists():
        return

    local_keys = {
        line.split("=", 1)[0].strip()
        for line in env_path.read_text(encoding="utf-8").splitlines()
        if "=" in line
        and line.split("=", 1)[0].strip()
        and not line.lstrip().startswith("#")
    }
    declared = {
        line.split("=", 1)[0].strip()
        for line in source.split("$safeEnvironment = [ordered]@{", 1)[1]
        .split("}", 1)[0]
        .splitlines()
        if "=" in line
    }
    assert local_keys <= declared


def test_local_test_launcher_refuses_unknown_listener_owners() -> None:
    source = START.read_text(encoding="utf-8")

    assert "Assert-PortFree -Port $BackendPort" in source
    assert "Assert-PortFree -Port $FrontendPort" in source
    assert "this launcher never kills unknown processes" in source
    port_guard = source[
        source.index("function Assert-PortFree") : source.index("function Wait-HttpJson")
    ]
    assert "Stop-Process" not in port_guard


def test_local_test_launcher_uses_project_runtime_and_proxy_isolation() -> None:
    source = START.read_text(encoding="utf-8")
    wrapper = (ROOT / "start-project-test.bat").read_text(encoding="utf-8")

    assert r'.venv\Scripts\python.exe' in source
    assert "--no-proxy-headers" in source
    assert "node_modules\\vite\\bin\\vite.js" in source
    assert "start-local-test-stack.ps1" in wrapper
    assert "python -m uvicorn" not in wrapper
    assert "Stop-Process" not in wrapper


def test_local_test_stopper_requires_manifest_pid_and_command_ownership() -> None:
    source = STOP.read_text(encoding="utf-8")

    pid_check = source.index("listener PID $listenerPid differs from recorded PID")
    path_check = source.index("does not contain the recorded command path")
    stop_call = source.index("Stop-Process -Id $listenerPid")
    assert pid_check < stop_call
    assert path_check < stop_call
    assert "data_preserved=true" in source


def test_local_test_plan_is_non_mutating_and_names_isolated_paths() -> None:
    result = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(START),
            "-RepoRoot",
            str(ROOT),
            "-PlanOnly",
        ],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "LOCAL_TEST_PLAN_OK" in result.stdout
    assert ".runtime\\local-test\\data\\local-test.sqlite3" in result.stdout
    assert "providers=disabled-or-fake tunnel=disabled" in result.stdout
