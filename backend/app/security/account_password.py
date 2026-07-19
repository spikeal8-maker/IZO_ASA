"""Password-management route kept outside the application composition root."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel


class PasswordChangeRequest(BaseModel):
    current_password: str = ""
    new_password: str = ""
    new_password_repeat: str = ""


@dataclass(frozen=True)
class PasswordChangeRuntime:
    open_db: Callable[[], Any]
    require_user: Callable[[Request], dict[str, Any]]
    validate_password: Callable[[str], list[str]]
    verify_password: Callable[[str, str], bool]
    hash_password: Callable[[str], str]
    record_security_event: Callable[..., Any]
    revoke_session: Callable[..., bool]
    record_event: Callable[..., Any]


def password_is_configured(conn: Any, internal_user_id: str) -> bool:
    return bool(
        conn.execute(
            "SELECT 1 FROM auth_passwords WHERE internal_user_id = ? AND disabled_at IS NULL",
            (internal_user_id,),
        ).fetchone()
    )


def install_password_change_route(app: FastAPI, runtime: PasswordChangeRuntime) -> None:
    @app.post("/api/auth/password/change-v2")
    async def auth_password_change_v2(req: PasswordChangeRequest, request: Request) -> dict[str, Any]:
        user = runtime.require_user(request)
        internal_user_id = user["internal_user_id"]
        current_session_id = user["session_id"]
        if runtime.validate_password(req.new_password):
            raise HTTPException(400, "Новый пароль должен быть от 8 до 128 символов.")
        if req.new_password != req.new_password_repeat:
            raise HTTPException(400, "Новые пароли не совпадают.")
        if not req.current_password:
            raise HTTPException(400, "Введите текущий пароль.")

        with runtime.open_db() as conn:
            password_row = conn.execute(
                "SELECT id, password_hash FROM auth_passwords WHERE internal_user_id = ? AND disabled_at IS NULL",
                (internal_user_id,),
            ).fetchone()
        if password_row is None or not runtime.verify_password(req.current_password, password_row["password_hash"]):
            with runtime.open_db() as conn:
                runtime.record_security_event(
                    conn,
                    "password_change_failed",
                    severity="warning",
                    internal_user_id=internal_user_id,
                    request=request,
                )
            raise HTTPException(400, "Текущий пароль указан неверно.")
        if runtime.verify_password(req.new_password, password_row["password_hash"]):
            raise HTTPException(400, "Новый пароль должен отличаться от текущего.")

        now = datetime.now(timezone.utc).isoformat()
        with runtime.open_db() as conn:
            conn.execute(
                "UPDATE auth_passwords SET password_hash = ?, algorithm = 'argon2id', updated_at = ?, password_updated_at = ? WHERE id = ?",
                (runtime.hash_password(req.new_password), now, now, password_row["id"]),
            )
            other_sessions = conn.execute(
                "SELECT id FROM auth_sessions WHERE internal_user_id = ? AND id != ? AND revoked_at IS NULL",
                (internal_user_id, current_session_id),
            ).fetchall()
            runtime.record_security_event(conn, "password_changed", internal_user_id=internal_user_id, request=request)

        revoked_sessions = sum(
            1
            for session_row in other_sessions
            if runtime.revoke_session(
                session_row["id"], reason="password_changed", request=request, event_type="revoked"
            )
        )
        try:
            runtime.record_event(
                "password_changed",
                internal_user_id=internal_user_id,
                legacy_user_id=user.get("legacy_user_id"),
                session_id=current_session_id,
                platform=user.get("platform"),
                request=request,
                properties={"revoked_sessions": revoked_sessions},
            )
        except Exception as exc:  # pragma: no cover - defensive logging only
            print(f"password-change: event log error: {type(exc).__name__}")
        return {"ok": True, "revoked_sessions": revoked_sessions}
