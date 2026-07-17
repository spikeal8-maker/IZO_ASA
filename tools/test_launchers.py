from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_public_launcher_stops_when_candidate_release_fails() -> None:
    launcher = (ROOT / "start-public.bat").read_text(encoding="utf-8")
    publish_index = launcher.index("publish-frontend-release.ps1")
    restart_index = launcher.index("Controlled backend restart from immutable release manifest")
    gate = launcher[publish_index:restart_index]

    assert "if errorlevel 1" in gate
    assert "exit /b 1" in gate
    assert "active public release was NOT changed" in gate
    assert "-SkipVerify" not in launcher


def test_public_launcher_verifies_release_before_restarting_ports() -> None:
    launcher = (ROOT / "start-public.bat").read_text(encoding="utf-8")

    assert launcher.index("publish-frontend-release.ps1") < launcher.index("Controlled backend restart from immutable release manifest")
    assert "restart-backend.ps1" in launcher
    assert "-ReleaseManifestPath \"%RELEASE_MANIFEST%\"" in launcher
    assert "-AllowColdStart" in launcher
    assert "backend\\.venv\\Scripts\\python.exe" in launcher
    assert "Immutable frontend release is already active" in launcher
    assert "RELEASE IDENTITY MISMATCH" in launcher
    assert "FRONTEND RELEASE MISMATCH" in launcher
    assert "STATIC SHELL RELEASE MISMATCH" in launcher
    assert "X-IZO-Release" in launcher
    assert "release meta matches" in launcher
    assert "rollback-frontend-release.ps1" in launcher
    assert "BACKEND_LOG" not in launcher


def test_public_launcher_never_blocks_noninteractive_failures_on_pause() -> None:
    launcher = (ROOT / "start-public.bat").read_text(encoding="utf-8")

    assert "& pause & exit" not in launcher
    assert launcher.count('if /I not "%IZO_NO_PAUSE%"=="1" pause') >= 8


def test_production_stack_has_no_unmanaged_bootstrap_backend() -> None:
    launcher = (ROOT / "tools" / "start-production-stack.ps1").read_text(encoding="utf-8")

    assert "Start-BootstrapBackend" not in launcher
    assert "bootstrap_backend_" not in launcher
    assert "start-public-autostart.bat" in launcher


def test_public_stop_script_describes_the_actual_frp_transport() -> None:
    launcher = (ROOT / "stop-public.bat").read_text(encoding="utf-8")

    assert "FRP left running" in launcher
    assert "Cloudflared" not in launcher


def test_public_launcher_keeps_max_polling_unless_webhook_is_explicit() -> None:
    launcher = (ROOT / "start-public.bat").read_text(encoding="utf-8")

    assert 'if "%MAX_UPDATES_MODE%"=="" set "MAX_UPDATES_MODE=polling"' in launcher
    assert 'if "%MAX_UPDATES_MODE%"=="" set "MAX_UPDATES_MODE=webhook"' not in launcher


def test_public_launcher_defaults_to_migrated_max_api2_hostname() -> None:
    launcher = (ROOT / "start-public.bat").read_text(encoding="utf-8")

    assert 'set "MAX_API_BASE_URL=https://platform-api2.max.ru"' in launcher
    assert 'set "MAX_API_BASE_URL=https://platform-api.max.ru"' not in launcher


def test_public_launcher_uses_valid_json_and_blocks_on_auth_smoke_mismatch() -> None:
    launcher = (ROOT / "start-public.bat").read_text(encoding="utf-8")

    assert "$generateBody=@{mode='text_to_image'} | ConvertTo-Json -Compress" in launcher
    assert "$generateStatus=St 'POST' 'http://127.0.0.1:5173/api/generate' $generateBody" in launcher
    assert "$generateStatus -ne 401" in launcher
    assert "$galleryStatus -ne 401" in launcher
    assert "$meStatus -ne 401" in launcher
    assert "AUTH SMOKE FAILED" in launcher
    assert "exit 23" in launcher
