"""Receiver integrity, no-Git PATH and cleanup ownership regression controls."""
import copy
import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from tools import docker_linux_bundle_build as build
from tools import docker_linux_bundle_probe as probe


def engine_evidence(boot, fingerprint):
    local = {"version": 1, "bootFingerprint": boot, "endpoint": "unix:///var/run/docker.sock",
             "socketPath": "/run/docker.sock", "socketType": "socket", "socketOwnerUid": 0,
             "hostnameFingerprint": "f" * 64, "kernelRelease": "6.8.0-1044-azure"}
    payload = {"persistentEngineFingerprint": fingerprint, **local}
    return {"fingerprint": fingerprint, "context": "default", "locality": local,
            "engineInstanceFingerprint": hashlib.sha256(
                json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("ascii")).hexdigest()}


class TransferTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.runner = {"head": "a" * 40, "runId": "123", "attempt": "1", "job": "receiver",
                       "runner": "second-vm", "bootFingerprint": "d" * 64}
        self.engine = engine_evidence(self.runner["bootFingerprint"], "b" * 64)
        self.producer = {"status": "PASS_TEST_PRODUCER_ONLY", "toolingSha": build.TOOLING,
            "contract": build.CONTRACT, "before": {"images": [], "containers": [], "volumes": []},
            "runner": {**self.runner, "job": "producer", "runner": "first-vm", "bootFingerprint": "e" * 64},
            "engine": engine_evidence("e" * 64, "c" * 64), "releases": {}}
        for label, sha in build.SOURCES.items():
            archive = self.root / ("release-" + label + ".zip"); archive.write_bytes(label.encode())
            receipt = {"source_sha": sha, "tooling_sha": build.TOOLING, "project": build.PROJECT,
                       "images_embedded": True, "archive_sha256": build.digest(archive)}
            path = archive.with_suffix(".receipt.json"); build.write_json(path, receipt)
            self.producer["releases"][label] = {"receipt": receipt, "receiptSha256": build.digest(path)}
        self.save()

    def save(self):
        build.write_json(self.root / "producer.json", self.producer)
        self.pin = build.digest(self.root / "producer.json")

    def validate(self):
        return probe.validate_transfer(self.root, self.pin, self.runner, self.engine)

    def test_both_exact_archives_transfer_from_a_distinct_engine(self):
        self.assertEqual(self.validate(), self.producer)

    def test_claimed_pass_requires_exact_contract_and_measured_empty_producer(self):
        invalid = [None, {}, {"images": [], "containers": []}]
        for kind in ("images", "containers", "volumes"):
            inventory = {"images": [], "containers": [], "volumes": []}; inventory[kind] = ["foreign"]
            invalid.append(inventory)
        for before in invalid:
            with self.subTest(before=before):
                changed = {**self.producer, "before": before}
                build.write_json(self.root / "producer.json", changed)
                with self.assertRaisesRegex(build.ProofError, "PRODUCER_FRESH_ENGINE_EVIDENCE_REQUIRED"):
                    probe.validate_transfer(self.root, build.digest(self.root / "producer.json"), self.runner, self.engine)
        for previous in ("DOCKER-LINUX-BUNDLE-ACCEPTANCE-001", "DOCKER-LINUX-BUNDLE-ACCEPTANCE-002"):
            self.producer["contract"] = previous; self.save()
            with self.assertRaisesRegex(build.ProofError, "PRODUCER_FRESH_ENGINE_EVIDENCE_REQUIRED"):
                self.validate()

    def test_self_consistent_artifact_cannot_replace_trusted_job_output_pin(self):
        self.producer["runner"]["runId"] = "other-run"
        build.write_json(self.root / "producer.json", self.producer)
        with self.assertRaisesRegex(build.ProofError, "PRODUCER_RECEIPT_PIN_MISMATCH"):
            self.validate()

    def test_archive_corruption_is_detected(self):
        (self.root / "release-B.zip").write_bytes(b"corrupted")
        with self.assertRaisesRegex(build.ProofError, "TRANSFER_IDENTITY_MISMATCH"):
            self.validate()

    def test_receipt_substitution_is_detected(self):
        (self.root / "release-A.receipt.json").write_text("{}")
        with self.assertRaisesRegex(build.ProofError, "TRANSFER_IDENTITY_MISMATCH"):
            self.validate()

    def test_same_engine_same_boot_or_different_run_cannot_pass(self):
        for field in ("engine", "bootFingerprint", "runId", "head"):
            with self.subTest(field=field):
                changed = copy.deepcopy(self.producer)
                if field == "engine": changed["engine"] = self.engine
                elif field == "bootFingerprint": changed["runner"][field] = self.runner[field]
                else: changed["runner"][field] = "different"
                build.write_json(self.root / "producer.json", changed)
                with self.assertRaises(build.ProofError):
                    probe.validate_transfer(self.root, build.digest(self.root / "producer.json"), self.runner, self.engine)

    def test_runner_display_name_is_recorded_without_assuming_global_uniqueness(self):
        self.producer["runner"]["runner"] = self.runner["runner"]
        self.save()
        self.assertEqual(self.validate()["status"], "PASS_TEST_PRODUCER_ONLY")

    def test_cloned_persistent_engine_id_on_distinct_verified_local_boots_passes(self):
        self.producer["engine"] = engine_evidence(self.producer["runner"]["bootFingerprint"], self.engine["fingerprint"])
        self.save()
        self.assertEqual(self.validate(), self.producer)
        self.assertEqual(self.producer["engine"]["fingerprint"], self.engine["fingerprint"])

    def test_same_boot_is_refused_even_with_other_persistent_and_instance_hashes(self):
        self.producer["runner"]["bootFingerprint"] = self.runner["bootFingerprint"]
        self.producer["engine"] = engine_evidence(self.runner["bootFingerprint"], "c" * 64)
        self.save()
        self.assertNotEqual(self.producer["engine"]["engineInstanceFingerprint"], self.engine["engineInstanceFingerprint"])
        with self.assertRaisesRegex(build.ProofError, "DISTINCT_LINUX_BOOT_REQUIRED"):
            self.validate()

    def test_both_instance_receipts_reject_missing_malformed_and_cross_bound_fields(self):
        cases = [("engine", value) for value in (None, [], "engine")]
        cases += [("locality", value) for value in (None, [], {}, "local")]
        cases += [("engineInstanceFingerprint", value) for value in (None, True, 1, [], {}, "a" * 64)]
        cases += [("fingerprint", value) for value in (None, True, [], "a" * 64)]
        cases += [("version", value) for value in (True, 1.0, "1", None, 2)]
        cases += [("socketOwnerUid", value) for value in (False, 0.0, "0", 1001)]
        cases += [("bootFingerprint", value) for value in (None, [], "0" * 64)]
        cases += [("hostnameFingerprint", value) for value in (None, {}, "0" * 64)]
        cases += [("kernelRelease", value) for value in (None, [], "", "other-kernel")]
        cases += [("endpoint", "tcp://remote:2375"), ("socketPath", "/tmp/docker.sock"),
                  ("socketType", "file"), ("context", "remote")]
        original = copy.deepcopy(self.producer)
        own = copy.deepcopy(self.engine)
        for side in ("producer", "receiver"):
            for field, value in cases:
                with self.subTest(side=side, field=field, value=value):
                    self.producer, self.engine = copy.deepcopy(original), copy.deepcopy(own)
                    target = self.producer["engine"] if side == "producer" else self.engine
                    if field == "engine":
                        if side == "producer": self.producer["engine"] = value
                        else: self.engine = value
                    elif field in ("locality", "fingerprint", "context", "engineInstanceFingerprint"):
                        target[field] = value
                    else: target["locality"][field] = value
                    self.save()
                    with self.assertRaisesRegex(build.ProofError, "ENGINE_INSTANCE_(EVIDENCE_INVALID|FINGERPRINT_MISMATCH)"):
                        self.validate()

    def test_declared_instance_digest_cannot_be_copied_from_other_boot(self):
        self.producer["engine"]["engineInstanceFingerprint"] = self.engine["engineInstanceFingerprint"]
        self.save()
        with self.assertRaisesRegex(build.ProofError, "ENGINE_INSTANCE_FINGERPRINT_MISMATCH"):
            self.validate()


def resources():
    return {"containers": [{"Id": "container", "Image": "sha256:image", "Config": {"Labels": {"owner": "test"}},
        "State": {"Running": True, "StartedAt": "start", "Health": {"Log": ["old-probe"]}}}],
        "volumes": [{"Name": build.PROJECT + "_worker_ipc", "Driver": "local", "Scope": "local",
                     "CreatedAt": "created", "Labels": {"io.izo.bundle.installation": "a" * 32,
                     "io.izo.bundle.generation": "b" * 32}}], "networks": []}


class ReceiverBoundaryTests(unittest.TestCase):
    def test_nonempty_receiver_retains_initial_inventory_without_support_or_cleanup(self):
        for kind in ("images", "containers", "volumes"):
            before = {"images": [], "containers": [], "volumes": []}
            before[kind] = ["foreign-" + kind]
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp); candidate = root / "candidate"; candidate.mkdir()
                (candidate / ".python-version").write_text(probe.platform.python_version())
                receipt = root / "receiver.json"
                values = {"candidate": candidate, "tooling": root / "tooling", "source-b": root / "source-b",
                          "transfer": root / "transfer", "work": root / "work", "receipt": receipt}
                args = [part for key, path in values.items() for part in ("--" + key, str(path))]
                with patch.object(probe, "runner_metadata", return_value={"head": "a" * 40, "bootFingerprint": "d" * 64}), \
                        patch.object(probe, "source_guard"), patch.object(probe, "engine_metadata", return_value={}), \
                        patch.object(build, "inventory", return_value=before), \
                        patch.object(probe, "inventory", return_value=before), \
                        patch.object(probe, "load_support") as support, \
                        patch.object(probe, "validate_transfer") as transfer, \
                        patch.object(probe, "Receiver") as receiver, patch.object(build, "run") as command:
                    self.assertEqual(probe.main(args), 1)
                for operation in (support, transfer, receiver, command):
                    operation.assert_not_called()
                report = json.loads(receipt.read_text())
                self.assertEqual(report.get("before"), before)
                self.assertEqual(report["reason"], "RECEIVER_ENGINE_NOT_EMPTY_NO_PRUNE")
                self.assertEqual(report["stage"], "fresh_engine")
                self.assertNotIn("cleanup", report)
                self.assertEqual(list(values["work"].iterdir()), [])

    def test_support_module_cached_from_another_checkout_is_rejected(self):
        before = list(sys.path)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                wrong = SimpleNamespace(__file__=str(root / "foreign/runtime.py"))
                with patch.object(probe.importlib, "import_module", return_value=wrong), \
                        self.assertRaisesRegex(build.ProofError, "PINNED_TOOL_MODULE_REQUIRED"):
                    probe.load_support(root / "pinned", root / "source")
        finally:
            sys.path[:] = before

    def test_periodic_health_logs_do_not_look_like_an_installer_mutation(self):
        before = resources(); after = copy.deepcopy(before)
        after["containers"][0]["State"]["Health"]["Log"] = ["new-probe"]
        self.assertEqual(probe.resource_identity(before), probe.resource_identity(after))
        after["containers"][0]["State"]["StartedAt"] = "restart"
        self.assertNotEqual(probe.resource_identity(before), probe.resource_identity(after))

    def test_generation_drift_is_in_resource_comparison(self):
        before = resources(); after = copy.deepcopy(before)
        after["volumes"][0]["Labels"]["io.izo.bundle.generation"] = "c" * 32
        self.assertNotEqual(probe.resource_identity(before), probe.resource_identity(after))

    def test_installer_bin_preserves_docker_and_python_but_excludes_git_node_npm(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "bin"
            def which(name, *, path=None):
                if name in {"git", "node", "npm"}: return None
                return str(Path(tmp) / name)
            proof = json.dumps({"python": True, "docker": True, "git": False, "node": False, "npm": False})
            with patch.object(probe.shutil, "which", side_effect=which), patch.object(Path, "symlink_to") as link, \
                    patch.object(probe, "run", side_effect=[proof, "2.38.2"]) as command:
                env = probe.installer_environment(directory)
            self.assertEqual(env["PATH"], str(directory))
            self.assertEqual(link.call_count, 3)
            self.assertEqual(command.call_args_list[-1].args[0], ["docker", "--context", "default", "compose", "version", "--short"])

    def test_blocked_case_requires_unchanged_active_receipt_and_resources(self):
        with tempfile.TemporaryDirectory() as tmp:
            receiver = object.__new__(probe.Receiver); receiver.state = Path(tmp)
            (receiver.state / "active.json").write_text("unchanged")
            receiver.resources = resources
            receiver.invoke = lambda *args, **kwargs: (2, {"reason": "PERSISTENT_VOLUME_DRIFT"})
            self.assertFalse(receiver.blocked("PERSISTENT_VOLUME_DRIFT")["resourceMutation"])
            def wrong(*args, **kwargs):
                (receiver.state / "active.json").write_text("modified")
                return 2, {"reason": "PERSISTENT_VOLUME_DRIFT"}
            receiver.invoke = wrong
            with self.assertRaisesRegex(build.ProofError, "NEGATIVE_MUTATED"):
                receiver.blocked("PERSISTENT_VOLUME_DRIFT")

    def cleanup_receiver(self, tmp):
        receiver = object.__new__(probe.Receiver); receiver.state = Path(tmp) / "state"; receiver.state.mkdir()
        owner = {"id": "a" * 32, "project": build.PROJECT, "engine": "f" * 64,
                 "state": probe.hashlib.sha256(str(receiver.state.absolute()).encode()).hexdigest()}
        build.write_json(receiver.state / "owner.json", owner)
        receiver.report = {"engine": {"fingerprint": owner["engine"]}}
        receiver.clients = []; receiver.fmt = SimpleNamespace(OWNER="DOCKER-TEST-BUNDLE-001")
        receiver.resources = resources
        receiver.cleanup_expected = probe.resource_identity(resources())["volumes"]
        mutations = []
        def command(*args, **kwargs):
            if args[:2] == ("volume", "inspect"):
                if args[-1].endswith("-operation-lock"): return None
                if args[-1].endswith("-installation"):
                    return json.dumps([{"Labels": {"io.izo.bundle": receiver.fmt.OWNER,
                        "io.izo.bundle.installation": owner["id"], "io.izo.bundle.state": owner["state"],
                        "io.izo.bundle.engine": owner["engine"]}}])
                return json.dumps(resources()["volumes"])
            mutations.append(args)
            return "removed"
        receiver.docker = SimpleNamespace(run=command)
        return receiver, mutations

    def test_foreign_installation_volume_is_refused_before_any_removal(self):
        with tempfile.TemporaryDirectory() as tmp:
            receiver, mutations = self.cleanup_receiver(tmp)
            foreign = resources(); foreign["volumes"][0]["Labels"]["io.izo.bundle.installation"] = "c" * 32
            receiver.resources = lambda: foreign
            with self.assertRaisesRegex(build.ProofError, "CLEANUP_UNEXPECTED_VOLUME_IDENTITY"):
                receiver.cleanup()
            self.assertEqual(mutations, [])

    def test_unknown_valid_generation_drift_is_not_adopted_for_cleanup(self):
        with tempfile.TemporaryDirectory() as tmp:
            receiver, mutations = self.cleanup_receiver(tmp)
            drifted = resources(); drifted["volumes"][0]["Labels"]["io.izo.bundle.generation"] = "e" * 32
            receiver.resources = lambda: drifted
            with self.assertRaisesRegex(build.ProofError, "CLEANUP_UNEXPECTED_VOLUME_IDENTITY"):
                receiver.cleanup()
            self.assertEqual(mutations, [])

    def test_stale_lock_is_never_deleted_by_cleanup(self):
        with tempfile.TemporaryDirectory() as tmp:
            receiver, mutations = self.cleanup_receiver(tmp)
            receiver.docker = SimpleNamespace(run=lambda *args, **kwargs: "exists")
            with self.assertRaisesRegex(build.ProofError, "CLEANUP_REFUSES_STALE_OR_ACTIVE_LOCK"):
                receiver.cleanup()
            self.assertEqual(mutations, [])

    def test_cleanup_removes_only_enumerated_owned_resources_and_claim(self):
        with tempfile.TemporaryDirectory() as tmp:
            receiver, mutations = self.cleanup_receiver(tmp)
            with patch.object(probe, "inventory", return_value={"containers": [], "volumes": [], "images": ["imported"]}):
                self.assertEqual(receiver.cleanup()["status"], "PASS")
            self.assertEqual(mutations, [("rm", "-f", "container"), ("volume", "rm", build.PROJECT + "_worker_ipc"),
                                         ("volume", "rm", build.PROJECT + "-installation")])


if __name__ == "__main__":
    unittest.main()
