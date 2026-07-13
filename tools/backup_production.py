"""Create a consistent production database and incremental media backup."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.config import load_local_env, sqlite_path_from_database_url  # noqa: E402
from app.storage.backup import (  # noqa: E402
    BackupError,
    create_backup,
    media_source_totals,
    validate_backup_destination,
)


def default_config_path() -> Path:
    base = Path(os.getenv("LOCALAPPDATA") or Path.home() / ".local" / "share")
    return base / "IZO_ASA" / "backup.json"


def write_config(path: Path, backup_root: Path) -> None:
    path = path.expanduser().resolve()
    try:
        path.relative_to(ROOT)
    except ValueError:
        pass
    else:
        raise BackupError("backup_config_must_be_outside_repository")
    if path.exists():
        raise BackupError("backup_config_already_exists")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps({"version": 1, "backup_root": str(backup_root.expanduser().resolve())}, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def read_config(path: Path) -> Path:
    try:
        document = json.loads(path.expanduser().resolve().read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BackupError("backup_config_unreadable") from exc
    if document.get("version") != 1 or not str(document.get("backup_root", "")).strip():
        raise BackupError("backup_config_invalid")
    return Path(document["backup_root"])


def main() -> int:
    load_local_env(BACKEND)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=default_config_path())
    parser.add_argument("--create-config", action="store_true")
    parser.add_argument("--backup-root", type=Path)
    parser.add_argument("--plan", action="store_true")
    args = parser.parse_args()
    try:
        if args.create_config:
            if args.backup_root is None:
                raise BackupError("backup_root_required_for_config")
            write_config(args.config, args.backup_root)
            print(f"BACKUP_CONFIG_OK drive={args.backup_root.expanduser().resolve().drive or '/'}")
            return 0
        database = sqlite_path_from_database_url(os.getenv("DATABASE_URL"), BACKEND).expanduser().resolve()
        media = Path(os.getenv("MEDIA_DIR", str(BACKEND / "media"))).expanduser().resolve()
        backup_root = read_config(args.config).expanduser().resolve()
        validate_backup_destination(backup_root, database, media)
        if args.plan:
            media_files, media_bytes = media_source_totals(media)
            print(
                f"BACKUP_PLAN_OK sourceDrive={database.drive or '/'} targetDrive={backup_root.drive or '/'} "
                f"databaseBytes={database.stat().st_size} mediaFiles={media_files} mediaBytes={media_bytes}"
            )
            return 0
        result = create_backup(database, media, backup_root)
        print(
            f"BACKUP_OK snapshot={result.snapshot_id} databaseBytes={result.database_bytes} "
            f"mediaFiles={result.media_files} mediaBytes={result.media_bytes} "
            f"copiedObjects={result.copied_objects} reusedObjects={result.reused_objects}"
        )
        return 0
    except (BackupError, OSError, sqlite3.Error) as exc:
        print(f"BACKUP_ERROR reason={exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
