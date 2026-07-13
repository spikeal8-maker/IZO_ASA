"""SQLite connection and startup safety helpers.

The public backend entrypoint keeps compatibility wrappers around these helpers
while the legacy application is split incrementally.
"""

from .connection import open_sqlite
from .guard import (
    DbGuardError,
    collect_sqlite_guard_status,
    database_size_mb,
    mask_database_path,
    parse_allowed_database_paths,
    preflight_sqlite_database,
    safe_guard_payload,
)
from .migrations import (
    FEED_PUBLICATION_ADDITIVE_COLUMNS,
    IMAGE_ADDITIVE_COLUMNS,
    IMAGE_SOURCE_ADDITIVE_COLUMNS,
    LEGACY_BASELINE_MIGRATION,
    MIGRATION_LEDGER_SQL,
    MigrationDefinition,
    USER_EARLY_ADDITIVE_COLUMNS,
    add_missing_columns,
    ensure_migration_ledger,
    finalize_legacy_schema_baseline,
    record_applied_migration,
    sqlite_user_version,
    table_columns,
)
from .schema import BASE_SCHEMA_SQL, IDENTITY_SCHEMA_SQL, IMAGE_SEARCH_SCHEMA_SQL
from .schema_groups import initialize_media_schema_group

__all__ = [
    "DbGuardError",
    "BASE_SCHEMA_SQL",
    "IDENTITY_SCHEMA_SQL",
    "IMAGE_SEARCH_SCHEMA_SQL",
    "initialize_media_schema_group",
    "LEGACY_BASELINE_MIGRATION",
    "MIGRATION_LEDGER_SQL",
    "MigrationDefinition",
    "FEED_PUBLICATION_ADDITIVE_COLUMNS",
    "IMAGE_ADDITIVE_COLUMNS",
    "IMAGE_SOURCE_ADDITIVE_COLUMNS",
    "USER_EARLY_ADDITIVE_COLUMNS",
    "add_missing_columns",
    "collect_sqlite_guard_status",
    "database_size_mb",
    "ensure_migration_ledger",
    "finalize_legacy_schema_baseline",
    "mask_database_path",
    "open_sqlite",
    "parse_allowed_database_paths",
    "preflight_sqlite_database",
    "record_applied_migration",
    "safe_guard_payload",
    "sqlite_user_version",
    "table_columns",
]
