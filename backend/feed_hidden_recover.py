from __future__ import annotations

import argparse
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

import main


DEFAULT_COMFY_OUTPUT = Path(
    r"C:\LLM\ComfyUI_windows_portable_nvidia_cu126\ComfyUI_windows_portable\ComfyUI"
    r"\output\one-node-flux-2-klein"
)
MATCH_WINDOW_SECONDS = 45.0


def _source_candidates(output_dir: Path) -> list[dict]:
    candidates: list[dict] = []
    for path in output_dir.glob("FK_*.png"):
        try:
            with Image.open(path) as image:
                width, height = image.size
            candidates.append({"path": path, "mtime": path.stat().st_mtime, "width": width, "height": height})
        except (OSError, ValueError):
            continue
    return candidates


def plan_hidden_feed_recovery(output_dir: Path = DEFAULT_COMFY_OUTPUT) -> list[dict]:
    sources = _source_candidates(output_dir)
    with main.db() as conn:
        rows = conn.execute(
            """
            SELECT p.id, p.title, i.created_at, i.width, i.height
            FROM feed_publications p
            JOIN images i ON i.id = p.image_id
            WHERE p.status = 'hidden' AND p.media_error = 'source_image_deleted'
            ORDER BY p.created_at
            """
        ).fetchall()
    plan: list[dict] = []
    for row in rows:
        target_time = datetime.fromisoformat(row["created_at"]).timestamp()
        matches = [
            source for source in sources
            if source["width"] == row["width"]
            and source["height"] == row["height"]
            and abs(source["mtime"] - target_time) <= MATCH_WINDOW_SECONDS
        ]
        matches.sort(key=lambda source: abs(source["mtime"] - target_time))
        nearest_is_distinct = bool(matches) and (
            len(matches) == 1
            or abs(matches[1]["mtime"] - target_time) - abs(matches[0]["mtime"] - target_time) >= 5.0
        )
        unique = nearest_is_distinct
        plan.append({
            "publication_id": row["id"],
            "title": row["title"],
            "width": row["width"],
            "height": row["height"],
            "source": str(matches[0]["path"]) if unique else None,
            "match_count": len(matches),
            "delta_seconds": round(abs(matches[0]["mtime"] - target_time), 3) if unique else None,
            "recoverable": unique,
        })
    return plan


def _backup_database() -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    target = main.ROOT / "backups" / f"onenode-before-feed-hidden-recovery-{stamp}.sqlite3"
    target.parent.mkdir(parents=True, exist_ok=True)
    source = sqlite3.connect(main.DB_PATH)
    backup = sqlite3.connect(target)
    try:
        source.backup(backup)
    finally:
        backup.close()
        source.close()
    return target


def recover_hidden_feed_publications(*, apply: bool = False, output_dir: Path = DEFAULT_COMFY_OUTPUT) -> dict:
    plan = plan_hidden_feed_recovery(output_dir)
    recoverable = [item for item in plan if item["recoverable"]]
    backup_path = _backup_database() if apply and recoverable else None
    restored = 0
    if apply:
        now = datetime.now(timezone.utc).isoformat()
        for item in recoverable:
            publication_id = item["publication_id"]
            safe_id = re.sub(r"[^a-zA-Z0-9_-]", "_", publication_id)
            thumb_rel = f"feed/{safe_id}_thumb.webp"
            large_rel = f"feed/{safe_id}_large.webp"
            thumb_path = main.MEDIA / thumb_rel
            large_path = main.MEDIA / large_rel
            thumb_path.parent.mkdir(parents=True, exist_ok=True)
            with Image.open(item["source"]) as source:
                native_ratio = main._feed_aspect_ratio(source.width, source.height)
                orientation = main._feed_orientation(source.width, source.height)
                tw, th, tb = main._save_feed_variant(source, thumb_path, main.FEED_THUMB_MAX_SIDE, 82)
                lw, lh, lb = main._save_feed_variant(source, large_path, main.FEED_LARGE_MAX_SIDE, 86)
            with main.db() as conn:
                cursor = conn.execute(
                    """
                    UPDATE feed_publications
                    SET status = 'published', feed_thumb_name = ?, feed_large_name = ?,
                        feed_thumb_width = ?, feed_thumb_height = ?, feed_thumb_bytes = ?,
                        feed_large_width = ?, feed_large_height = ?, feed_large_bytes = ?,
                        media_ready_at = ?, media_error = NULL,
                        native_aspect_ratio = ?, orientation = ?, updated_at = ?
                    WHERE id = ? AND status = 'hidden' AND media_error = 'source_image_deleted'
                    """,
                    (thumb_rel, large_rel, tw, th, tb, lw, lh, lb, now, native_ratio, orientation, now, publication_id),
                )
            if cursor.rowcount == 1:
                restored += 1
    return {
        "apply": apply,
        "output_dir": str(output_dir),
        "total": len(plan),
        "recoverable": len(recoverable),
        "restored": restored,
        "backup": str(backup_path) if backup_path else None,
        "items": plan,
    }


def main_cli() -> None:
    parser = argparse.ArgumentParser(description="Recover feed publications retired by gallery quota eviction.")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_COMFY_OUTPUT)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    report = recover_hidden_feed_publications(apply=args.apply, output_dir=args.output_dir)
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(rendered, encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main_cli()
