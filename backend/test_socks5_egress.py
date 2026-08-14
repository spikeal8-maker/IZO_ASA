from __future__ import annotations

import socket
import socketserver
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx


class _SocksRecorder:
    destinations: list[tuple[str, int]] = []


def _read_exact(sock: socket.socket, size: int) -> bytes:
    payload = b""
    while len(payload) < size:
        chunk = sock.recv(size - len(payload))
        if not chunk:
            raise ConnectionError("SOCKS client disconnected")
        payload += chunk
    return payload


class _FakeSocksHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        version, method_count = _read_exact(self.request, 2)
        assert version == 5
        _read_exact(self.request, method_count)
        self.request.sendall(b"\x05\x00")

        version, command, _reserved, address_type = _read_exact(self.request, 4)
        assert version == 5
        assert command == 1
        if address_type == 1:
            host = socket.inet_ntoa(_read_exact(self.request, 4))
        elif address_type == 3:
            host_length = _read_exact(self.request, 1)[0]
            host = _read_exact(self.request, host_length).decode("ascii")
        elif address_type == 4:
            host = socket.inet_ntop(socket.AF_INET6, _read_exact(self.request, 16))
        else:
            raise AssertionError(f"Unsupported SOCKS address type: {address_type}")
        port = int.from_bytes(_read_exact(self.request, 2), "big")
        _SocksRecorder.destinations.append((host, port))
        self.request.sendall(b"\x05\x00\x00\x01\x7f\x00\x00\x01\x00\x00")

        request = b""
        while b"\r\n\r\n" not in request:
            request += self.request.recv(4096)
        body = b'{"via":"socks5"}'
        self.request.sendall(
            b"HTTP/1.1 200 OK\r\n"
            b"Content-Type: application/json\r\n"
            + f"Content-Length: {len(body)}\r\n".encode("ascii")
            + b"Connection: close\r\n\r\n"
            + body
        )


class _DirectHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - stdlib callback name
        body = b'{"via":"direct"}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *_args: object) -> None:
        return


def _start(server: socketserver.BaseServer) -> threading.Thread:
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return thread


def test_httpx_uses_explicit_socks5_and_bypasses_loopback(monkeypatch) -> None:
    _SocksRecorder.destinations.clear()
    socks = socketserver.ThreadingTCPServer(("127.0.0.1", 0), _FakeSocksHandler)
    direct = ThreadingHTTPServer(("127.0.0.1", 0), _DirectHandler)
    socks_thread = _start(socks)
    direct_thread = _start(direct)
    try:
        for name in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
            monkeypatch.delenv(name, raising=False)
        monkeypatch.setenv("ALL_PROXY", f"socks5://127.0.0.1:{socks.server_address[1]}")
        monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost,::1")

        with httpx.Client(timeout=3.0, trust_env=True) as client:
            proxied = client.get("http://provider.invalid/probe")
            local = client.get(f"http://127.0.0.1:{direct.server_address[1]}/health")

        assert proxied.json() == {"via": "socks5"}
        assert local.json() == {"via": "direct"}
        assert _SocksRecorder.destinations == [("provider.invalid", 80)]
    finally:
        socks.shutdown()
        direct.shutdown()
        socks.server_close()
        direct.server_close()
        socks_thread.join(timeout=3)
        direct_thread.join(timeout=3)
