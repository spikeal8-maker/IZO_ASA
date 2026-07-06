from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps

import main


def _is_seed_publication(row: Any) -> bool:
    pub_id = str(row["id"] or "")
    return (
        pub_id.startswith("seed-")
        or int(main._row_get(row, "is_seed") or 0) == 1
        or str(main._row_get(row, "author_type") or "") == "seed"
        or str(main._row_get(row, "legacy_user_id") or "") == "seed_editorial"
    )


def migrate_feed_media(*, apply: bool) -> dict[str, Any]:
    main.init_db()
    report: dict[str, Any] = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "apply": apply,
        "created_or_updated": 0,
        "media_missing": 0,
        "skipped": 0,
        "errors": [],
        "items": [],
    }
    with main.db() as conn:
        rows = conn.execute(
            """
            SELECT p.*, i.url AS image_url, i.width AS image_width, i.height AS image_height, i.mode AS image_mode
            FROM feed_publications p
            LEFT JOIN images i ON i.id = p.image_id
            WHERE p.status IN ('published', 'media_missing')
            ORDER BY p.created_at ASC
            """
        ).fetchall()
        for row in rows:
            pub_id = row["id"]
            now = datetime.now(timezone.utc).isoformat()
            is_seed = _is_seed_publication(row)
            source_type = main._feed_source_type(row["image_mode"], is_seed=is_seed)
            source_label = main._feed_source_label(source_type)
            try:
                if apply:
                    assets = main.create_feed_assets(pub_id, row["image_url"])
                else:
                    source_path = main._media_file_path_from_url(row["image_url"])
                    if source_path is None or not source_path.exists():
                        raise FileNotFoundError("Feed source image file not found.")
                    with Image.open(source_path) as opened:
                        source = ImageOps.exif_transpose(opened)
                        native_ratio = main._feed_aspect_ratio(source.width, source.height)
                        orientation = main._feed_orientation(source.width, source.height)
                    report["skipped"] += 1
                    report["items"].append(
                        {
                            "id": pub_id,
                            "status": "would_update",
                            "seed": is_seed,
                            "source": str(source_path),
                            "native_aspect_ratio": native_ratio,
                            "orientation": orientation,
                        }
                    )
                    continue
            except FileNotFoundError as exc:
                report["media_missing"] += 1
                report["items"].append({"id": pub_id, "status": "media_missing", "error": str(exc), "seed": is_seed})
                if apply:
                    conn.execute(
                        "UPDATE feed_publications SET status = 'media_missing', media_error = ?, updated_at = ? WHERE id = ?",
                        (str(exc), now, pub_id),
                    )
                continue
            except Exception as exc:  # Keep going; one bad image must not stop all seed migration.
                report["errors"].append({"id": pub_id, "error": type(exc).__name__, "seed": is_seed})
                if apply:
                    conn.execute(
                        "UPDATE feed_publications SET media_error = ?, updated_at = ? WHERE id = ?",
                        (type(exc).__name__, now, pub_id),
                    )
                continue

            report["created_or_updated"] += 1
            report["items"].append(
                {
                    "id": pub_id,
                    "status": "ready",
                    "seed": is_seed,
                    "thumb": assets.feed_thumb_name,
                    "thumb_bytes": assets.feed_thumb_bytes,
                    "large": assets.feed_large_name,
                    "large_bytes": assets.feed_large_bytes,
                    "native_aspect_ratio": assets.native_aspect_ratio,
                }
            )
            if apply:
                conn.execute(
                    """
                    UPDATE feed_publications
                    SET status = 'published',
                        feed_thumb_name = ?,
                        feed_large_name = ?,
                        feed_thumb_width = ?,
                        feed_thumb_height = ?,
                        feed_thumb_bytes = ?,
                        feed_large_width = ?,
                        feed_large_height = ?,
                        feed_large_bytes = ?,
                        media_ready_at = ?,
                        media_error = NULL,
                        native_aspect_ratio = ?,
                        orientation = ?,
                        source_type = ?,
                        source_label = ?,
                        display_policy = ?,
                        remix_policy = COALESCE(remix_policy, ?),
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        assets.feed_thumb_name,
                        assets.feed_large_name,
                        assets.feed_thumb_width,
                        assets.feed_thumb_height,
                        assets.feed_thumb_bytes,
                        assets.feed_large_width,
                        assets.feed_large_height,
                        assets.feed_large_bytes,
                        now,
                        assets.native_aspect_ratio,
                        assets.orientation,
                        source_type,
                        source_label,
                        main.FEED_DISPLAY_POLICY,
                        "allowed" if int(row["allow_recreate"] or 0) else "disabled",
                        now,
                        pub_id,
                    ),
                )
    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    return report


def main_cli() -> None:
    parser = argparse.ArgumentParser(description="Prepare optimized public feed media variants.")
    parser.add_argument("--apply", action="store_true", help="Create WebP files and write DB updates. Without this, run read-only validation.")
    parser.add_argument("--report", default="", help="Optional JSON report path.")
    args = parser.parse_args()
    report = migrate_feed_media(apply=args.apply)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.report:
        Path(args.report).write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main_cli()
