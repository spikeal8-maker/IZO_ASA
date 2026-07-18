"""Atomic bot-login challenge cleanup and abuse controls."""

from __future__ import annotations

import sqlite3
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any


@dataclass(frozen=True)
class BotLoginRuntime:
    connect: Callable[[], sqlite3.Connection]
    get_client_ip: Callable[[Any], str | None]
    hash_user_agent: Callable[[Any], str | None]
    hash_token: Callable[[str], str]
    record_security_event: Callable[..., None]


@dataclass(frozen=True)
class BotLoginRateLimits:
    request_window_seconds: int
    max_requests_per_ip_window: int
    max_active_per_ip_provider: int
    max_global_pending: int
    retention_seconds: int


class BotLoginAccessError(RuntimeError):
    def __init__(self, reason: str, retry_after: int):
        super().__init__(reason)
        self.reason = reason
        self.retry_after = retry_after


def cleanup_bot_login_challenges(
    conn: sqlite3.Connection,
    *,
    now: str,
    retention_seconds: int,
) -> None:
    conn.execute(
        "UPDATE auth_login_challenges SET status = 'expired' "
        "WHERE status = 'pending' AND expires_at <= ?",
        (now,),
    )
    cutoff = (datetime.fromisoformat(now) - timedelta(seconds=retention_seconds)).isoformat()
    conn.execute(
        "DELETE FROM auth_login_challenges "
        "WHERE status IN ('expired', 'consumed', 'conflict') AND created_at < ?",
        (cutoff,),
    )


def pending_bot_login_challenges_count(
    runtime: BotLoginRuntime,
    provider: str,
    *,
    retention_seconds: int,
) -> int:
    now = datetime.now(timezone.utc).isoformat()
    with runtime.connect() as conn:
        cleanup_bot_login_challenges(conn, now=now, retention_seconds=retention_seconds)
        return conn.execute(
            "SELECT COUNT(*) AS c FROM auth_login_challenges "
            "WHERE provider = ? AND status = 'pending' AND expires_at > ?",
            (provider, now),
        ).fetchone()["c"]


def create_bot_login_challenge(
    runtime: BotLoginRuntime,
    limits: BotLoginRateLimits,
    provider: str,
    request: Any,
    *,
    token: str,
    nonce: str,
    ttl_seconds: int,
    internal_user_id: str | None = None,
) -> str:
    now_dt = datetime.now(timezone.utc)
    now = now_dt.isoformat()
    expires_at = (now_dt + timedelta(seconds=ttl_seconds)).isoformat()
    ip_address = runtime.get_client_ip(request)
    window_start = (now_dt - timedelta(seconds=limits.request_window_seconds)).isoformat()
    blocked_reason: str | None = None
    with runtime.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        cleanup_bot_login_challenges(conn, now=now, retention_seconds=limits.retention_seconds)
        recent_count = conn.execute(
            "SELECT COUNT(*) AS c FROM auth_login_challenges WHERE created_ip IS ? AND created_at >= ?",
            (ip_address, window_start),
        ).fetchone()["c"]
        active_count = conn.execute(
            "SELECT COUNT(*) AS c FROM auth_login_challenges "
            "WHERE created_ip IS ? AND provider = ? AND status = 'pending' AND expires_at > ?",
            (ip_address, provider, now),
        ).fetchone()["c"]
        global_pending = conn.execute(
            "SELECT COUNT(*) AS c FROM auth_login_challenges WHERE status = 'pending' AND expires_at > ?",
            (now,),
        ).fetchone()["c"]
        if recent_count >= limits.max_requests_per_ip_window:
            blocked_reason = "ip_window"
        elif active_count >= limits.max_active_per_ip_provider:
            blocked_reason = "active_ip_provider"
        elif global_pending >= limits.max_global_pending:
            blocked_reason = "global_pending"
        if blocked_reason:
            runtime.record_security_event(
                conn,
                "bot_login_rate_limited",
                request=request,
                details={"provider": provider, "reason": blocked_reason},
            )
        else:
            conn.execute(
                """
                INSERT INTO auth_login_challenges
                    (id, provider, token_hash, browser_nonce_hash, status, expires_at,
                     internal_user_id, created_at, created_ip, user_agent)
                VALUES (?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?)
                """,
                (
                    uuid.uuid4().hex, provider, runtime.hash_token(token), runtime.hash_token(nonce),
                    expires_at, internal_user_id, now, ip_address, runtime.hash_user_agent(request),
                ),
            )
    if blocked_reason:
        raise BotLoginAccessError(blocked_reason, limits.request_window_seconds)
    return expires_at
