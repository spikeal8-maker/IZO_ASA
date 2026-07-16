from __future__ import annotations

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run_plan(script: str) -> str:
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(ROOT / "tools" / script), "-RepoRoot", str(ROOT), "-PlanOnly"],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


def test_publish_plan_is_immutable_and_atomic() -> None:
    output = run_plan("publish-frontend-release.ps1")
    assert "branch=" in output
    assert "smoke_port=5197" in output
    assert "atomic_manifest=" in output
    assert "retain=2" in output
    script = (ROOT / "tools" / "publish-frontend-release.ps1").read_text(encoding="utf-8")
    assert '$branch -ne "main" -and -not $PlanOnly' in script
    assert "npm run build" in script
    assert script.index("npm run build") < script.index("e2e:synthetic")
    assert "Port 5173 is not owned by the canonical Vite preview" in script
    assert '"--port", "5173", "--strictPort", "--outDir", "`"$releasePath`""' in script
    assert "Activated frontend preview did not become ready on port 5173." in script


def test_drill_plan_covers_primary_failure_modes() -> None:
    output = run_plan("run-resilience-drill.ps1")
    for scenario in ("malformed-gallery-contract", "isolated-preview", "backend-unavailable", "auth-401", "failed-candidate-release"):
        assert scenario in output


def test_rollback_validates_candidate_before_port_restart() -> None:
    script = (ROOT / "tools" / "rollback-frontend-release.ps1").read_text(encoding="utf-8")
    assert script.index("e2e:synthetic") < script.index("LocalPort 5173")
    assert "refusing to stop it" in script
    assert "ROLLBACK_OK" in script
