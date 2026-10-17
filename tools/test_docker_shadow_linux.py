"""Linux wiring contracts only; no Docker daemon, live provider or host mutation."""
from __future__ import annotations

import copy
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from tools import docker_shadow as lifecycle
from tools import docker_shadow_executor as execution
from tools import docker_shadow_smoke as smoke

SHA = "a" * 40
PROJECT = "izo-asa-shadow-linux-unit"
MACHINE = "b" * 64
ENGINE = "01234567-89ab-cdef-0123-456789abcdef"
IDENTITY = {"executor_context": "default", "engine_id": ENGINE, "machine_sha256": MACHINE}


def boundary_snapshot():
    return {"scope": "ISOLATED_GUEST_ONLY", "identity": {
        "context": "default", "engineId": ENGINE, "machineIdentitySha256": MACHINE},
        "foreignResources": {"container": [], "network": [], "volume": []},
        "productionUnchanged": "NOT_VERIFIED_HERE"}


def fixture_config():
    app = {"network_mode": "service:guard", "labels": {"io.izo.owner": lifecycle.OWNER},
           "user": "10001:10001", "cap_drop": ["ALL"],
           "security_opt": ["no-new-privileges:true"],
           "depends_on": {"guard": {"condition": "service_healthy"}}}
    backend = copy.deepcopy(app)
    backend.update(command=["python", "/opt/izo/fixtures/docker_shadow_fixture.py"],
                   environment={"IZO_SHADOW_FIXTURE": "controlled-comfyui-v1",
                                "COMFYUI_BASE_URL": "http://127.0.0.1:48991",
                                "COMFYUI_MOCK_FALLBACK": "false"})
    guard = {"networks": {"shadow": {}}, "dns": ["127.0.0.1"],
             "labels": {"io.izo.owner": lifecycle.OWNER}, "cap_drop": ["ALL"],
             "security_opt": ["no-new-privileges:true"],
             "healthcheck": {"test": ["CMD", "python", "/network_guard.py", "--check"]}}
    return {"services": {"backend": backend, "web": app, "guard": guard},
            "networks": {"shadow": {}}}


class LinuxLifecycleTests(unittest.TestCase):
    def test_desktop_default_is_unchanged(self):
        shadow = lifecycle.Shadow(PROJECT, SHA)
        shadow.run = Mock(return_value="desktop-result")
        self.assertIsNone(shadow.executor)
        self.assertEqual(shadow.docker("ps", "-aq"), "desktop-result")
        shadow.run.assert_called_once_with(["docker", "--context", "desktop-linux", "ps", "-aq"])
        self.assertEqual([p.name for p in shadow.files], ["compose.yml", "compose.shadow.yml"])

    def test_linux_adapter_gets_all_pins_and_sanitized_runner(self):
        with patch.object(execution, "IsolatedExecutor") as factory:
            shadow = lifecycle.Shadow(PROJECT, SHA, fixture=True, **IDENTITY)
            factory.assert_called_once_with(shadow.run, context="default", engine_id=ENGINE,
                                            machine_sha256=MACHINE)
            self.assertIs(shadow.executor, factory.return_value)
            shadow.docker("compose", "config", timeout=7)
            shadow.executor.docker.assert_called_once_with("compose", "config", timeout=7)
        self.assertEqual(shadow.files[-1].name, "compose.acceptance.yml")

    def test_partial_pins_fail_before_a_command(self):
        for missing in IDENTITY:
            values = {name: value for name, value in IDENTITY.items() if name != missing}
            with self.subTest(missing=missing), patch.object(lifecycle.subprocess, "run") as command:
                with self.assertRaisesRegex(lifecycle.ShadowError, "EXECUTOR_IDENTITY_REQUIRED"):
                    lifecycle.Shadow(PROJECT, SHA, **values)
                command.assert_not_called()

    def test_guest_change_is_rejected_before_any_docker_command(self):
        with patch.object(execution, "guest_identity", return_value="c" * 64), \
             patch.object(lifecycle.subprocess, "run") as command:
            shadow = lifecycle.Shadow(PROJECT, SHA, **IDENTITY)
            with self.assertRaisesRegex(execution.ExecutorError, "GUEST_CHANGED"):
                shadow.docker("compose", "up")
            command.assert_not_called()

    def test_fixture_guard_refuses_wrong_target_fallback_or_command(self):
        for change in ("target", "fallback", "marker", "command"):
            config = fixture_config()
            backend = config["services"]["backend"]
            if change == "target":
                backend["environment"]["COMFYUI_BASE_URL"] = "http://198.51.100.1:48991"
            elif change == "fallback":
                backend["environment"]["COMFYUI_MOCK_FALLBACK"] = "true"
            elif change == "marker":
                backend["environment"].pop("IZO_SHADOW_FIXTURE")
            else:
                backend["command"] = ["python", "other.py"]
            shadow = lifecycle.Shadow(PROJECT, SHA, fixture=True)
            shadow.compose = Mock(return_value=json.dumps(config))
            with self.subTest(change=change), self.assertRaisesRegex(lifecycle.ShadowError, "FIXTURE_CONFIG_INVALID"):
                shadow.config()
        shadow.compose = Mock(return_value=json.dumps(fixture_config()))
        self.assertEqual(shadow.config(), fixture_config())

    def test_ambient_routing_and_provider_values_are_still_dropped(self):
        ambient = {name: "private-sentinel" for name in (
            "DOCKER_HOST", "DOCKER_CONTEXT", "COMPOSE_FILE", "OPENROUTER_API_KEY",
            "COMFYUI_BASE_URL", "IZO_SHADOW_FIXTURE", "HTTP_PROXY")}
        with patch.dict(lifecycle.os.environ, ambient):
            shadow = lifecycle.Shadow(PROJECT, SHA, fixture=True, **IDENTITY)
        self.assertFalse(set(ambient) & set(shadow.env))
        self.assertNotIn("private-sentinel", shadow.env.values())

    def test_cli_requires_explicit_linux_mode_and_complete_pins(self):
        base = ["docker_shadow", "config", "--project", PROJECT, "--source-sha", SHA]
        pins = ["--executor-context", "default", "--engine-id", ENGINE, "--machine-sha256", MACHINE]
        for extra in (["--isolated-linux"], pins, ["--engine-id", ENGINE]):
            with self.subTest(extra=extra), patch.object(sys, "argv", base + extra), \
                 patch.object(lifecycle, "Shadow") as factory:
                self.assertEqual(lifecycle.main(), 1)
                factory.assert_not_called()
        with patch.object(sys, "argv", base + ["--isolated-linux", "--fixture"] + pins), \
             patch.object(lifecycle, "Shadow") as factory:
            self.assertEqual(lifecycle.main(), 0)
            factory.assert_called_once_with(PROJECT, SHA, 48125, 48126, fixture=True, **IDENTITY)


class GatewayEvidenceTests(unittest.TestCase):
    def make_shadow(self, *, isolated=True, positive="LISTENER_REACHABLE"):
        network = PROJECT + "_shadow"
        guard = {"Id": "guard-id", "Image": "sha256:" + "d" * 64,
                 "Config": {"Labels": {"com.docker.compose.service": "guard"}},
                 "NetworkSettings": {"Networks": {network: {}}}}
        peer = {"Config": {"Labels": {"io.izo.owner": lifecycle.OWNER, "io.izo.project": PROJECT}},
                "NetworkSettings": {"Networks": {network: {"IPAddress": "172.28.0.2"}}}}
        def docker(*args, **kwargs):
            if args[:2] == ("network", "inspect"):
                return json.dumps([{"IPAM": {"Config": [{"Gateway": "172.28.0.1"}]}}])
            if args[0] == "ps":
                return ""
            if args[:2] == ("run", "-d"):
                return "peer-id"
            if args[:2] == ("run", "--rm"):
                return positive
            if args == ("inspect", "peer-id"):
                return json.dumps([peer])
            if args == ("rm", "-f", "peer-id"):
                return ""
            raise AssertionError("Unexpected Docker command")
        return SimpleNamespace(project=PROJECT, executor=object() if isolated else None,
                               containers=Mock(return_value=[guard]), docker=Mock(side_effect=docker))

    def listener(self):
        value = Mock(address="172.28.0.1", port=49123, accepted=1)
        value.thread.is_alive.return_value = True
        context = Mock()
        context.__enter__ = Mock(return_value=value)
        context.__exit__ = Mock(return_value=False)
        return context

    def test_linux_positive_gateway_control_and_all_kernel_drops_are_required(self):
        shadow, listener = self.make_shadow(), self.listener()
        counter = iter(range(20))
        with patch.object(execution, "GatewayListener", return_value=listener) as factory, \
             patch.object(smoke, "kernel_policy", side_effect=lambda *_: {"blockedPackets": next(counter)}), \
             patch.object(smoke, "exec_json", side_effect=lambda *_: {"connected": False, "timeout": True, "errno": None}):
            result = smoke.egress_proof(shadow, "backend-id")
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["controlledGatewayProbe"], "PASS")
        self.assertEqual(result["probes"]["gateway"]["port"], 49123)
        self.assertEqual(set(result["probes"]), {"gateway", "bridgePeer", "external"})
        self.assertTrue(all(p["blockedPacketDelta"] > 0 for p in result["probes"].values()))
        factory.assert_called_once_with(shadow.executor, PROJECT, seconds=60)
        controls = [call for call in shadow.docker.call_args_list if call.args[:2] == ("run", "--rm")]
        self.assertEqual(len(controls), 2)
        self.assertIn("172.28.0.1", controls[1].args[-1])
        listener.__exit__.assert_called_once()
        self.assertEqual(shadow.docker.call_args.args, ("rm", "-f", "peer-id"))

    def test_refusal_or_missing_drop_count_cannot_pass_and_probe_is_cleaned(self):
        for no_counter in (False, True):
            shadow = self.make_shadow()
            counter = iter(range(20))
            policy = lambda *_: {"blockedPackets": 0 if no_counter else next(counter)}
            response = {"connected": False, "timeout": no_counter, "errno": None if no_counter else 111}
            with self.subTest(no_counter=no_counter), \
                 patch.object(execution, "GatewayListener", return_value=self.listener()), \
                 patch.object(smoke, "kernel_policy", side_effect=policy), \
                 patch.object(smoke, "exec_json", side_effect=lambda *_: dict(response)):
                with self.assertRaisesRegex(RuntimeError, "NOT_BLOCKED_BY_POLICY"):
                    smoke.egress_proof(shadow, "backend-id")
            self.assertEqual(shadow.docker.call_args.args, ("rm", "-f", "peer-id"))

    def test_missing_positive_control_fails_before_negative_probes(self):
        shadow = self.make_shadow(positive="")
        with patch.object(smoke, "kernel_policy", return_value={"blockedPackets": 1}), \
             patch.object(smoke, "exec_json") as probe:
            with self.assertRaisesRegex(RuntimeError, "CONTROL_LISTENER_NOT_READY"):
                smoke.egress_proof(shadow, "backend-id")
        probe.assert_not_called()
        self.assertEqual(shadow.docker.call_args.args, ("rm", "-f", "peer-id"))

    def test_desktop_retains_gateway_blocker_and_never_starts_linux_listener(self):
        shadow = self.make_shadow(isolated=False)
        counter = iter(range(20))
        with patch.object(execution, "GatewayListener") as listener, \
             patch.object(smoke, "kernel_policy", side_effect=lambda *_: {"blockedPackets": next(counter)}), \
             patch.object(smoke, "exec_json", side_effect=lambda *_: {"connected": False, "timeout": True, "errno": None}):
            result = smoke.egress_proof(shadow, "backend-id")
        self.assertEqual(result["controlledGatewayProbe"], "GATEWAY_LISTENER_PROOF_BLOCKED")
        self.assertNotEqual(result["status"], "PASS")
        listener.assert_not_called()


class ReceiptBoundaryTests(unittest.TestCase):
    def make_shadow(self, after=None, *, isolated=True):
        executor = SimpleNamespace(foreign_snapshot=Mock(side_effect=[boundary_snapshot(), after or boundary_snapshot()]))
        return SimpleNamespace(project=PROJECT, sha=SHA, executor=executor if isolated else None,
                               source_guard=Mock(), up=Mock(), config=Mock(return_value={}),
                               docker=Mock(return_value="resource-sample"))

    def run_proof(self, shadow, receipt, *, egress_error=None, desktop=False, build=True):
        production = types.ModuleType("tools.docker_shadow_evidence")
        production.snapshot = Mock(return_value={"status": "CAPTURED"}) if desktop else Mock(side_effect=AssertionError("Production must not be read"))
        production.compare = Mock(return_value={"status": "PROVEN"})
        containers = {name: {"container": name + "-id"} for name in ("backend", "web", "guard")}
        with patch.dict(sys.modules, {"tools.docker_shadow_evidence": production}), \
             patch.object(smoke, "inspect_stack", return_value=containers), \
             patch.object(smoke, "http_proof", return_value={"/": 200}), \
             patch.object(smoke, "fixture", return_value={"fixtureRow": "fixed"}), \
             patch.object(smoke, "egress_proof", side_effect=egress_error, return_value={"status": "PASS"}):
            smoke.prove(shadow, receipt, build=build)
        if not desktop:
            production.snapshot.assert_not_called()

    def test_linux_receipt_compares_guest_resources_and_recreates_once(self):
        shadow = self.make_shadow()
        with tempfile.TemporaryDirectory() as directory:
            receipt = Path(directory) / "topology.json"
            self.run_proof(shadow, receipt)
            result = json.loads(receipt.read_text())
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["executorComparison"]["status"], "PASS")
        self.assertEqual(result["productionUnchanged"], "NOT_VERIFIED_HERE")
        self.assertNotIn("productionBefore", result)
        self.assertEqual(shadow.up.call_count, 2)
        shadow.up.assert_called_with(build=False, recreate=True)

    def test_prebuilt_driver_can_skip_build_without_skipping_start_guards(self):
        shadow = self.make_shadow()
        with tempfile.TemporaryDirectory() as directory:
            self.run_proof(shadow, Path(directory) / "prebuilt.json", build=False)
        self.assertEqual(shadow.up.call_args_list[0].kwargs, {"build": False})
        shadow.up.assert_called_with(build=False, recreate=True)
        shadow.source_guard.assert_called_once()

    def test_foreign_resource_change_is_preserved_as_failure(self):
        changed = boundary_snapshot()
        changed["foreignResources"]["volume"] = [{"id": "foreign", "name": "foreign"}]
        shadow = self.make_shadow(after=changed)
        with tempfile.TemporaryDirectory() as directory:
            receipt = Path(directory) / "failed.json"
            with self.assertRaisesRegex(RuntimeError, "FAIL"):
                self.run_proof(shadow, receipt)
            result = json.loads(receipt.read_text())
        self.assertEqual(result["status"], "FAIL")
        self.assertFalse(result["executorComparison"]["checks"]["foreignResources"])

    def test_failure_still_records_original_error_and_after_snapshot(self):
        shadow = self.make_shadow()
        with tempfile.TemporaryDirectory() as directory:
            receipt = Path(directory) / "failed.json"
            with self.assertRaisesRegex(RuntimeError, "FAIL"):
                self.run_proof(shadow, receipt, egress_error=RuntimeError("WIRE_PROBE_FAILED"))
            result = json.loads(receipt.read_text())
        self.assertIn("WIRE_PROBE_FAILED", result["error"])
        self.assertEqual(result["executorComparison"]["status"], "PASS")
        self.assertEqual(result["status"], "FAIL")

    def test_desktop_smoke_remains_blocked_even_if_other_checks_pass(self):
        shadow = self.make_shadow(isolated=False)
        with tempfile.TemporaryDirectory() as directory:
            receipt = Path(directory) / "desktop.json"
            with self.assertRaisesRegex(RuntimeError, "GATEWAY_LISTENER_PROOF_BLOCKED"):
                self.run_proof(shadow, receipt, desktop=True)
            result = json.loads(receipt.read_text())
        self.assertEqual(result["status"], "GATEWAY_LISTENER_PROOF_BLOCKED")
        self.assertEqual(result["productionComparison"]["status"], "PROVEN")
        self.assertNotIn("executorBefore", result)


if __name__ == "__main__":
    unittest.main()
