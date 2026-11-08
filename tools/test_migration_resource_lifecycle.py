"""Regression checks for temporary secret-migration resource ownership."""

from __future__ import annotations

import shutil
import sqlite3
import subprocess
from contextlib import nullcontext
from pathlib import Path

import pytest

from tools import test_migrate_openrouter_secret as migration_tests


@pytest.mark.parametrize("invalid_value", [False, True])
def test_database_owner_closes_connection_on_success_and_insert_error(
    tmp_path: Path, monkeypatch, invalid_value: bool
):
    original_connect = sqlite3.connect
    connections = []

    def tracking_connect(path):
        connection = original_connect(path)
        connections.append(connection)
        return connection

    monkeypatch.setattr(migration_tests.sqlite3, "connect", tracking_connect)
    expected = pytest.raises(sqlite3.ProgrammingError) if invalid_value else nullcontext()
    try:
        with expected:
            migration_tests.create_database(
                tmp_path / "owned.sqlite3",
                object() if invalid_value else "synthetic-test-value",
            )
        assert len(connections) == 1
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            connections[0].execute("SELECT 1")
    finally:
        for connection in connections:
            connection.close()


@pytest.mark.parametrize("body_fails", [False, True])
def test_directory_owner_restores_acl_and_removes_tree_before_return(
    tmp_path: Path, monkeypatch, body_fails: bool
):
    path = tmp_path / "owned-secrets"
    restored = []

    def restore_acl(directory):
        assert (directory / "synthetic.dpapi.json").read_text() == "ciphertext"
        restored.append(directory)

    monkeypatch.setattr(migration_tests, "_restore_temporary_acl", restore_acl)
    expected = pytest.raises(AssertionError, match="body failure") if body_fails else nullcontext()
    with expected:
        with migration_tests._owned_secret_directory(path) as directory:
            (directory / "synthetic.dpapi.json").write_text("ciphertext")
            if body_fails:
                raise AssertionError("body failure")
    assert restored == [path]
    assert not path.exists()


def test_acl_restoration_error_is_not_suppressed_or_retried(tmp_path: Path, monkeypatch):
    path = tmp_path / "owned-secrets"
    calls = []
    failure = subprocess.CalledProcessError(5, ["icacls", str(path), "/reset", "/T"])

    def fail_restore(directory):
        calls.append(directory)
        raise failure

    monkeypatch.setattr(migration_tests, "_restore_temporary_acl", fail_restore)
    try:
        with pytest.raises(subprocess.CalledProcessError) as captured:
            with migration_tests._owned_secret_directory(path):
                raise AssertionError("original body failure")
        assert captured.value is failure
        assert isinstance(captured.value.__context__, AssertionError)
        assert calls == [path]
        assert path.is_dir()
    finally:
        shutil.rmtree(path)


def test_directory_removal_error_is_not_suppressed_or_retried(tmp_path: Path, monkeypatch):
    path = tmp_path / "owned-secrets"
    restored = []
    removals = []
    failure = PermissionError("synthetic locked directory")

    def fail_remove(directory):
        removals.append(directory)
        raise failure

    try:
        with monkeypatch.context() as patch:
            patch.setattr(migration_tests, "_restore_temporary_acl", restored.append)
            patch.setattr(migration_tests.shutil, "rmtree", fail_remove)
            with pytest.raises(PermissionError) as captured:
                with migration_tests._owned_secret_directory(path):
                    pass
        assert captured.value is failure
        assert restored == [path]
        assert removals == [path]
        assert path.is_dir()
    finally:
        shutil.rmtree(path)
