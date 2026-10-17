from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
FULL_SHA_ACTION = re.compile(r"uses: actions/[a-z-]+@[0-9a-f]{40}(?=\s|$)")


def workflow_source() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_ci_workflow_uses_pinned_hosted_windows_toolchain_and_lockfiles() -> None:
    source = workflow_source()

    assert "runs-on: windows-2022" in source
    assert "self-hosted" not in source
    assert "actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97" in source
    assert "actions/setup-node@820762786026740c76f36085b0efc47a31fe5020" in source
    assert "python-version-file: .python-version" in source
    assert "node-version-file: .node-version" in source
    assert source.count("architecture: x64") == 2
    assert source.index("Check out repository") < source.index("Configure pinned Python")
    assert source.index("Configure pinned Node") < source.index("Assert pinned local toolchain")
    assert "timeout-minutes: 45" in source
    assert "$expectedPython = (Get-Content .python-version -Raw).Trim()" in source
    assert "$expectedNode = (Get-Content .node-version -Raw).Trim()" in source
    assert "Python version mismatch" in source
    assert "Node version mismatch" in source
    assert not re.search(r"^\s+cache:", source, re.MULTILINE)
    assert "package-manager-cache: false" in source
    assert "python -m pip install --requirement backend/requirements.txt" in source
    assert "working-directory: frontend" in source
    assert "run: npm ci" in source
    assert "run: npx playwright install chromium" in source
    assert (ROOT / ".python-version").read_text(encoding="utf-8").strip() == "3.11.9"
    assert (ROOT / ".node-version").read_text(encoding="utf-8").strip() == "24.14.1"
    assert len(FULL_SHA_ACTION.findall(source)) == 5
    assert "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02 # v4.6.2" in source
    assert "persist-credentials: false" in source
    assert "Enforce package scope" in source
    assert "tools.agent_system.enforce" in source
    assert "IZO_PR_BASE_SHA" in source
    assert "clean: true" in source
    assert "fetch-depth: 0" in source
    assert source.count("shell: powershell") == 7
    assert "shell: pwsh" not in source


def test_ci_runner_admission_uses_github_hosted_context_before_checkout() -> None:
    source = workflow_source()
    admission = source.split("- name: Assert GitHub-hosted Windows runner", 1)[1].split(
        "- name: Check out repository", 1
    )[0]

    assert "IZO_RUNNER_ENVIRONMENT: ${{ runner.environment }}" in admission
    assert "IZO_RUNNER_OS: ${{ runner.os }}" in admission
    assert "IZO_RUNNER_ARCH: ${{ runner.arch }}" in admission
    assert '$env:GITHUB_ACTIONS -ne "true" -or' in admission
    assert '$env:IZO_RUNNER_ENVIRONMENT -ne "github-hosted" -or' in admission
    assert '$env:IZO_RUNNER_OS -ne "Windows" -or' in admission
    assert '$env:IZO_RUNNER_ARCH -ne "X64"' in admission
    assert 'throw "CI requires a GitHub-hosted Windows X64 runner."' in admission


def test_ci_workflow_enforces_both_npm_audits_and_uploads_exact_head_evidence() -> None:
    source = workflow_source()

    assert "& $npm audit --json" in source
    assert "& $npm audit --omit=dev --json" in source
    assert "NPM_AUDIT_HEAD=$candidateHead" in source
    assert "steps.supply_chain_range.outputs.exact_head" in source
    assert "--full-input $fullJson" in source
    assert "--production-input $productionJson" in source
    assert "--policy ../architecture/security-policy.json" in source
    assert 'exactHead = $candidateHead' in source
    assert 'workflowRun = [string]$env:GITHUB_RUN_ID' in source
    assert 'workflowAttempt = [int]$env:GITHUB_RUN_ATTEMPT' in source
    assert 'nodeVersion = $nodeVersion' in source
    assert 'npmVersion = $npmVersion' in source
    assert 'scannerExitCodes = [ordered]@{' in source
    assert "npm-audit-full.json" in source
    assert "npm-audit-production.json" in source
    assert "npm-audit-normalized.json" in source
    assert "metadata.json" in source
    assert "if-no-files-found: error" in source
    assert "retention-days: 30" in source
    assert "supply-chain-evidence-" in source
    assert "python-audit.json" in source
    assert "frontend-licenses.json" in source
    assert "backend-licenses.json" in source
    assert "secret-scan-redacted.json" in source
    assert "supply-chain-floor-normalized.json" in source
    assert "id: npm_audit" in source
    assert "if: always() && steps.npm_audit.outcome != 'skipped'" in source


def test_ci_workflow_calls_only_deterministic_verifier_mode() -> None:
    source = workflow_source()

    assert r".\tools\verify.ps1 -Mode CI" in source
    assert "-Mode Full" not in source
    assert "-Mode Quick" not in source
    assert "restart-backend.ps1" not in source
    assert "start-public" not in source
    assert "127.0.0.1:8000" not in source
    assert "BACKUP" not in source


def test_ci_workflow_is_read_only_and_has_no_secret_or_provider_access() -> None:
    source = workflow_source()

    assert "permissions:\n  contents: read" in source
    assert "pull_request_target" not in source
    assert "secrets." not in source
    assert "IZO_CI_RUNNER_TRUSTED" not in source
    assert 'github.actor == \'spikeal8-maker\'' in source
    assert "github.event.pull_request.head.repo.full_name == github.repository" in source
    assert "git push" not in source
    assert "deploy" not in source.lower()
    assert '$env:BOT_UPDATES_MODE = "disabled"' in source
    assert '$env:MAX_UPDATES_MODE = "disabled"' in source
    assert '$env:COMFYUI_REQUIRED = "false"' in source
    assert '$env:TELEGRAM_BOT_TOKEN = ""' in source
    assert '$env:MAX_BOT_TOKEN = ""' in source
    assert '$env:OPENROUTER_API_KEY = ""' in source
    assert '$env:SESSION_HMAC_SECRET = ""' in source
    assert '$env:EMAIL_PROVIDER = ""' in source
    assert '$env:DATABASE_URL = Join-Path $env:RUNNER_TEMP' in source
    assert '$env:MEDIA_DIR = Join-Path $env:RUNNER_TEMP' in source
    assert '$env:IZO_SECRET_DIR = Join-Path $env:RUNNER_TEMP' in source
    assert "Remove temporary CI data" in source
    assert "if: always()" in source


def test_ci_triggers_are_bounded_to_main_and_manual_runs() -> None:
    source = workflow_source()

    assert "push:\n    branches: [main]" in source
    assert "pull_request:\n    branches: [main]" in source
    assert "workflow_dispatch:" in source
    assert "cancel-in-progress: true" in source


def test_ci_workflow_runs_pinned_temporary_python_license_and_secret_scanners() -> None:
    source = workflow_source()

    assert "pip-audit==2.10.1" in source
    assert "pip-licenses==5.5.5" in source
    assert "license-checker-rseidelsohn@5.0.1" in source
    assert "gitleaks_8.30.1_windows_x64.zip" in source
    assert "d29144deff3a68aa93ced33dddf84b7fdc26070add4aa0f4513094c8332afc4e" in source
    assert "--requirement backend/requirements.txt" in source
    assert "--from=expression" in source
    assert "--direct true" in source
    assert "--redact=100" in source
    assert "--log-opts=$logOpts" in source
    assert '$logOpts = "$baseSha..$candidateHead"' in source


def test_ci_workflow_has_runtime_synthetic_secret_redaction_acceptance() -> None:
    source = workflow_source()

    assert '$fakeSecret = "gh" + "p_"' in source
    assert "synthetic-secret-report.json" in source
    assert "$syntheticText.Contains($fakeSecret)" in source
    assert "syntheticSecretTest = $syntheticStatus" in source
    upload = source.split("Upload supply-chain evidence", 1)[1]
    assert "gitleaks-changed-scope-redacted.raw.json" not in upload


def event_range_source() -> str:
    source = workflow_source()
    return source.split("- name: Resolve supply-chain event range", 1)[1].split(
        "- name: Assert pinned local toolchain", 1
    )[0]


def test_supply_chain_event_range_matrix_covers_pr_push_and_dispatch() -> None:
    block = event_range_source()

    assert 'IZO_EVENT_NAME: ${{ github.event_name }}' in block
    assert 'IZO_EVENT_SHA: ${{ github.sha }}' in block
    assert 'IZO_PR_HEAD_SHA: ${{ github.event.pull_request.head.sha }}' in block
    assert 'IZO_PR_BASE_SHA: ${{ github.event.pull_request.base.sha }}' in block
    assert 'IZO_PUSH_BEFORE_SHA: ${{ github.event.before }}' in block

    assert '"pull_request" {' in block
    assert '$expectedHead = $env:IZO_PR_HEAD_SHA' in block
    assert '$baseSha = $env:IZO_PR_BASE_SHA' in block
    assert '$baseSource = "pull_request.base.sha"' in block

    assert '"push" {' in block
    assert '$expectedHead = $env:IZO_EVENT_SHA' in block
    assert '$before = $env:IZO_PUSH_BEFORE_SHA' in block
    assert '$baseSource = "push.before"' in block
    assert '$baseSource = "push.before-fallback-head-parent"' in block

    assert '"workflow_dispatch" {' in block
    assert '$expectedHead = $env:IZO_EVENT_SHA' in block
    assert '$baseSha = Resolve-HeadParent $actualHead' in block
    assert '$baseSource = "workflow_dispatch.head-parent"' in block


def test_supply_chain_gates_consume_resolved_range_without_pr_only_runtime_dependency() -> None:
    source = workflow_source()
    npm_block = source.split("- name: Enforce reviewed npm audit baseline", 1)[1].split(
        "- name: Enforce Python licenses and changed-scope secret floor", 1
    )[0]
    floor_block = source.split("- name: Enforce Python licenses and changed-scope secret floor", 1)[1].split(
        "- name: Upload supply-chain evidence", 1
    )[0]

    assert 'IZO_EXPECTED_HEAD_SHA: ${{ steps.supply_chain_range.outputs.exact_head }}' in npm_block
    assert "github.event.pull_request" not in npm_block

    assert 'IZO_EVENT_NAME: ${{ steps.supply_chain_range.outputs.event_name }}' in floor_block
    assert 'IZO_EXPECTED_HEAD_SHA: ${{ steps.supply_chain_range.outputs.exact_head }}' in floor_block
    assert 'IZO_SCAN_BASE_SHA: ${{ steps.supply_chain_range.outputs.base_sha }}' in floor_block
    assert 'IZO_SCAN_BASE_SOURCE: ${{ steps.supply_chain_range.outputs.base_source }}' in floor_block
    assert "github.event.pull_request" not in floor_block
    assert 'f63d596f1ccae432378f431a1d4eaab41ab81308' not in floor_block
    assert 'eventName = $eventName' in floor_block
    assert 'baseSource = $baseSource' in floor_block


def test_secret_scan_policy_uses_event_derived_range_not_package_base() -> None:
    import json

    policy = json.loads((ROOT / "architecture" / "security-policy.json").read_text(encoding="utf-8"))
    secret = policy["secretScan"]

    assert "baseSha" not in secret
    assert secret["scope"] == "event-derived-git-range-base-exclusive-head-inclusive"
    assert secret["eventRange"]["head"] == {
        "pull_request": "github.event.pull_request.head.sha",
        "push": "github.sha",
        "workflow_dispatch": "github.sha",
    }
    assert secret["eventRange"]["base"]["pull_request"] == "github.event.pull_request.base.sha"
    assert secret["eventRange"]["base"]["workflow_dispatch"] == "HEAD^"
    assert "github.event.before" in secret["eventRange"]["base"]["push"]
    assert "HEAD^ fallback" in secret["eventRange"]["base"]["push"]


def test_ci_workflow_collects_test_health_baseline_without_changing_test_semantics() -> None:
    source = workflow_source()

    assert "id: test_health" in source
    assert "TestHealthOutputPath $pytestRaw" in source
    assert "tools/test_health_audit.py normalize" in source
    assert "--raw-output $pytestRaw" in source
    assert "--metadata $metadataPath" in source
    assert "--policy architecture/test-health-policy.json" in source
    assert "--output $receiptPath" in source
    assert "test-health-evidence-" in source
    assert "pytest-raw.log" in source
    assert "test-health-receipt.json" in source
    assert "pytest-telemetry.json" in source
    assert "--telemetry $telemetryPath" in source
    assert "pytestProcessLeakCheck = $processLeakStatus" in source
    assert '$processLeakMarker = $pytestRaw + ".process-leak"' in source
    assert 'IZO_EXPECTED_HEAD_SHA: ${{ steps.supply_chain_range.outputs.exact_head }}' in source
    assert "Test-health exact-head mismatch" in source
    assert '(Join-Path $env:RUNNER_TEMP "test-health")' in source
    assert "filterwarnings" not in source.lower()
    assert "--reruns" not in source
