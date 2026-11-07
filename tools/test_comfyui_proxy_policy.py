"""Real local fake HTTP tests; no GPU, credentials, external hosts or live data."""
from __future__ import annotations

import contextlib
import concurrent.futures
import copy
import http.client
import importlib.util
import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlencode

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("comfy_bridge", ROOT / "ops/docker/dev/comfyui_proxy.py")
proxy = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(proxy)
NAMESPACE = "izo-unit-1234567890abcdef"
PID = "12345678-1234-1234-1234-123456789abc"
CLIENT = "onenode-backend-job_20261105_070532_cb33f6"
PNG = b"\x89PNG\r\n\x1a\ncontrolled-test-image"


def payload():
    path = ROOT / "ops/comfyui/runtime-contract/one-node-flux-2-klein/workflows/t2i_workflow.json"
    graph = json.loads(path.read_text())
    graph["FK:165"]["inputs"]["unet_name"] = proxy.MODEL
    graph["FK:155"]["inputs"]["clip_name"] = proxy.ENCODER
    return {"prompt": graph, "client_id": CLIENT, "extra_data": {"enable_previews": True}}


@contextlib.contextmanager
def serving(server):
    thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.01), daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown(); server.server_close(); thread.join(2)


class Upstream(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def handle_fake(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        self.server.calls.append((self.command, self.path, dict(self.headers), raw))
        if self.server.delay:
            time.sleep(self.server.delay)
        if self.server.hold_response is not None:
            self.server.response_waiting.set()
            if not self.server.hold_response.wait(5):
                return
        if self.path == "/prompt":
            value = json.loads(raw)
            self.server.history = {PID: {"prompt": [0, PID, value["prompt"],
                {"client_id": value["client_id"]}, ["FK:86"]], "outputs": {"FK:86": {"images": [{
                    "filename": "image_00001_.png", "subfolder": NAMESPACE + "\\" + CLIENT, "type": "output"}]}},
                "status": {"status_str": "success", "completed": True, "messages": [["private", {}]]}}}
            data = {"prompt_id": PID, "number": 0, "node_errors": {}}
        elif self.path.startswith("/history/"):
            data = self.server.history
        elif self.path == "/queue":
            data = {"queue_running": [["foreign private prompt"]], "queue_pending": [["foreign user"]]}
        elif self.path == "/object_info":
            data = {"FluxKleinOneNode": {"private": "hidden"}, "SaveImage": {}, "ForeignNode": {}}
        elif self.path == "/flux_klein/models":
            data = {"diffusion_models": [proxy.MODEL, "foreign9b.safetensors"],
                    "text_encoders": [proxy.ENCODER], "vaes": [proxy.VAE], "loras": ["foreign.safetensors"]}
        elif self.path == "/flux_klein/workflow_t2i":
            data = payload()["prompt"]
        else:
            data = {"private": "secret upstream body"}
        body = PNG if self.path.startswith("/view?") else json.dumps(data).encode()
        if self.server.large:
            body = b"x" * 1024
        try:
            if self.server.drip_response:
                body = b"{" + b" " * 128 + b"}"
                headers = (b"HTTP/1.0 200 OK\r\nContent-Type: application/json\r\nContent-Length: " +
                           str(len(body)).encode() + b"\r\n\r\n")
                if self.server.drip_response == "body":
                    self.connection.sendall(headers)
                    headers = b""
                for value in headers + body:
                    self.connection.sendall(bytes([value]))
                    time.sleep(0.01)
                return
            self.send_response(self.server.status)
            self.send_header("Location", "http://forbidden.invalid/private")
            self.send_header("Set-Cookie", "provider-secret=never-forward")
            self.send_header("Content-Type", "image/png" if self.path.startswith("/view?") else "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except OSError:
            pass  # The timeout case intentionally closes the peer before this reply.

    do_GET = do_POST = handle_fake


@pytest.fixture
def upstream():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
    server.calls, server.history, server.status, server.delay, server.large = [], {}, 200, 0, False
    server.hold_response, server.response_waiting = None, threading.Event()
    server.drip_response = None
    with serving(server):
        yield server


def bridge(upstream, mode="generate-t2i-4b"):
    # Deliberate in-process fixture injection; production configuration rejects loopback.
    policy = proxy.Policy({"host": "127.0.0.1", "port": upstream.server_port, "namespace": NAMESPACE, "mode": mode})
    return proxy.Server(("127.0.0.1", 0), policy)


def request(server, method, path, body=None, headers=None):
    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=2)
    data = json.dumps(body).encode() if isinstance(body, dict) else body
    try:
        connection.request(method, path, body=data,
                           headers={"Host": "127.0.0.1:18188", "Content-Type": "application/json", **(headers or {})})
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        connection.close()


@pytest.mark.parametrize("method,path", [("POST", "/interrupt"), ("POST", "/free"), ("POST", "/queue"),
    ("POST", "/history"), ("GET", "/history"), ("POST", "/upload/image"), ("GET", "/flux_klein/workflow_edit"),
    ("GET", "/%6fbject_info"), ("GET", "//object_info"), ("GET", "/object_info?target=outside"),
    ("GET", "http://outside.invalid/object_info"), ("CONNECT", "outside.invalid:80")])
def test_denied_calls_never_reach_upstream(upstream, method, path):
    with serving(bridge(upstream)) as server:
        assert request(server, method, path, b"{}")[0] >= 400
    assert not upstream.calls


def test_capabilities_only_no_submission_no_foreign_metadata(upstream):
    with serving(bridge(upstream, "capabilities")) as server:
        assert request(server, "POST", "/prompt", payload())[0] == 403
        for path in ("/queue", "/object_info", "/flux_klein/models", "/flux_klein/config"):
            status, headers, body = request(server, "GET", path, headers={"Authorization": "secret", "Cookie": "secret"})
            assert status == 200 and b"foreign" not in body.lower() and b"private" not in body
            assert "Set-Cookie" not in headers and "Location" not in headers
    assert all("Authorization" not in headers and "Cookie" not in headers for _, _, headers, _ in upstream.calls)
    assert all(method == "GET" for method, *_ in upstream.calls)


@pytest.mark.parametrize("change", ["extra-node", "extra-input", "link", "batch", "size", "steps", "model",
    "nan", "huge-number", "front", "prompt-id", "extra-data", "prefix", "client", "duplicate", "numeric-bool"])
def test_unapproved_graph_and_submission_controls_are_denied(upstream, change):
    value = payload(); graph = value["prompt"]
    if change == "extra-node": graph["evil"] = {"class_type": "LoadImage", "inputs": {"image": "private.png"}}
    if change == "extra-input": graph["FK:86"]["inputs"]["path"] = "/outside"
    if change == "link": graph["FK:86"]["inputs"]["images"] = ["evil", 0]
    if change == "batch": graph["FK:170"]["inputs"]["batch_size"] = 2
    if change == "size": graph["FK:170"]["inputs"]["width"] = 2048
    if change == "steps": graph["FK:171"]["inputs"]["steps"] = 40
    if change == "model": graph["FK:165"]["inputs"]["unet_name"] = "foreign9b.safetensors"
    if change == "nan": graph["FK:171"]["inputs"]["cfg"] = float("nan")
    if change == "huge-number": graph["FK:171"]["inputs"]["cfg"] = 10**400
    if change == "front": value["front"] = True
    if change == "prompt-id": value["prompt_id"] = PID
    if change == "extra-data": value["extra_data"]["client_id"] = "foreign"
    if change == "prefix": graph["FK:86"]["inputs"]["filename_prefix"] = "../../outside"
    if change == "client": value["client_id"] = "foreign"
    if change == "numeric-bool": value["extra_data"]["enable_previews"] = 1
    if change == "duplicate": value = json.dumps(value).replace('"steps": 4', '"steps": 4, "steps": 4').encode()
    with serving(bridge(upstream)) as server:
        assert request(server, "POST", "/prompt", value)[0] in {400, 403}
    assert not upstream.calls


def test_own_history_and_media_survive_cold_proxy_restart_without_resubmit(upstream):
    with serving(bridge(upstream)) as server:
        status, _, body = request(server, "POST", "/prompt", payload())
        assert status == 200 and json.loads(body)["prompt_id"] == PID
    saved = json.loads(upstream.calls[0][3])
    assert saved["client_id"] == NAMESPACE + ":" + CLIENT
    assert saved["prompt"]["FK:86"]["inputs"]["filename_prefix"] == NAMESPACE + "/" + CLIENT + "/image"
    assert saved["extra_data"] == {"enable_previews": False}
    with serving(bridge(upstream)) as restarted:
        status, _, body = request(restarted, "GET", "/history/" + PID)
        assert status == 200 and b"private" not in body and b'"prompt"' not in body
        item = json.loads(body)[PID]["outputs"]["FK:86"]["images"][0]
        assert request(restarted, "GET", "/view?" + urlencode(item))[2] == PNG
        upstream.history[PID]["prompt"][3]["client_id"] = "foreign-user"
        assert request(restarted, "GET", "/history/" + PID)[0] == 403
        upstream.history = {}
        assert request(restarted, "GET", "/history/" + PID)[2] == b"{}"
    assert sum(method == "POST" for method, *_ in upstream.calls) == 1


@pytest.mark.parametrize("query", ["filename=private.png&subfolder=foreign&type=output",
    "filename=image_00001_.png&subfolder=" + NAMESPACE + "%2f..%2fforeign&type=output",
    "filename=image_00001_.png&subfolder=" + NAMESPACE + "%252f..&type=output",
    "filename=image_00001_.png&subfolder=" + NAMESPACE + "/" + CLIENT + "&type=input",
    "filename=image_00001_.png&subfolder=" + NAMESPACE + "/" + CLIENT + "&type=output&type=output"])
def test_foreign_or_ambiguous_view_never_forwarded(upstream, query):
    with serving(bridge(upstream)) as server:
        assert request(server, "GET", "/view?" + query)[0] >= 400
    assert not upstream.calls


@pytest.mark.parametrize("change", ["root-id", "tuple-id", "tuple-shape", "namespace", "prefix", "graph", "output-node",
    "output-folder", "output-type", "status", "extra-file"])
def test_history_requires_complete_ownership_and_output_schema(upstream, change):
    with serving(bridge(upstream)) as server:
        assert request(server, "POST", "/prompt", payload())[0] == 200
        row = upstream.history[PID]
        if change == "root-id": upstream.history = {"87654321-1234-1234-1234-123456789abc": row}
        if change == "tuple-id": row["prompt"][1] = "87654321-1234-1234-1234-123456789abc"
        if change == "tuple-shape": row["prompt"] = [0, PID]
        if change == "namespace": row["prompt"][3]["client_id"] = "izo-foreign-123456789:other"
        if change == "prefix": row["prompt"][2]["FK:86"]["inputs"]["filename_prefix"] = "foreign/image"
        if change == "graph": row["prompt"][2]["FK:165"]["class_type"] = "LoadImage"
        if change == "output-node": row["outputs"]["foreign"] = {"images": []}
        if change == "output-folder": row["outputs"]["FK:86"]["images"][0]["subfolder"] = "foreign"
        if change == "output-type": row["outputs"]["FK:86"]["images"][0]["type"] = "input"
        if change == "status": row["status"]["completed"] = "true"
        if change == "extra-file": row["outputs"]["FK:86"]["images"] *= 2
        status, _, body = request(server, "GET", "/history/" + PID)
        assert status == 403 and b"foreign" not in body and b"private" not in body


@pytest.mark.parametrize("headers", ["Content-Length: 2\r\nContent-Length: 2", "Transfer-Encoding: chunked",
    "Content-Length: -2", "Content-Length: 999999", "Expect: 100-continue", "Host: duplicate"])
def test_raw_http_ambiguous_framing_never_forwarded(upstream, headers):
    with serving(bridge(upstream)) as server, socket.create_connection(server.server_address, timeout=2) as client:
        client.sendall(("POST /prompt HTTP/1.1\r\nHost: 127.0.0.1:18188\r\nContent-Type: application/json\r\n" +
                        headers + "\r\n\r\n{}").encode())
        assert int(client.recv(4096).split()[1]) >= 400
    assert not upstream.calls


def test_upstream_redirect_and_size_fail_closed(upstream, monkeypatch):
    with serving(bridge(upstream)) as server:
        upstream.status = 302
        status, headers, body = request(server, "GET", "/object_info")
        assert status == 502 and b"secret" not in body and "Location" not in headers
        upstream.status, upstream.large = 200, True
        monkeypatch.setattr(proxy, "JSON_LIMIT", 32)
        assert request(server, "GET", "/object_info")[0] == 502
    assert len(upstream.calls) == 2


@pytest.mark.parametrize("close_only", [False, True])
def test_upstream_deadline_closes_waiting_response(upstream, monkeypatch, close_only):
    upstream.hold_response = threading.Event()
    monkeypatch.setattr(proxy, "UPSTREAM_DEADLINE", 0.1)
    if close_only:
        monkeypatch.setattr(proxy, "close_socket", lambda sock: sock.close())
    timeouts = []
    original_connect = http.client.HTTPConnection.connect
    def connect(connection):
        if connection.port == upstream.server_port:
            timeouts.append(connection.timeout)
        return original_connect(connection)
    monkeypatch.setattr(http.client.HTTPConnection, "connect", connect)
    with serving(bridge(upstream)) as server:
        try:
            status, _, body = request(server, "GET", "/object_info")
            # The provider cannot finish until this test releases it. The
            # client's own socket timeout fails the test if the proxy waits.
            assert upstream.response_waiting.is_set() and not upstream.hold_response.is_set()
            assert status == 502 and json.loads(body) == {"error": "COMFY_UPSTREAM_UNAVAILABLE"}
            assert len(upstream.calls) == 1
            assert timeouts and 0 < max(timeouts) <= proxy.UPSTREAM_DEADLINE
            assert request(server, "GET", "/healthz")[0] == 200
        finally:
            upstream.hold_response.set()


@pytest.mark.parametrize("drip_response", ["headers", "body"])
def test_absolute_upstream_deadline_bounds_drip_without_shutdown(upstream, monkeypatch, drip_response):
    upstream.drip_response = drip_response
    monkeypatch.setattr(proxy, "UPSTREAM_DEADLINE", 0.1)
    monkeypatch.setattr(proxy, "close_socket", lambda sock: sock.close())
    with serving(bridge(upstream)) as server:
        status, _, body = request(server, "GET", "/object_info")
        assert status == 502 and json.loads(body) == {"error": "COMFY_UPSTREAM_UNAVAILABLE"}
        assert request(server, "GET", "/healthz")[0] == 200
    assert len(upstream.calls) == 1


def test_upstream_deadline_releases_all_slots_without_shutdown(upstream, monkeypatch):
    upstream.hold_response = threading.Event()
    monkeypatch.setattr(proxy, "UPSTREAM_DEADLINE", 0.1)
    monkeypatch.setattr(proxy, "close_socket", lambda sock: sock.close())
    with serving(bridge(upstream)) as server:
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
                futures = [executor.submit(request, server, "GET", "/object_info") for _ in range(4)]
                results = [future.result(timeout=3) for future in futures]
            assert len(upstream.calls) == 4 and not upstream.hold_response.is_set()
            assert all(status == 502 and json.loads(body) == {"error": "COMFY_UPSTREAM_UNAVAILABLE"}
                       for status, _, body in results)
            until = time.monotonic() + 1
            while server.slots._value != 4 and time.monotonic() < until:
                time.sleep(0.01)
            assert server.slots._value == 4
            assert request(server, "GET", "/healthz")[0] == 200
        finally:
            upstream.hold_response.set()


def test_absolute_socket_deadline_bounds_blocked_send():
    original, peer = socket.socketpair()
    with peer, proxy.DeadlineSocket(original, time.monotonic() + 0.1) as client:
        client.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4096)
        client.settimeout(2)
        with pytest.raises(TimeoutError) as error:
            client.sendall(b"x" * 1024**2)
        assert 0 < client.gettimeout() <= 0.1 or str(error.value) == "ComfyUI deadline exceeded"


@pytest.mark.parametrize("phase", ["headers", "body", "upstream"])
def test_request_deadline_releases_dripping_clients_and_caps_upstream(upstream, monkeypatch, phase):
    monkeypatch.setattr(proxy, "REQUEST_DEADLINE", 0.2)
    monkeypatch.setattr(proxy, "UPSTREAM_DEADLINE", 5)
    upstream.hold_response = threading.Event()
    prefix = {"headers": b"GET /healthz HTTP/1.1\r\nHost: ",
              "body": b"POST /prompt HTTP/1.1\r\nHost: 127.0.0.1:18188\r\nContent-Type: application/json\r\nContent-Length: 10000\r\n\r\n",
              "upstream": b"GET /object_info HTTP/1.1\r\nHost: 127.0.0.1:18188\r\n\r\n"}[phase]
    with serving(bridge(upstream)) as server:
        clients = [socket.create_connection(server.server_address, timeout=2) for _ in range(4)]
        stopped = threading.Event()
        def drip():
            while not stopped.wait(0.01):
                for client in clients:
                    try: client.sendall(b" ")
                    except OSError: pass
        thread = threading.Thread(target=drip, daemon=True)
        try:
            for client in clients:
                client.sendall(prefix)
            thread.start()
            for client in clients:
                try: assert client.recv(1) == b""
                except ConnectionResetError: pass
            until = time.monotonic() + 1
            while server.slots._value != 4 and time.monotonic() < until:
                time.sleep(0.01)
            assert server.slots._value == 4
            assert len(upstream.calls) == (4 if phase == "upstream" else 0)
        finally:
            stopped.set()
            for client in clients: client.close()
            if thread.ident: thread.join(1)
            upstream.hold_response.set()


def test_deep_request_and_upstream_json_are_bounded_without_tracebacks(upstream, capsys):
    nested = []
    for _ in range(600):
        nested = [nested]
    value = payload(); value["prompt"]["FK:86"]["_meta"] = nested
    with serving(bridge(upstream)) as server:
        status, _, body = request(server, "POST", "/prompt", value)
        assert status == 400 and json.loads(body)["error"] == "COMFY_JSON_TOO_DEEP"
        assert not upstream.calls
        upstream.history = {"ignored": nested}
        status, _, body = request(server, "GET", "/history/" + PID)
        assert status == 400 and json.loads(body)["error"] == "COMFY_JSON_TOO_DEEP"
        assert len(upstream.calls) == 1
    assert capsys.readouterr().err == ""
    for raw in (b'{"ignored":1e999}', b'{"ignored":NaN}', b'{"ignored":Infinity}'):
        with pytest.raises(proxy.Denied):
            proxy.strict_json(raw)


def test_accepted_sockets_are_bounded_and_disconnects_release_capacity_without_tracebacks(upstream, capsys):
    with serving(bridge(upstream)) as server:
        clients = [socket.create_connection(server.server_address, timeout=2) for _ in range(4)]
        try:
            for client in clients:
                client.sendall(b"GET /healthz HTTP/1.1\r\nHost: ")
            until = time.monotonic() + 1
            while server.slots._value and time.monotonic() < until:
                time.sleep(0.01)
            assert server.slots._value == 0
            with socket.create_connection(server.server_address, timeout=2) as extra:
                assert extra.recv(1) == b""
        finally:
            for client in clients:
                client.close()
        until = time.monotonic() + 1
        while server.slots._value != 4 and time.monotonic() < until:
            time.sleep(0.01)
        assert server.slots._value == 4
        assert request(server, "GET", "/healthz")[0] == 200
    assert not upstream.calls
    assert capsys.readouterr().err == ""


def test_successful_runtime_configuration_is_explicit_and_pins_mode_namespace():
    env = {"IZO_SHADOW_EGRESS_PROFILE": proxy.PROFILE, "IZO_COMFY_UPSTREAM_IP": "192.168.1.112",
           "IZO_COMFY_UPSTREAM_PORT": "8188", "IZO_COMFY_NAMESPACE": NAMESPACE}
    assert proxy.configuration(env) == {"host": "192.168.1.112", "port": 8188,
                                        "namespace": NAMESPACE, "mode": "capabilities"}
    for extra in ({"IZO_SHADOW_EGRESS_PROFILE": ""}, {"IZO_COMFY_MODE": "unrestricted"},
                  {"IZO_COMFY_NAMESPACE": "../foreign"}, {"IZO_COMFY_UPSTREAM_PORT": "8188;accept"}):
        with pytest.raises(proxy.Denied):
            proxy.configuration(env | extra)


@pytest.mark.parametrize("address", ["127.0.0.1", "169.254.169.254", "0.0.0.0", "100.64.0.1", "192.0.0.1",
    "8.8.8.8", "::1", "localhost", "192.168.1.112/24", "192.168.1.112;accept"])
def test_production_configuration_allows_only_literal_rfc1918(address):
    with pytest.raises(proxy.Denied):
        proxy.configuration({"IZO_SHADOW_EGRESS_PROFILE": proxy.PROFILE, "IZO_COMFY_UPSTREAM_IP": address,
            "IZO_COMFY_UPSTREAM_PORT": "8188", "IZO_COMFY_NAMESPACE": NAMESPACE})
