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


class PlanAndPrivateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def plan(self):
        plan = {"version": 1, "scope": {"os": platform.system().lower(), "host": platform.node(), "context": "default",
                "engineFingerprint": "e" * 64, "project": "izo-asa-bundle-runtime-test", "root": str(self.root),
                "ports": {"web": 48754, "api": 48755}}, "toolingSha": "f" * 40, "bundles": {},
                "support": {"toolingRoot": str(self.root / "tooling"), "httpClientPath": str(self.root / "http.py"),
                            "moduleHashes": {x: "a" * 64 for x in ("docker_test_bundle_format", "docker_test_bundle_runtime")},
                            "httpClientSha256": "b" * 64},
                "controllerHashes": {name: checks.digest(Path(__file__).parent / name, canonical=True)
                                     for name in ("synthetic_runtime_accept.py", "synthetic_runtime_checks.py")},
                "observationSeconds": 360, "retainSyntheticCredentials": True}
        for label in ("A", "B"):
            archive = self.root / ("release-" + label + ".zip"); archive.write_bytes(label.encode())
            item = {"archiveSha256": checks.digest(archive), "manifestSha256": label.lower() * 64}
            receipt = {"status": "TEST_BUNDLE_BUILT", "source_sha": accept.SOURCES[label], "tooling_sha": plan["toolingSha"],
                       "project": plan["scope"]["project"], "images_embedded": True, "production_authorized": False,
                       "manifest_sha256": item["manifestSha256"], "archive_sha256": item["archiveSha256"], "archive_bytes": 1}
            path = archive.with_suffix(".receipt.json"); write_json(path, receipt)
            item["receiptSha256"] = checks.digest(path); plan["bundles"][label] = item
        return plan

    def load(self, plan):
        path = self.root / "plan.json"; write_json(path, plan)
        return accept.load_plan(path, checks.digest(path))

    def test_plan_pins_pass_and_archive_tamper_refuses(self):
        plan = self.plan(); self.assertEqual(self.load(plan), plan)
        (self.root / "release-A.zip").write_bytes(b"changed")
        with self.assertRaises(checks.CheckFailure): self.load(plan)

    def test_plan_wrong_host_script_pin_duration_or_missing_bundle_refuses(self):
        for mutation in (lambda p: p["scope"].update(host="different-host"),
                         lambda p: p["controllerHashes"].update(synthetic_runtime_checks_py="a" * 64),
                         lambda p: p.update(observationSeconds=300), lambda p: p["bundles"].pop("B")):
            plan = self.plan(); mutation(plan)
            with self.subTest(plan=plan["observationSeconds"]), self.assertRaises(checks.CheckFailure): self.load(plan)

    def test_dotdot_and_symlink_path_refused(self):
        with self.assertRaisesRegex(checks.CheckFailure, "UNSAFE_PATH"): checks.plain(self.root / "missing/../private")
        if os.name != "nt":
            (self.root / "link").symlink_to(self.root, target_is_directory=True)
            with self.assertRaisesRegex(checks.CheckFailure, "LINKED_PATH"): checks.plain(self.root / "link/file")

    def accounts(self):
        return [{"role": role, "legacyUserId": role + "-legacy", "internalUserId": role + "-internal",
                 "email": role + "@example.invalid", "password": "private-" + role + "-synthetic"} for role in ("owner", "other")]

    @unittest.skipIf(os.name == "nt", "POSIX mode semantics; Windows ACL tested independently")
    def test_private_artifact_restricts_then_readonly_load_and_refuses_mode_drift(self):
        accounts = self.accounts(); receipt = checks.private_credentials(self.root, "test-project", accounts, {})
        folder = self.root / "private"; path = folder / "credentials.json"
        self.assertEqual(stat.S_IMODE(folder.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        original = path.read_bytes()
        self.assertEqual(checks.load_private_credentials(self.root, "test-project", receipt["sha256"], {}), accounts)
        self.assertEqual(path.read_bytes(), original)
        self.assertFalse(receipt["cookiesStored"])
        self.assertFalse(any(a["password"] in json.dumps(receipt) for a in accounts))
        path.chmod(0o644)
        with self.assertRaisesRegex(checks.CheckFailure, "PRIVATE_MODE_NOT_VERIFIED"):
            checks.load_private_credentials(self.root, "test-project", receipt["sha256"], {})

    def test_existing_private_directory_untouched_and_cookies_refused(self):
        folder = self.root / "private"; folder.mkdir(); (folder / "marker").write_text("keep")
        with self.assertRaisesRegex(checks.CheckFailure, "PRIVATE_DIRECTORY_EXISTS"):
            checks.private_credentials(self.root, "test", self.accounts(), {})
        self.assertEqual((folder / "marker").read_text(), "keep")
        accounts = self.accounts(); accounts[0]["cookies"] = "do-not-write"
        with self.assertRaisesRegex(checks.CheckFailure, "SYNTHETIC_CREDENTIAL_SHAPE_INVALID"): checks.credential_shape(accounts)

    def test_windows_acl_failure_precedes_credentials_and_verify_never_sets_acl(self):
        fake_os = types.SimpleNamespace(name="nt", environ={"SystemRoot": "C:/Windows"})
        with patch.object(checks, "os", fake_os), patch.object(checks.subprocess, "run") as command:
            command.return_value = types.SimpleNamespace(returncode=1, stdout=b"failure")
            with self.assertRaisesRegex(checks.CheckFailure, "PRIVATE_ACL_NOT_VERIFIED"):
                checks.private_credentials(self.root, "test", self.accounts(), {})
            self.assertFalse((self.root / "private/credentials.json").exists())
            self.assertEqual(command.call_args.kwargs["env"]["IZO_QA_SET_PRIVATE_ACL"], "1")
            command.return_value = types.SimpleNamespace(returncode=0, stdout=b"PRIVATE_DIRECTORY_ACL_VERIFIED\r\n")
            checks.credential_permissions(self.root / "private", {})
            self.assertEqual(command.call_args.kwargs["env"]["IZO_QA_SET_PRIVATE_ACL"], "0")


class ResourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.manifest = {"images": {role: "sha256:" + role for role in ("backend", "web", "guard")},
                         "ports": {"api": 48755, "web": 48754}}
        self.rows = []
        for role, image in self.manifest["images"].items():
            self.rows.append({"Id": role + "-id", "Image": image, "State": {"Running": True, "StartedAt": "original", "OOMKilled": False},
                "RestartCount": 0, "Config": {"Labels": {"com.docker.compose.service": role}, "Cmd": ["uvicorn"], "Env": ["MODE=test"]},
                "HostConfig": {"RestartPolicy": {"Name": "no"}, "NetworkMode": "container:guard-id", "PortBindings": {} }})
        self.rows[-1]["HostConfig"]["PortBindings"] = {"8000/tcp": [{"HostIp": "127.0.0.1", "HostPort": "48755"}],
                                                        "8080/tcp": [{"HostIp": "127.0.0.1", "HostPort": "48754"}]}
        self.resources = {"containers": self.rows, "volumes": [volume("data"), volume("media")],
                          "networks": [{"Containers": {"guard-id": {}}}]}
        write_json(self.root / "compose.json", {"services": {r: {"environment": {"MODE": "test"}} for r in self.manifest["images"]}})
        self.runtime = types.SimpleNamespace(UVICORN=["uvicorn"], health=Mock(), owned_resources=Mock(return_value=self.resources))
        self.docker = Mock(); self.netns = {r["Id"]: "net:[100]" for r in self.rows}
        self.docker.run.side_effect = lambda *args, **kwargs: json.dumps({"Env": []}) if args[0] == "image" else self.netns[args[1]]

    def test_current_guard_namespace_and_exact_environment_pass(self):
        result = checks.topology(self.runtime, self.docker, self.root, self.manifest)
        self.assertEqual(set(result["netns"].values()), {"net:[100]"})
        self.assertEqual(len(result["containers"]), 3)

    def test_actual_stale_namespace_refused_despite_correct_networkmode(self):
        self.netns["backend-id"] = "net:[99]"
        with self.assertRaisesRegex(checks.CheckFailure, "NETWORK_NAMESPACE_MISMATCH"):
            checks.topology(self.runtime, self.docker, self.root, self.manifest)

    def test_stale_guard_reference_environment_and_restart_refused(self):
        changes = (("HostConfig", "NetworkMode", "container:old-guard"),
                   ("Config", "Env", ["MODE=test", "EXTERNAL_KEY=unexpected"]))
        for section, key, value in changes:
            original = deepcopy(self.rows[0]); self.rows[0][section][key] = value
            with self.subTest(section=section), self.assertRaises(checks.CheckFailure):
                checks.topology(self.runtime, self.docker, self.root, self.manifest)
            self.rows[0].clear(); self.rows[0].update(original)
        self.rows[0]["RestartCount"] = 1
        with self.assertRaisesRegex(checks.CheckFailure, "RUNTIME_PROCESS_IDENTITY_CHANGED"):
            checks.topology(self.runtime, self.docker, self.root, self.manifest)

    def test_foreign_deletion_drift_and_unexpected_new_resources_refuse(self):
        before = {"containers": {"foreign": {"started": "old"}}, "volumes": {}, "networks": {}}
        own = {"containers": {"own"}, "volumes": set(), "networks": set()}
        good = deepcopy(before); good["containers"]["own"] = {}
        checks.foreign_unchanged(good, before, own)
        for current in ({**good, "containers": {}}, {**good, "containers": {"foreign": {"started": "new"}}},
                        {**good, "volumes": {"unknown": {}}}):
            with self.assertRaises(checks.CheckFailure): checks.foreign_unchanged(current, before, own)


class DatabaseProofTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name).resolve() / "app.sqlite3"
        with closing(sqlite3.connect(self.path)) as db:
            db.executescript("PRAGMA user_version=7; CREATE TABLE images(id TEXT); CREATE TABLE jobs(id TEXT,status TEXT);"
                "CREATE TABLE token_ledger(user_id TEXT,reason TEXT,delta INTEGER,meta_json TEXT);"
                "CREATE TABLE video_file_deletions(id TEXT); CREATE TABLE feed_publications(media_type TEXT,status TEXT);")
            db.execute("INSERT INTO images VALUES ('image')"); db.execute("INSERT INTO jobs VALUES ('full-job-id','completed')")
            db.execute("INSERT INTO token_ledger VALUES (?,?,?,?)", ("user", "daily_generation", 0,
                json.dumps({"jobId": "full-job-id", "token_cost": 1, "daily_part": 1, "balance_part": 0, "balance_delta": 0})))
            db.commit()
        self.expected = [{"id": "full-job-id", "cost": 1, "user": "user", "image": "image"}]

    def probe(self):
        connect = sqlite3.connect; calls = []; opened = []
        def readonly(database_uri, **kwargs):
            calls.append((database_uri, kwargs))
            self.assertEqual(database_uri, "file:/home/izo/data/app.sqlite3?mode=ro")
            self.assertTrue(kwargs["uri"])
            connection = connect(self.path.as_uri() + "?mode=ro", uri=True); opened.append(connection)
            return connection
        before = checks.digest(self.path); output = io.StringIO()
        try:
            with patch.object(sqlite3, "connect", readonly), patch.object(sys, "argv", ["probe", json.dumps(self.expected)]), redirect_stdout(output):
                exec(compile(checks.DB_PROBE, "pinned_db_probe", "exec"), {})
        finally:
            for connection in opened: connection.close()
            self.assertEqual(checks.digest(self.path), before)
        self.assertEqual(checks.digest(self.path), before); self.assertEqual(len(calls), 1)
        return json.loads(output.getvalue())

    def test_zero_main_balance_delta_still_proves_daily_charge_and_unchanged_source(self):
        result = self.probe()
        self.assertEqual(result["charges"]["full-job-id"], {"rows": 1, "cost": 1, "daily": 1, "main": 0, "delta": 0})
        self.assertEqual(result["protectedTables"]["jobs"]["count"], 1)

    def test_duplicate_charge_refund_or_wrong_full_job_id_refuse(self):
        original = self.path.read_bytes()
        for sql in ("INSERT INTO token_ledger SELECT * FROM token_ledger", "UPDATE token_ledger SET reason='daily_generation_refund'",
                    "UPDATE token_ledger SET meta_json=replace(meta_json,'full-job-id','short-job')",
                    "UPDATE token_ledger SET user_id='another-user'"):
            self.path.write_bytes(original)
            with closing(sqlite3.connect(self.path)) as db: db.execute(sql); db.commit()
            with self.subTest(sql=sql), self.assertRaises(AssertionError): self.probe()

    def test_null_nonterminal_job_and_video_queues_refuse(self):
        original = self.path.read_bytes()
        for sql in ("UPDATE jobs SET status=NULL", "UPDATE jobs SET status='unknown'",
                    "INSERT INTO video_file_deletions VALUES ('x')", "INSERT INTO feed_publications VALUES ('video','preparing')"):
            self.path.write_bytes(original)
            with closing(sqlite3.connect(self.path)) as db: db.execute(sql); db.commit()
            with self.subTest(sql=sql), self.assertRaises(AssertionError): self.probe()


if __name__ == "__main__":
    unittest.main()
