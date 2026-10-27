"""Failure-sensitive local tests; no Docker daemon, provider or D2 operations."""
from contextlib import closing, contextmanager, redirect_stdout
from copy import deepcopy
import io
import json
import os
from pathlib import Path
import platform
import sqlite3
import stat
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

sys.dont_write_bytecode = True
import synthetic_runtime_accept as accept
import synthetic_runtime_checks as checks


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(checks.encoded(value))


def volume(name):
    return {"Name": name, "CreatedAt": "2026-10-27T20:00:00Z", "Driver": "local", "Scope": "local",
            "Labels": {"io.izo.bundle": "test", "io.izo.bundle.generation": "a" * 32}, "Options": None}


class OperationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.c = object.__new__(accept.Controller)
        self.c.root = self.root; self.c.state = self.root / "installed"; self.c.project = "izo-asa-bundle-runtime-test"
        self.c.plan = {"observationSeconds": 360, "bundles": {"B": {"manifestSha256": "b" * 64}}}; self.c.pin = "a" * 64
        self.c.active = "B"; self.c.manifests = {"B": {}}; self.c.owner = {"id": "owner"}; self.c.before = {x: {} for x in ("containers", "volumes", "networks")}
        self.c.product = None; self.c.claim = volume(self.c.project + "-installation")
        self.c.docker = Mock(); self.c.fmt = Mock(); self.c.runtime = Mock()
        self.c.runtime.atomic_json.side_effect = write_json; self.held = False
        @contextmanager
        def lock(*args):
            self.assertFalse(self.held); self.held = True
            try: yield
            finally: self.held = False
        self.c.runtime.engine_lock.side_effect = lock
        self.c.receipt = self.root / "runtime-acceptance.json"
        self.c.report = {"status": "RUNNING", "steps": []}

    def topology(self, started="old", new=False):
        return {"containers": {r: {"id": r + ("-new" if new else "-old"), "startedAt": started} for r in ("backend", "web", "guard")},
                "netns": {r: "net:[100]" for r in ("backend", "web", "guard")}, "volumes": {x: volume(x) for x in ("data", "media")}}

    def test_post_deadline_restart_is_not_reported_continuous_uptime(self):
        initial = {"topology": self.topology(), "database": {}, "product": {}}
        self.c.accepted = initial; self.c.capture = Mock(return_value=initial)
        self.c.persist = Mock(return_value={**initial, "topology": self.topology(started="new")})
        self.c.next_generation = Mock()
        with patch.object(accept.time, "monotonic", side_effect=[0, 0, 360, 360, 360]), patch.object(accept.time, "sleep"):
            with self.assertRaisesRegex(checks.CheckFailure, "UPTIME_INTERRUPTED"): self.c.observe()
        self.c.next_generation.assert_not_called()

    def test_lifecycle_uses_existing_lock_and_generation_only_after_release(self):
        before = {"topology": self.topology()}; after = {"topology": self.topology(started="new", new=True)}
        self.c.persist = Mock(side_effect=[before, before, after])
        self.c.docker.compose.side_effect = lambda *args: self.assertTrue(self.held)
        self.c.next_generation = lambda: self.assertFalse(self.held)
        self.c.lifecycle("group-recreate")
        self.assertEqual(self.c.docker.compose.call_count, 2)
        self.assertEqual(self.c.docker.compose.call_args.args[-1], "--force-recreate")

    def test_failed_lifecycle_does_not_retry_or_cleanup(self):
        self.c.persist = Mock(return_value={"topology": self.topology()})
        self.c.runtime.wait_health.side_effect = checks.CheckFailure("READINESS_FAILED")
        self.c.next_generation = Mock()
        with self.assertRaisesRegex(checks.CheckFailure, "READINESS_FAILED"): self.c.lifecycle("backend-restart")
        self.assertEqual(self.c.docker.compose.call_count, 1); self.c.next_generation.assert_not_called()
        self.assertFalse(self.held)

    def test_run_timeout_retains_resources_and_writes_secret_free_failure(self):
        self.c.preflight = Mock(); self.c.unpack = Mock(return_value={})
        self.c.install = Mock(side_effect=subprocess.TimeoutExpired(["python", "secret-argument"], 300))
        self.c.cleanup = Mock()
        with patch.object(accept, "installer_environment", return_value={}), redirect_stdout(io.StringIO()): result = self.c.run()
        self.assertEqual(result["status"], "FAILED_RESOURCES_RETAINED")
        report = checks.read_json(self.c.receipt)
        self.assertEqual(report["reason"], "TimeoutExpired"); self.assertNotIn("secret-argument", self.c.receipt.read_text())
        self.c.cleanup.assert_not_called(); self.c.docker.compose.assert_not_called()
        self.assertFalse((self.root / "controller.lock").exists())

    def cleanup_fixture(self):
        topology = self.topology(); database = {"idle": True, "charges": {}, "protectedTables": {}}
        write_json(self.c.state / "owner.json", self.c.owner); write_json(self.c.state / "active.json", {"active": "B"})
        report = {"status": accept.STATUS, "planSha256": self.c.pin, "project": self.c.project, "foreignResourcesChanged": 0,
                  "steps": [{"status": "PASS"} for _ in range(11)], "owner": self.c.owner, "claim": self.c.claim,
                  "foreignBefore": self.c.before, "accepted": {"topology": topology, "database": database, "product": {"jobs": []}},
                  "ownerReceiptSha256": checks.digest(self.c.state / "owner.json"), "activeReceiptSha256": checks.digest(self.c.state / "active.json")}
        write_json(self.c.receipt, report); self.c.scope_check = Mock(); self.c.namespace_names = Mock()
        self.c.runtime.owned_resources.return_value = {"containers": [], "networks": [], "volumes": list(topology["volumes"].values())}
        def run(*args):
            if args[:2] == ("volume", "inspect"): return json.dumps([self.c.claim if args[2] == self.c.claim["Name"] else topology["volumes"][args[2]]])
            return "removed"
        self.c.docker.run.side_effect = run
        return topology, database, checks.digest(self.c.receipt)

    def test_cleanup_pin_topology_or_database_drift_prevents_mutation(self):
        topology, database, pin = self.cleanup_fixture()
        with self.assertRaisesRegex(checks.CheckFailure, "ACCEPTANCE_RECEIPT_PIN_MISMATCH"): self.c.cleanup("0" * 64)
        for view, data in ((self.topology(started="changed"), database), (topology, {"idle": False})):
            with patch.object(checks, "topology", return_value=view), patch.object(checks, "database", return_value=data):
                with self.assertRaises(checks.CheckFailure): self.c.cleanup(pin)
        self.c.docker.compose.assert_not_called(); self.c.runtime.engine_lock.assert_not_called()
        self.assertFalse((self.root / "cleanup.json").exists())

    def test_scope_refuses_owner_active_claim_and_volume_drift_before_mutations(self):
        self.c.scope = {"engineFingerprint": "e" * 64}; self.c.fmt.OWNER = "test"
        self.c.owner = {"engine": "e" * 64, "id": "a" * 32, "project": self.c.project,
            "profile": "synthetic-runtime", "test_only": True,
            "state": checks.hashlib.sha256(os.path.normcase(str(self.c.state.absolute())).encode()).hexdigest()}
        self.c.claim.update(Labels={"io.izo.bundle": "test", "io.izo.bundle.installation": "a" * 32,
            "io.izo.bundle.state": self.c.owner["state"], "io.izo.bundle.engine": "e" * 64,
            "io.izo.bundle.profile": "synthetic-runtime"})
        active = {"manifest_sha256": "b" * 64, "profile": "synthetic-runtime", "engine": "e" * 64,
                  "source_sha": accept.SOURCES["B"], "project": self.c.project, "status": "TEST_RUNTIME_VERIFIED",
                  "production_authorized": False, "volumes": {"data": {"created": "old", "generation": "g"}}}
        write_json(self.c.state / "owner.json", self.c.owner); write_json(self.c.state / "active.json", active)
        self.c.docker.engine.return_value = "e" * 64; self.c.namespace_names = Mock()
        self.c.runtime.volume_identity.return_value = active["volumes"]
        self.c.runtime.owned_resources.return_value = {"containers": [{"Id": "backend"}], "volumes": [volume("data")], "networks": [{"Name": "network"}]}
        claim = deepcopy(self.c.claim); self.c.docker.run.side_effect = lambda *args: json.dumps([claim])
        with patch.object(checks, "inventory", return_value=self.c.before):
            self.c.scope_check()
            for target, field, value, reason in (("owner", "id", "b" * 32, "OWNER_BINDING_CHANGED"),
                ("active", "manifest_sha256", "c" * 64, "ACTIVE_RECEIPT_CHANGED")):
                original = self.c.owner if target == "owner" else active
                write_json(self.c.state / (target + ".json"), {**original, field: value})
                with self.assertRaisesRegex(checks.CheckFailure, reason): self.c.scope_check()
                write_json(self.c.state / (target + ".json"), original)
            claim["CreatedAt"] = "recreated"
            with self.assertRaisesRegex(checks.CheckFailure, "INSTALLATION_CLAIM_DRIFT"): self.c.scope_check()
            claim["CreatedAt"] = self.c.claim["CreatedAt"]
            claim["Options"] = {"device": "foreign"}
            with self.assertRaisesRegex(checks.CheckFailure, "INSTALLATION_CLAIM_CHANGED"): self.c.scope_check()
            claim["Options"] = None; self.c.runtime.volume_identity.return_value = {"data": {"created": "new", "generation": "g"}}
            with self.assertRaisesRegex(checks.CheckFailure, "VOLUME_RECEIPT_DRIFT"): self.c.scope_check()
        self.c.docker.compose.assert_not_called()
        self.assertTrue(all(call.args[:2] == ("volume", "inspect") for call in self.c.docker.run.call_args_list))

    def test_cleanup_partial_failure_records_only_removed_owned_volume_no_retry(self):
        topology, database, pin = self.cleanup_fixture()
        original = self.c.docker.run.side_effect
        def drift(*args):
            if args == ("volume", "inspect", "media"):
                return json.dumps([{**topology["volumes"]["media"], "CreatedAt": "recreated"}])
            return original(*args)
        self.c.docker.run.side_effect = drift
        with patch.object(checks, "topology", return_value=topology), patch.object(checks, "database", return_value=database), \
             patch.object(checks, "inventory", return_value=self.c.before): result = self.c.cleanup(pin)
        self.assertEqual(result["status"], "FAILED_RESOURCES_RETAINED")
        self.assertEqual(result["reason"], "CLEANUP_VOLUME_DRIFT"); self.assertEqual(result["removedVolumes"], ["data"])
        self.assertEqual([call.args for call in self.c.docker.run.call_args_list if call.args[:2] == ("volume", "rm")], [("volume", "rm", "data")])
        self.assertEqual(checks.read_json(self.root / "cleanup.json"), result)

    def test_cleanup_success_exact_data_and_claim_only(self):
        topology, database, pin = self.cleanup_fixture()
        with patch.object(checks, "topology", return_value=topology), patch.object(checks, "database", return_value=database), \
             patch.object(checks, "inventory", return_value=self.c.before): result = self.c.cleanup(pin)
        self.assertEqual(result["status"], "PASS_OWNED_SYNTHETIC_CLEANUP")
        self.assertEqual(result["removedVolumes"], ["data", "media"])
        self.assertEqual(result["claimsRemoved"], 1)
        self.assertEqual(self.c.docker.compose.call_args.args[-1], "down")

    def test_idempotency_header_restored_after_request_error_without_retry(self):
        product = object.__new__(checks.Product); original = [("Accept", "application/json")]
        product.owner = types.SimpleNamespace(opener=types.SimpleNamespace(addheaders=original), request=Mock(side_effect=RuntimeError("FAIL")))
        with self.assertRaises(RuntimeError): product.post_job({"provider": "comfyui"}, "key")
        self.assertIs(product.owner.opener.addheaders, original); product.owner.request.assert_called_once()


if __name__ == "__main__":
    unittest.main()
