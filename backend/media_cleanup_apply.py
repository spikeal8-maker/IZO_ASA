from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import main
import media_cleanup_plan
import media_storage_audit


def _is_safe_media_rel(rel: str) -> bool:
    path = Path(rel.replace("\\", "/"))
    return bool(rel) and not path.is_absolute() and ".." not in path.parts


def _resolve_media_file(rel: str) -> Path:
    media_root = main.MEDIA.resolve()
    target = (media_root / rel).resolve()
    if target != media_root and media_root not in target.parents:
        raise ValueError(f"Refusing path outside media dir: {rel}")
    return target


def apply_cleanup(
    *,
    apply: bool = False,
    kinds: set[str] | None = None,
    min_bytes: int = 1,
    include_deleted_residue: bool = True,
    include_unreferenced: bool = True,
    item_limit: int = 5000,
) -> dict[str, Any]:
    plan = media_cleanup_plan.build_cleanup_plan(
        kinds=kinds,
        min_bytes=min_bytes,
        include_deleted_residue=include_deleted_residue,
        include_unreferenced=include_unreferenced,
        item_limit=item_limit,
    )
    deleted: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for item in plan["candidates"]:
        rel = str(item.get("file") or "")
        kind = str(item.get("kind") or "")
        if kind in media_cleanup_plan.PROTECTED_KINDS:
            skipped.append({**item, "skip_reason": "protected_kind"})
            continue
        if not _is_safe_media_rel(rel):
            skipped.append({**item, "skip_reason": "unsafe_relative_path"})
            continue
        try:
            path = _resolve_media_file(rel)
        except ValueError as exc:
            skipped.append({**item, "skip_reason": str(exc)})
            continue
        if not path.exists():
            skipped.append({**item, "skip_reason": "already_missing"})
            continue
        if not path.is_file():
            skipped.append({**item, "skip_reason": "not_file"})
            continue
        actual_bytes = path.stat().st_size
        if apply:
            path.unlink()
        deleted.append({**item, "actual_bytes": actual_bytes})

    deleted_bytes = sum(int(item.get("actual_bytes") or item.get("bytes") or 0) for item in deleted)
    result: dict[str, Any] = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "mode": "apply" if apply else "dry_run",
        "deletes_files": apply,
        "media_dir": str(main.MEDIA),
        "source_plan": {
            "created_at": plan["created_at"],
            "candidate_summary": plan["candidate_summary"],
            "source_audit": plan["source_audit"],
            "selected_kinds": plan["selected_kinds"],
            "protected_kinds": plan["protected_kinds"],
            "ignored_requested_protected_kinds": plan["ignored_requested_protected_kinds"],
        },
        "deleted_summary": {
            "count": len(deleted),
            "bytes": deleted_bytes,
            "human": media_storage_audit._bytes_fmt(deleted_bytes),
        },
        "skipped_summary": {
            "count": len(skipped),
            "bytes": sum(int(item.get("bytes") or 0) for item in skipped),
            "human": media_storage_audit._bytes_fmt(sum(int(item.get("bytes") or 0) for item in skipped)),
        },
        "deleted": deleted,
        "skipped": skipped,
    }
    return result


def main_cli() -> None:
    parser = argparse.ArgumentParser(description="Safely apply backend/media cleanup candidates.")
    parser.add_argument("--apply", action="store_true", help="Actually delete candidate files. Default is dry-run.")
    parser.add_argument("--report", default="", help="Optional JSON report path.")
    parser.add_argument("--kind", action="append", default=[], help="Candidate kind. Defaults to original_or_input and gallery_thumb.")
    parser.add_argument("--min-bytes", type=int, default=1, help="Skip candidates smaller than this many bytes.")
    parser.add_argument("--limit", type=int, default=5000, help="Maximum candidates to consider.")
    parser.add_argument("--no-deleted-residue", action="store_true", help="Do not include deleted-image residue candidates.")
    parser.add_argument("--no-unreferenced", action="store_true", help="Do not include unreferenced candidates.")
    args = parser.parse_args()
    kinds = set(args.kind) if args.kind else None
    result = apply_cleanup(
        apply=bool(args.apply),
        kinds=kinds,
        min_bytes=max(1, int(args.min_bytes or 1)),
        include_deleted_residue=not args.no_deleted_residue,
        include_unreferenced=not args.no_unreferenced,
        item_limit=max(1, int(args.limit or 5000)),
    )
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.report:
        Path(args.report).write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main_cli()
