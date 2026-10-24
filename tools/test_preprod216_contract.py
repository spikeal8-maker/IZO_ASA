"""Fail-closed static contract checks for isolated preprod #216."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
OPS = ROOT / "ops" / "docker" / "dev"


class Preprod216ContractTests(unittest.TestCase):
    def test_guard_does_not_expand_general_internet_egress(self):
        path = OPS / "network_guard.preprod216.py"
        spec = importlib.util.spec_from_file_location("preprod216_guard", path)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.validate_policy(module.RULES)
        self.assertIn("policy drop;", module.RULES)
        self.assertIn("ip daddr 10.249.221.3 tcp dport 3128 accept", module.RULES)
        self.assertNotIn("ip daddr 0.0.0.0", module.RULES)
        self.assertNotIn("10.249.211.3", module.RULES)
        self.assertEqual(module.RULES.count("tcp dport"), 1)
        context = (OPS / "Dockerfile.guard.preprod216.dockerignore").read_text(
            encoding="utf-8"
        )
        self.assertIn("!ops/docker/dev/network_guard.preprod216.py", context)
        self.assertIn("**/secrets/**", context)

    def test_overlay_separates_candidate_volumes_and_ports(self):
        text = (OPS / "compose.preprod216.yml").read_text(encoding="utf-8")
        for fragment in (
            "10.249.221.0/28",
            "10.249.221.2",
            "10.249.221.3",
            "127.0.0.1:",
            "COMFYUI_NATIVE4B_ONLY:",
            'IZO_PREPROD_PRESERVE_HISTORY: "1"',
            "COMFYUI_MOCK_FALLBACK:",
            "OPENROUTER_BASE_URL: https://openrouter.ai/api/v1",
            "HTTPS_PROXY: http://10.249.221.3:3128",
            "OLLAMA_BASE_URL: http://127.0.0.1:1",
            "openrouter-secrets:",
            "openrouter-master:",
            "seed-data:",
            "preprod216-guard:",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, text)
        for forbidden in (
            "izo-asa-restore-20261024_sqlite-data",
            "izo-asa-shadow-or-210_openrouter-secrets",
            "izo-asa-shadow-comfy-214_sqlite-data",
            "host.docker.internal",
            "network_mode: host",
            "0.0.0.0:",
        ):
            self.assertNotIn(forbidden, text)

    def test_own_agent_is_pinned_to_dedicated_loopback(self):
        source = (ROOT / "ops" / "windows" / "preprod216_comfy_agent.py").read_text(
            encoding="utf-8"
        )
        launcher = (ROOT / "ops" / "windows" / "start-preprod216-comfy-agent.ps1").read_text(
            encoding="utf-8"
        )
        self.assertIn('http://127.0.0.1:48316', source)
        self.assertIn('http://127.0.0.1:8188', source)
        self.assertIn('http://127.0.0.1:48316', launcher)
        self.assertIn('IZO_ASA_Preprod216Runtime', launcher)
        self.assertIn('preprod216_comfy_agent.py', launcher)
        self.assertNotIn('IZO_ASA_Comfy214Runtime', launcher)
        self.assertNotIn('http://127.0.0.1:48216', source)
        self.assertIn('validate_bridge_route(method, path, body)', source)
        self.assertIn('HOST_ENDPOINT_NOT_LOOPBACK_ALLOWLIST', source)
        self.assertIn('HOST_BRIDGE_STATE_INVALID', source)

    def test_restore_cloner_never_touches_baseline_and_rejects_nonempty(self):
        text = (ROOT / "tools" / "preprod216_restore_clone.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('DESTINATION_VOLUME_NOT_EMPTY', text)
        self.assertIn('COPIED_MEDIA_SHA_MISMATCH', text)
        self.assertIn('BASELINE_DB_SHA_MISMATCH', text)
        self.assertIn('auth_sessions', text)
        self.assertIn('revoke_reason=', text)
        self.assertIn('DISABLED_SIDE_EFFECT_SETTINGS', text)
        self.assertNotIn('UPDATE users SET role=', text)
        verifier = (ROOT / "tools" / "preprod216_verify_runtime.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("mode=ro&immutable=1", verifier)


if __name__ == "__main__":
    unittest.main()
