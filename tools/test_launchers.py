from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_public_launcher_stops_on_typescript_failure() -> None:
    launcher = (ROOT / "start-public.bat").read_text(encoding="utf-8")
    tsc_index = launcher.index("call npx tsc -b")
    vite_index = launcher.index("call npx vite build", tsc_index)
    gate = launcher[tsc_index:vite_index]

    assert "if errorlevel 1" in gate
    assert "exit /b 1" in gate
    assert "TypeScript compile failed" in gate
    assert "Vite build will still run" not in gate


def test_public_launcher_builds_before_restarting_ports() -> None:
    launcher = (ROOT / "start-public.bat").read_text(encoding="utf-8")

    assert launcher.index("call npx tsc -b") < launcher.index("call npx vite build")
    assert launcher.index("call npx vite build") < launcher.index("Freeing ports 8000 and 5173")


def test_public_launcher_keeps_max_polling_unless_webhook_is_explicit() -> None:
    launcher = (ROOT / "start-public.bat").read_text(encoding="utf-8")

    assert 'if "%MAX_UPDATES_MODE%"=="" set "MAX_UPDATES_MODE=polling"' in launcher
    assert 'if "%MAX_UPDATES_MODE%"=="" set "MAX_UPDATES_MODE=webhook"' not in launcher
