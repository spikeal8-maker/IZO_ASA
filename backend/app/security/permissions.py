"""Trusted-user and admin authorization independent from FastAPI globals."""

from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PermissionRuntime:
    connect: Callable[[], sqlite3.Connection]
    resolve_session: Callable[[Any], dict[str, Any]]
    record_security_event: Callable[..., None]


class PermissionAccessError(RuntimeError):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def _user_row(runtime: PermissionRuntime, internal_user_id: str, legacy_user_id: str | None, column: str):
    if column not in {"id", "role"}:
        raise ValueError("unsupported_user_column")
    with runtime.connect() as conn:
        row = conn.execute(
            f"SELECT {column} FROM users WHERE internal_user_id = ?", (internal_user_id,)
        ).fetchone()
        if row is None and legacy_user_id:
            row = conn.execute(f"SELECT {column} FROM users WHERE id = ?", (legacy_user_id,)).fetchone()
    return row


def resolve_trusted_identity(runtime: PermissionRuntime, request: Any) -> dict[str, Any]:
    session = runtime.resolve_session(request)
    internal_user_id = session["internal_user_id"]
    legacy_user_id = session["legacy_user_id"]
    if _user_row(runtime, internal_user_id, legacy_user_id, "id") is None:
        with runtime.connect() as conn:
            runtime.record_security_event(
                conn,
                "trusted_user_missing",
                severity="critical",
                internal_user_id=internal_user_id,
                session_id=session["session_id"],
                request=request,
            )
        raise PermissionAccessError(403, "User not found.")

    header_user = request.headers.get("x-onenode-user")
    if header_user and header_user != legacy_user_id and header_user != "demo_user":
        with runtime.connect() as conn:
            runtime.record_security_event(
                conn,
                "legacy_identity_spoof_attempt",
                internal_user_id=internal_user_id,
                session_id=session["session_id"],
                request=request,
                details={
                    "trusted_legacy_user_id": legacy_user_id,
                    "spoofed_header_hash": hashlib.sha256(header_user.encode()).hexdigest(),
                },
            )

    return {
        "internal_user_id": internal_user_id,
        "legacy_user_id": legacy_user_id,
        "session_id": session["session_id"],
        "provider": session["provider"],
        "platform": session["platform"],
    }


def require_admin(runtime: PermissionRuntime, request: Any) -> dict[str, Any]:
    user = resolve_trusted_identity(runtime, request)
    row = _user_row(runtime, user["internal_user_id"], user["legacy_user_id"], "role")
    if not row or row["role"] != "admin":
        with runtime.connect() as conn:
            runtime.record_security_event(
                conn,
                "trusted_admin_denied",
                internal_user_id=user["internal_user_id"],
                session_id=user["session_id"],
                request=request,
            )
        raise PermissionAccessError(403, "Admin access required")
    return user


def user_is_admin(runtime: PermissionRuntime, user: dict[str, Any]) -> bool:
    row = _user_row(runtime, user["internal_user_id"], user.get("legacy_user_id"), "role")
    return bool(row and row["role"] == "admin")
