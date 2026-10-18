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
from unittest.mock import Mock, patch

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
        process = subprocess.run([sys.executable, "-"], input=code, capture_output=True,
            text=True, encoding="utf-8", cwd=ROOT, timeout=15)
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

    def test_fixture_requires_exact_owned_worker_ipc_without_widening_default_mounts(self):
        self.shadow.fixture = True
        with self.assertRaisesRegex(storage.StorageError, "STORAGE_VOLUME_NOT_OWNED"):
            storage.mount_guard(self.shadow, CID)
        self.assertEqual(storage.mount_guard(self.shadow, CID, helper=True)["Id"], CID)
        self.row["Mounts"].append({"Type": "volume", "RW": True,
            "Destination": "/home/izo/worker", "Name": PROJECT + "_worker_ipc"})
        self.assertEqual(storage.mount_guard(self.shadow, CID)["Id"], CID)
        with self.assertRaisesRegex(storage.StorageError, "STORAGE_VOLUME_NOT_OWNED"):
            storage.mount_guard(self.shadow, CID, helper=True)
        original = copy.deepcopy(self.row)
        for field, value in (("Type", "bind"), ("RW", False), ("Name", "foreign_worker_ipc"),
                             ("Destination", "/home/izo/foreign")):
            with self.subTest(field=field):
                self.row = copy.deepcopy(original)
                self.row["Mounts"][2][field] = value
                with self.assertRaisesRegex(storage.StorageError, "STORAGE_VOLUME_NOT_OWNED"):
                    storage.mount_guard(self.shadow, CID)
        self.row, self.shadow.fixture = original, False
        with self.assertRaisesRegex(storage.StorageError, "STORAGE_VOLUME_NOT_OWNED"):
            storage.mount_guard(self.shadow, CID)

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


class OrchestrationTests(unittest.TestCase):
    def test_helper_transport_lifecycle_and_source_change_receipt(self):
        baseline = {"database": {"migrationLedger": {"rows": 1}, "imageReferences": 2,
            "tables": {"power_samples": {"rows": 1, "digest": "a" * 64, "schemaDigest": "c" * 64}}},
            "media": {"digest": "fixture"}}
        changed = copy.deepcopy(baseline)
        changed["database"]["tables"]["power_samples"].update(rows=2, digest="b" * 64)
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
                        raw_override = override.read_text()
                        self.assertEqual(raw_override.count('"volumes": !override ['), 1)
                        settings = json.loads(raw_override.replace('"volumes": !override [', '"volumes": [', 1))["services"]["backend"]
                        self.assertEqual(settings["image"], image)
                        self.assertEqual(settings["network_mode"], "none")
                        self.assertEqual(settings["healthcheck"], {"disable": True})
                        self.assertNotIn("ports", settings)
                        self.assertEqual(settings["volumes"], [
                            {"type": "volume", "source": "sqlite-data", "target": "/home/izo/data"},
                            {"type": "volume", "source": "media-data", "target": "/home/izo/media"}])
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
                        return changed if shadow is source and source_changed else baseline
                    return {"written": True}

                def fault(*args, **kwargs):
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
                reader = types.SimpleNamespace(open=lambda: None,
                    call=lambda code: call(source, CID, code), close=Mock(return_value={"status": "PASS"}))
                stack.enter_context(patch("tools.docker_clean_storage_quiesce.QuiescedSource", return_value=reader))
                evidence = Path(directory) / "new-evidence"
                result = storage.rehearse_storage(source, restored, types.SimpleNamespace(saved={"present": True}), evidence)
                reader.close.assert_called_once()
                self.assertEqual(result["status"], "FAIL" if source_changed or unavailable else "PASS")
                self.assertEqual(result["checks"]["D2-06"]["status"], "NOT_RUN" if unavailable else "PASS")
                self.assertEqual(result["applicationVolumes"], {"/home/izo/data": restored.project + "_sqlite-data",
                    "/home/izo/media": restored.project + "_media-data", "/home/izo/worker": restored.project + "_worker_ipc"})
                self.assertLess(events.index("remove-helper"), events.index("application-up"))
                self.assertEqual(events[-1], "down")
                self.assertFalse(any(running.values()))
                if source_changed:
                    self.assertEqual(result["cleanup"]["errorCode"], "STORAGE_SOURCE_CHANGED_DURING_D2")
                else:
                    self.assertEqual(result["sourceUnchanged"], "PASS")
                receipt = (evidence / "storage.json").read_text()
                published = json.loads(receipt)
                self.assertEqual(published["sourceAfterD2"], changed if source_changed else baseline)
                self.assertEqual(published["backup"]["receipt"]["sourceState"], baseline)
                if source_changed:
                    self.assertEqual(published["status"], "FAIL")
                    self.assertNotIn("sourceUnchanged", published)
                self.assertNotIn(base64.b64encode(b"archive-fixture").decode(), receipt)
                self.assertNotIn('"archive":', receipt)


if __name__ == "__main__":
    unittest.main()
