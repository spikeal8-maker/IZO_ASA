"""Migrate the legacy OpenRouter SQLite secret to external CurrentUser DPAPI."""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.config import load_local_env, sqlite_path_from_database_url  # noqa: E402
from app.security.secret_store import (  # noqa: E402
    DpapiSecretStore,
    assert_secret_store_outside_repository,
    default_secret_store_dir,
    migrate_sqlite_secret_to_store,
)


SECRET_NAME = "openrouter_api_key"


def main() -> int:
    load_local_env(BACKEND)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path)
    parser.add_argument("--secret-dir", type=Path)
    parser.add_argument("--plan", action="store_true")
    args = parser.parse_args()

    database = (args.database or sqlite_path_from_database_url(os.getenv("DATABASE_URL"), BACKEND)).resolve()
    secret_dir = (args.secret_dir or default_secret_store_dir()).resolve()
    assert_secret_store_outside_repository(secret_dir, ROOT)
    if not database.is_file():
        print("OPENROUTER_SECRET_MIGRATION_ERROR reason=database_not_found")
        return 2
    store = DpapiSecretStore(secret_dir)
    with sqlite3.connect(database) as conn:
        table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='admin_secrets'"
        ).fetchone()
        if table is None:
            print("OPENROUTER_SECRET_MIGRATION_ERROR reason=table_not_found")
            return 3
        legacy_before = conn.execute(
            "SELECT COUNT(*) FROM admin_secrets WHERE key = ?",
            (SECRET_NAME,),
        ).fetchone()[0]
        if args.plan:
            print(
                f"OPENROUTER_SECRET_MIGRATION_PLAN legacyRows={legacy_before} "
                f"dpapiConfigured={store.exists(SECRET_NAME)}"
            )
            return 0
        result = migrate_sqlite_secret_to_store(conn, store, SECRET_NAME)
        legacy_after = conn.execute(
            "SELECT COUNT(*) FROM admin_secrets WHERE key = ?",
            (SECRET_NAME,),
        ).fetchone()[0]
    configured = store.exists(SECRET_NAME) or bool(os.getenv("OPENROUTER_API_KEY", "").strip())
    if legacy_after != 0 or (legacy_before and not configured):
        print("OPENROUTER_SECRET_MIGRATION_ERROR reason=postcondition_failed")
        return 4
    print(
        f"OPENROUTER_SECRET_MIGRATION_OK result={result} legacyRows={legacy_after} "
        f"configured={configured} source={'env' if os.getenv('OPENROUTER_API_KEY', '').strip() else 'dpapi' if store.exists(SECRET_NAME) else 'none'}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
