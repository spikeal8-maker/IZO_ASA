"""Deferred social-account verification for password registrations.

Password users may enter the account immediately, but resource-consuming
generation stays locked until they link MAX or Telegram. The browser reminds
them again on a later login after 24 hours. Accounts still pending after 30
days become due for the bounded retention/anonymization worker.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from .trial_access import TRIAL_REMINDER_SECONDS, trial_payload


SOCIAL_VERIFICATION_REMINDER_SECONDS = TRIAL_REMINDER_SECONDS
SOCIAL_VERIFICATION_DELETE_SECONDS = 30 * 24 * 60 * 60
SocialProvider = Literal["max", "telegram"]


def upsert_web_email_identity(
    conn: sqlite3.Connection,
    email_norm: str,
    now: str,
    *,
    verified: bool = True,
    initialize_intro: bool = True,
    random_avatar_choice: Callable[[], tuple[str, str]],
    initialize_intro_tariff: Callable[[sqlite3.Connection, str, str], bool],
) -> tuple[str, str]:
    """Resolve/create web identity without ever merging on unverified users.email."""
    existing = conn.execute(
        "SELECT id, internal_user_id, legacy_user_id FROM auth_identities "
        "WHERE provider='web_email' AND provider_user_id=?",
        (email_norm,),
    ).fetchone()
    if existing:
        if verified:
            conn.execute(
                "UPDATE auth_identities SET provider_email=?, verified_at=COALESCE(verified_at, ?), "
                "last_login_at=? WHERE id=?",
                (email_norm, now, now, existing["id"]),
            )
        else:
            conn.execute("UPDATE auth_identities SET provider_email=? WHERE id=?", (email_norm, existing["id"]))
        if existing["legacy_user_id"]:
            conn.execute("UPDATE users SET last_login_at=? WHERE id=?", (now, existing["legacy_user_id"]))
            if initialize_intro:
                created = conn.execute("SELECT created_at FROM users WHERE id=?", (existing["legacy_user_id"],)).fetchone()
                if created:
                    initialize_intro_tariff(conn, existing["legacy_user_id"], created["created_at"])
        return existing["internal_user_id"], existing["legacy_user_id"]

    legacy_user_id = f"web_{uuid.uuid4().hex}"
    internal_user_id = uuid.uuid4().hex
    user_columns = {row["name"] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
    avatar_url, avatar_preset = random_avatar_choice()
    if "email" in user_columns:
        conn.execute(
            """
            INSERT OR IGNORE INTO users
                (id, email, language, role, plan, token_balance, gallery_enabled,
                 avatar_url, avatar_preset, created_at, last_login_at, internal_user_id)
            VALUES (?, ?, 'ru', 'user', ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (legacy_user_id, email_norm, "mini" if initialize_intro else "free",
             50 if initialize_intro else 0, 1, avatar_url,
             avatar_preset, now, now, internal_user_id),
        )
    else:
        conn.execute(
            """
            INSERT OR IGNORE INTO users
                (id, language, role, avatar_url, avatar_preset, created_at, last_login_at, internal_user_id)
            VALUES (?, 'ru', 'user', ?, ?, ?, ?, ?)
            """,
            (legacy_user_id, avatar_url, avatar_preset, now, now, internal_user_id),
        )
    row = conn.execute("SELECT internal_user_id FROM users WHERE id=?", (legacy_user_id,)).fetchone()
    if row and row["internal_user_id"]:
        internal_user_id = row["internal_user_id"]
    conn.execute(
        """
        INSERT OR IGNORE INTO auth_identities
            (id, internal_user_id, legacy_user_id, provider, provider_user_id, provider_email,
             raw_profile_json, verified_at, linked_at, last_login_at)
        VALUES (?, ?, ?, 'web_email', ?, ?, ?, ?, ?, ?)
        """,
        (uuid.uuid4().hex, internal_user_id, legacy_user_id, email_norm, email_norm,
         json.dumps({"email": email_norm}, ensure_ascii=False), now if verified else None,
         now, now if verified else None),
    )
    if initialize_intro:
        initialize_intro_tariff(conn, legacy_user_id, now)
    return internal_user_id, legacy_user_id


def complete_social_verification(
    conn: sqlite3.Connection,
    internal_user_id: str,
    *,
    provider: SocialProvider,
    provider_user_id: str,
    now: str,
    initialize_intro_tariff: Callable[[sqlite3.Connection, str, str], bool],
) -> bool:
    """Mark verified and enable the signup tariff exactly once."""
    if not mark_social_verified(conn, internal_user_id, provider=provider, provider_user_id=provider_user_id, now=now):
        return False
    user = conn.execute("SELECT id, created_at FROM users WHERE internal_user_id=?", (internal_user_id,)).fetchone()
    if user:
        initialize_intro_tariff(conn, user["id"], user["created_at"])
    return True


def generation_block_detail(conn: sqlite3.Connection, internal_user_id: str, *, now: str) -> dict[str, Any] | None:
    state = get_social_verification(conn, internal_user_id, now=now)
    if not state or not state["social_verification_pending"]:
        return None
    return {
        "code": "social_verification_required",
        "message": "Подтвердите аккаунт через MAX или Telegram, чтобы создавать изображения и видео.",
        "remind_after_at": state["social_verification_remind_after_at"],
        "delete_after_at": state["social_verification_delete_after_at"],
    }


def ensure_social_requirement(
    conn: sqlite3.Connection,
    internal_user_id: str,
    *,
    enabled: bool,
    now: str,
) -> dict[str, Any] | None:
    if not enabled:
        return None
    verified = conn.execute(
        "SELECT 1 FROM auth_identities WHERE internal_user_id=? "
        "AND provider IN ('max','telegram') AND verified_at IS NOT NULL",
        (internal_user_id,),
    ).fetchone()
    return None if verified else require_social_verification(conn, internal_user_id, now=now)


def _as_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def require_social_verification(
    conn: sqlite3.Connection,
    internal_user_id: str,
    *,
    now: str,
    reminder_seconds: int = SOCIAL_VERIFICATION_REMINDER_SECONDS,
    delete_seconds: int = SOCIAL_VERIFICATION_DELETE_SECONDS,
) -> dict[str, Any]:
    """Create a deferred MAX-or-Telegram requirement once."""
    now_dt = _as_utc(now)
    remind_after_at = (now_dt + timedelta(seconds=reminder_seconds)).isoformat()
    delete_after_at = (now_dt + timedelta(seconds=delete_seconds)).isoformat()
    conn.execute(
        """
        INSERT INTO account_verifications
            (internal_user_id, verification_kind, status, required_at,
             remind_after_at, delete_after_at, verified_at, verified_provider,
             provider_user_id, deleted_at, updated_at)
        VALUES (?, 'social', 'pending', ?, ?, ?, NULL, NULL, NULL, NULL, ?)
        ON CONFLICT(internal_user_id) DO NOTHING
        """,
        (internal_user_id, now, remind_after_at, delete_after_at, now),
    )
    row = conn.execute(
        "SELECT * FROM account_verifications WHERE internal_user_id = ?",
        (internal_user_id,),
    ).fetchone()
    if row is None:  # pragma: no cover - defensive invariant
        raise RuntimeError("ACCOUNT_VERIFICATION_STATE_MISSING")
    base = verification_payload(row, now=now)
    trial = trial_payload(conn, internal_user_id, required_at=row["required_at"], pending=base["social_verification_pending"], now=now)
    return {**base, **trial, "social_verification_blocks_generation": trial["trial_generation_blocked"]}


def get_social_verification(
    conn: sqlite3.Connection,
    internal_user_id: str,
    *,
    now: str,
) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT * FROM account_verifications
        WHERE internal_user_id = ? AND verification_kind = 'social'
        """,
        (internal_user_id,),
    ).fetchone()
    if row is None:
        return None
    base = verification_payload(row, now=now)
    trial = trial_payload(conn, internal_user_id, required_at=row["required_at"], pending=base["social_verification_pending"], now=now)
    return {**base, **trial, "social_verification_blocks_generation": trial["trial_generation_blocked"]}


def mark_social_verified(
    conn: sqlite3.Connection,
    internal_user_id: str,
    *,
    provider: SocialProvider,
    provider_user_id: str,
    now: str,
) -> bool:
    """Complete a pending requirement after a MAX or Telegram identity link."""
    if provider not in {"max", "telegram"}:
        return False
    changed = conn.execute(
        """
        UPDATE account_verifications
        SET status = 'verified', verified_at = ?, verified_provider = ?,
            provider_user_id = ?, updated_at = ?
        WHERE internal_user_id = ? AND verification_kind = 'social' AND status = 'pending'
        """,
        (now, provider, provider_user_id, now, internal_user_id),
    ).rowcount
    return bool(changed)


def verification_payload(row: Any, *, now: str) -> dict[str, Any]:
    now_dt = _as_utc(now)
    status = str(row["status"])
    remind_after_at = str(row["remind_after_at"])
    delete_after_at = str(row["delete_after_at"])
    return {
        "social_verification_status": status,
        "social_verification_pending": status == "pending",
        "social_verification_blocks_generation": False,
        "should_prompt_social_verification": (
            status == "pending" and now_dt >= _as_utc(remind_after_at)
        ),
        "social_verification_required_at": str(row["required_at"]),
        "social_verification_remind_after_at": remind_after_at,
        "social_verification_delete_after_at": delete_after_at,
        "social_verification_deletion_due": (
            status == "pending" and now_dt >= _as_utc(delete_after_at)
        ),
        "social_verification_provider": row["verified_provider"],
        "social_verification_verified_at": row["verified_at"],
    }
