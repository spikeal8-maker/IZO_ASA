"""Restore the versioned editorial feed bundle into SQLite and MEDIA_DIR."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
from pathlib import Path
from typing import Any


DEFAULT_BUNDLE_ROOT = Path(__file__).resolve().parents[2] / "seed" / "feed"
IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class DemoFeedBundleError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_path(root: Path, relative: str) -> Path:
    candidate = (root / relative).resolve()
    resolved_root = root.resolve()
    if candidate != resolved_root and resolved_root not in candidate.parents:
        raise DemoFeedBundleError(f"Unsafe demo feed path: {relative}")
    return candidate


def _load_manifest(bundle_root: Path) -> dict[str, Any]:
    manifest_path = bundle_root / "manifest.json"
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise DemoFeedBundleError(f"Cannot read demo feed manifest: {manifest_path}") from exc
    if payload.get("version") != 1 or not isinstance(payload.get("items"), list):
        raise DemoFeedBundleError("Unsupported demo feed manifest")
    return payload


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    if not IDENTIFIER_RE.fullmatch(table):
        raise DemoFeedBundleError(f"Unsafe table name: {table}")
    return {str(row[1]) for row in conn.execute(f'PRAGMA table_info("{table}")').fetchall()}


def _upsert(conn: sqlite3.Connection, table: str, row: dict[str, Any], *, key: str = "id") -> None:
    columns = _table_columns(conn, table)
    values = {name: value for name, value in row.items() if name in columns}
    if key not in values:
        raise DemoFeedBundleError(f"Demo row for {table} has no {key}")
    ordered = list(values)
    if not all(IDENTIFIER_RE.fullmatch(name) for name in ordered):
        raise DemoFeedBundleError(f"Unsafe column in demo row for {table}")
    quoted = ", ".join(f'"{name}"' for name in ordered)
    placeholders = ", ".join("?" for _ in ordered)
    updates = ", ".join(
        f'"{name}" = excluded."{name}"' for name in ordered if name != key
    )
    sql = (
        f'INSERT INTO "{table}" ({quoted}) VALUES ({placeholders}) '
        f'ON CONFLICT("{key}") DO UPDATE SET {updates}'
    )
    conn.execute(sql, [values[name] for name in ordered])


def _validate_asset(bundle_root: Path, asset: dict[str, Any]) -> Path:
    relative = str(asset.get("file") or "")
    expected_hash = str(asset.get("sha256") or "").lower()
    expected_bytes = int(asset.get("bytes") or 0)
    source = _safe_path(bundle_root, relative)
    if not source.is_file() or source.stat().st_size != expected_bytes:
        raise DemoFeedBundleError(f"Demo feed asset size mismatch: {relative}")
    if _sha256(source) != expected_hash:
        raise DemoFeedBundleError(f"Demo feed asset hash mismatch: {relative}")
    return source


def _copy_asset(source: Path, target: Path, expected_hash: str) -> bool:
    if target.is_file() and _sha256(target) == expected_hash:
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.demo-seed.tmp")
    try:
        shutil.copyfile(source, temporary)
        with temporary.open("r+b") as handle:
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return True


def _seed_reaction_count(publication_id: str, kind: str) -> int:
    match = re.search(r"(\d+)$", publication_id)
    number = int(match.group(1)) if match else 0
    if kind == "like":
        return 6 + ((number * 7) % 28)
    if kind == "recreate":
        return 1 + ((number * 3) % 9)
    if kind == "save":
        return 1 + ((number * 5) % 7)
    return 0


def restore_demo_feed_bundle(
    conn: sqlite3.Connection,
    media_root: Path,
    *,
    bundle_root: Path | None = None,
    apply: bool = False,
) -> dict[str, Any]:
    """Validate or restore only versioned ``seed-*`` editorial content."""

    bundle = (bundle_root or DEFAULT_BUNDLE_ROOT).resolve()
    media = media_root.resolve()
    manifest = _load_manifest(bundle)
    authors = manifest.get("authors") or []
    items = manifest["items"]
    retired = manifest.get("retired") or []
    publication_ids: set[str] = set()
    image_ids: set[str] = set()
    validated_assets: list[tuple[Path, Path, str]] = []

    for item in items:
        publication = item.get("publication") or {}
        image = item.get("image") or {}
        publication_id = str(publication.get("id") or "")
        image_id = str(image.get("id") or "")
        if not publication_id.startswith("seed-pub-") or not image_id.startswith("seed-img-"):
            raise DemoFeedBundleError("Demo bundle contains a non-seed identifier")
        if publication_id in publication_ids or image_id in image_ids:
            raise DemoFeedBundleError("Demo bundle contains duplicate identifiers")
        publication_ids.add(publication_id)
        image_ids.add(image_id)
        if publication.get("image_id") != image_id:
            raise DemoFeedBundleError(f"Publication/image mismatch: {publication_id}")
        for variant in ("thumb", "large"):
            asset = (item.get("assets") or {}).get(variant) or {}
            source = _validate_asset(bundle, asset)
            target = _safe_path(media, str(asset.get("target") or ""))
            validated_assets.append((source, target, str(asset["sha256"]).lower()))

    retired_publications = {str(item.get("publicationId") or "") for item in retired}
    if publication_ids & retired_publications:
        raise DemoFeedBundleError("Active and retired demo publications overlap")

    report = {
        "apply": apply,
        "authors": len(authors),
        "publications": len(items),
        "assets": len(validated_assets),
        "retired": sorted(retired_publications),
        "assetsCopied": 0,
        "reactionsEnsured": 0,
    }
    if not apply:
        return report

    for source, target, expected_hash in validated_assets:
        report["assetsCopied"] += int(_copy_asset(source, target, expected_hash))

    for retired_item in retired:
        publication_id = str(retired_item.get("publicationId") or "")
        image_id = str(retired_item.get("imageId") or "")
        if not publication_id.startswith("seed-pub-") or not image_id.startswith("seed-img-"):
            raise DemoFeedBundleError("Retired demo identifier is not seed-scoped")
        conn.execute("DELETE FROM challenge_entries WHERE publication_id = ?", (publication_id,))
        conn.execute("DELETE FROM feed_reactions WHERE publication_id = ?", (publication_id,))
        conn.execute("DELETE FROM feed_publications WHERE id = ?", (publication_id,))
        conn.execute("DELETE FROM images WHERE id = ?", (image_id,))
        for relative in retired_item.get("runtimeFiles") or []:
            _safe_path(media, str(relative)).unlink(missing_ok=True)

    for author in authors:
        author_id = str(author.get("id") or "")
        if not author_id.startswith("seed_author_"):
            raise DemoFeedBundleError("Demo author is not seed-scoped")
        _upsert(conn, "users", author)

    for item in items:
        publication = dict(item["publication"])
        image = dict(item["image"])
        publication_id = str(publication["id"])
        image["url"] = f"/api/feed/media/{publication_id}?variant=large"
        image["thumbnail_url"] = f"/api/feed/media/{publication_id}?variant=thumb"
        image["deleted_at"] = None
        _upsert(conn, "images", image)
        _upsert(conn, "feed_publications", publication)
        for kind in ("like", "recreate", "save"):
            for index in range(_seed_reaction_count(publication_id, kind)):
                conn.execute(
                    "INSERT OR IGNORE INTO feed_reactions "
                    "(publication_id, internal_user_id, kind, created_at) VALUES (?, ?, ?, ?)",
                    (
                        publication_id,
                        f"seed_reactor_{kind}_{index:03d}",
                        kind,
                        publication["created_at"],
                    ),
                )
                report["reactionsEnsured"] += 1
        if publication.get("category") == "challenge_moscow_2120":
            conn.execute(
                "INSERT OR IGNORE INTO challenge_entries "
                "(id, challenge_id, publication_id, user_id, status, judge_score, final_score, created_at) "
                "VALUES (?, 'moscow_2120_week', ?, ?, 'accepted', NULL, NULL, ?)",
                (
                    f"moscow_2120_week_{publication_id}",
                    publication_id,
                    publication["internal_user_id"],
                    publication["created_at"],
                ),
            )
    return report
