from __future__ import annotations

import argparse
import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import main


MEDIA_INPUT_FIELDS = {"inputImage1", "inputImage2", "maskImage", "outpaintMask"}


def _missing_media_url(value: Any) -> tuple[str, str] | None:
    if not isinstance(value, str):
        return None
    filename = main.media_filename_from_url(value)
    if not filename:
        return None
    if main.local_media_path_from_url(value):
        return None
    return filename, value


def _repair_settings(settings: dict[str, Any], *, checked_at: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    repaired = deepcopy(settings)
    missing: list[dict[str, Any]] = []

    for field in MEDIA_INPUT_FIELDS:
        found = _missing_media_url(repaired.get(field))
        if not found:
            continue
        filename, original_url = found
        missing.append({"field": field, "file": filename, "url": original_url, "reason": "file_missing"})
        repaired[field] = None

    input_images = repaired.get("inputImages")
    if isinstance(input_images, list):
        for index, item in enumerate(input_images):
            if not isinstance(item, dict):
                continue
            found = _missing_media_url(item.get("image"))
            if not found:
                continue
            filename, original_url = found
            field = f"inputImages[{index}].image"
            missing.append({"field": field, "file": filename, "url": original_url, "reason": "file_missing"})
            item["image"] = None

    if missing:
        status = repaired.get("_media_ref_status")
        if not isinstance(status, dict):
            status = {}
        previous = status.get("missing")
        status["missing"] = (previous if isinstance(previous, list) else []) + missing
        status["checked_at"] = checked_at
        repaired["_media_ref_status"] = status
    return repaired, missing


def repair_job_media_refs(*, apply: bool = False, item_limit: int = 1000) -> dict[str, Any]:
    main.init_db()
    checked_at = datetime.now(timezone.utc).isoformat()
    items: list[dict[str, Any]] = []
    updated = 0
    with main.db() as conn:
        rows = conn.execute("SELECT id, user_id, status, result_image_id, settings_json FROM jobs").fetchall()
        for row in rows:
            try:
                settings = json.loads(row["settings_json"] or "{}")
            except Exception:
                continue
            if not isinstance(settings, dict):
                continue
            repaired, missing = _repair_settings(settings, checked_at=checked_at)
            if not missing:
                continue
            item = {
                "job_id": row["id"],
                "user_id": row["user_id"],
                "status": row["status"],
                "result_image_id": row["result_image_id"],
                "missing": missing,
            }
            items.append(item)
            if apply:
                conn.execute(
                    "UPDATE jobs SET settings_json = ? WHERE id = ?",
                    (json.dumps(repaired, ensure_ascii=False), row["id"]),
                )
                updated += 1

    return {
        "checked_at": checked_at,
        "mode": "apply" if apply else "dry_run",
        "updates_db": apply,
        "jobs_with_missing_refs": len(items),
        "missing_refs": sum(len(item["missing"]) for item in items),
        "updated_jobs": updated,
        "items": items[: max(1, item_limit)],
    }


def main_cli() -> None:
    parser = argparse.ArgumentParser(description="Move missing job media inputs into diagnostic metadata.")
    parser.add_argument("--apply", action="store_true", help="Update jobs.settings_json. Default is dry-run.")
    parser.add_argument("--report", default="", help="Optional JSON report path.")
    parser.add_argument("--limit", type=int, default=1000, help="Maximum items in output.")
    args = parser.parse_args()
    report = repair_job_media_refs(apply=bool(args.apply), item_limit=max(1, int(args.limit or 1000)))
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.report:
        Path(args.report).write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main_cli()
