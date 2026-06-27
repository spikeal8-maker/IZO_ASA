"""Password auth schema + Argon2id hashing tests (Phase 14.4).

All tests use a TEMPORARY SQLite DB via monkeypatching main.DB_PATH;
backend/onenode.sqlite3 is never touched. No endpoints are exercised.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

import main


NOW = "2026-06-26T00:00:00+00:00"


@pytest.fixture
def temp_db(tmp_path: Path, monkeypatch):
    db_file = tmp_path / "password_schema_test.sqlite3"
    monkeypatch.setattr(main, "DB_PATH", db_file)
    return db_file


def table_names(conn) -> set[str]:
    return {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def column_names(conn, table) -> set[str]:
    return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}


def count(conn, table, where="", params=()):
    return conn.execute(f"SELECT COUNT(*) AS c FROM {table} {where}", params).fetchone()["c"]


# 1, 2
def test_init_db_creates_password_tables(temp_db):
    main.init_db()
    with main.db() as conn:
        names = table_names(conn)
    assert "auth_passwords" in names
    assert "password_reset_challenges" in names


# 3, 4
def test_users_verified_columns_added(temp_db):
    main.init_db()
    with main.db() as conn:
        cols = column_names(conn, "users")
    assert "email_verified_at" in cols
    assert "phone_verified_at" in cols


# 5
def test_init_db_idempotent(temp_db):
    main.init_db()
    main.init_db()
    main.init_db()
    with main.db() as conn:
        assert "auth_passwords" in table_names(conn)


# 6, 7
def test_existing_data_and_user_ids_preserved(temp_db):
    main.init_db()
    with main.db() as conn:
        conn.execute("INSERT INTO users (id, internal_user_id, language, role, created_at, last_login_at) VALUES ('telegram_1','iuid-1','ru','user',?,?)", (NOW, NOW))
        conn.execute("INSERT INTO jobs (id, user_id, mode, provider, status, created_at) VALUES ('j1','telegram_1','t2i','comfyui','completed',?)", (NOW,))
        conn.execute("INSERT INTO images (id, user_id, job_id, url, thumbnail_url, width, height, mode, provider, created_at) VALUES ('i1','telegram_1','j1','/u','/t',1024,1024,'t2i','comfyui',?)", (NOW,))
        conn.execute("INSERT INTO token_ledger (id, user_id, delta, reason, created_at) VALUES ('t1','telegram_1',-1,'generation',?)", (NOW,))
        before_ids = sorted(r["id"] for r in conn.execute("SELECT id FROM users"))
    main.init_db()
    with main.db() as conn:
        assert count(conn, "jobs") == 1 and count(conn, "images") == 1 and count(conn, "token_ledger") == 1
        after_ids = sorted(r["id"] for r in conn.execute("SELECT id FROM users"))
    assert before_ids == after_ids


# 8, 9
def test_one_active_password_per_user(temp_db):
    main.init_db()
    with main.db() as conn:
        conn.execute("INSERT INTO auth_passwords (id, internal_user_id, password_hash, algorithm, created_at, updated_at) VALUES ('p1','iuid-1','h1','argon2id',?,?)", (NOW, NOW))
        # second ACTIVE password for same user must violate the partial unique index
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO auth_passwords (id, internal_user_id, password_hash, algorithm, created_at, updated_at) VALUES ('p2','iuid-1','h2','argon2id',?,?)", (NOW, NOW))
        # but multiple DISABLED passwords are allowed
        conn.execute("INSERT INTO auth_passwords (id, internal_user_id, password_hash, algorithm, created_at, updated_at, disabled_at) VALUES ('p3','iuid-1','h3','argon2id',?,?,?)", (NOW, NOW, NOW))
        conn.execute("INSERT INTO auth_passwords (id, internal_user_id, password_hash, algorithm, created_at, updated_at, disabled_at) VALUES ('p4','iuid-1','h4','argon2id',?,?,?)", (NOW, NOW, NOW))
        assert count(conn, "auth_passwords", "WHERE internal_user_id='iuid-1'") == 3
        assert count(conn, "auth_passwords", "WHERE internal_user_id='iuid-1' AND disabled_at IS NULL") == 1


# 10
def test_password_reset_token_hash_indexed(temp_db):
    main.init_db()
    with main.db() as conn:
        idx = {r["name"] for r in conn.execute("PRAGMA index_list(password_reset_challenges)")}
    assert "idx_password_reset_token_hash" in idx
    assert "idx_password_reset_internal_user_id" in idx
    assert "idx_password_reset_expires_at" in idx


# 11, 12
def test_hash_not_raw_and_salted(temp_db):
    h1 = main.hash_password_argon2("correct horse battery")
    h2 = main.hash_password_argon2("correct horse battery")
    assert "correct horse battery" not in h1
    assert h1.startswith("$argon2id$")
    assert h1 != h2  # per-hash random salt


# 13, 14, 15
def test_verify_true_false_and_invalid(temp_db):
    h = main.hash_password_argon2("S3cretPassw0rd")
    assert main.verify_password_argon2("S3cretPassw0rd", h) is True
    assert main.verify_password_argon2("wrong-password", h) is False
    assert main.verify_password_argon2("S3cretPassw0rd", "not-a-valid-hash") is False
    assert main.verify_password_argon2("", h) is False


# 16
def test_needs_rehash_returns_bool(temp_db):
    h = main.hash_password_argon2("AnotherStrongPass1")
    assert isinstance(main.password_hash_needs_rehash(h), bool)
    assert main.password_hash_needs_rehash("garbage") is False


# 17, 18, 19
def test_password_policy(temp_db):
    assert main.validate_password_policy("short") == ["password_too_short"]
    assert main.validate_password_policy("a" * 129) == ["password_too_long"]
    assert main.validate_password_policy("normal-strong-pass") == []
    # hashing rejects policy violations before hashing
    with pytest.raises(ValueError):
        main.hash_password_argon2("short")
    with pytest.raises(ValueError):
        main.hash_password_argon2("")


# 20
def test_raw_password_not_in_log_tables(temp_db):
    main.init_db()
    secret = "Sup3rSecretLoginPw"
    main.hash_password_argon2(secret)  # hashing must not write the password anywhere
    with main.db() as conn:
        for table in ("security_events", "event_logs", "audit_logs", "auth_passwords"):
            for row in conn.execute(f"SELECT * FROM {table}").fetchall():
                assert secret not in " ".join(str(v) for v in tuple(row))


# 22, 23, 24
def test_existing_auth_untouched():
    import inspect
    ru = inspect.getsource(main.request_user_id)
    ra = inspect.getsource(main.require_admin)
    assert "auth_sessions" not in ru and "auth_sessions" not in ra
    routes = {r.path for r in main.app.routes}
    for p in ("/api/auth/telegram-v2", "/api/auth/max-v2", "/api/auth/email/request-code-v2",
              "/api/auth/email/verify-code-v2", "/api/admin/users-v2", "/api/me/profile-v2"):
        assert p in routes
    # Phase 14.5A: password register/login endpoints must exist
    for p in ("/api/auth/password/register-v2", "/api/auth/password/login-v2"):
        assert p in routes, f"{p} route missing"
