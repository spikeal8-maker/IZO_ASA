from __future__ import annotations

import shutil
import sqlite3
import subprocess
import sys
from contextlib import closing, contextmanager
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "migrate_openrouter_secret.py"


def create_database(path: Path, value: str) -> None:
    # A SQLite connection context commits/rolls back; it does not close.
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute("CREATE TABLE admin_secrets (key TEXT PRIMARY KEY, value TEXT, updated_at TEXT)")
        conn.execute(
            "INSERT INTO admin_secrets VALUES ('openrouter_api_key', ?, 'now')",
            (value,),
        )


def _restore_temporary_acl(path: Path) -> None:
    if sys.platform == "win32":
        subprocess.run(
            ["icacls", str(path), "/reset", "/T"],
            check=True,
            timeout=30,
        )


@contextmanager
def _owned_secret_directory(path: Path):
    # This owner creates the directory before the real store hardens its ACL.
    # Restore this disposable tree and remove it before pytest's later cleanup.
    path.mkdir()
    try:
        yield path
    finally:
        _restore_temporary_acl(path)
        shutil.rmtree(path)


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
    assert "OPENROUTER_SECRET_MIGRATION_PLAN legacyRows=1 storeConfigured=False" in result.stdout
    assert secret not in result.stdout + result.stderr
    with closing(sqlite3.connect(database)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM admin_secrets").fetchone()[0] == 1


@pytest.mark.skipif(sys.platform != "win32", reason="Windows DPAPI only")
def test_apply_encrypts_verifies_and_deletes_legacy_row(tmp_path: Path):
    database = tmp_path / "apply.sqlite3"
    secret = "sk-or-apply-private-value"
    create_database(database, secret)

    with _owned_secret_directory(tmp_path / "apply-secrets") as secret_dir:
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
        with closing(sqlite3.connect(database)) as conn:
            assert conn.execute("SELECT COUNT(*) FROM admin_secrets").fetchone()[0] == 0
        documents = list(secret_dir.glob("*.dpapi.json"))
        assert len(documents) == 1
        assert secret not in documents[0].read_text(encoding="utf-8")
    assert not secret_dir.exists()


def test_apply_locks_legacy_source_before_store_write_and_does_not_delete_a_racing_value(tmp_path, monkeypatch, capsys):
    from tools import migrate_openrouter_secret as subject

    database = tmp_path / "concurrent.sqlite3"
    fixture = "fixture-legacy-value"
    create_database(database, fixture)
    observed = []

    class ProtectedStore:
        source = "fixture-protected"
        value = ""

        def set_if_absent(self, name, value):
            with closing(sqlite3.connect(database, timeout=0)) as other, other:
                with pytest.raises(sqlite3.OperationalError, match="locked"):
                    other.execute("UPDATE admin_secrets SET value=? WHERE key=?", ("fixture-newer-value", name))
            observed.append("concurrent-writer-blocked")
            self.value = value

        def get(self, _name): return self.value
        def exists(self, _name): return bool(self.value)

    store = ProtectedStore()
    monkeypatch.setattr(subject, "create_secret_store", lambda _root: store)
    monkeypatch.setattr(subject, "load_local_env", lambda _root: None)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "--database", str(database), "--secret-dir", str(tmp_path / "secrets")])
    assert subject.main() == 0 and observed == ["concurrent-writer-blocked"]
    assert store.value == fixture
    with closing(sqlite3.connect(database)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM admin_secrets").fetchone()[0] == 0
    assert fixture not in capsys.readouterr().out


def test_plan_keeps_legacy_source_writable_and_does_not_create_a_store(tmp_path, monkeypatch, capsys):
    from tools import migrate_openrouter_secret as subject

    database = tmp_path / "plan-concurrent.sqlite3"
    create_database(database, "fixture-original")

    class PlanStore:
        def exists(self, _name):
            with closing(sqlite3.connect(database, timeout=0)) as other, other:
                other.execute("UPDATE admin_secrets SET value='fixture-newer'")
            return False

    monkeypatch.setattr(subject, "create_secret_store", lambda _root: PlanStore())
    monkeypatch.setattr(subject, "load_local_env", lambda _root: None)
    directory = tmp_path / "absent-secret-dir"
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "--database", str(database), "--secret-dir", str(directory), "--plan"])
    assert subject.main() == 0 and not directory.exists()
    with closing(sqlite3.connect(database)) as conn:
        assert conn.execute("SELECT value FROM admin_secrets").fetchone()[0] == "fixture-newer"
    assert "fixture-newer" not in capsys.readouterr().out
