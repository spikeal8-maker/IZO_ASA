from __future__ import annotations

import sqlite3

from app.api.routers.phone_chat import PhoneChatRequest, _resolve_phone_chat_model
from app.services.chat_billing import charge_chat_tokens, normalize_chat_config, refund_chat_tokens


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
        INSERT INTO users (id, token_balance) VALUES ('user-1', 10);
        """
    )
    return conn


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
