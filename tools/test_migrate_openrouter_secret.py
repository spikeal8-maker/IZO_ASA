from __future__ import annotations

import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "migrate_openrouter_secret.py"


def create_database(path: Path, value: str) -> None:
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE admin_secrets (key TEXT PRIMARY KEY, value TEXT, updated_at TEXT)")
        conn.execute(
            "INSERT INTO admin_secrets VALUES ('openrouter_api_key', ?, 'now')",
            (value,),
        )


def test_plan_reports_only_counts_and_never_secret(tmp_path: Path):
    database = tmp_path / "plan.sqlite3"
    secret = "sk-or-plan-private-value"
    create_database(database, secret)

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--database",
            str(database),
            "--secret-dir",
            str(tmp_path / "plan-secrets"),
            "--plan",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "OPENROUTER_SECRET_MIGRATION_PLAN legacyRows=1 dpapiConfigured=False" in result.stdout
    assert secret not in result.stdout + result.stderr
    with sqlite3.connect(database) as conn:
        assert conn.execute("SELECT COUNT(*) FROM admin_secrets").fetchone()[0] == 1


@pytest.mark.skipif(sys.platform != "win32", reason="Windows DPAPI only")
def test_apply_encrypts_verifies_and_deletes_legacy_row(tmp_path: Path):
    database = tmp_path / "apply.sqlite3"
    secret_dir = tmp_path / "apply-secrets"
    secret = "sk-or-apply-private-value"
    create_database(database, secret)

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--database",
            str(database),
            "--secret-dir",
            str(secret_dir),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "OPENROUTER_SECRET_MIGRATION_OK result=migrated legacyRows=0 configured=True source=dpapi" in result.stdout
    assert secret not in result.stdout + result.stderr
    with sqlite3.connect(database) as conn:
        assert conn.execute("SELECT COUNT(*) FROM admin_secrets").fetchone()[0] == 0
    documents = list(secret_dir.glob("*.dpapi.json"))
    assert len(documents) == 1
    assert secret not in documents[0].read_text(encoding="utf-8")
