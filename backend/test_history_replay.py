"""Restore fencing uses synthetic WAL SQLite only; no runtime or providers."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from app.services.history_replay import (
    RESOURCE_COLUMNS,
    HistoricalReplayBlocked,
    HistoryReplayConfigurationError,
    history_policy_for_connection,
    history_preservation_enabled,
    initialize_history_replay,
    seal_restored_history,
)

SNAPSHOT = "synthetic-snapshot-20261104"
SCHEMA = """
CREATE TABLE history_replay_boundary (
    singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
    snapshot_id TEXT NOT NULL UNIQUE CHECK(length(snapshot_id) > 0),
    sealed_at TEXT NOT NULL,
    manifest_json TEXT NOT NULL,
    manifest_sha256 TEXT NOT NULL CHECK(length(manifest_sha256) = 64)
);
CREATE TABLE history_replay_resources (
    snapshot_id TEXT NOT NULL,
    resource TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    PRIMARY KEY(snapshot_id, resource, resource_id),
    FOREIGN KEY(snapshot_id) REFERENCES history_replay_boundary(snapshot_id)
        DEFERRABLE INITIALLY DEFERRED
) WITHOUT ROWID;
"""


def install_schema(conn):
    conn.executescript(SCHEMA)
    conn.execute(
        "CREATE TRIGGER boundary_no_replace BEFORE INSERT ON history_replay_boundary "
        "WHEN EXISTS (SELECT 1 FROM history_replay_boundary WHERE singleton = 1) "
        "BEGIN SELECT RAISE(ABORT, 'history replay boundary is immutable'); END"
    )
    for event in ("UPDATE", "DELETE"):
        conn.execute(
            f"CREATE TRIGGER boundary_no_{event.lower()} BEFORE {event} "
            "ON history_replay_boundary BEGIN "
            "SELECT RAISE(ABORT, 'history replay boundary is immutable'); END"
        )
    for event in ("INSERT", "UPDATE", "DELETE"):
        conn.execute(
            f"CREATE TRIGGER resources_no_{event.lower()} BEFORE {event} "
            "ON history_replay_resources WHEN EXISTS "
            "(SELECT 1 FROM history_replay_boundary WHERE singleton = 1) BEGIN "
            "SELECT RAISE(ABORT, 'history replay resources are immutable'); END"
        )


def connect(path):
    conn = sqlite3.connect(path, timeout=10)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=10000")
    return conn


def insert(conn, resource, identity, *, parent=None, status="pending"):
    column = RESOURCE_COLUMNS[resource]
    conn.execute(
        f'INSERT INTO "{resource}" '
        f'("{column}", user_id, parent_id, status, token_balance, delta) '
        "VALUES (?, 'old-users', ?, ?, 100, 3)",
        (identity, parent, status),
    )


@pytest.fixture
def history(tmp_path):
    path = tmp_path / "synthetic.sqlite3"
    conn = connect(path)
    assert conn.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
    install_schema(conn)
    for resource, column in RESOURCE_COLUMNS.items():
        conn.execute(
            f'CREATE TABLE "{resource}" ("{column}" TEXT PRIMARY KEY, '
            "user_id TEXT, parent_id TEXT, status TEXT, token_balance INTEGER, delta INTEGER)"
        )
        insert(
            conn, resource, "old-" + resource,
            parent="old-feed_publications" if resource == "social_delivery_outbox" else None,
        )
    conn.commit()
    yield path, conn
    conn.close()


def source_state(conn):
    return {
        name: conn.execute(f'SELECT * FROM "{name}" ORDER BY 1').fetchall()
        for name in RESOURCE_COLUMNS
    }


def seal(conn, **kwargs):
    policy = seal_restored_history(conn, snapshot_id=SNAPSHOT, **kwargs)
    conn.commit()
    return policy


def test_seal_preserves_sources_and_read_only_init_survives_restart(history):
    path, conn = history
    before = source_state(conn)
    seal(conn, expected_counts={"users": 1, "images": 1, "videos": 1, "jobs": 1, "token_ledger": 1})
    assert source_state(conn) == before
    with connect(path) as restarted:
        statements = []
        restarted.set_trace_callback(statements.append)
        policy = initialize_history_replay(restarted, enabled=True, expected_snapshot_id=SNAPSHOT)
        assert policy.is_historical("jobs", "old-jobs")
        assert not policy.automatic_history_mutation_allowed
        assert restarted.total_changes == 0
        assert statements and all(s.lstrip().upper().startswith("SELECT") for s in statements)
        assert source_state(restarted) == before


@pytest.mark.parametrize("status", ["queued", "running", "uploading", "completed", "failed"])
def test_old_job_blocked_before_execution_or_refund_for_every_status(history, status):
    _, conn = history
    conn.execute("UPDATE jobs SET status=?", (status,))
    policy = seal(conn)
    before = source_state(conn)
    effects = []
    with pytest.raises(HistoricalReplayBlocked):
        policy.require_allowed("jobs", "old-jobs")
        effects.append("provider/refund")
    assert effects == []
    assert source_state(conn) == before


def test_new_jobs_for_historical_users_remain_allowed(history):
    _, conn = history
    policy = seal(conn)
    insert(conn, "jobs", "new-job", status="queued")
    policy.require_allowed("jobs", "new-job")
    assert policy.is_historical("users", "old-users")
    assert not policy.is_historical("jobs", "new-job")
    predicate, args = policy.where_allowed("jobs", "j.id")
    assert conn.execute(f"SELECT j.id FROM jobs j WHERE {predicate}", args).fetchall() == [("new-job",)]


def test_second_seal_does_not_expand_and_rejects_other_snapshot(history):
    _, conn = history
    seal(conn)
    original = conn.execute("SELECT * FROM history_replay_resources").fetchall()
    insert(conn, "jobs", "new-job")
    conn.commit()
    changes = conn.total_changes
    again = seal(conn, expected_counts={"jobs": 1})
    assert conn.total_changes == changes
    assert not again.is_historical("jobs", "new-job")
    assert conn.execute("SELECT * FROM history_replay_resources").fetchall() == original
    with pytest.raises(HistoryReplayConfigurationError, match="does not match"):
        seal_restored_history(conn, snapshot_id="different-snapshot")
    conn.rollback()
    with pytest.raises(HistoryReplayConfigurationError, match="does not match"):
        initialize_history_replay(conn, enabled=True, expected_snapshot_id="different-snapshot")


def test_new_delivery_of_historical_parent_is_blocked_in_query_and_execution(history):
    _, conn = history
    policy = seal(conn)
    insert(conn, "feed_publications", "new-publication")
    insert(conn, "social_delivery_outbox", "new-old-parent", parent="old-feed_publications")
    insert(conn, "social_delivery_outbox", "new-new-parent", parent="new-publication")
    predicate, args = policy.where_allowed(
        "social_delivery_outbox", "o.id",
        parents=(("feed_publications", "o.parent_id"),),
    )
    assert conn.execute(
        f"SELECT o.id FROM social_delivery_outbox o WHERE {predicate}", args,
    ).fetchall() == [("new-new-parent",)]
    with pytest.raises(HistoricalReplayBlocked):
        policy.require_allowed(
            "social_delivery_outbox", "new-old-parent",
            parents=(("feed_publications", "old-feed_publications"),),
        )
    policy.require_allowed(
        "social_delivery_outbox", "new-new-parent",
        parents=(("feed_publications", "new-publication"),),
    )


@pytest.mark.parametrize("resource", [
    "payment_notification_outbox", "admin_notification_delivery_outbox",
    "social_delivery_outbox", "payments", "feed_publications", "video_file_deletions",
])
def test_pending_outgoing_and_preparing_historical_resources_are_fenced(history, resource):
    _, conn = history
    conn.execute(f'UPDATE "{resource}" SET status=?', ("preparing",))
    policy = seal(conn)
    with pytest.raises(HistoricalReplayBlocked):
        policy.require_allowed(resource, "old-" + resource)
    predicate, args = policy.where_allowed(resource, RESOURCE_COLUMNS[resource])
    assert conn.execute(f'SELECT * FROM "{resource}" WHERE {predicate}', args).fetchall() == []


def test_missing_schema_missing_boundary_and_invalid_flag_fail_closed(history):
    _, conn = history
    with sqlite3.connect(":memory:") as empty:
        with pytest.raises(HistoryReplayConfigurationError, match="migration"):
            initialize_history_replay(empty, enabled=True)
        disabled = initialize_history_replay(empty, enabled=False)
        disabled.require_allowed("jobs", "old")
        assert disabled.where_allowed("jobs", "j.id") == ("1 = 1", ())
        assert disabled.automatic_history_mutation_allowed
    with pytest.raises(HistoryReplayConfigurationError, match="Exactly one"):
        initialize_history_replay(conn, enabled=True)
    with pytest.raises(HistoryReplayConfigurationError):
        history_preservation_enabled({"IZO_PREPROD_PRESERVE_HISTORY": "tru"})
    with pytest.raises(HistoryReplayConfigurationError):
        history_policy_for_connection(conn, environment={"IZO_PREPROD_PRESERVE_HISTORY": "1"})


@pytest.mark.parametrize("corruption", ["hash", "missing-id", "manifest-count"])
def test_corrupt_seal_fails_closed(history, corruption):
    _, conn = history
    seal(conn)
    if corruption == "missing-id":
        conn.execute("DROP TRIGGER resources_no_delete")
        conn.execute("DELETE FROM history_replay_resources WHERE resource='jobs'")
    else:
        conn.execute("DROP TRIGGER boundary_no_update")
        if corruption == "hash":
            conn.execute("UPDATE history_replay_boundary SET manifest_sha256=?", ("0" * 64,))
        else:
            manifest = json.loads(conn.execute("SELECT manifest_json FROM history_replay_boundary").fetchone()[0])
            manifest["resources"]["jobs"]["count"] += 1
            raw = json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            conn.execute(
                "UPDATE history_replay_boundary SET manifest_json=?, manifest_sha256=?",
                (raw, hashlib.sha256(raw.encode()).hexdigest()),
            )
    conn.commit()
    with pytest.raises(HistoryReplayConfigurationError):
        initialize_history_replay(conn, enabled=True)


def test_immutable_schema_blocks_late_fence_changes(history):
    _, conn = history
    seal(conn)
    for statement, args in [
        ("UPDATE history_replay_boundary SET sealed_at='changed'", ()),
        ("DELETE FROM history_replay_boundary", ()),
        ("INSERT OR REPLACE INTO history_replay_boundary SELECT * FROM history_replay_boundary", ()),
        ("UPDATE history_replay_resources SET resource_id='changed'", ()),
        ("DELETE FROM history_replay_resources", ()),
        ("INSERT INTO history_replay_resources VALUES (?, 'jobs', 'new-job')", (SNAPSHOT,)),
    ]:
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            conn.execute(statement, args)
        conn.rollback()
    assert initialize_history_replay(conn, enabled=True).is_historical("jobs", "old-jobs")


def test_failed_seal_rolls_back_own_writes_preserving_caller_transaction(history):
    _, conn = history
    conn.execute(
        "CREATE TRIGGER reject_seal BEFORE INSERT ON history_replay_boundary "
        "BEGIN SELECT RAISE(ABORT, 'injected failure'); END"
    )
    conn.commit()
    conn.execute("UPDATE users SET token_balance=101")
    with pytest.raises(sqlite3.IntegrityError, match="injected failure"):
        seal_restored_history(conn, snapshot_id=SNAPSHOT)
    assert conn.in_transaction
    assert conn.execute("SELECT COUNT(*) FROM history_replay_resources").fetchone()[0] == 0
    assert conn.execute("SELECT token_balance FROM users").fetchone()[0] == 101
    conn.rollback()
    assert conn.execute("SELECT token_balance FROM users").fetchone()[0] == 100


def test_caller_rollback_removes_whole_seal_and_count_mismatch_writes_nothing(history):
    _, conn = history
    with pytest.raises(HistoryReplayConfigurationError, match="count"):
        seal_restored_history(conn, snapshot_id=SNAPSHOT, expected_counts={"jobs": 2})
    assert conn.execute("SELECT COUNT(*) FROM history_replay_resources").fetchone()[0] == 0
    conn.rollback()
    seal_restored_history(conn, snapshot_id=SNAPSHOT)
    assert conn.in_transaction
    conn.rollback()
    assert conn.execute("SELECT COUNT(*) FROM history_replay_boundary").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM history_replay_resources").fetchone()[0] == 0


@pytest.mark.parametrize("contenders", [2, 5])
def test_concurrent_seals_converge_without_expansion(history, contenders):
    path, conn = history
    before = source_state(conn)
    barrier = Barrier(contenders)

    def attempt():
        with connect(path) as separate:
            barrier.wait(timeout=10)
            policy = seal_restored_history(separate, snapshot_id=SNAPSHOT)
            assert policy.is_historical("jobs", "old-jobs")
        return True

    with ThreadPoolExecutor(max_workers=contenders) as pool:
        assert list(pool.map(lambda _: attempt(), range(contenders))) == [True] * contenders
    assert conn.execute("SELECT COUNT(*) FROM history_replay_boundary").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM history_replay_resources").fetchone()[0] == len(RESOURCE_COLUMNS)
    assert source_state(conn) == before


def test_sql_identifiers_and_unknown_resources_are_rejected(history):
    _, conn = history
    policy = seal(conn)
    for column in ("id OR 1=1", "j.id; DROP TABLE jobs", "id)", "j.*"):
        with pytest.raises(HistoryReplayConfigurationError):
            policy.where_allowed("jobs", column)
    with pytest.raises(HistoryReplayConfigurationError):
        policy.require_allowed("unknown", "x")
    with pytest.raises(HistoryReplayConfigurationError):
        policy.require_allowed("jobs", None)


def test_connection_helper_does_not_cache_a_different_database(history):
    _, conn = history
    seal(conn)
    env = {"IZO_PREPROD_PRESERVE_HISTORY": "true", "IZO_HISTORY_SNAPSHOT_ID": SNAPSHOT}
    assert history_policy_for_connection(conn, environment=env).is_historical("jobs", "old-jobs")
    with sqlite3.connect(":memory:") as other:
        with pytest.raises(HistoryReplayConfigurationError):
            history_policy_for_connection(other, environment=env)


def test_missing_source_identity_column_fails_closed(history):
    _, conn = history
    conn.execute("DROP TABLE jobs")
    conn.execute("CREATE TABLE jobs (wrong_id TEXT PRIMARY KEY)")
    conn.execute("INSERT INTO jobs VALUES ('old-job')")
    conn.commit()
    with pytest.raises(HistoryReplayConfigurationError, match="column is missing"):
        seal_restored_history(conn, snapshot_id=SNAPSHOT)
    assert conn.execute("SELECT COUNT(*) FROM history_replay_resources").fetchone()[0] == 0
    conn.rollback()


@pytest.mark.parametrize("resource", ["jobs", "payments"])
def test_sql_predicate_rejects_null_even_when_historical_set_is_empty(history, resource):
    _, conn = history
    conn.execute(f'DELETE FROM "{resource}"')
    policy = seal(conn)
    predicate, args = policy.where_allowed(resource, "candidate.id")
    assert conn.execute(
        f"SELECT candidate.id FROM (SELECT NULL AS id) candidate WHERE {predicate}", args,
    ).fetchall() == []
