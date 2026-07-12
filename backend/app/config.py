"""Pure configuration helpers extracted from the legacy backend entrypoint.

This module must stay safe to import: it does not create directories, connect to
SQLite, start workers or import the FastAPI application.
"""

from __future__ import annotations

import os
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]


def load_local_env(root: Path | None = None) -> None:
    """Load `root/.env` without overriding process-level environment values."""
    env_path = (root or BACKEND_ROOT) / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def sqlite_path_from_database_url(value: str | None, root: Path | None = None) -> Path:
    raw = (value or "").strip()
    if raw.startswith("sqlite:///"):
        return Path(raw.replace("sqlite:///", "", 1))
    if raw.startswith("sqlite:"):
        return Path(raw.replace("sqlite:", "", 1))
    return Path(raw) if raw else (root or BACKEND_ROOT) / "onenode.sqlite3"
