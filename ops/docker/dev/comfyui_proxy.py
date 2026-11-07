"""Restricted private ComfyUI transport for the existing IZO adapter; no queue."""
from __future__ import annotations

import copy
import http.client
import ipaddress
import json
import math
import os
import re
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qsl, urlencode, urlsplit

PROFILE = "comfyui-private-v1"
BODY_LIMIT, JSON_LIMIT, IMAGE_LIMIT = 131072, 16 * 1024**2, 16 * 1024**2
REQUEST_DEADLINE, UPSTREAM_DEADLINE, IDLE_TIMEOUT = 25, 12, 10
JOB = re.compile(r"onenode-backend-[A-Za-z0-9_-]{1,96}")
UUID = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}")
MODEL = "flux-2-klein-4b-fp8.safetensors"
ENCODER, VAE = "qwen_3_4b.safetensors", "flux2-vae.safetensors"
CAPABILITIES = {"/object_info", "/system_stats", "/flux_klein/models",
                "/flux_klein/config", "/flux_klein/workflow_t2i", "/queue"}
# Exact application-owned T2I topology. File/HTTP/custom nodes and extra inputs
# cannot reach the provider. This is validation, not another workflow builder.
GRAPH = {
    "FK:155": ("CLIPLoader", {"clip_name": ENCODER, "type": "flux2", "device": "default"}),
    "FK:153": ("VAELoader", {"vae_name": VAE}),
    "FK:165": ("UNETLoader", {"unet_name": MODEL, "weight_dtype": "default"}),
    "FK:166": ("CLIPTextEncode", {"text": "@text", "clip": ["FK:155", 0]}),
    "FK:156": ("CLIPTextEncode", {"text": "@text", "clip": ["FK:155", 0]}),
    "FK:169": ("ModelSamplingAuraFlow", {"shift": "@shift", "model": ["FK:165", 0]}),
    "FK:170": ("EmptyFlux2LatentImage", {"width": "@size", "height": "@size", "batch_size": 1}),
    "FK:171": ("KSampler", {"seed": "@seed", "steps": 4, "cfg": "@one",
        "sampler_name": "er_sde", "scheduler": "simple", "denoise": "@one",
        "model": ["FK:169", 0], "positive": ["FK:166", 0], "negative": ["FK:156", 0],
        "latent_image": ["FK:170", 0]}),
    "FK:152": ("VAEDecode", {"samples": ["FK:171", 0], "vae": ["FK:153", 0]}),
    "FK:86": ("SaveImage", {"filename_prefix": "@prefix", "images": ["FK:152", 0]}),
}


class Denied(Exception):
    def __init__(self, code="COMFY_POLICY_DENIED", status=403):
        self.code, self.status = code, status


def require(value, code="COMFY_POLICY_DENIED", status=403):
    if not value:
        raise Denied(code, status)


def strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "COMFY_JSON_INVALID", 400)
            result[key] = value
        return result
    try:
        value = json.loads(raw, object_pairs_hook=pairs,
                           parse_constant=lambda _: require(False, "COMFY_JSON_INVALID", 400))
    except (ValueError, UnicodeError, RecursionError):
        raise Denied("COMFY_JSON_INVALID", 400) from None
    # Limit depth before deepcopy/encoding. Iterator stack is bounded even for
    # broad object_info responses and does not recurse on attacker input.
    stack = [(iter((value,)), 0)]
    while stack:
        children, depth = stack[-1]
        try:
            item = next(children)
        except StopIteration:
            stack.pop()
            continue
        require(depth <= 32, "COMFY_JSON_TOO_DEEP", 400)
        if isinstance(item, (dict, list)):
            stack.append((iter(item.values() if isinstance(item, dict) else item), depth + 1))
        elif type(item) is float:
            require(math.isfinite(item), "COMFY_JSON_INVALID", 400)
    return value


def encoded(value):
    return json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(",", ":")).encode()


def close_socket(sock):
    try:
        sock.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass
    sock.close()


class DeadlineSocket(socket.socket):
    def __init__(self, sock, deadline):
        super().__init__(sock.family, sock.type, sock.proto, fileno=sock.detach())
        self.deadline = deadline

    def set_remaining_timeout(self):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("ComfyUI deadline exceeded")
        self.settimeout(min(IDLE_TIMEOUT, remaining))

    def recv_into(self, buffer, nbytes=0, flags=0):
        self.set_remaining_timeout()
        return super().recv_into(buffer, nbytes, flags)

    def sendall(self, data, flags=0):
        self.set_remaining_timeout()
        return super().sendall(data, flags)


def configuration(env):
    require(env.get("IZO_SHADOW_EGRESS_PROFILE") == PROFILE, "COMFY_PROFILE_REQUIRED")
    try:
        address = ipaddress.IPv4Address(env.get("IZO_COMFY_UPSTREAM_IP", ""))
        port = env.get("IZO_COMFY_UPSTREAM_PORT", "")
        require(any(address in ipaddress.IPv4Network(n)
                    for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")))
        require(port.isascii() and port.isdecimal() and 1 <= int(port) <= 65535)
    except (ValueError, TypeError):
        raise Denied("COMFY_TARGET_INVALID") from None
    namespace = env.get("IZO_COMFY_NAMESPACE", "")
    require(re.fullmatch(r"izo-[a-z0-9][a-z0-9-]{15,59}", namespace), "COMFY_NAMESPACE_INVALID")
    mode = env.get("IZO_COMFY_MODE", "capabilities")
    require(mode in {"capabilities", "generate-t2i-4b"}, "COMFY_MODE_INVALID")
    return {"host": str(address), "port": int(port), "namespace": namespace, "mode": mode}


def parts(value):
    require(isinstance(value, str) and 0 < len(value) <= 240)
    require(not any(ord(c) < 32 for c in value) and not any(c in value for c in ":%[]"))
    result = value.replace("\\", "/").split("/")
    require(all(re.fullmatch(r"[A-Za-z0-9_-][A-Za-z0-9_.-]*", p)
                and p not in {".", ".."} and not p.endswith((".", " ")) for p in result))
    return result


def number(value, lower, upper):
    return type(value) in {int, float} and lower <= value <= upper and math.isfinite(value)


def workflow(graph, namespace, *, template=False, client=""):
    require(isinstance(graph, dict) and set(graph) == set(GRAPH), "COMFY_WORKFLOW_DENIED")
    result = copy.deepcopy(graph)
    for key, (kind, expected) in GRAPH.items():
        node = result[key]
        require(isinstance(node, dict) and set(node) <= {"class_type", "inputs", "_meta"}
                and node.get("class_type") == kind and isinstance(node.get("inputs"), dict)
                and set(node["inputs"]) == set(expected), "COMFY_WORKFLOW_DENIED")
        node.pop("_meta", None)
        for field, spec in expected.items():
            value = node["inputs"][field]
            if template and field in {"clip_name", "vae_name", "unet_name"}:
                valid = isinstance(value, str) and len(parts(value)) == 1 and value.endswith(".safetensors")
            elif spec == "@text":
                valid = isinstance(value, str) and len(value) <= 12000 and "\x00" not in value
            elif spec == "@size":
                valid = type(value) is int and 256 <= value <= 1024 and value % 16 == 0
            elif spec == "@seed":
                valid = type(value) is int and 0 <= value <= 2**64 - 1
            elif spec == "@shift":
                valid = number(value, 3, 3)
            elif spec == "@one":
                valid = number(value, 1, 1)
            elif spec == "@prefix":
                valid = bool(parts(value))
            else:
                valid = encoded(value) == encoded(spec)
            require(valid, "COMFY_WORKFLOW_DENIED")
    if not template:
        result["FK:86"]["inputs"]["filename_prefix"] = namespace + "/" + client + "/image"
    return result


def view_parameters(params, namespace):
    require(set(params) == {"filename", "subfolder", "type"} and params["type"] == "output")
    folders = parts(params["subfolder"])
    require(len(folders) == 2 and folders[0] == namespace and JOB.fullmatch(folders[1]))
    require(isinstance(params["filename"], str)
            and re.fullmatch(r"image_[0-9]{5,12}_\.png", params["filename"]))
    return {"filename": params["filename"], "subfolder": "/".join(folders), "type": "output"}


class Policy:
    def __init__(self, config):
        self.config = config

    def request(self, method, target, body):
        require(len(target) <= 2048 and target.startswith("/") and not target.startswith("//"))
        require(not any(ord(c) < 33 or ord(c) > 126 for c in target) and "\\" not in target and "#" not in target)
        url = urlsplit(target)
        require(not url.scheme and not url.netloc and "%" not in url.path)
        if method == "GET" and url.path in CAPABILITIES and not url.query:
            return url.path, None
        require(self.config["mode"] == "generate-t2i-4b")
        if method == "POST" and url.path == "/prompt" and not url.query:
            value = strict_json(body)
            require(isinstance(value, dict) and set(value) == {"prompt", "client_id", "extra_data"})
            client = value["client_id"]
            require(isinstance(client, str) and JOB.fullmatch(client))
            require(encoded(value["extra_data"]) == encoded({"enable_previews": True}))
            value["prompt"] = workflow(value["prompt"], self.config["namespace"], client=client)
            value["client_id"] = self.config["namespace"] + ":" + client
            value["extra_data"] = {"enable_previews": False}
            return "/prompt", encoded(value)
        if method == "GET" and url.path.startswith("/history/") and not url.query:
            require(UUID.fullmatch(url.path.removeprefix("/history/")))
            return url.path, None
        if method == "GET" and url.path == "/view":
            fields = parse_qsl(url.query, keep_blank_values=True, strict_parsing=True, max_num_fields=3)
            require(len(fields) == len(dict(fields)))
            params = view_parameters(dict(fields), self.config["namespace"])
            return "/view?" + urlencode(params), None
        raise Denied()

    def response(self, path, data):
        require(isinstance(data, dict), "COMFY_RESPONSE_INVALID", 502)
        namespace = self.config["namespace"]
        if path == "/prompt":
            require(isinstance(data.get("prompt_id"), str) and UUID.fullmatch(data["prompt_id"])
                    and data.get("node_errors") == {}, "COMFY_SUBMISSION_UNVERIFIED", 502)
            return {"prompt_id": data["prompt_id"], "node_errors": {}}
        if path.startswith("/history/"):
            if not data:
                return {}
            pid = path.removeprefix("/history/")
            require(set(data) == {pid} and isinstance(data[pid], dict), "COMFY_HISTORY_DENIED")
            row, client = data[pid], None
            prompt = row.get("prompt")
            require(isinstance(prompt, list) and len(prompt) in {5, 6} and prompt[1] == pid
                    and isinstance(prompt[3], dict), "COMFY_HISTORY_DENIED")
            client = prompt[3].get("client_id", "")
            require(isinstance(client, str) and client.startswith(namespace + ":")
                    and JOB.fullmatch(client[len(namespace) + 1:]), "COMFY_HISTORY_DENIED")
            original = prompt[2]
            checked = workflow(original, namespace, client=client[len(namespace) + 1:])
            require(original["FK:86"]["inputs"]["filename_prefix"] ==
                    checked["FK:86"]["inputs"]["filename_prefix"], "COMFY_HISTORY_DENIED")
            outputs, status = row.get("outputs"), row.get("status")
            require(isinstance(outputs, dict) and set(outputs) <= {"FK:86"}
                    and isinstance(status, dict) and status.get("status_str") in {"success", "error"}
                    and type(status.get("completed")) is bool, "COMFY_HISTORY_DENIED")
            clean = {}
            if outputs:
                saved = outputs["FK:86"]
                require(isinstance(saved, dict) and set(saved) == {"images"}
                        and isinstance(saved["images"], list) and len(saved["images"]) <= 1)
                clean["FK:86"] = {"images": [view_parameters(item, namespace) for item in saved["images"]]}
                require(all(item["subfolder"] == namespace + "/" + client[len(namespace) + 1:]
                            for item in clean["FK:86"]["images"]))
            return {pid: {"outputs": clean, "status": {"status_str": status["status_str"],
                          "completed": status["completed"], "messages": []}}}
        if path == "/object_info":
            return {name: {} for name in sorted({v[0] for v in GRAPH.values()} | {"FluxKleinOneNode"}) if name in data}
        if path == "/flux_klein/models":
            require(all(isinstance(data.get(k), list) and all(isinstance(v, str) for v in data[k])
                        for k in ("diffusion_models", "text_encoders", "vaes")), "COMFY_RESPONSE_INVALID", 502)
            return {key: [name] if name in data.get(key, []) else []
                    for key, name in (("diffusion_models", MODEL), ("text_encoders", ENCODER), ("vaes", VAE))} | {"loras": []}
        if path == "/flux_klein/config":
            return {}  # Shared provider's prompts/templates are not this instance's data.
        if path == "/flux_klein/workflow_t2i":
            return workflow(data, namespace, template=True)
        if path == "/queue":
            require(all(isinstance(data.get(k), list) for k in ("queue_running", "queue_pending")))
            return {"running_count": len(data["queue_running"]), "pending_count": len(data["queue_pending"])}
        if path == "/system_stats":
            system = data.get("system", {})
            return {"system": {k: system[k] for k in ("comfyui_version", "python_version") if k in system},
                    "devices": [{k: d[k] for k in ("name", "type", "vram_total", "vram_free") if k in d}
                                for d in data.get("devices", [])[:4]]}
        raise Denied()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"
    server_version = "IZO-Comfy-Bridge"

    def setup(self):
        self.deadline = self.request.deadline
        super().setup()

    def log_message(self, *_):
        pass  # Never log prompts, paths, credentials or upstream bodies.

    def send_error(self, code, message=None, explain=None):
        self.reply(code, encoded({"error": "COMFY_HTTP_INVALID"}))

    def reply(self, status, body, content_type="application/json"):
        self.close_connection = True
        try:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)
        except OSError:
            pass  # Disconnect/deadline: release capacity without exception-context logging.

    def handle_expect_100(self):
        self.send_error(400)
        return False

    def handle_request(self):
        upstream = upstream_timer = None
        try:
            require(len(self.headers.as_bytes()) <= 16384, "COMFY_HEADERS_TOO_LARGE", 431)
            require(self.raw_requestline.split()[1].decode("ascii") == self.path, "COMFY_TARGET_INVALID")
            require(len(self.headers.get_all("Host", [])) == 1
                    and self.headers["Host"] in {"127.0.0.1:18188", "localhost:18188"}, "COMFY_HOST_DENIED")
            require(not any(self.headers.get_all(k) for k in ("Transfer-Encoding", "Expect", "Upgrade")),
                    "COMFY_FRAMING_INVALID", 400)
            lengths = self.headers.get_all("Content-Length", [])
            require(len(lengths) <= 1 and (not lengths or re.fullmatch(r"0|[1-9][0-9]{0,6}", lengths[0])),
                    "COMFY_FRAMING_INVALID", 400)
            length = int(lengths[0]) if lengths else 0
            require(length <= BODY_LIMIT, "COMFY_BODY_TOO_LARGE", 413)
            require(self.command in {"GET", "POST"} and (self.command != "GET" or length == 0))
            if self.command == "POST":
                require(len(lengths) == 1 and self.headers.get_all("Content-Type") == ["application/json"],
                        "COMFY_FRAMING_INVALID", 400)
            if self.command == "GET" and self.path == "/healthz":
                self.reply(200, encoded({"ok": True, "profile": PROFILE, "mode": self.server.policy.config["mode"]}))
                return
            body = self.rfile.read(length)
            require(len(body) == length, "COMFY_BODY_INCOMPLETE", 400)
            path, forwarded = self.server.policy.request(self.command, self.path, body)
            config = self.server.policy.config
            remaining = self.deadline - time.monotonic()
            require(remaining > 0, "COMFY_REQUEST_TIMEOUT", 408)
            upstream_deadline = min(self.deadline, time.monotonic() + UPSTREAM_DEADLINE)
            upstream = http.client.HTTPConnection(config["host"], config["port"],
                timeout=min(IDLE_TIMEOUT, UPSTREAM_DEADLINE, upstream_deadline - time.monotonic()))
            upstream.connect()
            upstream.sock = DeadlineSocket(upstream.sock, upstream_deadline)
            upstream_timer = threading.Timer(max(0.001, upstream_deadline - time.monotonic()),
                                             close_socket, args=(upstream.sock,))
            upstream_timer.daemon = True
            upstream_timer.start()
            headers = {"Accept": "application/json", "Connection": "close"}
            if forwarded is not None:
                headers["Content-Type"] = "application/json"
            upstream.request(self.command, path, body=forwarded, headers=headers)
            response = upstream.getresponse()
            require(response.status == 200, "COMFY_UPSTREAM_STATUS", 502)  # No redirect follow.
            require(response.getheader("Content-Encoding") in {None, "identity"}, "COMFY_RESPONSE_ENCODING", 502)
            media = path.startswith("/view?")
            limit = IMAGE_LIMIT if media else JSON_LIMIT
            raw = response.read(limit + 1)
            require(len(raw) <= limit, "COMFY_RESPONSE_TOO_LARGE", 502)
            if media:
                require(response.getheader("Content-Type", "").split(";")[0] == "image/png"
                        and raw.startswith(b"\x89PNG\r\n\x1a\n"), "COMFY_IMAGE_INVALID", 502)
                self.reply(200, raw, "image/png")
            else:
                require(response.getheader("Content-Type", "").split(";")[0] == "application/json",
                        "COMFY_RESPONSE_INVALID", 502)
                self.reply(200, encoded(self.server.policy.response(path, strict_json(raw))))
        except Denied as error:
            self.reply(error.status, encoded({"error": error.code}))
        except (OSError, ValueError, TypeError, KeyError, RecursionError, OverflowError, http.client.HTTPException):
            self.reply(502, encoded({"error": "COMFY_UPSTREAM_UNAVAILABLE"}))
        finally:
            if upstream_timer:
                upstream_timer.cancel()
            if upstream:
                upstream.close()

    do_GET = do_POST = handle_request


class Server(ThreadingHTTPServer):
    daemon_threads, request_queue_size = True, 4

    def __init__(self, address, policy):
        self.policy, self.slots = policy, threading.BoundedSemaphore(4)
        super().__init__(address, Handler)

    def process_request(self, request, address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            request = DeadlineSocket(request, time.monotonic() + REQUEST_DEADLINE)
            super().process_request(request, address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request, address):
        # A wall-clock deadline also bounds slow-drip headers/bodies and upstream.
        timer = threading.Timer(max(0.001, request.deadline - time.monotonic()),
                                self.shutdown_request, args=(request,))
        timer.daemon = True
        request.settimeout(IDLE_TIMEOUT)
        timer.start()
        try:
            super().process_request_thread(request, address)
        finally:
            timer.cancel()
            self.slots.release()


if __name__ == "__main__":
    config = configuration(os.environ)
    require(os.getuid() == 10002, "COMFY_PROXY_UID_INVALID")
    with Server(("127.0.0.1", 18188), Policy(config)) as server:
        server.serve_forever()
