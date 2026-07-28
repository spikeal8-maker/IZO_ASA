from __future__ import annotations

import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / "tools" / "check_frontend_release_identity.mjs"


def _fake_dist(tmp_path: Path, release: str) -> Path:
    dist = tmp_path / "dist"
    assets = dist / "assets"
    assets.mkdir(parents=True)
    (dist / "index.html").write_text(
        f'<html><head><meta name="izo-release" content="{release}"></head></html>\n',
        encoding="utf-8",
    )
    (assets / "index-test.js").write_text(f'const release={release!r};\n', encoding="utf-8")
    return dist


def _run(dist: Path, release: str) -> subprocess.CompletedProcess[str]:
    environment = dict(os.environ)
    environment["FRONTEND_BUILD_LABEL"] = release
    return subprocess.run(
        ["node", str(CHECKER), "--dist", str(dist)],
        cwd=ROOT,
        env=environment,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )


def _run_without_expected(dist: Path) -> subprocess.CompletedProcess[str]:
    environment = dict(os.environ)
    environment.pop("FRONTEND_BUILD_LABEL", None)
    environment.pop("GITHUB_SHA", None)
    return subprocess.run(
        ["node", str(CHECKER), "--dist", str(dist)],
        cwd=ROOT,
        env=environment,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )


def test_frontend_release_checker_accepts_matching_html_and_javascript(tmp_path: Path) -> None:
    release = "a" * 12 + "-20260717220000"
    result = _run(_fake_dist(tmp_path, release), release)

    assert result.returncode == 0, result.stdout + result.stderr
    assert f"FRONTEND_RELEASE_IDENTITY_OK release={release}" in result.stdout


def test_frontend_release_checker_rejects_marker_or_bundle_mismatch(tmp_path: Path) -> None:
    dist = _fake_dist(tmp_path, "old-release")
    result = _run(dist, "new-release")

    assert result.returncode != 0
    assert "frontend release meta mismatch" in result.stderr


def test_frontend_release_checker_rejects_missing_or_development_identity(tmp_path: Path) -> None:
    missing = _run_without_expected(_fake_dist(tmp_path / "missing", "dev"))
    development = _run(_fake_dist(tmp_path / "development", "dev"), "dev")

    assert missing.returncode != 0
    assert "expected frontend release id is required" in missing.stderr
    assert development.returncode != 0
    assert "unsafe frontend release id is forbidden" in development.stderr


def test_frontend_build_identity_has_one_injected_source_and_no_hardcoded_label() -> None:
    identity = (ROOT / "frontend" / "src" / "releaseIdentity.ts").read_text(encoding="utf-8")
    diagnostics = (ROOT / "frontend" / "src" / "diagMeta.ts").read_text(encoding="utf-8")
    telemetry = (ROOT / "frontend" / "src" / "runtimeTelemetry.ts").read_text(encoding="utf-8")
    vite = (ROOT / "frontend" / "vite.config.ts").read_text(encoding="utf-8")
    synthetic = (ROOT / "frontend" / "e2e-synthetic.mjs").read_text(encoding="utf-8")

    assert "__APP_RELEASE__" in identity
    assert "FRONTEND_RELEASE_ID" in diagnostics
    assert "FRONTEND_RELEASE_ID" in telemetry
    assert "FEED-4COL-FULLWIDTH" not in diagnostics
    assert "izo-release" in vite
    assert "FRONTEND_BUILD_LABEL must identify the immutable release" in vite
    assert "process.argv.includes('build')" in vite
    assert "frontendReleaseRoutes = new Set(['/', '/profile'])" in synthetic
    assert "page.evaluate" in synthetic
