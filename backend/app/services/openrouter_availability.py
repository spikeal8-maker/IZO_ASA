"""Durable, administrator-only OpenRouter runtime availability state."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any, Callable


SETTINGS_KEY = "openrouter_runtime_availability"
BLOCKING_STATES = frozenset({"billing_blocked", "authorization_blocked"})


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def default_snapshot() -> dict[str, Any]:
    return {
        "state": "unknown",
        "ready": None,
        "lastStatusCode": None,
        "lastFailureAt": None,
        "lastSuccessAt": None,
    }


def load_snapshot(conn: sqlite3.Connection) -> dict[str, Any]:
    try:
        row = conn.execute(
            "SELECT value_json FROM admin_settings WHERE key = ?",
            (SETTINGS_KEY,),
        ).fetchone()
    except sqlite3.OperationalError:
        return default_snapshot()
    if row is None:
        return default_snapshot()
    try:
        stored = json.loads(row["value_json"] if hasattr(row, "keys") else row[0])
    except (TypeError, ValueError, json.JSONDecodeError):
        return default_snapshot()
    if not isinstance(stored, dict):
        return default_snapshot()
    snapshot = {**default_snapshot(), **stored}
    snapshot["ready"] = snapshot.get("state") == "available"
    return snapshot


def _save_snapshot(conn: sqlite3.Connection, snapshot: dict[str, Any], now: str) -> dict[str, Any]:
    normalized = {**default_snapshot(), **snapshot}
    normalized["ready"] = normalized.get("state") == "available"
    try:
        conn.execute(
            """
            INSERT INTO admin_settings (key, value_json, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value_json = excluded.value_json,
                updated_at = excluded.updated_at
            """,
            (SETTINGS_KEY, json.dumps(normalized, ensure_ascii=False), now),
        )
    except sqlite3.OperationalError as exc:
        if "no such table" not in str(exc).lower():
            raise
    return normalized


def record_failure(
    conn: sqlite3.Connection,
    status_code: int,
    *,
    now: str | None = None,
) -> dict[str, Any]:
    """Persist a classified provider failure without retaining provider secrets."""

    timestamp = now or utc_now()
    current = load_snapshot(conn)
    code = int(status_code)
    if code == 402:
        state = "billing_blocked"
    elif code in {401, 403}:
        state = "authorization_blocked"
    else:
        state = current.get("state") if current.get("state") in BLOCKING_STATES else "service_error"
    return _save_snapshot(
        conn,
        {
            **current,
            "state": state,
            "lastStatusCode": code,
            "lastFailureAt": timestamp,
        },
        timestamp,
    )


def record_success(
    conn: sqlite3.Connection,
    *,
    now: str | None = None,
) -> dict[str, Any]:
    """A completed paid request is authoritative evidence that generation works."""

    timestamp = now or utc_now()
    current = load_snapshot(conn)
    return _save_snapshot(
        conn,
        {
            **current,
            "state": "available",
            "lastStatusCode": 200,
            "lastSuccessAt": timestamp,
        },
        timestamp,
    )


def attach_to_key_status(
    status: dict[str, Any],
    availability: dict[str, Any],
) -> dict[str, Any]:
    """Combine read-only key checks with the last real generation outcome."""

    result = dict(status)
    runtime = {**default_snapshot(), **availability}
    key_ok = bool(result.get("ok"))
    state = str(runtime.get("state") or "unknown")
    result["availability"] = runtime
    if not key_ok or state in BLOCKING_STATES or state == "service_error":
        result["ready"] = False
    elif state == "available":
        result["ready"] = True
    else:
        result["ready"] = None
    return result


class Runtime:
    """Composition adapter that keeps diagnostic persistence non-fatal."""

    def __init__(self, connect: Callable[[], Any], invalidate: Callable[[], None]) -> None:
        self._connect = connect
        self._invalidate = invalidate

    def snapshot(self) -> dict[str, Any]:
        try:
            with self._connect() as conn:
                return load_snapshot(conn)
        except sqlite3.Error:
            return default_snapshot()

    def attach(self, status: dict[str, Any]) -> dict[str, Any]:
        return attach_to_key_status(status, self.snapshot())

    def record(self, status_code: int) -> None:
        try:
            with self._connect() as conn:
                if int(status_code) < 400:
                    record_success(conn)
                else:
                    record_failure(conn, status_code)
            self._invalidate()
        except sqlite3.Error:
            return
