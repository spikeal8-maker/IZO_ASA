"""Preprod-only safety: full Pro gallery never silently evicts old media.

Pure synthetic fixtures. No real users, sessions, billing, network, filesystem or GPU.
"""
from __future__ import annotations

import os
import sqlite3
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.services.generation_admission import (
    AdmissionError, _ensure_preprod_gallery_slot, preprod216_personal_gallery_limits,
)
import main


def _db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE users (id TEXT PRIMARY KEY, plan TEXT)")
    conn.execute("CREATE TABLE images (id TEXT PRIMARY KEY, user_id TEXT, deleted_at TEXT)")
    conn.execute("CREATE TABLE jobs (id TEXT PRIMARY KEY, user_id TEXT, mode TEXT, status TEXT)")
    conn.execute("CREATE TABLE videos (id TEXT PRIMARY KEY, user_id TEXT, deleted_at TEXT, "
                 "is_favorite INTEGER NOT NULL DEFAULT 0, stored_bytes INTEGER DEFAULT 0)")
    conn.execute("INSERT INTO users VALUES ('qa-user','pro')")
    for n in range(100):
        conn.execute("INSERT INTO images VALUES (?,?,NULL)", (str(n), "qa-user"))
    for n in range(10):
        conn.execute("INSERT INTO videos VALUES (?,?,NULL,0,12345)", (str(n), "qa-user"))
    return conn


def _runtime():
    return SimpleNamespace(
        plan_order=("free", "mini", "plus", "pro", "business"),
        get_tariff_config=lambda: {"pro": {"gallery_slots": 100}},
    )


def _migration_table(db, *, owner: str = "qa-user", images: int = 120,
                     videos: int = 15):
    db.execute(
        "CREATE TABLE preprod216_owner_gallery_overrides "
        "(user_id TEXT PRIMARY KEY, gallery_slots INTEGER, video_slots INTEGER)"
    )
    db.execute(
        "INSERT INTO preprod216_owner_gallery_overrides VALUES (?,?,?)",
        (owner, images, videos),
    )


def test_only_migrated_pro_owner_gets_120_15_not_other_users():
    with _db() as db, patch.dict(os.environ, {"IZO_PREPROD_PRESERVE_HISTORY": "1"}):
        db.execute("INSERT INTO users VALUES ('qa-other','pro')")
        _migration_table(db)
        assert preprod216_personal_gallery_limits(db, "qa-user", "pro") == (120, 15)
        assert preprod216_personal_gallery_limits(db, "qa-other", "pro") is None
        assert preprod216_personal_gallery_limits(db, "qa-user", "free") is None
        with patch.object(main, "get_tariff_config", return_value={"pro": {
            "gallery_slots": 100, "video_slots": 10, "daily_tokens": 1,
            "monthly_tokens": 20, "video_enabled": True,
        }}), patch.object(main, "storage_count_active_gallery_images", return_value=100):
            user = db.execute("SELECT * FROM users WHERE id='qa-user'").fetchone()
            actual = main.gallery_quota_for_user(db, user, "qa-user")
            assert (actual["gallery_slots"], actual["video_slots"]) == (120, 15)
            other = db.execute("SELECT * FROM users WHERE id='qa-other'").fetchone()
            unchanged = main.gallery_quota_for_user(db, other, "qa-other")
            assert (unchanged["gallery_slots"], unchanged["video_slots"]) == (100, 10)


def test_personal_override_absent_in_other_projects_and_plans():
    with _db() as db:
        _migration_table(db)
        with patch.dict(os.environ, {"IZO_PREPROD_PRESERVE_HISTORY": "0"}):
            assert preprod216_personal_gallery_limits(db, "qa-user", "pro") is None
        with patch.dict(os.environ, {"IZO_PREPROD_PRESERVE_HISTORY": "1"}):
            assert preprod216_personal_gallery_limits(db, "qa-user", "plus") is None


def test_invalid_or_multiple_personal_overrides_fail_closed():
    with _db() as db, patch.dict(os.environ, {"IZO_PREPROD_PRESERVE_HISTORY": "1"}):
        _migration_table(db, images=121)
        with pytest.raises(RuntimeError, match="UNAPPROVED_PERSONAL_QUOTA"):
            preprod216_personal_gallery_limits(db, "qa-user", "pro")
        db.execute("UPDATE preprod216_owner_gallery_overrides SET gallery_slots=120")
        db.execute("INSERT INTO users VALUES ('qa-other','pro')")
        db.execute("INSERT INTO preprod216_owner_gallery_overrides VALUES ('qa-other',120,15)")
        with pytest.raises(RuntimeError, match="MULTIPLE_OWNER_OVERRIDES"):
            preprod216_personal_gallery_limits(db, "qa-user", "pro")


def test_migration_owner_has_twelve_free_image_slots_and_four_video_slots():
    with _db() as db, patch.dict(os.environ, {"IZO_PREPROD_PRESERVE_HISTORY": "1"}):
        _migration_table(db)
        runtime = _runtime()
        _ensure_preprod_gallery_slot(db, runtime, "qa-user")
        for n in range(19):
            db.execute(
                "INSERT INTO jobs VALUES (?,?,?,?)",
                ("qa-pending-"+str(n), "qa-user", "text_to_image", "queued"),
            )
        _ensure_preprod_gallery_slot(db, runtime, "qa-user")
        db.execute(
            "INSERT INTO jobs VALUES ('qa-last','qa-user','text_to_image','queued')"
        )
        with pytest.raises(AdmissionError) as exc:
            _ensure_preprod_gallery_slot(db, runtime, "qa-user")
        assert exc.value.status_code == 409
        with patch.object(main, "get_tariff_config", return_value={"pro": {
            "gallery_slots": 100, "video_slots": 10, "daily_tokens": 1,
            "monthly_tokens": 20, "video_enabled": True,
        }}), patch.object(main, "storage_count_active_gallery_images", return_value=100):
            user = db.execute("SELECT * FROM users WHERE id='qa-user'").fetchone()
            state = main._video_storage_reservation(db, user, "qa-user")
            assert (state.active, state.limit, state.free) == (10, 15, 5)


def test_full_gallery_denied_before_charge_only_on_preprod():
    with _db() as db, patch.dict(os.environ, {"IZO_PREPROD_PRESERVE_HISTORY": "1"}):
        with pytest.raises(AdmissionError) as exc:
            _ensure_preprod_gallery_slot(db, _runtime(), "qa-user")
        assert exc.value.status_code == 409
        assert exc.value.detail == "GALLERY_QUOTA_FULL_HISTORY_PRESERVED"
        assert db.execute("SELECT COUNT(*) FROM images WHERE deleted_at IS NULL").fetchone()[0] == 100
        assert db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 0


def test_pending_image_claims_reserve_remaining_slot():
    with _db() as db, patch.dict(os.environ, {"IZO_PREPROD_PRESERVE_HISTORY": "1"}):
        db.execute("UPDATE images SET deleted_at='old' WHERE id='99'")
        _ensure_preprod_gallery_slot(db, _runtime(), "qa-user")
        db.execute("INSERT INTO jobs VALUES ('queued-1','qa-user','text_to_image','queued')")
        with pytest.raises(AdmissionError) as exc:
            _ensure_preprod_gallery_slot(db, _runtime(), "qa-user")
        assert exc.value.status_code == 409
        db.execute("UPDATE jobs SET status='failed'")
        _ensure_preprod_gallery_slot(db, _runtime(), "qa-user")


def test_other_users_and_inactive_jobs_cannot_consume_slot():
    with _db() as db, patch.dict(os.environ, {"IZO_PREPROD_PRESERVE_HISTORY": "1"}):
        db.execute("UPDATE images SET deleted_at='old' WHERE id='99'")
        db.execute("INSERT INTO jobs VALUES ('other','other-user','text_to_image','queued')")
        db.execute("INSERT INTO jobs VALUES ('prior','qa-user','text_to_image','completed')")
        _ensure_preprod_gallery_slot(db, _runtime(), "qa-user")


def test_guard_does_not_modify_normal_product_when_env_unset():
    with _db() as db, patch.dict(os.environ, {"IZO_PREPROD_PRESERVE_HISTORY": "0"}):
        _ensure_preprod_gallery_slot(db, _runtime(), "qa-user")


def test_preprod_image_eviction_refuses_old_file_deletion():
    with _db() as db, patch.dict(os.environ, {"IZO_PREPROD_PRESERVE_HISTORY": "1"}):
        with pytest.raises(RuntimeError, match="HISTORIC_GALLERY_FULL_REFUSE_EVICTION"):
            main.evict_gallery_images_for_new_save(
                db, "qa-user", {"gallery_slots": 100, "gallery_used": 100}, "2026-10-24T00:00:00Z"
            )
        assert db.execute("SELECT COUNT(*) FROM images WHERE deleted_at IS NULL").fetchone()[0] == 100


def test_video_storage_refuses_paid_submission_at_full_quota():
    with _db() as db, patch.dict(os.environ, {"IZO_PREPROD_PRESERVE_HISTORY": "1"}):
        with patch.object(main, "gallery_quota_for_user", return_value={
            "plan": "pro", "video_enabled": True, "video_slots": 10,
        }):
            with pytest.raises(HTTPException) as exc:
                main._video_storage_reservation(db, db.execute(
                    "SELECT * FROM users WHERE id='qa-user'").fetchone(), "qa-user")
            assert exc.value.status_code == 409
        assert db.execute("SELECT COUNT(*) FROM videos WHERE deleted_at IS NULL").fetchone()[0] == 10


def test_video_finalizer_cannot_soft_delete_preprod_owner_rows():
    with _db() as db, patch.dict(os.environ, {"IZO_PREPROD_PRESERVE_HISTORY": "1"}):
        assert main._evict_videos_for_new_result(
            db, None, "qa-user", now="2026-10-24T00:00:00Z"
        ) == 0
        assert db.execute("SELECT COUNT(*) FROM videos WHERE deleted_at IS NULL").fetchone()[0] == 10
