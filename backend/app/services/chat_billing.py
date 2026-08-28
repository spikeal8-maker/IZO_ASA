"""Atomic product-token billing for user chat answers."""

from __future__ import annotations

import json
import math
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException

from . import cloud_quote


DEFAULT_CHAT_CONFIG: dict[str, Any] = {
    "enabled": True,
    "localEnabled": True,
    "localModel": "gemma4:12b",
    "localLabel": "ИЗО Чат",
    "localTokenCost": 0,
    "defaultModel": "local:izo-chat",
    "publishedApiModels": ["deepseek/deepseek-v4-flash"],
    "enabledApiModels": ["deepseek/deepseek-v4-flash"],
    "apiTokenCosts": {"deepseek/deepseek-v4-flash": 0.1},
    "apiTierAccess": {},
    "contextChars": 60000,
    "localNumCtx": 16384,
    "localTimeoutSeconds": 60,
    "apiTimeoutSeconds": 60,
    "usageBillingEnabled": True,
}


def normalize_chat_config(value: Any) -> dict[str, Any]:
    stored = value if isinstance(value, dict) else {}
    source = {**DEFAULT_CHAT_CONFIG, **stored}
    bounded = lambda raw, default, low, high: max(low, min(high, int(raw if str(raw).lstrip("+-").isdigit() else default)))
    requested_enabled = list(dict.fromkeys(str(item).strip() for item in source.get("enabledApiModels", []) if str(item).strip()))[:100]
    raw_published = stored.get("publishedApiModels")
    published_api = (
        list(dict.fromkeys(str(item).strip() for item in raw_published if str(item).strip()))[:100]
        if isinstance(raw_published, list)
        else list(requested_enabled)
    )
    published_set = set(published_api)
    enabled_api = [model_id for model_id in requested_enabled if model_id in published_set]
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
        "publishedApiModels": published_api,
        "enabledApiModels": enabled_api,
        "apiTokenCosts": {model_id: bounded_cost(raw_costs.get(model_id)) for model_id in enabled_api},
        "apiTierAccess": tier_access,
        "contextChars": bounded(source.get("contextChars"), 60000, 4000, 240000),
        "localNumCtx": bounded(source.get("localNumCtx"), 16384, 4096, 32768),
        "localTimeoutSeconds": bounded(source.get("localTimeoutSeconds"), 60, 10, 180),
        "apiTimeoutSeconds": bounded(source.get("apiTimeoutSeconds"), 60, 10, 90),
        "usageBillingEnabled": bool(source.get("usageBillingEnabled", True)),
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
    if provider != "local" and cost_milli > 0 and old_balance <= 0:
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


def build_chat_reservation_quote(
    *,
    messages: list[Any],
    image_count: int,
    input_per_million_usd: float,
    output_per_million_usd: float,
    exchange_rate: float,
    funding_reserve_percent: float,
    minimum_margin_percent: float,
    token_rub: float,
) -> dict[str, Any]:
    """Conservatively reserve up to three chat/tool rounds at 0.001-token precision."""

    input_chars = sum(len(str(getattr(item, "content", None) or (item.get("content") if isinstance(item, dict) else ""))) for item in messages)
    estimated_input_tokens = max(1, (input_chars + 3) // 4) + 600 + max(0, image_count) * 1200
    billed_input_ceiling = estimated_input_tokens * 3
    output_token_ceiling = 4000
    official_cost = (
        max(0.0, float(input_per_million_usd)) * billed_input_ceiling
        + max(0.0, float(output_per_million_usd)) * output_token_ceiling
    ) / 1_000_000
    quote = cloud_quote.build_cloud_quote(
        official_cost_usd=official_cost,
        exchange_rate=exchange_rate,
        funding_reserve_percent=funding_reserve_percent,
        minimum_margin_percent=minimum_margin_percent,
        token_rub=token_rub,
        minimum_tokens=0.001,
        token_quantum=0.001,
        official_source="openrouter_text_catalog",
    )
    quote.update({
        "product": "chat",
        "estimatedInputTokens": estimated_input_tokens,
        "billedInputTokenCeiling": billed_input_ceiling,
        "outputTokenCeiling": output_token_ceiling,
        "inputPerMillionUsd": float(input_per_million_usd),
        "outputPerMillionUsd": float(output_per_million_usd),
        "reserveMillitokens": int(round(float(quote["reservedTokens"]) * 1000)),
    })
    return quote


def build_text_model_economics(
    *,
    input_per_million_usd: float,
    output_per_million_usd: float,
    exchange_rate: float | None,
    funding_reserve_percent: float,
    minimum_margin_percent: float,
    token_rub: float,
    observed_at: str | None = None,
) -> dict[str, Any]:
    """Return the canonical admin/public retail view for one text model.

    One million Russian characters is deliberately an estimate based on the
    same four-characters-per-provider-token assumption used by chat preflight.
    The input and output estimates stay separate because provider rates differ.
    """

    input_usd = max(0.0, float(input_per_million_usd))
    output_usd = max(0.0, float(output_per_million_usd))
    common = {
        "exchange_rate": exchange_rate,
        "funding_reserve_percent": funding_reserve_percent,
        "minimum_margin_percent": minimum_margin_percent,
        "token_rub": token_rub,
        "minimum_tokens": 0.001,
        "token_quantum": 0.001,
        "official_source": "openrouter_text_catalog",
        "observed_at": observed_at,
    }

    def quote(cost_usd: float) -> dict[str, Any] | None:
        if cost_usd == 0:
            return {
                "quotedCostUsd": 0.0,
                "quotedCostRub": 0.0,
                "reservedTokens": 0.0,
                "revenueRub": 0.0,
                "profitRub": 0.0,
                "marginPercent": None,
            }
        if exchange_rate is None or float(exchange_rate) <= 0:
            return None
        return cloud_quote.build_cloud_quote(official_cost_usd=cost_usd, **common)

    input_quote = quote(input_usd)
    output_quote = quote(output_usd)
    chars_provider_tokens = 250_000
    chars_input_quote = quote(input_usd / 4)
    chars_output_quote = quote(output_usd / 4)
    sample_quote = quote(input_usd / 1000 + output_usd / 2000)
    price_status = "missing_rate" if exchange_rate is None or float(exchange_rate or 0) <= 0 else "free" if input_usd == 0 and output_usd == 0 else "priced"
    return {
        "schema": "text-model-economics-v1",
        "priceStatus": price_status,
        "priceSource": "openrouter_text_catalog",
        "priceObservedAt": observed_at,
        "exchangeRate": float(exchange_rate) if exchange_rate is not None else None,
        "fundingReservePercent": round(max(0.0, float(funding_reserve_percent)), 4),
        "minimumMarginPercent": round(max(0.0, min(95.0, float(minimum_margin_percent))), 4),
        "tokenRub": round(max(0.01, float(token_rub)), 6),
        "inputPerMillion": input_quote,
        "outputPerMillion": output_quote,
        "millionRussianChars": {
            "assumedProviderTokens": chars_provider_tokens,
            "charsPerProviderToken": 4,
            "input": chars_input_quote,
            "output": chars_output_quote,
            "approximate": True,
        },
        "sample1000Input500Output": sample_quote,
    }


def enrich_text_models_economics(
    models: list[dict[str, Any]],
    *,
    exchange: dict[str, Any],
    economy: dict[str, Any],
    fallback_observed_at: str,
) -> list[dict[str, Any]]:
    observed_at = str(exchange.get("fetchedAt") or exchange.get("sourceDate") or fallback_observed_at)
    exchange_rate = float(exchange["rate"]) if isinstance(exchange.get("rate"), (int, float)) else None
    return [{
        **model,
        "economics": build_text_model_economics(
            input_per_million_usd=float(model.get("inputPerMillionUsd") or 0),
            output_per_million_usd=float(model.get("outputPerMillionUsd") or 0),
            exchange_rate=exchange_rate,
            funding_reserve_percent=float(economy["usdFeePercent"]),
            minimum_margin_percent=float(economy["minMarginPercent"]),
            token_rub=float(economy["tokenRub"]),
            observed_at=observed_at,
        ),
    } for model in models]


def chat_usage_report(conn: sqlite3.Connection, *, limit: int = 500) -> dict[str, Any]:
    rows = conn.execute(
        "SELECT properties_json,created_at FROM event_logs WHERE event_name='phone_chat_answered' "
        "ORDER BY created_at DESC LIMIT ?",
        (max(1, min(2000, int(limit))),),
    ).fetchall()
    priced = 0
    cost_usd = settled_tokens = revenue_rub = profit_rub = 0.0
    recent: list[dict[str, Any]] = []
    per_model: dict[str, dict[str, Any]] = {}
    for row in rows:
        try:
            properties = json.loads(row["properties_json"] or "{}")
        except (TypeError, json.JSONDecodeError):
            continue
        settlement = properties.get("billing_settlement") if isinstance(properties.get("billing_settlement"), dict) else {}
        quote = properties.get("billing_quote") if isinstance(properties.get("billing_quote"), dict) else {}
        actual = properties.get("cost_usd")
        model_id = str(properties.get("model") or "").strip()
        model_stats = per_model.setdefault(model_id, {"answers": 0, "priced": 0, "costUsd": 0.0, "settledTokens": 0.0, "revenueRub": 0.0, "profitRub": 0.0}) if model_id else None
        if model_stats is not None:
            model_stats["answers"] += 1
        if isinstance(actual, (int, float)) and float(actual) > 0:
            priced += 1
            actual_value = float(actual)
            cost_usd += actual_value
            tokens = float(settlement.get("settled_tokens") or properties.get("product_token_cost") or 0)
            settled_tokens += tokens
            revenue = tokens * float(quote.get("tokenRub") or 0)
            cost_rub = actual_value * float(quote.get("effectiveUsdRub") or 0)
            revenue_rub += revenue
            profit_rub += revenue - cost_rub
            if model_stats is not None:
                model_stats["priced"] += 1
                model_stats["costUsd"] += actual_value
                model_stats["settledTokens"] += tokens
                model_stats["revenueRub"] += revenue
                model_stats["profitRub"] += revenue - cost_rub
        if len(recent) < 30:
            usage = properties.get("provider_usage") if isinstance(properties.get("provider_usage"), dict) else {}
            recent.append({
                "createdAt": row["created_at"],
                "model": properties.get("model"),
                "inputTokens": usage.get("prompt_tokens") or usage.get("input_tokens"),
                "outputTokens": usage.get("completion_tokens") or usage.get("output_tokens"),
                "costUsd": actual if isinstance(actual, (int, float)) else None,
                "settledTokens": settlement.get("settled_tokens"),
                "status": settlement.get("status") or "legacy",
            })
    normalized_per_model: dict[str, dict[str, Any]] = {}
    for model_id, stats in per_model.items():
        priced_count = int(stats["priced"])
        model_revenue = float(stats["revenueRub"])
        normalized_per_model[model_id] = {
            "answers": int(stats["answers"]),
            "priced": priced_count,
            "averageCostUsd": round(float(stats["costUsd"]) / priced_count, 8) if priced_count else None,
            "settledTokens": round(float(stats["settledTokens"]), 3),
            "revenueRub": round(model_revenue, 6),
            "profitRub": round(float(stats["profitRub"]), 6),
            "marginPercent": round(float(stats["profitRub"]) / model_revenue * 100, 4) if model_revenue else None,
        }
    return {
        "answers": len(rows),
        "priced": priced,
        "missingActual": len(rows) - priced,
        "costUsd": round(cost_usd, 8),
        "averageCostUsd": round(cost_usd / priced, 8) if priced else None,
        "settledTokens": round(settled_tokens, 3),
        "revenueRub": round(revenue_rub, 6),
        "profitRub": round(profit_rub, 6),
        "marginPercent": round(profit_rub / revenue_rub * 100, 4) if revenue_rub else None,
        "recent": recent,
        "perModel": normalized_per_model,
    }


def settle_chat_tokens(
    conn: sqlite3.Connection,
    *,
    user_id: str,
    ledger_id: str,
    quote: dict[str, Any],
    actual_cost_usd: float | None,
) -> dict[str, Any]:
    """Idempotently settle below the accepted reservation and return unused credit."""

    existing = conn.execute(
        "SELECT meta_json FROM token_ledger WHERE reason='chat_settlement' AND meta_json LIKE ? LIMIT 1",
        (f'%"charged_ledger_id": "{ledger_id}"%',),
    ).fetchone()
    if existing is not None:
        return {**json.loads(existing["meta_json"] or "{}"), "duplicate": True}
    charge = conn.execute(
        "SELECT meta_json FROM token_ledger WHERE id=? AND user_id=? AND reason='chat'",
        (ledger_id, user_id),
    ).fetchone()
    if charge is None:
        return {"settled_tokens": 0.0, "returned_balance": 0, "duplicate": False}
    charge_meta = json.loads(charge["meta_json"] or "{}")
    reserved_milli = max(0, int(charge_meta.get("cost_millitokens") or quote.get("reserveMillitokens") or 0))
    actual_values = []
    try:
        if actual_cost_usd is not None and float(actual_cost_usd) > 0:
            actual_values.append(float(actual_cost_usd))
    except (TypeError, ValueError):
        pass
    if actual_values:
        effective_rate = float(quote.get("effectiveUsdRub") or 0)
        margin_factor = max(0.05, 1 - float(quote.get("minimumMarginPercent") or 0) / 100)
        rub_per_token = max(0.01, float(quote.get("tokenRub") or 5))
        required_tokens = actual_values[0] * effective_rate / margin_factor / rub_per_token
        settled_milli = min(reserved_milli, max(1, math.ceil(required_tokens * 1000)))
        status = "actual"
    else:
        settled_milli = reserved_milli
        status = "actual_cost_missing"
    refund_milli = reserved_milli - settled_milli
    meter_row = conn.execute("SELECT accrued_millitokens FROM chat_billing_meters WHERE user_id=?", (user_id,)).fetchone()
    meter_before = int(meter_row["accrued_millitokens"] or 0) if meter_row is not None else 0
    meter_after = max(0, meter_before - refund_milli)
    returned_balance = meter_before // 1000 - meter_after // 1000
    now_iso = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "UPDATE users SET token_balance=token_balance+?, tokens_used=MAX(0,tokens_used-?) WHERE id=?",
        (returned_balance, returned_balance, user_id),
    )
    conn.execute(
        "INSERT INTO chat_billing_meters (user_id,accrued_millitokens,updated_at) VALUES (?,?,?) "
        "ON CONFLICT(user_id) DO UPDATE SET accrued_millitokens=excluded.accrued_millitokens,updated_at=excluded.updated_at",
        (user_id, meter_after, now_iso),
    )
    row = conn.execute("SELECT token_balance FROM users WHERE id=?", (user_id,)).fetchone()
    meta = {
        "charged_ledger_id": ledger_id,
        "request_id": charge_meta.get("request_id"),
        "status": status,
        "reserved_millitokens": reserved_milli,
        "settled_millitokens": settled_milli,
        "refunded_millitokens": refund_milli,
        "settled_tokens": round(settled_milli / 1000, 3),
        "actual_cost_usd": actual_values[0] if actual_values else None,
        "underquoted": bool(actual_values and settled_milli == reserved_milli and actual_values[0] > float(quote.get("quotedCostUsd") or 0)),
        "returned_balance": returned_balance,
        "new_balance": int(row["token_balance"] or 0) if row is not None else None,
    }
    conn.execute(
        "INSERT INTO token_ledger (id,user_id,delta,reason,meta_json,created_at) VALUES (?,?,?,?,?,?)",
        (uuid.uuid4().hex, user_id, returned_balance, "chat_settlement", json.dumps(meta, ensure_ascii=False), now_iso),
    )
    return {**meta, "duplicate": False}


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


def settle_chat_tokens_for_user(*, connect: Any, user_id: str, **kwargs: Any) -> dict[str, Any]:
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        result = settle_chat_tokens(conn, user_id=user_id, **kwargs)
        conn.commit()
        return result


def refund_chat_tokens_for_user(*, connect: Any, **kwargs: Any) -> bool:
    with connect() as conn:
        result = refund_chat_tokens(conn, **kwargs)
        conn.commit()
        return result
