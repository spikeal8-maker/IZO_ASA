from __future__ import annotations

import sqlite3

from app.api.routers.phone_chat import PhoneChatRequest, _resolve_phone_chat_model
from app.services.chat_billing import build_chat_reservation_quote, build_text_model_economics, charge_chat_tokens, chat_usage_report, normalize_chat_config, refund_chat_tokens, settle_chat_tokens


def test_text_model_economics_exposes_canonical_per_million_product_prices() -> None:
    result = build_text_model_economics(
        input_per_million_usd=1,
        output_per_million_usd=2,
        exchange_rate=100,
        funding_reserve_percent=30,
        minimum_margin_percent=50,
        token_rub=5,
        observed_at="2026-08-28T10:00:00+00:00",
    )

    assert result["priceStatus"] == "priced"
    assert result["inputPerMillion"]["quotedCostRub"] == 130
    assert result["inputPerMillion"]["reservedTokens"] == 52
    assert result["outputPerMillion"]["reservedTokens"] == 104
    assert result["millionRussianChars"]["assumedProviderTokens"] == 250_000
    assert result["millionRussianChars"]["input"]["reservedTokens"] == 13
    assert result["millionRussianChars"]["output"]["reservedTokens"] == 26
    assert result["fundingReservePercent"] == 30
    assert result["minimumMarginPercent"] == 50


def test_text_model_economics_marks_missing_rate_and_free_models_honestly() -> None:
    missing = build_text_model_economics(
        input_per_million_usd=1,
        output_per_million_usd=2,
        exchange_rate=None,
        funding_reserve_percent=30,
        minimum_margin_percent=50,
        token_rub=5,
    )
    free = build_text_model_economics(
        input_per_million_usd=0,
        output_per_million_usd=0,
        exchange_rate=100,
        funding_reserve_percent=30,
        minimum_margin_percent=50,
        token_rub=5,
    )

    assert missing["priceStatus"] == "missing_rate"
    assert missing["inputPerMillion"] is None
    assert free["priceStatus"] == "free"
    assert free["inputPerMillion"]["reservedTokens"] == 0


def test_shared_64k_context_survives_normalization_and_stays_bounded() -> None:
    assert normalize_chat_config({"localNumCtx": 65536})["localNumCtx"] == 65536
    assert normalize_chat_config({"localNumCtx": 131072})["localNumCtx"] == 65536
    assert normalize_chat_config({"localNumCtx": 1024})["localNumCtx"] == 4096
    assert normalize_chat_config({})["localNumCtx"] == 16384


def _database() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE users (
          id TEXT PRIMARY KEY,
          token_balance INTEGER NOT NULL,
          daily_tokens_used INTEGER NOT NULL DEFAULT 0,
          last_daily_reset TEXT,
          tokens_used INTEGER NOT NULL DEFAULT 0,
          last_seen_at TEXT
        );
        CREATE TABLE token_ledger (
          id TEXT PRIMARY KEY,
          user_id TEXT NOT NULL,
          delta INTEGER NOT NULL,
          reason TEXT NOT NULL,
          meta_json TEXT,
          created_at TEXT NOT NULL
        );
        CREATE TABLE event_logs (event_name TEXT, properties_json TEXT, created_at TEXT);
        INSERT INTO users (id, token_balance) VALUES ('user-1', 10);
        """
    )
    return conn


def test_same_request_id_is_independent_between_users() -> None:
    conn = _database()
    conn.execute("INSERT INTO users (id, token_balance) VALUES ('user-2', 10)")

    first = charge_chat_tokens(
        conn,
        user_id="user-1",
        token_cost=3,
        request_id="shared-request",
        provider="api",
        model="provider/model",
        daily_limit=25,
    )
    second = charge_chat_tokens(
        conn,
        user_id="user-2",
        token_cost=3,
        request_id="shared-request",
        provider="api",
        model="provider/model",
        daily_limit=25,
    )

    balances = {
        row["id"]: row["token_balance"]
        for row in conn.execute("SELECT id,token_balance FROM users ORDER BY id")
    }
    assert first["ledger_id"] != second["ledger_id"]
    assert balances == {"user-1": 7, "user-2": 7}


def test_request_id_underscore_is_matched_literally() -> None:
    conn = _database()
    first = charge_chat_tokens(
        conn,
        user_id="user-1",
        token_cost=1,
        request_id="requestXliteral",
        provider="api",
        model="provider/model",
        daily_limit=25,
    )
    second = charge_chat_tokens(
        conn,
        user_id="user-1",
        token_cost=1,
        request_id="request_literal",
        provider="api",
        model="provider/model",
        daily_limit=25,
    )

    assert first["ledger_id"] != second["ledger_id"]
    assert conn.execute("SELECT token_balance FROM users WHERE id='user-1'").fetchone()[0] == 8


def test_local_chat_is_free_and_preserves_both_balances() -> None:
    conn = _database()
    charge = charge_chat_tokens(conn, user_id="user-1", token_cost=0, request_id="req-local-1", provider="local", model="gemma4:12b", daily_limit=25)
    row = conn.execute("SELECT token_balance,daily_tokens_used,tokens_used FROM users WHERE id='user-1'").fetchone()
    assert dict(row) == {"token_balance": 10, "daily_tokens_used": 0, "tokens_used": 0}
    assert charge["token_cost"] == 0
    assert charge["daily_part"] == 0
    assert charge["balance_part"] == 0


def test_openrouter_chat_uses_main_balance_and_is_idempotent() -> None:
    conn = _database()
    first = charge_chat_tokens(conn, user_id="user-1", token_cost=3, request_id="req-api-1", provider="api", model="provider/model", daily_limit=25)
    second = charge_chat_tokens(conn, user_id="user-1", token_cost=3, request_id="req-api-1", provider="api", model="provider/model", daily_limit=25)
    row = conn.execute("SELECT token_balance,daily_tokens_used,tokens_used FROM users WHERE id='user-1'").fetchone()
    assert dict(row) == {"token_balance": 7, "daily_tokens_used": 0, "tokens_used": 3}
    assert second["ledger_id"] == first["ledger_id"]
    assert second["duplicate"] is True


def test_fractional_openrouter_chat_accumulates_before_one_main_token() -> None:
    conn = _database()
    for index in range(9):
        charge = charge_chat_tokens(conn, user_id="user-1", token_cost=0.1, request_id=f"req-frac-{index}", provider="api", model="provider/model", daily_limit=25)
        assert charge["balance_part"] == 0
    tenth = charge_chat_tokens(conn, user_id="user-1", token_cost=0.1, request_id="req-frac-9", provider="api", model="provider/model", daily_limit=25)
    row = conn.execute("SELECT token_balance,daily_tokens_used,tokens_used FROM users WHERE id='user-1'").fetchone()
    assert dict(row) == {"token_balance": 9, "daily_tokens_used": 0, "tokens_used": 1}
    assert tenth["balance_part"] == 1


def test_zero_whole_token_balance_cannot_fund_fractional_api_responses() -> None:
    conn = _database()
    conn.execute("UPDATE users SET token_balance=0 WHERE id='user-1'")
    try:
        charge_chat_tokens(conn, user_id="user-1", token_cost=0.1, request_id="req-zero", provider="api", model="provider/model", daily_limit=25)
    except Exception as exc:
        assert getattr(exc, "status_code", None) == 402
    else:
        raise AssertionError("A zero balance funded a paid fractional response")


def test_usage_quote_reserves_then_idempotently_refunds_unused_fraction() -> None:
    conn = _database()
    quote = build_chat_reservation_quote(
        messages=[{"content": "Короткий вопрос"}],
        image_count=0,
        input_per_million_usd=1,
        output_per_million_usd=10,
        exchange_rate=80,
        funding_reserve_percent=30,
        minimum_margin_percent=50,
        token_rub=5,
    )
    charge = charge_chat_tokens(
        conn, user_id="user-1", token_cost=quote["reservedTokens"], request_id="req-settle",
        provider="api", model="provider/model", daily_limit=25,
    )
    settled = settle_chat_tokens(
        conn, user_id="user-1", ledger_id=charge["ledger_id"], quote=quote, actual_cost_usd=0.001,
    )
    repeated = settle_chat_tokens(
        conn, user_id="user-1", ledger_id=charge["ledger_id"], quote=quote, actual_cost_usd=0.001,
    )
    assert 0 < settled["settled_tokens"] <= quote["reservedTokens"]
    assert settled["refunded_millitokens"] > 0
    assert repeated["duplicate"] is True


def test_chat_usage_report_uses_provider_usage_and_actual_margin() -> None:
    conn = _database()
    conn.execute(
        "INSERT INTO event_logs VALUES (?,?,?)",
        (
            "phone_chat_answered",
            '{"model":"provider/model","cost_usd":0.01,"provider_usage":{"prompt_tokens":100,"completion_tokens":50},"billing_quote":{"tokenRub":5,"effectiveUsdRub":100},"billing_settlement":{"settled_tokens":0.4,"status":"actual"}}',
            "2026-08-28T00:00:00+00:00",
        ),
    )
    report = chat_usage_report(conn)
    assert report["priced"] == 1
    assert report["averageCostUsd"] == 0.01
    assert report["marginPercent"] == 50
    assert report["recent"][0]["inputTokens"] == 100


def test_failed_chat_refund_is_idempotent() -> None:
    conn = _database()
    charge = charge_chat_tokens(conn, user_id="user-1", token_cost=3, request_id="req-api-2", provider="api", model="provider/model", daily_limit=25)
    assert refund_chat_tokens(conn, user_id="user-1", ledger_id=charge["ledger_id"], reason="provider failed") is True
    assert refund_chat_tokens(conn, user_id="user-1", ledger_id=charge["ledger_id"], reason="provider failed") is False
    row = conn.execute("SELECT token_balance,daily_tokens_used,tokens_used FROM users WHERE id='user-1'").fetchone()
    assert dict(row) == {"token_balance": 10, "daily_tokens_used": 0, "tokens_used": 0}


def test_chat_model_selection_never_exposes_or_silently_switches_local_model() -> None:
    config = {
        "enabled": True,
        "localEnabled": True,
        "localModel": "gemma4:12b",
        "localTokenCost": 0,
        "defaultModel": "local:izo-chat",
        "enabledApiModels": ["provider/model"],
        "apiTokenCosts": {"provider/model": 0.1},
    }
    selected = _resolve_phone_chat_model(PhoneChatRequest(messages=[{"role": "user", "content": "Привет"}], modelId="local:izo-chat"), config)
    assert selected == ("local:izo-chat", "local", "gemma4:12b", 0.0, "free")
    selected_api = _resolve_phone_chat_model(PhoneChatRequest(messages=[{"role": "user", "content": "Привет"}], modelId="provider/model"), config)
    assert selected_api == ("provider/model", "api", "provider/model", 0.1, "main")


def test_chat_model_tariff_access_is_normalized_and_enforced() -> None:
    legacy = normalize_chat_config({"enabledApiModels": ["provider/model"]})
    assert legacy["publishedApiModels"] == ["provider/model"]
    assert legacy["apiTierAccess"] == {
        "mini": ["provider/model"], "plus": ["provider/model"],
        "pro": ["provider/model"], "business": ["provider/model"],
    }
    config = normalize_chat_config({
        "enabledApiModels": ["provider/model", "provider/other"],
        "apiTierAccess": {"mini": ["provider/model", "not-enabled"], "pro": ["provider/other"]},
    })
    assert config["apiTierAccess"]["mini"] == ["provider/model"]
    assert config["apiTierAccess"]["plus"] == []
    request = PhoneChatRequest(messages=[{"role": "user", "content": "Привет"}], modelId="provider/model")
    assert _resolve_phone_chat_model(request, config, "mini")[0] == "provider/model"
    try:
        _resolve_phone_chat_model(request, config, "plus")
    except ValueError as exc:
        assert "тарифе" in str(exc)
    else:
        raise AssertionError("Tariff-blocked model was accepted")


def test_unpublished_chat_model_is_removed_from_operations_and_tariffs() -> None:
    config = normalize_chat_config({
        "publishedApiModels": ["provider/model"],
        "enabledApiModels": ["provider/model", "provider/hidden"],
        "apiTierAccess": {"mini": ["provider/model", "provider/hidden"]},
    })
    assert config["publishedApiModels"] == ["provider/model"]
    assert config["enabledApiModels"] == ["provider/model"]
    assert config["apiTierAccess"]["mini"] == ["provider/model"]
