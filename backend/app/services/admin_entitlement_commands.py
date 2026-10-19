"""Local token and tariff commands behind the trusted compatibility routes."""
from __future__ import annotations

from contextlib import closing
import json
from typing import Any

from fastapi import HTTPException

from .admin_commands import (
    AdminCommandError, CommandContext, execute_local_command, normalize_reason,
)


def adjust_tokens(
    internal_user_id: str, req, request, *, admin, db, load_target,
    audit, event_log, max_abs: int,
) -> dict[str, Any]:
    try:
        reason = normalize_reason(req.reason)
        if req.delta == 0:
            raise AdminCommandError(400, "Изменение баланса не может быть нулевым.")
        if abs(req.delta) > max_abs:
            raise AdminCommandError(400, "Слишком большое изменение баланса.")
        with closing(db()) as conn, conn:
            def mutate(command: CommandContext) -> dict[str, Any]:
                target = load_target(conn, internal_user_id)
                old_balance = int(target["token_balance"] or 0)
                new_balance = old_balance + req.delta
                if new_balance < 0:
                    raise AdminCommandError(400, "Баланс не может стать отрицательным.")
                conn.execute(
                    "UPDATE users SET token_balance = ? WHERE internal_user_id = ?",
                    (new_balance, internal_user_id),
                )
                conn.execute(
                    "INSERT INTO token_ledger "
                    "(id, user_id, delta, reason, meta_json, created_at) "
                    "VALUES (?, ?, ?, 'admin_adjust', ?, ?)",
                    (command.id, target["id"], req.delta, json.dumps({
                        "actor_internal_user_id": admin["internal_user_id"],
                        "reason": reason, "admin_command_id": command.id,
                    }, ensure_ascii=False), command.now.isoformat()),
                )
                audit(
                    conn, "admin_adjust_tokens", actor_internal_user_id=admin["internal_user_id"],
                    target_internal_user_id=internal_user_id, entity_id=target["id"],
                    before={"token_balance": old_balance},
                    after={"token_balance": new_balance, "delta": req.delta,
                           "reason": reason, "admin_command_id": command.id}, request=request,
                )
                return {"ok": True, "internal_user_id": internal_user_id,
                        "old_balance": old_balance, "new_balance": new_balance, "delta": req.delta}

            result = execute_local_command(
                conn, key=req.idempotency_key, actor_internal_user_id=admin["internal_user_id"],
                target_internal_user_id=internal_user_id, operation="adjust-tokens-v2",
                payload={"delta": req.delta, "reason": reason}, mutate=mutate,
            )
    except AdminCommandError as exc:
        raise HTTPException(exc.status_code, exc.detail) from None
    if not result.replayed:
        try:
            event_log(
                "admin_tokens_adjusted", internal_user_id=internal_user_id, platform="web",
                properties={"delta": req.delta, "new_balance": result.response["new_balance"]},
            )
        except Exception:
            pass  # Non-authoritative analytics cannot change the committed command.
    return result.response


def activate_plan(
    internal_user_id: str, req, request, *, admin, db, load_target, activate_tariff, audit,
) -> dict[str, Any]:
    try:
        reason = normalize_reason(req.reason)
        with closing(db()) as conn, conn:
            def mutate(command: CommandContext) -> dict[str, Any]:
                target = load_target(conn, internal_user_id)
                activation = activate_tariff(
                    conn, internal_user_id=internal_user_id, plan=req.plan, now=command.now,
                    source="admin", source_id=command.id, duration_days=req.duration_days,
                )
                audit(
                    conn, "admin_change_plan", actor_internal_user_id=admin["internal_user_id"],
                    target_internal_user_id=internal_user_id, entity_id=target["id"],
                    before={"plan": target["plan"]},
                    after={"plan": req.plan, "duration_days": req.duration_days,
                           "reason": reason, "admin_command_id": command.id}, request=request,
                )
                return {"ok": True, "internal_user_id": internal_user_id,
                        "plan": req.plan, "activation": activation}

            result = execute_local_command(
                conn, key=req.idempotency_key, actor_internal_user_id=admin["internal_user_id"],
                target_internal_user_id=internal_user_id, operation="activate-plan-v2",
                payload={"plan": req.plan, "duration_days": req.duration_days, "reason": reason},
                mutate=mutate,
            )
    except AdminCommandError as exc:
        raise HTTPException(exc.status_code, exc.detail) from None
    return result.response
