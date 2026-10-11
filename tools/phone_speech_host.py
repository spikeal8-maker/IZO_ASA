"""Opt-in private Windows speech helper. Starting it needs an owned runtime scope."""
from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.integrations.phone_speech_http import (  # noqa: E402
    MAX_AUDIO_BYTES, MAX_REQUEST_BYTES, SpeechHttpError, authorized, private_host,
    read_token_file, valid_input, validate_wave,
)
from backend.app.api.routers.phone_audio import _synthesize_windows_speech  # noqa: E402


class SpeechServer(ThreadingHTTPServer):
    daemon_threads = False
    block_on_close = True
    request_queue_size = 4

    def __init__(self, address, token: str, synthesize, work_root: Path):
        self.token, self.synthesize, self.work_root = token, synthesize, work_root
        self.slots = threading.BoundedSemaphore(4)
        self.render_slots = threading.BoundedSemaphore(2)
        super().__init__(address, SpeechHandler)

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            try:
                request.settimeout(1)
                request.sendall(b"HTTP/1.0 503 Service Unavailable\r\nContent-Length: 0\r\n\r\n")
            except OSError:
                pass
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
        # Default socketserver tracebacks can include sensitive operation state.
        pass


class SpeechHandler(BaseHTTPRequestHandler):
    def setup(self):
        self.request.settimeout(3)
        super().setup()
        self.input_lock = threading.Lock()
        self.input_active = True
        self.input_deadline = time.monotonic() + 3
        self.input_timer = threading.Timer(3, self.expire_input)
        self.input_timer.daemon = True
        self.input_timer.start()

    def expire_input(self):
        with self.input_lock:
            if self.input_active:
                self.input_active = False
                try:
                    self.request.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

    def finish_input(self):
        with self.input_lock:
            accepted = self.input_active and time.monotonic() < self.input_deadline
            self.input_active = False
        self.input_timer.cancel()
        self.input_timer.join()
        return accepted

    def finish(self):
        self.finish_input()
        super().finish()

    def log_message(self, *_):
        pass

    def reply(self, status: int, content: bytes = b"", content_type="application/json"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(content)

    def do_POST(self):
        if self.path != "/v1/speech":
            self.reply(404)
            return
        if not authorized(self.headers.get("Authorization", ""), self.server.token):
            self.reply(401)
            return
        try:
            if len(self.headers.get_all("Content-Length", [])) != 1:
                self.reply(400)
                return
            size = int(self.headers.get("Content-Length", "0"))
            if (not 0 < size <= MAX_REQUEST_BYTES or self.headers.get("Transfer-Encoding")
                    or self.headers.get_content_type() != "application/json"):
                self.reply(400)
                return
            body = json.loads(self.rfile.read(size))
            if not valid_input(body):
                self.reply(400)
                return
        except (ValueError, OSError):
            self.reply(400)
            return
        # An absolute deadline bounds slow headers and bodies before the longer
        # existing Windows synthesis timeout. Socket inactivity alone does not.
        if not self.finish_input():
            return
        if not self.server.render_slots.acquire(blocking=False):
            self.reply(503)
            return
        try:
            with tempfile.TemporaryDirectory(prefix="izo-speech-", dir=self.server.work_root) as directory:
                output = Path(directory) / "speech.wav"
                self.server.synthesize(body["text"], body["voice"], body["rate"], str(output))
                with output.open("rb") as stream:
                    content = stream.read(MAX_AUDIO_BYTES + 1)
                validate_wave(content)
            self.reply(200, content, "audio/wav")
        except Exception:
            self.reply(503)
        finally:
            self.server.render_slots.release()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=49231)
    parser.add_argument("--token-file", type=Path, required=True)
    parser.add_argument("--work-root", type=Path, required=True)
    args = parser.parse_args()
    if (os.name != "nt" or not private_host(args.bind)
            or args.bind == "host.docker.internal" or not 20000 <= args.port <= 65535):
        print("SPEECH_HOST_CONFIG_INVALID")
        return 1
    try:
        token = read_token_file(str(args.token_file))
        args.work_root.mkdir(parents=True, exist_ok=True)
        with SpeechServer((args.bind, args.port), token, _synthesize_windows_speech, args.work_root) as server:
            print("SPEECH_HOST_LISTENING", flush=True)
            try:
                server.serve_forever(poll_interval=.2)
            except KeyboardInterrupt:
                pass
        return 0
    except (OSError, SpeechHttpError):
        print("SPEECH_HOST_START_FAILED")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
