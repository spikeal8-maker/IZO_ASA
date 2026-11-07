"""Real localhost HTTP contention around the admission service; no live app/provider."""

from __future__ import annotations

import json
import socket
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from http.client import RemoteDisconnected
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import pytest

from app.services.generation_admission import IdempotencyConflict, admit_generation
from test_services_generation_admission import (
    REQUEST, balance, connect, counts, create_job, database,
)


@pytest.fixture
def http_app(database):
    state = SimpleNamespace(
        path=database, barrier=None, calls=0, enqueued=[],
        fail_after_debit=False, drop_response=False, guard=threading.Lock(),
    )

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass

        def send_json(self, status, body):
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):
            if self.path != "/api/generate":
                return self.send_json(404, {"error": "not found"})
            user = {"session=alice-test": "alice", "session=bob-test": "bob"}.get(
                self.headers.get("Cookie")
            )
            if user is None:
                return self.send_json(401, {"error": "authentication required"})
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            try:
                if state.barrier is not None:
                    state.barrier.wait(timeout=5)
                with closing(connect(state.path)) as conn:
                    def create(active):
                        with state.guard:
                            state.calls += 1
                            fail = state.fail_after_debit
                            state.fail_after_debit = False
                        created = create_job(active, user)
                        if fail:
                            raise RuntimeError("injected failure after debit")
                        return created
                    try:
                        result = admit_generation(
                            conn,
                            trusted_user_id=user,
                            idempotency_key=self.headers.get("Idempotency-Key"),
                            normalized_request=payload,
                            create_job_and_accounting=create,
                        )
                        conn.commit()
                    except BaseException:
                        conn.rollback()
                        raise
                    with state.guard:
                        if result.created:
                            state.enqueued.append(result.job_id)
                        drop = state.drop_response
                        state.drop_response = False
                    current = conn.execute(
                        "SELECT status FROM jobs WHERE id = ? AND user_id = ?",
                        (result.job_id, user),
                    ).fetchone()[0]
                if drop:
                    self.connection.shutdown(socket.SHUT_RDWR)
                    self.connection.close()
                    return
                self.send_json(200, {
                    "created": result.created, "jobId": result.job_id,
                    "job": {**result.response, "status": current},
                })
            except IdempotencyConflict:
                self.send_json(409, {"error": "idempotency_conflict"})
            except (RuntimeError, ValueError) as exc:
                self.send_json(500, {"error": str(exc)})

    class Server(ThreadingHTTPServer):
        request_queue_size = 32
        daemon_threads = True

    server = Server(("127.0.0.1", 0), Handler)
    state.url = f"http://127.0.0.1:{server.server_port}/api/generate"
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01})
    thread.start()
    try:
        yield state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        assert not thread.is_alive()


def post(state, *, user="alice", key="same-key", payload=None):
    request = Request(
        state.url, method="POST",
        data=json.dumps(REQUEST if payload is None else payload).encode(),
        headers={
            "Content-Type": "application/json",
            "Idempotency-Key": key,
            "Cookie": f"session={user}-test",
        },
    )
    try:
        with urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read())
    except HTTPError as response:
        with response:
            return response.code, json.loads(response.read())


def concurrently(state, requests):
    state.barrier = threading.Barrier(len(requests))
    try:
        with ThreadPoolExecutor(max_workers=len(requests)) as pool:
            futures = [pool.submit(post, state, **request) for request in requests]
            return [future.result(timeout=15) for future in futures]
    finally:
        state.barrier = None


@pytest.mark.parametrize("contenders", [2, 5, 10])
def test_concurrent_http_admission_charges_and_enqueues_once(http_app, contenders):
    results = concurrently(http_app, [
        {"payload": dict(reversed(list(REQUEST.items()))) if index % 2 else REQUEST}
        for index in range(contenders)
    ])
    assert [status for status, _ in results] == [200] * contenders
    assert sum(body["created"] for _, body in results) == 1
    assert len({body["jobId"] for _, body in results}) == 1
    assert http_app.calls == 1
    assert http_app.enqueued == [results[0][1]["jobId"]]
    with closing(connect(http_app.path)) as conn:
        assert counts(conn) == (1, 1, 1)
        assert balance(conn) == 7


def test_competing_changed_content_returns_409(http_app):
    results = concurrently(http_app, [
        {"payload": REQUEST},
        {"payload": {**REQUEST, "prompt": "Иной запрос"}},
    ])
    assert sorted(status for status, _ in results) == [200, 409]
    assert http_app.calls == len(http_app.enqueued) == 1
    with closing(connect(http_app.path)) as conn:
        assert counts(conn) == (1, 1, 1)
        assert balance(conn) == 7


def test_trusted_sessions_isolate_shared_key_despite_spoofed_body_user(http_app):
    payload = {**REQUEST, "userId": "alice"}
    results = concurrently(http_app, [
        {"user": "alice", "payload": payload},
        {"user": "bob", "payload": payload},
    ])
    assert [status for status, _ in results] == [200, 200]
    assert {body["job"]["userId"] for _, body in results} == {"alice", "bob"}
    assert len({body["jobId"] for _, body in results}) == 2
    assert http_app.calls == len(http_app.enqueued) == 2
    with closing(connect(http_app.path)) as conn:
        assert counts(conn) == (2, 2, 2)
        assert balance(conn, "alice") == balance(conn, "bob") == 7


def test_admission_failure_rolls_back_and_retry_can_create(http_app):
    http_app.fail_after_debit = True
    status, body = post(http_app)
    assert status == 500 and "after debit" in body["error"]
    assert http_app.enqueued == []
    with closing(connect(http_app.path)) as conn:
        assert counts(conn) == (0, 0, 0)
        assert balance(conn) == 10
    status, body = post(http_app)
    assert status == 200 and body["created"]
    assert http_app.calls == 2 and len(http_app.enqueued) == 1
    with closing(connect(http_app.path)) as conn:
        assert counts(conn) == (1, 1, 1)
        assert balance(conn) == 7


def test_committed_admission_survives_lost_http_response(http_app):
    http_app.drop_response = True
    with pytest.raises((RemoteDisconnected, URLError, ConnectionResetError)):
        post(http_app)
    status, replay = post(http_app)
    assert status == 200 and not replay["created"]
    assert http_app.calls == len(http_app.enqueued) == 1
    with closing(connect(http_app.path)) as conn:
        assert counts(conn) == (1, 1, 1)
        assert balance(conn) == 7


def fake_failure_and_refund(path, job_id):
    """Disposable worker policy; production refund wiring is tested by root."""
    with closing(connect(path)) as conn:
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT user_id, -amount FROM ledger WHERE job_id = ? AND kind = 'generation'",
                (job_id,),
            ).fetchone()
            conn.execute("UPDATE jobs SET status = 'failed' WHERE id = ?", (job_id,))
            created = conn.execute(
                "INSERT INTO ledger (user_id, job_id, kind, amount) "
                "VALUES (?, ?, 'refund', ?) ON CONFLICT(job_id, kind) DO NOTHING",
                (row[0], job_id, row[1]),
            ).rowcount
            if created:
                conn.execute(
                    "UPDATE users SET balance = balance + ? WHERE id = ?", (row[1], row[0])
                )
            conn.commit()
        except BaseException:
            conn.rollback()
            raise


@pytest.mark.parametrize("contenders", [2, 5, 10])
def test_failed_refunded_job_is_replayed_without_new_charge_or_dispatch(http_app, contenders):
    status, initial = post(http_app)
    assert status == 200
    fake_failure_and_refund(http_app.path, initial["jobId"])
    fake_failure_and_refund(http_app.path, initial["jobId"])
    results = concurrently(http_app, [{} for _ in range(contenders)])
    assert [status for status, _ in results] == [200] * contenders
    assert all(not body["created"] for _, body in results)
    assert {body["jobId"] for _, body in results} == {initial["jobId"]}
    assert {body["job"]["status"] for _, body in results} == {"failed"}
    assert http_app.calls == len(http_app.enqueued) == 1
    with closing(connect(http_app.path)) as conn:
        assert counts(conn) == (1, 1, 2)
        assert balance(conn) == 10
        assert conn.execute("SELECT COUNT(*) FROM ledger WHERE kind = 'refund'").fetchone()[0] == 1


def test_an_unknown_session_cannot_start_admission(http_app):
    status, _ = post(http_app, user="unknown")
    assert status == 401 and http_app.calls == 0
    with closing(connect(http_app.path)) as conn:
        assert counts(conn) == (0, 0, 0)
