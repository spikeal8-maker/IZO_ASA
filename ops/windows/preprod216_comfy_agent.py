"""Windows-initiated, single-flight bridge to already-running loopback ComfyUI.

No listener on Windows, no new Python environment, no web keys, no model writes.
Exit/restart this agent never restarts or stops ComfyUI/Ollama/Docker.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend" / "app" / "services"))
from comfyui_native4b import CORE_NODES, validate_bridge_route  # noqa: E402

MAX_RESULT = 9_000_000
_STATE_LIMIT = 262_144
_PROMPT_RE = re.compile(r"^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$")
_IMAGE_RE = re.compile(r"^local4b_[0-9]{5}_.png$")


def restore_memory(token_file: Path) -> dict:
    """Reclaim only previously accepted prompt/image ownership after agent restart."""
    path = token_file.with_name("bridge-agent-state.json")
    memory = {"owned": set(), "images": set(), "active": None, "state_path": path}
    if not path.exists():
        return memory
    if path.stat().st_size > _STATE_LIMIT:
        raise RuntimeError("HOST_BRIDGE_STATE_TOO_LARGE")
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
        ids, names, active = state["owned"], state["images"], state["active"]
        if (not isinstance(ids, list) or not isinstance(names, list)
                or len(ids) > 2048 or len(names) > 2048
                or any(not isinstance(i, str) or not _PROMPT_RE.fullmatch(i) for i in ids)
                or any(not isinstance(n, str) or not _IMAGE_RE.fullmatch(n) for n in names)
                or (active is not None and (not isinstance(active, str) or active not in ids))):
            raise ValueError("HOST_BRIDGE_STATE_INVALID")
        memory["owned"] = set(ids)
        memory["images"] = {(n, "Comfy214") for n in names}
        memory["active"] = active
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError("HOST_BRIDGE_STATE_INVALID") from exc
    return memory


def save_memory(memory: dict) -> None:
    """Atomic, bounded metadata journal next to the off-repo bridge token."""
    path = memory.get("state_path")
    if not isinstance(path, Path):
        return
    data = {
        "owned": sorted(memory["owned"]),
        "images": sorted(name for name, folder in memory["images"] if folder == "Comfy214"),
        "active": memory["active"],
    }
    encoded = json.dumps(data, separators=(",", ":"), sort_keys=True)
    if len(encoded.encode("utf-8")) > _STATE_LIMIT:
        raise RuntimeError("HOST_BRIDGE_STATE_TOO_LARGE")
    temp = path.with_name("bridge-agent-state.tmp")
    with temp.open("w", encoding="utf-8") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)


def fetch(opener, url, *, method="GET", body=None, headers=None, timeout=20):
    req = urllib.request.Request(url, data=body, method=method,
                                 headers=headers or {})
    try:
        with opener.open(req, timeout=timeout) as response:
            return response.status, response.read(MAX_RESULT + 1)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(200_000)


def gpu_available() -> bool:
    try:
        result = subprocess.run([
            "nvidia-smi", "--query-gpu=memory.used,utilization.gpu",
            "--format=csv,noheader,nounits",
        ], capture_output=True, text=True, timeout=6, check=True)
        used, utilization = [int(v.strip()) for v in result.stdout.splitlines()[0].split(",")]
        return used < 3500 and utilization < 80
    except (OSError, ValueError, subprocess.SubprocessError):
        return False


def local_queue_idle(opener, comfy):
    status, body = fetch(opener, comfy + "/queue", timeout=8)
    if status != 200:
        return False
    try:
        q = json.loads(body)
        return not q.get("queue_running") and not q.get("queue_pending")
    except (ValueError, AttributeError):
        return False


def process_task(opener, task, comfy, memory):
    ident = task.get("id")
    method = task.get("method")
    path = task.get("path")
    try:
        body = base64.b64decode(task.get("body_b64", ""), validate=True)
    except (ValueError, TypeError):
        return 422, b'{"detail":"HOST_BRIDGE_BODY_INVALID"}'
    if not isinstance(ident, str) or not validate_bridge_route(method, path, body):
        return 403, b'{"detail":"HOST_BRIDGE_ROUTE_DENIED"}'
    if method == "POST":
        if (len(memory["owned"]) >= 2048 or not gpu_available()
                or not local_queue_idle(opener, comfy) or memory["active"]):
            return 409, b'{"detail":"GPU_BUSY_OR_COMFY_QUEUE_ACTIVE"}'
    if path.startswith("/history/"):
        if path.split("/")[-1] not in memory["owned"]:
            return 404, b"{}"
    if path.startswith("/view?"):
        parsed = urllib.parse.parse_qs(urllib.parse.urlsplit(path).query)
        key = (parsed.get("filename", [""])[0], parsed.get("subfolder", [""])[0])
        if key not in memory["images"]:
            return 403, b'{"detail":"UNOWNED_COMFY_IMAGE"}'
    try:
        headers = {"Content-Type": "application/json"} if method == "POST" else {}
        status, response = fetch(opener, comfy + path, method=method,
                                 body=body if method == "POST" else None,
                                 headers=headers, timeout=45)
    except (TimeoutError, OSError, ValueError):
        return 502, b'{"detail":"HOST_COMFY_CONNECTION_ERROR"}'
    if len(response) > MAX_RESULT:
        return 413, b'{"detail":"HOST_COMFY_RESULT_TOO_LARGE"}'
    if status == 200 and path == "/object_info":
        try:
            all_nodes = json.loads(response)
            response = json.dumps(
                {name: all_nodes[name] for name in CORE_NODES if name in all_nodes}
            ).encode("utf-8")
        except (ValueError, KeyError, TypeError):
            return 502, b'{"detail":"HOST_OBJECT_INFO_INVALID"}'
    if status == 200 and path == "/prompt":
        try:
            result = json.loads(response)
            ident = result["prompt_id"]
            if not isinstance(ident, str) or not _PROMPT_RE.fullmatch(ident):
                raise ValueError
            memory["owned"].add(ident)
            memory["active"] = ident
            save_memory(memory)
        except (ValueError, KeyError, TypeError):
            return 502, b'{"detail":"HOST_COMFY_SUBMISSION_INVALID"}'
    if status == 200 and path.startswith("/history/"):
        try:
            pid = path.rsplit("/", 1)[-1]
            item = json.loads(response).get(pid, {})
            for output in item.get("outputs", {}).values():
                for img in output.get("images", []):
                    key = (img.get("filename"), img.get("subfolder", ""))
                    if (key[1] == "Comfy214" and isinstance(key[0], str)
                            and _IMAGE_RE.fullmatch(key[0])):
                        memory["images"].add(key)
            # Only Comfy's definitive terminal history can release this prompt.
            # A missing/partial history is ambiguous: retain the ownership fence.
            outcome = item.get("status", {})
            complete = (outcome.get("status_str") == "error"
                        or (outcome.get("status_str") == "success"
                            and outcome.get("completed") is True))
            own_terminal = complete and memory["active"] == pid
            if own_terminal:
                memory["active"] = None
            save_memory(memory)
            # Free owned 4B VRAM when idle even if /view later fails. Never
            # unload another queued job, and never resubmit a prior /prompt.
            if own_terminal and outcome.get("status_str") == "success" and local_queue_idle(opener, comfy):
                payload = b'{"unload_models":true,"free_memory":true}'
                try:
                    fetch(opener, comfy + "/free", method="POST",
                          body=payload, headers={"Content-Type": "application/json"}, timeout=8)
                except (OSError, TimeoutError):
                    pass
        except (ValueError, AttributeError, TypeError):
            return 502, b'{"detail":"HOST_COMFY_HISTORY_INVALID"}'
    if status == 200 and path.startswith("/view?"):
        if not response.startswith(b"\x89PNG\r\n\x1a\n"):
            return 502, b'{"detail":"HOST_COMFY_VIEW_NOT_PNG"}'
        # PNG fetch is not an ownership signal. An older /view must never
        # release an unrelated currently active Comfy prompt.
    return status, response


def run(bridge: str, comfy: str, token_file: Path) -> None:
    token = token_file.read_text(encoding="ascii").strip()
    if len(token) < 40:
        raise RuntimeError("BRIDGE_TOKEN_INVALID")
    if bridge != "http://127.0.0.1:48316" or comfy != "http://127.0.0.1:8188":
        raise RuntimeError("HOST_ENDPOINT_NOT_LOOPBACK_ALLOWLIST")
    headers = {"X-Comfy214-Token": token}
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    owned = restore_memory(token_file)
    print("COMFY214_HOST_AGENT_STARTED local-only, strict 4B t2i", flush=True)
    while True:
        try:
            status, raw = fetch(opener, bridge + "/bridge/poll", headers=headers, timeout=20)
            if status == 204:
                continue
            if status != 200:
                if status == 403:
                    raise RuntimeError("HOST_BRIDGE_AUTH_REJECTED")
                time.sleep(2)
                continue
            task = json.loads(raw)
            result_status, result_body = process_task(opener, task, comfy, owned)
            ident = task["id"]
            reply = json.dumps({
                "status": result_status,
                "body_b64": base64.b64encode(result_body).decode("ascii"),
            }).encode("ascii")
            response_status, _ = fetch(
                opener, bridge + "/bridge/complete/" + ident,
                method="POST", body=reply,
                headers={**headers, "Content-Type": "application/json"}, timeout=20,
            )
            if response_status not in (200, 409):
                print("COMFY214_HOST_DELIVERY_FAILED", flush=True)
        except (ConnectionError, OSError, TimeoutError, ValueError):
            time.sleep(2)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--bridge", required=True)
    parser.add_argument("--comfy", required=True)
    parser.add_argument("--token-file", required=True)
    args = parser.parse_args()
    run(args.bridge, args.comfy, Path(args.token_file))
