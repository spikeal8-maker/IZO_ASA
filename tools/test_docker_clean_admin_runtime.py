"""Profile admission, private output and cleanup contracts; no Docker is run here."""
from __future__ import annotations

from contextlib import ExitStack
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from tools import docker_clean_admin_runtime as runtime
from tools import docker_clean_install as driver
from tools.agent_system.env_runtime import EMPTY_CREDENTIAL_KEYS
from tools.docker_shadow import Shadow

SHA = "a" * 40
CODE = "B" * 48
ENGINE = "isolated-fixture-engine-01"
MACHINE = "b" * 64


class AdminRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        overlay = self.root / "ops/docker/dev/compose.admin-acceptance.yml"
        overlay.parent.mkdir(parents=True)
        overlay.write_text('{"services":{"backend":{"environment":{}}}}\n', encoding="utf-8")
        self.source = Shadow("izo-asa-shadow-runtime-test", SHA, root=self.root, fixture=True,
            executor_context="default", engine_id=ENGINE, machine_sha256=MACHINE)
        self.instances = []
        self.config_mutation = None
        self.source_error = None
        self.before = {"ownedFixture": "foreign-before"}
        self.after = {"ownedFixture": "foreign-after"}
        self.cleanup = Mock(return_value={"status": "PASS", "remaining": {}})
        self.compare = Mock(return_value={"status": "PASS"})
        self.fresh = Mock()
        self.api = Mock(return_value={"status": "PASS", "sessionCleanup": {"sessionCleanup": "PASS"}})

    def factory(self, *args, **kwargs):
        case = self

        class FixtureShadow(Shadow):
            def config(self):
                env = {**{key: "" for key in EMPTY_CREDENTIAL_KEYS},
                       "APP_ENV": "test", "ENV": "test", "MODE": "test",
                       "IZO_SHADOW_FIXTURE": "controlled-comfyui-v1",
                       "COMFYUI_BASE_URL": "http://127.0.0.1:48991", "COMFYUI_MOCK_FALLBACK": "false",
                       "ADMIN_ONE_TIME_CODE": "", "BILLING_SIMULATOR_ENABLED": "false",
                       "PUBLIC_SITE_URL": ""}
                result = {"services": {"backend": {
                    "command": ["python", "/opt/izo/fixtures/docker_shadow_fixture.py"],
                    "environment": env}}}
                if any(path.name == "compose.admin-acceptance.yml" for path in self.files):
                    env.update(ADMIN_ONE_TIME_CODE=self.env["IZO_ACCEPTANCE_ADMIN_CODE"],
                               BILLING_SIMULATOR_ENABLED="true",
                               PUBLIC_SITE_URL=f"http://127.0.0.1:{self.web_port}")
                    if case.config_mutation:
                        case.config_mutation(result)
                return result

            def source_guard(self):
                if case.source_error:
                    raise case.source_error
                self.source_checked = True

            def compose(self, *args, **kwargs):
                case.assertEqual(args[:1], ("logs",))
                case.assertTrue(kwargs.get("capture"))
                return "fixture startup " + CODE

        instance = FixtureShadow(*args, **kwargs)
        instance.executor.foreign_snapshot = Mock(side_effect=[self.before, self.after])
        self.instances.append(instance)
        return instance

    def proof(self, shadow, path, **kwargs):
        self.assertTrue(shadow.source_checked)
        self.assertFalse(kwargs["build"])
        self.assertEqual(kwargs["expected_ephemeral_admin_code"], CODE)
        self.assertEqual(shadow.env["IZO_ACCEPTANCE_ADMIN_CODE"], CODE)
        self.fresh.assert_called_once_with(shadow)
        path.write_text('{"status":"PASS"}\n', encoding="utf-8")

    def run_probe(self, *, proof=None):
        with ExitStack() as stack:
            stack.enter_context(patch.object(runtime, "CapturedAdminShadow", side_effect=self.factory))
            stack.enter_context(patch.object(runtime.secrets, "token_urlsafe", return_value=CODE))
            proof_mock = stack.enter_context(patch.object(runtime, "prove", side_effect=proof or self.proof))
            stack.enter_context(patch.object(runtime, "prove_admin", self.api))
            stack.enter_context(patch.object(runtime, "compare_isolated", self.compare))
            stack.enter_context(patch.object(driver, "ports", return_value=(48001, 48002)))
            stack.enter_context(patch.object(driver, "require_fresh", self.fresh))
            stack.enter_context(patch.object(driver, "cleanup_owned", self.cleanup))
            stack.enter_context(patch.object(driver, "telemetry", return_value={"fixture": "sample"}))
            result = runtime.rehearse_admin(self.source, self.root / "evidence")
        return result, proof_mock

    def assert_private(self):
        for path in (self.root / "evidence").iterdir():
            if path.is_file():
                self.assertNotIn(CODE, path.read_text(encoding="utf-8"), path.name)
        self.assertNotIn("IZO_ACCEPTANCE_ADMIN_CODE", self.instances[0].env)

    def test_fresh_profile_proves_topology_before_normal_admin_api_and_cleans_up(self):
        result, proof = self.run_probe()
        self.assertEqual(result["status"], "PASS")
        proof.assert_called_once()
        attestation = self.api.call_args.args[0]
        self.assertTrue(attestation["freshData"] and attestation["networkEgressDenied"])
        self.assertEqual(attestation["project"], self.source.project + "-admin")
        self.assertEqual(attestation["origin"], "http://127.0.0.1:48001")
        self.assertEqual(self.api.call_args.kwargs, {"bootstrap_code": CODE})
        self.cleanup.assert_called_once_with(self.instances[0], True)
        self.compare.assert_called_once_with(self.before, self.after)
        self.assertEqual(len(result["configSha256"]), 64)
        self.assertEqual(len(result["overlaySha256"]), 64)
        self.assert_private()

    def test_any_extra_resolved_config_change_fails_before_mutation(self):
        self.config_mutation = lambda config: config.update(unrequested="change")
        result, proof = self.run_probe()
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["failedStage"], "admission")
        self.fresh.assert_not_called()
        proof.assert_not_called()
        self.api.assert_not_called()
        self.cleanup.assert_not_called()
        self.assert_private()

    def test_invalid_provider_credential_and_site_fail_before_start(self):
        for key, value in (("YOOKASSA_SECRET_KEY", "private-provider-value"),
                           ("PUBLIC_SITE_URL", "https://external.invalid"),
                           ("BILLING_SIMULATOR_ENABLED", "false")):
            with self.subTest(key=key):
                candidate = self.factory(self.source.project + "-admin", SHA, 48001, 48002,
                    root=self.root, fixture=True, executor_context="default", engine_id=ENGINE,
                    machine_sha256=MACHINE)
                candidate.files.append(self.root / "ops/docker/dev/compose.admin-acceptance.yml")
                candidate.env["IZO_ACCEPTANCE_ADMIN_CODE"] = CODE
                self.config_mutation = lambda config: config["services"]["backend"]["environment"].update({key: value})
                with self.assertRaises(RuntimeError):
                    runtime.profile_config(candidate, CODE)

    def test_every_other_credential_must_be_present_and_exactly_empty(self):
        candidate = self.factory(self.source.project + "-admin", SHA, 48001, 48002,
            root=self.root, fixture=True, executor_context="default", engine_id=ENGINE,
            machine_sha256=MACHINE)
        candidate.files.append(self.root / "ops/docker/dev/compose.admin-acceptance.yml")
        candidate.env["IZO_ACCEPTANCE_ADMIN_CODE"] = CODE
        for key in EMPTY_CREDENTIAL_KEYS:
            if key == "ADMIN_ONE_TIME_CODE":
                continue
            for value in ("private-provider-value", None, False):
                with self.subTest(key=key, value=value):
                    self.config_mutation = lambda config: config["services"]["backend"]["environment"].update({key: value})
                    with self.assertRaisesRegex(RuntimeError, "^SHADOW_CREDENTIAL_PRESENT$"):
                        runtime.profile_config(candidate, CODE)
        self.config_mutation = lambda config: config["services"]["backend"]["environment"].pop("YOOKASSA_SECRET_KEY")
        with self.assertRaisesRegex(RuntimeError, "^SHADOW_CREDENTIAL_PRESENT$"):
            runtime.profile_config(candidate, CODE)

    def test_exact_fixture_guard_rejects_non_test_mode_and_entrypoint_before_start(self):
        candidate = self.factory(self.source.project + "-admin", SHA, 48001, 48002,
            root=self.root, fixture=True, executor_context="default", engine_id=ENGINE,
            machine_sha256=MACHINE)
        candidate.files.append(self.root / "ops/docker/dev/compose.admin-acceptance.yml")
        candidate.env["IZO_ACCEPTANCE_ADMIN_CODE"] = CODE
        for key in ("APP_ENV", "ENV", "MODE"):
            self.config_mutation = lambda config: config["services"]["backend"]["environment"].update({key: "production"})
            with self.assertRaisesRegex(RuntimeError, "^SHADOW_ADMIN_PROFILE_REQUIRED$"):
                runtime.profile_config(candidate, CODE)
        self.config_mutation = lambda config: config["services"]["backend"].update(entrypoint=["sh", "-c"])
        with self.assertRaisesRegex(RuntimeError, "^SHADOW_ADMIN_PROFILE_REQUIRED$"):
            runtime.profile_config(candidate, CODE)
        self.config_mutation = lambda config: config["services"]["backend"]["environment"].update(ADMIN_ONE_TIME_CODE="\u042f" * 48)
        with self.assertRaisesRegex(RuntimeError, "^SHADOW_ADMIN_CODE_MISMATCH$"):
            runtime.profile_config(candidate, CODE)

    def test_source_guard_failure_never_admits_or_starts_the_project(self):
        self.source_error = RuntimeError("private source diagnostics " + CODE)
        result, proof = self.run_probe()
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["failedStage"], "admission")
        self.fresh.assert_not_called()
        proof.assert_not_called()
        self.api.assert_not_called()
        self.cleanup.assert_not_called()
        self.assert_private()

    def test_failed_topology_receipt_cannot_enable_normal_admin_api(self):
        def fail(shadow, path, **kwargs):
            self.proof(shadow, path, **kwargs)
            path.write_text('{"status":"FAIL"}\n', encoding="utf-8")
        result, _ = self.run_probe(proof=fail)
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["failedStage"], "topology")
        self.api.assert_not_called()
        self.cleanup.assert_called_once_with(self.instances[0], True)
        self.assert_private()

    def test_private_exception_still_cleans_owned_state_and_never_enters_receipt(self):
        def fail(*args, **kwargs):
            raise RuntimeError("resolved environment contains " + CODE)
        result, _ = self.run_probe(proof=fail)
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["errorCode"], "ADMIN_RUNTIME_OPERATION_FAILED")
        self.api.assert_not_called()
        self.cleanup.assert_called_once_with(self.instances[0], True)
        self.assert_private()

    def test_cleanup_failure_cannot_leave_a_pass_after_successful_api(self):
        self.cleanup.side_effect = RuntimeError("private cleanup state " + CODE)
        result, _ = self.run_probe()
        self.assertEqual(result["acceptance"]["status"], "PASS")
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["cleanupError"], "ADMIN_RUNTIME_CLEANUP_FAILED")
        self.assert_private()

    def test_foreign_change_cannot_leave_a_pass_after_successful_api(self):
        self.compare.return_value = {"status": "FAIL"}
        result, _ = self.run_probe()
        self.assertEqual(result["acceptance"]["status"], "PASS")
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["cleanupError"], "ADMIN_RUNTIME_CLEANUP_FAILED")
        self.assert_private()

    def test_failed_api_receipt_remains_fail_after_successful_cleanup(self):
        self.api.return_value = {"status": "FAIL", "checks": {"replay": {"status": "FAIL"}}}
        result, _ = self.run_probe()
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["failedStage"], "admin-api")
        self.assertEqual(result["cleanup"]["status"], "PASS")
        self.assertEqual(result["foreignResources"]["status"], "PASS")
        self.assert_private()

    def test_shared_executor_refused_before_evidence_or_commands(self):
        self.source.executor = None
        with self.assertRaisesRegex(RuntimeError, "ADMIN_RUNTIME_EXECUTOR_REQUIRED"):
            runtime.rehearse_admin(self.source, self.root / "evidence")
        self.assertFalse((self.root / "evidence").exists())

    def test_inherited_lifecycle_output_is_captured_even_when_caller_disables_it(self):
        shadow = runtime.CapturedAdminShadow.__new__(runtime.CapturedAdminShadow)
        with patch.object(Shadow, "run", return_value="captured") as base:
            self.assertEqual(shadow.run(["docker", "compose", "up"], capture=False, timeout=42), "captured")
        base.assert_called_once_with(["docker", "compose", "up"], capture=True, timeout=42)
