"""Safety checks for opting a real backend into the bounded wire fixture."""
import json
from pathlib import Path
import tempfile
import unittest

from tools.docker_shadow_fixture import (DISABLED_ENDPOINTS, MARKER, SECRET_KEYS,
                                         validate_environment, write_receipt)


def safe_environment():
    return {"IZO_SHADOW_FIXTURE": MARKER, "APP_ENV": "test", "ENV": "test",
            "MODE": "test", "BOT_MODE": "disabled", "MAX_UPDATES_MODE": "disabled",
            "COMFYUI_BASE_URL": "http://127.0.0.1:48991", "COMFYUI_MOCK_FALLBACK": "false",
            **{key: "http://127.0.0.1:1" for key in DISABLED_ENDPOINTS},
            **{key: "" for key in SECRET_KEYS}}


class FixtureEntrypointTests(unittest.TestCase):
    def test_requires_explicit_safe_profile(self):
        safe = safe_environment()
        validate_environment(safe)
        for key, value in (("IZO_SHADOW_FIXTURE", ""), ("APP_ENV", "production"),
                           ("COMFYUI_MOCK_FALLBACK", "true"), ("BOT_MODE", "polling")):
            with self.subTest(key=key), self.assertRaisesRegex(RuntimeError, "PROFILE_REQUIRED"):
                validate_environment({**safe, key: value})

    def test_real_endpoint_or_credentials_are_rejected(self):
        for key in DISABLED_ENDPOINTS:
            with self.subTest(key=key), self.assertRaisesRegex(RuntimeError, "ENDPOINT_FORBIDDEN"):
                validate_environment({**safe_environment(), key: "https://example.invalid"})
        for key in SECRET_KEYS:
            with self.subTest(key=key), self.assertRaisesRegex(RuntimeError, "CREDENTIAL_FORBIDDEN"):
                validate_environment({**safe_environment(), key: "unit-fixture-value"})

    def test_atomic_receipt_does_not_serialize_provider_object(self):
        class Provider:
            control_token = "private-control-capability"

            def receipt(self):
                return {"counts": {"accepted": 2}, "jobs": [], "model_execution": False}

        with tempfile.TemporaryDirectory(prefix="izo-fixture-test-") as folder:
            path = Path(folder) / "receipt.json"
            write_receipt(Provider(), path)
            first = path.read_text(encoding="utf-8")
            self.assertNotIn(Provider.control_token, first)
            self.assertEqual(json.loads(first)["provider"]["counts"]["accepted"], 2)
            write_receipt(Provider(), path)
            self.assertEqual(path.read_text(encoding="utf-8"), first)
            self.assertFalse(path.with_suffix(".tmp").exists())


if __name__ == "__main__":
    unittest.main()
