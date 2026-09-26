from __future__ import annotations
from pathlib import Path
import socket
import unittest
from tools.test_health_pytest_plugin import (
    NetworkGuard,
    OutboundNetworkBlocked,
    TelemetryState,
    classify_host,
)
class TestHealthPytestPluginTests(unittest.TestCase):
    def test_loopback_is_allowed_by_guard(self) -> None:
        state = TelemetryState(active_nodeid="tools/test_plugin.py::test_loopback")
        state.check("create_connection", ("127.0.0.1", 8080))
        state.check("getaddrinfo", "::1", port=80)
        self.assertEqual([item["blocked"] for item in state.attempts], [False, False])
        self.assertEqual([item["classification"] for item in state.attempts], ["loopback", "loopback"])
    def test_synthetic_external_provider_is_blocked_before_real_network(self) -> None:
        state = TelemetryState(active_nodeid="tools/test_plugin.py::test_external")
        with self.assertRaises(OutboundNetworkBlocked):
            state.check("create_connection", ("api.openrouter.ai", 443))
        self.assertEqual(
            state.attempts,
            [{
                "testNodeid": "tools/test_plugin.py::test_external",
                "operation": "create_connection",
                "host": "api.openrouter.ai",
                "port": 443,
                "classification": "external",
                "blocked": True,
            }],
        )
    def test_numeric_external_ip_is_blocked(self) -> None:
        state = TelemetryState()
        with self.assertRaises(OutboundNetworkBlocked):
            state.check("socket.connect", ("8.8.8.8", 53), family=socket.AF_INET)
        self.assertEqual(state.attempts[0]["classification"], "external")
    def test_local_ipc_is_allowed(self) -> None:
        if not hasattr(socket, "AF_UNIX"): self.skipTest("AF_UNIX unavailable")
        state = TelemetryState()
        state.check("socket.connect", "/tmp/izo.sock", family=socket.AF_UNIX)
        self.assertEqual(state.attempts[0]["classification"], "local_ipc")
        self.assertFalse(state.attempts[0]["blocked"])
    def test_retry_payload_zero_is_observable_not_inferred(self) -> None:
        payload = TelemetryState().payload()
        self.assertEqual(payload["retry"]["observability"], "AVAILABLE")
        self.assertEqual(payload["retry"]["rerunReports"], 0)
        self.assertEqual(payload["retry"]["rerunNodeids"], [])
        self.assertEqual(payload["retry"]["flakyStatus"], "NO_PYTEST_RERUN_EVENTS_OBSERVED")
        self.assertEqual(payload["retry"]["repeatRunNondeterminism"], "NOT_MEASURED")
    def test_rerun_reports_are_counted_from_hook_state(self) -> None:
        state = TelemetryState(rerun_nodeids=["a::test_x", "a::test_x", "b::test_y"])
        payload = state.payload()
        self.assertEqual(payload["retry"]["rerunReports"], 3)
        self.assertEqual(payload["retry"]["rerunNodeids"], ["a::test_x", "b::test_y"])
        self.assertEqual(payload["retry"]["flakyStatus"], "PYTEST_RERUN_EVENTS_OBSERVED")
    def test_host_classification_is_bounded(self) -> None:
        self.assertEqual(classify_host("localhost"), "loopback")
        self.assertEqual(classify_host("127.9.8.7"), "loopback")
        self.assertEqual(classify_host("::1"), "loopback")
        self.assertEqual(classify_host("api.openrouter.ai"), "external")

    def test_plugin_is_observation_only(self) -> None:
        source = Path(__file__).with_name("test_health_pytest_plugin.py").read_text(encoding="utf-8")
        forbidden = (
            "backend/test_",
            "deterministic_provider_test_fakes",
            "EXCHANGE_FIXTURE_NODES",
            "CAPABILITY_FIXTURE_NODES",
            "import main",
            "monkeypatch",
            "fetch_openrouter_image_capabilities",
            "refresh_openrouter_catalog",
            "_saved_setting",
            "from datetime import",
            "@pytest.fixture",
        )
        for token in forbidden:
            with self.subTest(token=token):
                self.assertNotIn(token, source)
if __name__ == "__main__":
    unittest.main()
