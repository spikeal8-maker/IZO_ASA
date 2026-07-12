"""Startup storage maintenance must never touch live media during pytest."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

import main
from app.storage.maintenance import startup_storage_maintenance_allowed


def test_storage_maintenance_policy_blocks_pytest_and_explicit_disable():
    assert startup_storage_maintenance_allowed({"PYTEST_CURRENT_TEST": "test::case (call)"}) is False
    assert startup_storage_maintenance_allowed({"IZO_DISABLE_STARTUP_STORAGE_MAINTENANCE": "true"}) is False
    assert startup_storage_maintenance_allowed({}) is True


def test_backend_conftest_redirects_live_database_and_media(tmp_path: Path):
    assert main.DB_PATH.parent == tmp_path
    assert main.MEDIA.parent == tmp_path
    assert main.AVATAR_DIR.parent == main.MEDIA


def test_testclient_startup_skips_all_storage_maintenance(tmp_path: Path, monkeypatch):
    database = tmp_path / "startup-safety.sqlite3"
    monkeypatch.setattr(main, "DB_PATH", database)
    monkeypatch.setattr(main, "worker_started", True)
    monkeypatch.setattr(main, "BOT_UPDATES_MODE", "disabled")
    monkeypatch.setattr(main, "MAX_UPDATES_MODE", "disabled")
    monkeypatch.setattr(main, "start_bot_polling_tasks", lambda: [])

    def forbidden(*args, **kwargs):
        raise AssertionError("pytest startup must not run storage maintenance")

    for name in (
        "recover_missing_optimized_gallery_files",
        "repair_missing_gallery_thumbnails",
        "repair_missing_user_avatars",
        "cleanup_orphan_image_sources",
        "reconcile_image_source_availability",
        "repair_unavailable_image_sources_from_jobs",
        "optimize_existing_gallery_storage",
    ):
        monkeypatch.setattr(main, name, forbidden)

    with TestClient(main.app) as client:
        assert client.get("/api/health").status_code == 200
