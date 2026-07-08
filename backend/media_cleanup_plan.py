from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import media_storage_audit


DEFAULT_KINDS = {"original_or_input", "gallery_thumb"}
PROTECTED_KINDS = {"seed_original", "feed_variant"}


def build_cleanup_plan(
    *,
    kinds: set[str] | None = None,
    min_bytes: int = 1,
    include_deleted_residue: bool = True,
    include_unreferenced: bool = True,
    item_limit: int = 5000,
) -> dict[str, Any]:
    selected_kinds = set(kinds or DEFAULT_KINDS)
    protected_selected = sorted(selected_kinds & PROTECTED_KINDS)
    selected_kinds -= PROTECTED_KINDS
    audit = media_storage_audit.audit_media_storage(item_limit=max(item_limit, 1_000_000))
    candidates: list[dict[str, Any]] = []

    def add_items(items: list[dict[str, Any]], reason: str) -> None:
        for item in items:
            kind = str(item.get("kind") or "")
            size = int(item.get("bytes") or 0)
            if kind not in selected_kinds or size < min_bytes:
                continue
            candidates.append(
                {
                    "file": item["file"],
                    "bytes": size,
                    "human": media_storage_audit._bytes_fmt(size),
                    "kind": kind,
                    "reason": reason,
                }
            )

    if include_unreferenced:
        add_items(audit.get("largest_unreferenced", []), "unreferenced")
    if include_deleted_residue:
        add_items(audit.get("largest_deleted_image_residue", []), "deleted_image_residue")

    candidates = sorted(candidates, key=lambda item: int(item["bytes"]), reverse=True)
    total_bytes = sum(int(item["bytes"]) for item in candidates)
    limited_candidates = candidates[: max(1, item_limit)]
    return {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "mode": "plan_only",
        "deletes_files": False,
        "selected_kinds": sorted(selected_kinds),
        "protected_kinds": sorted(PROTECTED_KINDS),
        "ignored_requested_protected_kinds": protected_selected,
        "min_bytes": min_bytes,
        "source_audit": {
            "checked_at": audit["checked_at"],
            "media_dir": audit["media_dir"],
            "total": audit["total"],
            "unreferenced": audit["unreferenced"],
            "deleted_image_residue": audit["deleted_image_residue"],
            "issues": audit["issues"],
        },
        "candidate_summary": {
            "count": len(candidates),
            "bytes": total_bytes,
            "human": media_storage_audit._bytes_fmt(total_bytes),
            "truncated_to": len(limited_candidates),
        },
        "candidates": limited_candidates,
        "next_step": "Review this manifest and create a backup before any delete/archive command.",
    }


def main_cli() -> None:
    parser = argparse.ArgumentParser(description="Build a read-only cleanup manifest for backend/media.")
    parser.add_argument("--report", default="", help="Optional JSON report path.")
    parser.add_argument("--kind", action="append", default=[], help="Candidate kind. Defaults to original_or_input and gallery_thumb.")
    parser.add_argument("--min-bytes", type=int, default=1, help="Skip candidates smaller than this many bytes.")
    parser.add_argument("--limit", type=int, default=5000, help="Maximum candidates in output.")
    parser.add_argument("--no-deleted-residue", action="store_true", help="Do not include deleted-image residue candidates.")
    parser.add_argument("--no-unreferenced", action="store_true", help="Do not include unreferenced candidates.")
    args = parser.parse_args()
    kinds = set(args.kind) if args.kind else None
    plan = build_cleanup_plan(
        kinds=kinds,
        min_bytes=max(1, int(args.min_bytes or 1)),
        include_deleted_residue=not args.no_deleted_residue,
        include_unreferenced=not args.no_unreferenced,
        item_limit=max(1, int(args.limit or 5000)),
    )
    text = json.dumps(plan, ensure_ascii=False, indent=2)
    if args.report:
        Path(args.report).write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main_cli()
