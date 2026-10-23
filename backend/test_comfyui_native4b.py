from __future__ import annotations

import copy
import unittest

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

    def test_inventory_requirements(self):
        data = {"diffusion_models": [native.MODEL],
                "text_encoders": [native.ENCODER],
                "vaes": [native.VAE]}
        self.assertTrue(native.validate_model_inventory(data))
        self.assertFalse(native.validate_model_inventory({**data, "vaes": []}))


if __name__ == "__main__":
    unittest.main()
