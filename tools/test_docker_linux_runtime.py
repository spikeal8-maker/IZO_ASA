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

SELECTED = {"A": runtime.PREVIOUS_SOURCE, "B": "f" * 40}


def engine(boot):
    value = {"fingerprint": "a" * 64, "context": "default", "locality": {
        "version": 1, "bootFingerprint": boot, "endpoint": "unix:///var/run/docker.sock", "socketPath": "/run/docker.sock",
        "socketType": "socket", "socketOwnerUid": 0, "hostnameFingerprint": "b" * 64, "kernelRelease": "6.8.0-test"}}
    value["engineInstanceFingerprint"] = runtime.linux.engine_instance_fingerprint(value, boot)
    return value


def archive(root, label, profile="synthetic-runtime"):
    value = {"format": 2 if profile == "synthetic-runtime" else 1, "profile": profile,
        "source_sha": SELECTED[label], "tooling_sha": runtime.TOOLING, "project": runtime.PROJECT,
        "ports": runtime.PORTS, "images": {r: "sha256:" + "a" * 64 for r in ("backend", "web", "guard")},
        "production_authorized": False, "model_execution": False}
    body = json.dumps(value).encode(); path = root / ("release-" + label + ".zip")
    with zipfile.ZipFile(path, "w") as bundle:
        bundle.writestr("bundle.json", body)
    receipt = {"status": "TEST_BUNDLE_BUILT", "source_sha": SELECTED[label], "tooling_sha": runtime.TOOLING,
        "project": runtime.PROJECT, "images_embedded": True, "production_authorized": False,
        "archive_sha256": runtime.linux.digest(path), "archive_bytes": path.stat().st_size,
        "manifest_sha256": hashlib.sha256(body).hexdigest()}
    runtime.linux.write_json(path.with_suffix(".receipt.json"), receipt)
    return {"receipt": receipt, "receiptSha256": runtime.linux.digest(path.with_suffix(".receipt.json"))}


def context_record(root, pins=None):
    value = {"contract": runtime.CONTRACT, "status": "PASS_CONTEXT_EXPORT_ONLY", "sourceSha": SELECTED["B"],
             "sourceDirty": False, "ignoreSha256": pins or {role: "a" * 64 for role in ("root", "web", "guard")},
             "roles": {role: {"status": "PASS", "files": [], "unexpected": [], "missing": [], "contentsVerified": True}
                       for role in ("web", "guard")}}
    path = root / "context.json"; runtime.linux.write_json(path, value)
    return {"receipt": value, "receiptSha256": runtime.linux.digest(path)}


class TransferTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.args = SimpleNamespace(transfer=self.root, root=self.root / "receiver", candidate=self.root / "candidate",
                                    source_a_sha=SELECTED["A"], source_b_sha=SELECTED["B"])
        self.runner = {"head": "f" * 40, "runId": "1", "attempt": "1", "job": "receiver", "bootFingerprint": "c" * 64}
        self.engine = engine("c" * 64)
        self.support = {"moduleHashes": {"format": "d" * 64}, "httpClientSha256": "e" * 64}
        self.producer = {"status": "PASS_ORDINARY_PRODUCER_ONLY", "contract": runtime.CONTRACT,
            "profile": "synthetic-runtime", "toolingSha": runtime.TOOLING, "sources": dict(SELECTED),
            "contextProof": context_record(self.root), "before": {"images": [], "containers": [], "volumes": []},
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

    def test_transfer_binds_sources_and_context(self):
        self.producer["sources"]["B"] = runtime.linux.SOURCES["B"]
        with self.assertRaisesRegex(runtime.linux.ProofError, "APPLICATION_SOURCE_TRANSFER_CHANGED"):
            self.validate()
        self.producer["sources"] = dict(SELECTED)
        changed = dict(self.producer["contextProof"]["receipt"]); changed["sourceDirty"] = True
        runtime.linux.write_json(self.root / "context.json", changed)
        with self.assertRaisesRegex(runtime.linux.ProofError, "CANONICAL_CONTEXT_NOT_PROVEN"):
            self.validate()
        self.producer["contextProof"] = context_record(self.root)
        self.producer["contextProof"]["receiptSha256"] = "0" * 64
        with self.assertRaisesRegex(runtime.linux.ProofError, "CONTEXT_PROOF_CHANGED"):
            self.validate()

    def test_receiver_plan_uses_actual_destination_and_keeps_credentials_in_memory(self):
        with patch.object(runtime, "support", return_value=self.support):
            plan = runtime.make_plan(self.args, self.producer, self.engine)
        self.assertEqual(plan["scope"]["root"], str(self.args.root))
        self.assertEqual(plan["scope"]["engineFingerprint"], self.engine["fingerprint"])
        self.assertEqual(plan["observationSeconds"], 420)
        self.assertFalse(plan["retainSyntheticCredentials"])
        self.assertEqual(set(plan["bundles"]), {"A", "B"})
        self.assertEqual(plan["version"], 2); self.assertEqual(plan["sources"], SELECTED)

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
            root = Path(folder); args = SimpleNamespace(source_a=root / "A", source_b=root / "B", tooling=root / "tooling", root=root,
                                                      source_a_sha=SELECTED["A"], source_b_sha=SELECTED["B"])
            commands = []
            def run(command, **kwargs):
                commands.append((command, kwargs))
                if "tools.docker_test_bundle" in command:
                    archive(root, "A")
                return json.dumps({"services": {role: {} for role in ("guard", "backend", "web")}}) if "config" in command else ""
            with patch.object(runtime.linux, "run", side_effect=run), patch.object(runtime.linux, "source_guard"), \
                 patch.object(runtime.linux, "pinned_dockerfiles", return_value={"guard": "pinned"}):
                runtime.build_release(args, "A", {})
            rendered, build, bundle = [c for c, _ in commands]
            self.assertEqual(rendered[-3:], ["config", "--format", "json"])
            self.assertIn("--no-cache", build)
            self.assertFalse(any("compose.acceptance" in part for part in build))
            self.assertIn(str(args.source_a / "ops/docker/dev/compose.shadow.yml"), build)
            self.assertEqual(bundle[bundle.index("--profile") + 1], "synthetic-runtime")
            self.assertEqual(commands[2][1]["cwd"], args.tooling)
            self.assertEqual(bundle[bundle.index("--sha") + 1], SELECTED["A"])
            self.assertEqual(commands[0][1]["env"]["IZO_SOURCE_SHA"], SELECTED["A"])

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


class CanonicalSelectionTests(unittest.TestCase):
    def args(self, root, *, action="producer"):
        return SimpleNamespace(action=action, candidate=root / "candidate", tooling=root / "tooling", root=root / "run",
            source_a=root / "A", source_b=root / "B", source_a_sha=SELECTED["A"], source_b_sha=SELECTED["B"])

    def test_source_pins_and_distinct_checkouts(self):
        with tempfile.TemporaryDirectory() as folder:
            args = self.args(Path(folder))
            self.assertEqual(runtime.source_selection(args, SELECTED["B"]), SELECTED)
            for field, value in (("source_a_sha", runtime.linux.SOURCES["A"]), ("source_b_sha", "main"),
                                 ("source_b_sha", SELECTED["A"]), ("source_b_sha", "e" * 40)):
                original = getattr(args, field); setattr(args, field, value)
                with self.subTest(field=field, value=value), self.assertRaisesRegex(runtime.linux.ProofError, "CANONICAL_SOURCE_SELECTION_INVALID"):
                    runtime.source_selection(args, SELECTED["B"])
                setattr(args, field, original)
            args.source_b = args.source_a
            with patch.object(runtime.linux, "source_guard") as guard:
                with self.assertRaisesRegex(runtime.linux.ProofError, "SOURCE_CHECKOUTS_NOT_DISTINCT"):
                    runtime.sources(args, {"head": SELECTED["B"]})
            guard.assert_not_called()

    def test_dirty_or_wrong_source_blocks_docker(self):
        with tempfile.TemporaryDirectory() as folder:
            args = self.args(Path(folder))
            for actual, dirty in ((SELECTED["B"], " M backend/main.py"), ("e" * 40, "")):
                commands = []
                def run(command, **kwargs):
                    commands.append(command); self.assertEqual(command[0], "git")
                    if command[-3:] == ["remote", "get-url", "origin"]: return "https://github.com/spikeal8-maker/IZO_ASA.git"
                    if command[-2:] == ["rev-parse", "HEAD"]: return actual
                    if command[-2:] == ["status", "--porcelain"]: return dirty
                    self.fail("unexpected command")
                with self.subTest(actual=actual, dirty=bool(dirty)), patch.object(runtime.linux, "run", side_effect=run):
                    with self.assertRaisesRegex(runtime.linux.ProofError, "CLEAN_EXACT_REPOSITORY_REQUIRED"):
                        runtime.build_release(args, "B", {})
                self.assertTrue(commands)

    def test_http_client_has_no_source_b_dependency(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); candidate = root / "candidate"; tooling = root / "tooling"
            (candidate / "tools").mkdir(parents=True); (tooling / "tools").mkdir(parents=True)
            helper = candidate / "tools/synthetic_http_client.py"
            helper.write_bytes(Path(runtime.__file__).with_name("synthetic_http_client.py").read_bytes())
            for name in ("docker_test_bundle_format", "docker_test_bundle_runtime"):
                (tooling / "tools" / (name + ".py")).write_text("pinned module fixture\n")
            args = SimpleNamespace(candidate=candidate, tooling=tooling)
            value = runtime.support(args)
            self.assertEqual(value["httpClientPath"], str(helper)); self.assertEqual(value["httpClientSha256"], runtime.HTTP_CLIENT)
            helper.write_bytes(helper.read_bytes() + b"# changed\n")
            with self.assertRaisesRegex(runtime.linux.ProofError, "HTTP_CLIENT_CHANGED"):
                runtime.support(args)

    def test_probe_binds_current_context(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); args = self.args(root); args.root.mkdir(); pins = {}
            for role, name in (("root", ".dockerignore"), ("web", "ops/docker/dev/Dockerfile.web.dockerignore"),
                               ("guard", "ops/docker/dev/Dockerfile.guard.dockerignore")):
                path = args.source_b / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text("**\n")
                pins[role] = runtime.linux.digest(path)
            def run(command, **kwargs):
                self.assertEqual(command[2:4], ["-m", "tools.docker_canonical_context_probe"])
                self.assertEqual(command[command.index("--source") + 1], str(args.source_b))
                self.assertNotIn(str(args.source_a), command); self.assertEqual(kwargs["cwd"], args.candidate)
                context_record(args.root, pins)
                return ""
            with patch.object(runtime.linux, "run", side_effect=run), patch.object(runtime.linux, "source_guard") as guard:
                proof = runtime.run_context_probe(args, {})
            self.assertEqual([call.args for call in guard.call_args_list], [(args.source_b, SELECTED["B"])] * 2)
            self.assertEqual(proof["receipt"]["sourceSha"], SELECTED["B"])
            with patch.object(runtime.linux, "source_guard"), patch.object(runtime.linux, "run",
                    side_effect=lambda *a, **kw: context_record(args.root, {**pins, "web": "0" * 64})):
                with self.assertRaisesRegex(runtime.linux.ProofError, "CONTEXT_IGNORE_PINS_CHANGED"):
                    runtime.run_context_probe(args, {})
            for field, value in (("sourceSha", SELECTED["A"]), ("sourceDirty", True), ("status", "FAIL")):
                receipt = dict(proof["receipt"]); receipt[field] = value
                runtime.linux.write_json(args.root / "context.json", receipt)
                with self.subTest(field=field), self.assertRaisesRegex(runtime.linux.ProofError, "CANONICAL_CONTEXT_NOT_PROVEN"):
                    runtime.context_proof(args.root, SELECTED["B"])

    def test_bad_merged_compose_stops_before_image_build(self):
        with tempfile.TemporaryDirectory() as folder:
            args = self.args(Path(folder))
            with patch.object(runtime.linux, "source_guard"), patch.object(runtime.linux, "pinned_dockerfiles"), \
                 patch.object(runtime.linux, "run", return_value=json.dumps({"services": {"backend": {}}})) as command:
                with self.assertRaisesRegex(runtime.linux.ProofError, "ORDINARY_COMPOSE_REQUIRED"):
                    runtime.build_release(args, "B", {})
            command.assert_called_once(); self.assertEqual(command.call_args.args[0][-3:], ["config", "--format", "json"])

    def test_context_gate_precedes_builds_and_failure_stops(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for fails in (False, True):
                run_root = root / ("failed" if fails else "pass"); events = []
                def probe(args, report):
                    events.append("context")
                    if fails: raise runtime.linux.ProofError("CONTEXT_FAILED")
                    return context_record(run_root)
                argv = ["producer", "--candidate", str(root / "candidate"), "--tooling", str(root / "tooling"),
                        "--source-a", str(root / "A"), "--source-b", str(root / "B"), "--root", str(run_root),
                        "--source-a-sha", SELECTED["A"], "--source-b-sha", SELECTED["B"]]
                with patch.object(runtime.linux, "runner_metadata", return_value={"head": SELECTED["B"], "bootFingerprint": "a" * 64}), \
                     patch.object(runtime, "sources", return_value=dict(SELECTED)), patch.object(runtime.linux, "engine_metadata", return_value={}), \
                     patch.object(runtime.linux, "inventory", return_value={"images": [], "containers": [], "volumes": []}), \
                     patch.object(runtime.linux, "fresh_engine", side_effect=lambda *args: events.append("fresh")), \
                     patch.object(runtime, "support", return_value={"moduleHashes": {}, "httpClientSha256": runtime.HTTP_CLIENT}), \
                     patch.object(runtime, "run_context_probe", side_effect=probe), \
                     patch.object(runtime, "build_release", side_effect=lambda args, label, report: events.append(label)):
                    self.assertEqual(runtime.main(argv), 1 if fails else 0)
                self.assertEqual(events, ["fresh", "context"] if fails else ["fresh", "context", "A", "B"])
                self.assertEqual(runtime.read(run_root / "producer.json")["sources"], SELECTED)


if __name__ == "__main__":
    unittest.main()
