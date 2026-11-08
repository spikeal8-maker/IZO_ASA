"""Closed loopback transport to one TLS origin; never a general HTTP proxy."""
from __future__ import annotations

import http.client
import http.server
import io
import ipaddress
import json
import os
import re
import socket
import ssl
import threading
import time
from urllib.parse import parse_qsl, urlsplit

HOST = "openrouter.ai"
PORT = 18189
PROFILE = "closed-proxy-v1"
MAX_IPS = 8
MAX_HEADERS = 16384
MAX_REQUEST = 24 * 1024 * 1024
MAX_RESPONSE = 32 * 1024 * 1024
IDLE_SECONDS, TOTAL_SECONDS, CONNECT_SECONDS = 30, 300, 5
MODEL = r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}"
ENDPOINT = re.compile(r"/api/v1/images/models/" + MODEL + "/" + MODEL + r"/endpoints")
QUERIES = {(), (("output_modalities", "text"),),
           (("input_modalities", "audio"), ("output_modalities", "text"))}
GET_PATHS = {"/api/v1/key", "/api/v1/credits", "/api/v1/images/models", "/api/v1/videos/models"}
POST_PATHS = {"/api/v1/chat/completions", "/api/v1/images"}
BEARER = re.compile(r"Bearer [A-Za-z0-9._~+/-]{1,2048}={0,2}")


class PolicyError(ValueError):
    """Fixed diagnostic code only; request/key/provider text is never included."""


class DeadlineReader(io.RawIOBase):
    """Reapply the remaining absolute budget before each real socket read."""

    def __init__(self, stream, connection):
        self.stream, self.connection = stream, connection

    def readable(self):
        return True

    def readinto(self, buffer):
        self.connection.remaining_timeout()
        return self.stream.readinto(buffer)

    def close(self):
        try:
            self.stream.close()
        finally:
            super().close()


class DeadlineSocket:
    """One wall deadline also covers buffered header/chunk parsers and writes."""

    def __init__(self, connection, deadline):
        self.connection, self.deadline = connection, deadline

    def __getattr__(self, name):
        return getattr(self.connection, name)

    def remaining_timeout(self):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError()
        self.connection.settimeout(min(IDLE_SECONDS, remaining))

    def makefile(self, mode="rb", buffering=-1):
        if mode != "rb":
            raise ValueError("OPENROUTER_SOCKET_MODE_INVALID")
        # Keep the real SocketIO reference, so HTTPConnection.close() cannot
        # close a response's fd before its file reader has been consumed.
        raw = DeadlineReader(self.connection.makefile("rb", buffering=0), self)
        return raw if buffering == 0 else io.BufferedReader(raw, io.DEFAULT_BUFFER_SIZE if buffering < 0 else buffering)

    def sendall(self, data, flags=0):
        view = memoryview(data)
        while view:
            self.remaining_timeout()
            count = self.connection.send(view, flags)
            if count <= 0:
                raise OSError("OPENROUTER_SOCKET_WRITE_FAILED")
            view = view[count:]


def public_ipv4s(value):
    parts = value.split(",") if type(value) is str else []
    try:
        addresses = [ipaddress.IPv4Address(part) for part in parts]
        if not 1 <= len(addresses) <= MAX_IPS or len(set(addresses)) != len(addresses):
            raise ValueError()
        if any(not a.is_global or a.is_multicast or a.is_reserved or a.is_unspecified
               or a in ipaddress.IPv4Network("192.0.0.0/24") for a in addresses):
            raise ValueError()
        canonical = [str(a) for a in sorted(addresses)]
        if parts != canonical:
            raise ValueError()
        return tuple(canonical)
    except (ValueError, TypeError):
        raise PolicyError("OPENROUTER_IPV4_SET_INVALID") from None


def allowed_target(method, target):
    if type(target) is not str or len(target) > 1024 or not target.isascii():
        return False
    if any(ord(c) <= 32 or ord(c) == 127 for c in target) or any(c in target for c in "%\\#"):
        return False
    try:
        url = urlsplit(target)
        if url.scheme or url.netloc or url.fragment or not target.startswith("/") or "//" in url.path:
            return False
        if method == "GET" and url.path == "/api/v1/models":
            query = tuple(sorted(parse_qsl(url.query, keep_blank_values=True, strict_parsing=True)))
            return query in QUERIES and (not url.query or "?" in target)
        if url.query or "?" in target:
            return False
        return bool((method == "GET" and (url.path in GET_PATHS or ENDPOINT.fullmatch(url.path)))
                    or (method == "POST" and url.path in POST_PATHS))
    except ValueError:
        return False


def request_policy(method, target, headers):
    if not allowed_target(method, target):
        raise PolicyError("OPENROUTER_ROUTE_DENIED")
    pairs = list(headers.items())
    if len(pairs) > 48 or sum(len(k) + len(v) + 4 for k, v in pairs) > MAX_HEADERS:
        raise PolicyError("OPENROUTER_HEADERS_INVALID")
    values = {}
    for name, value in pairs:
        name = name.lower()
        if name in values or not re.fullmatch(r"[a-z0-9!#$%&'*+.^_`|~-]+", name):
            raise PolicyError("OPENROUTER_HEADERS_INVALID")
        if any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise PolicyError("OPENROUTER_HEADERS_INVALID")
        values[name] = value
    if values.get("host") != "127.0.0.1:" + str(PORT):
        raise PolicyError("OPENROUTER_HOST_DENIED")
    if any(k in values for k in ("transfer-encoding", "expect", "upgrade", "proxy-authorization",
                                 "proxy-connection", "te", "trailer")):
        raise PolicyError("OPENROUTER_FRAMING_INVALID")
    if values.get("connection", "close").lower() not in {"close", "keep-alive"}:
        raise PolicyError("OPENROUTER_FRAMING_INVALID")
    authorization = values.get("authorization", "")
    if not BEARER.fullmatch(authorization):
        raise PolicyError("OPENROUTER_AUTH_INVALID")
    raw_length = values.get("content-length", "0")
    if not re.fullmatch(r"0|[1-9][0-9]{0,8}", raw_length):
        raise PolicyError("OPENROUTER_FRAMING_INVALID")
    length = int(raw_length)
    if length > MAX_REQUEST or (method == "GET" and length != 0):
        raise PolicyError("OPENROUTER_BODY_INVALID")
    if method == "POST" and (length == 0 or values.get("content-type", "").lower()
                            not in {"application/json", "application/json; charset=utf-8"}):
        raise PolicyError("OPENROUTER_BODY_INVALID")
    # Never forward client Host, proxy/hop headers, cookies, environment settings,
    # arbitrary reference URLs, or content encodings to the fixed upstream.
    accept = values.get("accept", "application/json")
    if accept not in {"*/*", "application/json", "text/event-stream"}:
        raise PolicyError("OPENROUTER_HEADERS_INVALID")
    return length, {"Authorization": authorization, "Accept": accept,
                    "Content-Type": "application/json", "Accept-Encoding": "identity",
                    "Host": HOST, "Connection": "close"}


def tls_context():
    context = ssl.create_default_context()
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.set_alpn_protocols(["http/1.1"])
    return context


def dial(address, context, timeout, *, deadline=None):
    # A literal AF_INET socket avoids runtime DNS, proxy environment variables,
    # IPv6 and implicit hostname fallback in high-level HTTP clients.
    raw = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    budget = min(time.monotonic() + timeout, deadline if deadline is not None else float("inf"))
    try:
        remaining = budget - time.monotonic()
        if remaining <= 0:
            raise TimeoutError()
        raw.settimeout(remaining)
        raw.connect((address, 443))
        remaining = budget - time.monotonic()
        if remaining <= 0:
            raise TimeoutError()
        raw.settimeout(remaining)
        return context.wrap_socket(raw, server_hostname=HOST)
    except BaseException:
        raw.close()
        raise


def connect_upstream(addresses, context, *, deadline, connector=None):
    for address in addresses:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        try:
            timeout = min(CONNECT_SECONDS, remaining)
            connected = (dial(address, context, timeout, deadline=deadline) if connector is None
                         else connector(address, context, timeout))
            sock = DeadlineSocket(connected, deadline)
        except (OSError, ssl.SSLError):
            continue
        connection = http.client.HTTPConnection(HOST, 443, timeout=IDLE_SECONDS)
        connection.sock = sock
        return connection, sock
    raise PolicyError("OPENROUTER_TLS_CONNECT_FAILED")


def response_policy(response):
    if not 200 <= response.status < 300:
        raise PolicyError("OPENROUTER_UPSTREAM_REJECTED")
    lengths, encodings = [], []
    for name, value in response.getheaders():
        if name.lower() == "content-length":
            lengths.append(value)
        if name.lower() == "transfer-encoding":
            encodings.append(value.lower())
    if len(lengths) > 1 or len(encodings) > 1 or (lengths and encodings):
        raise PolicyError("OPENROUTER_UPSTREAM_FRAMING_INVALID")
    if not lengths and not encodings:
        raise PolicyError("OPENROUTER_UPSTREAM_FRAMING_REQUIRED")
    if encodings and encodings != ["chunked"]:
        raise PolicyError("OPENROUTER_UPSTREAM_FRAMING_INVALID")
    length = None
    if lengths:
        if not re.fullmatch(r"0|[1-9][0-9]{0,9}", lengths[0]):
            raise PolicyError("OPENROUTER_UPSTREAM_FRAMING_INVALID")
        length = int(lengths[0])
        if length > MAX_RESPONSE:
            raise PolicyError("OPENROUTER_RESPONSE_TOO_LARGE")
    content_type = response.getheader("Content-Type", "").split(";", 1)[0].strip().lower()
    if content_type not in {"application/json", "text/event-stream"}:
        raise PolicyError("OPENROUTER_CONTENT_TYPE_INVALID")
    if response.getheader("Content-Encoding", "identity").lower() != "identity":
        raise PolicyError("OPENROUTER_CONTENT_ENCODING_INVALID")
    return content_type, length


class HeaderReader:
    def __init__(self, stream):
        self.stream, self.remaining = stream, MAX_HEADERS

    def readline(self, size=-1):
        line = self.stream.readline(min(8193, self.remaining + 1))
        self.remaining -= len(line)
        if self.remaining < 0 or len(line) > 8192:
            raise http.client.LineTooLong("header")
        return line


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version, sys_version = "IZOOpenRouter", ""

    def setup(self):
        self.request = DeadlineSocket(self.request, time.monotonic() + TOTAL_SECONDS)
        super().setup()

    def log_message(self, *args):
        pass

    def parse_request(self):
        if len(self.raw_requestline) > 4096:
            self.request_version = "HTTP/1.1"
            self.close_connection = True
            self.send_error(414)
            return False
        stream = self.rfile
        self.rfile = HeaderReader(stream)
        try:
            return super().parse_request()
        finally:
            self.rfile = stream

    def handle_expect_100(self):
        self.send_error(417)
        return False

    def send_error(self, code, message=None, explain=None):
        self.reply(code, {"error": {"code": "OPENROUTER_REQUEST_REJECTED"}})

    def reply(self, status, payload):
        body = json.dumps(payload, separators=(",", ":")).encode("ascii")
        self.close_connection = True
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def budget(self, deadline):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError()
        return min(IDLE_SECONDS, remaining)

    def read_body(self, length, deadline):
        chunks = []
        while length:
            self.connection.settimeout(self.budget(deadline))
            part = self.rfile.read1(min(length, 65536))
            if not part:
                raise PolicyError("OPENROUTER_BODY_INCOMPLETE")
            chunks.append(part)
            length -= len(part)
        return b"".join(chunks)

    def forward(self):
        self.close_connection = True
        if self.command == "GET" and self.path == "/healthz":
            self.reply(200, {"ok": True, "profile": PROFILE, "address_count": len(self.server.addresses)})
            return
        connection, started, admitted, phase = None, False, False, "request"
        deadline = self.connection.deadline
        try:
            length, headers = request_policy(self.command, self.path, self.headers)
            if length:
                admitted = self.server.body_slots.acquire(blocking=False)
                if not admitted:
                    self.reply(503, {"error": {"code": "OPENROUTER_PROXY_BUSY"}})
                    return
            body = self.read_body(length, deadline)
            phase = "upstream"
            connection, sock = connect_upstream(self.server.addresses, self.server.tls, deadline=deadline)
            sock.settimeout(self.budget(deadline))
            # Failover is over. Once any HTTP bytes can be sent, neither POST nor
            # GET is retried, including ambiguous partial-send and read failures.
            connection.request(self.command, self.path, body=body or None, headers=headers)
            response = connection.getresponse()
            if not 200 <= response.status < 300:
                self.reply(response.status if 400 <= response.status <= 599 else 502,
                           {"error": {"code": "OPENROUTER_UPSTREAM_REJECTED"}})
                return
            content_type, expected_length = response_policy(response)
            self.send_response(response.status)
            self.send_header("Content-Type", content_type)
            self.send_header("Transfer-Encoding", "chunked")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.end_headers()
            started, total = True, 0
            while True:
                sock.settimeout(self.budget(deadline))
                part = response.read1(65536)
                if not part:
                    break
                total += len(part)
                if total > MAX_RESPONSE:
                    raise PolicyError("OPENROUTER_RESPONSE_TOO_LARGE")
                self.connection.settimeout(self.budget(deadline))
                self.wfile.write(f"{len(part):x}\r\n".encode("ascii") + part + b"\r\n")
                self.wfile.flush()
                if expected_length is not None and total == expected_length:
                    break
            if expected_length is not None and total != expected_length:
                raise PolicyError("OPENROUTER_RESPONSE_INCOMPLETE")
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()
        except PolicyError as error:
            if not started:
                self.reply(400 if phase == "request" else 502, {"error": {"code": str(error)}})
        except (OSError, ValueError, http.client.HTTPException):
            if not started:
                self.reply(502, {"error": {"code": "OPENROUTER_TRANSPORT_UNAVAILABLE"}})
            # No terminating chunk on partial upstream failure: the client sees
            # an incomplete response instead of a successful truncated stream.
        finally:
            if connection is not None:
                connection.close()
            if admitted:
                self.server.body_slots.release()

    do_GET = do_POST = forward


class Server(http.server.ThreadingHTTPServer):
    daemon_threads, request_queue_size = True, 16

    def __init__(self, addresses):
        self.addresses, self.tls = addresses, tls_context()
        self.slots = threading.BoundedSemaphore(16)
        self.body_slots = threading.BoundedSemaphore(2)
        super().__init__(("127.0.0.1", PORT), Handler)

    def get_request(self):
        request, address = super().get_request()
        request.settimeout(IDLE_SECONDS)
        return request, address

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()

    def handle_error(self, request, client_address):
        pass


def main():
    if os.geteuid() != 10003 or os.environ.get("IZO_OPENROUTER_PROFILE") != PROFILE:
        raise PolicyError("OPENROUTER_PROXY_IDENTITY_INVALID")
    addresses = public_ipv4s(os.environ.get("IZO_OPENROUTER_IPV4S", ""))
    with Server(addresses) as server:
        print("OPENROUTER_PROXY_READY profile=" + PROFILE, flush=True)
        server.serve_forever(poll_interval=0.5)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError):
        raise SystemExit("OPENROUTER_PROXY_START_FAILED") from None
