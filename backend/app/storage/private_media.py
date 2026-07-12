"""Private media ownership resolution without FastAPI or application globals."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .paths import StoragePathError


@dataclass(frozen=True)
class PrivateMediaRuntime:
    connect: Callable[[], sqlite3.Connection]
    resolve_trusted_user: Callable[[Any], dict[str, Any]]
    owner_exists: Callable[[sqlite3.Connection, str, str], bool]
    cached_images: Callable[[], Iterable[Mapping[str, Any]]]
    resolve_path: Callable[[Path, str], Path]


class PrivateMediaAccessError(RuntimeError):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def media_url_matches_filename(value: Any, filename: str) -> bool:
    path = str(value or "").split("?", 1)[0]
    return path in {f"/api/media/{filename}", f"/media/{filename}"}


def _query_pattern(prefix: str) -> str:
    escaped = prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"{escaped}?%"


def find_gallery_media_owner(
    conn: sqlite3.Connection,
    filename: str,
    legacy_user_id: str,
    *,
    active_image_where: str,
):
    """Return an owner row using an exact path plus optional query string."""
    canonical = f"/api/media/{filename}"
    legacy = f"/media/{filename}"
    image_row = conn.execute(
        f"""
        SELECT id, user_id, url, thumbnail_url FROM images
        WHERE user_id = ? AND {active_image_where}
          AND (
            url = ? OR url LIKE ? ESCAPE '\\'
            OR thumbnail_url = ? OR thumbnail_url LIKE ? ESCAPE '\\'
            OR url = ? OR url LIKE ? ESCAPE '\\'
            OR thumbnail_url = ? OR thumbnail_url LIKE ? ESCAPE '\\'
          )
        LIMIT 1
        """,
        (
            legacy_user_id,
            canonical,
            _query_pattern(canonical),
            canonical,
            _query_pattern(canonical),
            legacy,
            _query_pattern(legacy),
            legacy,
            _query_pattern(legacy),
        ),
    ).fetchone()
    if image_row is not None:
        return image_row
    return conn.execute(
        """
        SELECT id, user_id, image_id, thumb_url FROM image_sources
        WHERE user_id = ?
          AND (
            thumb_url = ? OR thumb_url LIKE ? ESCAPE '\\'
            OR thumb_url = ? OR thumb_url LIKE ? ESCAPE '\\'
          )
        LIMIT 1
        """,
        (
            legacy_user_id,
            canonical,
            _query_pattern(canonical),
            legacy,
            _query_pattern(legacy),
        ),
    ).fetchone()


def resolve_private_media(
    runtime: PrivateMediaRuntime,
    media_root: Path,
    filename: str,
    request: Any,
) -> Path:
    trusted = runtime.resolve_trusted_user(request)
    user_id = trusted["legacy_user_id"]
    try:
        path = runtime.resolve_path(media_root, filename)
    except StoragePathError as exc:
        raise PrivateMediaAccessError(404, "Image not found") from exc
    if not path.is_file():
        raise PrivateMediaAccessError(404, "Image not found")

    with runtime.connect() as conn:
        allowed = runtime.owner_exists(conn, filename, user_id)
    if not allowed:
        allowed = any(
            item.get("userId", "demo_user") == user_id
            and any(
                media_url_matches_filename(item.get(field), filename)
                for field in ("url", "thumbnailUrl")
            )
            for item in runtime.cached_images()
        )
    if not allowed:
        raise PrivateMediaAccessError(404, "Image not found")
    return path
