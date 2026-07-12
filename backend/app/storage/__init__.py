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
from .maintenance import startup_storage_maintenance_allowed
from .cleanup import SourceCleanupRuntime, reconcile_orphan_source_rows
from .recovery import (
    SourceAvailabilityRuntime,
    SourceRepairRuntime,
    reconcile_source_availability,
    repair_unavailable_sources_from_jobs,
)
from .source_graph import (
    SourcePersistenceRuntime,
    SourceRowRepairRuntime,
    SourceTreeRuntime,
    persist_image_source_rows,
    read_image_source_tree,
    repair_image_source_rows_from_job,
)
from .source_thumbnails import (
    SourceThumbnailRuntime,
    open_source_image,
    save_source_thumbnail,
)

__all__ = [
    "StoragePathError",
    "PrivateMediaAccessError",
    "PrivateMediaRuntime",
    "PublicMediaAccessError",
    "PublicMediaRuntime",
    "SourceCleanupRuntime",
    "SourceAvailabilityRuntime",
    "SourceRepairRuntime",
    "SourcePersistenceRuntime",
    "SourceRowRepairRuntime",
    "SourceTreeRuntime",
    "SourceThumbnailRuntime",
    "local_media_path_from_url",
    "media_filename_from_url",
    "public_media_url",
    "media_url_matches_filename",
    "find_gallery_media_owner",
    "resolve_feed_media",
    "resolve_private_media",
    "resolve_public_avatar",
    "reconcile_orphan_source_rows",
    "reconcile_source_availability",
    "repair_unavailable_sources_from_jobs",
    "read_image_source_tree",
    "repair_image_source_rows_from_job",
    "persist_image_source_rows",
    "open_source_image",
    "save_source_thumbnail",
    "startup_storage_maintenance_allowed",
    "resolve_under_root",
]
