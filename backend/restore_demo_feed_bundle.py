"""Validate or restore the versioned editorial feed bundle."""

from __future__ import annotations

import argparse
import json

import main
from app.database.demo_feed import restore_demo_feed_bundle


def main_cli() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Restore SQLite rows and runtime media.")
    args = parser.parse_args()
    with main.db() as conn:
        report = restore_demo_feed_bundle(conn, main.MEDIA, apply=args.apply)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main_cli()
