"""Closed route, TLS dial, framing and no-retry behavior with local fake upstreams."""
from __future__ import annotations

import http.client
import http.server
import importlib.util
import io
import json
import socket
import ssl
import threading
import time
from contextlib import contextmanager
from email.message import Message
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("openrouter_proxy_test", ROOT / "ops/docker/dev/openrouter_https_proxy.py")
proxy = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(proxy)
TOKEN = "Bearer synthetic-inference-key"


def headers(**changes):
    values = {"Host": "127.0.0.1:18189", "Authorization": TOKEN, "Accept": "application/json"} | changes
    message = Message()
    for name, value in values.items():
        message[name] = value
    return message


@pytest.mark.parametrize("method,target", [
    ("GET", "/api/v1/key"), ("GET", "/api/v1/credits"), ("GET", "/api/v1/models"),
    ("GET", "/api/v1/models?output_modalities=text"),
    ("GET", "/api/v1/models?input_modalities=audio&output_modalities=text"),
    ("GET", "/api/v1/models?output_modalities=text&input_modalities=audio"),
    ("GET", "/api/v1/images/models"), ("GET", "/api/v1/videos/models"),
    ("GET", "/api/v1/images/models/black-forest-labs/flux.2-klein-4b/endpoints"),
    ("POST", "/api/v1/chat/completions"), ("POST", "/api/v1/images"),
])
def test_exact_product_routes_are_admitted(method, target):
    assert proxy.allowed_target(method, target)


@pytest.mark.parametrize("method,target", [
    ("CONNECT", "openrouter.ai:443"), ("POST", "/api/v1/key"), ("GET", "/api/v1/keys"),
    ("POST", "/api/v1/credits"), ("POST", "/api/v1/videos"), ("GET", "/api/v1/videos/id"),
    ("GET", "https://openrouter.ai/api/v1/key"), ("GET", "//openrouter.ai/api/v1/key"),
    ("GET", "/api/v1/%6bey"), ("GET", "/api/v1/key?"), ("GET", "/api/v1/key?token=x"),
    ("GET", "/api/v1/key#x"), ("GET", "/api/v1/../key"), ("GET", "/api/v1\\key"),
    ("GET", "/api/v1/models?output_modalities=text&output_modalities=text"),
    ("GET", "/api/v1/models?output_modalities=image"), ("GET", "/api/v1/models?url=https://evil.invalid"),
    ("GET", "/api/v1/images/models/../key/endpoints"),
    ("GET", "/api/v1/images/models/author/model/endpoints?url=x"), ("GET", "/api/v1/key\r\nX: y"),
])
def test_ssrf_management_video_and_noncanonical_routes_are_denied(method, target):
    assert not proxy.allowed_target(method, target)


@pytest.mark.parametrize("change", [
    {"Host": "openrouter.ai"}, {"Content-Length": "1"}, {"Content-Length": "+0"},
    {"Content-Length": "00"}, {"Transfer-Encoding": "chunked"}, {"Expect": "100-continue"},
    {"Connection": "authorization"}, {"Upgrade": "websocket"}, {"Proxy-Authorization": "x"},
    {"Authorization": "Bearer synthetic\nsecret"}, {"Authorization": "Basic x"},
])
def test_ambiguous_request_framing_never_reaches_upstream(change):
    with pytest.raises(proxy.PolicyError):
        proxy.request_policy("GET", "/api/v1/key", headers(**change))


def test_duplicate_headers_fail_and_arbitrary_metadata_is_not_forwarded():
    duplicate = headers()
    duplicate["Authorization"] = TOKEN
    with pytest.raises(proxy.PolicyError):
        proxy.request_policy("GET", "/api/v1/key", duplicate)
    _, forwarded = proxy.request_policy("GET", "/api/v1/key", headers(**{
        "Cookie": "unrelated-private-cookie", "HTTP-Referer": "https://evil.invalid",
        "X-Title": "private-name", "Accept-Encoding": "gzip"}))
    assert forwarded["Host"] == "openrouter.ai" and forwarded["Accept-Encoding"] == "identity"
    assert set(forwarded) == {"Authorization", "Accept", "Content-Type", "Accept-Encoding", "Host", "Connection"}


def test_tls_dial_is_literal_ipv4_with_fixed_sni_and_certificate_verification(monkeypatch):
    events = []
    class Socket:
        def settimeout(self, value): events.append(("timeout", value))
        def connect(self, value): events.append(("connect", value))
        def close(self): events.append(("close",))
    raw = Socket()
    def socket_factory(family, kind):
        assert family == proxy.socket.AF_INET and kind == proxy.socket.SOCK_STREAM
        return raw
    context = proxy.tls_context()
    assert context.check_hostname and context.verify_mode == ssl.CERT_REQUIRED
    def wrap(self, sock, server_hostname):
        assert self is context and sock is raw and server_hostname == "openrouter.ai"
        return raw
    monkeypatch.setattr(proxy.socket, "socket", socket_factory)
    monkeypatch.setattr(ssl.SSLContext, "wrap_socket", wrap)
    monkeypatch.setattr(proxy.socket, "getaddrinfo", lambda *a, **k: pytest.fail("runtime DNS"))
    assert proxy.dial("8.8.8.8", context, 2) is raw
    assert events[1] == ("connect", ("8.8.8.8", 443))
    assert events[0][0] == events[2][0] == "timeout" and 0 < events[2][1] <= events[0][1] <= 2


class MemorySocket:
    def __init__(self, raw=b""):
        self.raw = raw
    def makefile(self, *args, **kwargs): return io.BytesIO(self.raw)
    def settimeout(self, value): pass
    def close(self): pass


class Upstream:
    def __init__(self, raw, failure=False):
        self.socket, self.calls, self.failure = MemorySocket(raw), [], failure
    def request(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if self.failure:
            raise OSError("synthetic partial send containing private body")
    def getresponse(self):
        response = http.client.HTTPResponse(self.socket)
        response.begin()
        return response
    def close(self): pass


@pytest.fixture
def local_proxy(monkeypatch):
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), proxy.Handler)
    server.addresses, server.tls = ("8.8.8.8", "104.18.2.47"), object()
    server.body_slots = threading.BoundedSemaphore(2)
    server.handle_error = lambda *args: None
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    opened = []
    def call(upstream, *, method="GET", target="/api/v1/key", body=None):
        def connect(*args, **kwargs):
            opened.append(args)
            if callable(upstream):
                return upstream(*args, **kwargs)
            return upstream, upstream.socket
        monkeypatch.setattr(proxy, "connect_upstream", connect)
        client = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
        request_headers = {"Host": "127.0.0.1:18189", "Authorization": TOKEN}
        if body is not None: request_headers["Content-Type"] = "application/json"
        try:
            client.request(method, target, body=body, headers=request_headers)
            response = client.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            client.close()
    call.port = server.server_port
    yield call, opened
    server.shutdown()
    server.server_close()
    thread.join(3)
    assert not thread.is_alive()


@pytest.mark.parametrize("content_type,body", [
    ("application/json", b'{"data":{"is_valid":true}}'),
    ("text/event-stream", b': comment\n\ndata: {"ok":true}\n\ndata: [DONE]\n\n'),
])
def test_real_local_http_preserves_json_and_sse_without_redirect_or_body_transform(local_proxy, content_type, body):
    upstream = Upstream(b"HTTP/1.1 200 OK\r\nContent-Type: " + content_type.encode() +
        b"\r\nContent-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body)
    call, opened = local_proxy
    status, observed_headers, result = call(upstream)
    assert status == 200 and result == body and observed_headers["Content-Type"] == content_type
    assert len(opened) == len(upstream.calls) == 1


@pytest.mark.parametrize("status", [302, 401, 403, 429, 500])
def test_provider_errors_are_static_and_redirects_never_followed(local_proxy, status):
    upstream = Upstream(f"HTTP/1.1 {status} Rejected\r\nLocation: https://evil.invalid\r\n".encode() +
        b"Content-Type: application/json\r\nContent-Length: 26\r\n\r\nprivate-echoed-secret-value")
    call, opened = local_proxy
    code, observed_headers, body = call(upstream)
    assert code == (502 if status == 302 else status)
    assert body == b'{"error":{"code":"OPENROUTER_UPSTREAM_REJECTED"}}'
    assert "Location" not in observed_headers and len(opened) == 1


def test_tls_failover_stops_before_first_request_bytes():
    calls = []
    connected = MemorySocket()
    def connector(address, context, timeout):
        calls.append(address)
        if len(calls) == 1: raise ssl.SSLError("unverified synthetic endpoint")
        return connected
    connection, sock = proxy.connect_upstream(("8.8.8.8", "104.18.2.47"), object(),
        deadline=time.monotonic() + 20, connector=connector)
    assert calls == ["8.8.8.8", "104.18.2.47"] and sock.connection is connected
    connection.close()


def test_post_partial_send_is_not_retried_and_diagnostic_does_not_echo_body(local_proxy):
    upstream = Upstream(b"", failure=True)
    call, opened = local_proxy
    status, _, body = call(upstream, method="POST", target="/api/v1/chat/completions", body=b'{"model":"synthetic"}')
    assert status == 502 and len(opened) == len(upstream.calls) == 1
    assert b"private" not in body and b"synthetic" not in body


def test_truncated_response_is_an_http_failure_without_retry(local_proxy):
    call, opened = local_proxy
    upstream = Upstream(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 200\r\n\r\n{}")
    with pytest.raises(http.client.IncompleteRead):
        call(upstream)
    assert len(opened) == len(upstream.calls) == 1


@pytest.mark.parametrize("extra", [b"Content-Length: 40000000\r\n", b"Content-Length: 2\r\nContent-Length: 2\r\n",
    b"Content-Length: 2\r\nTransfer-Encoding: chunked\r\n", b"Content-Encoding: gzip\r\n"])
def test_response_bounds_and_ambiguous_framing_fail_before_body(local_proxy, extra):
    call, _ = local_proxy
    status, _, body = call(Upstream(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n" + extra + b"\r\n{}"))
    assert status == 502 and b"OPENROUTER_" in body


@pytest.mark.parametrize("content_type", ["application/json", "text/event-stream"])
def test_close_delimited_eof_is_not_rewritten_as_success(local_proxy, content_type):
    call, opened = local_proxy
    raw = ("HTTP/1.1 200 OK\r\nContent-Type: " + content_type + "\r\nConnection: close\r\n\r\n").encode()
    code, _, body = call(Upstream(raw + b'data: {"unfinished":true}\n\n'))
    assert code == 502 and len(opened) == 1
    assert body == b'{"error":{"code":"OPENROUTER_UPSTREAM_FRAMING_REQUIRED"}}'


@contextmanager
def dripped_upstream(initial, parts, final):
    left, right = socket.socketpair()
    right.settimeout(2)
    stop = threading.Event()
    def run():
        try:
            request = b""
            while b"\r\n\r\n" not in request:
                block = right.recv(4096)
                if not block: return
                request += block
            right.sendall(initial)
            for part in parts:
                right.sendall(part)
                if stop.wait(0.04): return
            right.sendall(final)
        except OSError:
            pass
        finally:
            right.close()
    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    try:
        yield left
    finally:
        stop.set()
        left.close()
        right.close()
        thread.join(3)
        assert not thread.is_alive()


@pytest.mark.parametrize("phase", ["headers", "chunk-size", "trailers"])
def test_slow_drip_upstream_parsers_obey_one_wall_deadline(local_proxy, monkeypatch, phase):
    monkeypatch.setattr(proxy, "TOTAL_SECONDS", 0.25)
    monkeypatch.setattr(proxy, "IDLE_SECONDS", 0.10)
    call, opened = local_proxy
    connect = proxy.connect_upstream
    headers = b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nTransfer-Encoding: chunked\r\n"
    lines = [f"X-Wait-{index}: a\r\n".encode() for index in range(25)]
    if phase == "headers":
        initial, parts, final = headers, lines, b"\r\n2\r\n{}\r\n0\r\n\r\n"
    elif phase == "chunk-size":
        initial, parts, final = headers + b"\r\n", [b"0"] * 25, b"2\r\n{}\r\n0\r\n\r\n"
    else:
        initial, parts, final = headers + b"\r\n2\r\n{}\r\n0\r\n", lines, b"\r\n"
    with dripped_upstream(initial, parts, final) as peer:
        def upstream(addresses, context, *, deadline):
            return connect(addresses, context, deadline=deadline, connector=lambda *args: peer)
        started, completed = time.monotonic(), False
        try:
            call(upstream)
            completed = True
        except (OSError, http.client.HTTPException):
            pass
        elapsed = time.monotonic() - started
    # Each drip is faster than the idle timeout; without the absolute I/O
    # deadline these valid headers/chunk metadata take more than one second.
    assert not completed and elapsed < 0.65 and len(opened) == 1


@pytest.mark.parametrize("phase", ["request-line", "request-headers"])
def test_client_slow_drip_before_forward_cannot_reset_wall_deadline(local_proxy, monkeypatch, phase):
    monkeypatch.setattr(proxy, "TOTAL_SECONDS", 0.25)
    monkeypatch.setattr(proxy, "IDLE_SECONDS", 0.10)
    call, _ = local_proxy
    opened = []
    def unavailable(*args, **kwargs):
        opened.append(True)
        raise proxy.PolicyError("OPENROUTER_TLS_CONNECT_FAILED")
    monkeypatch.setattr(proxy, "connect_upstream", unavailable)
    stop = threading.Event()
    client = socket.create_connection(("127.0.0.1", call.port), timeout=2)
    client.settimeout(2)
    request = b"GET /api/v1/key HTTP/1.1\r\n"
    headers = b"Host: 127.0.0.1:18189\r\nAuthorization: Bearer synthetic-key\r\n"
    if phase == "request-line":
        initial, parts, final = b"", [bytes([value]) for value in request], headers + b"\r\n"
    else:
        initial, parts, final = request + headers, [f"X-Wait-{i}: a\r\n".encode() for i in range(25)], b"\r\n"
    def drip():
        try:
            client.sendall(initial)
            for part in parts:
                client.sendall(part)
                if stop.wait(0.04): return
            client.sendall(final)
        except OSError:
            pass
    thread = threading.Thread(target=drip, daemon=True)
    started = time.monotonic()
    thread.start()
    try:
        try:
            response = client.recv(4096)
        except ConnectionError:
            response = b""
        elapsed = time.monotonic() - started
        assert response == b"" and elapsed < 0.65 and opened == []
    finally:
        stop.set()
        client.close()
        thread.join(3)
        assert not thread.is_alive()
