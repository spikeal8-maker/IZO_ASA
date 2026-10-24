"""Regression guards for model x plan x provider resolution intersections.

Pure tests; no persistent database, network, GPU, or paid generation.
"""
from __future__ import annotations

import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent / 'app' / 'services'))
from image_model_publication import public_access_for_plan


PLAN_RESOLUTIONS = {
    "free": ["sq-sd"],
    "mini": ["sq-sd", "sq-hd"],
    "plus": ["sq-sd", "sq-hd", "h-fhd"],
    "pro": ["sq-sd", "sq-hd", "h-fhd"],
    "business": ["sq-sd", "sq-hd", "h-fhd", "sq-4k"],
}
CLOUD_MODEL = "vendor/cloud-image"
LOCAL_MODEL = "server:local_flux_klein"


def model_option(model_id, _capability):
    return {
        "id": model_id,
        "provider": "comfyui" if model_id == LOCAL_MODEL else "openrouter",
        "supportedResolutionIds": ["sq-sd"] if model_id == LOCAL_MODEL else ["sq-hd", "h-fhd", "sq-4k"],
    }


def access(plan, resolutions=None, enabled_cloud=True):
    config = {
        "published": [CLOUD_MODEL] if enabled_cloud else [],
        "enabled": {"text_to_image": [CLOUD_MODEL], "image_to_image": [CLOUD_MODEL]} if enabled_cloud else {},
        "access": {
            mode: {tier: [CLOUD_MODEL] for tier in PLAN_RESOLUTIONS}
            for mode in ("text_to_image", "image_to_image")
        } if enabled_cloud else {},
    }
    return public_access_for_plan(
        plan,
        valid_plans=PLAN_RESOLUTIONS,
        tariff={
            "allowed_resolutions": PLAN_RESOLUTIONS[plan] if resolutions is None else resolutions,
            "model_defaults": {"fast": LOCAL_MODEL, "max": CLOUD_MODEL},
        },
        config=config,
        capability_catalog=[
            {"id": CLOUD_MODEL, "modes": ["text_to_image", "image_to_image"]}
        ],
        mode_labels={"text_to_image": "Text to image", "image_to_image": "Image to image"},
        quality_presets=("fast", "max"),
        option_builder=model_option,
        quality_model=lambda *_: None,
        local_model_modes=("text_to_image",),
    )


class EffectiveResolutionAccessTests(unittest.TestCase):
    def test_native_local_preset_is_square_only_for_all_five_plans(self):
        for plan in PLAN_RESOLUTIONS:
            with self.subTest(plan=plan):
                row = access(plan)["modes"]["text_to_image"]
                local = next(item for item in row["models"] if item["id"] == LOCAL_MODEL)
                self.assertEqual(local["supportedResolutionIds"], ["sq-sd"])

    def test_cloud_resolution_matrix_respects_plan(self):
        expected = {
            "free": [],
            "mini": ["sq-hd"],
            "plus": ["sq-hd", "h-fhd"],
            "pro": ["sq-hd", "h-fhd"],
            "business": ["sq-hd", "h-fhd", "sq-4k"],
        }
        for plan, expected_resolutions in expected.items():
            with self.subTest(plan=plan):
                models = access(plan)["modes"]["text_to_image"]["models"]
                cloud = next((item for item in models if item["id"] == CLOUD_MODEL), None)
                self.assertEqual(cloud["supportedResolutionIds"] if cloud else [], expected_resolutions)

    def test_native_adapter_does_not_advertise_unsupported_edit(self):
        for plan in PLAN_RESOLUTIONS:
            with self.subTest(plan=plan):
                models = access(plan)["modes"]["image_to_image"]["models"]
                self.assertFalse(any(item["id"] == LOCAL_MODEL for item in models))

    def test_no_common_resolution_has_no_models_or_fake_fallback(self):
        row = access("pro", resolutions=["v-sd"])["modes"]["text_to_image"]
        self.assertEqual(row["models"], [])
        self.assertEqual(row["presets"], {"fast": "", "max": ""})

    def test_disable_cloud_does_not_resurrect_cloud_from_defaults(self):
        row = access("pro", enabled_cloud=False)["modes"]["text_to_image"]
        self.assertEqual([item["id"] for item in row["models"]], [LOCAL_MODEL])
        self.assertEqual(row["presets"]["max"], LOCAL_MODEL)


if __name__ == "__main__":
    unittest.main()
