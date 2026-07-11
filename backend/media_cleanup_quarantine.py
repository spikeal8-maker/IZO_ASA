from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import main
import media_cleanup_apply
import media_cleanup_plan
import media_storage_audit


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def quarantine_cleanup(
    quarantine_dir: Path,
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
    media_root = main.MEDIA.resolve()
    quarantine_root = quarantine_dir.expanduser().resolve()
    if quarantine_root == media_root or media_root in quarantine_root.parents:
        raise ValueError("Quarantine directory must be outside MEDIA_DIR")

    issues = list(plan.get("source_audit", {}).get("issues") or [])
    moved: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    if apply and issues:
        skipped = [{**item, "skip_reason": "blocked_by_source_issues"} for item in plan["candidates"]]
    else:
        for item in plan["candidates"]:
            rel = str(item.get("file") or "")
            kind = str(item.get("kind") or "")
            if kind in media_cleanup_plan.PROTECTED_KINDS:
                skipped.append({**item, "skip_reason": "protected_kind"})
                continue
            if not media_cleanup_apply._is_safe_media_rel(rel):
                skipped.append({**item, "skip_reason": "unsafe_relative_path"})
                continue
            source = media_cleanup_apply._resolve_media_file(rel)
            if not source.is_file():
                skipped.append({**item, "skip_reason": "already_missing"})
                continue
            target = (quarantine_root / rel).resolve()
            if quarantine_root not in target.parents:
                skipped.append({**item, "skip_reason": "unsafe_quarantine_path"})
                continue
            if target.exists():
                skipped.append({**item, "skip_reason": "quarantine_collision"})
                continue
            details = {
                **item,
                "actual_bytes": source.stat().st_size,
                "sha256": _sha256(source),
                "quarantine_file": target.relative_to(quarantine_root).as_posix(),
            }
            if apply:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(source), str(target))
            moved.append(details)

    moved_bytes = sum(int(item.get("actual_bytes") or item.get("bytes") or 0) for item in moved)
    result = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "mode": "blocked" if apply and issues else ("quarantine" if apply else "dry_run"),
        "moves_files": bool(apply and not issues),
        "media_dir": str(media_root),
        "quarantine_dir": str(quarantine_root),
        "source_plan": {
            "created_at": plan["created_at"],
            "candidate_summary": plan["candidate_summary"],
            "source_audit": plan["source_audit"],
            "selected_kinds": plan["selected_kinds"],
            "protected_kinds": plan["protected_kinds"],
        },
        "moved_summary": {
            "count": len(moved),
            "bytes": moved_bytes,
            "human": media_storage_audit._bytes_fmt(moved_bytes),
        },
        "skipped_summary": {"count": len(skipped)},
        "moved": moved,
        "skipped": skipped,
        "source_issues": issues,
    }
    if apply and not issues:
        quarantine_root.mkdir(parents=True, exist_ok=True)
        manifest = quarantine_root / "manifest.json"
        temporary = quarantine_root / ".manifest.json.tmp"
        temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(manifest)
        result["manifest"] = str(manifest)
    return result


def main_cli() -> None:
    parser = argparse.ArgumentParser(description="Move reviewed media cleanup candidates into a reversible quarantine.")
    parser.add_argument("--apply", action="store_true", help="Move candidates. Default is dry-run.")
    parser.add_argument("--quarantine-dir", required=True, help="Directory outside MEDIA_DIR.")
    parser.add_argument("--kind", action="append", default=[])
    parser.add_argument("--min-bytes", type=int, default=1)
    parser.add_argument("--limit", type=int, default=5000)
    parser.add_argument("--no-deleted-residue", action="store_true")
    parser.add_argument("--no-unreferenced", action="store_true")
    args = parser.parse_args()
    result = quarantine_cleanup(
        Path(args.quarantine_dir),
        apply=bool(args.apply),
        kinds=set(args.kind) if args.kind else None,
        min_bytes=max(1, int(args.min_bytes or 1)),
        include_deleted_residue=not args.no_deleted_residue,
        include_unreferenced=not args.no_unreferenced,
        item_limit=max(1, int(args.limit or 5000)),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main_cli()
