from __future__ import annotations

import asyncio
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routers import phone_chat
from app.api.routers.phone_chat import PhoneChatDependencies, create_phone_chat_router
from app.database import PHONE_CHAT_HISTORY_SCHEMA_SQL, PHONE_CHAT_REQUEST_LIFECYCLE_SCHEMA_SQL
from app.services import chat_request_lifecycle


THREAD_ID = "abcdef12"
MODEL_ID = "provider/model"


def _database(path, *, users: tuple[str, ...] = ("user-1",), with_thread: bool = False) -> None:
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE users (
              id TEXT PRIMARY KEY,
              internal_user_id TEXT,
              plan TEXT NOT NULL DEFAULT 'mini',
              role TEXT NOT NULL DEFAULT 'user',
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
            """
        )
        conn.executemany(
            "INSERT INTO users (id,token_balance) VALUES (?,100)",
            [(user_id,) for user_id in users],
        )
        conn.executescript(PHONE_CHAT_REQUEST_LIFECYCLE_SCHEMA_SQL)
        if with_thread:
            conn.executescript(PHONE_CHAT_HISTORY_SCHEMA_SQL)
            conn.execute(
                "INSERT INTO phone_chat_threads "
                "(id,user_id,title,chat_model_id,context_chars,created_at,updated_at) "
                "VALUES (?,?,?,?,60000,?,?)",
                (THREAD_ID, "user-1", "Новый чат", MODEL_ID, "2026-08-31T00:00:00+00:00", "2026-08-31T00:00:00+00:00"),
            )


def _connect(path):
    def connect() -> sqlite3.Connection:
        conn = sqlite3.connect(path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 10000")
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    return connect


def _lifecycle(path) -> chat_request_lifecycle.ChatRequestLifecycle:
    return chat_request_lifecycle.ChatRequestLifecycle(
        connect=_connect(path),
        get_tariffs=lambda _conn: {"mini": {"daily_tokens": 25}},
        reconcile_tariff=lambda *_args, **_kwargs: None,
    )


def _deps(
    path,
    *,
    record_event=lambda *_args, **_kwargs: None,
    usage_billing: bool = False,
    with_db: bool = False,
) -> PhoneChatDependencies:
    async def catalog():
        return [{"id": MODEL_ID, "inputPerMillionUsd": 1, "outputPerMillionUsd": 1}]

    return PhoneChatDependencies(
        require_trusted_user=lambda request: {
            "legacy_user_id": request.headers.get("x-test-user", "user-1"),
            "internal_user_id": "internal-test",
            "session_id": "session-test",
        },
        assistant_models_config=lambda: {"chat": {
            "enabled": True,
            "localEnabled": True,
            "localModel": "gemma4:12b",
            "defaultModel": MODEL_ID,
            "publishedApiModels": [MODEL_ID],
            "enabledApiModels": [MODEL_ID],
            "apiTokenCosts": {MODEL_ID: 1},
            "apiTierAccess": {"mini": [MODEL_ID]},
            "usageBillingEnabled": usage_billing,
        }},
        openrouter_headers=lambda: {},
        record_openrouter_availability=lambda _status: None,
        record_event=record_event,
        openrouter_text_models=catalog,
        request_lifecycle=_lifecycle(path),
        connect_db=_connect(path) if with_db else None,
        usd_rub_snapshot=lambda: {"rate": 80},
        openrouter_economy=lambda: {"usdFeePercent": 30, "minMarginPercent": 50, "tokenRub": 5},
    )


def _app(deps: PhoneChatDependencies) -> FastAPI:
    app = FastAPI()
    app.include_router(create_phone_chat_router(deps))
    return app


def _payload(*, request_id: str, content: str = "Повтори безопасно", thread_id: str | None = None) -> dict:
    payload = {
        "messages": [{"role": "user", "content": content}],
        "modelId": MODEL_ID,
        "requestId": request_id,
    }
    if thread_id:
        payload["threadId"] = thread_id
    return payload


def _successful_route(call_counter: list[int]):
    async def route(*_args, **_kwargs):
        call_counter[0] += 1
        return "Готово", {"usage": {"cost": 0.001}}, "api", MODEL_ID, MODEL_ID, 1.0, "main"

    return route


def test_completed_request_replay_returns_exact_response_and_one_history_exchange(tmp_path, monkeypatch) -> None:
    path = tmp_path / "chat.sqlite3"
    _database(path, with_thread=True)
    provider_calls = [0]
    monkeypatch.setattr(phone_chat, "route_phone_chat", _successful_route(provider_calls))
    app = _app(_deps(path, with_db=True))
    payload = _payload(request_id="request-replay-1", thread_id=THREAD_ID)

    with TestClient(app) as client:
        first = client.post("/api/phone/chat", json=payload)
        second = client.post("/api/phone/chat", json=payload)

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json() == first.json()
    assert first.json()["messageId"]
    assert provider_calls == [1]
    with _connect(path)() as conn:
        assert conn.execute("SELECT COUNT(*) FROM phone_chat_messages").fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM token_ledger WHERE reason='chat'").fetchone()[0] == 1
        assert conn.execute("SELECT state FROM phone_chat_requests").fetchone()[0] == "succeeded"


def test_reused_request_id_with_different_payload_is_rejected_before_provider(tmp_path, monkeypatch) -> None:
    path = tmp_path / "conflict.sqlite3"
    _database(path)
    provider_calls = [0]
    monkeypatch.setattr(phone_chat, "route_phone_chat", _successful_route(provider_calls))
    app = _app(_deps(path))

    with TestClient(app) as client:
        first = client.post("/api/phone/chat", json=_payload(request_id="request-conflict-1"))
        conflict = client.post(
            "/api/phone/chat",
            json=_payload(request_id="request-conflict-1", content="Другой запрос"),
        )

    assert first.status_code == 200
    assert conflict.status_code == 409
    assert "requestId" in conflict.json()["detail"]
    assert provider_calls == [1]


def test_same_request_id_is_independent_between_authenticated_users(tmp_path, monkeypatch) -> None:
    path = tmp_path / "users.sqlite3"
    _database(path, users=("user-1", "user-2"))
    provider_calls = [0]
    monkeypatch.setattr(phone_chat, "route_phone_chat", _successful_route(provider_calls))
    app = _app(_deps(path))
    payload = _payload(request_id="request-shared-1")

    with TestClient(app) as client:
        first = client.post("/api/phone/chat", json=payload, headers={"x-test-user": "user-1"})
        second = client.post("/api/phone/chat", json=payload, headers={"x-test-user": "user-2"})

    assert first.status_code == 200
    assert second.status_code == 200
    assert provider_calls == [2]
    with _connect(path)() as conn:
        assert conn.execute("SELECT COUNT(*) FROM phone_chat_requests").fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(DISTINCT id) FROM token_ledger WHERE reason='chat'").fetchone()[0] == 2
        assert {
            row["id"]: row["token_balance"]
            for row in conn.execute("SELECT id,token_balance FROM users")
        } == {"user-1": 99, "user-2": 99}


def test_concurrent_replay_has_one_provider_owner_and_retry_after(tmp_path, monkeypatch) -> None:
    path = tmp_path / "race.sqlite3"
    _database(path)
    entered = threading.Event()
    release = threading.Event()
    provider_calls = [0]

    async def blocked_route(*_args, **_kwargs):
        provider_calls[0] += 1
        entered.set()
        while not release.is_set():
            await asyncio.sleep(0.01)
        return "Готово", {"usage": {"cost": 0.001}}, "api", MODEL_ID, MODEL_ID, 1.0, "main"

    monkeypatch.setattr(phone_chat, "route_phone_chat", blocked_route)
    app = _app(_deps(path))
    payload = _payload(request_id="request-race-1")

    with TestClient(app) as first_client, TestClient(app) as second_client:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(first_client.post, "/api/phone/chat", json=payload)
            assert entered.wait(timeout=5)
            duplicate = second_client.post("/api/phone/chat", json=payload)
            release.set()
            first = future.result(timeout=5)

    assert first.status_code == 200
    assert duplicate.status_code == 409
    assert int(duplicate.headers["retry-after"]) >= 1
    assert provider_calls == [1]
    with _connect(path)() as conn:
        assert conn.execute("SELECT COUNT(*) FROM token_ledger WHERE reason='chat'").fetchone()[0] == 1


def test_provider_failure_refunds_once_and_failed_replay_does_not_retry_provider(tmp_path, monkeypatch) -> None:
    path = tmp_path / "failure.sqlite3"
    _database(path)
    provider_calls = [0]

    async def failed_route(*_args, **_kwargs):
        provider_calls[0] += 1
        raise RuntimeError("provider secret detail")

    monkeypatch.setattr(phone_chat, "route_phone_chat", failed_route)
    app = _app(_deps(path))
    payload = _payload(request_id="request-failure-1")

    with TestClient(app) as client:
        first = client.post("/api/phone/chat", json=payload)
        second = client.post("/api/phone/chat", json=payload)

    assert first.status_code == 502
    assert second.status_code == 502
    assert second.json() == first.json()
    assert "secret" not in first.text
    assert provider_calls == [1]
    with _connect(path)() as conn:
        user = conn.execute("SELECT token_balance,tokens_used FROM users WHERE id='user-1'").fetchone()
        assert dict(user) == {"token_balance": 100, "tokens_used": 0}
        assert conn.execute("SELECT accrued_millitokens FROM chat_billing_meters").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM token_ledger WHERE reason='chat_refund'").fetchone()[0] == 1
        assert conn.execute("SELECT state FROM phone_chat_requests").fetchone()[0] == "failed"


def test_post_settlement_history_failure_rolls_back_settlement_then_refunds(tmp_path, monkeypatch) -> None:
    path = tmp_path / "history-failure.sqlite3"
    _database(path, with_thread=True)
    provider_calls = [0]
    monkeypatch.setattr(phone_chat, "route_phone_chat", _successful_route(provider_calls))

    def fail_history(*_args, **_kwargs):
        raise RuntimeError("history unavailable")

    monkeypatch.setattr(chat_request_lifecycle.phone_chat_history, "add_exchange", fail_history)
    app = _app(_deps(path, usage_billing=True, with_db=True))
    payload = _payload(request_id="request-history-failure-1", thread_id=THREAD_ID)

    with TestClient(app) as client:
        first = client.post("/api/phone/chat", json=payload)
        second = client.post("/api/phone/chat", json=payload)

    assert first.status_code == 502
    assert second.status_code == 502
    assert provider_calls == [1]
    with _connect(path)() as conn:
        assert conn.execute("SELECT COUNT(*) FROM phone_chat_messages").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM token_ledger WHERE reason='chat_settlement'").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM token_ledger WHERE reason='chat_refund'").fetchone()[0] == 1
        assert conn.execute("SELECT token_balance FROM users WHERE id='user-1'").fetchone()[0] == 100
        assert conn.execute("SELECT accrued_millitokens FROM chat_billing_meters").fetchone()[0] == 0


def test_telemetry_failure_cannot_change_committed_chat_success(tmp_path, monkeypatch) -> None:
    path = tmp_path / "telemetry.sqlite3"
    _database(path)
    provider_calls = [0]
    event_calls = [0]
    monkeypatch.setattr(phone_chat, "route_phone_chat", _successful_route(provider_calls))

    def failed_event(*_args, **_kwargs):
        event_calls[0] += 1
        raise RuntimeError("telemetry unavailable")

    app = _app(_deps(path, record_event=failed_event))
    payload = _payload(request_id="request-telemetry-1")

    with TestClient(app) as client:
        first = client.post("/api/phone/chat", json=payload)
        second = client.post("/api/phone/chat", json=payload)

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json() == first.json()
    assert provider_calls == [1]
    assert event_calls == [1]


def test_stale_processing_request_is_refunded_and_closed_exactly_once(tmp_path) -> None:
    path = tmp_path / "stale.sqlite3"
    _database(path)
    lifecycle = _lifecycle(path)
    fingerprint = chat_request_lifecycle.phone_chat_request_fingerprint(
        messages=[{"role": "user", "content": "Прерванный запрос"}],
        route="auto",
        model_id=MODEL_ID,
        images=[],
        thread_id=None,
    )
    started = lifecycle.begin(
        user_id="user-1",
        request_id="request-stale-1",
        fingerprint=fingerprint,
        token_cost=1,
        provider="api",
        model=MODEL_ID,
    )
    assert started["state"] == "started"
    with _connect(path)() as conn:
        conn.execute("UPDATE phone_chat_requests SET lease_expires_at='2000-01-01T00:00:00+00:00'")
        conn.commit()

    recovered = lifecycle.inspect(
        user_id="user-1", request_id="request-stale-1", fingerprint=fingerprint
    )
    repeated = lifecycle.inspect(
        user_id="user-1", request_id="request-stale-1", fingerprint=fingerprint
    )

    assert recovered["state"] == "failed"
    assert recovered["recovered"] is True
    assert repeated == {"state": "failed", "status": 503, "detail": chat_request_lifecycle.STALE_DETAIL}
    with _connect(path)() as conn:
        assert conn.execute("SELECT token_balance FROM users WHERE id='user-1'").fetchone()[0] == 100
        assert conn.execute("SELECT COUNT(*) FROM token_ledger WHERE reason='chat_refund'").fetchone()[0] == 1
        assert conn.execute("SELECT state FROM phone_chat_requests").fetchone()[0] == "failed"


def test_processing_claim_binds_selected_provider_and_model(tmp_path) -> None:
    path = tmp_path / "model-binding.sqlite3"
    _database(path)
    lifecycle = _lifecycle(path)
    fingerprint = chat_request_lifecycle.phone_chat_request_fingerprint(
        messages=[{"role": "user", "content": "Один запрос"}],
        route="auto",
        model_id=MODEL_ID,
        images=[],
        thread_id=None,
    )
    started = lifecycle.begin(
        user_id="user-1",
        request_id="request-model-1",
        fingerprint=fingerprint,
        token_cost=1,
        provider="api",
        model=MODEL_ID,
    )
    conflict = lifecycle.begin(
        user_id="user-1",
        request_id="request-model-1",
        fingerprint=fingerprint,
        token_cost=1,
        provider="api",
        model="provider/other",
    )

    assert started["state"] == "started"
    assert conflict["state"] == "conflict"
    with _connect(path)() as conn:
        assert conn.execute("SELECT COUNT(*) FROM token_ledger WHERE reason='chat'").fetchone()[0] == 1
