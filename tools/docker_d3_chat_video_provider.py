"""D3-only Ollama/LTX wire extension; synthetic answers/video, no models or GPU."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile
from urllib.parse import parse_qs, urlsplit
import uuid

try:
    from tools.docker_shadow_provider import MODELS, ControlledProvider, RequestError
except ModuleNotFoundError:
    from docker_shadow_provider import MODELS, ControlledProvider, RequestError

MARKER = "controlled-chat-video-v1"
CHAT_MODEL = "gemma4:12b"
FIRST_REPLY = "Controlled reply one."
SECOND_REPLY = "Controlled reply two; prior turn confirmed."
IMAGE_REPLY = "Controlled image request prepared."
IMAGE_PROMPT = "A blue ceramic cup on a plain table"
MAX_CHAT_CALLS = 8
FACE_LORAS = ("bfs_head_fixture_flux-klein_4b.safetensors", "bfs_head_fixture_flux-klein_9b.safetensors")


def video_clip(*, executable=None):
    """Encode 25 actual frames with the already installed ffmpeg dependency."""
    if executable is None:
        import imageio_ffmpeg
        executable = imageio_ffmpeg.get_ffmpeg_exe()
    with tempfile.TemporaryDirectory(prefix="izo-d3-video-") as directory:
        path = Path(directory) / "controlled.mp4"
        command = [str(executable), "-nostdin", "-v", "error", "-f", "lavfi", "-i",
                   "testsrc2=size=832x480:rate=12", "-frames:v", "25", "-an", "-c:v", "libx264",
                   "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(path)]
        try:
            subprocess.run(command, check=True, capture_output=True, timeout=5)
            data = path.read_bytes()
        except (OSError, subprocess.SubprocessError):
            raise RuntimeError("D3_VIDEO_FIXTURE_ENCODING_FAILED") from None
    if not 1024 <= len(data) <= 1024 * 1024 or data[4:8] != b"ftyp":
        raise RuntimeError("D3_VIDEO_FIXTURE_CONTAINER_INVALID")
    return data


class ChatVideoProvider(ControlledProvider):
    """Inherited loopback/deadline/body/concurrency bounds; at most one LTX job."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._clip = video_clip()
        self._chat, self._runs, self._video = [], {}, None

    def receipt(self):
        value = super().receipt()
        with self._lock:
            value["d3"] = {"profile": MARKER, "chat": [dict(item) for item in self._chat],
                           "video": dict(self._video) if self._video else None,
                           "clipSha256": hashlib.sha256(self._clip).hexdigest(), "clipBytes": len(self._clip),
                           "modelExecution": False, "acceleratorExecution": False}
        return value

    def _submit(self, headers, body):
        payload = self._json(headers, body)
        prompt = payload.get("prompt")
        if (not isinstance(prompt, dict) or not 1 <= len(prompt) <= 128
                or any(not isinstance(node, dict) or not isinstance(node.get("inputs"), dict)
                       for node in prompt.values())):
            raise RequestError()
        loads = {key: node["inputs"].get("image") for key, node in prompt.items() if node.get("class_type") == "LoadImage"}
        loras = [node["inputs"]["lora_name"] for node in prompt.values() if "lora_name" in node["inputs"]]
        pending, reachable = {"FK:171"}, set()
        while pending:
            identifier = pending.pop()
            if identifier in reachable or identifier not in prompt:
                continue
            reachable.add(identifier)
            pending.update(value[0] for value in prompt[identifier]["inputs"].values()
                           if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str)
                           and type(value[1]) is int and value[0] in prompt and value[0] not in reachable)
        with self._lock:
            facts = {"loadImageCount": len(loads), "allInputsOwned": all(isinstance(name, str) and name in self._uploads for name in loads.values()),
                     "inputChainConnected": loads.keys() <= reachable, "loraCount": len(loras),
                     "selectedFaceLora": loras[0] if len(loras) == 1 and loras[0] in FACE_LORAS else None,
                     "allLorasAllowed": all(name in FACE_LORAS for name in loras)}
        reply = super()._submit(headers, body)
        fingerprint = hashlib.sha256(body).hexdigest()
        with self._lock:
            for job in self._jobs.values():
                if job["body_sha256"] == fingerprint:
                    job["graph"] = facts
        return reply

    def _chat_reply(self, headers, body):
        payload = self._json(headers, body)
        messages = payload.get("messages")
        if (payload.get("model") != CHAT_MODEL or payload.get("stream") is not False
                or not isinstance(messages, list) or not 2 <= len(messages) <= 8
                or any(not isinstance(item, dict) or not isinstance(item.get("content"), str)
                       or len(item["content"]) > 12000 for item in messages)):
            raise RequestError()
        user = next((item["content"] for item in reversed(messages) if item.get("role") == "user"), "")
        match = re.fullmatch(r"D3_CHAT_(FIRST|SECOND|FAIL|IMAGE):([a-f0-9]{32})", user)
        if not match:
            raise RequestError()
        kind, run_id = match.groups()
        history = [(item.get("role"), item["content"]) for item in messages]
        with self._lock:
            if len(self._chat) >= MAX_CHAT_CALLS:
                raise RequestError(429)
            stage = self._runs.get(run_id)
            calls, reply, status = [], "", 200
            if kind == "FIRST" and stage is None:
                next_stage, reply = "first", FIRST_REPLY
            elif kind == "SECOND" and stage == "first":
                if ("user", "D3_CHAT_FIRST:" + run_id) not in history or ("assistant", FIRST_REPLY) not in history:
                    raise RequestError(409)
                next_stage, reply = "second", SECOND_REPLY
            elif kind == "FAIL" and stage == "second":
                next_stage, status = "failed", 502
            elif kind == "IMAGE" and stage == "failed":
                tools = payload.get("tools")
                if (not isinstance(tools, list) or len(tools) > 8 or any(not isinstance(item, dict)
                        or not isinstance(item.get("function"), dict) for item in tools)):
                    raise RequestError()
                names = [item["function"].get("name") for item in tools]
                if "generate_image" not in names or messages[-1].get("role") != "user":
                    raise RequestError()
                next_stage = "image"
                calls = [{"function": {"name": "generate_image", "arguments": {
                    "prompt": IMAGE_PROMPT, "aspect_ratio": "1:1"}}}]
            elif kind == "IMAGE" and stage == "image" and messages[-1].get("role") == "tool":
                result = json.loads(messages[-1]["content"])
                if result != {"ok": True, "status": "requested", "prompt": IMAGE_PROMPT, "aspectRatio": "1:1"}:
                    raise RequestError()
                next_stage, reply = "done", IMAGE_REPLY
            else:
                raise RequestError(409)
            self._runs[run_id] = next_stage
            self._chat.append({"runId": run_id, "stage": next_stage, "httpStatus": status,
                               "bodySha256": hashlib.sha256(body).hexdigest(), "messageCount": len(messages),
                               "historyConfirmed": kind == "SECOND", "toolRound": next_stage == "done"})
        if status != 200:
            return status, {"error": "CONTROLLED_CHAT_FAILURE"}, "application/json"
        message = {"role": "assistant", "content": reply}
        if calls:
            message["tool_calls"] = calls
        return 200, {"model": CHAT_MODEL, "message": message, "done": True,
                     "prompt_eval_count": 10, "eval_count": 5}, "application/json"

    def _ltx_submit(self, payload, body):
        prompt, client_id = payload.get("prompt"), payload.get("client_id")
        if (set(payload) != {"prompt", "client_id"} or not isinstance(prompt, dict)
                or len(prompt) != 14 or not isinstance(client_id, str)
                or re.fullmatch(r"video_\d{8}_\d{6}_[0-9a-f]{6}", client_id) is None):
            raise RequestError()
        def inputs(identifier, class_type):
            node = prompt.get(identifier, {})
            if (not isinstance(node, dict) or node.get("class_type") != class_type
                    or not isinstance(node.get("inputs"), dict)):
                raise RequestError()
            return node["inputs"]
        latent = inputs("5", "EmptyLTXVLatentVideo")
        output = inputs("14", "VHS_VideoCombine")
        if (inputs("1", "UnetLoaderGGUF").get("unet_name") != "ltx-2.3-22b-distilled-1.1-Q3_K_M.gguf"
                or {key: latent.get(key) for key in ("width", "height", "length", "batch_size")}
                   != {"width": 832, "height": 480, "length": 25, "batch_size": 1}
                or inputs("10", "LTXVScheduler").get("steps") != 8
                or inputs("6", "LTXVConditioning").get("frame_rate") != 12
                or output.get("filename_prefix") != "izo_ltx/" + client_id
                or output.get("format") != "video/h264-mp4" or output.get("frame_rate") != 12
                or output.get("save_output") is not True):
            raise RequestError()
        with self._lock:
            if self._video is not None:
                raise RequestError(429)
            self._video = {"jobId": client_id, "promptId": str(uuid.uuid4()), "statusReads": 0,
                           "bodySha256": hashlib.sha256(body).hexdigest(), "frames": 25,
                           "width": 832, "height": 480, "frameRate": 12, "downloads": 0}
            prompt_id = self._video["promptId"]
        return 200, {"prompt_id": prompt_id}, "application/json"

    def _provider(self, method, target, headers, body):
        if method == "POST" and target == "/api/chat":
            return self._chat_reply(headers, body)
        if method == "POST" and target == "/prompt":
            payload = self._json(headers, body)
            if str(payload.get("client_id", "")).startswith("video_"):
                return self._ltx_submit(payload, body)
        if method == "GET" and target in {"/api/tags", "/api/ps"}:
            return 200, {"models": [{"name": CHAT_MODEL, "model": CHAT_MODEL, "size_vram": 0}]}, "application/json"
        if method == "GET" and target == "/flux_klein/models":
            return 200, {**MODELS, "loras": list(FACE_LORAS)}, "application/json"
        if method == "GET" and target == "/system_stats":
            return 200, {"devices": [{"name": "Controlled protocol fixture; no GPU", "type": "cuda",
                                      "vram_total": 0}]}, "application/json"
        if method == "GET":
            parsed = urlsplit(target)
            with self._lock:
                video = self._video
                if video and target == "/history/" + video["promptId"]:
                    video["statusReads"] += 1
                    data = {} if video["statusReads"] == 1 else {video["promptId"]: {
                        "status": {"status_str": "success", "completed": True}, "outputs": {"14": {"gifs": [
                            {"filename": video["promptId"] + ".mp4", "subfolder": "", "type": "output"}]}}}}
                    return 200, data, "application/json"
                if target == "/queue":
                    running = [[0, video["promptId"]]] if video and video["statusReads"] <= 1 else []
                    return 200, {"queue_running": running, "queue_pending": []}, "application/json"
                if video and parsed.path == "/view":
                    query = parse_qs(parsed.query, keep_blank_values=True, max_num_fields=3)
                    if query == {"filename": [video["promptId"] + ".mp4"], "subfolder": [""], "type": ["output"]}:
                        if video["statusReads"] < 2:
                            raise RequestError(409)
                        video["downloads"] += 1
                        return 200, self._clip, "video/mp4"
        return super()._provider(method, target, headers, body)
