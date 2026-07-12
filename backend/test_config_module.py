from __future__ import annotations

import os
from pathlib import Path

from backend.app.config import env_bool, load_local_env, sqlite_path_from_database_url


def test_sqlite_path_parsing(tmp_path: Path) -> None:
    assert sqlite_path_from_database_url("sqlite:///C:/data/app.sqlite3") == Path("C:/data/app.sqlite3")
    assert sqlite_path_from_database_url("sqlite:C:/data/app.sqlite3") == Path("C:/data/app.sqlite3")
    assert sqlite_path_from_database_url("C:/data/app.sqlite3") == Path("C:/data/app.sqlite3")
    assert sqlite_path_from_database_url(None, tmp_path) == tmp_path / "onenode.sqlite3"


def test_env_bool(monkeypatch) -> None:
    monkeypatch.delenv("CONFIG_BOOL_TEST", raising=False)
    assert env_bool("CONFIG_BOOL_TEST") is False
    assert env_bool("CONFIG_BOOL_TEST", True) is True
    for value in ("1", "true", "YES", "on"):
        monkeypatch.setenv("CONFIG_BOOL_TEST", value)
        assert env_bool("CONFIG_BOOL_TEST") is True
    monkeypatch.setenv("CONFIG_BOOL_TEST", "false")
    assert env_bool("CONFIG_BOOL_TEST", True) is False


def test_local_env_loader_does_not_override_process_environment(tmp_path: Path, monkeypatch) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "# comment\nCONFIG_EXISTING=file-value\nCONFIG_NEW='new value'\nINVALID_LINE\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("CONFIG_EXISTING", "process-value")
    monkeypatch.delenv("CONFIG_NEW", raising=False)

    load_local_env(tmp_path)

    assert os.environ["CONFIG_EXISTING"] == "process-value"
    assert os.environ["CONFIG_NEW"] == "new value"
