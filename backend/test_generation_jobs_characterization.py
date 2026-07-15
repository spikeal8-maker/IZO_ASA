from __future__ import annotations

import json

import main


def job_row(**overrides):
    row = {
        "id": "job-1",
        "user_id": "user-1",
        "mode": "text_to_image",
        "provider": "comfyui",
        "status": "completed",
        "progress": 100,
        "error_message": None,
        "result_image_id": "image-1",
        "settings_json": json.dumps(
            {
                "resultUrl": "/fallback.png",
                "width": 704,
                "height": 704,
                "tokenCost": 3,
                "modelProfile": "profile-1",
                "openrouterBilling": {"chargedTokens": 3},
            }
        ),
        "created_at": "2026-07-14T01:00:00+00:00",
        "completed_at": "2026-07-14T01:01:00+00:00",
    }
    row.update(overrides)
    return row


def test_job_response_exact_image_and_fallback_contract(monkeypatch) -> None:
    monkeypatch.setattr(main, "_user_model_name", lambda value: f"display:{value}")
    image = {
        "url": "/image.png",
        "thumbnail_url": "/thumb.webp",
        "width": 1024,
        "height": 768,
        "settings_json": json.dumps({"modelProfile": "image-profile", "generationTimeMs": 4321}),
    }

    assert main.job_response_from_row(job_row(), image) == {
        "id": "job-1",
        "userId": "user-1",
        "mode": "text_to_image",
        "provider": "comfyui",
        "status": "completed",
        "progress": 100,
        "message": "Готово",
        "resultImageId": "image-1",
        "resultUrl": "/image.png",
        "thumbnailUrl": "/thumb.webp",
        "width": 1024,
        "height": 768,
        "createdAt": "2026-07-14T01:00:00+00:00",
        "completedAt": "2026-07-14T01:01:00+00:00",
        "tokenCost": 3,
        "openrouterBilling": {"chargedTokens": 3},
        "modelProfile": "display:image-profile",
        "generationTimeMs": 4321,
    }

    failed = main.job_response_from_row(
        job_row(
            status="failed",
            progress=100,
            error_message="provider failed",
            result_image_id=None,
            settings_json="not-json",
        )
    )
    assert failed["message"] == failed["error"] == "Сервер временно недоступен. Попробуйте ещё раз позже."
    assert failed["resultUrl"] is None and failed["thumbnailUrl"] is None
    assert failed["width"] is None and failed["height"] is None
    assert failed["tokenCost"] is None and failed["openrouterBilling"] is None


def test_persisted_response_is_owner_scoped_and_prefers_result_image() -> None:
    main.init_db()
    with main.db() as conn:
        conn.execute(
            "INSERT INTO jobs (id,user_id,mode,provider,status,progress,result_image_id,settings_json,created_at) "
            "VALUES ('job-persisted','user-1','edit','comfyui','completed',100,'image-chosen','{}','2026-07-14T01:00:00+00:00')"
        )
        for image_id, user_id, created_at, deleted_at in (
            ("image-chosen", "user-1", "2026-07-14T01:01:00+00:00", None),
            ("image-newer", "user-1", "2026-07-14T01:02:00+00:00", None),
            ("image-other", "user-2", "2026-07-14T01:03:00+00:00", None),
            ("image-deleted", "user-1", "2026-07-14T01:04:00+00:00", "2026-07-14T01:05:00+00:00"),
        ):
            conn.execute(
                "INSERT INTO images (id,user_id,job_id,url,thumbnail_url,width,height,mode,provider,settings_json,created_at,deleted_at) "
                "VALUES (?,?, 'job-persisted', ?, ?,512,512,'edit','comfyui','{}',?,?)",
                (image_id, user_id, f"/{image_id}.png", f"/{image_id}.webp", created_at, deleted_at),
            )

    response = main.get_persisted_job_response("job-persisted", "user-1")

    assert response is not None and response["resultUrl"] == "/image-chosen.png"
    assert main.get_persisted_job_response("job-persisted", "user-2") is None

    with main.db() as conn:
        conn.execute("UPDATE jobs SET result_image_id='image-deleted' WHERE id='job-persisted'")
    fallback = main.get_persisted_job_response("job-persisted", "user-1")
    assert fallback is not None and fallback["resultUrl"] == "/image-newer.png"


def test_persist_job_preserves_insert_and_conflict_update_semantics() -> None:
    main.init_db()
    request_data = {"prompt": "исходный prompt", "seed": 42}
    job = {
        "id": "job-upsert",
        "userId": "user-1",
        "mode": "text_to_image",
        "provider": "comfyui",
        "status": "queued",
        "progress": 0,
        "request": request_data,
        "tokenCost": 3,
        "createdAt": "2026-07-14T01:00:00+00:00",
        "startedAt": "2026-07-14T01:00:10+00:00",
    }
    main.persist_job(job)

    assert request_data["tokenCost"] == 3
    with main.db() as conn:
        inserted = conn.execute("SELECT * FROM jobs WHERE id='job-upsert'").fetchone()
    assert inserted["user_id"] == "user-1" and inserted["prompt_original"] == "исходный prompt"
    assert inserted["mode"] == "text_to_image" and inserted["provider"] == "comfyui"
    assert inserted["status"] == "queued" and inserted["progress"] == 0
    assert inserted["created_at"] == "2026-07-14T01:00:00+00:00"
    assert inserted["started_at"] == "2026-07-14T01:00:10+00:00"
    assert json.loads(inserted["settings_json"])["tokenCost"] == 3

    job.update(
        userId="user-2",
        mode="edit",
        provider="openrouter",
        status="completed",
        progress=100,
        resultImageId="image-2",
        error="late warning",
        completedAt="2026-07-14T01:02:00+00:00",
        createdAt="changed-created-at",
        startedAt="changed-started-at",
        width=1024,
    )
    main.persist_job(job)

    with main.db() as conn:
        updated = conn.execute("SELECT * FROM jobs WHERE id='job-upsert'").fetchone()
    assert updated["user_id"] == "user-1"
    assert updated["mode"] == "text_to_image" and updated["provider"] == "comfyui"
    assert updated["prompt_original"] == "исходный prompt"
    assert updated["created_at"] == "2026-07-14T01:00:00+00:00"
    assert updated["started_at"] == "2026-07-14T01:00:10+00:00"
    assert updated["status"] == "completed" and updated["progress"] == 100
    assert updated["result_image_id"] == "image-2" and updated["error_message"] == "late warning"
    assert updated["completed_at"] == "2026-07-14T01:02:00+00:00"
    assert json.loads(updated["settings_json"])["width"] == 1024
