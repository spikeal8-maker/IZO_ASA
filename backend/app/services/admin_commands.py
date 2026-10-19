"""Durable idempotency for synchronous, local admin mutations.

The caller owns the connection and commit/rollback context. No provider call,
await, nested connection or independent commit is permitted inside ``mutate``.
The command receipt, business effect and audit commit together. A process loss
before commit rolls all three back; a loss after commit is a stored replay.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import re
import sqlite3
from typing import Any, Callable
import uuid


KEY_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{11,119}\Z")


class AdminCommandError(ValueError):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


@dataclass(frozen=True)
class CommandContext:
    id: str
    now: datetime


@dataclass(frozen=True)
class CommandResult:
    response: dict[str, Any]
    replayed: bool


def normalize_reason(value: str | None) -> str:
    reason = (value or "").strip()
    if not reason:
        raise AdminCommandError(400, "Укажите причину.")
    if len(reason) > 500:
        raise AdminCommandError(400, "Причина не должна превышать 500 символов.")
    return reason


def validate_key(value: str | None) -> str:
    if not isinstance(value, str) or not KEY_PATTERN.fullmatch(value):
        raise AdminCommandError(400, "Укажите корректный ключ операции: от 12 до 120 символов.")
    return value


def execute_local_command(
    conn: sqlite3.Connection,
    *,
    key: str | None,
    actor_internal_user_id: str,
    target_internal_user_id: str,
    operation: str,
    payload: dict[str, Any],
    mutate: Callable[[CommandContext], dict[str, Any]],
) -> CommandResult:
    """Start a writer transaction before authorization, command or balance reads."""
    key = validate_key(key)
    if conn.in_transaction:
        raise RuntimeError("ADMIN_COMMAND_REQUIRES_OWN_TRANSACTION")
    encoded = json.dumps(
        {"actor": actor_internal_user_id, "target": target_internal_user_id,
         "operation": operation, "payload": payload},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
    )
    fingerprint = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    conn.execute("BEGIN IMMEDIATE")
    actor = conn.execute(
        "SELECT role, banned FROM users WHERE internal_user_id = ?",
        (actor_internal_user_id,),
    ).fetchone()
    if actor is None or actor["role"] != "admin" or actor["banned"]:
        raise AdminCommandError(403, "Недостаточно прав для выполнения операции.")
    previous = conn.execute(
        "SELECT actor_internal_user_id, target_internal_user_id, operation, "
        "request_sha256, response_json FROM admin_commands WHERE command_key = ?",
        (key,),
    ).fetchone()
    if previous is not None:
        if (previous["actor_internal_user_id"] != actor_internal_user_id
                or previous["target_internal_user_id"] != target_internal_user_id
                or previous["operation"] != operation
                or previous["request_sha256"] != fingerprint):
            raise AdminCommandError(409, "Ключ операции уже использован для другого действия.")
        response = json.loads(previous["response_json"])
        if not isinstance(response, dict):
            raise RuntimeError("ADMIN_COMMAND_RESULT_INVALID")
        return CommandResult(response, replayed=True)
    context = CommandContext(uuid.uuid4().hex, datetime.now(timezone.utc))
    response = mutate(context)
    if not isinstance(response, dict):
        raise RuntimeError("ADMIN_COMMAND_RESULT_INVALID")
    encoded_response = json.dumps(
        response, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
    )
    conn.execute(
        "INSERT INTO admin_commands "
        "(id, command_key, actor_internal_user_id, target_internal_user_id, "
        "operation, request_sha256, response_json, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (context.id, key, actor_internal_user_id, target_internal_user_id,
         operation, fingerprint, encoded_response, context.now.isoformat()),
    )
    return CommandResult(json.loads(encoded_response), replayed=False)
