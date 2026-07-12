"""Filesystem storage boundaries shared by services and HTTP adapters."""

from .paths import (
    StoragePathError,
    local_media_path_from_url,
    media_filename_from_url,
    public_media_url,
    resolve_under_root,
)
from .private_media import (
    PrivateMediaAccessError,
    PrivateMediaRuntime,
    find_gallery_media_owner,
    media_url_matches_filename,
    resolve_private_media,
)
from .public_media import (
    PublicMediaAccessError,
    PublicMediaRuntime,
    resolve_feed_media,
    resolve_public_avatar,
)

__all__ = [
    "StoragePathError",
    "PrivateMediaAccessError",
    "PrivateMediaRuntime",
    "PublicMediaAccessError",
    "PublicMediaRuntime",
    "local_media_path_from_url",
    "media_filename_from_url",
    "public_media_url",
    "media_url_matches_filename",
    "find_gallery_media_owner",
    "resolve_feed_media",
    "resolve_private_media",
    "resolve_public_avatar",
    "resolve_under_root",
]
