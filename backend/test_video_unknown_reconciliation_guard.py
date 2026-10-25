"""P0 synthetic regressions: unknown video provider outcomes must not expire."""
import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from app.services.video_submission import DuplicateVideoSubmission, blocking_duplicate

NOW = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)
OWNER = "synthetic_video_owner"
FP = "synthetic_fingerprint"


def connection():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE jobs (id TEXT PRIMARY KEY, user_id TEXT, provider TEXT, mode TEXT, "
        "status TEXT, settings_json TEXT, created_at TEXT)"
    )
    return conn


def seed(conn, *, job_id="unknown", owner=OWNER, fingerprint=FP,
         status="failed", state="provider_response_timeout", age_minutes=0, raw=None):
    settings = raw if raw is not None else json.dumps({
        "submissionFingerprint": fingerprint,
        "openrouterSubmissionState": state,
    })
    conn.execute(
        "INSERT INTO jobs VALUES (?,?,?,?,?,?,?)",
        (job_id, owner, "openrouter", "text_to_video", status, settings,
         (NOW - timedelta(minutes=age_minutes)).isoformat()),
    )


@pytest.mark.parametrize("minutes", [1, 14, 16, 361, 60 * 24 * 30])
def test_unknown_outcome_blocks_without_any_time_expiry(minutes):
    conn = connection()
    seed(conn)
    row = blocking_duplicate(conn, OWNER, FP, now=NOW + timedelta(minutes=minutes))
    assert row is not None and row["id"] == "unknown"


def test_old_unknown_cannot_be_hidden_by_more_than_fifty_new_jobs():
    conn = connection()
    seed(conn, age_minutes=60 * 24 * 90)
    for index in range(75):
        seed(conn, job_id=f"newer-{index}", fingerprint=f"other-{index}", state="completed")
    row = blocking_duplicate(conn, OWNER, FP, now=NOW)
    assert row is not None and row["id"] == "unknown"


def test_other_owner_and_other_fingerprint_are_independent():
    conn = connection()
    seed(conn)
    assert blocking_duplicate(conn, "another_owner", FP, now=NOW) is None
    assert blocking_duplicate(conn, OWNER, "another_fingerprint", now=NOW) is None


def test_positive_reconciliation_or_completion_unlocks_new_intent():
    conn = connection()
    seed(conn)
    conn.execute(
        "UPDATE jobs SET settings_json=? WHERE id='unknown'",
        (json.dumps({"submissionFingerprint": FP, "openrouterSubmissionState": "provider_rejected"}),),
    )
    assert blocking_duplicate(conn, OWNER, FP, now=NOW) is None
    conn.execute(
        "UPDATE jobs SET status='completed', settings_json=? WHERE id='unknown'",
        (json.dumps({"submissionFingerprint": FP, "openrouterSubmissionState": "provider_response_timeout"}),),
    )
    assert blocking_duplicate(conn, OWNER, FP, now=NOW) is None


def test_corrupt_unknown_receipt_fails_closed():
    conn = connection()
    seed(conn, raw='{"openrouterSubmissionState":"provider_response_timeout",BROKEN')
    with pytest.raises(DuplicateVideoSubmission, match="invalid metadata"):
        blocking_duplicate(conn, OWNER, FP, now=NOW)


def test_unresolved_active_submissions_remain_blocked():
    conn = connection()
    seed(conn, status="submitting", state="not_sent", age_minutes=60 * 24 * 10)
    assert blocking_duplicate(conn, OWNER, FP, now=NOW) is not None
