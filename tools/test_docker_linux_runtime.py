"""Ordinary-profile, artifact, process and evidence boundaries; no Docker/network."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import zipfile

import docker_linux_runtime as runtime


def engine(boot):
    value = {"fingerprint": "a" * 64, "context": "default", "locality": {
        "version": 1, "bootFingerprint": boot, "endpoint": "unix:///var/run/docker.sock", "socketPath": "/run/docker.sock",
        "socketType": "socket", "socketOwnerUid": 0, "hostnameFingerprint": "b" * 64, "kernelRelease": "6.8.0-test"}}
    value["engineInstanceFingerprint"] = runtime.linux.engine_instance_fingerprint(value, boot)
    return value


def archive(root, label, profile="synthetic-runtime"):
    value = {"format": 2 if profile == "synthetic-runtime" else 1, "profile": profile,
        "source_sha": runtime.linux.SOURCES[label], "tooling_sha": runtime.TOOLING, "project": runtime.PROJECT,
        "ports": runtime.PORTS, "images": {r: "sha256:" + "a" * 64 for r in ("backend", "web", "guard")},
        "production_authorized": False, "model_execution": False}
    body = json.dumps(value).encode(); path = root / ("release-" + label + ".zip")
    with zipfile.ZipFile(path, "w") as bundle:
        bundle.writestr("bundle.json", body)
    receipt = {"status": "TEST_BUNDLE_BUILT", "source_sha": runtime.linux.SOURCES[label], "tooling_sha": runtime.TOOLING,
        "project": runtime.PROJECT, "images_embedded": True, "production_authorized": False,
        "archive_sha256": runtime.linux.digest(path), "archive_bytes": path.stat().st_size,
        "manifest_sha256": hashlib.sha256(body).hexdigest()}
    runtime.linux.write_json(path.with_suffix(".receipt.json"), receipt)
    return {"receipt": receipt, "receiptSha256": runtime.linux.digest(path.with_suffix(".receipt.json"))}


class TransferTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.args = SimpleNamespace(transfer=self.root, root=self.root / "receiver", candidate=self.root / "candidate")
        self.runner = {"head": "f" * 40, "runId": "1", "attempt": "1", "job": "receiver", "bootFingerprint": "c" * 64}
        self.engine = engine("c" * 64)
        self.support = {"moduleHashes": {"format": "d" * 64}, "httpClientSha256": "e" * 64}
        self.producer = {"status": "PASS_ORDINARY_PRODUCER_ONLY", "contract": runtime.CONTRACT,
            "profile": "synthetic-runtime", "toolingSha": runtime.TOOLING,
            "before": {"images": [], "containers": [], "volumes": []},
            "runner": {**self.runner, "job": "producer", "bootFingerprint": "d" * 64}, "engine": engine("d" * 64),
            "moduleHashes": self.support["moduleHashes"], "httpClientSha256": self.support["httpClientSha256"],
            "controllerHashes": runtime.CONTROLLERS, "releases": {label: archive(self.root, label) for label in ("A", "B")}}

    def validate(self, *, previous_pin=None):
        runtime.linux.write_json(self.root / "producer.json", self.producer)
        pin = previous_pin or runtime.linux.digest(self.root / "producer.json")
        with patch.dict(os.environ, {"IZO_PRODUCER_RECEIPT_SHA256": pin}), patch.object(runtime, "support", return_value=self.support):
            return runtime.transfer(self.args, self.runner, self.engine)

    def test_same_persistent_engine_id_distinct_verified_boots_are_valid(self):
        self.assertEqual(self.validate(), self.producer)
        self.assertEqual(self.engine["fingerprint"], self.producer["engine"]["fingerprint"])

    def test_same_boot_or_remote_endpoint_refuses_before_controller(self):
        self.producer["runner"]["bootFingerprint"] = self.runner["bootFingerprint"]
        with self.assertRaisesRegex(runtime.linux.ProofError, "DISTINCT_BOOT_REQUIRED"):
            self.validate()
        self.producer["runner"]["bootFingerprint"] = "d" * 64
        self.producer["engine"]["locality"]["endpoint"] = "tcp://remote:2375"
        with self.assertRaisesRegex(runtime.linux.ProofError, "ENGINE_INSTANCE_EVIDENCE_INVALID"):
            self.validate()

    def test_nonempty_producer_each_resource_kind_refuses(self):
        for kind in ("images", "containers", "volumes"):
            self.producer["before"][kind] = ["preexisting"]
            with self.subTest(kind=kind), self.assertRaisesRegex(runtime.linux.ProofError, "PRODUCER_CONTRACT_CHANGED"):
                self.validate()
            self.producer["before"][kind] = []

    def test_old_v1_contract_or_profile_cannot_be_relabelled(self):
        for key, value in (("contract", "DOCKER-LINUX-BUNDLE-ACCEPTANCE-004"), ("profile", "acceptance-fixture")):
            original = self.producer[key]; self.producer[key] = value
            with self.subTest(key=key), self.assertRaisesRegex(runtime.linux.ProofError, "PRODUCER_CONTRACT_CHANGED"):
                self.validate()
            self.producer[key] = original
        self.producer["releases"]["B"] = archive(self.root, "B", profile="acceptance-fixture")
        with self.assertRaisesRegex(runtime.linux.ProofError, "ORDINARY_PROFILE_REQUIRED"):
            self.validate()

    def test_changed_artifact_or_archive_does_not_receive_a_new_trust_pin(self):
        self.validate(); pin = runtime.linux.digest(self.root / "producer.json")
        self.producer["runner"]["attempt"] = "2"
        with self.assertRaisesRegex(runtime.linux.ProofError, "PRODUCER_RECEIPT_PIN_MISMATCH"):
            self.validate(previous_pin=pin)
        self.producer["runner"]["attempt"] = "1"
        (self.root / "release-B.zip").write_bytes(b"corrupted")
        with self.assertRaisesRegex(runtime.linux.ProofError, "TRANSFER_RELEASE_CHANGED"):
            self.validate()

    def test_receiver_plan_uses_actual_destination_and_keeps_credentials_in_memory(self):
        with patch.object(runtime, "support", return_value=self.support):
            plan = runtime.make_plan(self.args, self.producer, self.engine)
        self.assertEqual(plan["scope"]["root"], str(self.args.root))
        self.assertEqual(plan["scope"]["engineFingerprint"], self.engine["fingerprint"])
        self.assertEqual(plan["observationSeconds"], 420)
        self.assertFalse(plan["retainSyntheticCredentials"])
        self.assertEqual(set(plan["bundles"]), {"A", "B"})

    def test_failed_controller_never_invokes_cleanup(self):
        self.args.root.mkdir()
        report = {"runner": self.runner, "engine": self.engine}
        self.validate()
        with patch.object(runtime, "transfer", return_value=self.producer), patch.object(runtime, "support", return_value=self.support), \
             patch.object(runtime, "lifecycle_window", return_value={"fixedTestClock": True}), \
             patch.object(runtime, "controller", side_effect=runtime.linux.ProofError("RUN_FAILED")) as child:
            with self.assertRaisesRegex(runtime.linux.ProofError, "RUN_FAILED"):
                runtime.receiver(self.args, report)
        self.assertEqual([call.args[1] for call in child.call_args_list], ["run"])

    def test_rollover_refusal_precedes_every_controller_or_auth_mutation(self):
        self.args.root.mkdir(); self.validate()
        with patch.object(runtime, "transfer", return_value=self.producer), patch.object(runtime, "support", return_value=self.support), \
             patch.object(runtime, "lifecycle_window", side_effect=runtime.linux.ProofError("DAILY_COUNTER_WINDOW_TOO_SHORT")), \
             patch.object(runtime, "controller") as child:
            with self.assertRaisesRegex(runtime.linux.ProofError, "DAILY_COUNTER_WINDOW_TOO_SHORT"):
                runtime.receiver(self.args, {"runner": self.runner, "engine": self.engine})
        child.assert_not_called()


class CommandAndEvidenceTests(unittest.TestCase):
    def test_full_lifecycle_window_plus_margin_must_fit_before_utc_rollover(self):
        before = runtime.datetime(2026, 10, 27, 23, 29, 59, tzinfo=runtime.timezone.utc)
        result = runtime.lifecycle_window(before)
        self.assertEqual(result["remainingSeconds"], 1801)
        self.assertEqual(result["runDeadlineSeconds"], 1500)
        self.assertEqual(result["cleanupDeadlineSeconds"], 240)
        for now in (before + runtime.timedelta(seconds=1), before.replace(tzinfo=None)):
            with self.subTest(now=now), self.assertRaises(runtime.linux.ProofError):
                runtime.lifecycle_window(now)

    def test_build_uses_ordinary_compose_and_explicit_format2_profile(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); args = SimpleNamespace(source_a=root / "A", source_b=root / "B", tooling=root / "tooling", root=root)
            commands = []
            def run(command, **kwargs):
                commands.append((command, kwargs))
                if "tools.docker_test_bundle" in command:
                    archive(root, "A")
                return ""
            with patch.object(runtime.linux, "run", side_effect=run), patch.object(runtime.linux, "source_guard"), \
                 patch.object(runtime.linux, "pinned_dockerfiles", return_value={"guard": "pinned"}):
                runtime.build_release(args, "A", {})
            build, bundle = [c for c, _ in commands]
            self.assertIn("--no-cache", build)
            self.assertFalse(any("compose.acceptance" in part for part in build))
            self.assertIn(str(args.source_a / "ops/docker/dev/compose.shadow.yml"), build)
            self.assertEqual(bundle[bundle.index("--profile") + 1], "synthetic-runtime")
            self.assertEqual(commands[1][1]["cwd"], args.tooling)

    def test_controller_is_fresh_cli_without_tools_module_import_and_bounded_group(self):
        args = SimpleNamespace(candidate=Path("/candidate"), root=Path("/work"))
        process = Mock(returncode=0); process.communicate.return_value = (b"PASS\n", b"")
        with patch.object(runtime.subprocess, "Popen", return_value=process) as start:
            runtime.controller(args, "run", "a" * 64)
        command = start.call_args.args[0]
        self.assertEqual(command[2], str(args.candidate / "tools" / "synthetic_runtime_accept.py"))
        self.assertNotIn("-m", command)
        self.assertTrue(start.call_args.kwargs["start_new_session"])
        process.communicate.assert_called_once_with(timeout=1500)

    def test_timeout_signals_only_owned_controller_group_and_never_retries(self):
        args = SimpleNamespace(candidate=Path("/candidate"), root=Path("/work"))
        process = Mock(pid=123); process.communicate.side_effect = [subprocess.TimeoutExpired("controller", 1500), (b"", b"")]
        with patch.object(runtime.subprocess, "Popen", return_value=process) as start, \
             patch.object(runtime.os, "getpgid", return_value=123, create=True), \
             patch.object(runtime.os, "killpg", create=True) as kill, patch.object(runtime.signal, "SIGKILL", 9, create=True):
            with self.assertRaisesRegex(runtime.linux.ProofError, "CONTROLLER_DEADLINE_RESOURCES_RETAINED"):
                runtime.controller(args, "run", "a" * 64)
        start.assert_called_once(); kill.assert_called_once_with(123, 9)

    def acceptance(self):
        steps = [{"name": "stage" + str(i), "status": "PASS", "seconds": 1} for i in range(11)]
        steps[4].update(name="continuous_uptime_and_live_generation", evidence={"observedSeconds": 421, "sameStartedAt": True,
            "samples": 70, "postDeadlineGeneration": {"jobId": "synthetic", "realModelExecution": False}})
        return {"status": "PASS_SYNTHETIC_RUNTIME_LIFECYCLE_ONLY", "project": runtime.PROJECT, "foreignResourcesChanged": 0,
            "steps": steps, "perUserImages": {"owner": 9, "other": 0}, "planSha256": "p", "activeReceiptSha256": "a", "ownerReceiptSha256": "o",
            "accepted": {"topology": {"containers": {}}, "database": {"charges": {str(i): {} for i in range(9)}},
                "product": {"jobs": list(range(9)), "accounts": [{"email": "private@example.invalid", "password": "PASSWORD_SECRET", "session_id": "SESSION_SECRET"}]}}}

    def test_public_evidence_excludes_raw_account_or_session_fields(self):
        result = runtime.public_acceptance(self.acceptance()); body = json.dumps(result)
        for forbidden in ("PASSWORD_SECRET", "SESSION_SECRET", "private@example.invalid", '"accounts"'):
            self.assertNotIn(forbidden, body)
        self.assertFalse(result["credentialsUploaded"])
        self.assertFalse(result["sessionIdentifiersUploaded"])

    def test_short_uptime_missing_stage_or_private_artifact_cannot_pass(self):
        original = self.acceptance()
        variants = []
        value = deepcopy(original); value["steps"][4]["evidence"]["observedSeconds"] = 300; variants.append(value)
        value = deepcopy(original); value["steps"].pop(); variants.append(value)
        value = deepcopy(original); value["privateCredentials"] = {"path": "private/credentials.json"}; variants.append(value)
        value = deepcopy(original); value["perUserImages"]["owner"] = 8; variants.append(value)
        for value in variants:
            with self.subTest(value=value), self.assertRaises(runtime.linux.ProofError):
                runtime.public_acceptance(value)


if __name__ == "__main__":
    unittest.main()
