from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
FULL_SHA_ACTION = re.compile(r"uses: actions/[a-z-]+@[0-9a-f]{40} # v\d+\.\d+\.\d+")


def workflow_source() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_ci_workflow_uses_pinned_self_hosted_windows_toolchain_and_lockfiles() -> None:
    source = workflow_source()

    assert "runs-on: [self-hosted, windows, x64, izo-ci]" in source
    assert "timeout-minutes: 45" in source
    assert "$expectedPython = (Get-Content .python-version -Raw).Trim()" in source
    assert "$expectedNode = (Get-Content .node-version -Raw).Trim()" in source
    assert "Python version mismatch" in source
    assert "Node version mismatch" in source
    assert "cache:" not in source
    assert "python -m pip install --requirement backend/requirements.txt" in source
    assert "working-directory: frontend" in source
    assert "run: npm ci" in source
    assert "run: npx playwright install chromium" in source
    assert (ROOT / ".python-version").read_text(encoding="utf-8").strip() == "3.11.9"
    assert (ROOT / ".node-version").read_text(encoding="utf-8").strip() == "24.14.1"
    assert len(FULL_SHA_ACTION.findall(source)) == 1
    assert "persist-credentials: false" in source
    assert "clean: true" in source
    assert "fetch-depth: 1" in source
    assert source.count("shell: powershell") == 4
    assert "shell: pwsh" not in source


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
    assert "IZO_CI_RUNNER_TRUSTED" in source
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
