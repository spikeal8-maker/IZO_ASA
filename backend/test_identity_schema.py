"""Identity Core additive-schema tests (Phase 3).

Every test runs against a TEMPORARY SQLite file via monkeypatching main.DB_PATH.
The working database backend/onenode.sqlite3 is never touched.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import main


IDENTITY_TABLES = [
    "auth_identities",
    "auth_sessions",
    "session_events",
    "auth_login_attempts",
    "device_installations",
    "user_consents",
    "security_events",
    "audit_logs",
    "auth_otp_challenges",
]


@pytest.fixture
def temp_db(tmp_path: Path, monkeypatch):
    """Point main at an isolated, empty SQLite file for the duration of a test."""
    db_file = tmp_path / "identity_test.sqlite3"
    monkeypatch.setattr(main, "DB_PATH", db_file)
    return db_file


def table_names(conn) -> set[str]:
    return {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def column_names(conn, table: str) -> set[str]:
    return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}


def seed_legacy_user(conn, now: str, uid: str, *, telegram_id=None, max_id=None) -> None:
    """Insert a user the way the base schema allows, with no internal_user_id."""
    conn.execute(
        """
        INSERT INTO users (id, telegram_id, max_id, username, first_name, language, role, created_at, last_login_at)
        VALUES (?, ?, ?, ?, ?, 'ru', 'user', ?, ?)
        """,
        (uid, telegram_id, max_id, uid, uid, now, now),
    )
    # Simulate a legacy row predating the internal_user_id column.
    conn.execute("UPDATE users SET internal_user_id = NULL WHERE id = ?", (uid,))


# 1.
def test_init_db_creates_all_new_tables(temp_db):
    main.init_db()
    with main.db() as conn:
        names = table_names(conn)
    for t in IDENTITY_TABLES:
        assert t in names, f"missing table {t}"


# 2.
def test_init_db_adds_internal_user_id_column(temp_db):
    main.init_db()
    with main.db() as conn:
        assert "internal_user_id" in column_names(conn, "users")


# 3.
def test_init_db_is_idempotent(temp_db):
    main.init_db()
    main.init_db()  # must not raise
    with main.db() as conn:
        names = table_names(conn)
    for t in IDENTITY_TABLES:
        assert t in names


# 4 & 5.
def test_existing_users_preserved_and_id_unchanged(temp_db):
    main.init_db()
    now = "2026-06-25T00:00:00+00:00"
    with main.db() as conn:
        seed_legacy_user(conn, now, "telegram_111", telegram_id="111")
        seed_legacy_user(conn, now, "max_222", max_id="222")
        seed_legacy_user(conn, now, "web_333")
        before_ids = sorted(r["id"] for r in conn.execute("SELECT id FROM users"))
    main.init_db()
    with main.db() as conn:
        after_ids = sorted(r["id"] for r in conn.execute("SELECT id FROM users"))
    assert before_ids == after_ids


# 6.
def test_every_user_gets_internal_user_id(temp_db):
    main.init_db()
    now = "2026-06-25T00:00:00+00:00"
    with main.db() as conn:
        seed_legacy_user(conn, now, "telegram_111", telegram_id="111")
        seed_legacy_user(conn, now, "web_333")
    main.init_db()
    with main.db() as conn:
        missing = conn.execute("SELECT COUNT(*) AS c FROM users WHERE internal_user_id IS NULL").fetchone()["c"]
    assert missing == 0


# 7.
def test_internal_user_id_values_are_unique(temp_db):
    main.init_db()
    now = "2026-06-25T00:00:00+00:00"
    with main.db() as conn:
        for i in range(5):
            seed_legacy_user(conn, now, f"web_{i}")
    main.init_db()
    with main.db() as conn:
        dups = conn.execute(
            "SELECT internal_user_id, COUNT(*) AS c FROM users "
            "GROUP BY internal_user_id HAVING c > 1"
        ).fetchall()
    assert dups == []


# 8.
def test_telegram_identity_backfill_one_per_telegram_id(temp_db):
    main.init_db()
    now = "2026-06-25T00:00:00+00:00"
    with main.db() as conn:
        seed_legacy_user(conn, now, "telegram_111", telegram_id="111")
    main.init_db()
    with main.db() as conn:
        rows = conn.execute(
            "SELECT * FROM auth_identities WHERE provider='telegram' AND provider_user_id='111'"
        ).fetchall()
    assert len(rows) == 1
    assert rows[0]["legacy_user_id"] == "telegram_111"
    assert rows[0]["verified_at"] is None
    assert rows[0]["internal_user_id"]


# 9.
def test_max_identity_backfill_one_per_max_id(temp_db):
    main.init_db()
    now = "2026-06-25T00:00:00+00:00"
    with main.db() as conn:
        seed_legacy_user(conn, now, "max_222", max_id="222")
    main.init_db()
    with main.db() as conn:
        rows = conn.execute(
            "SELECT * FROM auth_identities WHERE provider='max' AND provider_user_id='222'"
        ).fetchall()
    assert len(rows) == 1
    assert rows[0]["legacy_user_id"] == "max_222"


# 10.
def test_repeated_init_db_does_not_duplicate_identities(temp_db):
    main.init_db()
    now = "2026-06-25T00:00:00+00:00"
    with main.db() as conn:
        seed_legacy_user(conn, now, "telegram_111", telegram_id="111")
        seed_legacy_user(conn, now, "max_222", max_id="222")
    main.init_db()
    main.init_db()
    main.init_db()
    with main.db() as conn:
        count = conn.execute("SELECT COUNT(*) AS c FROM auth_identities").fetchone()["c"]
    assert count == 2


# 11.
def test_web_identity_is_not_guessed(temp_db):
    main.init_db()
    now = "2026-06-25T00:00:00+00:00"
    with main.db() as conn:
        seed_legacy_user(conn, now, "web_333")
    main.init_db()
    with main.db() as conn:
        web_or_email = conn.execute(
            "SELECT COUNT(*) AS c FROM auth_identities WHERE provider IN ('web', 'email')"
        ).fetchone()["c"]
    assert web_or_email == 0


# 12.
def test_jobs_images_token_ledger_counts_preserved(temp_db):
    main.init_db()
    now = "2026-06-25T00:00:00+00:00"
    with main.db() as conn:
        seed_legacy_user(conn, now, "telegram_111", telegram_id="111")
        conn.execute(
            "INSERT INTO jobs (id, user_id, mode, provider, status, created_at) "
            "VALUES ('j1','telegram_111','text_to_image','comfyui','completed', ?)",
            (now,),
        )
        conn.execute(
            "INSERT INTO images (id, user_id, job_id, url, thumbnail_url, width, height, mode, provider, created_at) "
            "VALUES ('i1','telegram_111','j1','/u','/t',1024,1024,'text_to_image','comfyui', ?)",
            (now,),
        )
        conn.execute(
            "INSERT INTO token_ledger (id, user_id, delta, reason, created_at) "
            "VALUES ('t1','telegram_111',-1,'generation', ?)",
            (now,),
        )
        before = {
            "jobs": conn.execute("SELECT COUNT(*) AS c FROM jobs").fetchone()["c"],
            "images": conn.execute("SELECT COUNT(*) AS c FROM images").fetchone()["c"],
            "token_ledger": conn.execute("SELECT COUNT(*) AS c FROM token_ledger").fetchone()["c"],
        }
    main.init_db()
    with main.db() as conn:
        after = {
            "jobs": conn.execute("SELECT COUNT(*) AS c FROM jobs").fetchone()["c"],
            "images": conn.execute("SELECT COUNT(*) AS c FROM images").fetchone()["c"],
            "token_ledger": conn.execute("SELECT COUNT(*) AS c FROM token_ledger").fetchone()["c"],
        }
        # rows untouched
        assert conn.execute("SELECT user_id FROM jobs WHERE id='j1'").fetchone()["user_id"] == "telegram_111"
    assert before == after == {"jobs": 1, "images": 1, "token_ledger": 1}


# 13.
def test_unique_provider_provider_user_id_constraint(temp_db):
    import sqlite3

    main.init_db()
    with main.db() as conn:
        conn.execute(
            "INSERT INTO auth_identities (id, internal_user_id, provider, provider_user_id, linked_at) "
            "VALUES ('a1','iuid','telegram','999','2026-06-25T00:00:00+00:00')"
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO auth_identities (id, internal_user_id, provider, provider_user_id, linked_at) "
                "VALUES ('a2','iuid2','telegram','999','2026-06-25T00:00:00+00:00')"
            )
        # Same provider_user_id under a different provider is allowed.
        conn.execute(
            "INSERT INTO auth_identities (id, internal_user_id, provider, provider_user_id, linked_at) "
            "VALUES ('a3','iuid3','max','999','2026-06-25T00:00:00+00:00')"
        )


# 14.
def test_user_without_provider_gets_internal_id_but_no_identity(temp_db):
    main.init_db()  # seeds demo_user (no telegram/max id)
    with main.db() as conn:
        demo = conn.execute("SELECT internal_user_id FROM users WHERE id='demo_user'").fetchone()
        assert demo is not None and demo["internal_user_id"]
        identities = conn.execute(
            "SELECT COUNT(*) AS c FROM auth_identities WHERE legacy_user_id='demo_user'"
        ).fetchone()["c"]
    assert identities == 0


# Extra: duplicate provider ids across distinct users must stop, not merge.
def test_duplicate_telegram_id_raises(temp_db):
    main.init_db()
    now = "2026-06-25T00:00:00+00:00"
    with main.db() as conn:
        seed_legacy_user(conn, now, "telegram_a", telegram_id="555")
        seed_legacy_user(conn, now, "telegram_b", telegram_id="555")
    with pytest.raises(RuntimeError):
        main.init_db()
