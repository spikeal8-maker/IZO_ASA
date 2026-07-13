"""Verify or rehearse restoration of an IZO ASA backup snapshot."""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.storage.backup import BackupError, rehearse_restore, restore_snapshot, verify_snapshot  # noqa: E402
from backup_production import default_config_path, read_config  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=default_config_path())
    parser.add_argument("--snapshot", default="latest")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--verify-only", action="store_true")
    action.add_argument("--rehearse", action="store_true")
    action.add_argument("--destination", type=Path)
    parser.add_argument("--work-root", type=Path)
    args = parser.parse_args()
    try:
        backup_root = read_config(args.config)
        if args.verify_only:
            result = verify_snapshot(backup_root, args.snapshot)
            operation = "VERIFY"
        elif args.rehearse:
            result = rehearse_restore(backup_root, args.snapshot, args.work_root)
            operation = "REHEARSAL"
        else:
            result = restore_snapshot(backup_root, args.destination, args.snapshot)
            operation = "RESTORE"
        print(
            f"BACKUP_{operation}_OK snapshot={result.snapshot_id} databaseBytes={result.database_bytes} "
            f"mediaFiles={result.media_files} mediaBytes={result.media_bytes}"
        )
        return 0
    except (BackupError, OSError, sqlite3.Error) as exc:
        print(f"BACKUP_OPERATION_ERROR reason={exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
