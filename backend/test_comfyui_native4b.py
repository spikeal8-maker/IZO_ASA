from __future__ import annotations

import copy
import unittest
import asyncio
from types import SimpleNamespace

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent / 'app' / 'services'))
import comfyui_native4b as native


class Native4BTests(unittest.TestCase):
    def setUp(self):
        self.g = native.graph(prompt="A small robot in a city park", width=512, height=512, seed=812)

    def test_exact_graph_matches_official_distilled_components(self):
        self.assertEqual({node["class_type"] for node in self.g.values()}, set(native.CORE_NODES))
        self.assertEqual(self.g["70"]["inputs"]["unet_name"], native.MODEL)
        self.assertEqual(self.g["71"]["inputs"]["clip_name"], native.ENCODER)
        self.assertEqual(self.g["72"]["inputs"]["vae_name"], native.VAE)
        self.assertEqual(self.g["9"]["inputs"]["filename_prefix"], native.PREFIX)
        self.assertEqual(self.g["62"]["inputs"]["steps"], 4)

    def test_provider_envelope_validates_exact_nodes_and_values(self):
        body = {"prompt": self.g, "client_id": "onenode-backend-job_214_a",
                "extra_data": {"enable_previews": True}}
        self.assertTrue(native.validate_submitted_graph(body))
        for change in [
            lambda g: g["70"]["inputs"].update(unet_name="flux-2-klein-9b-fp8.safetensors"),
            lambda g: g["9"]["inputs"].update(filename_prefix="../secret"),
            lambda g: g.update({"E": {"class_type": "PythonExec", "inputs": {}}}),
            lambda g: g["66"]["inputs"].update(width=2048),
            lambda g: g["62"]["inputs"].update(steps=24),
            lambda g: g["71"]["inputs"].update(clip_name="other.safetensors"),
        ]:
            bad = copy.deepcopy(body)
            change(bad["prompt"])
            self.assertFalse(native.validate_submitted_graph(bad))

    def test_only_4b_t2i_no_lora_or_9b(self):
        for attrs in [
            {"mode": "edit"},
            {"mode": "image_to_image"},
            {"profile": "flux_klein_9b"},
            {"width": 1024},
            {"steps": 20},
            {"loras": 1},
            {"prompt": ""},
        ]:
            params = {"mode": "text_to_image", "profile": "flux_klein_4b",
                      "width": 512, "height": 512,
                      "steps": 4, "prompt": "A small robot", "loras": 0}
            params.update(attrs)
            with self.assertRaises(native.Native4BError):
                native.check_request(**params)

    def test_studio_publishes_only_native_4b_compatible_resolutions(self):
        presets = [
            {"id": "sq-sd", "width": 704, "height": 704},
            {"id": "sq-hd", "width": 1024, "height": 1024},
            {"id": "h-sd", "width": 1024, "height": 576},
            {"id": "v-sd", "width": 576, "height": 1024},
            {"id": "small-valid", "width": 512, "height": 512},
            {"id": "large-valid", "width": 768, "height": 768},
            {"id": "unaligned", "width": 701, "height": 704},
        ]
        self.assertEqual(native.supported_resolution_ids(presets),
                         ["sq-sd", "small-valid", "large-valid"])

    def test_inventory_requirements(self):
        data = {"diffusion_models": [native.MODEL],
                "text_encoders": [native.ENCODER],
                "vaes": [native.VAE]}
        self.assertTrue(native.validate_model_inventory(data))
        self.assertFalse(native.validate_model_inventory({**data, "vaes": []}))


class Native4BProviderBoundaries(unittest.TestCase):
    """No charged/provider effects in guarded denial paths; no ambiguous resubmit."""

    def setUp(self):
        self.request = SimpleNamespace(mode="text_to_image", modelProfile="flux_klein_4b",
            width=512, height=512, prompt="A small friendly robot", steps=4, loras=[], seed=2414)
        self.inv = {"diffusion_models": [native.MODEL], "text_encoders": [native.ENCODER],
                    "vaes": [native.VAE]}
        self.submit_calls = 0
        self.download_calls = 0

    async def good_available(self):
        return True

    async def good_inventory(self):
        return self.inv

    async def submitted(self, graph, job):
        self.submit_calls += 1
        return "test-prompt-id", {"status": "completed"}, [{"filename": "local4b_00001_.png"}]

    async def downloaded(self, item, job_id):
        self.download_calls += 1
        return "/isolated/media/result.png", "/isolated/media/thumb.png"

    def _run(self, *, available=None, inventory=None, enabled=None, submit=None):
        return asyncio.run(native.execute_request(
            self.request, {"id": "test-job-214"},
            available=available or self.good_available,
            inventory=inventory or self.good_inventory,
            enabled=(lambda: True) if enabled is None else enabled,
            submit=submit or self.submitted,
            download=self.downloaded,
            result_factory=lambda **kwargs: kwargs))

    def test_offline_missing_checkpoint_and_admin_off_do_not_submit(self):
        async def offline():
            return False
        async def missing():
            return {"diffusion_models": [], "text_encoders": [], "vaes": []}
        for case in [
            {"available": offline},
            {"inventory": missing},
            {"enabled": lambda: False},
        ]:
            with self.subTest(case=list(case)[0]):
                with self.assertRaises(RuntimeError):
                    self._run(**case)
                self.assertEqual(self.submit_calls, 0)
                self.assertEqual(self.download_calls, 0)

    def test_unknown_outcome_does_not_retry_or_save_fake_media(self):
        async def outage(graph, job):
            self.submit_calls += 1
            raise TimeoutError("network response lost after submission")
        with self.assertRaises(TimeoutError):
            self._run(submit=outage)
        self.assertEqual(self.submit_calls, 1)
        self.assertEqual(self.download_calls, 0)

    def test_mock_success_returns_persistent_worker_result_shape_only(self):
        result = self._run()
        self.assertEqual(self.submit_calls, 1)
        self.assertEqual(self.download_calls, 1)
        self.assertEqual(result["prompt_id"], "test-prompt-id")
        self.assertTrue(result["image_path"].endswith("result.png"))


if __name__ == "__main__":
    unittest.main()
