from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from unittest.mock import patch

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent / 'app' / 'services'))
from comfyui_native4b import graph, validate_bridge_route


class BridgeSecurityTests(unittest.TestCase):
    def test_allow_only_safe_standard_http_api(self):
        good = [
            "/system_stats", "/queue", "/object_info",
            "/object_info/UNETLoader", "/object_info/CLIPLoader",
            "/object_info/VAELoader",
            "/history/64a9e041-fe65-439f-874f-2b32d0acb40b",
            "/view?filename=local4b_00001_.png&subfolder=Comfy214&type=output",
        ]
        for path in good:
            with self.subTest(path=path):
                self.assertTrue(validate_bridge_route("GET", path))

    def test_delete_open_folder_upload_input_path_exfiltration_denied(self):
        bad = [
            "/flux_klein/delete", "/flux_klein/open_folder", "/flux_klein/stage_input",
            "/flux_klein/set_output", "/upload/image", "/view?filename=../../etc/passwd",
            "/view?filename=local4b_00001_.png&subfolder=../../&type=output",
            "/view?filename=other.png&subfolder=Comfy214&type=output",
            "/view?filename=local4b_00001_.png&subfolder=Comfy214&type=input",
            "/view?filename=local4b_00001_.png&subfolder=Comfy214&type=output&x=1",
            "/%2e%2e/secrets", "//evil.example/path", "/history/other",
            "/api/admin/settings", "/prompt", "/queue?clear=true",
        ]
        for path in bad:
            with self.subTest(path=path):
                self.assertFalse(validate_bridge_route("GET", path))
                self.assertFalse(validate_bridge_route("POST", path, b"{}"))

    def test_post_only_exact_t2i_payload(self):
        good = {"prompt": graph(prompt="A safe robot", width=512, height=512, seed=214),
                "client_id": "onenode-backend-realjob214",
                "extra_data": {"enable_previews": True}}
        self.assertTrue(validate_bridge_route("POST", "/prompt", json.dumps(good).encode()))
        self.assertFalse(validate_bridge_route("POST", "/prompt", b"not-json"))
        self.assertFalse(validate_bridge_route("POST", "/prompt", b"{}"))
        self.assertFalse(validate_bridge_route("POST", "/free", b'{"unload_models":true,"free_memory":true}'))
        self.assertFalse(validate_bridge_route("POST", "/interrupt", b"{}"))


class HostAgentJournalTests(unittest.TestCase):
    @staticmethod
    def host_agent():
        script = (Path(__file__).resolve().parents[1]
                  / "ops" / "windows" / "comfyui_bridge_agent.py")
        spec = importlib.util.spec_from_file_location("comfy214_agent_test", script)
        if spec is None or spec.loader is None:
            raise AssertionError("Host agent module unavailable")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_restart_keeps_only_owned_prompt_and_image(self):
        agent = self.host_agent()
        with tempfile.TemporaryDirectory() as folder:
            token = Path(folder) / "bridge.token"
            current = agent.restore_memory(token)
            prompt_id = "06e0e337-8839-4c8f-b415-3c33ccc026ac"
            self.assertEqual(current["owned"], set())
            current["owned"].add(prompt_id)
            current["active"] = prompt_id
            current["images"].add(("local4b_00001_.png", "Comfy214"))
            agent.save_memory(current)
            restored = agent.restore_memory(token)
            self.assertEqual(restored["owned"], {prompt_id})
            self.assertEqual(restored["active"], prompt_id)
            self.assertEqual(restored["images"], {("local4b_00001_.png", "Comfy214")})
            restored["active"] = None
            agent.save_memory(restored)
            self.assertIsNone(agent.restore_memory(token)["active"])

    def test_only_definitive_gpu_error_releases_active_job(self):
        agent = self.host_agent()
        prompt_id = "06e0e337-8839-4c8f-b415-3c33ccc026ac"
        task = {"id": "bridge-req", "method": "GET",
                "path": "/history/" + prompt_id, "body_b64": ""}
        with tempfile.TemporaryDirectory() as folder:
            token = Path(folder) / "bridge.token"
            memory = agent.restore_memory(token)
            memory["owned"].add(prompt_id)
            memory["active"] = prompt_id
            for item, expected_active in [
                ({}, prompt_id),
                ({"status": {"status_str": "error"}, "outputs": {}}, None),
            ]:
                payload = json.dumps({prompt_id: item}).encode("utf-8")
                with patch.object(agent, "fetch", return_value=(200, payload)) as mocked:
                    status, result = agent.process_task(None, task, "http://127.0.0.1:8188", memory)
                self.assertEqual(status, 200)
                self.assertEqual(result, payload)
                self.assertEqual(memory["active"], expected_active)
                self.assertEqual(mocked.call_count, 1)
                self.assertEqual(agent.restore_memory(token)["active"], expected_active)

    def test_tampered_journal_fails_closed_without_reclaim(self):
        agent = self.host_agent()
        with tempfile.TemporaryDirectory() as folder:
            token = Path(folder) / "bridge.token"
            agent.restore_memory(token)["state_path"].write_text(
                json.dumps({"owned": ["../../other-user"], "images": ["secret.png"],
                            "active": None}), encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "HOST_BRIDGE_STATE_INVALID"):
                agent.restore_memory(token)


if __name__ == "__main__":
    unittest.main()
