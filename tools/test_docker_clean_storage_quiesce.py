"""RO SQLite/WAL and compensation tests; these do not attest Docker execution."""
from __future__ import annotations

import copy
import builtins
import base64
import http.client
import hashlib
import io
import json
import sqlite3
import sys
import tempfile
import types
import unittest
from contextlib import closing, redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

from backend.app.storage.backup import create_backup, verify_snapshot
from tools import docker_clean_storage_quiesce as quiesce

from tools.test_helpers.docker_storage_quiesce_fixture import CANARY, CID, HID, IMAGE, PROJECT, Source


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.source = Source()
        self.reader = quiesce.QuiescedSource(self.source)
        self.addCleanup(self.reader.close)

    def test_exact_source_is_paused_for_both_snapshots_and_then_resumed(self):
        self.reader.open()
        before = self.reader.call("first-snapshot")
        after = self.reader.call("last-snapshot")
        self.assertEqual(after, before)
        self.assertTrue(self.source.rows[CID]["State"]["Paused"])
        self.assertEqual(len(self.source.rows), 2)
        receipt = self.reader.close()
        self.assertEqual(receipt["status"], "PASS")
        self.assertEqual(receipt["sourceResumed"], "PASS")
        self.assertEqual(receipt["sourceContainerId"], CID)
        self.assertEqual(receipt["sourceMounts"], "READ_ONLY")
        self.assertEqual(receipt["mode"], "QUIESCED_APPLICATION")
        self.assertFalse(receipt["zeroDowntime"])
        self.assertGreaterEqual(receipt["quiescedWindowSeconds"], 0)
        self.assertEqual(set(receipt["volumeIdentities"]), set(self.source.volumes))
        self.assertEqual(self.source.events, ["pause", "run", "reader-exec", "reader-exec", "reader-exec",
                                               "remove-reader", "unpause"])
        self.assertEqual(set(self.source.rows), {CID})
        self.assertFalse(self.source.rows[CID]["State"]["Paused"])
        self.assertFalse(self.reader.override.exists())
        self.assertNotIn(CANARY, json.dumps(receipt))
        previous = list(self.source.events)
        self.assertEqual(self.reader.close(), receipt)
        self.assertEqual(self.source.events, previous)

    def test_lost_pause_or_create_response_still_resumes_original_container(self):
        for failure in ("pause_after", "run_after"):
            with self.subTest(failure=failure):
                source = Source()
                source.failure = failure
                reader = quiesce.QuiescedSource(source)
                try:
                    with self.assertRaisesRegex(quiesce.StorageError, "^STORAGE_QUIESCE_OPEN_FAILED$"):
                        reader.open()
                finally:
                    result = reader.close()
                self.assertEqual(result["status"], "FAIL")
                self.assertEqual(result["sourceResumed"], "PASS")
                self.assertFalse(source.rows[CID]["State"]["Paused"])
                self.assertNotIn(HID, source.rows)
                self.assertNotIn(CANARY, json.dumps(result))

    def test_reader_delete_failure_does_not_skip_original_container_unpause(self):
        self.reader.open()
        self.source.failure = "rm"
        result = self.reader.close()
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["sourceResumed"], "PASS")
        self.assertEqual(result["errorCodes"], ["STORAGE_QUIESCE_READER_CLEANUP_FAILED"])
        self.assertEqual(self.source.events[-2:], ["remove-reader", "unpause"])
        self.assertFalse(self.source.rows[CID]["State"]["Paused"])

    def test_unpause_failure_keeps_fail_after_successful_reader_delete(self):
        self.reader.open()
        self.source.failure = "unpause"
        result = self.reader.close()
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["helperRemoved"], "PASS")
        self.assertNotEqual(result["sourceResumed"], "PASS")
        self.assertEqual(result["errorCodes"], ["STORAGE_QUIESCE_SOURCE_RESUME_FAILED"])

    def test_helper_override_damage_cannot_prevent_original_resume(self):
        self.reader.open()
        self.reader.override.unlink()
        with self.assertRaisesRegex(quiesce.StorageError, "^STORAGE_QUIESCE_READ_FAILED$"):
            self.reader.call("never-executed")
        result = self.reader.close()
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["sourceResumed"], "PASS")
        self.assertEqual(result["helperRemoved"], "PASS")
        self.assertFalse(self.source.rows[CID]["State"]["Paused"])

    def test_rejected_reader_after_lost_create_response_does_not_block_resume(self):
        for key in (quiesce.READER_LABEL, "io.izo.owner"):
            with self.subTest(label=key):
                source = Source()
                source.failure = "run_after"
                source.bad_reader = lambda row: row["Config"]["Labels"].update({key: "unrecognized"})
                reader = quiesce.QuiescedSource(source)
                try:
                    with self.assertRaises(quiesce.StorageError):
                        reader.open()
                finally:
                    result = reader.close()
                self.assertEqual(result["status"], "FAIL")
                self.assertEqual(result["sourceResumed"], "PASS")
                self.assertIn(HID, source.rows)
                self.assertNotIn("remove-reader", source.events)

    def test_changed_base_config_and_second_normal_backend_still_block_resume(self):
        for change in ("base", "backend"):
            with self.subTest(change=change):
                source = Source()
                reader = quiesce.QuiescedSource(source)
                reader.open()
                if change == "base":
                    previous = source.config
                    source.config = lambda: {**previous(), "changedBase": True}
                else:
                    other = copy.deepcopy(source.rows[CID])
                    other.update(Id="f" * 64, Name="/unexpected-backend")
                    source.rows[other["Id"]] = other
                result = reader.close()
                self.assertEqual(result["status"], "FAIL")
                self.assertNotEqual(result["sourceResumed"], "PASS")
                self.assertNotIn("unpause", source.events)

    def test_preexisting_paused_source_or_reader_name_is_never_mutated(self):
        for collision in (False, True):
            with self.subTest(collision=collision):
                source = Source()
                if collision:
                    source.rows[HID] = copy.deepcopy(source.rows[CID])
                    source.rows[HID].update(Id=HID, Name="/" + PROJECT + "-storage-source-reader")
                    source.rows[HID]["Config"]["Labels"]["com.docker.compose.service"] = "web"
                else:
                    source.rows[CID]["State"]["Paused"] = True
                reader = quiesce.QuiescedSource(source)
                try:
                    with self.assertRaises(quiesce.StorageError):
                        reader.open()
                finally:
                    reader.close()
                self.assertFalse(source.events)

    def test_engine_volume_and_container_replacement_prevent_reads_and_mutations(self):
        mutations = (
            lambda source: source.identity.update(engineId="substituted-engine"),
            lambda source: source.volumes[next(iter(source.volumes))].update(CreatedAt="replaced"),
            lambda source: source.rows[CID].update(Image="sha256:" + "f" * 64),
        )
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                source = Source()
                reader = quiesce.QuiescedSource(source)
                reader.open()
                mutate(source)
                before = list(source.events)
                with self.assertRaisesRegex(quiesce.StorageError, "^STORAGE_QUIESCE_READ_FAILED$"):
                    reader.call("must-not-run")
                result = reader.close()
                self.assertEqual(result["status"], "FAIL")
                self.assertNotIn("unpause", source.events[len(before):])

    def test_ro_mount_and_egress_guards_prevent_exec(self):
        for mutate in (lambda row: row["Mounts"][0].update(RW=True),
                       lambda row: row["HostConfig"].update(NetworkMode="bridge"),
                       lambda row: row["Config"].update(User="0:0")):
            with self.subTest(mutation=mutate):
                source = Source()
                source.bad_reader = mutate
                reader = quiesce.QuiescedSource(source)
                try:
                    with self.assertRaises(quiesce.StorageError):
                        reader.open()
                finally:
                    result = reader.close()
                self.assertEqual(result["status"], "FAIL")
                self.assertNotIn("reader-exec", source.events)
                self.assertEqual(result["sourceResumed"], "PASS")

    def test_config_delta_and_probe_data_do_not_publish_credential_contents(self):
        self.source.bad_config = lambda config: config["services"]["backend"].update(environment={"secret": CANARY})
        with self.assertRaises(quiesce.StorageError) as failed:
            self.reader.open()
        self.assertFalse(self.source.events)
        self.assertNotIn(CANARY, str(failed.exception))
        self.assertNotIn(CANARY, json.dumps(self.reader.close()))
        source = Source()
        source.probe["secret"] = CANARY
        reader = quiesce.QuiescedSource(source)
        try:
            with self.assertRaises(quiesce.StorageError):
                reader.open()
        finally:
            result = reader.close()
        self.assertNotIn(CANARY, json.dumps(result))
        self.assertNotIn("sqliteReadOnly", result)

    def test_read_failure_is_sanitized_and_source_resumes_in_finally(self):
        self.reader.open()
        self.source.failure = "exec"
        try:
            with self.assertRaisesRegex(quiesce.StorageError, "^STORAGE_QUIESCE_READ_FAILED$"):
                self.reader.call("private archive is never an error body")
        finally:
            result = self.reader.close()
        self.assertEqual(result["sourceResumed"], "PASS")
        self.assertNotIn(CANARY, json.dumps(result))


class IntegrationCleanupTests(unittest.TestCase):
    def test_logout_exception_or_invalid_result_still_cleans_both_projects_and_writes_receipt(self):
        from tools import docker_clean_storage as storage
        state = {"database": {"migrationLedger": [], "imageReferences": 0}, "media": {}}
        for logout in (Mock(side_effect=http.client.IncompleteRead(CANARY.encode())), Mock(return_value=None)):
            with self.subTest(logout=logout), tempfile.TemporaryDirectory() as directory:
                source, events = Source(), []
                source.root = Path(storage.__file__).resolve().parents[1]
                source.web_port, source.api_port = 48125, 48126
                source.executor.foreign_snapshot = lambda project: {}
                restored = copy.copy(source)
                restored.project, restored.web_port, restored.api_port = PROJECT + "-new", 48127, 48128
                restored.containers, restored.docker = Mock(return_value=[]), Mock(return_value="")
                clone = types.SimpleNamespace(verify_persistence=lambda: {}, close=logout)

                def compose(*args, **kwargs):
                    events.append(args[0])
                    if args[0] == "down":
                        restored.containers.return_value = []
                    return HID if args[0] == "run" else ""

                def up(**kwargs):
                    restored.containers.return_value = [{"Id": HID, "Name": "guard", "Config": {
                        "Labels": {"com.docker.compose.service": "guard"}}}]

                def call(*args, **kwargs):
                    if "getattr(m,'backup_export')" in args[-1]:
                        return {"archive": base64.b64encode(b"fixture").decode(),
                            "sha256": hashlib.sha256(b"fixture").hexdigest(), "receipt": {"sourceState": state}}
                    if "getattr(m,'restore_import')" in args[-1]:
                        return {"restoredState": state, "negativeCases": {}}
                    return state

                def resume():
                    events.append("source-resumed")
                    return {"status": "PASS"}

                restored.compose, restored.up = compose, up
                reader = types.SimpleNamespace(open=Mock(), call=call, close=resume)
                executor = types.SimpleNamespace(compare_isolated=lambda *args: {"status": "PASS"})
                smoke = types.SimpleNamespace(**{key: lambda *args: {} for key in
                    ("inspect_stack", "http_proof", "kernel_policy")})
                with patch.dict(sys.modules, {"tools.docker_shadow_executor": executor, "tools.docker_shadow_smoke": smoke}), \
                     patch.object(quiesce, "QuiescedSource", return_value=reader), \
                     patch.multiple(storage, backend_id=lambda *args: HID, container_call=call,
                         mount_guard=lambda *args, **kwargs: {"Image": IMAGE, "Config": {"Healthcheck": {"Test": ["NONE"]}}},
                         copied_flow=lambda *args: clone, media_fault=lambda *args: {"status": "PASS"}):
                    folder = Path(directory) / "evidence"
                    storage.rehearse_storage(source, restored, types.SimpleNamespace(saved={"present": True}), folder)
                text = (folder / "storage.json").read_text()
                result = json.loads(text)
                self.assertEqual(result["status"], "FAIL")
                self.assertEqual(result["sessionCleanup"]["errorCode"], "STORAGE_SESSION_CLEANUP_FAILED")
                self.assertEqual(result["cleanup"]["status"], "PASS")
                self.assertEqual(result["sourceQuiescence"]["status"], "PASS")
                self.assertEqual(result["sourceAfterD2"], state)
                self.assertEqual(events[-2:], ["down", "source-resumed"])
                self.assertNotIn(CANARY, text)
                self.assertNotIn('"archive":', text)


class ReadOnlyWalTests(unittest.TestCase):
    def test_injected_storage_script_does_not_import_host_only_reader(self):
        from tools import docker_clean_storage as storage
        contract = "def database_state(*args): return {'tables': {}}\ndef media_state(*args): return {'files': 1}\n"
        script = storage.script("storage_probe", {"contract_source": contract},
                                Path(storage.__file__).read_text())
        original_import, output = builtins.__import__, io.StringIO()

        def image_import(name, *args, **kwargs):
            if name == "tools.docker_clean_storage_quiesce":
                raise ModuleNotFoundError("host module unavailable inside fixture image")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", image_import), redirect_stdout(output):
            exec(script, {})
        self.assertEqual(json.loads(output.getvalue()), {"database": {"tables": {}}, "media": {"files": 1}})

    def test_committed_wal_only_row_survives_real_backup_without_source_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database, media = root / "source.sqlite3", root / "media"
            media.mkdir()
            (media / "owned-image.png").write_bytes(b"bounded fixture media")
            with closing(sqlite3.connect(database)) as writer:
                writer.execute("PRAGMA journal_mode=WAL")
                writer.execute("PRAGMA wal_autocheckpoint=0")
                writer.execute("CREATE TABLE ledger(id INTEGER PRIMARY KEY, amount INTEGER)")
                writer.execute("INSERT INTO ledger VALUES(1,50)")
                writer.commit()
                writer.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                base = database.read_bytes()
                writer.execute("INSERT INTO ledger VALUES(2,-7)")
                writer.commit()
                self.assertEqual(database.read_bytes(), base)
                wal = Path(str(database) + "-wal")
                self.assertGreater(wal.stat().st_size, 0)
                before = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in (database, wal)}
                output = io.StringIO()
                with redirect_stdout(output):
                    exec(quiesce.READ_ONLY_PROBE.replace("'/home/izo/data/app.sqlite3'", repr(str(database))), {})
                observed = json.loads(output.getvalue())
                self.assertEqual(observed["journalMode"], "wal")
                self.assertTrue(observed["walPresent"] and observed["shmPresent"])
                with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as reader:
                    self.assertEqual(reader.execute("SELECT * FROM ledger ORDER BY id").fetchall(), [(1, 50), (2, -7)])
                    with self.assertRaises(sqlite3.OperationalError):
                        reader.execute("INSERT INTO ledger VALUES(3,-99)")
                backup = create_backup(database, media, root / "owned-backups", require_separate_volume=False)
                verified = verify_snapshot(root / "owned-backups", backup.snapshot_id)
                self.assertEqual(verified.media_files, 1)
                with closing(sqlite3.connect(backup.snapshot_dir / "database.sqlite3")) as restored:
                    self.assertEqual(restored.execute("SELECT * FROM ledger ORDER BY id").fetchall(), [(1, 50), (2, -7)])
                    self.assertEqual(restored.execute("PRAGMA integrity_check").fetchall(), [("ok",)])
                self.assertEqual(before, {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in (database, wal)})
                self.assertEqual(writer.execute("SELECT * FROM ledger ORDER BY id").fetchall(), [(1, 50), (2, -7)])
                self.assertEqual((media / "owned-image.png").read_bytes(), b"bounded fixture media")

    def test_held_write_transaction_is_read_at_last_commit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database, media = root / "source.sqlite3", root / "media"
            media.mkdir()
            (media / "fixture.png").write_bytes(b"image")
            with closing(sqlite3.connect(database)) as writer:
                writer.execute("PRAGMA journal_mode=WAL")
                writer.execute("CREATE TABLE ledger(id INTEGER PRIMARY KEY, amount INTEGER)")
                writer.execute("INSERT INTO ledger VALUES(1,50)")
                writer.commit()
                writer.execute("BEGIN IMMEDIATE")
                writer.execute("INSERT INTO ledger VALUES(2,-7)")
                backup = create_backup(database, media, root / "backups", require_separate_volume=False)
                with closing(sqlite3.connect(backup.snapshot_dir / "database.sqlite3")) as restored:
                    self.assertEqual(restored.execute("SELECT * FROM ledger").fetchall(), [(1, 50)])
                self.assertTrue(writer.in_transaction)
                writer.rollback()
                self.assertEqual(writer.execute("SELECT * FROM ledger").fetchall(), [(1, 50)])


if __name__ == "__main__":
    unittest.main()
