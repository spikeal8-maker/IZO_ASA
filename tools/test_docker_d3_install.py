"""Admission uses real bounded JSON files; missing D1/D2 never reaches image load."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from tools import docker_d3_install as subject
from tools.docker_d3_images import read_installations
from tools.docker_shadow_product import ProductError
from tools.test_docker_d3_orchestration import observations, SHA

BASE = "b" * 40


class EntryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.rows = observations()
        self.paths, self.proofs = [], []
        for replica in (1, 2):
            directory = self.root / f"linux-{replica}"
            directory.mkdir()
            rows = self.rows[(replica - 1) * 3:replica * 3]
            summary = {"repository": "spikeal8-maker/IZO_ASA", "sourceSha": SHA, "baseSha": BASE,
                "replica": replica, "completedFixtureRuns": 3, "D1Status": "PASS", "status": "FAIL", "host": rows[0]["host"]}
            (directory / "summary.json").write_text(json.dumps(summary))
            hashes = []
            for number, row in enumerate(rows, 1):
                path = directory / f"run-{number}" / "receipt.json"
                path.parent.mkdir(); path.write_text(json.dumps(row))
                hashes.append({"path": f"run-{number}/receipt.json", "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
            self.paths.append(directory); self.proofs.append(hashes)
        self.images = self.root / "images"; self.images.mkdir()
        self.manifest = {"version": 1, "status": "PASS", "evidenceClass": "EXACT_TESTED_IMAGE_TRANSFER",
            "repository": "spikeal8-maker/IZO_ASA", "sourceSha": SHA, "baseSha": BASE, "runId": "17", "attempt": "1",
            "replica": 1, "installReceipts": self.proofs[0], "selectedProject": self.rows[2]["project"]}
        self.output = self.root / "output"; self.output.mkdir()
        self.args = SimpleNamespace(source_sha=SHA, base_sha=BASE, evidence_dir=self.output,
            linux_1_dir=self.paths[0], linux_2_dir=self.paths[1], images_dir=self.images)
        self.host = {"runId": "17", "attempt": "1", "engineId": "new-d3-engine-id",
                     "machineIdentitySha256": "e" * 64, "bootIdentitySha256": "f" * 64,
                     "runnerName": "GitHub Actions third-d3-vm"}
        self.seed = SimpleNamespace(sha=SHA, root=self.root, source_guard=Mock())

    def call(self, report=None, *, admission_only=False):
        (self.images / "handoff.json").write_text(json.dumps(self.manifest))
        report = report or {"status": "PARTIAL", "controlledScenarios": "PASS", "remainingAcceptance": ["real models"]}
        evidence = {"status": "FAIL"}
        with patch.dict(os.environ, {"RUNNER_TEMP": str(self.root)}), \
                patch.object(subject, "load_images", return_value={"status": "PASS"}) as load, \
                patch.object(subject, "runtime_sources", return_value={"fixed-io": "a" * 64}), \
                patch.object(subject, "rehearse_d3", return_value=report) as runtime:
            try:
                result = subject.run_transferred(self.seed, self.host, self.args, evidence, admission_only=admission_only)
                return result, evidence
            finally:
                self.load, self.runtime = load, runtime

    def test_all_six_actual_receipt_files_allow_controlled_run_but_partial_exit_is_nonzero(self):
        result, evidence = self.call()
        self.assertEqual(result, 2)
        self.assertEqual(evidence["status"], "PARTIAL")
        self.assertEqual(evidence["D1D2Admission"]["D1Assertions"], 48)
        self.assertFalse(evidence["D1D2Admission"]["promotedPartial"])
        self.load.assert_called_once()
        self.runtime.assert_called_once()

    def test_failed_last_install_or_stale_artifact_digest_cannot_load_images(self):
        for fault in ("D1", "D2", "digest", "run"):
            path = self.paths[1] / "run-3/receipt.json"
            row = deepcopy(self.rows[-1])
            if fault == "D1": row["checks"]["D1-08"]["status"] = "FAIL"
            if fault == "D2": row["extended"]["results"]["recovery"]["checks"]["D2-03"]["status"] = "FAIL"
            if fault == "digest": self.manifest["installReceipts"] = []
            if fault == "run": self.manifest["attempt"] = "2"
            path.write_text(json.dumps(row))
            with self.subTest(fault=fault), self.assertRaises(ProductError):
                self.call()
            self.load.assert_not_called(); self.runtime.assert_not_called()
            self.manifest["attempt"], self.manifest["installReceipts"] = "1", self.proofs[0]

    def test_reused_install_vm_is_rejected_before_docker_load(self):
        original = deepcopy(self.host)
        for key in ("bootIdentitySha256", "runnerName"):
            self.host = {**original, key: self.rows[0]["host"][key]}
            with self.subTest(identity=key), self.assertRaisesRegex(ProductError, "NEW_VM_REQUIRED"):
                self.call()
            self.load.assert_not_called()

    def test_new_boot_and_runner_admit_the_same_golden_machine_and_engine_ids(self):
        self.host["machineIdentitySha256"] = self.rows[0]["host"]["machineIdentitySha256"]
        self.host["engineId"] = self.rows[0]["host"]["engineId"]
        result, evidence = self.call()
        self.assertEqual(result, 2)
        self.assertEqual(evidence["D1D2Admission"]["status"], "PASS")
        self.load.assert_called_once()

    def test_admission_stage_does_not_load_images_or_claim_runtime_pass(self):
        result, evidence = self.call(admission_only=True)
        self.assertEqual(result, 0)
        self.assertEqual(evidence["status"], "NOT_RUN")
        self.assertEqual(evidence["D1D2Admission"]["status"], "PASS")
        self.load.assert_not_called(); self.runtime.assert_not_called()

    def test_missing_third_receipt_and_parent_input_directory_fail_closed(self):
        directory = self.paths[0]
        path = directory / "run-3/receipt.json"; path.unlink()
        with self.assertRaises(FileNotFoundError):
            read_installations(directory, SHA, BASE, "17", "1", 1)
        with self.assertRaises(ProductError):
            subject.owned_input(directory.parent, self.root, self.output)

    def test_runtime_failure_is_not_replaced_by_successful_image_transfer(self):
        result, evidence = self.call({"status": "FAIL", "controlledScenarios": "FAIL", "remainingAcceptance": ["failed media"]})
        self.assertEqual(result, 1)
        self.assertEqual(evidence["status"], "FAIL")
