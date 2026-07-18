from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = ROOT / "ops" / "caddy" / "runtime.json"
CADDYFILE = ROOT / "ops" / "caddy" / "Caddyfile"


def _powershell_plan(script: str, *extra: str) -> str:
    result = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(ROOT / "tools" / script),
            "-RepoRoot",
            str(ROOT),
            *extra,
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
    return result.stdout


def test_caddy_runtime_is_exact_version_and_dual_hash_pinned() -> None:
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))

    assert spec == {
        "schema_version": 1,
        "version": "2.11.4",
        "platform": "windows_amd64",
        "release_url": "https://github.com/caddyserver/caddy/releases/tag/v2.11.4",
        "archive_name": "caddy_2.11.4_windows_amd64.zip",
        "download_url": "https://github.com/caddyserver/caddy/releases/download/v2.11.4/caddy_2.11.4_windows_amd64.zip",
        "archive_sha256": "1708333f79e274c7697285afe6d592ab39314e0b131e9ec6bea08ad27df62ebf",
        "executable_sha256": "5cb9ab71e5756ce72840b8234177a2f40c8b4ab47a806b8e841e2b784e9df62b",
        "install_relative_path": ".tools/caddy/2.11.4/caddy.exe",
        "production_port": 5173,
        "candidate_port": 5197,
        "production_admin_address": "127.0.0.1:2019",
        "candidate_admin_address": "127.0.0.1:2020",
    }
    assert len(spec["archive_sha256"]) == len(spec["executable_sha256"]) == 64
    int(spec["archive_sha256"], 16)
    int(spec["executable_sha256"], 16)


def test_caddyfile_is_loopback_only_and_preserves_route_ownership() -> None:
    source = CADDYFILE.read_text(encoding="utf-8")

    assert "default_bind 127.0.0.1" in source
    assert "servers 127.0.0.1:{$IZO_CADDY_PORT}" in source
    assert "http://:{$IZO_CADDY_PORT}" in source
    assert "https://" not in source
    assert "not host izo.alikinas.ru 127.0.0.1 localhost" in source
    assert "respond @blocked_host 421" in source
    for path in ("/api", "/media", "/feed", "/gallery", "/static"):
        assert path in source
    assert "reverse_proxy {$IZO_CADDY_BACKEND_ADDRESS}" in source
    assert 'root * "{$IZO_FRONTEND_ROOT}"' in source
    assert "try_files {path} /index.html" in source


def test_caddyfile_has_bounded_requests_security_cache_and_redacted_json_logs() -> None:
    source = CADDYFILE.read_text(encoding="utf-8")

    assert "max_size 128MiB" in source
    assert "read_header 10s" in source
    assert "response_header_timeout 10m" in source
    assert "X-Content-Type-Options nosniff" in source
    assert "Referrer-Policy strict-origin-when-cross-origin" in source
    assert "X-Frame-Options SAMEORIGIN" in source
    assert "-Server" in source
    assert 'Cache-Control "public, max-age=31536000, immutable"' in source
    assert 'Cache-Control "no-store"' in source
    assert "encode zstd gzip" in source
    assert source.count("roll_at 00:00") == 2
    assert "format filter" in source
    for sensitive in ("Authorization delete", "Cookie delete", "X-IZO-Synthetic-Key delete"):
        assert sensitive in source
    for query_key in ("token", "access_token", "refresh_token", "code", "initData", "userId"):
        assert query_key in source


def test_installer_is_official_hash_verified_and_plan_only_is_network_free() -> None:
    source = (ROOT / "tools" / "install-caddy.ps1").read_text(encoding="utf-8")
    plan = _powershell_plan("install-caddy.ps1")

    assert "CADDY_INSTALL_PLAN" in plan
    assert "networkOnlyWhenMissing=true" in plan
    assert "Invoke-WebRequest" in source
    assert source.index("archive hash mismatch") < source.index("Expand-Archive")
    assert source.index("Extracted Caddy executable hash mismatch") < source.index("Move-Item")
    assert "Test-InstallerPathWithin" in source
    assert "github.com/caddyserver/caddy/releases/download" in source


def test_caddy_operational_scripts_have_fail_closed_plans() -> None:
    check_plan = _powershell_plan(
        "check-caddy-edge.ps1",
        "-ReleasePath",
        str(ROOT / "frontend"),
        "-ReleaseId",
        "plan-only-release",
        "-ConfigOnly",
    )
    start_plan = _powershell_plan("start-caddy-from-active-release.ps1")
    stop_plan = _powershell_plan("stop-caddy.ps1")

    assert "hostAllowlist=izo.alikinas.ru,127.0.0.1,localhost" in check_plan
    assert "CADDY_START_PLAN_OK activation=start-or-reload unknownOwner=refuse" in start_plan
    assert "ownership=required frp=untouched" in stop_plan
    runtime_source = (ROOT / "tools" / "caddy-runtime.ps1").read_text(encoding="utf-8")
    assert "Pinned Caddy executable failed its SHA-256 integrity check" in runtime_source
    assert "Get-IzoFrontendListenerState" in runtime_source
    assert 'Kind = "unknown"' in runtime_source

    check_source = (ROOT / "tools" / "check-caddy-edge.ps1").read_text(encoding="utf-8")
    assert "Add-Type -AssemblyName System.Net.Http" in check_source
    assert check_source.index("Add-Type -AssemblyName System.Net.Http") < check_source.index(
        "New-Object System.Net.Http.HttpClientHandler"
    )


def test_release_and_launcher_normal_paths_use_caddy_not_vite_preview() -> None:
    publisher = (ROOT / "tools" / "publish-frontend-release.ps1").read_text(encoding="utf-8")
    rollback = (ROOT / "tools" / "rollback-frontend-release.ps1").read_text(encoding="utf-8")
    launcher = (ROOT / "start-public.bat").read_text(encoding="utf-8")

    assert "caddy-reload" in publisher
    assert "legacy-vite-to-caddy" in publisher
    assert publisher.count("Start-LegacyViteRollback") == 2  # definition plus migration-only recovery
    assert "Start-FrontendPreview" not in publisher
    assert "graceful-reload" in rollback
    assert "vite" not in rollback.lower()
    assert "dist via vite preview" not in launcher.lower()
    assert "immutable dist via local Caddy" in launcher
    assert publisher.index("Test-IzoCaddyReleaseReady -Port $caddyRuntime.ProductionPort") < publisher.index(
        "Move-Item -LiteralPath $tempManifest -Destination $activeManifest"
    )


def test_installed_binary_matches_committed_executable_hash_when_present() -> None:
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    executable = ROOT / Path(spec["install_relative_path"])
    if not executable.is_file():
        return
    assert hashlib.sha256(executable.read_bytes()).hexdigest() == spec["executable_sha256"]
