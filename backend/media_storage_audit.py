from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import main

DIAGNOSTIC_SETTINGS_KEYS = {"_media_ref_status", "media_ref_status"}


def _bytes_fmt(value: int) -> str:
    if value >= 1024 * 1024 * 1024:
        return f"{value / (1024 * 1024 * 1024):.2f} GB"
    if value >= 1024 * 1024:
        return f"{value / (1024 * 1024):.2f} MB"
    if value >= 1024:
        return f"{value / 1024:.1f} KB"
    return f"{value} B"


def _media_rel_from_url(url: str | None) -> str | None:
    name = main._feed_media_name(url)
    if not name:
        return None
    rel = Path(name.replace("\\", "/")).as_posix()
    if rel.startswith("../") or rel == ".." or "/../" in rel:
        return None
    return rel


def _add_ref(refs: dict[str, set[str]], rel: str | None, source: str) -> None:
    if not rel:
        return
    refs.setdefault(rel, set()).add(source)


def _add_text_media_refs(refs: dict[str, set[str]], value: Any, source: str, known_by_name: dict[str, list[str]]) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key) in DIAGNOSTIC_SETTINGS_KEYS:
                continue
            _add_text_media_refs(refs, child, source, known_by_name)
        return
    if isinstance(value, list):
        for child in value:
            _add_text_media_refs(refs, child, source, known_by_name)
        return
    if not isinstance(value, str) or not value:
        return
    direct = _media_rel_from_url(value)
    if direct:
        _add_ref(refs, direct, source)
    normalized = value.replace("\\", "/")
    candidates = {Path(normalized).name}
    candidates.update(re.findall(r"[\w.-]+\.(?:png|jpg|jpeg|webp)", normalized, flags=re.IGNORECASE))
    for name in candidates:
        for rel in known_by_name.get(name, []):
            _add_ref(refs, rel, source)


def _file_kind(rel: str) -> str:
    name = Path(rel).name
    if rel.startswith("feed/"):
        return "feed_variant"
    if name.endswith("_thumb.webp"):
        return "gallery_thumb"
    if name.startswith("seed_izo_"):
        return "seed_original"
    return "original_or_input"


def _summarize_files(items: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    return sorted(items, key=lambda item: int(item.get("bytes") or 0), reverse=True)[:limit]


def _summary(count: int, bytes_total: int) -> dict[str, Any]:
    return {"count": count, "bytes": bytes_total, "human": _bytes_fmt(bytes_total)}


def audit_media_storage(*, item_limit: int = 50) -> dict[str, Any]:
    main.init_db()
    active_refs: dict[str, set[str]] = {}
    deleted_refs: dict[str, set[str]] = {}
    feed_refs: dict[str, set[str]] = {}
    job_refs: dict[str, set[str]] = {}
    active_job_refs: dict[str, set[str]] = {}
    known_missing_refs: dict[str, set[str]] = {}

    files: list[dict[str, Any]] = []
    for path in main.MEDIA.rglob("*") if main.MEDIA.exists() else []:
        if not path.is_file():
            continue
        rel = path.relative_to(main.MEDIA).as_posix()
        size = path.stat().st_size
        files.append({"file": rel, "bytes": size, "human": _bytes_fmt(size), "kind": _file_kind(rel)})
    known_by_name: dict[str, list[str]] = {}
    for item in files:
        known_by_name.setdefault(Path(str(item["file"])).name, []).append(str(item["file"]))

    with main.db() as conn:
        image_columns = {row["name"] for row in conn.execute("PRAGMA table_info(images)").fetchall()}
        has_deleted_at = "deleted_at" in image_columns
        deleted_expr = "deleted_at" if has_deleted_at else "NULL AS deleted_at"
        settings_expr = "settings_json" if "settings_json" in image_columns else "NULL AS settings_json"
        rows = conn.execute(
            f"SELECT id, url, thumbnail_url, {settings_expr}, {deleted_expr} FROM images"
        ).fetchall()
        for row in rows:
            target = deleted_refs if main._row_get(row, "deleted_at") else active_refs
            _add_ref(target, _media_rel_from_url(row["url"]), f"images.url:{row['id']}")
            _add_ref(target, _media_rel_from_url(row["thumbnail_url"]), f"images.thumbnail_url:{row['id']}")
            try:
                settings = json.loads(main._row_get(row, "settings_json") or "{}")
            except Exception:
                settings = {}
            _add_text_media_refs(target, settings, f"images.settings_json:{row['id']}", known_by_name)

        source_tables = {row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        if "image_sources" in source_tables:
            for row in conn.execute(
                "SELECT s.id, s.thumb_url, s.availability_status, s.library_deleted_at, i.deleted_at FROM image_sources s "
                "LEFT JOIN images i ON i.id = s.image_id AND i.user_id = s.user_id"
            ).fetchall():
                rel = _media_rel_from_url(row["thumb_url"])
                source = f"image_sources.thumb_url:{row['id']}"
                known_unavailable = str(main._row_get(row, "availability_status") or "").lower() in {"missing", "unavailable"}
                removed_from_library = bool(main._row_get(row, "library_deleted_at"))
                if removed_from_library:
                    _add_ref(deleted_refs, rel, source)
                elif known_unavailable:
                    if rel and (main.MEDIA / rel).is_file():
                        _add_ref(active_refs, rel, source)
                    else:
                        _add_ref(known_missing_refs, rel, source)
                else:
                    _add_ref(active_refs, rel, source)

        user_columns = {row["name"] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
        if "avatar_url" in user_columns:
            for row in conn.execute("SELECT id, avatar_url FROM users WHERE avatar_url IS NOT NULL AND avatar_url != ''").fetchall():
                _add_ref(active_refs, _media_rel_from_url(row["avatar_url"]), f"users.avatar_url:{row['id']}")
        identity_columns = {row["name"] for row in conn.execute("PRAGMA table_info(auth_identities)").fetchall()}
        if "provider_avatar_url" in identity_columns:
            for row in conn.execute(
                "SELECT id, provider_avatar_url FROM auth_identities "
                "WHERE provider_avatar_url IS NOT NULL AND provider_avatar_url != ''"
            ).fetchall():
                _add_ref(active_refs, _media_rel_from_url(row["provider_avatar_url"]), f"auth_identities.provider_avatar_url:{row['id']}")

        feed_columns = {row["name"] for row in conn.execute("PRAGMA table_info(feed_publications)").fetchall()}
        if {"feed_thumb_name", "feed_large_name"} <= feed_columns:
            optional_columns = [
                name
                for name in ("media_type", "video_poster_name", "video_preview_name", "video_full_name")
                if name in feed_columns
            ]
            select_columns = ", ".join(["id", "feed_thumb_name", "feed_large_name", *optional_columns])
            for row in conn.execute(f"SELECT {select_columns} FROM feed_publications").fetchall():
                publication_id = str(row["id"])
                _add_ref(feed_refs, main._row_get(row, "feed_thumb_name"), f"feed.thumb:{publication_id}")
                _add_ref(feed_refs, main._row_get(row, "feed_large_name"), f"feed.large:{publication_id}")
                for field, label in (
                    ("video_poster_name", "video_poster"),
                    ("video_preview_name", "video_preview"),
                    ("video_full_name", "video_full"),
                ):
                    if field in feed_columns:
                        _add_ref(feed_refs, main._row_get(row, field), f"feed.{label}:{publication_id}")
                if main._row_get(row, "media_type") == "video":
                    download_name = main.feed_downloads.video_download_name(publication_id)
                    if (main.MEDIA / download_name).is_file():
                        _add_ref(feed_refs, download_name, f"feed.video_download:{publication_id}")
        if "jobs" in {row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}:
            for row in conn.execute("SELECT id, status, settings_json FROM jobs").fetchall():
                try:
                    settings = json.loads(main._row_get(row, "settings_json") or "{}")
                except Exception:
                    settings = {}
                _add_text_media_refs(job_refs, settings, f"jobs.settings_json:{row['id']}", known_by_name)
                if str(main._row_get(row, "status") or "").lower() not in {"completed", "failed", "cancelled"}:
                    _add_text_media_refs(active_job_refs, settings, f"jobs.settings_json:{row['id']}", known_by_name)

    all_active_refs = set(active_refs) | set(feed_refs) | set(job_refs)
    all_deleted_refs = set(deleted_refs)
    all_db_refs = all_active_refs | all_deleted_refs

    total_bytes = sum(int(item["bytes"]) for item in files)
    active_bytes = 0
    deleted_residue: list[dict[str, Any]] = []
    unreferenced: list[dict[str, Any]] = []
    missing_active_refs: list[dict[str, Any]] = []
    by_kind: dict[str, dict[str, int]] = {}
    existing = {str(item["file"]) for item in files}

    for item in files:
        rel = str(item["file"])
        kind = str(item["kind"])
        bucket = by_kind.setdefault(kind, {"count": 0, "bytes": 0})
        bucket["count"] += 1
        bucket["bytes"] += int(item["bytes"])
        if rel in all_active_refs:
            active_bytes += int(item["bytes"])
        elif rel in all_deleted_refs:
            deleted_residue.append(item)
        elif rel not in all_db_refs:
            unreferenced.append(item)

    hard_active_refs = set(active_refs) | set(feed_refs) | set(active_job_refs)
    for rel in sorted(hard_active_refs - existing):
        missing_active_refs.append({"file": rel, "sources": sorted(active_refs.get(rel, set()) | feed_refs.get(rel, set()) | active_job_refs.get(rel, set()))})
    missing_historical_job_refs = [
        {"file": rel, "sources": sorted(job_refs.get(rel, set()))}
        for rel in sorted((set(job_refs) - set(active_job_refs)) - existing)
    ]
    missing_known_unavailable_refs = [
        {"file": rel, "sources": sorted(sources)} for rel, sources in sorted(known_missing_refs.items())
    ]

    report: dict[str, Any] = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "db_path": str(main.DB_PATH),
        "media_dir": str(main.MEDIA),
        "total": _summary(len(files), total_bytes),
        "active_referenced": _summary(len(existing & all_active_refs), active_bytes),
        "job_referenced": _summary(len(existing & set(job_refs)), sum(int(item["bytes"]) for item in files if str(item["file"]) in job_refs)),
        "deleted_image_residue": _summary(len(deleted_residue), sum(int(item["bytes"]) for item in deleted_residue)),
        "unreferenced": _summary(len(unreferenced), sum(int(item["bytes"]) for item in unreferenced)),
        "by_kind": {kind: _summary(data["count"], data["bytes"]) for kind, data in sorted(by_kind.items())},
        "missing_active_refs": missing_active_refs[:item_limit],
        "missing_historical_job_refs": missing_historical_job_refs[:item_limit],
        "missing_known_unavailable_refs": missing_known_unavailable_refs[:item_limit],
        "largest_deleted_image_residue": _summarize_files(deleted_residue, limit=item_limit),
        "largest_unreferenced": _summarize_files(unreferenced, limit=item_limit),
        "issues": [],
    }
    if missing_active_refs:
        report["issues"].append("missing_active_refs")
    return report


def main_cli() -> None:
    parser = argparse.ArgumentParser(description="Read-only storage audit for backend/media.")
    parser.add_argument("--report", default="", help="Optional JSON report path.")
    parser.add_argument("--limit", type=int, default=50, help="Maximum files per detailed list.")
    parser.add_argument("--fail-on-issues", action="store_true", help="Exit with code 2 if hard issues are found.")
    args = parser.parse_args()
    report = audit_media_storage(item_limit=max(1, int(args.limit or 50)))
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.report:
        Path(args.report).write_text(text + "\n", encoding="utf-8")
    print(text)
    if args.fail_on_issues and report["issues"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main_cli()
