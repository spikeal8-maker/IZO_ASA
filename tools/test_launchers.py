from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_public_launcher_stops_when_candidate_release_fails() -> None:
    launcher = (ROOT / "start-public.bat").read_text(encoding="utf-8")
    publish_index = launcher.index("publish-frontend-release.ps1")
    restart_index = launcher.index("Freeing ports 8000 and 5173")
    gate = launcher[publish_index:restart_index]

    assert "if errorlevel 1" in gate
    assert "exit /b 1" in gate
    assert "active public release was NOT changed" in gate


def test_public_launcher_verifies_release_before_restarting_ports() -> None:
    launcher = (ROOT / "start-public.bat").read_text(encoding="utf-8")

    assert launcher.index("publish-frontend-release.ps1") < launcher.index("Freeing ports 8000 and 5173")
    assert "--outDir '%FRONTEND_RELEASE%'" in launcher


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
