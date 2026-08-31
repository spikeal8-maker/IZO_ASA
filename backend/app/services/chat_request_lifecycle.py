"""Durable, per-user idempotency and compensation for phone-chat requests."""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from . import chat_billing, phone_chat_history


CONFLICT_DETAIL = "requestId уже использован для другого запроса."
PROCESSING_DETAIL = "Этот запрос уже выполняется. Повторите через несколько секунд."
STALE_DETAIL = "Предыдущая попытка была прервана. Создайте новый запрос."
LEGACY_DETAIL = "Этот requestId уже использовался ранее. Создайте новый запрос."


def phone_chat_request_fingerprint(
    *,
    messages: list[Any],
    route: str,
    model_id: str | None,
    images: list[str],
    thread_id: str | None,
) -> str:
    """Hash only stable client input; never persist raw images in the ledger."""

    normalized_messages = [
        {
            "role": str(getattr(item, "role", None) or item.get("role") or ""),
            "content": str(getattr(item, "content", None) or item.get("content") or ""),
        }
        for item in messages
    ]
    payload = {
        "messages": normalized_messages,
        "route": str(route),
        "modelId": str(model_id or ""),
        "images": [
            {"sha256": hashlib.sha256(value.encode("utf-8")).hexdigest(), "length": len(value)}
            for value in images
        ],
        "threadId": str(thread_id or ""),
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


@dataclass(frozen=True)
class ChatRequestLifecycle:
    """Own the request claim, charge, settlement, history, outcome and refund."""

    connect: Callable[[], sqlite3.Connection]
    get_tariffs: Callable[[sqlite3.Connection], dict[str, Any]]
    reconcile_tariff: Callable[..., Any]
    lease_seconds: int = 300
    clock: Callable[[], datetime] = _utc_now

    def _failed_outcome(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "state": "failed",
            "status": int(row["error_status"] or 503),
            "detail": str(row["error_detail"] or STALE_DETAIL),
        }

    def _existing_outcome(
        self,
        conn: sqlite3.Connection,
        row: sqlite3.Row,
        *,
        fingerprint: str,
        now: datetime,
    ) -> dict[str, Any]:
        if str(row["request_fingerprint"]) != fingerprint:
            return {"state": "conflict", "status": 409, "detail": CONFLICT_DETAIL}
        state = str(row["state"])
        if state == "succeeded":
            response = json.loads(str(row["response_json"] or "{}"))
            if not isinstance(response, dict) or not response.get("ok"):
                raise RuntimeError("PHONE_CHAT_RESPONSE_LEDGER_INVALID")
            return {"state": "succeeded", "response": response, "replay": True}
        if state == "failed":
            return self._failed_outcome(row)
        lease_expires_at = _parse_utc(str(row["lease_expires_at"]))
        if lease_expires_at > now:
            retry_after = max(1, math.ceil((lease_expires_at - now).total_seconds()))
            return {
                "state": "processing",
                "status": 409,
                "detail": PROCESSING_DETAIL,
                "retry_after": retry_after,
            }
        ledger_id = str(row["charged_ledger_id"] or "")
        if not ledger_id:
            raise RuntimeError("PHONE_CHAT_PROCESSING_LEDGER_MISSING")
        chat_billing.refund_chat_tokens(
            conn,
            user_id=str(row["user_id"]),
            ledger_id=ledger_id,
            reason="stale_request_recovery",
        )
        now_iso = now.isoformat()
        conn.execute(
            "UPDATE phone_chat_requests SET state='failed',error_status=503,error_detail=?,"
            "updated_at=?,finished_at=? WHERE user_id=? AND request_id=? AND state='processing'",
            (STALE_DETAIL, now_iso, now_iso, row["user_id"], row["request_id"]),
        )
        return {"state": "failed", "status": 503, "detail": STALE_DETAIL, "recovered": True}

    def inspect(self, *, user_id: str, request_id: str, fingerprint: str) -> dict[str, Any]:
        """Return a replay/conflict/in-flight outcome before dynamic routing work."""

        now = self.clock()
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM phone_chat_requests WHERE user_id=? AND request_id=?",
                (user_id, request_id),
            ).fetchone()
            if row is None:
                conn.commit()
                return {"state": "new"}
            outcome = self._existing_outcome(conn, row, fingerprint=fingerprint, now=now)
            conn.commit()
            return outcome

    def begin(
        self,
        *,
        user_id: str,
        request_id: str,
        fingerprint: str,
        token_cost: float,
        provider: str,
        model: str,
    ) -> dict[str, Any]:
        """Atomically claim a new request and reserve its product tokens."""

        now = self.clock()
        now_iso = now.isoformat()
        lease_expires_at = (now + timedelta(seconds=max(210, self.lease_seconds))).isoformat()
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT * FROM phone_chat_requests WHERE user_id=? AND request_id=?",
                (user_id, request_id),
            ).fetchone()
            if existing is not None:
                if (
                    str(existing["state"]) == "processing"
                    and str(existing["request_fingerprint"]) == fingerprint
                    and (str(existing["provider"]) != provider or str(existing["model"]) != model)
                ):
                    conn.commit()
                    return {"state": "conflict", "status": 409, "detail": CONFLICT_DETAIL}
                outcome = self._existing_outcome(conn, existing, fingerprint=fingerprint, now=now)
                conn.commit()
                return outcome
            conn.execute(
                "INSERT INTO phone_chat_requests "
                "(user_id,request_id,request_fingerprint,state,provider,model,created_at,updated_at,lease_expires_at) "
                "VALUES (?,?,?,'processing',?,?,?,?,?)",
                (user_id, request_id, fingerprint, provider, model, now_iso, now_iso, lease_expires_at),
            )
            user = conn.execute(
                "SELECT internal_user_id,plan FROM users WHERE id=?",
                (user_id,),
            ).fetchone()
            if user is None:
                raise RuntimeError("PHONE_CHAT_USER_MISSING")
            if user["internal_user_id"]:
                self.reconcile_tariff(conn, str(user["internal_user_id"]), now=now)
                user = conn.execute(
                    "SELECT internal_user_id,plan FROM users WHERE id=?",
                    (user_id,),
                ).fetchone()
            tariffs = self.get_tariffs(conn)
            plan = str(user["plan"] or "mini").lower()
            tariff = tariffs.get(plan, tariffs["mini"])
            charge = chat_billing.charge_chat_tokens(
                conn,
                user_id=user_id,
                token_cost=token_cost,
                request_id=request_id,
                provider=provider,
                model=model,
                daily_limit=int(tariff["daily_tokens"]),
            )
            if charge.get("duplicate"):
                conn.execute(
                    "UPDATE phone_chat_requests SET state='failed',charged_ledger_id=?,charge_json=?,"
                    "error_status=409,error_detail=?,updated_at=?,finished_at=? WHERE user_id=? AND request_id=?",
                    (
                        charge["ledger_id"],
                        json.dumps(charge, ensure_ascii=False),
                        LEGACY_DETAIL,
                        now_iso,
                        now_iso,
                        user_id,
                        request_id,
                    ),
                )
                conn.commit()
                return {"state": "failed", "status": 409, "detail": LEGACY_DETAIL}
            conn.execute(
                "UPDATE phone_chat_requests SET charged_ledger_id=?,charge_json=?,updated_at=? "
                "WHERE user_id=? AND request_id=? AND state='processing'",
                (charge["ledger_id"], json.dumps(charge, ensure_ascii=False), now_iso, user_id, request_id),
            )
            conn.commit()
            return {"state": "started", "charge": charge}

    def complete(
        self,
        *,
        user_id: str,
        request_id: str,
        fingerprint: str,
        reply: str,
        provider: str,
        public_model_id: str,
        usage: dict[str, Any],
        cost_usd: float,
        token_cost: float,
        token_kind: str,
        reservation_quote: dict[str, Any] | None,
        tool_runs: list[dict[str, Any]],
        thread_id: str | None,
        user_content: str,
    ) -> dict[str, Any]:
        """Atomically settle billing, append history and persist the replay response."""

        now = self.clock()
        now_iso = now.isoformat()
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM phone_chat_requests WHERE user_id=? AND request_id=?",
                (user_id, request_id),
            ).fetchone()
            if row is None:
                raise RuntimeError("PHONE_CHAT_REQUEST_LEDGER_MISSING")
            if str(row["request_fingerprint"]) != fingerprint:
                raise RuntimeError("PHONE_CHAT_REQUEST_FINGERPRINT_MISMATCH")
            if str(row["state"]) == "succeeded":
                outcome = self._existing_outcome(conn, row, fingerprint=fingerprint, now=now)
                conn.commit()
                return outcome
            if str(row["state"]) != "processing":
                outcome = self._failed_outcome(row)
                conn.commit()
                return outcome
            charge = json.loads(str(row["charge_json"] or "{}"))
            ledger_id = str(row["charged_ledger_id"] or "")
            if not ledger_id or not isinstance(charge, dict):
                raise RuntimeError("PHONE_CHAT_CHARGE_LEDGER_INVALID")
            settlement: dict[str, Any] | None = None
            settled_token_cost = float(token_cost)
            if reservation_quote is not None:
                settlement = chat_billing.settle_chat_tokens(
                    conn,
                    user_id=user_id,
                    ledger_id=ledger_id,
                    quote=reservation_quote,
                    actual_cost_usd=cost_usd if cost_usd > 0 else None,
                )
                settled_token_cost = float(settlement.get("settled_tokens", token_cost))
                charge["new_balance"] = settlement.get("new_balance", charge.get("new_balance"))
            message_ids: dict[str, str] = {}
            if thread_id:
                message_ids = phone_chat_history.add_exchange(
                    conn,
                    user_id,
                    thread_id,
                    user_content=user_content,
                    assistant_content=reply,
                    provider=provider,
                    model=public_model_id,
                    tools=tool_runs,
                    charged_tokens=settled_token_cost,
                    token_kind=token_kind,
                )
                if len(phone_chat_history.list_messages(conn, user_id, thread_id, limit=3)) <= 2:
                    phone_chat_history.update_thread(
                        conn,
                        user_id,
                        thread_id,
                        {"title": user_content.strip()[:42], "chatModelId": public_model_id},
                    )
            response = {
                "ok": True,
                "reply": reply,
                "model": public_model_id,
                "provider": provider,
                "usage": usage,
                "costUsd": cost_usd,
                "modelId": public_model_id,
                "chargedTokens": settled_token_cost,
                "tokenKind": token_kind,
                "tokenBalance": charge.get("new_balance"),
                "dailyTokensUsed": charge.get("daily_tokens_used_after"),
                "dailyTokensLimit": charge.get("daily_tokens_limit"),
                "reservedTokens": float(reservation_quote["reservedTokens"]) if reservation_quote is not None else settled_token_cost,
                "billingStatus": settlement.get("status") if settlement is not None else "fixed",
                "tools": tool_runs,
                "messageId": message_ids.get("assistantMessageId"),
            }
            cursor = conn.execute(
                "UPDATE phone_chat_requests SET state='succeeded',response_json=?,updated_at=?,finished_at=? "
                "WHERE user_id=? AND request_id=? AND state='processing'",
                (json.dumps(response, ensure_ascii=False), now_iso, now_iso, user_id, request_id),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("PHONE_CHAT_REQUEST_COMPLETION_RACE")
            conn.commit()
            return {
                "state": "succeeded",
                "response": response,
                "settlement": settlement,
                "replay": False,
            }

    def fail(
        self,
        *,
        user_id: str,
        request_id: str,
        fingerprint: str,
        status: int,
        detail: str,
        error_code: str,
    ) -> dict[str, Any]:
        """Atomically refund an unfinished charge and persist a safe failure."""

        now = self.clock()
        now_iso = now.isoformat()
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM phone_chat_requests WHERE user_id=? AND request_id=?",
                (user_id, request_id),
            ).fetchone()
            if row is None:
                raise RuntimeError("PHONE_CHAT_REQUEST_LEDGER_MISSING")
            if str(row["request_fingerprint"]) != fingerprint:
                raise RuntimeError("PHONE_CHAT_REQUEST_FINGERPRINT_MISMATCH")
            if str(row["state"]) == "succeeded":
                outcome = self._existing_outcome(conn, row, fingerprint=fingerprint, now=now)
                conn.commit()
                return outcome
            if str(row["state"]) == "failed":
                outcome = self._failed_outcome(row)
                conn.commit()
                return outcome
            ledger_id = str(row["charged_ledger_id"] or "")
            if not ledger_id:
                raise RuntimeError("PHONE_CHAT_PROCESSING_LEDGER_MISSING")
            chat_billing.refund_chat_tokens(
                conn,
                user_id=user_id,
                ledger_id=ledger_id,
                reason=error_code[:80],
            )
            safe_detail = str(detail).strip()[:240] or "Чат временно недоступен."
            conn.execute(
                "UPDATE phone_chat_requests SET state='failed',error_status=?,error_detail=?,"
                "updated_at=?,finished_at=? WHERE user_id=? AND request_id=? AND state='processing'",
                (max(400, min(599, int(status))), safe_detail, now_iso, now_iso, user_id, request_id),
            )
            conn.commit()
            return {"state": "failed", "status": status, "detail": safe_detail, "refunded": True}
