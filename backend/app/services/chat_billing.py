"""Atomic product-token billing for user chat answers."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException


DEFAULT_CHAT_CONFIG: dict[str, Any] = {
    "enabled": True,
    "localEnabled": True,
    "localModel": "gemma4:12b",
    "localLabel": "ИЗО Чат",
    "localTokenCost": 0,
    "defaultModel": "local:izo-chat",
    "enabledApiModels": ["deepseek/deepseek-v4-flash"],
    "apiTokenCosts": {"deepseek/deepseek-v4-flash": 0.1},
    "apiTierAccess": {},
    "contextChars": 60000,
    "localNumCtx": 16384,
    "localTimeoutSeconds": 60,
    "apiTimeoutSeconds": 60,
}


def normalize_chat_config(value: Any) -> dict[str, Any]:
    stored = value if isinstance(value, dict) else {}
    source = {**DEFAULT_CHAT_CONFIG, **stored}
    bounded = lambda raw, default, low, high: max(low, min(high, int(raw if str(raw).lstrip("+-").isdigit() else default)))
    enabled_api = list(dict.fromkeys(str(item).strip() for item in source.get("enabledApiModels", []) if str(item).strip()))[:100]
    raw_costs = source.get("apiTokenCosts") if isinstance(source.get("apiTokenCosts"), dict) else {}
    raw_access = stored.get("apiTierAccess") if isinstance(stored.get("apiTierAccess"), dict) else None
    def bounded_cost(raw: Any, default: float = 0.1) -> float:
        try:
            value = float(raw)
        except (TypeError, ValueError):
            value = default
        return round(max(0.01, min(1000.0, value)), 3)
    tier_access = {
        tier: [model_id for model_id in enabled_api if raw_access is None or model_id in {
            str(item).strip() for item in raw_access.get(tier, []) if str(item).strip()
        }]
        for tier in ("mini", "plus", "pro", "business")
    }
    source.update({
        "enabled": bool(source.get("enabled", True)),
        "localEnabled": bool(source.get("localEnabled", True)),
        "localModel": str(source.get("localModel") or "gemma4:12b").strip(),
        "localLabel": str(source.get("localLabel") or "ИЗО Чат").strip()[:60] or "ИЗО Чат",
        # The local base assistant is part of the product and never consumes
        # either the daily allowance or the purchased balance.
        "localTokenCost": 0,
        "enabledApiModels": enabled_api,
        "apiTokenCosts": {model_id: bounded_cost(raw_costs.get(model_id)) for model_id in enabled_api},
        "apiTierAccess": tier_access,
        "contextChars": bounded(source.get("contextChars"), 60000, 4000, 240000),
        "localNumCtx": bounded(source.get("localNumCtx"), 16384, 4096, 32768),
        "localTimeoutSeconds": bounded(source.get("localTimeoutSeconds"), 60, 10, 180),
        "apiTimeoutSeconds": bounded(source.get("apiTimeoutSeconds"), 60, 10, 90),
    })
    allowed = (["local:izo-chat"] if source["localEnabled"] else []) + enabled_api
    source["defaultModel"] = source["defaultModel"] if source.get("defaultModel") in allowed else (allowed[0] if allowed else "local:izo-chat")
    return source


def charge_chat_tokens(
    conn: sqlite3.Connection,
    *,
    user_id: str,
    token_cost: float,
    request_id: str,
    provider: str,
    model: str,
    daily_limit: int,
) -> dict[str, Any]:
    """Reserve chat credits before provider work.

    Local chat consumes the daily allowance first, matching local image
    generation. OpenRouter chat consumes the main balance only.
    """

    cost = 0.0 if provider == "local" else round(max(0.01, min(1000.0, float(token_cost))), 3)
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    today = now.strftime("%Y-%m-%d")
    row = conn.execute(
        "SELECT id, token_balance, daily_tokens_used, last_daily_reset FROM users WHERE id=?",
        (user_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(404, "Пользователь не найден.")

    duplicate = conn.execute(
        "SELECT id, meta_json FROM token_ledger WHERE reason IN ('free_chat','chat') AND meta_json LIKE ? ORDER BY created_at DESC LIMIT 1",
        (f'%"request_id": "{request_id}"%',),
    ).fetchone()
    if duplicate is not None:
        meta = json.loads(duplicate["meta_json"] or "{}")
        return {"ledger_id": duplicate["id"], **meta, "duplicate": True}

    old_balance = int(row["token_balance"] or 0)
    daily_used_before = int(row["daily_tokens_used"] or 0) if row["last_daily_reset"] == today else 0
    daily_part = 0
    conn.execute(
        "CREATE TABLE IF NOT EXISTS chat_billing_meters ("
        "user_id TEXT PRIMARY KEY, accrued_millitokens INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL)"
    )
    meter_row = conn.execute(
        "SELECT accrued_millitokens FROM chat_billing_meters WHERE user_id=?", (user_id,)
    ).fetchone()
    meter_before = int(meter_row["accrued_millitokens"] or 0) if meter_row is not None else 0
    cost_milli = int(round(cost * 1000)) if provider != "local" else 0
    meter_after = meter_before + cost_milli
    balance_part = meter_after // 1000 - meter_before // 1000
    if old_balance < balance_part:
        raise HTTPException(402, "Недостаточно токенов для ответа этой модели.")

    daily_used_after = daily_used_before
    new_balance = old_balance - balance_part
    ledger_id = uuid.uuid4().hex
    meta = {
        "request_id": request_id,
        "mode": "phone_chat",
        "provider": provider,
        "model": model,
        "token_cost": cost,
        "daily_part": daily_part,
        "balance_part": balance_part,
        "daily_tokens_used_before": daily_used_before,
        "daily_tokens_used_after": daily_used_after,
        "daily_tokens_limit": int(daily_limit),
        "new_balance": new_balance,
        "cost_millitokens": cost_milli,
        "meter_before": meter_before,
        "meter_after": meter_after,
    }
    conn.execute(
        "UPDATE users SET token_balance=?, daily_tokens_used=?, last_daily_reset=?, tokens_used=tokens_used+?, last_seen_at=? WHERE id=?",
        (new_balance, daily_used_after, today, balance_part, now_iso, user_id),
    )
    conn.execute(
        "INSERT INTO chat_billing_meters (user_id,accrued_millitokens,updated_at) VALUES (?,?,?) "
        "ON CONFLICT(user_id) DO UPDATE SET accrued_millitokens=excluded.accrued_millitokens,updated_at=excluded.updated_at",
        (user_id, meter_after, now_iso),
    )
    conn.execute(
        "INSERT INTO token_ledger (id,user_id,delta,reason,meta_json,created_at) VALUES (?,?,?,?,?,?)",
        (
            ledger_id,
            user_id,
            -balance_part,
            "free_chat" if provider == "local" else "chat",
            json.dumps(meta, ensure_ascii=False),
            now_iso,
        ),
    )
    return {"ledger_id": ledger_id, **meta, "duplicate": False}


def refund_chat_tokens(
    conn: sqlite3.Connection,
    *,
    user_id: str,
    ledger_id: str,
    reason: str,
) -> bool:
    """Idempotently return a reserved chat charge after provider failure."""

    charge = conn.execute(
        "SELECT id, meta_json FROM token_ledger WHERE id=? AND user_id=? AND reason IN ('free_chat','chat')",
        (ledger_id, user_id),
    ).fetchone()
    if charge is None:
        return False
    duplicate = conn.execute(
        "SELECT 1 FROM token_ledger WHERE reason='chat_refund' AND meta_json LIKE ? LIMIT 1",
        (f'%"charged_ledger_id": "{ledger_id}"%',),
    ).fetchone()
    if duplicate is not None:
        return False
    meta = json.loads(charge["meta_json"] or "{}")
    daily_part = 0
    balance_part = max(0, int(meta.get("balance_part") or 0))
    token_cost = max(0.0, float(meta.get("token_cost") or 0))
    cost_milli = max(0, int(meta.get("cost_millitokens") or round(token_cost * 1000)))
    row = conn.execute(
        "SELECT daily_tokens_used,last_daily_reset FROM users WHERE id=?",
        (user_id,),
    ).fetchone()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    returned_daily = 0
    conn.execute(
        "CREATE TABLE IF NOT EXISTS chat_billing_meters ("
        "user_id TEXT PRIMARY KEY, accrued_millitokens INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL)"
    )
    meter_row = conn.execute("SELECT accrued_millitokens FROM chat_billing_meters WHERE user_id=?", (user_id,)).fetchone()
    meter_before = int(meter_row["accrued_millitokens"] or 0) if meter_row is not None else 0
    meter_after = max(0, meter_before - cost_milli)
    returned_balance = meter_before // 1000 - meter_after // 1000
    conn.execute(
        "UPDATE users SET token_balance=token_balance+?, daily_tokens_used=MAX(0,daily_tokens_used-?), tokens_used=MAX(0,tokens_used-?) WHERE id=?",
        (returned_balance, returned_daily, returned_balance, user_id),
    )
    conn.execute(
        "INSERT INTO chat_billing_meters (user_id,accrued_millitokens,updated_at) VALUES (?,?,?) "
        "ON CONFLICT(user_id) DO UPDATE SET accrued_millitokens=excluded.accrued_millitokens,updated_at=excluded.updated_at",
        (user_id, meter_after, datetime.now(timezone.utc).isoformat()),
    )
    conn.execute(
        "INSERT INTO token_ledger (id,user_id,delta,reason,meta_json,created_at) VALUES (?,?,?,?,?,?)",
        (
            uuid.uuid4().hex,
            user_id,
            returned_balance,
            "chat_refund",
            json.dumps(
                {
                    "charged_ledger_id": ledger_id,
                    "request_id": meta.get("request_id"),
                    "daily_part": returned_daily,
                    "balance_part": returned_balance,
                    "reason": reason[:240],
                },
                ensure_ascii=False,
            ),
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    return True


def charge_chat_tokens_for_user(*, connect: Any, get_tariffs: Any, reconcile_tariff: Any, user_id: str, **kwargs: Any) -> dict[str, Any]:
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT internal_user_id,plan FROM users WHERE id=?", (user_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "Пользователь не найден.")
        if row["internal_user_id"]:
            reconcile_tariff(conn, str(row["internal_user_id"]), now=datetime.now(timezone.utc))
            row = conn.execute("SELECT internal_user_id,plan FROM users WHERE id=?", (user_id,)).fetchone()
        tariffs = get_tariffs(conn)
        tariff = tariffs.get(str(row["plan"] or "mini").lower(), tariffs["mini"])
        result = charge_chat_tokens(conn, user_id=user_id, daily_limit=int(tariff["daily_tokens"]), **kwargs)
        conn.commit()
        return result


def refund_chat_tokens_for_user(*, connect: Any, **kwargs: Any) -> bool:
    with connect() as conn:
        result = refund_chat_tokens(conn, **kwargs)
        conn.commit()
        return result
