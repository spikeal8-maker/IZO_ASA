from __future__ import annotations

import json
import unittest

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


if __name__ == "__main__":
    unittest.main()
