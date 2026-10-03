from __future__ import annotations

import re
import subprocess
from pathlib import Path

from tools.agent_system.env_runtime import EMPTY_CREDENTIAL_KEYS

ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = ROOT / "ops" / "docker" / "dev" / "Dockerfile.backend"
DOCKERIGNORE = ROOT / ".dockerignore"
COMPOSE = ROOT / "ops" / "docker" / "dev" / "compose.yml"
ENV_EXAMPLE = ROOT / "ops" / "docker" / "dev" / ".env.example"
AGENT_SANDBOX = ROOT / "ops" / "docker" / "agent-sandbox"
BASE_SHA = "126d276ef1a9fc09935125203288c013627457ed"
BASE_IMAGE = "python:3.11.9-slim-bookworm"
BASE_DIGEST = "sha256:8fb099199b9f2d70342674bd9dbccd3ed03a258f26bbd1d556822c6dfc60c317"

CREDENTIAL_NAMES = EMPTY_CREDENTIAL_KEYS


def _dockerfile() -> str:
    return DOCKERFILE.read_text(encoding="utf-8")


def _compose() -> str:
    return COMPOSE.read_text(encoding="utf-8")


def _compose_environment() -> dict[str, str]:
    values: dict[str, str] = {}
    in_environment = False
    for line in _compose().splitlines():
        if line == "    environment:":
            in_environment = True
            continue
        if in_environment and line and not line.startswith("      "):
            break
        if not in_environment:
            continue
        match = re.fullmatch(r"      ([A-Za-z0-9_]+):(?: (.*))?", line)
        if match:
            values[match.group(1)] = (match.group(2) or "").strip()
    return values


def _env_example() -> dict[str, str]:
    return dict(
        line.split("=", 1)
        for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )


def _dockerignore_lines() -> set[str]:
    return {
        line.strip()
        for line in DOCKERIGNORE.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }


def test_dockerfile_exists_and_pins_python_3119() -> None:
    assert DOCKERFILE.is_file()
    text = _dockerfile()
    from_lines = [
        line.strip() for line in text.splitlines() if line.strip().startswith("FROM ")
    ]
    assert len(from_lines) == 1
    assert from_lines[0] == f"FROM {BASE_IMAGE}@{BASE_DIGEST}"
    assert re.fullmatch(
        r"FROM python:3\.11\.9-slim-bookworm@sha256:[0-9a-f]{64}",
        from_lines[0],
    )


def test_copy_boundary_is_backend_only() -> None:
    text = _dockerfile()
    assert "COPY . ." not in text
    assert "COPY ./ ./" not in text
    copy_lines = [
        line.strip() for line in text.splitlines() if line.strip().startswith("COPY ")
    ]
    assert copy_lines == [
        "COPY backend/requirements.txt /tmp/requirements.txt",
        "COPY --chown=10001:10001 backend/ /opt/izo/backend/",
    ]
    assert "ops/docker/agent-sandbox" not in text


def test_non_root_and_exact_source_identity_contract() -> None:
    text = _dockerfile()
    assert "ARG IZO_SOURCE_SHA" in text
    assert 'RUN test -n "${IZO_SOURCE_SHA}"' in text
    assert 'org.opencontainers.image.revision="${IZO_SOURCE_SHA}"' in text
    assert 'org.opencontainers.image.source="spikeal8-maker/IZO_ASA"' in text
    assert "WORKDIR /opt/izo/backend" in text
    assert "PYTHONDONTWRITEBYTECODE=1" in text
    assert "PYTHONUNBUFFERED=1" in text
    user_lines = [
        line.strip() for line in text.splitlines() if line.strip().startswith("USER ")
    ]
    assert user_lines == ["USER 10001:10001"]
    assert user_lines[-1] not in {"USER root", "USER 0", "USER 0:0"}


def test_dockerfile_has_no_build_credentials() -> None:
    text = _dockerfile()
    for name in CREDENTIAL_NAMES:
        assert name not in text


def test_dockerignore_is_safe_and_keeps_backend_source() -> None:
    lines = _dockerignore_lines()
    required = {
        "**",
        "!backend/",
        "!backend/**",
        ".git",
        ".runtime",
        "**/.env",
        "**/.env.*",
        "**/.venv",
        "**/node_modules",
        "**/__pycache__",
        "**/*.pyc",
        "**/*.sqlite",
        "**/*.sqlite-wal",
        "**/*.sqlite-shm",
        "**/*.sqlite-journal",
        "**/*.sqlite3",
        "**/*.sqlite3-wal",
        "**/*.sqlite3-shm",
        "**/*.sqlite3-journal",
        "**/*.db",
        "**/*.db-wal",
        "**/*.db-shm",
        "**/*.db-journal",
        "**/media/",
        "**/secrets/",
        "**/.pytest_cache",
        "**/playwright-report/",
        "**/screenshots/",
    }
    assert required <= lines
    assert "backend/**" not in lines
    assert "backend/requirements.txt" not in lines
    assert (ROOT / "backend" / "requirements.txt").is_file()
    assert (ROOT / "backend" / "main.py").is_file()


def test_agent_sandbox_is_untouched_and_not_reused() -> None:
    assert (AGENT_SANDBOX / "Dockerfile").is_file()
    worktree = subprocess.run(
        ["git", "-C", str(ROOT), "status", "--porcelain", "--", "ops/docker/agent-sandbox"],
        text=True,
        capture_output=True,
        check=False,
    )
    assert worktree.returncode == 0
    assert worktree.stdout.strip() == ""

    branch_diff = subprocess.run(
        [
            "git",
            "-C",
            str(ROOT),
            "diff",
            "--name-only",
            f"{BASE_SHA}...HEAD",
            "--",
            "ops/docker/agent-sandbox",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert branch_diff.returncode == 0
    assert branch_diff.stdout.strip() == ""

def test_compose_build_only_backend_contract() -> None:
    assert COMPOSE.is_file()
    text = _compose()
    lines = text.splitlines()
    assert lines[0] == "name: ${IZO_COMPOSE_PROJECT:?IZO_COMPOSE_PROJECT is required}"

    services: list[str] = []
    in_services = False
    for line in lines:
        if line == "services:":
            in_services = True
            continue
        if in_services and line and not line.startswith(" "):
            break
        match = re.fullmatch(r"  ([A-Za-z0-9_-]+):", line)
        if in_services and match:
            services.append(match.group(1))

    assert services == ["backend"]
    assert "      context: ../../.." in text
    assert "      dockerfile: ops/docker/dev/Dockerfile.backend" in text
    assert "        IZO_SOURCE_SHA: ${IZO_SOURCE_SHA:?IZO_SOURCE_SHA is required}" in text
    assert "    image: izo-asa-dev-backend:${IZO_SOURCE_SHA:?IZO_SOURCE_SHA is required}" in text

def test_compose_runtime_c_isolated_contract() -> None:
    text = _compose()
    assert "    network_mode: none" in text
    assert '    user: "10001:10001"' in text
    assert '    restart: "no"' in text
    assert "    cpus: 2.0" in text
    assert "    mem_limit: 2g" in text
    assert "    pids_limit: 128" in text
    assert re.search(r"(?m)^    cap_drop:\s*\n      - ALL$", text)
    assert re.search(
        r"(?m)^    security_opt:\s*\n      - no-new-privileges:true$", text
    )

    forbidden_keys = (
        "ports",
        "expose",
        "tmpfs",
        "networks",
        "env_file",
        "secrets",
        "configs",
        "healthcheck",
        "depends_on",
        "privileged",
        "pid",
        "ipc",
        "devices",
        "gpus",
        "command",
        "entrypoint",
    )
    for key in forbidden_keys:
        assert re.search(rf"(?m)^\s*{re.escape(key)}\s*:", text) is None
    assert "network_mode: host" not in text
    assert "ops/docker/agent-sandbox" not in text


def test_compose_runtime_c_environment_is_sanitized() -> None:
    env = _compose_environment()
    expected = {
        "DATABASE_URL": "/home/izo/data/app.sqlite3",
        "MEDIA_DIR": "/home/izo/media",
        "IZO_SECRET_DIR": "/home/izo/secrets",
        "APP_ENV": "test",
        "ENV": "test",
        "MODE": "test",
        "BOT_MODE": "disabled",
        "BOT_UPDATES_MODE": "disabled",
        "TELEGRAM_POLLING_ENABLED": '"false"',
        "MAX_UPDATES_MODE": "disabled",
        "MAX_POLLING_ENABLED": '"false"',
        "LOCAL_LTX_ENABLED": '"false"',
        "EMAIL_OTP_DEBUG_RETURN_CODE": '"false"',
        "COMFYUI_BASE_URL": "http://127.0.0.1:1",
        "OLLAMA_BASE_URL": "http://127.0.0.1:1",
        "QWEN_ASR_BASE_URL": "http://127.0.0.1:1",
        "LOCAL_LTX_COMFYUI_BASE_URL": "http://127.0.0.1:1",
        "OPENROUTER_BASE_URL": "http://127.0.0.1:1",
        "MAX_API_BASE_URL": "http://127.0.0.1:1",
        "CBR_DAILY_XML_URL": "http://127.0.0.1:1",
        "USD_RUB_FALLBACK_URL": "http://127.0.0.1:1",
        "MAX_WEBHOOK_URL": '""',
        "BACKEND_PUBLIC_URL": '""',
        "RUNTIME_ALERT_WEBHOOK_URL": '""',
        "HTTP_PROXY": '""',
        "HTTPS_PROXY": '""',
        "ALL_PROXY": '""',
        "http_proxy": '""',
        "https_proxy": '""',
        "all_proxy": '""',
        "NO_PROXY": "localhost,127.0.0.1",
        "no_proxy": "localhost,127.0.0.1",
    }
    for key, value in expected.items():
        assert env.get(key) == value
    for name in CREDENTIAL_NAMES:
        assert env.get(name) == '""'

def test_env_example_is_non_secret_build_template_only() -> None:
    assert ENV_EXAMPLE.is_file()
    values = _env_example()
    assert values == {
        "IZO_SOURCE_SHA": "<exact-40-hex-git-sha>",
        "IZO_COMPOSE_PROJECT": "izo-asa-dev-<unique-suffix>",
    }

    env_text = ENV_EXAMPLE.read_text(encoding="utf-8")
    for name in CREDENTIAL_NAMES:
        assert name not in env_text

def test_slice_d_named_volume_contract_and_non_root_mountpoints() -> None:
    dockerfile = _dockerfile()
    compose = _compose()
    assert "RUN install -d -o 10001 -g 10001 /home/izo/data /home/izo/media" in dockerfile
    assert "      - type: volume\n        source: sqlite-data\n        target: /home/izo/data" in compose
    assert "      - type: volume\n        source: media-data\n        target: /home/izo/media" in compose
    assert "\nvolumes:\n  sqlite-data:" in compose
    assert "\n  media-data:" in compose
    assert "io.izo.state: sqlite" in compose
    assert "io.izo.state: media" in compose
    assert "type: bind" not in compose
    assert "IZO_SECRET_DIR: /home/izo/secrets" in compose
    assert "source: secrets" not in compose
    assert "target: /home/izo/secrets" not in compose


def test_slice_d_agent_cli_is_project_scoped_exact_sha_and_preserves_volumes_on_down() -> None:
    text = (ROOT / "tools" / "agent.ps1").read_text(encoding="utf-8")
    assert '"docker-dev-up"' in text
    assert '"docker-dev-down"' in text
    assert "-DockerProject is required for Docker DEV lifecycle." in text
    assert "-SourceSha must be an exact lowercase 40-hex Git SHA." in text
    assert '$currentHead -cne $SourceSha' in text
    assert '"--project-name", $DockerProject' in text
    assert '"--context", "desktop-linux"' in text
    assert '$composeArguments += @("up", "-d", "--build", "backend")' in text
    assert '$composeArguments += @("down")' in text
    assert "--volumes" not in text
    assert "docker system prune" not in text
    assert "docker container prune" not in text
    assert "docker volume prune" not in text
    assert "docker network prune" not in text

def test_slice_d_provenance_guard_blocks_dirty_up_but_not_down() -> None:
    text = (ROOT / "tools" / "agent.ps1").read_text(encoding="utf-8")
    up_guard = re.search(
        r'if \(\$Command -eq "docker-dev-up"\) \{\s*'
        r'\$sourceStatus = @\(& git -C \$RepoRoot status --porcelain\)\s*'
        r'if \(\$LASTEXITCODE -ne 0\) \{\s*'
        r'throw "DOCKER_DEV_SOURCE_STATUS_FAILED"\s*'
        r'\}\s*'
        r'if \(\$sourceStatus\.Count -ne 0\) \{\s*'
        r'throw "DOCKER_DEV_SOURCE_DIRTY"\s*'
        r'\}\s*'
        r'\}',
        text,
        re.DOTALL,
    )
    assert up_guard is not None
    assert text.index("$currentHead -cne $SourceSha") < up_guard.start()
    assert up_guard.end() < text.index("$dockerCommand = Get-Command docker")
    assert text.count("git -C $RepoRoot status --porcelain") == 1
    assert '$composeArguments += @("down")' in text
    assert "--volumes" not in text
    assert "docker system prune" not in text
    assert "docker container prune" not in text
    assert "docker volume prune" not in text
    assert "docker network prune" not in text
