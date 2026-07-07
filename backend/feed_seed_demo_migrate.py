"""Prepare editorial seed feed rows as a small demo community.

Only touches seed/demo publications (`seed-pub-*`). Real user publications are
left untouched. The script is idempotent and can be safely re-run after seed data
is recreated.
"""
from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import main


@dataclass(frozen=True)
class DemoAuthor:
    legacy_id: str
    internal_id: str
    username: str
    display_name: str


DEMO_AUTHORS = [
    DemoAuthor("seed_author_mira", "seed_author_mira", "mira_izo", "Мира Соколова"),
    DemoAuthor("seed_author_lev", "seed_author_lev", "lev_arch", "Лев Орлов"),
    DemoAuthor("seed_author_alisa", "seed_author_alisa", "alisa_neon", "Алиса Ветрова"),
    DemoAuthor("seed_author_tim", "seed_author_tim", "timur_frame", "Тимур Ким"),
    DemoAuthor("seed_author_nika", "seed_author_nika", "nika_art", "Ника Ларина"),
]

CHALLENGE_PUBLICATION_IDS = {
    "seed-pub-01",
    "seed-pub-04",
    "seed-pub-06",
    "seed-pub-11",
    "seed-pub-30",
    "seed-pub-37",
}

SOURCE_LABELS = ["Текст -> Изо", "Изо -> Изо", "Рисунок -> Изо", "Лицо"]
SOURCE_TYPES = ["text_to_image", "image_to_image", "drawing_to_image", "faceswap"]


def _seed_number(publication_id: str) -> int:
    match = re.search(r"(\d+)$", publication_id)
    return int(match.group(1)) if match else 0


def _reaction_count(seed_number: int, kind: str) -> int:
    if kind == "like":
        return 6 + ((seed_number * 7) % 28)
    if kind == "recreate":
        return 1 + ((seed_number * 3) % 9)
    if kind == "save":
        return 1 + ((seed_number * 5) % 7)
    return 0


def migrate_seed_demo_feed(*, apply: bool = False) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    changed_publications = 0
    reactions_written = 0
    with main.db() as conn:
        rows = conn.execute(
            """
            SELECT id FROM feed_publications
            WHERE id LIKE 'seed-pub-%'
            ORDER BY id
            """
        ).fetchall()
        plan: list[dict[str, Any]] = []
        for row in rows:
            pub_id = row["id"]
            n = _seed_number(pub_id)
            author = DEMO_AUTHORS[n % len(DEMO_AUTHORS)]
            source_index = n % len(SOURCE_LABELS)
            category = "challenge_moscow_2120" if pub_id in CHALLENGE_PUBLICATION_IDS else "showcase"
            plan.append(
                {
                    "id": pub_id,
                    "author": author.display_name,
                    "internal_user_id": author.internal_id,
                    "legacy_user_id": author.legacy_id,
                    "category": category,
                    "source_type": SOURCE_TYPES[source_index],
                    "source_label": SOURCE_LABELS[source_index],
                    "likes": _reaction_count(n, "like"),
                    "remixes": _reaction_count(n, "recreate"),
                    "saves": _reaction_count(n, "save"),
                }
            )
        if apply:
            for author in DEMO_AUTHORS:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO users (
                        id, username, first_name, display_name, language, role, plan,
                        token_balance, gallery_enabled, internal_user_id, created_at, last_login_at
                    )
                    VALUES (?, ?, ?, ?, 'ru', 'user', 'mini', 0, 0, ?, ?, ?)
                    """,
                    (
                        author.legacy_id,
                        author.username,
                        author.display_name.split()[0],
                        author.display_name,
                        author.internal_id,
                        now,
                        now,
                    ),
                )
            for item in plan:
                conn.execute(
                    """
                    UPDATE feed_publications
                    SET internal_user_id = ?, legacy_user_id = ?, category = ?,
                        source_type = ?, source_label = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        item["internal_user_id"],
                        item["legacy_user_id"],
                        item["category"],
                        item["source_type"],
                        item["source_label"],
                        now,
                        item["id"],
                    ),
                )
                changed_publications += 1
                conn.execute(
                    """
                    DELETE FROM feed_reactions
                    WHERE publication_id = ? AND internal_user_id LIKE 'seed_reactor_%'
                    """,
                    (item["id"],),
                )
                for kind in ("like", "recreate", "save"):
                    for idx in range(int(item[f"{'remixes' if kind == 'recreate' else kind + 's'}"])):
                        conn.execute(
                            """
                            INSERT OR IGNORE INTO feed_reactions
                                (publication_id, internal_user_id, kind, created_at)
                            VALUES (?, ?, ?, ?)
                            """,
                            (item["id"], f"seed_reactor_{kind}_{idx:03d}", kind, now),
                        )
                        reactions_written += 1
    return {
        "apply": apply,
        "seed_publications": len(plan),
        "changed_publications": changed_publications,
        "reactions_written": reactions_written,
        "challenge_publications": sorted(CHALLENGE_PUBLICATION_IDS),
        "authors": [author.display_name for author in DEMO_AUTHORS],
        "items": plan[:20],
    }


def main_cli() -> None:
    parser = argparse.ArgumentParser(description="Prepare seed feed demo authors, challenge and reactions.")
    parser.add_argument("--apply", action="store_true", help="Write changes. Default is dry-run.")
    args = parser.parse_args()
    import json

    print(json.dumps(migrate_seed_demo_feed(apply=args.apply), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main_cli()
