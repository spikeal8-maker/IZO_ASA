from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
FULL_SHA_ACTION = re.compile(r"uses: actions/[a-z-]+@[0-9a-f]{40} # v\d+\.\d+\.\d+")


def workflow_source() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_ci_workflow_uses_pinned_windows_toolchain_and_lockfiles() -> None:
    source = workflow_source()

    assert "runs-on: windows-latest" in source
    assert "timeout-minutes: 30" in source
    assert "python-version-file: .python-version" in source
    assert "node-version-file: .node-version" in source
    assert "cache-dependency-path: backend/requirements.txt" in source
    assert "cache-dependency-path: frontend/package-lock.json" in source
    assert "python -m pip install --requirement backend/requirements.txt" in source
    assert "working-directory: frontend" in source
    assert "run: npm ci" in source
    assert "run: npx playwright install chromium" in source
    assert (ROOT / ".python-version").read_text(encoding="utf-8").strip() == "3.11.9"
    assert (ROOT / ".node-version").read_text(encoding="utf-8").strip() == "24.14.1"
    assert len(FULL_SHA_ACTION.findall(source)) == 3
    assert "persist-credentials: false" in source


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
    assert "self-hosted" not in source
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


def test_ci_triggers_are_bounded_to_main_and_manual_runs() -> None:
    source = workflow_source()

    assert "push:\n    branches: [main]" in source
    assert "pull_request:\n    branches: [main]" in source
    assert "workflow_dispatch:" in source
    assert "cancel-in-progress: true" in source
