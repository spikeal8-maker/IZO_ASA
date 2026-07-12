"""Mandatory isolation from the live SQLite database and media tree."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolate_live_runtime_paths(tmp_path: Path, monkeypatch):
    """Redirect every backend test, including forgotten fixtures, to temp storage."""
    import main

    media = tmp_path / "_isolated_runtime_media"
    avatars = media / "avatars"
    avatars.mkdir(parents=True)
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "_isolated_runtime.sqlite3")
    monkeypatch.setattr(main, "MEDIA", media)
    monkeypatch.setattr(main, "AVATAR_DIR", avatars)
