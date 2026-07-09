from __future__ import annotations

import argparse
import os
import secrets
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parent
AVATAR_PRESET_COUNT = 71
MISSING_AVATAR_WHERE = "(avatar_url IS NULL OR avatar_url = '') AND (avatar_preset IS NULL OR avatar_preset = '')"


def sqlite_path_from_database_url(value: str | None) -> Path:
    raw = (value or "").strip()
    if raw.startswith("sqlite:///"):
        return Path(raw.replace("sqlite:///", "", 1))
    if raw.startswith("sqlite:"):
        return Path(raw.replace("sqlite:", "", 1))
    return Path(raw) if raw else ROOT / "onenode.sqlite3"


def preset_path(preset: str) -> str:
    return f"/avatars/{preset}.webp"


def random_avatar_choice() -> tuple[str, str]:
    preset = f"avatar-{secrets.randbelow(AVATAR_PRESET_COUNT) + 1:03d}"
    return preset_path(preset), preset


def verify_avatar_assets() -> None:
    avatar_dir = ROOT.parent / "frontend" / "public" / "avatars"
    missing = [
        f"avatar-{index:03d}.webp"
        for index in range(1, AVATAR_PRESET_COUNT + 1)
        if not (avatar_dir / f"avatar-{index:03d}.webp").exists()
    ]
    if missing:
        raise SystemExit(f"Missing avatar preset files: {', '.join(missing[:10])}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Assign random preset avatars to users without any avatar.")
    parser.add_argument("--db", type=Path, default=sqlite_path_from_database_url(os.getenv("DATABASE_URL")))
    parser.add_argument("--apply", action="store_true", help="Persist changes. Without this flag, only prints a dry run.")
    args = parser.parse_args()

    verify_avatar_assets()
    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            f"SELECT id, internal_user_id FROM users WHERE {MISSING_AVATAR_WHERE} ORDER BY created_at, id"
        ).fetchall()
        print(f"database: {args.db}")
        print(f"missing avatars before: {len(rows)}")
        if not rows:
            print("nothing to update")
            return 0

        assignments: list[tuple[str, str, str]] = []
        for row in rows:
            avatar_url, avatar_preset = random_avatar_choice()
            assignments.append((avatar_url, avatar_preset, row["id"]))

        conn.execute("BEGIN")
        before_changes = conn.total_changes
        conn.executemany(
            f"UPDATE users SET avatar_url = ?, avatar_preset = ? WHERE id = ? AND {MISSING_AVATAR_WHERE}",
            assignments,
        )
        changed = conn.total_changes - before_changes
        missing_after = conn.execute(f"SELECT COUNT(*) FROM users WHERE {MISSING_AVATAR_WHERE}").fetchone()[0]
        invalid_after = conn.execute(
            """
            SELECT COUNT(*)
            FROM users
            WHERE avatar_preset IS NOT NULL
              AND avatar_preset != ''
              AND avatar_preset NOT GLOB 'avatar-[0-9][0-9][0-9]'
            """
        ).fetchone()[0]
        if not args.apply:
            conn.rollback()
            print(f"dry run: would update {changed} users")
            print(f"dry run: missing avatars after would be {missing_after}")
            print("pass --apply to persist")
            return 0
        if changed != len(rows) or missing_after != 0 or invalid_after != 0:
            conn.rollback()
            raise SystemExit(
                f"verification failed: changed={changed}, expected={len(rows)}, "
                f"missing_after={missing_after}, invalid_after={invalid_after}"
            )
        conn.commit()
        print(f"updated users: {changed}")
        print(f"missing avatars after: {missing_after}")
        print(f"invalid avatar presets after: {invalid_after}")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
