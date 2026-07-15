"""Plan or apply safe compaction of terminal job settings containing data URLs."""

from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.services.generation_jobs import COMPACTABLE_JOB_STATUSES, _compact_terminal_media


ROOT = Path(__file__).resolve().parent
DEFAULT_DB = ROOT / "onenode.sqlite3"


def _candidates(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    placeholders = ",".join("?" for _ in COMPACTABLE_JOB_STATUSES)
    return conn.execute(
        f"SELECT id, settings_json FROM jobs WHERE lower(status) IN ({placeholders}) AND settings_json LIKE '%data:image%'",
        tuple(sorted(COMPACTABLE_JOB_STATUSES)),
    ).fetchall()


def _compact_json(raw: str) -> str:
    value: Any = json.loads(raw or "{}")
    return json.dumps(_compact_terminal_media(value), ensure_ascii=False, separators=(",", ":"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DEFAULT_DB)
    parser.add_argument("--apply", action="store_true", help="Apply updates after creating a SQLite backup.")
    parser.add_argument("--backup", type=Path, help="Required backup destination when --apply is used.")
    args = parser.parse_args()
    database = args.database.expanduser().resolve()
    if args.apply and args.backup is None:
        parser.error("--backup is required with --apply")

    conn = sqlite3.connect(database)
    conn.row_factory = sqlite3.Row
    rows = _candidates(conn)
    before = sum(len(str(row["settings_json"] or "").encode("utf-8")) for row in rows)
    compacted = [(row["id"], _compact_json(str(row["settings_json"] or "{}"))) for row in rows]
    after = sum(len(value.encode("utf-8")) for _, value in compacted)
    report = {
        "database": str(database),
        "mode": "apply" if args.apply else "plan",
        "rows": len(rows),
        "bytes_before": before,
        "bytes_after": after,
        "bytes_reclaimable": max(0, before - after),
    }

    if args.apply:
        backup = args.backup.expanduser().resolve()
        backup.parent.mkdir(parents=True, exist_ok=True)
        if backup.exists():
            raise SystemExit(f"Backup already exists: {backup}")
        backup_conn = sqlite3.connect(backup)
        try:
            conn.backup(backup_conn)
        finally:
            backup_conn.close()
        with conn:
            conn.executemany("UPDATE jobs SET settings_json = ? WHERE id = ?", [(value, job_id) for job_id, value in compacted])
        report["backup"] = str(backup)
        report["applied_at"] = datetime.now(timezone.utc).isoformat()

    print(json.dumps(report, ensure_ascii=False, indent=2))
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
