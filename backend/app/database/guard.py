"""Pure checks used to prevent startup against the wrong SQLite database."""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from ..config import sqlite_path_from_database_url


class DbGuardError(RuntimeError):
    """Raised when a production-like startup database fails a safety check."""


def mask_database_path(path: Path) -> str:
    try:
        resolved = path.resolve()
        return f".../{resolved.parent.name}/{resolved.name}"
    except Exception:
        return f".../{path.name}"


def database_size_mb(path: Path) -> float:
    try:
        return round(path.stat().st_size / 1024 / 1024, 2)
    except OSError:
        return 0.0


def parse_allowed_database_paths(raw: str) -> set[Path]:
    parts = [part.strip() for part in re.split(r"[;|]", raw) if part.strip()]
    return {sqlite_path_from_database_url(part).resolve() for part in parts}


def _single_line_text(value: Any, limit: int) -> str:
    if value is None:
        return ""
    text = " ".join(str(value).replace("\r", " ").replace("\n", " ").split())
    return text[:limit] + ("…" if len(text) > limit else "")


def safe_guard_payload(status: Mapping[str, Any]) -> dict[str, Any]:
    """Return the non-sensitive DB Guard subset exposed by API responses."""
    return {
        "ok": bool(status.get("ok")),
        "status": str(status.get("status") or "unknown"),
        "reason": _single_line_text(status.get("reason") or "", 160),
        "migration_status": str(status.get("migration_status") or "unknown"),
    }


def preflight_sqlite_database(
    *,
    production_like: bool,
    database_url: str,
    path: Path,
    allowed_paths: set[Path],
    min_size_mb: float,
) -> None:
    """Validate the configured SQLite file before additive migrations run."""
    if not production_like:
        return
    if not database_url.strip():
        raise DbGuardError("DATABASE_URL is required in production/live mode.")
    resolved = path.resolve()
    if allowed_paths and resolved not in allowed_paths:
        raise DbGuardError(f"DB path is not in production allowlist: {mask_database_path(resolved)}")
    if not path.exists():
        raise DbGuardError(f"DB file does not exist: {mask_database_path(path)}")
    min_bytes = int(min_size_mb * 1024 * 1024)
    try:
        size = path.stat().st_size
    except OSError:
        size = 0
    if size < min_bytes:
        raise DbGuardError(f"DB file is suspiciously small: {database_size_mb(path)} MB")


def collect_sqlite_guard_status(
    *,
    path: Path,
    connection_factory: Callable[[], sqlite3.Connection],
    required_tables: set[str],
    required_columns: Mapping[str, set[str]],
    production_like: bool,
    min_users: int,
    min_active_admins: int,
) -> dict[str, Any]:
    """Inspect the migrated schema and return a serializable safety status."""
    status: dict[str, Any] = {
        "ok": False,
        "status": "fail",
        "reason": "",
        "migration_status": "fail",
        "db_type": "sqlite",
        "db_path": mask_database_path(path),
        "db_size_mb": database_size_mb(path),
        "users_count": 0,
        "active_admin_count": 0,
    }
    if not path.exists():
        status["reason"] = f"DB file does not exist: {mask_database_path(path)}"
        return status

    with connection_factory() as conn:
        tables = {row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        missing_tables = sorted(required_tables - tables)
        if missing_tables:
            status["reason"] = f"Missing required tables: {', '.join(missing_tables)}"
            return status
        for table, required in required_columns.items():
            columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
            missing_columns = sorted(required - columns)
            if missing_columns:
                status["reason"] = f"Missing required columns: {table}.{', '.join(missing_columns)}"
                return status
        users_count = int(conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"] or 0)
        active_admin_count = int(
            conn.execute("SELECT COUNT(*) AS c FROM users WHERE role='admin' AND COALESCE(banned,0)=0").fetchone()["c"] or 0
        )
        status["users_count"] = users_count
        status["active_admin_count"] = active_admin_count
        if production_like and users_count < min_users:
            status["reason"] = f"Users count below production minimum: {users_count}"
            return status
        if production_like and active_admin_count < min_active_admins:
            status["reason"] = f"Active admin count below production minimum: {active_admin_count}"
            return status

    status.update({"ok": True, "status": "ok", "reason": "ok", "migration_status": "ok"})
    return status
