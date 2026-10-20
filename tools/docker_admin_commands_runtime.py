"""Finite fixture and real loopback HTTP checks inside the owned test container.

Seed runs before uvicorn. Exercise/replay use HTTP for every mutation and open
SQLite read-only. Private sessions and full expected responses stay in the owned
volume; only a redacted finite receipt leaves the container.
"""
from __future__ import annotations

import argparse
import calendar
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
from threading import Barrier
import urllib.error
import urllib.parse
import urllib.request


DATA = Path("/home/izo/data")
MEDIA = Path("/home/izo/media")
DATABASE = DATA / "app.sqlite3"
PRIVATE = DATA / "admin-command-proof.json"
MARKER = MEDIA / "admin-command-proof.bin"
PREFIX = "IZO_ADMIN_RECEIPT:"


def admit() -> str:
    run = os.environ.get("IZO_ADMIN_COMMAND_PROOF_RUN", "")
    if (not re.fullmatch(r"[0-9]+-[0-9]+", run)
            or os.environ.get("APP_ENV") != "test"
            or os.environ.get("DATABASE_URL") != str(DATABASE)
            or os.environ.get("MEDIA_DIR") != str(MEDIA)
            or os.getuid() != 10001):
        raise RuntimeError("ADMIN_PROOF_SCOPE_REJECTED")
    return run


def save_private(value: dict) -> None:
    descriptor = os.open(PRIVATE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, sort_keys=True)
    if PRIVATE.stat().st_mode & 0o077:
        raise RuntimeError("ADMIN_PROOF_PRIVATE_MODE_INVALID")


def private(run: str) -> dict:
    value = json.loads(PRIVATE.read_text(encoding="utf-8"))
    if value.get("run") != run or PRIVATE.stat().st_mode & 0o077:
        raise RuntimeError("ADMIN_PROOF_FIXTURE_OWNER_MISMATCH")
    return value


def seed(run: str) -> dict:
    import main
    if PRIVATE.exists() or DATABASE.exists() and DATABASE.stat().st_size:
        raise RuntimeError("ADMIN_PROOF_FIXTURE_NOT_EMPTY")
    main.init_db()
    targets = []
    for kind in ("tokens", "plan"):
        for trial in range(5):
            internal = f"admin-proof-{run}-{kind}-{trial}"
            targets.append({"kind": kind, "trial": trial, "internal": internal, "legacy": internal + "-legacy"})
    browser_targets = []
    for viewport in ("desktop", "mobile"):
        for kind in ("tokens", "plan"):
            internal = f"admin-proof-{run}-browser-{viewport}-{kind}"
            browser_targets.append({"kind": kind, "viewport": viewport, "internal": internal, "legacy": internal + "-legacy"})
    actors = [(f"admin-proof-{run}-admin", "admin"), (f"admin-proof-{run}-user", "user")]
    with closing(main.db()) as conn, conn:
        users = [(item["internal"], item["legacy"], "user") for item in targets + browser_targets]
        users += [(internal, internal + "-legacy", role) for internal, role in actors]
        for number, (internal, legacy, role) in enumerate(users, 1):
            conn.execute(
                "INSERT INTO users (id,internal_user_id,role,banned,token_balance,plan,language,created_at,last_login_at,public_user_code) "
                "VALUES (?,?,?,0,50,'mini','ru','2026-01-01','2026-01-01',?)", (legacy, internal, role, f"WEB-98{number:04d}"),
            )
        for item in browser_targets:
            conn.execute("UPDATE users SET display_name=? WHERE internal_user_id=?",
                         (f"Admin proof {item['viewport']} {item['kind']}", item["internal"]))
        tariffs = main.get_tariff_config(conn)
        for item in targets + browser_targets:
            item.update(actor=actors[0][0], delta=25, plan="pro", durationDays=30 if "viewport" in item else 35,
                        expectedGrant=int(tariffs["pro"]["monthly_tokens"]))
    sessions = {}
    for internal, role in actors:
        sessions[role] = main.create_auth_session(
            internal, internal + "-legacy", provider="telegram", platform="telegram_mini_app",
        )["session_token"]
    MEDIA.mkdir(exist_ok=True)
    MARKER.write_bytes(b"IZO administrative command persistence proof\n")
    save_private({"run": run, "sessions": sessions, "targets": targets, "browserTargets": browser_targets,
                  "expected": {}, "browserExpected": {}})
    return {"status": "PASS", "phase": "seed", "targets": len(targets), "browserTargets": 4, "privateSessions": "volume-only"}


def request(path: str, payload: dict, session: str | None, method: str = "POST") -> tuple[int, dict, str]:
    headers = {"Content-Type": "application/json"}
    if session:
        headers["Authorization"] = "Bearer " + session
    req = urllib.request.Request(
        "http://127.0.0.1:8000" + path, data=json.dumps(payload).encode() if method == "POST" else None,
        headers=headers, method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            status, raw = response.status, response.read(262145)
    except urllib.error.HTTPError as response:
        status, raw = response.code, response.read(262145)
    if len(raw) > 262144:
        raise RuntimeError("ADMIN_PROOF_RESPONSE_TOO_LARGE")
    decoded = json.loads(raw)
    if not isinstance(decoded, dict):
        raise RuntimeError("ADMIN_PROOF_RESPONSE_INVALID")
    return status, decoded, hashlib.sha256(raw).hexdigest()


def state(target: dict, *, details: bool = False) -> dict:
    with closing(sqlite3.connect(f"file:{DATABASE}?mode=ro", uri=True)) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("BEGIN")
        user = dict(conn.execute(
            "SELECT id,role,token_balance,plan,plan_started_at,plan_expires_at,plan_next_token_grant_at,plan_monthly_token_grant "
            "FROM users WHERE internal_user_id=?", (target["internal"],),
        ).fetchone())
        selections = [("ledger", "token_ledger", "user_id", target["legacy"]),
                      ("grants", "tariff_token_grants", "internal_user_id", target["internal"]),
                      ("audit", "audit_logs", "target_internal_user_id", target["internal"]),
                      ("commands", "admin_commands", "target_internal_user_id", target["internal"])]
        rows = {name: [dict(row) for row in conn.execute(f"SELECT * FROM {table} WHERE {column}=? ORDER BY id", (value,))]
                for name, table, column, value in selections}
        result = {"user": user, "counts": {name: len(values) for name, values in rows.items()},
                  "rowSha256": {name: hashlib.sha256(json.dumps(values, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
                                for name, values in rows.items()}}
        if details:
            result["rows"] = rows
        return result


def command(target: dict, run: str) -> tuple[str, dict]:
    path = f"/api/admin/users/{target['internal']}/{target['kind']}-v2"
    payload = {"reason": f"controlled {target['kind']} correction", "idempotency_key": f"admin-proof-{run}-{target['kind']}-{target['trial']}"}
    if target["kind"] == "tokens":
        payload["delta"] = 25
    else:
        payload.update(plan="pro", duration_days=35)
    return path, payload


def verified_effect(target: dict, response: dict, payload: dict) -> dict:
    observed = state(target, details=True)
    rows = observed.pop("rows")
    assert observed["counts"] == {"ledger": 1, "grants": int(target["kind"] == "plan"), "audit": 1, "commands": 1}, "ADMIN_PROOF_DUPLICATE_EFFECT"
    assert observed["user"]["id"] == target["legacy"], "ADMIN_PROOF_IDENTITY_CHANGED"
    assert observed["user"]["role"] == "user", "ADMIN_PROOF_ROLE_CHANGED"
    delta = target["delta"] if target["kind"] == "tokens" else target["expectedGrant"]
    assert delta > 0 and observed["user"]["token_balance"] == 50 + delta, "ADMIN_PROOF_BALANCE_MISMATCH"
    ledger, audit, stored = (rows[name][0] for name in ("ledger", "audit", "commands"))
    ledger_meta, audit_after = json.loads(ledger["meta_json"]), json.loads(audit["after_json"])
    assert response["ok"] is True and response["internal_user_id"] == target["internal"], "ADMIN_PROOF_RESPONSE_TARGET_MISMATCH"
    assert stored["command_key"] == payload["idempotency_key"] and stored["actor_internal_user_id"] == target["actor"], "ADMIN_PROOF_COMMAND_BINDING_MISMATCH"
    assert stored["target_internal_user_id"] == target["internal"] and json.loads(stored["response_json"]) == response, "ADMIN_PROOF_STORED_RESPONSE_MISMATCH"
    assert audit["actor_internal_user_id"] == target["actor"] and audit["entity_id"] == target["legacy"], "ADMIN_PROOF_AUDIT_ACTOR_TARGET_MISMATCH"
    assert audit_after["admin_command_id"] == stored["id"] and audit_after["reason"] == payload["reason"].strip(), "ADMIN_PROOF_AUDIT_COMMAND_MISMATCH"
    assert ledger["delta"] == delta, "ADMIN_PROOF_LEDGER_AMOUNT_MISMATCH"
    if target["kind"] == "tokens":
        normalized = {"delta": target["delta"], "reason": payload["reason"].strip()}
        assert payload["delta"] == delta and response["delta"] == delta, "ADMIN_PROOF_TOKEN_REQUEST_MISMATCH"
        assert response["old_balance"] == 50 and response["new_balance"] == 50 + delta, "ADMIN_PROOF_TOKEN_RESULT_MISMATCH"
        assert ledger["id"] == stored["id"] == ledger_meta["admin_command_id"], "ADMIN_PROOF_TOKEN_COMMAND_MISMATCH"
        assert ledger_meta["actor_internal_user_id"] == target["actor"] and ledger_meta["reason"] == normalized["reason"], "ADMIN_PROOF_TOKEN_LEDGER_METADATA_MISMATCH"
        assert json.loads(audit["before_json"])["token_balance"] == 50 and audit_after["token_balance"] == 50 + delta and audit_after["delta"] == delta, "ADMIN_PROOF_TOKEN_AUDIT_AMOUNT_MISMATCH"
        assert ledger["reason"] == "admin_adjust" and audit["action"] == "admin_adjust_tokens", "ADMIN_PROOF_TOKEN_ACTION_MISMATCH"
        assert stored["operation"] == "adjust-tokens-v2", "ADMIN_PROOF_TOKEN_OPERATION_MISMATCH"
    else:
        normalized = {"plan": target["plan"], "duration_days": target["durationDays"], "reason": payload["reason"].strip()}
        activation, user, grant = response["activation"], observed["user"], rows["grants"][0]
        assert payload["plan"] == response["plan"] == activation["plan"] == user["plan"] == target["plan"], "ADMIN_PROOF_PLAN_MISMATCH"
        assert payload.get("duration_days", 30) == target["durationDays"], "ADMIN_PROOF_PLAN_DURATION_MISMATCH"
        assert isinstance(user["plan_started_at"], str) and isinstance(user["plan_expires_at"], str), "ADMIN_PROOF_PLAN_DATES_MISSING"
        started, expires = datetime.fromisoformat(user["plan_started_at"]), datetime.fromisoformat(user["plan_expires_at"])
        assert started.tzinfo and expires.tzinfo and expires - started == timedelta(days=target["durationDays"]), "ADMIN_PROOF_PLAN_DATES_MISMATCH"
        assert activation["plan_started_at"] == user["plan_started_at"] == stored["created_at"], "ADMIN_PROOF_PLAN_START_MISMATCH"
        assert activation["plan_expires_at"] == user["plan_expires_at"], "ADMIN_PROOF_PLAN_EXPIRY_MISMATCH"
        year, month = (started.year + 1, 1) if started.month == 12 else (started.year, started.month + 1)
        next_grant = started.replace(year=year, month=month, day=min(started.day, calendar.monthrange(year, month)[1]))
        expected_next = next_grant.isoformat() if target["durationDays"] > 30 and next_grant < expires else None
        assert user["plan_next_token_grant_at"] == expected_next and user["plan_monthly_token_grant"] == delta, "ADMIN_PROOF_PLAN_NEXT_GRANT_MISMATCH"
        assert activation["monthly_tokens_granted"] == grant["amount"] == delta and grant["plan"] == target["plan"], "ADMIN_PROOF_PLAN_GRANT_AMOUNT_MISMATCH"
        expected_key = f"tariff:admin:{stored['id']}:{user['plan_started_at']}"
        assert grant["grant_key"] == ledger_meta["grant_key"] == expected_key, "ADMIN_PROOF_GRANT_KEY_MISMATCH"
        assert grant["source_id"] == ledger_meta["source_id"] == stored["id"] and grant["source"] == ledger_meta["source"] == "admin", "ADMIN_PROOF_GRANT_COMMAND_MISMATCH"
        assert grant["period_start"] == ledger_meta["period_start"] == user["plan_started_at"], "ADMIN_PROOF_GRANT_PERIOD_MISMATCH"
        assert ledger["reason"] == "tariff_monthly_grant" and audit["action"] == "admin_change_plan", "ADMIN_PROOF_PLAN_ACTION_MISMATCH"
        assert audit_after["plan"] == target["plan"] and audit_after["duration_days"] == target["durationDays"], "ADMIN_PROOF_PLAN_AUDIT_MISMATCH"
        assert stored["operation"] == "activate-plan-v2", "ADMIN_PROOF_PLAN_OPERATION_MISMATCH"
    identity = {"actor": target["actor"], "target": target["internal"], "operation": stored["operation"], "payload": normalized}
    expected_fingerprint = hashlib.sha256(json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    assert stored["request_sha256"] == expected_fingerprint, "ADMIN_PROOF_REQUEST_FINGERPRINT_MISMATCH"
    return observed


def exercise(run: str) -> dict:
    fixture = private(run)
    checks = []
    for target in fixture["targets"]:
        path, payload = command(target, run)
        barrier = Barrier(2)

        def submit():
            barrier.wait(timeout=5)
            return request(path, payload, fixture["sessions"]["admin"])

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(submit) for _ in range(2)]
            results = [future.result(timeout=20) for future in futures]
        assert [result[0] for result in results] == [200, 200], "ADMIN_PROOF_CONCURRENT_HTTP_FAILED"
        assert results[0][1] == results[1][1], "ADMIN_PROOF_REPLAY_RESPONSE_CHANGED"
        assert results[0][2] == results[1][2], "ADMIN_PROOF_REPLAY_RESPONSE_BYTES_CHANGED"
        observed = verified_effect(target, results[0][1], payload)
        fixture["expected"][target["internal"]] = {"response": results[0][1], "responseSha256": results[0][2], "state": observed}
        checks.append({"kind": target["kind"], "trial": target["trial"], "target": target["internal"], "status": "PASS",
                       "httpStatuses": [200, 200], "effects": observed["counts"], "persistedState": observed,
                       "apiBodySha256": results[0][2]})
        if target["trial"] != 0:
            continue
        invalid = {key: value for key, value in payload.items() if key != "idempotency_key"}
        conflicts = {**payload, "delta": 26} if target["kind"] == "tokens" else {**payload, "duration_days": 36}
        cases = [
            (invalid, fixture["sessions"]["admin"], 400),
            ({**payload, "idempotency_key": "short"}, fixture["sessions"]["admin"], 400),
            ({**payload, "reason": " \t "}, fixture["sessions"]["admin"], 400),
            (payload, fixture["sessions"]["user"], 403), (payload, None, 401),
            (conflicts, fixture["sessions"]["admin"], 409),
        ]
        for bad_payload, session, expected in cases:
            actual, _, _ = request(path, bad_payload, session)
            assert actual == expected, "ADMIN_PROOF_NEGATIVE_HTTP_STATUS"
            assert state(target) == observed, "ADMIN_PROOF_NEGATIVE_MUTATED_STATE"
        checks.append({"kind": target["kind"], "negativeStatuses": [item[2] for item in cases], "status": "PASS"})
    fixture["markerSha256"] = hashlib.sha256(MARKER.read_bytes()).hexdigest()
    save_private(fixture)
    return {"status": "PASS", "phase": "exercise", "realHttp": True, "races": 10, "negativeCases": 12, "checks": checks}


def replay(run: str) -> dict:
    fixture = private(run)
    assert len(fixture["expected"]) == 10, "ADMIN_PROOF_EXPECTATIONS_INCOMPLETE"
    checks = []
    for target in fixture["targets"]:
        path, payload = command(target, run)
        status, response, response_digest = request(path, payload, fixture["sessions"]["admin"])
        assert status == 200, "ADMIN_PROOF_RECREATE_SESSION_OR_HTTP_FAILED"
        expected = fixture["expected"][target["internal"]]
        assert response == expected["response"], "ADMIN_PROOF_RECREATE_RESPONSE_CHANGED"
        assert response_digest == expected["responseSha256"], "ADMIN_PROOF_RECREATE_RESPONSE_BYTES_CHANGED"
        observed = verified_effect(target, response, payload)
        assert observed == expected["state"], "ADMIN_PROOF_RECREATE_STATE_CHANGED"
        checks.append({"target": target["internal"], "kind": target["kind"], "status": "PASS",
                       "persistedState": observed, "apiBodySha256": response_digest})
    assert len(fixture["browserExpected"]) == 4, "ADMIN_PROOF_BROWSER_EXPECTATIONS_INCOMPLETE"
    for target in fixture["browserTargets"]:
        expected = fixture["browserExpected"][target["internal"]]
        status, response, response_digest = request(expected["path"], expected["payload"], fixture["sessions"]["admin"])
        assert status == 200 and response == expected["response"], "ADMIN_PROOF_BROWSER_RECREATE_RESPONSE_CHANGED"
        assert response_digest == expected["responseSha256"], "ADMIN_PROOF_BROWSER_RECREATE_BYTES_CHANGED"
        observed = verified_effect(target, response, expected["payload"])
        assert observed == expected["state"], "ADMIN_PROOF_BROWSER_RECREATE_STATE_CHANGED"
        checks.append({"target": target["internal"], "kind": target["kind"], "viewport": target["viewport"], "status": "PASS",
                       "persistedState": observed, "apiBodySha256": response_digest})
    assert hashlib.sha256(MARKER.read_bytes()).hexdigest() == fixture["markerSha256"], "ADMIN_PROOF_MEDIA_MARKER_CHANGED"
    with closing(sqlite3.connect(f"file:{DATABASE}?mode=ro", uri=True)) as conn:
        assert conn.execute("PRAGMA integrity_check").fetchall() == [("ok",)], "ADMIN_PROOF_DATABASE_INTEGRITY_FAILED"
    return {"status": "PASS", "phase": "replay", "realHttp": True, "replayedCommands": 10, "browserReplays": 4,
            "sameSession": True, "sameLedgerAuditPlanDates": True, "sqliteIntegrity": "ok", "mediaSha256": fixture["markerSha256"], "checks": checks}


def bridge(run: str, raw: str) -> dict:
    """Only the finite CRM reads/bootstrap and owned entitlement routes are reachable."""
    if len(raw) > 8192:
        raise RuntimeError("ADMIN_PROOF_BRIDGE_INPUT_LIMIT")
    message, fixture = json.loads(raw), private(run)
    path, method, payload = message.get("path", ""), message.get("method", ""), message.get("payload", {})
    url = urllib.parse.urlsplit(path)
    if url.scheme or url.netloc or url.fragment or len(path) > 1024 or not isinstance(payload, dict):
        raise RuntimeError("ADMIN_PROOF_BRIDGE_SCOPE_REJECTED")
    targets = {item["internal"]: item for item in fixture["browserTargets"]}
    target = next((item for internal, item in targets.items()
                   if url.path == f"/api/admin/users/{internal}/{item['kind']}-v2"), None)
    read_paths = {"/api/me-v2", "/api/admin/summary", "/api/admin/dashboard-v2",
                  "/api/admin/users-analytics-v2", "/api/admin/diagnostics-v2"}
    read_paths.update(f"/api/admin/users/{internal}/analytics-v2" for internal in targets)
    allowed = (method == "GET" and url.path in read_paths
               or method == "POST" and url.path == "/api/auth/bootstrap-v2" and not url.query
               or method == "POST" and target is not None and not url.query)
    if not allowed:
        raise RuntimeError("ADMIN_PROOF_BRIDGE_SCOPE_REJECTED")
    status, response, response_digest = request(path, payload, fixture["sessions"]["admin"], method)
    observed = None
    if target is not None and status == 200:
        observed = verified_effect(target, response, payload)
        entry = {"path": path, "payload": payload, "response": response, "responseSha256": response_digest, "state": observed}
        previous = fixture["browserExpected"].get(target["internal"])
        if previous is not None:
            assert previous == entry, "ADMIN_PROOF_BROWSER_DUPLICATE_COMMAND_OR_RESPONSE"
        fixture["browserExpected"][target["internal"]] = entry
        save_private(fixture)
    return {"status": "PASS", "phase": "bridge", "httpStatus": status, "body": response,
            "bodySha256": response_digest, "ownedState": observed}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("seed", "exercise", "replay", "bridge"))
    parser.add_argument("--request-json", default="")
    args = parser.parse_args()
    run = admit()
    result = bridge(run, args.request_json) if args.phase == "bridge" else {"seed": seed, "exercise": exercise, "replay": replay}[args.phase](run)
    print(PREFIX + json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
