"""Storage/transport contracts; Docker D2 PASS requires the separate runtime run."""
from __future__ import annotations

import base64
import copy
import hashlib
import http.cookiejar
import io
import json
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import types
import unittest
from pathlib import Path
from contextlib import ExitStack
from unittest.mock import patch

from tools import docker_clean_storage as storage

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = (ROOT / "tools/docker_shadow_storage.py").read_text(encoding="utf-8")
CID = "c" * 64
PROJECT = "izo-asa-shadow-storage-contract"


def archive_bytes(entries):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as archive:
        for name, content, kind in entries:
            entry = tarfile.TarInfo(name)
            entry.type = kind
            entry.size = len(content) if kind == tarfile.REGTYPE else 0
            entry.linkname = "outside"
            archive.addfile(entry, io.BytesIO(content))
    return output.getvalue()


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.data, self.media = self.root / "source-data", self.root / "source-media"
        self.data.mkdir()
        self.media.mkdir()
        self.database = self.data / "app.sqlite3"
        self.connection = sqlite3.connect(self.database)
        self.addCleanup(self.connection.close)
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.executescript("""
            CREATE TABLE users (id TEXT PRIMARY KEY, token_balance INTEGER);
            CREATE TABLE jobs (id TEXT PRIMARY KEY, user_id TEXT REFERENCES users(id), status TEXT);
            CREATE TABLE images (id TEXT PRIMARY KEY, user_id TEXT REFERENCES users(id), url TEXT, thumbnail_url TEXT);
            CREATE TABLE schema_migrations (id TEXT PRIMARY KEY, applied_at TEXT);
            CREATE TABLE token_ledger (id TEXT PRIMARY KEY, user_id TEXT REFERENCES users(id), delta INTEGER);
            INSERT INTO users VALUES ('fixture-user', 50);
            INSERT INTO jobs VALUES ('fixture-job', 'fixture-user', 'completed');
            INSERT INTO images VALUES ('fixture-image', 'fixture-user', '/api/media/image.png', '/api/media/thumb.png');
            INSERT INTO schema_migrations VALUES ('001', 'fixture-timestamp');
            INSERT INTO token_ledger VALUES ('fixture-charge', 'fixture-user', -4);
        """)
        self.connection.commit()
        for name in ("image.png", "thumb.png", "_shadow_topology_probe.txt"):
            (self.media / name).write_bytes(("fixture-media:" + name).encode())
        self.target_data, self.target_media = self.root / "restored-data", self.root / "restored-media"
        self.target_data.mkdir()
        self.target_media.mkdir()

    def export(self):
        return storage.backup_export(CONTRACT, str(self.database), str(self.media))

    def restore(self, exported, payload=None):
        payload = base64.b64decode(exported["archive"]) if payload is None else payload
        path = self.root / "transfer.tar.gz"
        path.write_bytes(payload)
        return storage.restore_import(CONTRACT, str(path), str(self.target_data / "app.sqlite3"),
            str(self.target_media), hashlib.sha256(payload).hexdigest())

    def test_live_wal_backup_restores_complete_database_media_and_probe(self):
        self.assertTrue(Path(str(self.database) + "-wal").stat().st_size > 0)
        self.connection.execute("INSERT INTO token_ledger VALUES ('wal-only-charge', 'fixture-user', -7)")
        self.connection.commit()
        exported = self.export()
        before = storage.storage_probe(CONTRACT, self.database, self.media)
        restored = self.restore(exported)
        self.assertEqual(restored["restoredState"], before)
        self.assertEqual(exported["receipt"]["sourceState"], before)
        self.assertEqual(exported["receipt"]["activeJobs"], 0)
        self.assertEqual(restored["restoredState"]["database"]["tables"]["token_ledger"]["rows"], 2)
        self.assertEqual(restored["restoredState"]["database"]["imageReferences"], 2)
        self.assertEqual(set(restored["negativeCases"]), {"database", "media", "incomplete"})
        self.assertFalse(restored["invalidDestinationsWritten"])
        self.assertEqual((self.target_media / "_shadow_topology_probe.txt").read_bytes(),
                         (self.media / "_shadow_topology_probe.txt").read_bytes())
        self.assertEqual(storage.storage_probe(CONTRACT, self.database, self.media), before)
        self.assertFalse((self.root / "transfer.tar.gz").exists())
        self.assertNotIn("fixture-user", json.dumps(exported["receipt"]))

    def test_active_job_prevents_backup(self):
        self.connection.execute("UPDATE jobs SET status='running'")
        self.connection.commit()
        with self.assertRaisesRegex(storage.StorageError, "STORAGE_SOURCE_JOBS_NOT_QUIESCENT"):
            self.export()
        self.assertFalse(list(self.target_data.iterdir()))

    def test_invalid_archived_database_media_or_marker_never_writes_target(self):
        exported = self.export()
        original = base64.b64decode(exported["archive"])
        with tarfile.open(fileobj=io.BytesIO(original), mode="r:gz") as archive:
            entries = [(item.name, archive.extractfile(item).read(), item.type) for item in archive.getmembers()]
        for failure in ("database", "media", "incomplete"):
            with self.subTest(failure=failure):
                changed = []
                for name, value, kind in entries:
                    if failure == "incomplete" and name.endswith("/COMPLETED"):
                        continue
                    if (failure == "database" and name.endswith("/database.sqlite3")) or (
                        failure == "media" and "/media-objects/" in name):
                        value = b"corrupt"
                    changed.append((name, value, kind))
                with self.assertRaises(RuntimeError):
                    self.restore(exported, archive_bytes(changed))
                self.assertFalse(list(self.target_data.iterdir()))
                self.assertFalse(list(self.target_media.iterdir()))
                self.assertEqual(hashlib.sha256(original).hexdigest(), exported["sha256"])
        self.assertEqual(self.restore(exported)["status"], "PASS")

    def test_nonempty_destination_never_overwrites_existing_data(self):
        sentinel = self.target_data / "retain-me"
        sentinel.write_text("owned earlier fixture")
        with self.assertRaisesRegex(storage.StorageError, "STORAGE_DESTINATION_NOT_EMPTY"):
            self.restore(self.export())
        self.assertEqual(sentinel.read_text(), "owned earlier fixture")
        self.assertFalse(list(self.target_media.iterdir()))

    def test_media_reference_integrity_and_migration_ledger_are_required(self):
        (self.media / "image.png").unlink()
        with self.assertRaisesRegex(RuntimeError, "FIXTURE_IMAGE_REFERENCE_MISSING"):
            self.export()
        (self.media / "image.png").write_bytes(b"image")
        self.connection.execute("DELETE FROM schema_migrations")
        self.connection.commit()
        with self.assertRaisesRegex(RuntimeError, "FIXTURE_MIGRATION_LEDGER_EMPTY"):
            self.export()

    def test_container_python_transport_executes_existing_backup_primitives(self):
        code = storage.script("backup_export", {"contract_source": CONTRACT, "database": str(self.database),
            "media": str(self.media)}, Path(storage.__file__).read_text())
        self.assertLess(len(code.encode()), 120000)
        process = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=ROOT, timeout=15)
        self.assertEqual(process.returncode, 0, process.stderr)
        exported = json.loads(process.stdout)
        self.assertEqual(exported["receipt"]["databaseBackup"], "SQLITE_BACKUP_API")
        self.assertEqual(self.restore(exported)["status"], "PASS")


class ArchiveTests(unittest.TestCase):
    def test_traversal_links_duplicates_and_oversize_rejected_before_extraction(self):
        cases = [[("../outside", b"bad", tarfile.REGTYPE)], [("/absolute", b"bad", tarfile.REGTYPE)],
                 [("backup/../outside", b"bad", tarfile.REGTYPE)], [("backup/link", b"", tarfile.SYMTYPE)],
                 [("backup/hard", b"", tarfile.LNKTYPE)], [("backup/fifo", b"", tarfile.FIFOTYPE)],
                 [("backup/same", b"a", tarfile.REGTYPE), ("backup/same", b"b", tarfile.REGTYPE)]]
        with tempfile.TemporaryDirectory() as directory:
            for index, entries in enumerate(cases):
                destination = Path(directory) / str(index)
                with self.subTest(index=index), self.assertRaises(storage.StorageError):
                    storage.extract_archive(archive_bytes(entries), destination)
                self.assertFalse(destination.exists())
            with patch.object(storage, "MAX_EXPANDED", 2), self.assertRaisesRegex(storage.StorageError, "EXPANSION_LIMIT"):
                storage.extract_archive(archive_bytes([("backup/file", b"123", tarfile.REGTYPE)]), Path(directory) / "large")
            self.assertFalse((Path(directory) / "large").exists())

    def test_transfer_checksum_rejected_without_destination_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("data", "media"):
                (root / name).mkdir()
            archive = root / "payload"
            archive.write_bytes(b"not a valid archive")
            with self.assertRaisesRegex(storage.StorageError, "STORAGE_TRANSFER_CHECKSUM"):
                storage.restore_import(CONTRACT, str(archive), str(root / "data/app.sqlite3"),
                                       str(root / "media"), "0" * 64)
            self.assertFalse(list((root / "data").iterdir()))
            self.assertFalse(list((root / "media").iterdir()))


class OwnershipTests(unittest.TestCase):
    def setUp(self):
        self.row = {"Id": CID, "State": {"Running": True}, "Config": {"User": "10001:10001", "Labels": {
            "io.izo.owner": "SHADOW-TOPOLOGY-01", "com.docker.compose.project": PROJECT,
            "com.docker.compose.service": "backend"}}, "HostConfig": {"NetworkMode": "none", "PortBindings": None,
            "CapAdd": None, "CapDrop": ["ALL"], "Privileged": False, "SecurityOpt": ["no-new-privileges:true"]}, "Mounts": [
                {"Type": "volume", "RW": True, "Destination": "/home/izo/data", "Name": PROJECT + "_sqlite-data"},
                {"Type": "volume", "RW": True, "Destination": "/home/izo/media", "Name": PROJECT + "_media-data"}]}
        module = types.ModuleType("tools.docker_shadow")
        module.OWNER = "SHADOW-TOPOLOGY-01"
        self.modules = patch.dict(sys.modules, {"tools.docker_shadow": module})
        self.modules.start()
        self.addCleanup(self.modules.stop)
        self.shadow = types.SimpleNamespace(project=PROJECT, ownership_guard=lambda: None,
                                           docker=lambda *args: json.dumps([self.row]))

    def test_helper_needs_both_owned_writable_volumes_and_network_none(self):
        self.assertEqual(storage.mount_guard(self.shadow, CID, helper=True)["Id"], CID)
        original = copy.deepcopy(self.row)
        changes = (lambda: self.row["Mounts"][0].update(Name="foreign-volume"),
                   lambda: self.row["Mounts"][0].update(Type="bind"),
                   lambda: self.row["Mounts"][0].update(RW=False),
                   lambda: self.row["Mounts"].__setitem__(1, copy.deepcopy(self.row["Mounts"][0])),
                   lambda: self.row["Config"].update(User="0:0"),
                   lambda: self.row["HostConfig"].update(NetworkMode="host"),
                   lambda: self.row["HostConfig"].update(Privileged=True),
                   lambda: self.row["HostConfig"].update(SecurityOpt=[]),
                   lambda: self.row["Config"]["Labels"].update({"io.izo.owner": "other"}))
        for index, change in enumerate(changes):
            self.row = copy.deepcopy(original)
            change()
            with self.subTest(index=index), self.assertRaises(storage.StorageError):
                storage.mount_guard(self.shadow, CID, helper=True)

    def test_owned_stopped_helper_can_be_cleaned_without_executing_it(self):
        self.row["State"]["Running"] = False
        with self.assertRaises(storage.StorageError):
            storage.mount_guard(self.shadow, CID, helper=True)
        self.assertEqual(storage.mount_guard(self.shadow, CID, helper=True, running=False)["Id"], CID)

    def test_cookie_transport_copies_in_memory_without_altering_source(self):
        from tools.docker_shadow_product import ProductFlow
        attestation = {"origin": "http://127.0.0.1:48125", "sourceSha": "a" * 40, "project": PROJECT,
            "isolatedData": True, "fakeProviderOnly": True, "networkEgressDenied": True, "externalEffectsDisabled": True}
        flow = ProductFlow(attestation)
        cookie = http.cookiejar.Cookie(0, "fixture_session", "memory-only-value", None, False,
            "127.0.0.1", False, False, "/", True, False, None, True, None, None, {})
        flow.owner.cookies.set_cookie(cookie)
        flow.saved, flow.checks = {"fixture": [1]}, {"generation": [{"jobId": "fixture-job"}]}
        restored = types.SimpleNamespace(web_port=48127, project=PROJECT + "-new", sha="a" * 40)
        clone = storage.copied_flow(flow, restored)
        clone.owner.cookies.clear()
        clone.saved["fixture"].append(2)
        self.assertEqual(len(list(flow.owner.cookies)), 1)
        self.assertEqual(flow.saved["fixture"], [1])
        self.assertEqual(clone.origin, "http://127.0.0.1:48127")


class StorageFaultTests(unittest.TestCase):
    def setUp(self):
        self.before = {"account": {"token_balance": 50, "daily_tokens_used": 0}, "ledger": {"items": []}}
        self.after = {"account": copy.deepcopy(self.before["account"]), "ledger": {"items": [
            {"id": "charge", "spentTokens": 4, "reason": "daily_generation", "jobId": "fixturejob"},
            {"id": "refund", "spentTokens": 0, "reason": "daily_generation_refund", "jobId": "fixturejob"}]}}
        self.calls, self.snapshots = [], [self.before, self.after, self.after]
        self.job_status, self.blocked, self.http_status = "error", True, None
        self.owner = types.SimpleNamespace(request=self.request)
        self.flow = types.SimpleNamespace(owner=self.owner, guest=types.SimpleNamespace(request=lambda *a, **k: {"ok": True}),
            account_snapshot=lambda client: copy.deepcopy(self.snapshots.pop(0)))

    def request(self, method, path, *args, **kwargs):
        self.calls.append((method, path))
        if method == "POST":
            return {"httpStatus": self.http_status} if self.http_status else {"id": "fixturejob", "tokenCost": 4}
        return {"status": self.job_status, "resultImageId": "bad-image" if self.job_status == "completed" else None}

    def run_fault(self):
        with patch.object(storage, "backend_id", return_value=CID), patch.object(storage.time, "sleep"), \
             patch.object(storage, "container_call", side_effect=[{"mode": 493}, {"blocked": self.blocked},
                                                                  {"permissionsRestored": True}]) as transport:
            try:
                return storage.media_fault(object(), self.flow)
            finally:
                self.assertIn("chmod(493)", transport.call_args.args[2])

    def test_error_and_one_refund_are_required_and_permissions_restored(self):
        result = self.run_fault()
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["charges"], 1)
        self.assertEqual(result["refunds"], 1)

    def test_unestablished_fault_never_submits_generation(self):
        self.blocked = False
        with self.assertRaisesRegex(storage.StorageError, "STORAGE_FAULT_NOT_ESTABLISHED"):
            self.run_fault()
        self.assertFalse(self.calls)

    def test_false_success_or_financial_duplication_is_rejected(self):
        self.job_status = "completed"
        with self.assertRaisesRegex(storage.StorageError, "STORAGE_FAILURE_FALSE_SUCCESS"):
            self.run_fault()
        self.job_status = "error"
        self.snapshots = [self.before, copy.deepcopy(self.after)]
        self.snapshots[1]["ledger"]["items"].append({"id": "extra", "spentTokens": 4, "reason": "daily_generation"})
        with self.assertRaisesRegex(storage.StorageError, "STORAGE_FAILURE_LEDGER_INVALID"):
            self.run_fault()

    def test_http_rejection_passes_only_with_unchanged_finances(self):
        self.http_status, self.snapshots = 503, [self.before, self.before]
        result = self.run_fault()
        self.assertEqual(result["requestHttpStatus"], 503)
        self.assertEqual(result["charges"], 0)


class OrchestrationTests(unittest.TestCase):
    def test_helper_transport_lifecycle_and_source_change_receipt(self):
        baseline = {"database": {"migrationLedger": {"rows": 1}, "imageReferences": 2}, "media": {"digest": "fixture"}}
        image = "sha256:" + "a" * 64
        executor = types.SimpleNamespace(verify=lambda: {"isolated": True}, foreign_snapshot=lambda project: {})
        executor_module = types.ModuleType("tools.docker_shadow_executor")
        executor_module.compare_isolated = lambda before, after: {"status": "PASS" if before == after else "FAIL"}
        smoke = types.ModuleType("tools.docker_shadow_smoke")
        smoke.inspect_stack = smoke.http_proof = smoke.kernel_policy = lambda *a: {"status": "PASS"}
        for source_changed, unavailable in ((False, False), (True, False), (False, True)):
            with self.subTest(source_changed=source_changed, unavailable=unavailable), tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
                events, running = [], {"helper": False, "application": False}
                source = types.SimpleNamespace(project=PROJECT, sha="a" * 40, root=ROOT, fixture=True,
                    web_port=48125, api_port=48126, executor=executor, source_guard=lambda: None,
                    config=lambda: {}, ownership_guard=lambda: None)
                restored = copy.copy(source)
                restored.project, restored.web_port, restored.api_port = PROJECT + "-new", 48127, 48128
                helper_row = {"Id": CID, "Name": restored.project + "-storage-helper", "Image": image,
                    "Config": {"Labels": {"com.docker.compose.service": "backend"}, "Healthcheck": {"Test": ["NONE"]}}}
                restored.containers = lambda: [helper_row] if running["helper"] else (
                    [{"Id": CID, "Name": "guard", "Config": {"Labels": {"com.docker.compose.service": "guard"}}}]
                    if running["application"] else [])
                restored.image_guard = lambda config: {"backend": image}

                def compose(*args, override=None, **kwargs):
                    events.append(args[0])
                    if args[0] == "run":
                        self.assertNotIn("-c", args)
                        settings = json.loads(override.read_text())["services"]["backend"]
                        self.assertEqual(settings["image"], image)
                        self.assertEqual(settings["network_mode"], "none")
                        self.assertEqual(settings["healthcheck"], {"disable": True})
                        self.assertFalse("volumes" in settings or "ports" in settings)
                        running["helper"] = True
                        return CID
                    self.assertEqual(args, ("down", "--volumes"))
                    running.update(helper=False, application=False)
                    return ""

                def docker(*args, **kwargs):
                    if args[0] == "rm":
                        self.assertEqual(args, ("rm", "-f", CID))
                        running["helper"] = False
                        events.append("remove-helper")
                    return ""

                def up(**kwargs):
                    self.assertFalse(running["helper"])
                    events.append("application-up")
                    running["application"] = True

                def call(shadow, identifier, code, **kwargs):
                    if "getattr(m,'backup_export')" in code:
                        return {"archive": base64.b64encode(b"archive-fixture").decode(),
                            "sha256": hashlib.sha256(b"archive-fixture").hexdigest(), "receipt": {"sourceState": baseline}}
                    if "getattr(m,'restore_import')" in code:
                        return {"restoredState": baseline, "negativeCases": {"database": "rejected",
                            "media": "rejected", "incomplete": "rejected"}}
                    if "getattr(m,'storage_probe')" in code:
                        return {"changed": True} if shadow is source and source_changed else baseline
                    return {"written": True}

                def fault(*args):
                    if unavailable:
                        raise storage.StorageError("STORAGE_FAULT_NOT_ESTABLISHED")
                    return {"status": "PASS"}

                restored.compose, restored.docker, restored.up = compose, docker, up
                clone = types.SimpleNamespace(verify_persistence=lambda: {"status": "PASS"},
                                             close=lambda: {"sessionCleanup": "PASS"})
                stack.enter_context(patch.dict(sys.modules, {"tools.docker_shadow_executor": executor_module,
                                                             "tools.docker_shadow_smoke": smoke}))
                for name, value in (("backend_id", lambda shadow: CID), ("mount_guard", lambda *a, **k: helper_row),
                                    ("container_call", call), ("copied_flow", lambda *a: clone),
                                    ("media_fault", fault)):
                    stack.enter_context(patch.object(storage, name, value))
                evidence = Path(directory) / "new-evidence"
                result = storage.rehearse_storage(source, restored, types.SimpleNamespace(saved={"present": True}), evidence)
                self.assertEqual(result["status"], "FAIL" if source_changed or unavailable else "PASS")
                self.assertEqual(result["checks"]["D2-06"]["status"], "NOT_RUN" if unavailable else "PASS")
                self.assertLess(events.index("remove-helper"), events.index("application-up"))
                self.assertEqual(events[-1], "down")
                self.assertFalse(any(running.values()))
                if source_changed:
                    self.assertEqual(result["cleanup"]["errorCode"], "STORAGE_SOURCE_CHANGED_DURING_D2")
                else:
                    self.assertEqual(result["sourceUnchanged"], "PASS")
                receipt = (evidence / "storage.json").read_text()
                self.assertNotIn(base64.b64encode(b"archive-fixture").decode(), receipt)
                self.assertNotIn('"archive":', receipt)


if __name__ == "__main__":
    unittest.main()
