"""Security, session, login and product events without application globals."""

from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class EventRuntime:
    connect: Callable[[], sqlite3.Connection]
    get_client_ip: Callable[[Any | None], str | None]
    hash_user_agent: Callable[[Any | None], str | None]


def _json_or_none(value: dict[str, Any] | None) -> str | None:
    return json.dumps(value, ensure_ascii=False) if value else None


def record_session_event(
    runtime: EventRuntime,
    conn: sqlite3.Connection,
    session_id: str,
    internal_user_id: str,
    event_type: str,
    request: Any | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO session_events
            (id, session_id, internal_user_id, event_type, ip_address,
             user_agent_hash, metadata_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            uuid.uuid4().hex,
            session_id,
            internal_user_id,
            event_type,
            runtime.get_client_ip(request),
            runtime.hash_user_agent(request),
            _json_or_none(metadata),
            datetime.now(timezone.utc).isoformat(),
        ),
    )


def record_security_event(
    runtime: EventRuntime,
    conn: sqlite3.Connection,
    event_type: str,
    severity: str = "warning",
    internal_user_id: str | None = None,
    session_id: str | None = None,
    request: Any | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """Record sanitized security evidence; callers must never pass raw secrets."""
    conn.execute(
        """
        INSERT INTO security_events
            (id, internal_user_id, session_id, severity, event_type, ip_address,
             user_agent_hash, details_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            uuid.uuid4().hex,
            internal_user_id,
            session_id,
            severity,
            event_type,
            runtime.get_client_ip(request),
            runtime.hash_user_agent(request),
            _json_or_none(details),
            datetime.now(timezone.utc).isoformat(),
        ),
    )


def record_product_event(
    runtime: EventRuntime,
    event_name: str,
    internal_user_id: str | None = None,
    legacy_user_id: str | None = None,
    anonymous_id: str | None = None,
    installation_id: str | None = None,
    session_id: str | None = None,
    platform: str | None = None,
    device_type: str | None = None,
    request: Any | None = None,
    properties: dict[str, Any] | None = None,
) -> None:
    """Write analytics in its own transaction so callers cannot be rolled back."""
    with runtime.connect() as conn:
        conn.execute(
            """
            INSERT INTO event_logs
                (id, internal_user_id, legacy_user_id, anonymous_id, installation_id,
                 session_id, event_name, platform, device_type, ip_address,
                 user_agent_hash, properties_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                uuid.uuid4().hex,
                internal_user_id,
                legacy_user_id,
                anonymous_id,
                installation_id,
                session_id,
                event_name,
                platform,
                device_type,
                runtime.get_client_ip(request),
                runtime.hash_user_agent(request),
                _json_or_none(properties),
                datetime.now(timezone.utc).isoformat(),
            ),
        )


def record_login_attempt(
    runtime: EventRuntime,
    conn: sqlite3.Connection,
    provider: str,
    success: bool,
    identifier: str | None = None,
    internal_user_id: str | None = None,
    failure_reason: str | None = None,
    platform: str | None = None,
    request: Any | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO auth_login_attempts
            (id, internal_user_id, provider, identifier, success, failure_reason,
             ip_address, user_agent_hash, platform, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            uuid.uuid4().hex,
            internal_user_id,
            provider,
            identifier,
            1 if success else 0,
            failure_reason,
            runtime.get_client_ip(request),
            runtime.hash_user_agent(request),
            platform,
            datetime.now(timezone.utc).isoformat(),
        ),
    )
