"""Canonical filesystem paths and legacy media-URL parsing."""

from __future__ import annotations

from pathlib import Path


MEDIA_URL_PREFIXES = ("/api/media/", "/media/")


class StoragePathError(ValueError):
    """A relative storage name escaped its configured root."""


def resolve_under_root(root: Path, relative_name: str) -> Path:
    root_path = root.expanduser().resolve()
    candidate = (root_path / relative_name).resolve()
    try:
        candidate.relative_to(root_path)
    except ValueError as exc:
        raise StoragePathError("storage_path_outside_root") from exc
    return candidate


def _url_filename(url: str | None) -> str | None:
    if not url:
        return None
    for prefix in MEDIA_URL_PREFIXES:
        if url.startswith(prefix):
            filename = url.removeprefix(prefix).split("?", 1)[0]
            return filename or None
    return None


def media_filename_from_url(root: Path, url: str | None) -> str | None:
    filename = _url_filename(url)
    if filename is None:
        return None
    try:
        resolve_under_root(root, filename)
    except StoragePathError:
        return None
    return filename


def local_media_path_from_url(root: Path, url: str | None) -> Path | None:
    filename = _url_filename(url)
    if filename is None:
        return None
    path = resolve_under_root(root, filename)
    return path if path.is_file() else None


def public_media_url(path: Path, user_id: str = "demo_user") -> str:
    return f"/api/media/{path.name}?userId={user_id}"
