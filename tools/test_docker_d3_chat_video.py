"""Actual bounded wire exchanges and decoded synthetic frames; no application acceptance claim."""
import hashlib
import http.client
import json
from pathlib import Path
import shutil
import socket
import subprocess
import unittest
from unittest.mock import patch
from urllib.parse import urlencode
import uuid

from tools import docker_d3_chat_video_provider as fixture
from tools.docker_d3_chat_video import correlate
from tools.docker_shadow_product import ProductError
from tools.docker_shadow_provider import PNG
from tools.docker_shadow_fixture import DISABLED_ENDPOINTS, SECRET_KEYS, validate_environment


def free_ports():
    sockets = [socket.socket(), socket.socket()]
    try:
        for owned in sockets:
            owned.bind(("127.0.0.1", 0))
        ports = [owned.getsockname()[1] for owned in sockets]
        if min(ports) < 20000:
            raise RuntimeError("D3_TEST_HIGH_PORTS_REQUIRED")
        return ports
    finally:
        for owned in sockets:
            owned.close()


def environment():
    return {"IZO_SHADOW_FIXTURE": fixture.MARKER, "APP_ENV": "test", "ENV": "test", "MODE": "test",
            "BOT_MODE": "disabled", "MAX_UPDATES_MODE": "disabled", "COMFYUI_MOCK_FALLBACK": "false",
            "COMFYUI_BASE_URL": "http://127.0.0.1:48991", "LOCAL_LTX_ENABLED": "true",
            "LOCAL_LTX_WORKFLOW_API_PATH": "/opt/izo/backend/workflows/ltx23_t2v_api.json",
            **{key: "http://127.0.0.1:1" for key in DISABLED_ENDPOINTS},
            "OLLAMA_BASE_URL": "http://127.0.0.1:48991", "LOCAL_LTX_COMFYUI_BASE_URL": "http://127.0.0.1:48991",
            **{key: "" for key in SECRET_KEYS}}


class ChatVideoWireTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import imageio_ffmpeg
            cls.ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        except ModuleNotFoundError:
            cls.ffmpeg = shutil.which("ffmpeg")
        if not cls.ffmpeg:
            raise RuntimeError("D3_TEST_INSTALLED_FFMPEG_REQUIRED")
        cls.clip = fixture.video_clip(executable=cls.ffmpeg)

    def setUp(self):
        self.ports = free_ports()
        with patch.object(fixture, "video_clip", return_value=self.clip):
            self.provider = fixture.ChatVideoProvider(bind="127.0.0.1", port=self.ports[0],
                control_port=self.ports[1], lifetime_seconds=20)
        self.provider.__enter__()
        self.addCleanup(self.close)
        self.run_id = uuid.uuid4().hex

    def close(self):
        self.provider.close()
        self.assertFalse(self.provider._connections)
        self.assertTrue(all(not thread.is_alive() for thread in self.provider._threads))
        self.assertTrue(all(not thread.is_alive() for thread in self.provider._pool._threads))
        for port in self.ports:
            with socket.socket() as probe:
                probe.settimeout(.2)
                self.assertNotEqual(probe.connect_ex(("127.0.0.1", port)), 0)

    def wire(self, method, route, payload=None, *, expected=200, binary=False, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.ports[0], timeout=2)
        try:
            data = payload if isinstance(payload, bytes) else json.dumps(payload) if payload is not None else None
            connection.request(method, route, data, headers=headers or {"Content-Type": "application/json"})
            response = connection.getresponse()
            raw = response.read(1024 * 1024 + 1)
            self.assertEqual(response.status, expected)
            self.assertLessEqual(len(raw), 1024 * 1024)
            return raw if binary else json.loads(raw)
        finally:
            connection.close()

    def chat(self, kind, *, history=(), expected=200, overrides=None):
        messages = [{"role": "system", "content": "Private system canary"}, *history,
                    {"role": "user", "content": f"D3_CHAT_{kind}:{self.run_id}"}]
        payload = {"model": fixture.CHAT_MODEL, "stream": False, "messages": messages, **(overrides or {})}
        return self.wire("POST", "/api/chat", payload, expected=expected)

    def second(self):
        self.chat("FIRST")
        return [{"role": "user", "content": "D3_CHAT_FIRST:" + self.run_id},
                {"role": "assistant", "content": fixture.FIRST_REPLY}]

    def video(self):
        source = Path(__file__).resolve().parents[1] / "backend/workflows/ltx23_t2v_api.json"
        prompt = json.loads(source.read_text(encoding="utf-8"))
        job_id = "video_20261018_140000_" + uuid.uuid4().hex[:6]
        prompt["1"]["inputs"]["unet_name"] = "ltx-2.3-22b-distilled-1.1-Q3_K_M.gguf"
        prompt["5"]["inputs"].update(width=832, height=480, length=25)
        prompt["6"]["inputs"]["frame_rate"] = 12
        prompt["10"]["inputs"]["steps"] = 8
        prompt["14"]["inputs"].update(filename_prefix="izo_ltx/" + job_id, frame_rate=12,
                                     format="video/h264-mp4", save_output=True)
        return {"prompt": prompt, "client_id": job_id}

    def test_two_turns_failure_tool_round_and_private_receipt(self):
        history = self.second()
        self.assertEqual(self.chat("SECOND", history=history)["message"]["content"], fixture.SECOND_REPLY)
        self.chat("FAIL", history=history, expected=502)
        tools = [{"type": "function", "function": {"name": "generate_image"}}]
        first = self.chat("IMAGE", history=history, overrides={"tools": tools})
        self.assertEqual(first["message"]["tool_calls"][0]["function"]["name"], "generate_image")
        result = {"ok": True, "status": "requested", "prompt": fixture.IMAGE_PROMPT, "aspectRatio": "1:1"}
        messages = [{"role": "system", "content": "Private system canary"}, *history,
                    {"role": "user", "content": "D3_CHAT_IMAGE:" + self.run_id}, first["message"],
                    {"role": "tool", "content": json.dumps(result)}]
        done = self.chat("IMAGE", overrides={"messages": messages})
        self.assertEqual(done["message"]["content"], fixture.IMAGE_REPLY)
        receipt = self.provider.receipt()
        self.assertEqual([item["stage"] for item in receipt["d3"]["chat"]], ["first", "second", "failed", "image", "done"])
        for private in ("Private system canary", fixture.IMAGE_PROMPT, self.provider.control_token):
            self.assertNotIn(private, json.dumps(receipt))
        self.assertIs(receipt["d3"]["modelExecution"], False)
        self.assertIs(receipt["d3"]["acceleratorExecution"], False)

    def test_missing_history_or_provider_retry_rejected_without_advancing(self):
        history = self.second()
        self.chat("FIRST", expected=409)
        self.chat("SECOND", expected=409)
        self.assertEqual(len(self.provider.receipt()["d3"]["chat"]), 1)
        self.chat("SECOND", history=history)
        self.chat("SECOND", history=history, expected=409)
        self.assertEqual(len(self.provider.receipt()["d3"]["chat"]), 2)

    def test_malformed_models_messages_tools_are_bounded_http_rejections(self):
        for overrides in ({"model": "external"}, {"stream": True}, {"messages": []},
                          {"messages": [None, None]}, {"messages": [{"content": "x" * 12001}] * 2}):
            with self.subTest(overrides=list(overrides)):
                self.chat("FIRST", overrides=overrides, expected=400)
        history = self.second()
        self.chat("SECOND", history=history)
        self.chat("FAIL", expected=502)
        for tools in (None, {}, [None], [{"function": None}], [{"function": {"name": "generate_image"}}] * 9):
            with self.subTest(tools=type(tools).__name__):
                self.chat("IMAGE", overrides={"tools": tools}, expected=400)
        self.assertEqual(len(self.provider.receipt()["d3"]["chat"]), 3)

    def test_eight_chat_calls_are_a_hard_cap(self):
        for _ in range(8):
            self.run_id = uuid.uuid4().hex
            self.chat("FIRST")
        self.run_id = uuid.uuid4().hex
        self.chat("FIRST", expected=429)
        self.assertEqual(len(self.provider.receipt()["d3"]["chat"]), 8)

    def test_ltx_workflow_poll_download_and_real_decoded_motion(self):
        payload = self.video()
        prompt_id = self.wire("POST", "/prompt", payload)["prompt_id"]
        view = "/view?" + urlencode({"filename": prompt_id + ".mp4", "subfolder": "", "type": "output"})
        self.assertEqual(self.wire("GET", "/history/" + prompt_id), {})
        self.wire("GET", view, expected=409)
        self.assertEqual(self.wire("GET", "/queue")["queue_running"], [[0, prompt_id]])
        self.assertIn(prompt_id, self.wire("GET", "/history/" + prompt_id))
        content = self.wire("GET", view, binary=True)
        self.assertEqual(content, self.clip)
        self.assertEqual(self.wire("GET", "/queue")["queue_running"], [])
        decoded = subprocess.run([self.ffmpeg, "-nostdin", "-v", "error", "-i", "pipe:0", "-vf", "scale=32:32",
            "-pix_fmt", "rgb24", "-f", "rawvideo", "pipe:1"], input=content, capture_output=True, timeout=5, check=True).stdout
        frame = 32 * 32 * 3
        self.assertEqual(len(decoded), frame * 25)
        self.assertNotEqual(hashlib.sha256(decoded[3 * frame:4 * frame]).digest(),
                            hashlib.sha256(decoded[15 * frame:16 * frame]).digest())
        self.wire("POST", "/prompt", self.video(), expected=429)
        receipt = self.provider.receipt()["d3"]
        self.assertEqual(receipt["video"]["jobId"], payload["client_id"])
        self.assertEqual(receipt["video"]["downloads"], 1)
        self.assertEqual(receipt["clipSha256"], hashlib.sha256(content).hexdigest())

    def test_ltx_malformed_graph_does_not_allocate_a_job(self):
        for mutation in (lambda p: p["prompt"].update({"5": None}),
                         lambda p: p["prompt"]["5"]["inputs"].update(width=853),
                         lambda p: p.update(extra_data={}),
                         lambda p: p.update(client_id="video_bad")):
            payload = self.video()
            mutation(payload)
            self.wire("POST", "/prompt", payload, expected=400)
            self.assertIsNone(self.provider.receipt()["d3"]["video"])

    def test_catalog_extension_does_not_mutate_d1_and_gpu_claim_is_explicit(self):
        catalog = self.wire("GET", "/flux_klein/models")
        self.assertEqual(catalog["loras"], list(fixture.FACE_LORAS))
        self.assertEqual(fixture.MODELS["loras"], [])
        device = self.wire("GET", "/system_stats")["devices"][0]
        self.assertEqual(device["vram_total"], 0)
        self.assertIn("no GPU", device["name"])

    def test_image_graph_receipt_tracks_uploaded_inputs_and_rejects_disconnected_proof(self):
        boundary = "D3OwnedUpload"
        body = (f'--{boundary}\r\nContent-Disposition: form-data; name="image"; filename="private.png"\r\n'
                'Content-Type: image/png\r\n\r\n').encode() + PNG + b"\r\n"
        for key, value in (("overwrite", "true"), ("type", "input")):
            body += f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode()
        body += f"--{boundary}--\r\n".encode()
        upload = self.wire("POST", "/upload/image", body, headers={"Content-Type": "multipart/form-data; boundary=" + boundary})
        prompt = {"FK:171": {"class_type": "KSampler", "inputs": {"positive": ["ref", 0]}},
                  "ref": {"class_type": "LoadImage", "inputs": {"image": upload["name"]}},
                  "lora": {"class_type": "LoraLoaderModelOnly", "inputs": {"lora_name": fixture.FACE_LORAS[0]}}}
        def submit():
            result = self.wire("POST", "/prompt", {"prompt": prompt, "client_id": "onenode-backend-" + uuid.uuid4().hex,
                                                   "extra_data": {"enable_previews": True}})
            return next(row["graph"] for row in self.provider.receipt()["jobs"] if row["prompt_id"] == result["prompt_id"])
        self.assertEqual(submit(), {"loadImageCount": 1, "allInputsOwned": True, "inputChainConnected": True,
            "loraCount": 1, "selectedFaceLora": fixture.FACE_LORAS[0], "allLorasAllowed": True})
        prompt["FK:171"]["inputs"] = {}
        self.assertIs(submit()["inputChainConnected"], False)
        prompt["ref"]["inputs"]["image"] = "private-path-canary"
        prompt["lora"]["inputs"]["lora_name"] = "private-lora-canary"
        facts = submit()
        self.assertIs(facts["allInputsOwned"], False)
        self.assertIs(facts["allLorasAllowed"], False)
        self.assertIsNone(facts["selectedFaceLora"])
        for private in ("private-path-canary", "private-lora-canary", "private.png"):
            self.assertNotIn(private, json.dumps(self.provider.receipt()))


class D3ProfileTests(unittest.TestCase):
    def test_receipt_correlation_rejects_instance_replay_job_and_media_substitution(self):
        before = {"fixture": fixture.MARKER, "lifetimeSeconds": 300, "instanceId": "a" * 32,
            "provider": {"model_execution": False, "counts": {"accepted": 0}, "jobs": [],
                "d3": {"profile": fixture.MARKER, "modelExecution": False, "acceleratorExecution": False,
                       "chat": [], "video": None, "clipSha256": "b" * 64, "clipBytes": 1024}}}
        after = json.loads(json.dumps(before))
        provider = after["provider"]
        provider["counts"]["accepted"] = 1
        provider["jobs"] = [{"prompt_id": "01234567-0123-4567-8901-012345678901", "state": "completed",
            "mode": "complete", "body_sha256": "f" * 64,
            "client_sha256": hashlib.sha256(b"onenode-backend-fixture-job").hexdigest()}]
        provider["d3"]["chat"] = [{"stage": stage, "runId": "c" * 32,
            "httpStatus": 502 if stage == "failed" else 200, "historyConfirmed": stage == "second",
            "toolRound": stage == "done"} for stage in ("first", "second", "failed", "image", "done")]
        provider["d3"]["video"] = {"jobId": "video-job", "statusReads": 2, "downloads": 1,
            "width": 832, "height": 480, "frames": 25, "frameRate": 12}
        browser = {"runId": "c" * 32, "image": {"jobId": "fixture-job"},
            "checks": {"video": {"jobId": "video-job", "sha256": "b" * 64, "bytes": 1024}}}
        self.assertEqual(correlate(before, after, browser)["status"], "PASS")
        mutations = (lambda v: v.update(instanceId="d" * 32),
                     lambda v: v["provider"]["d3"]["chat"].append(v["provider"]["d3"]["chat"][0]),
                     lambda v: v["provider"]["jobs"][0].update(client_sha256="e" * 64),
                     lambda v: v["provider"]["d3"].update(clipSha256="f" * 64))
        for mutate in mutations:
            substituted = json.loads(json.dumps(after))
            mutate(substituted)
            with self.assertRaises(ProductError):
                correlate(before, substituted, browser)

    def test_only_exact_test_loopback_profile_and_existing_workflow_are_admitted(self):
        validate_environment(environment())
        mutations = [(key, "https://example.invalid") for key in DISABLED_ENDPOINTS]
        mutations += [(key, "private-canary") for key in SECRET_KEYS]
        mutations += [("LOCAL_LTX_ENABLED", "false"), ("LOCAL_LTX_WORKFLOW_API_PATH", "/tmp/other.json"),
                      ("IZO_SHADOW_FIXTURE", "arbitrary"), ("COMFYUI_MOCK_FALLBACK", "true")]
        for key, value in mutations:
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                validate_environment({**environment(), key: value})

    def test_constructor_retains_loopback_and_lifetime_bounds_before_encoding(self):
        for changes in ({"bind": "0.0.0.0"}, {"lifetime_seconds": 301}, {"port": 443}):
            with self.subTest(changes=changes), patch.object(fixture, "video_clip") as encode:
                with self.assertRaises(ValueError):
                    fixture.ChatVideoProvider(**{"bind": "127.0.0.1", "port": 48991, "control_port": 48992, **changes})
                encode.assert_not_called()


if __name__ == "__main__":
    unittest.main()
