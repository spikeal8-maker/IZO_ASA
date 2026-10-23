"""Single-origin CONNECT relay for an isolated OpenRouter-only Docker candidate.

It does not accept absolute-form HTTP URLs, arbitrary CONNECT hosts, admin
commands, or HTTP forwarding. All application contents remain TLS encrypted.
"""
from __future__ import annotations
import ipaddress
import select
import socket
import socketserver

UPSTREAM = "openrouter.ai"
UPSTREAM_PORT = 443
MAX_HEADER = 4096
MAX_CONNECTIONS = 16


def allowed_resolved_addresses(hostname: str) -> list[tuple[str, int]]:
    if hostname != UPSTREAM:
        raise ValueError("UNEXPECTED_HOSTNAME")
    addresses = []
    for family, socktype, protocol, _canonical, sockaddr in socket.getaddrinfo(
        hostname, UPSTREAM_PORT, family=socket.AF_INET, type=socket.SOCK_STREAM,
    ):
        if family != socket.AF_INET or socktype != socket.SOCK_STREAM:
            continue
        address = ipaddress.ip_address(sockaddr[0])
        if address.version == 4 and address.is_global and not (
            address.is_private or address.is_loopback or address.is_multicast
        ):
            addresses.append((str(address), UPSTREAM_PORT))
    if not addresses:
        raise ValueError("NO_PUBLIC_UPSTREAM_ADDRESS")
    return addresses


class ConnectHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        downstream: socket.socket = self.request
        downstream.settimeout(8)
        try:
            buffer = bytearray()
            while b"\r\n\r\n" not in buffer and len(buffer) <= MAX_HEADER:
                received = downstream.recv(1024)
                if not received:
                    return
                buffer.extend(received)
            if len(buffer) > MAX_HEADER or b"\r\n\r\n" not in buffer:
                return
            head, tail = bytes(buffer).split(b"\r\n\r\n", 1)
            lines = head.split(b"\r\n")
            if len(lines) > 32 or any(len(line) > 2048 for line in lines):
                return
            # Connection headers do not carry the OpenRouter credential. They
            # only select the TLS tunnel endpoint. The encrypted body is opaque.
            if lines[0] != b"CONNECT openrouter.ai:443 HTTP/1.1":
                downstream.sendall(b"HTTP/1.1 403 Forbidden\r\nConnection: close\r\nContent-Length: 0\r\n\r\n")
                return
            if tail:
                # Do not allow request smuggling or pre-connection buffered data.
                return
            target = None
            for address, port in allowed_resolved_addresses(UPSTREAM):
                try:
                    target = socket.create_connection((address, port), timeout=8)
                    break
                except OSError:
                    continue
            if target is None:
                downstream.sendall(b"HTTP/1.1 502 Bad Gateway\r\nConnection: close\r\nContent-Length: 0\r\n\r\n")
                return
            with target:
                downstream.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                self.relay(downstream, target)
        except (OSError, ValueError):
            return

    @staticmethod
    def relay(downstream: socket.socket, upstream: socket.socket) -> None:
        downstream.setblocking(False)
        upstream.setblocking(False)
        sockets = (downstream, upstream)
        idle = 0
        while idle < 30:
            try:
                readable, _, errors = select.select(list(sockets), [], list(sockets), 1)
            except (OSError, ValueError):
                break
            if errors:
                break
            if not readable:
                idle += 1
                continue
            idle = 0
            for source in readable:
                try:
                    chunk = source.recv(65536)
                    if not chunk:
                        return
                    target = upstream if source is downstream else downstream
                    target.setblocking(True)
                    target.settimeout(8)
                    target.sendall(chunk)
                    target.setblocking(False)
                except (OSError, ValueError):
                    return


class BoundedTCPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True
    request_queue_size = MAX_CONNECTIONS

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        import threading
        self._limit = threading.BoundedSemaphore(MAX_CONNECTIONS)

    def process_request(self, request, client_address):
        if not self._limit.acquire(blocking=False):
            request.close()
            return
        def serve():
            try:
                self.finish_request(request, client_address)
                self.shutdown_request(request)
            finally:
                self._limit.release()
        import threading
        threading.Thread(target=serve, daemon=True).start()


if __name__ == "__main__":
    with BoundedTCPServer(("0.0.0.0", 3128), ConnectHandler) as server:
        server.serve_forever(poll_interval=0.5)
