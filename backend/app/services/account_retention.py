"""Bounded cleanup for password accounts that never linked MAX or Telegram."""

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import Callable
from typing import Any

from ..security.account_verification import get_social_verification


PROTECTED_LEGACY_USER_IDS = {"demo_user", "web_admin"}
DEFAULT_ACCOUNT_RETENTION_INTERVAL_SECONDS = 60 * 60
DEFAULT_ACCOUNT_RETENTION_BATCH_SIZE = 50


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone() is not None


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    if not _table_exists(conn, table):
        return set()
    return {str(row["name"]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _update_available_columns(
    conn: sqlite3.Connection,
    table: str,
    values: dict[str, Any],
    *,
    where: str,
    params: tuple[Any, ...],
) -> None:
    columns = _columns(conn, table)
    selected = [(name, value) for name, value in values.items() if name in columns]
    if not selected:
        return
    assignments = ", ".join(f"{name} = ?" for name, _value in selected)
    conn.execute(
        f"UPDATE {table} SET {assignments} WHERE {where}",
        tuple(value for _name, value in selected) + params,
    )


def _anonymize_account(
    conn: sqlite3.Connection,
    *,
    internal_user_id: str,
    legacy_user_id: str,
    now: str,
) -> None:
    _update_available_columns(
        conn,
        "users",
        {
            "banned": 1,
            "telegram_id": None,
            "max_id": None,
            "username": None,
            "first_name": None,
            "last_name": None,
            "middle_name": None,
            "display_name": "Удалённый пользователь",
            "email": None,
            "phone": None,
            "country": None,
            "city": None,
            "timezone": None,
            "avatar_url": None,
            "avatar_preset": None,
            "public_about": None,
            "public_website": None,
            "public_focus": None,
            "public_phone": None,
            "public_links_json": None,
            "gender": None,
            "age": None,
            "last_user_agent": None,
            "last_screen": None,
            "gallery_enabled": 0,
        },
        where="internal_user_id = ?",
        params=(internal_user_id,),
    )

    if _table_exists(conn, "auth_identities"):
        conn.execute("DELETE FROM auth_identities WHERE internal_user_id = ?", (internal_user_id,))
    if _table_exists(conn, "auth_passwords"):
        conn.execute("DELETE FROM auth_passwords WHERE internal_user_id = ?", (internal_user_id,))
    if _table_exists(conn, "auth_sessions"):
        conn.execute("DELETE FROM auth_sessions WHERE internal_user_id = ?", (internal_user_id,))
    if _table_exists(conn, "password_reset_challenges"):
        conn.execute("DELETE FROM password_reset_challenges WHERE internal_user_id = ?", (internal_user_id,))

    _update_available_columns(
        conn,
        "device_installations",
        {"internal_user_id": None, "legacy_user_id": None},
        where="internal_user_id = ?",
        params=(internal_user_id,),
    )
    _update_available_columns(
        conn,
        "user_billing_profiles",
        {"receipt_email": None, "updated_at": now},
        where="internal_user_id = ?",
        params=(internal_user_id,),
    )
    _update_available_columns(
        conn,
        "jobs",
        {
            "prompt_original": None,
            "prompt_translated": None,
            "error_message": None,
            "settings_json": "{}",
        },
        where="user_id = ?",
        params=(legacy_user_id,),
    )
    _update_available_columns(
        conn,
        "images",
        {
            "prompt_original": None,
            "prompt_translated": None,
            "settings_json": "{}",
            "is_favorite": 0,
            "deleted_at": now,
        },
        where="user_id = ?",
        params=(legacy_user_id,),
    )
    _update_available_columns(
        conn,
        "videos",
        {"prompt_original": None, "settings_json": "{}", "is_favorite": 0, "deleted_at": now},
        where="user_id = ?",
        params=(legacy_user_id,),
    )
    _update_available_columns(
        conn,
        "image_sources",
        {"is_favorite": 0, "library_deleted_at": now},
        where="user_id = ?",
        params=(legacy_user_id,),
    )
    _update_available_columns(
        conn,
        "feed_publications",
        {
            "title": "Удалено",
            "description": None,
            "status": "hidden",
            "moderation_status": "rejected",
            "moderation_reason": "account_deleted_unverified_social",
            "moderated_at": now,
        },
        where="internal_user_id = ?",
        params=(internal_user_id,),
    )

    for table, where in (
        ("feed_reactions", "internal_user_id = ?"),
        ("feed_subscription_reads", "internal_user_id = ?"),
        ("feed_author_follows", "follower_internal_user_id = ? OR author_internal_user_id = ?"),
    ):
        if not _table_exists(conn, table):
            continue
        params = (internal_user_id, internal_user_id) if " OR " in where else (internal_user_id,)
        conn.execute(f"DELETE FROM {table} WHERE {where}", params)

    conn.execute(
        """
        UPDATE account_verifications
        SET status = 'deleted', deleted_at = ?, updated_at = ?
        WHERE internal_user_id = ? AND status = 'pending'
        """,
        (now, now, internal_user_id),
    )


def _process_due_account(
    conn: sqlite3.Connection,
    row: sqlite3.Row,
    *,
    now: str,
    record_security_event: Callable[..., Any] | None,
) -> str:
    """Process one already-due row and return its terminal outcome."""
    internal_user_id = str(row["internal_user_id"])
    social = conn.execute(
        """
        SELECT provider, provider_user_id FROM auth_identities
        WHERE internal_user_id = ? AND provider IN ('max', 'telegram')
          AND verified_at IS NOT NULL
        ORDER BY linked_at LIMIT 1
        """,
        (internal_user_id,),
    ).fetchone()
    if social:
        conn.execute(
            """
            UPDATE account_verifications
            SET status = 'verified', verified_at = ?, verified_provider = ?,
                provider_user_id = ?, updated_at = ?
            WHERE internal_user_id = ? AND status = 'pending'
            """,
            (now, social["provider"], social["provider_user_id"], now, internal_user_id),
        )
        return "reconciled"

    legacy_user_id = row["legacy_user_id"]
    if (
        not legacy_user_id
        or str(legacy_user_id) in PROTECTED_LEGACY_USER_IDS
        or str(row["role"] or "") == "admin"
    ):
        return "protected"
    _anonymize_account(
        conn,
        internal_user_id=internal_user_id,
        legacy_user_id=str(legacy_user_id),
        now=now,
    )
    if record_security_event is not None:
        record_security_event(
            conn,
            "account_deleted_unverified_social",
            severity="warning",
            internal_user_id=internal_user_id,
            details={"retention_days": 30},
        )
    return "deleted"


def cleanup_due_unverified_accounts(
    connect: Callable[[], sqlite3.Connection],
    *,
    now: str,
    limit: int = DEFAULT_ACCOUNT_RETENTION_BATCH_SIZE,
    record_security_event: Callable[..., Any] | None = None,
) -> dict[str, int]:
    """Anonymize a bounded due batch; financial/audit rows remain intact."""
    report = {"checked": 0, "deleted": 0, "reconciled": 0, "protected": 0}
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        due = conn.execute(
            """
            SELECT av.internal_user_id, u.id AS legacy_user_id, u.role
            FROM account_verifications av
            LEFT JOIN users u ON u.internal_user_id = av.internal_user_id
            WHERE av.verification_kind = 'social' AND av.status = 'pending'
              AND av.delete_after_at <= ?
            ORDER BY av.delete_after_at, av.internal_user_id
            LIMIT ?
            """,
            (now, max(1, int(limit))),
        ).fetchall()
        for row in due:
            report["checked"] += 1
            outcome = _process_due_account(
                conn,
                row,
                now=now,
                record_security_event=record_security_event,
            )
            report[outcome] += 1
    return report


def delete_due_unverified_account(
    connect: Callable[[], sqlite3.Connection],
    internal_user_id: str,
    *,
    now: str,
    record_security_event: Callable[..., Any] | None = None,
) -> str:
    """Prevent a due account from receiving a fresh session at password login."""
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            """
            SELECT av.internal_user_id, u.id AS legacy_user_id, u.role
            FROM account_verifications av
            LEFT JOIN users u ON u.internal_user_id = av.internal_user_id
            WHERE av.internal_user_id = ? AND av.verification_kind = 'social'
              AND av.status = 'pending' AND av.delete_after_at <= ?
            """,
            (internal_user_id, now),
        ).fetchone()
        if row is None:
            return "not_due"
        return _process_due_account(
            conn,
            row,
            now=now,
            record_security_event=record_security_event,
        )


def enforce_due_unverified_login(
    connect: Callable[[], sqlite3.Connection],
    internal_user_id: str,
    *,
    now: str,
    record_security_event: Callable[..., Any] | None = None,
) -> tuple[dict[str, Any] | None, str]:
    """Resolve the reminder state and prevent a due account receiving a session."""
    with connect() as conn:
        state = get_social_verification(conn, internal_user_id, now=now)
    if not state or not state["social_verification_deletion_due"]:
        return state, "not_due"
    outcome = delete_due_unverified_account(
        connect, internal_user_id, now=now, record_security_event=record_security_event,
    )
    if outcome == "reconciled":
        with connect() as conn:
            state = get_social_verification(conn, internal_user_id, now=now)
    return state, outcome


class AccountRetentionWorker:
    def __init__(self) -> None:
        self._task: asyncio.Task[None] | None = None
        self._stop: asyncio.Event | None = None

    def start(
        self,
        *,
        connect: Callable[[], sqlite3.Connection],
        record_security_event: Callable[..., Any] | None = None,
        interval_seconds: int = DEFAULT_ACCOUNT_RETENTION_INTERVAL_SECONDS,
    ) -> None:
        if self._task and not self._task.done():
            return
        self._stop = asyncio.Event()

        async def run() -> None:
            assert self._stop is not None
            while not self._stop.is_set():
                try:
                    report = await asyncio.to_thread(
                        cleanup_due_unverified_accounts,
                        connect,
                        now=datetime_now_iso(),
                        record_security_event=record_security_event,
                    )
                    if report["checked"]:
                        print(f"account retention cleanup: {report}")
                except Exception as exc:  # pragma: no cover - operational guard
                    print(f"account retention cleanup error: {type(exc).__name__}")
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=max(60, interval_seconds))
                except TimeoutError:
                    continue

        self._task = asyncio.create_task(run())

    def start_with_cleanup(
        self,
        *,
        connect: Callable[[], sqlite3.Connection],
        record_security_event: Callable[..., Any] | None = None,
    ) -> None:
        try:
            report = cleanup_due_unverified_accounts(
                connect, now=datetime_now_iso(), record_security_event=record_security_event,
            )
            if report["checked"]:
                print(f"account retention startup cleanup: {report}")
        except Exception as exc:  # pragma: no cover - operational guard
            print(f"account retention startup cleanup error: {type(exc).__name__}")
        self.start(connect=connect, record_security_event=record_security_event)

    async def stop(self) -> None:
        if self._stop is not None:
            self._stop.set()
        if self._task is not None:
            await self._task
        self._task = None
        self._stop = None


def datetime_now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()
