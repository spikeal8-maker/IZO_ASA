"""COMFYUI-BRIDGE-D2R2-001: no-egress, strict dual-socket reverse relay.

Backend uses 127.0.0.1:18888 (not host published).
Windows host agent polls 127.0.0.1:48216 -> container 18889, with private token.
No arbitrary HTTP targets, method/path or graph. Never logs request bodies/secrets.
"""
from __future__ import annotations

import base64
import hmac
import json
import os
import queue
import re
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from comfyui_native4b import validate_bridge_route as validate_route

MAX_REQUEST = 48_000
MAX_RESPONSE = 9_000_000
CALLS: dict[str, dict] = {}
LOCK = threading.Lock()
QUEUE: queue.Queue[dict] = queue.Queue(maxsize=16)
LAST_AGENT = 0.0
TOKEN_FILE = os.environ.get("COMFY214_BRIDGE_TOKEN_FILE", "/run/bridge/token")
TOKEN = open(TOKEN_FILE, "rb").read().strip()
if len(TOKEN) < 40:
    raise RuntimeError("BRIDGE_TOKEN_FILE_MISSING_OR_TOO_SHORT")


class Handler(BaseHTTPRequestHandler):
    server_version = "Comfy214CandidateBridge/1.0"

    def log_message(self, *_args):
        return  # No secret-bearing URL/query or body in process logs.

    def send(self, status: int, body: bytes = b"", kind: str = "application/json") -> None:
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if body:
            self.wfile.write(body)

    def read_bounded(self, limit: int) -> bytes | None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return None
        if length < 0 or length > limit:
            return None
        return self.rfile.read(length)

    def authorized(self) -> bool:
        received = self.headers.get("X-Comfy214-Token", "").encode("ascii", "ignore")
        return hmac.compare_digest(received, TOKEN)

    def do_GET(self):
        if self.server.server_port == 18889:
            return self.control_get()
        if self.path == "/bridge/health":
            with LOCK:
                active = len(CALLS)
            value = {"ok": True, "agentRecent": time.monotonic() - LAST_AGENT < 20,
                     "pending": active}
            return self.send(200, json.dumps(value).encode("utf-8"))
        return self.forward("GET", b"")

    def do_POST(self):
        raw = self.read_bounded((MAX_RESPONSE * 4 // 3 + 5000) if self.server.server_port == 18889 else MAX_REQUEST)
        if raw is None:
            return self.send(413)
        if self.server.server_port == 18889:
            return self.control_complete(raw)
        return self.forward("POST", raw)

    def control_get(self):
        global LAST_AGENT
        if not self.authorized():
            return self.send(403)
        if self.path != "/bridge/poll":
            return self.send(404)
        LAST_AGENT = time.monotonic()
        try:
            item = QUEUE.get(timeout=10)
        except queue.Empty:
            return self.send(204)
        value = {"id": item["id"], "method": item["method"],
                 "path": item["path"],
                 "body_b64": base64.b64encode(item["body"]).decode("ascii")}
        return self.send(200, json.dumps(value, separators=(",", ":")).encode("utf-8"))

    def control_complete(self, raw: bytes):
        if not self.authorized():
            return self.send(403)
        path = re.fullmatch(r"/bridge/complete/([0-9a-f]{32})", self.path)
        if not path:
            return self.send(404)
        try:
            item = json.loads(raw)
            status = item["status"]
            body = base64.b64decode(item["body_b64"], validate=True)
            if (type(status) is not int or not 200 <= status <= 599
                    or len(body) > MAX_RESPONSE):
                return self.send(422)
        except (ValueError, KeyError, TypeError):
            return self.send(422)
        with LOCK:
            call = CALLS.get(path.group(1))
            if not call or call["done"]:
                return self.send(409)
            call.update(done=True, status=status, body=body)
            call["event"].set()
        return self.send(200, b'{"ok":true}')

    def forward(self, method: str, body: bytes):
        if not validate_route(method, self.path, body):
            return self.send(403, b'{"detail":"COMFY214_ROUTE_DENIED"}')
        with LOCK:
            if len(CALLS) >= 12:
                return self.send(503, b'{"detail":"COMFY214_BUSY"}')
            ident = uuid.uuid4().hex
            call = {"id": ident, "method": method, "path": self.path,
                    "body": body, "event": threading.Event(), "done": False}
            CALLS[ident] = call
        try:
            QUEUE.put_nowait(call)
        except queue.Full:
            with LOCK:
                CALLS.pop(ident, None)
            return self.send(503, b'{"detail":"COMFY214_QUEUE_FULL"}')
        wait = 100 if self.path == "/prompt" else 65
        success = call["event"].wait(wait)
        with LOCK:
            CALLS.pop(ident, None)
        if not success:
            return self.send(504, b'{"detail":"COMFY214_AGENT_TIMEOUT"}')
        result = call["body"]
        kind = "image/png" if self.path.startswith("/view?") and call["status"] == 200 else "application/json"
        return self.send(call["status"], result, kind)


def main() -> None:
    backend = ThreadingHTTPServer(("127.0.0.1", 18888), Handler)
    agent = ThreadingHTTPServer(("0.0.0.0", 18889), Handler)
    backend.daemon_threads = True
    agent.daemon_threads = True
    print("COMFY214_BRIDGE_BOUND: backend=127.0.0.1:18888, host-control=18889 (published loopback only)", flush=True)
    t = threading.Thread(target=backend.serve_forever, daemon=True)
    t.start()
    agent.serve_forever()


if __name__ == "__main__":
    main()
