"""Narrow public avatar and feed-media resolution without FastAPI globals."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .paths import StoragePathError


@dataclass(frozen=True)
class PublicMediaRuntime:
    connect: Callable[[], sqlite3.Connection]
    resolve_path: Callable[[Path, str], Path]


class PublicMediaAccessError(RuntimeError):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def resolve_public_avatar(
    runtime: PublicMediaRuntime,
    avatar_root: Path,
    filename: str,
) -> Path:
    try:
        path = runtime.resolve_path(avatar_root, filename)
    except StoragePathError as exc:
        raise PublicMediaAccessError(404, "Avatar not found") from exc
    if not path.is_file():
        raise PublicMediaAccessError(404, "Avatar not found")
    with runtime.connect() as conn:
        referenced = conn.execute(
            "SELECT 1 FROM users WHERE avatar_url = ? LIMIT 1",
            (f"/media/avatars/{filename}",),
        ).fetchone()
    if referenced is None:
        raise PublicMediaAccessError(404, "Avatar not found")
    return path


def resolve_feed_media(
    runtime: PublicMediaRuntime,
    media_root: Path,
    publication_id: str,
    *,
    variant: str = "large",
    thumb: int = 0,
) -> Path:
    selected = "thumb" if int(thumb or 0) else (variant or "large").strip().lower()
    if selected not in {"thumb", "large"}:
        raise PublicMediaAccessError(400, "Invalid feed media variant")
    with runtime.connect() as conn:
        publication = conn.execute(
            """
            SELECT feed_thumb_name, feed_large_name FROM feed_publications
            WHERE id = ?
              AND status = 'published'
              AND media_ready_at IS NOT NULL
              AND feed_thumb_name IS NOT NULL
              AND feed_large_name IS NOT NULL
            """,
            (publication_id,),
        ).fetchone()
    if publication is None:
        raise PublicMediaAccessError(404, "Publication not found")
    name = publication["feed_thumb_name"] if selected == "thumb" else publication["feed_large_name"]
    if not name:
        raise PublicMediaAccessError(404, "Image file not found")
    try:
        path = runtime.resolve_path(media_root, str(name))
    except StoragePathError as exc:
        raise PublicMediaAccessError(404, "Image file not found") from exc
    if not path.is_file():
        raise PublicMediaAccessError(404, "Image file not found")
    return path
