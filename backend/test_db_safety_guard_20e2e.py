"""Phase 20E.2E production DB safety guard tests. Temp SQLite only."""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import main


@pytest.fixture(autouse=True)
def reset_guard(monkeypatch):
    monkeypatch.setattr(main, "APP_ENV", "development")
    monkeypatch.setattr(main, "ENV_NAME", "")
    monkeypatch.setattr(main, "MODE_NAME", "")
    monkeypatch.setattr(main, "DB_GUARD_MIN_SIZE_MB", 0.0)
    monkeypatch.setattr(main, "DB_GUARD_MIN_USERS", 1)
    monkeypatch.setattr(main, "DB_GUARD_MIN_ACTIVE_ADMINS", 1)
    main.DB_GUARD_STATUS.update({"ok": False, "status": "not_checked", "reason": "not_checked", "migration_status": "unknown"})
    yield


def make_real_like_db(path: Path) -> None:
    old = main.DB_PATH
    try:
        main.DB_PATH = path
        main.init_db()
        with main.db() as conn:
            for idx in range(4):
                conn.execute(
                    """
                    INSERT OR IGNORE INTO users
                        (id, internal_user_id, username, language, role, plan, token_balance, gallery_enabled, created_at, last_login_at)
                    VALUES (?, ?, ?, 'ru', 'user', 'mini', 50, 1, '2026-01-01', '2026-01-01')
                    """,
                    (f"web_guard_{idx}", f"iuid-guard-{idx}", f"guard{idx}"),
                )
    finally:
        main.DB_PATH = old


def test_production_missing_database_url_fails_startup(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "APP_ENV", "production")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "missing.sqlite3")
    with pytest.raises(main.DbGuardError, match="DATABASE_URL is required"):
        main.db_guard_preflight()


def test_production_tiny_wrong_sqlite_fails_guard(monkeypatch, tmp_path):
    db_file = tmp_path / "tiny.sqlite3"
    db_file.write_bytes(b"tiny")
    monkeypatch.setattr(main, "APP_ENV", "production")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")
    monkeypatch.setattr(main, "DB_PATH", db_file)
    monkeypatch.setattr(main, "DB_GUARD_MIN_SIZE_MB", 1.0)
    with pytest.raises(main.DbGuardError, match="suspiciously small"):
        main.db_guard_preflight()


def test_production_real_like_db_passes_guard(monkeypatch, tmp_path):
    db_file = tmp_path / "real_like.sqlite3"
    make_real_like_db(db_file)
    monkeypatch.setattr(main, "APP_ENV", "production")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")
    monkeypatch.setenv("DB_GUARD_ALLOWED_PATHS", str(db_file))
    monkeypatch.setattr(main, "DB_PATH", db_file)
    monkeypatch.setattr(main, "DB_GUARD_MIN_SIZE_MB", 0.0)
    monkeypatch.setattr(main, "DB_GUARD_MIN_USERS", 5)
    monkeypatch.setattr(main, "DB_GUARD_MIN_ACTIVE_ADMINS", 1)
    main.db_guard_preflight()
    status = main.collect_db_guard_status()
    assert status["ok"] is True
    assert status["users_count"] >= 5
    assert status["active_admin_count"] >= 1


def test_development_allows_local_fallback(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "APP_ENV", "development")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "dev_missing.sqlite3")
    main.db_guard_preflight()


def test_db_connection_enables_busy_timeout_foreign_keys_and_wal(monkeypatch, tmp_path):
    db_file = tmp_path / "pragma.sqlite3"
    monkeypatch.setattr(main, "DB_PATH", db_file)
    main.init_db()
    with main.db() as conn:
        busy_timeout = conn.execute("PRAGMA busy_timeout").fetchone()[0]
        foreign_keys = conn.execute("PRAGMA foreign_keys").fetchone()[0]
        journal_mode = str(conn.execute("PRAGMA journal_mode").fetchone()[0]).lower()
    assert busy_timeout == 10000
    assert foreign_keys == 1
    assert journal_mode in {"wal", "memory"}


def test_public_health_reports_readiness_without_database_details(monkeypatch, tmp_path):
    db_file = tmp_path / "health.sqlite3"
    make_real_like_db(db_file)
    monkeypatch.setattr(main, "APP_ENV", "development")
    monkeypatch.setattr(main, "DB_PATH", db_file)
    with TestClient(main.app) as client:
        res = client.get("/api/health")
    assert res.status_code == 200
    body = res.json()
    assert body["ready"] is True
    assert "database" not in body
    assert "db_guard" not in body
    dumped = str(body)
    assert str(tmp_path) not in dumped
    for forbidden in ("password_hash", "session_token_hash", "refresh_token_hash", "cookie", "token"):
        assert forbidden not in dumped

