from __future__ import annotations

import json
import sqlite3

from app.services.generation_jobs import (
    PERSISTED_JOB_SETTINGS_KEYS,
    get_persisted_job_response,
    job_response_from_row,
    persist_job,
    public_generation_error_message,
)


def connection() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE jobs (
            id TEXT PRIMARY KEY,
            user_id TEXT,
            mode TEXT NOT NULL,
            provider TEXT NOT NULL,
            status TEXT NOT NULL,
            progress INTEGER NOT NULL,
            prompt_original TEXT,
            prompt_translated TEXT,
            result_image_id TEXT,
            error_message TEXT,
            settings_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            started_at TEXT,
            completed_at TEXT
        );
        CREATE TABLE images (
            id TEXT PRIMARY KEY,
            user_id TEXT,
            job_id TEXT,
            url TEXT,
            thumbnail_url TEXT,
            width INTEGER,
            height INTEGER,
            settings_json TEXT,
            created_at TEXT,
            deleted_at TEXT
        );
        """
    )
    return conn


def test_persisted_settings_key_contract_is_stable() -> None:
    assert PERSISTED_JOB_SETTINGS_KEYS == (
        "tokenCost",
        "resultUrl",
        "width",
        "height",
        "gallerySaveStatus",
        "galleryQuota",
        "openrouterRequest",
        "openrouterModel",
        "openrouterResponseId",
        "openrouterUsage",
        "openrouterCostUsd",
        "openrouterBilling",
        "tokenAdjustment",
    )


def test_response_mapping_preserves_error_defaults_and_model_adapter() -> None:
    row = {
        "id": "job-1",
        "user_id": "user-1",
        "mode": "edit",
        "provider": "openrouter",
        "status": "failed",
        "progress": 100,
        "error_message": "failed safely",
        "result_image_id": None,
        "settings_json": json.dumps({"width": 704, "height": 960, "modelProfile": "fallback", "openrouterBilling": []}),
        "created_at": "created",
        "completed_at": "completed",
    }
    image = {
        "url": "/result.png",
        "thumbnail_url": "/thumb.webp",
        "width": 1024,
        "height": 1024,
        "settings_json": json.dumps({"generationTimeMs": 123}),
    }

    response = job_response_from_row(row, image, model_display_name=lambda value: f"display:{value}")

    assert response["message"] == response["error"] == "failed safely"
    assert response["resultUrl"] == "/result.png" and response["thumbnailUrl"] == "/thumb.webp"
    assert response["width"] == response["height"] == 1024
    assert response["modelProfile"] == "display:fallback"
    assert response["generationTimeMs"] == 123
    assert response["openrouterBilling"] is None


def test_provider_diagnostics_are_hidden_from_user_job_responses() -> None:
    assert public_generation_error_message("OpenRouter API key has insufficient credits") == (
        "Сервер временно недоступен. Попробуйте ещё раз позже."
    )
    assert public_generation_error_message("Проверьте исходное изображение") == "Проверьте исходное изображение"


def test_persisted_lookup_prefers_result_id_then_latest_active_image() -> None:
    conn = connection()
    conn.execute(
        "INSERT INTO jobs VALUES ('job-1','user-1','edit','comfyui','completed',100,'','',"
        "'chosen',NULL,'{}','created',NULL,'completed')"
    )
    for image_id, created_at, deleted_at in (
        ("chosen", "01", None),
        ("newer", "02", None),
        ("deleted", "03", "deleted-at"),
    ):
        conn.execute(
            "INSERT INTO images VALUES (?, 'user-1', 'job-1', ?, ?, 512, 512, '{}', ?, ?)",
            (image_id, f"/{image_id}.png", f"/{image_id}.webp", created_at, deleted_at),
        )

    chosen = get_persisted_job_response(conn, "job-1", "user-1", model_display_name=str)
    assert chosen is not None and chosen["resultUrl"] == "/chosen.png"
    assert get_persisted_job_response(conn, "job-1", "user-2", model_display_name=str) is None

    conn.execute("UPDATE jobs SET result_image_id='deleted' WHERE id='job-1'")
    fallback = get_persisted_job_response(conn, "job-1", "user-1", model_display_name=str)
    assert fallback is not None and fallback["resultUrl"] == "/newer.png"


def test_persist_insert_uses_defaults_unicode_and_overlay_reference() -> None:
    conn = connection()
    request_data = {"prompt": "русский prompt", "seed": 7}
    job = {"id": "job-1", "request": request_data, "tokenCost": 2, "openrouterBilling": {"chargedTokens": 2}}

    persist_job(
        conn,
        job,
        request_data=request_data,
        request_mode="",
        request_provider="",
        request_prompt=request_data["prompt"],
        now_iso="now",
    )

    row = conn.execute("SELECT * FROM jobs WHERE id='job-1'").fetchone()
    assert row["user_id"] == "demo_user" and row["status"] == "queued" and row["progress"] == 0
    assert row["prompt_original"] == "русский prompt" and row["created_at"] == "now"
    assert request_data["tokenCost"] == 2 and request_data["openrouterBilling"] == {"chargedTokens": 2}
    assert json.loads(row["settings_json"])["prompt"] == "русский prompt"


def test_persist_conflict_updates_only_legacy_mutable_columns() -> None:
    conn = connection()
    first = {
        "id": "job-1",
        "userId": "user-1",
        "mode": "text_to_image",
        "provider": "comfyui",
        "status": "queued",
        "progress": 0,
        "createdAt": "created-1",
        "startedAt": "started-1",
    }
    persist_job(
        conn,
        first,
        request_data={"prompt": "first"},
        request_mode="text_to_image",
        request_provider="comfyui",
        request_prompt="first",
        now_iso="unused",
    )
    second = {
        **first,
        "userId": "user-2",
        "mode": "edit",
        "provider": "openrouter",
        "status": "completed",
        "progress": 100,
        "resultImageId": "image-1",
        "error": "warning",
        "createdAt": "created-2",
        "startedAt": "started-2",
        "completedAt": "completed-2",
    }
    persist_job(
        conn,
        second,
        request_data={"prompt": "second"},
        request_mode="edit",
        request_provider="openrouter",
        request_prompt="second",
        now_iso="unused",
    )

    row = conn.execute("SELECT * FROM jobs WHERE id='job-1'").fetchone()
    assert (row["user_id"], row["mode"], row["provider"], row["prompt_original"]) == (
        "user-1", "text_to_image", "comfyui", "first"
    )
    assert (row["created_at"], row["started_at"]) == ("created-1", "started-1")
    assert (row["status"], row["progress"], row["result_image_id"]) == ("completed", 100, "image-1")
    assert row["error_message"] == "warning" and row["completed_at"] == "completed-2"


def test_terminal_job_compacts_embedded_images_but_keeps_request_object_usable() -> None:
    conn = connection()
    embedded = "data:image/png;base64," + ("a" * 400)
    request_data = {"prompt": "done", "inputImage": embedded, "nested": [embedded]}
    job = {"id": "job-terminal", "status": "completed", "progress": 100}

    persist_job(
        conn,
        job,
        request_data=request_data,
        request_mode="edit",
        request_provider="openrouter",
        request_prompt="done",
        now_iso="now",
    )

    settings_json = conn.execute("SELECT settings_json FROM jobs WHERE id='job-terminal'").fetchone()[0]
    assert "base64," not in settings_json
    assert settings_json.count("[data-image-omitted:image/png:") == 2
    assert request_data["inputImage"] == embedded


def test_nonterminal_job_keeps_embedded_images_for_restart_recovery() -> None:
    conn = connection()
    embedded = "data:image/webp;base64," + ("b" * 400)

    persist_job(
        conn,
        {"id": "job-running", "status": "running", "progress": 50},
        request_data={"inputImage": embedded},
        request_mode="edit",
        request_provider="openrouter",
        request_prompt="working",
        now_iso="now",
    )

    settings_json = conn.execute("SELECT settings_json FROM jobs WHERE id='job-running'").fetchone()[0]
    assert embedded in settings_json
