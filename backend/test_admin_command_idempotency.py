"""HTTP contracts for the two administrative entitlement command routes."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from threading import Barrier

import pytest
from fastapi.testclient import TestClient

import main


ROUTES = {
    "tokens": ("/api/admin/users/command-target/tokens-v2", {"delta": 25, "reason": "manual correction"}),
    "plan": ("/api/admin/users/command-target/plan-v2", {"plan": "pro", "duration_days": 35, "reason": "manual upgrade"}),
}


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "admin-command-http.sqlite3")
    monkeypatch.setattr(main, "TRUSTED_COOKIE_SECURE", False)
    main.init_db()
    with closing(main.db()) as conn, conn:
        for internal, legacy, role in (
            ("command-admin", "local_admin", "admin"),
            ("command-target", "local_target", "user"),
            ("command-other", "local_other", "user"),
        ):
            conn.execute(
                "INSERT INTO users (id, internal_user_id, role, banned, token_balance, plan, "
                "language, created_at, last_login_at) VALUES (?, ?, ?, 0, 50, 'mini', 'ru', ?, ?)",
                (legacy, internal, role, "2026-01-01", "2026-01-01"),
            )
    tokens = {}
    for internal, legacy in (("command-admin", "local_admin"), ("command-other", "local_other")):
        tokens[internal] = main.create_auth_session(
            internal, legacy, provider="telegram", platform="telegram_mini_app",
        )["session_token"]
    return tokens


def post(state, kind, *, key="admin-command-key-0001", changes=None, actor="command-admin"):
    route, source = ROUTES[kind]
    payload = {**source, **(changes or {})}
    if key is not None:
        payload["idempotency_key"] = key
    headers = {"Authorization": f"Bearer {state[actor]}"} if actor else {}
    # init_db is explicit; no application lifespan or background workers run.
    with closing(TestClient(main.app, raise_server_exceptions=False)) as client:
        return client.post(route, json=payload, headers=headers)


def snapshot():
    with closing(main.db()) as conn:
        user = dict(conn.execute(
            "SELECT id, role, token_balance, plan, plan_started_at, plan_expires_at, "
            "plan_next_token_grant_at FROM users WHERE internal_user_id='command-target'",
        ).fetchone())
        counts = {}
        for table, where in (
            ("token_ledger", "user_id='local_target'"),
            ("tariff_token_grants", "internal_user_id='command-target'"),
            ("audit_logs", "target_internal_user_id='command-target'"),
        ):
            counts[table] = conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}").fetchone()[0]
        return {"user": user, "counts": counts}


@pytest.mark.parametrize("kind", ["tokens", "plan"])
def test_same_key_replays_first_response_and_preserves_business_state(state, kind):
    first = post(state, kind)
    assert first.status_code == 200, first.text
    committed = snapshot()
    replay = post(state, kind)
    assert replay.status_code == 200, replay.text
    assert replay.json() == first.json()
    assert replay.content == first.content
    assert snapshot() == committed
    assert committed["counts"]["token_ledger"] == 1
    assert committed["counts"]["audit_logs"] == 1
    assert committed["counts"]["tariff_token_grants"] == (1 if kind == "plan" else 0)
    assert committed["user"]["id"] == "local_target"
    assert committed["user"]["role"] == "user"


@pytest.mark.parametrize("kind", ["tokens", "plan"])
@pytest.mark.parametrize("trial", range(5))
def test_concurrent_same_key_has_one_entitlement_ledger_and_audit(state, kind, trial):
    barrier = Barrier(2)

    def run():
        barrier.wait(timeout=5)
        return post(state, kind, key=f"http-race-{kind}-{trial:04d}")

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(run) for _ in range(2)]
        responses = [future.result(timeout=20) for future in futures]
    assert [response.status_code for response in responses] == [200, 200]
    assert responses[0].json() == responses[1].json()
    assert responses[0].content == responses[1].content
    observed = snapshot()
    assert observed["counts"]["token_ledger"] == 1
    assert observed["counts"]["audit_logs"] == 1
    assert observed["counts"]["tariff_token_grants"] == (1 if kind == "plan" else 0)
    expected = 75 if kind == "tokens" else 50 + responses[0].json()["activation"]["monthly_tokens_granted"]
    assert observed["user"]["token_balance"] == expected


@pytest.mark.parametrize("kind, changes", [("tokens", {"delta": 26}), ("plan", {"duration_days": 36})])
def test_conflicting_reuse_is_rejected_without_a_second_effect(state, kind, changes):
    assert post(state, kind).status_code == 200
    before = snapshot()
    response = post(state, kind, changes=changes)
    assert response.status_code == 409, response.text
    assert snapshot() == before


@pytest.mark.parametrize("kind", ["tokens", "plan"])
@pytest.mark.parametrize("key", [None, "", "short", "a" * 121, "bad key 00000001"])
def test_missing_or_invalid_key_is_rejected_before_a_financial_effect(state, kind, key):
    before = snapshot()
    response = post(state, kind, key=key)
    assert response.status_code == 400, response.text
    assert snapshot() == before


@pytest.mark.parametrize("kind", ["tokens", "plan"])
@pytest.mark.parametrize("actor, status", [(None, 401), ("command-other", 403)])
def test_each_route_requires_current_trusted_admin(state, kind, actor, status):
    before = snapshot()
    assert post(state, kind, actor=actor).status_code == status
    assert snapshot() == before


@pytest.mark.parametrize("kind", ["tokens", "plan"])
def test_whitespace_reason_fails_and_normalized_reason_replays(state, kind):
    before = snapshot()
    assert post(state, kind, changes={"reason": " \t\n "}).status_code == 400
    assert snapshot() == before
    first = post(state, kind, changes={"reason": "  explicit correction  "})
    assert first.status_code == 200, first.text
    replay = post(state, kind, changes={"reason": "explicit correction"})
    assert replay.status_code == 200
    assert replay.json() == first.json()


@pytest.mark.parametrize("kind", ["tokens", "plan"])
def test_audit_failure_is_atomic_and_retry_can_succeed(state, kind, monkeypatch):
    before = snapshot()
    original = main.record_audit_log

    def unavailable_audit(*args, **kwargs):
        raise RuntimeError("isolated audit write failure")

    monkeypatch.setattr(main, "record_audit_log", unavailable_audit)
    assert post(state, kind).status_code == 500
    assert snapshot() == before
    with closing(main.db()) as conn:
        assert conn.execute("SELECT COUNT(*) FROM admin_commands").fetchone()[0] == 0
    monkeypatch.setattr(main, "record_audit_log", original)
    assert post(state, kind).status_code == 200
    assert snapshot()["counts"]["token_ledger"] == 1
