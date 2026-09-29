from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = ROOT / "ops" / "docker" / "dev" / "Dockerfile.backend"
DOCKERIGNORE = ROOT / ".dockerignore"
COMPOSE = ROOT / "ops" / "docker" / "dev" / "compose.yml"
ENV_EXAMPLE = ROOT / "ops" / "docker" / "dev" / ".env.example"
AGENT_SANDBOX = ROOT / "ops" / "docker" / "agent-sandbox"
BASE_SHA = "e62dd06ef68f8d68041adaed5287a0f583289e68"
BASE_IMAGE = "python:3.11.9-slim-bookworm"
BASE_DIGEST = "sha256:8fb099199b9f2d70342674bd9dbccd3ed03a258f26bbd1d556822c6dfc60c317"

CREDENTIAL_NAMES = (
    "OPENROUTER_API_KEY",
    "TELEGRAM_BOT_TOKEN",
    "MAX_BOT_TOKEN",
    "SMTP_PASSWORD",
    "YOOKASSA_SECRET_KEY",
    "SESSION_HMAC_SECRET",
    "ADMIN_ONE_TIME_CODE",
)


def _dockerfile() -> str:
    return DOCKERFILE.read_text(encoding="utf-8")


def _compose() -> str:
    return COMPOSE.read_text(encoding="utf-8")


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
        "**/*.sqlite3",
        "**/*.sqlite-wal",
        "**/*.sqlite-shm",
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

def test_compose_has_no_runtime_contract_yet() -> None:
    text = _compose()
    forbidden_keys = (
        "ports",
        "volumes",
        "networks",
        "environment",
        "env_file",
        "secrets",
        "configs",
        "healthcheck",
        "depends_on",
        "restart",
        "privileged",
        "network_mode",
        "pid",
        "ipc",
        "command",
        "entrypoint",
    )
    for key in forbidden_keys:
        assert re.search(rf"(?m)^\s*{re.escape(key)}\s*:", text) is None
    assert "ops/docker/agent-sandbox" not in text

def test_env_example_is_non_secret_build_template_only() -> None:
    assert ENV_EXAMPLE.is_file()
    values = _env_example()
    assert values == {
        "IZO_SOURCE_SHA": "<exact-40-hex-git-sha>",
        "IZO_COMPOSE_PROJECT": "izo-asa-dev-<unique-suffix>",
    }

    combined = _compose() + "\n" + ENV_EXAMPLE.read_text(encoding="utf-8")
    for name in CREDENTIAL_NAMES:
        assert name not in combined
