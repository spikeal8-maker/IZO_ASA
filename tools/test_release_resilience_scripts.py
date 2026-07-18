from __future__ import annotations

import hashlib
import os
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
    assert "verification=run-full-and-receipt" in output
    assert "smoke_port=5197" in output
    assert "atomic_manifest=" in output
    assert "release-manifest.json" in output
    assert "retain=2" in output
    script = (ROOT / "tools" / "publish-frontend-release.ps1").read_text(encoding="utf-8")
    assert "SkipVerify" not in script
    assert '$branch -ne "main" -and -not $PlanOnly' in script
    assert "npm run build" in script
    assert "build_release_manifest.py" in script
    assert "release_verification_receipt.py" in script
    assert "-ReceiptPath" in script
    assert "validate" in script
    assert "[System.Security.Cryptography.SHA256]::Create()" in script
    assert "Get-FileHash" not in script
    assert '$env:FRONTEND_BUILD_LABEL = $releaseId' in script
    assert "--git-sha $fullSha" in script
    assert "Project Python is missing" in script
    assert script.index("npm run build") < script.index("e2e:synthetic")
    assert "Get-IzoFrontendListenerState" in script
    assert "Caddy candidate did not become ready" in script
    assert "caddy-reload" in script
    assert "legacy-vite-to-caddy" in script
    assert "Start-FrontendPreview" not in script
    assert "Activated Caddy edge did not serve the candidate release" in script
    assert script.index("Test-IzoCaddyReleaseReady -Port $caddyRuntime.ProductionPort") < script.index("Move-Item -LiteralPath $tempManifest")
    assert "RELEASE_ACTIVATION_ROLLBACK_OK" in script
    assert "RELEASE_VERIFICATION_RECEIPT_OK" in script
    public_release_info = script[script.index("$releaseInfo = [ordered]@{") : script.index("$releaseInfo | ConvertTo-Json")]
    assert "verification_evidence_sha256" in public_release_info
    assert "verification_evidence =" not in public_release_info
    assert "break_glass_operator" not in public_release_info
    assert "path = $releasePath" not in public_release_info


def test_publisher_receipt_hash_runs_under_windows_powershell() -> None:
    script_path = ROOT / "tools" / "publish-frontend-release.ps1"
    environment = os.environ.copy()
    environment["IZO_TEST_PUBLISHER"] = str(script_path)
    command = (
        "$tokens=$null;$errors=$null;"
        "$ast=[System.Management.Automation.Language.Parser]::ParseFile($env:IZO_TEST_PUBLISHER,[ref]$tokens,[ref]$errors);"
        "$node=$ast.Find({param($item) $item -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $item.Name -eq 'Get-FileSha256'},$true);"
        "if($null -eq $node){throw 'hash function missing'};"
        ". ([scriptblock]::Create($node.Extent.Text));"
        "Get-FileSha256 -Path $env:IZO_TEST_PUBLISHER"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
        cwd=ROOT,
        env=environment,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    expected = "sha256:" + hashlib.sha256(script_path.read_bytes()).hexdigest()
    assert result.stdout.strip() == expected


def test_break_glass_is_separate_reason_gated_and_audited() -> None:
    script_path = ROOT / "tools" / "publish-frontend-release-break-glass.ps1"
    script = script_path.read_text(encoding="utf-8")

    assert "[string]$Reason" in script
    assert "[string]$Operator" in script
    assert "I_ACCEPT_UNVERIFIED_RELEASE_RISK" in script
    assert "release-break-glass.jsonl" in script
    assert "release-break-glass-authorization" in script
    assert "IZO_BREAK_GLASS_AUTHORIZATION" in script
    assert "publish-frontend-release.ps1" in script
    assert "start-public.bat" in script
    assert "active.active_release" in script
    assert "activeBackend.release_id" in script
    assert "SkipVerify" not in script

    plan = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script_path),
            "-RepoRoot",
            str(ROOT),
            "-Reason",
            "Controlled emergency release test reason",
            "-Operator",
            "pytest",
            "-Acknowledgement",
            "I_ACCEPT_UNVERIFIED_RELEASE_RISK",
            "-PlanOnly",
        ],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    assert plan.returncode == 0, plan.stdout + plan.stderr
    assert "BREAK_GLASS_PLAN" in plan.stdout
    assert "singleUse=true" in plan.stdout
    assert "events=requested,completed|failed" in plan.stdout
    assert "fullStack=true" in plan.stdout


def test_break_glass_rejects_missing_acknowledgement_before_any_publish() -> None:
    result = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(ROOT / "tools" / "publish-frontend-release-break-glass.ps1"),
            "-RepoRoot",
            str(ROOT),
            "-Reason",
            "Controlled emergency release test reason",
            "-Operator",
            "pytest",
            "-Acknowledgement",
            "WRONG",
            "-PlanOnly",
        ],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    assert "I_ACCEPT_UNVERIFIED_RELEASE_RISK" in result.stderr


def test_drill_plan_covers_primary_failure_modes() -> None:
    output = run_plan("run-resilience-drill.ps1")
    for scenario in ("malformed-gallery-contract", "isolated-preview", "backend-unavailable", "auth-401", "failed-candidate-release"):
        assert scenario in output


def test_rollback_validates_candidate_before_atomic_caddy_reload() -> None:
    script = (ROOT / "tools" / "rollback-frontend-release.ps1").read_text(encoding="utf-8")
    assert script.index("e2e:synthetic") < script.index("Invoke-IzoCaddyReload -Runtime $runtime -AdminAddress $runtime.ProductionAdminAddress")
    assert "requires the pinned production Caddy listener" in script
    assert "Frontend rollback target does not match the active backend release" in script
    assert "ROLLBACK_OK" in script
    assert "IZO_ALLOW_LEGACY_RELEASE" in script
    assert script.index("Test-IzoCaddyReleaseReady -Port $runtime.ProductionPort") < script.index("Move-Item -LiteralPath $temp -Destination $manifestPath")
