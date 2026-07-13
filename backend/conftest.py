"""Mandatory isolation from the live SQLite database and media tree."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolate_live_runtime_paths(tmp_path: Path, monkeypatch):
    """Redirect every backend test, including forgotten fixtures, to temp storage."""
    import main
    from app.security.secret_store import DpapiSecretStore

    media = tmp_path / "_isolated_runtime_media"
    avatars = media / "avatars"
    avatars.mkdir(parents=True)
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "_isolated_runtime.sqlite3")
    monkeypatch.setattr(main, "MEDIA", media)
    monkeypatch.setattr(main, "AVATAR_DIR", avatars)
    monkeypatch.setattr(
        main,
        "OPENROUTER_SECRET_STORE",
        DpapiSecretStore(
            tmp_path / "_isolated_secrets",
            protector=lambda value: b"test:" + value,
            unprotector=lambda value: value.removeprefix(b"test:"),
            acl_setter=lambda _path: None,
        ),
    )
