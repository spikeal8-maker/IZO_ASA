"""Trusted session lifecycle independent from FastAPI and application globals."""

from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any


@dataclass(frozen=True)
class SessionRuntime:
    connect: Callable[[], sqlite3.Connection]
    validate_crypto: Callable[[], None]
    generate_token: Callable[[], str]
    hash_token: Callable[[str], str]
    record_session_event: Callable[..., None]
    record_security_event: Callable[..., None]
    user_is_banned: Callable[[sqlite3.Connection, str | None, str | None], bool]
    ensure_public_user_code: Callable[[sqlite3.Connection, str], str | None]
    get_client_ip: Callable[[Any | None], str | None]
    hash_user_agent: Callable[[Any | None], str | None]
    parse_user_agent: Callable[[str | None], dict[str, str]]


class SessionAccessError(RuntimeError):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def create_session(
    runtime: SessionRuntime,
    internal_user_id: str,
    legacy_user_id: str | None = None,
    provider: str | None = None,
    platform: str | None = None,
    request: Any | None = None,
    metadata: dict[str, Any] | None = None,
    *,
    access_ttl_seconds: int,
    refresh_ttl_seconds: int,
) -> dict[str, str]:
    runtime.validate_crypto()
    raw_session_token = runtime.generate_token()
    raw_refresh_token = runtime.generate_token()
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    expires_at = (now + timedelta(seconds=access_ttl_seconds)).isoformat()
    refresh_expires_at = (now + timedelta(seconds=refresh_ttl_seconds)).isoformat()
    session_id = uuid.uuid4().hex
    session_meta = dict(metadata) if metadata else {}
    if request is not None:
        session_meta.setdefault("device", runtime.parse_user_agent(request.headers.get("user-agent")))
    with runtime.connect() as conn:
        conn.execute(
            """
            INSERT INTO auth_sessions
                (id, internal_user_id, legacy_user_id, session_token_hash, refresh_token_hash,
                 provider, platform, ip_address, user_agent_hash, created_at, last_seen_at,
                 expires_at, refresh_expires_at, metadata_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                internal_user_id,
                legacy_user_id,
                runtime.hash_token(raw_session_token),
                runtime.hash_token(raw_refresh_token),
                provider,
                platform,
                runtime.get_client_ip(request),
                runtime.hash_user_agent(request),
                now_iso,
                now_iso,
                expires_at,
                refresh_expires_at,
                json.dumps(session_meta, ensure_ascii=False) if session_meta else None,
            ),
        )
        runtime.record_session_event(conn, session_id, internal_user_id, "created", request)
        conn.execute("UPDATE users SET last_seen_at = ? WHERE internal_user_id = ?", (now_iso, internal_user_id))
        runtime.ensure_public_user_code(conn, internal_user_id)
    return {
        "session_id": session_id,
        "session_token": raw_session_token,
        "refresh_token": raw_refresh_token,
        "expires_at": expires_at,
        "refresh_expires_at": refresh_expires_at,
    }


def resolve_session(
    runtime: SessionRuntime,
    token: str | None,
    request: Any,
    *,
    raise_on_failure: bool = True,
) -> dict[str, Any] | None:
    now_iso = datetime.now(timezone.utc).isoformat()

    def fail(
        event_type: str,
        status: int,
        message: str,
        *,
        severity: str = "warning",
        internal_user_id: str | None = None,
        session_id: str | None = None,
    ) -> None:
        with runtime.connect() as conn:
            runtime.record_security_event(
                conn,
                event_type,
                severity=severity,
                internal_user_id=internal_user_id,
                session_id=session_id,
                request=request,
            )
        if raise_on_failure:
            raise SessionAccessError(status, message)
        return None

    if not token:
        return fail("session_missing_token", 401, "Missing session token.")
    with runtime.connect() as conn:
        row = conn.execute(
            "SELECT * FROM auth_sessions WHERE session_token_hash = ?", (runtime.hash_token(token),)
        ).fetchone()
    if row is None:
        return fail("session_invalid", 401, "Invalid session.")
    if row["revoked_at"] is not None:
        return fail(
            "session_revoked",
            401,
            "Session revoked.",
            internal_user_id=row["internal_user_id"],
            session_id=row["id"],
        )
    if row["expires_at"] <= now_iso:
        return fail(
            "session_expired",
            401,
            "Session expired.",
            internal_user_id=row["internal_user_id"],
            session_id=row["id"],
        )
    with runtime.connect() as conn:
        banned = runtime.user_is_banned(conn, row["internal_user_id"], row["legacy_user_id"])
    if banned:
        return fail(
            "session_user_banned",
            403,
            "User is banned.",
            severity="critical",
            internal_user_id=row["internal_user_id"],
            session_id=row["id"],
        )
    with runtime.connect() as conn:
        conn.execute("UPDATE auth_sessions SET last_seen_at = ? WHERE id = ?", (now_iso, row["id"]))
    return {
        "session_id": row["id"],
        "internal_user_id": row["internal_user_id"],
        "legacy_user_id": row["legacy_user_id"],
        "provider": row["provider"],
        "platform": row["platform"],
        "created_at": row["created_at"],
        "last_seen_at": now_iso,
        "expires_at": row["expires_at"],
    }


def refresh_session(
    runtime: SessionRuntime,
    refresh_token: str,
    request: Any | None = None,
    *,
    app_env: str,
    access_ttl_seconds: int,
    refresh_ttl_seconds: int,
) -> dict[str, str]:
    runtime.validate_crypto()
    now_iso = datetime.now(timezone.utc).isoformat()

    def fail(
        event_type: str,
        status: int,
        message: str,
        *,
        severity: str = "warning",
        internal_user_id: str | None = None,
        session_id: str | None = None,
    ) -> None:
        with runtime.connect() as conn:
            runtime.record_security_event(
                conn,
                event_type,
                severity=severity,
                internal_user_id=internal_user_id,
                session_id=session_id,
                request=request,
            )
        raise SessionAccessError(status, message)

    with runtime.connect() as conn:
        row = conn.execute(
            "SELECT * FROM auth_sessions WHERE refresh_token_hash = ?",
            (runtime.hash_token(refresh_token),),
        ).fetchone()
    if row is None:
        fail("refresh_invalid", 401, "Invalid refresh token.")
    if row["revoked_at"] is not None:
        fail(
            "refresh_revoked",
            401,
            "Refresh token revoked.",
            internal_user_id=row["internal_user_id"],
            session_id=row["id"],
        )
    refresh_expires_at = row["refresh_expires_at"] if "refresh_expires_at" in row.keys() else None
    if refresh_expires_at is None:
        if app_env.lower() == "production":
            fail(
                "refresh_expired",
                401,
                "Refresh token expired.",
                internal_user_id=row["internal_user_id"],
                session_id=row["id"],
            )
        refresh_expires_at = row["expires_at"]
    if refresh_expires_at is None or refresh_expires_at <= now_iso:
        fail(
            "refresh_expired",
            401,
            "Refresh token expired.",
            internal_user_id=row["internal_user_id"],
            session_id=row["id"],
        )
    with runtime.connect() as conn:
        banned = runtime.user_is_banned(conn, row["internal_user_id"], row["legacy_user_id"])
    if banned:
        fail(
            "refresh_user_banned",
            403,
            "User is banned.",
            severity="critical",
            internal_user_id=row["internal_user_id"],
            session_id=row["id"],
        )
    with runtime.connect() as conn:
        conn.execute(
            "UPDATE auth_sessions SET revoked_at = ?, revoke_reason = 'rotated' WHERE id = ?",
            (now_iso, row["id"]),
        )
        runtime.record_session_event(conn, row["id"], row["internal_user_id"], "refreshed", request)
    return create_session(
        runtime,
        row["internal_user_id"],
        row["legacy_user_id"],
        row["provider"],
        row["platform"],
        request,
        access_ttl_seconds=access_ttl_seconds,
        refresh_ttl_seconds=refresh_ttl_seconds,
    )


def revoke_session(
    runtime: SessionRuntime,
    session_id: str,
    reason: str = "logout",
    request: Any | None = None,
    event_type: str | None = None,
) -> bool:
    now_iso = datetime.now(timezone.utc).isoformat()
    with runtime.connect() as conn:
        row = conn.execute(
            "SELECT internal_user_id, revoked_at FROM auth_sessions WHERE id = ?", (session_id,)
        ).fetchone()
        if row is None:
            return False
        if row["revoked_at"] is None:
            conn.execute(
                "UPDATE auth_sessions SET revoked_at = ?, revoke_reason = ? WHERE id = ?",
                (now_iso, reason, session_id),
            )
        runtime.record_session_event(
            conn,
            session_id,
            row["internal_user_id"],
            event_type or ("logout" if reason == "logout" else "revoked"),
            request,
        )
    return True
