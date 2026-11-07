"""Targeted provenance and refusal checks with temporary bytes; no Docker or network."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import call, patch
import zipfile

import docker_portable_delivery_proof as proof


def engine(boot):
    value = {"fingerprint": "a" * 64, "context": "default", "locality": {"version": 1, "bootFingerprint": boot,
        "endpoint": "unix:///var/run/docker.sock", "socketPath": "/run/docker.sock", "socketType": "socket",
        "socketOwnerUid": 0, "hostnameFingerprint": "b" * 64, "kernelRelease": "6.8.0-test"}}
    value["engineInstanceFingerprint"] = proof.common.engine_instance_fingerprint(value, boot)
    return value


class PortabilityProofTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup); self.root = Path(temp.name)
        self.args = SimpleNamespace(root=self.root / "receiver", transfer=self.root, tooling=self.root / "tooling")
        (self.args.tooling / "tools").mkdir(parents=True)
        for name in proof.MODULES:
            (self.root / name).write_bytes(b"synthetic bootstrap bytes"); (self.args.tooling / "tools" / name).write_bytes(b"synthetic bootstrap bytes")
        self.runner = {"head": "f" * 40, "runId": "1", "attempt": "1", "job": "receiver", "bootFingerprint": "c" * 64}
        self.report = {"runner": self.runner, "engine": engine("c" * 64)}
        self.manifest = {"format": 2, "profile": "synthetic-runtime", "source_sha": proof.SOURCE, "tooling_sha": proof.TOOLING,
            "project": proof.PROJECT, "ports": proof.PORTS, "production_authorized": False, "model_execution": False,
            "image_identity": {"version": 1, "roles": {}}}
        body = json.dumps(self.manifest).encode()
        with zipfile.ZipFile(self.root / "release.zip", "w") as archive:
            archive.writestr("bundle.json", body)
            for name in proof.MODULES: archive.writestr(name, (self.args.tooling / "tools" / name).read_bytes())
        receipt = {"status": "TEST_BUNDLE_BUILT", "source_sha": proof.SOURCE, "tooling_sha": proof.TOOLING,
            "project": proof.PROJECT, "images_embedded": True, "production_authorized": False,
            "archive_bytes": (self.root / "release.zip").stat().st_size, "archive_sha256": proof.common.digest(self.root / "release.zip"),
            "manifest_sha256": hashlib.sha256(body).hexdigest()}
        proof.common.write_json(self.root / "release.receipt.json", receipt)
        proof.common.write_json(self.root / "context.json", {"contract": "DOCKER-CANONICAL-CANDIDATE-002",
            "status": "PASS_CONTEXT_EXPORT_ONLY", "sourceSha": proof.SOURCE, "sourceDirty": False})
        self.prior = {"contract": proof.CONTRACT, "status": "PASS_PORTABLE_PRODUCER_ONLY", "applicationSha": proof.SOURCE,
            "acceptanceSha": proof.SOURCE, "workflowSha": self.runner["head"], "toolingSha": proof.TOOLING,
            "before": {"images": [], "containers": [], "volumes": []}, "imageStore": {"kind": "classic"},
            "runner": {**self.runner, "job": "producer", "bootFingerprint": "d" * 64}, "engine": engine("d" * 64),
            "contextProof": proof.context_proof(self.root), "imageIdentity": self.manifest["image_identity"],
            "bootstrap": {name: proof.common.digest(self.root / name) for name in proof.BOOTSTRAP},
            "moduleHashes": {name: proof.common.digest(self.args.tooling / "tools" / name) for name in proof.MODULES},
            "release": {"receipt": receipt, "receiptSha256": proof.common.digest(self.root / "release.receipt.json")}}

    def validate(self, pin=None):
        proof.common.write_json(self.root / "producer.json", self.prior)
        with patch.dict(os.environ, {"IZO_PRODUCER_RECEIPT_SHA256": pin or proof.common.digest(self.root / "producer.json")}):
            return proof.transfer(self.args, self.report)

    def test_separate_boots_same_persistent_id_and_exact_bootstrap_are_accepted(self):
        self.assertEqual(self.validate(), self.manifest)

    def test_wrong_refs_store_status_and_nonempty_source_are_refused(self):
        original = deepcopy(self.prior)
        for key, value in (("workflowSha", proof.SOURCE), ("workflowSha", proof.TOOLING),
                           ("toolingSha", proof.SOURCE), ("toolingSha", self.runner["head"]), ("applicationSha", "e" * 40),
                           ("acceptanceSha", "e" * 40), ("status", "PASS_SYNTHETIC_RUNTIME_LIFECYCLE_ONLY"),
                           ("imageStore", {"kind": "containerd"}), ("before", {"images": ["foreign"]})):
            self.prior = {**deepcopy(original), key: value}
            with self.subTest(key=key), self.assertRaisesRegex(proof.common.ProofError, "PRODUCER_CONTRACT_CHANGED"): self.validate()

    def test_wrong_run_and_same_boot_are_refused(self):
        for key, value, reason in (("attempt", "2", "SEPARATE_JOB_REQUIRED"), ("bootFingerprint", "c" * 64, "DISTINCT_BOOT_REQUIRED")):
            old = self.prior["runner"][key]; self.prior["runner"][key] = value
            with self.subTest(key=key), self.assertRaisesRegex(proof.common.ProofError, reason): self.validate()
            self.prior["runner"][key] = old

    def test_corrupt_pin_bootstrap_archive_and_context_are_refused_before_import(self):
        with self.assertRaisesRegex(proof.common.ProofError, "PRODUCER_RECEIPT_PIN_MISMATCH"): self.validate("0" * 64)
        for name, reason in ((proof.BOOTSTRAP[1], "SUPPORT_TRANSFER_CHANGED"), ("release.zip", "TRANSFER_RELEASE_CHANGED"),
                             ("context.json", "CONTEXT_PROOF_CHANGED")):
            path = self.root / name; saved = path.read_bytes(); path.write_bytes(b"{}")
            with self.subTest(name=name), self.assertRaisesRegex(proof.common.ProofError, reason): self.validate()
            path.write_bytes(saved)
        with zipfile.ZipFile(self.root / "release.zip", "w") as archive:
            archive.writestr("bundle.json", json.dumps(self.manifest).encode())
            for name in proof.MODULES:
                payload = (self.root / name).read_bytes()
                archive.writestr(name, b"X" + payload[1:] if "runtime" in name else payload)
        record = self.prior["release"]; receipt = record["receipt"]
        receipt.update(archive_sha256=proof.common.digest(self.root / "release.zip"), archive_bytes=(self.root / "release.zip").stat().st_size)
        proof.common.write_json(self.root / "release.receipt.json", receipt)
        record["receiptSha256"] = proof.common.digest(self.root / "release.receipt.json")
        with self.assertRaisesRegex(proof.common.ProofError, "EMBEDDED_TOOLING_CHANGED"): self.validate()

    def test_classic_refusal_and_fake_workflow_head_precede_any_build(self):
        with patch.object(proof.common, "run") as command:
            with self.assertRaisesRegex(proof.common.ProofError, "CLASSIC_PRODUCER_REQUIRED"): proof.producer(None, {"imageStore": {"kind": "containerd"}})
            with self.assertRaisesRegex(proof.common.ProofError, "WORKFLOW_HEAD_IS_NOT_APPLICATION_HEAD"): proof.guards(None, {"head": proof.SOURCE})
            with self.assertRaisesRegex(proof.common.ProofError, "WORKFLOW_HEAD_IS_NOT_TOOLING_HEAD"): proof.guards(None, {"head": proof.TOOLING})
        command.assert_not_called()

    def test_four_clean_distinct_checkout_roles_use_their_actual_pins(self):
        args = SimpleNamespace(action="producer", driver=self.root / "driver", tooling=self.args.tooling,
                               source=self.root / "application", acceptance=self.root / "acceptance", root=self.args.root, transfer=None)
        helper = args.driver / "tools/docker_linux_bundle_build.py"; helper.parent.mkdir(parents=True)
        helper.write_bytes(Path(proof.common.__file__).read_bytes())
        (args.driver / ".python-version").write_text(proof.platform.python_version())
        with patch.object(proof, "__file__", str(helper.with_name("docker_portable_delivery_proof.py"))), \
             patch.object(proof.common, "__file__", str(helper)), patch.object(proof.common, "source_guard") as guard, \
             patch.object(proof.common, "run") as command:
            proof.guards(args, self.runner)
        self.assertEqual(guard.call_args_list, [call(args.driver, self.runner["head"]), call(args.tooling, proof.TOOLING),
                                               call(args.source, proof.SOURCE), call(args.acceptance, proof.SOURCE)])
        command.assert_not_called()

    def test_dirty_fixed_tooling_refuses_before_docker(self):
        args = SimpleNamespace(action="receiver", driver=self.root / "driver", tooling=self.args.tooling,
                               root=self.args.root, transfer=self.root / "transfer")
        with patch.object(proof.common, "source_guard", side_effect=[None, proof.common.ProofError("CLEAN_EXACT_REPOSITORY_REQUIRED")]) as guard, \
             patch.object(proof.common, "run") as command:
            with self.assertRaisesRegex(proof.common.ProofError, "CLEAN_EXACT_REPOSITORY_REQUIRED"): proof.guards(args, self.runner)
        self.assertEqual(guard.call_args_list, [call(args.driver, self.runner["head"]), call(args.tooling, proof.TOOLING)])
        command.assert_not_called()

    def test_swapped_driver_and_tooling_roots_refuse_before_docker(self):
        driver = self.root / "driver"; heads = {driver: self.runner["head"], self.args.tooling: proof.TOOLING}
        args = SimpleNamespace(action="receiver", driver=self.args.tooling, tooling=driver,
                               root=self.args.root, transfer=self.root / "transfer")
        def source_guard(path, sha):
            proof.require(heads[path] == sha, "CLEAN_EXACT_REPOSITORY_REQUIRED")
        with patch.object(proof.common, "source_guard", side_effect=source_guard), patch.object(proof.common, "run") as command:
            with self.assertRaisesRegex(proof.common.ProofError, "CLEAN_EXACT_REPOSITORY_REQUIRED"): proof.guards(args, self.runner)
        command.assert_not_called()

    def test_build_receipt_cannot_substitute_workflow_head_for_tooling(self):
        record = self.prior["release"]; record["receipt"]["tooling_sha"] = self.runner["head"]
        proof.common.write_json(self.root / "release.receipt.json", record["receipt"])
        record["receiptSha256"] = proof.common.digest(self.root / "release.receipt.json")
        with patch.object(proof.common, "run") as command, patch.object(proof.subprocess, "run") as child:
            with self.assertRaisesRegex(proof.common.ProofError, "TRANSFER_RELEASE_CHANGED"): self.validate()
        command.assert_not_called(); child.assert_not_called()

    def test_failed_existing_installer_is_not_retried_or_relabelled(self):
        self.report["release"] = self.prior["release"]
        failed = subprocess.CompletedProcess([], 2, '{"status":"BLOCKED","reason":"IMAGE_IDENTITY_INVALID"}', "")
        with patch.object(proof, "transfer", return_value=self.manifest), patch.object(proof.common, "run", return_value="{}") as command, \
             patch.object(proof.subprocess, "run", return_value=failed) as installer:
            with self.assertRaisesRegex(proof.common.ProofError, "PORTABLE_INSTALL_FAILED"): proof.receiver(self.args, self.report)
        installer.assert_called_once(); self.assertEqual(command.call_count, 1)
        self.assertIn("extract", command.call_args.args[0]); self.assertNotIn("build", command.call_args.args[0])
        self.assertEqual(self.report["stage"], "install")
        self.assertNotIn("status", self.report)


if __name__ == "__main__":
    unittest.main()
