from copy import deepcopy
import hashlib
import io
import json
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from tools import docker_d3_phone_watch as subject
from tools import docker_d3_chat_video as runner
from tools.docker_shadow_executor import IsolatedExecutor
from tools.docker_shadow_product import ProductError

SHA, PROJECT, RUN = "a" * 40, "izo-asa-shadow-d3-17-1-generation", "b" * 32
OWNER = ["web_" + "c" * 32, "d" * 32]
HASHES = [hashlib.sha256(value.encode()).hexdigest() for value in OWNER]
JOB, PROMPT, INSTANCE = "job_owned_full_1234567890", "11111111-2222-3333-4444-555555555555", "e" * 32
CLIENT = hashlib.sha256(("onenode-backend-" + JOB).encode()).hexdigest()
CID, IMAGE, PRIVATE = "1" * 64, "sha256:" + "2" * 64, "private-cookie-at-/srv/fixture"
IDENTITY = {"containerId": CID, "imageId": IMAGE, "hostPid": 501, "startedAt": "2026-10-18T00:00:00Z", "restartCount": 0}
EXPECTED = {"user": "10001:10001", "command": ["python", "/opt/izo/fixtures/docker_shadow_fixture.py"],
            "environment": {"IZO_SHADOW_FIXTURE": "controlled-chat-video-v1", "IZO_PROCESS_ROLE": "server"}}


def checkpoint(**changes):
    value = {"schema": "izo-d3-phone-active/v1", "status": "AWAITING_RELEASE", "sourceSha": SHA,
        "project": PROJECT, "runId": RUN, "jobId": JOB, "clientSha256": CLIENT,
        "initialStatus": "running", "reloadedStatus": "processing", "returnedStatus": "running",
        "observations": deepcopy(subject.OBSERVATIONS), "modelExecution": False, "acceleratorExecution": False}
    value.update(changes)
    return value


def state():
    return {"queryOnly": True, "processStartTicks": "12345", "job": None, "receipt": {
        "fixture": "controlled-chat-video-v1", "lifetimeSeconds": 300, "instanceId": INSTANCE,
        "control": {"sequence": 0, "action": None, "status": "IDLE"},
        "provider": {"model_execution": False, "jobs": [], "counts": {"accepted": 0}, "d3": {
            "profile": "controlled-chat-video-v1", "modelExecution": False, "acceleratorExecution": False,
            "chat": [], "video": None}}}}


def held(value):
    value["job"] = {"id": JOB, "mode": "text_to_image", "provider": "comfyui", "status": "sent_to_comfyui",
                    "ownerSha256": HASHES, "activeOwnedJobs": 1}
    value["receipt"]["provider"]["jobs"] = [{"prompt_id": PROMPT, "client_sha256": CLIENT,
        "body_sha256": "3" * 64, "mode": "hold", "state": "held"}]
    value["receipt"]["provider"]["counts"]["accepted"] = 1


class FakeShadow:
    def __init__(self, directory):
        self.project, self.sha, self.root, self.fixture = PROJECT, SHA, directory, True
        self.files, self.env, self.calls, self.signals = [], {}, [], []
        self.observed, self.skip_ack, self.failure = state(), None, None
        self.executor = IsolatedExecutor(self.run, context="default", engine_id="owned-engine-123456789",
                                        machine_sha256="f" * 64)
        self.container = {"Id": CID, "Image": IMAGE, "RestartCount": 0,
            "State": {"Pid": 501, "StartedAt": IDENTITY["startedAt"], "Running": True},
            "Config": {"Labels": {"io.izo.owner": subject.OWNER, "com.docker.compose.project": PROJECT,
                "com.docker.compose.service": "backend"}, "User": EXPECTED["user"], "Cmd": EXPECTED["command"],
                "Env": [key + "=" + value for key, value in EXPECTED["environment"].items()]}}

    def config(self):
        return {"services": {"backend": deepcopy(EXPECTED)}}

    def docker(self, *args, **kwargs):
        return self.executor.docker(*args, **kwargs)

    def source_guard(self):
        self.run(["git", "status", "--porcelain"])

    def run(self, args, **kwargs):
        self.calls.append((list(args), dict(kwargs)))
        if self.failure:
            raise RuntimeError(PRIVATE)
        if args[0] == "git":
            return ""
        command = args[3:]
        if command[:2] == ["context", "inspect"]:
            return json.dumps([{"Name": "default", "Endpoints": {"docker": {"Host": "unix:///var/run/docker.sock"}}}])
        if command[0] == "info":
            return json.dumps({"ID": "owned-engine-123456789", "OSType": "linux"})
        if command == ["inspect", CID]:
            return json.dumps([self.container])
        if command[:5] == ["exec", CID, "python", "-c", subject.READ_STATE]:
            owner, job = json.loads(command[5])
            if owner != OWNER or job not in {None, JOB}:
                raise RuntimeError(PRIVATE)
            return json.dumps(self.observed)
        if command[:5] == ["exec", CID, "python", "-c", subject.SEND_SIGNAL]:
            self.signals.append(command[-1])
            if command[-1] != self.skip_ack:
                sequence = 1 if command[-1] == "hold" else 2
                self.observed["receipt"]["control"] = {"sequence": sequence, "action": command[-1], "status": "ACK"}
                if command[-1] == "release":
                    self.observed["receipt"]["provider"]["jobs"][0]["state"] = "completed"
                    self.observed["job"].update(status="completed", activeOwnedJobs=0)
            return "D3_PHONE_SIGNAL_SENT"
        raise AssertionError("Unexpected controlled Docker operation")


@unittest.skipUnless(sys.platform == "linux", "Linux filesystem boundary")
class WatchTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="izo-d3-phone-watch-")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name); self.directory.chmod(0o700)
        self.shadow = FakeShadow(self.directory)
        me = {"legacy_user_id": OWNER[0], "internal_user_id": OWNER[1]}
        self.flow = SimpleNamespace(project=PROJECT, source_sha=SHA, owner=SimpleNamespace(request=Mock(return_value=me)))
        identity = patch("tools.docker_shadow_executor.guest_identity", return_value="f" * 64)
        identity.start(); self.addCleanup(identity.stop)
        self.watch = subject.PhoneWatch(self.shadow, {"backend": IMAGE}, self.flow, self.directory, RUN,
                                       api_identity=Mock(return_value=deepcopy(IDENTITY)))
        self.addCleanup(self.watch.close)

    def write(self, value=None):
        path = self.directory / subject.MARKER
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as target:
            target.write((json.dumps(value if value is not None else checkpoint()) + "\n").encode())
        return path

    def complete(self, value=None):
        self.watch.start()
        self.assertEqual(self.shadow.signals, ["hold"])
        self.assertEqual(self.watch.snapshot()["holdAck"]["sequence"], 1)
        held(self.shadow.observed)
        self.write(value)
        self.watch.thread.join(1)
        self.assertFalse(self.watch.thread.is_alive())
        return self.watch.close()

    def test_actual_marker_thread_releases_one_full_owned_job_only_after_hold_ack_and_joins(self):
        result = self.complete()
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(self.shadow.signals, ["hold", "release"])
        self.assertEqual((result["jobId"], result["ownerSha256"]), (JOB, HASHES))
        self.assertEqual(result["cleanup"], "PASS"); self.assertFalse(result["threadAlive"])
        self.assertEqual(json.loads((self.directory / "phone-active-watch.json").read_text()), result)
        with self.assertRaises(OSError):
            os.fstat(self.watch.directory_fd)
        self.assertTrue(all(0 < options["timeout"] <= 2 for _, options in self.shadow.calls))
        self.assertIsNot(self.watch.transport.shadow.executor, self.shadow.executor)
        self.assertNotIn(PRIVATE, json.dumps(result))

    def test_cross_run_or_source_and_forged_full_client_hash_never_release(self):
        for key, value in (("runId", "0" * 32), ("sourceSha", "0" * 40), ("project", "izo-asa-shadow-foreign"),
                           ("clientSha256", "0" * 64), ("modelExecution", True)):
            with self.subTest(key=key), self.assertRaises(ProductError):
                subject.marker_contract(checkpoint(**{key: value}), SHA, PROJECT, RUN)
        result = self.complete(checkpoint(runId="0" * 32))
        self.assertEqual(result["status"], "FAIL"); self.assertEqual(self.shadow.signals, ["hold"])

    def test_empty_created_marker_waits_for_one_complete_write_without_replacement(self):
        self.watch.start(); held(self.shadow.observed)
        path = self.directory / subject.MARKER
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            self.assertIsNone(self.watch._marker())
            os.write(descriptor, (json.dumps(checkpoint()) + "\n").encode()); os.fsync(descriptor)
        finally:
            os.close(descriptor)
        self.watch.thread.join(1)
        self.assertEqual(self.watch.close()["status"], "PASS")

    def test_marker_link_permissions_size_and_replacement_refused_without_following(self):
        path = self.write(); self.watch._marker()
        path.chmod(0o644)
        with self.assertRaises(ProductError): self.watch._marker()
        path.chmod(0o600); path.write_bytes(b"x" * 4096)
        with self.assertRaises(ProductError): self.watch._marker()
        descriptor = os.open(path, os.O_RDONLY)
        try:
            path.unlink(); self.write()
            with self.assertRaises(ProductError): self.watch._marker()
        finally: os.close(descriptor)
        path.unlink(); foreign = self.directory / "foreign"; foreign.write_text("untouched")
        path.symlink_to(foreign)
        with self.assertRaises(OSError): self.watch._marker()
        self.assertEqual(foreign.read_text(), "untouched")

    def test_api_restart_or_profile_change_prevents_release(self):
        self.watch.start(); held(self.shadow.observed)
        self.shadow.container["State"]["Pid"] += 1
        self.write(); self.watch.thread.join(1)
        result = self.watch.close()
        self.assertEqual(result["status"], "FAIL"); self.assertEqual(self.shadow.signals, ["hold"])
        self.assertEqual(result["errorCode"], "D3_PHONE_API_CHANGED")

    def test_missing_marker_expires_and_stop_without_marker_never_sends_release(self):
        with patch.object(subject, "HOLD_SECONDS", .03): self.watch.start()
        self.watch.thread.join(.5)
        result = self.watch.close()
        self.assertEqual(result["status"], "FAIL"); self.assertEqual(result["cleanup"], "PASS")
        self.assertEqual(self.shadow.signals, ["hold"])
        self.assertEqual(result["errorCode"], "D3_PHONE_WATCH_DEADLINE")

    def test_stop_event_joins_without_cancelling_or_releasing_provider_job(self):
        self.watch.start()
        result = self.watch.close()
        self.assertFalse(result["threadAlive"]); self.assertEqual(result["status"], "FAIL")
        self.assertEqual(self.shadow.signals, ["hold"])

    def test_no_hold_ack_means_no_browser_thread_and_safe_error(self):
        self.shadow.skip_ack = "hold"
        with patch.object(subject, "ACK_SECONDS", .02), self.assertRaises(ProductError): self.watch.start()
        result = self.watch.close()
        self.assertIsNone(self.watch.thread); self.assertEqual(result["status"], "FAIL")
        self.assertEqual(self.shadow.signals, ["hold"]); self.assertNotIn(PRIVATE, json.dumps(result))

    def test_release_without_ack_is_fail_even_if_signal_was_sent(self):
        self.shadow.skip_ack = "release"
        with patch.object(subject, "ACK_SECONDS", .03): result = self.complete()
        self.assertEqual(result["status"], "FAIL"); self.assertNotIn("releaseAck", result)
        self.assertEqual(self.shadow.signals, ["hold", "release"])

    def test_stop_during_private_read_joins_and_prevents_release(self):
        original, entered, finish = self.shadow.run, threading.Event(), threading.Event()
        def delayed(args, **options):
            if subject.READ_STATE in args and json.loads(args[-1])[1] is not None:
                entered.set(); finish.wait(.2)
            return original(args, **options)
        with patch.object(self.shadow, "run", side_effect=delayed):
            self.watch.start(); held(self.shadow.observed); self.write()
            self.assertTrue(entered.wait(.5))
            result = self.watch.close(); finish.set()
        self.assertFalse(result["threadAlive"]); self.assertEqual(result["status"], "FAIL")
        self.assertEqual(self.shadow.signals, ["hold"])

    def test_join_timeout_is_explicit_fail_and_never_authorizes_release(self):
        entered, finish, original = threading.Event(), threading.Event(), self.watch._marker
        def blocked():
            entered.set(); finish.wait(1); return original()
        with patch.object(self.watch, "_marker", side_effect=blocked), patch.object(subject, "JOIN_SECONDS", .01):
            try:
                self.watch.start(); self.assertTrue(entered.wait(.5)); result = self.watch.close()
                self.assertEqual((result["status"], result["cleanup"], result["threadAlive"]), ("FAIL", "FAIL", True))
                self.assertEqual(result["errorCode"], "D3_PHONE_WATCH_JOIN_FAILED")
            finally:
                finish.set(); self.watch.thread.join(.5); os.close(self.watch.directory_fd)
        self.assertFalse(self.watch.thread.is_alive()); self.assertEqual(self.shadow.signals, ["hold"])

    def test_replaced_owned_directory_cannot_receive_marker_reads_or_checkpoint_writes(self):
        original = self.directory.with_name(self.directory.name + "-original")
        self.directory.rename(original); self.directory.mkdir(mode=0o700)
        try:
            with self.assertRaises(ProductError): self.watch._marker()
            self.assertEqual(self.watch.close()["status"], "FAIL")
            self.assertEqual(list(self.directory.iterdir()), [])
        finally:
            self.directory.rmdir(); original.rename(self.directory)

    def test_checkpoint_failure_cannot_leave_a_pass_or_an_active_thread(self):
        with patch.object(subject, "save_private", side_effect=OSError(PRIVATE)):
            with self.assertRaises(OSError): self.watch.start()
            result = self.watch.close()
        self.assertEqual(result["status"], "FAIL"); self.assertEqual(result["cleanup"], "PASS")
        self.assertNotIn(PRIVATE, json.dumps(result))


@unittest.skipUnless(sys.platform == "linux", "Linux filesystem boundary")
class ScriptTests(unittest.TestCase):
    def test_fixed_signal_checks_pid1_start_identity_before_existing_usr_signal(self):
        body = b"1 (python fixture) " + b" ".join([b"S"] + [b"0"] * 18 + [b"12345"])
        for ticks, uid, action, accepted in (("12345", 10001, "hold", True), ("12345", 10001, "release", True),
                                            ("999", 10001, "release", False), ("12345", 0, "hold", False)):
            with self.subTest(ticks=ticks, uid=uid, action=action), patch("builtins.open", return_value=io.BytesIO(body)), \
                    patch("sys.argv", ["probe", ticks, action]), patch("os.geteuid", return_value=uid), \
                    patch("os.kill") as kill, patch("sys.stdout", new=io.StringIO()):
                if accepted:
                    exec(subject.SEND_SIGNAL, {})
                    kill.assert_called_once_with(1, signal.SIGUSR1 if action == "hold" else signal.SIGUSR2)
                else:
                    with self.assertRaises(SystemExit): exec(subject.SEND_SIGNAL, {})
                    kill.assert_not_called()

    def test_actual_sqlite_readonly_query_checks_full_owner_without_import_or_mutation(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary); database = directory / "owned.sqlite3"; receipt = directory / "provider.json"
            provider = state()["receipt"]; receipt.write_text(json.dumps(provider)); receipt.chmod(0o600)
            with sqlite3.connect(database) as conn:
                conn.executescript("CREATE TABLE users(id TEXT,internal_user_id TEXT); CREATE TABLE jobs(id TEXT,user_id TEXT,mode TEXT,provider TEXT,status TEXT,settings_json TEXT);")
                conn.execute("INSERT INTO users VALUES(?,?)", OWNER)
                conn.execute("INSERT INTO jobs VALUES(?,?,?,?,?,?)", (JOB, OWNER[0], "text_to_image", "comfyui", "sent_to_comfyui", PRIVATE))
            conn.close()
            original_hash = hashlib.sha256(database.read_bytes()).hexdigest()
            original_open, original_lstat, original_fstat, connect = os.open, os.lstat, os.fstat, sqlite3.connect
            def owned(info):
                fields = list(info); fields[4] = 10001; return os.stat_result(fields)
            def mapped_open(path, flags, *args, **kwargs):
                self.assertEqual(path, "/tmp/izo-shadow-provider-receipt.json")
                self.assertTrue(flags & os.O_NOFOLLOW)
                return original_open(receipt, flags, *args, **kwargs)
            def mapped_connect(database_uri, **kwargs):
                self.assertEqual((database_uri, kwargs), ("file:/home/izo/data/app.sqlite3?mode=ro", {"uri": True, "timeout": 1}))
                return connect(database.as_uri() + "?mode=ro", **kwargs)
            body = b"1 (python fixture) " + b" ".join([b"S"] + [b"0"] * 18 + [b"12345"])
            for owner, job, success in ((OWNER, JOB, True), ([OWNER[0], "foreign"], JOB, False), (OWNER, JOB[:10], False)):
                buffer = io.BytesIO(); stdout = SimpleNamespace(buffer=buffer, write=lambda text: len(text), flush=lambda: None)
                with self.subTest(owner=owner, job=job), patch("sys.argv", ["probe", json.dumps([owner, job])]), \
                        patch("sys.stdout", stdout), patch("builtins.open", return_value=io.BytesIO(body)), \
                        patch("os.open", side_effect=mapped_open), patch("os.fstat", side_effect=lambda fd: owned(original_fstat(fd))), \
                        patch("os.lstat", side_effect=lambda _path: owned(original_lstat(database))), \
                        patch("sqlite3.connect", side_effect=mapped_connect):
                    if success:
                        exec(subject.READ_STATE, {})
                        result = json.loads(buffer.getvalue())
                        self.assertTrue(result["queryOnly"]); self.assertEqual(result["job"]["ownerSha256"], HASHES)
                        self.assertEqual(result["job"]["id"], JOB); self.assertNotIn(PRIVATE.encode(), buffer.getvalue())
                    else:
                        with self.assertRaises(SystemExit): exec(subject.READ_STATE, {})
                self.assertEqual(hashlib.sha256(database.read_bytes()).hexdigest(), original_hash)


class AdmissionTests(unittest.TestCase):
    def test_bool_counters_extra_observation_or_completed_state_are_not_active_proof(self):
        for marker in (checkpoint(initialStatus="completed"), checkpoint(observations={**subject.OBSERVATIONS, "imageSubmits": False}),
                       checkpoint(observations={**subject.OBSERVATIONS, "extra": True})):
            with self.assertRaises(ProductError):
                subject.marker_contract(marker, SHA, PROJECT, RUN)


    def test_owner_or_full_job_or_multiple_provider_jobs_fail_private_binding(self):
        base = state(); held(base)
        for fault in ("owner", "job", "extra", "expired", "mode", "another-active"):
            observed = deepcopy(base)
            if fault == "owner": observed["job"]["ownerSha256"] = ["0" * 64, "1" * 64]
            elif fault == "job": observed["job"]["id"] = JOB[:10]
            elif fault == "extra": observed["receipt"]["provider"]["jobs"].append(deepcopy(observed["receipt"]["provider"]["jobs"][0]))
            elif fault == "expired": observed["receipt"]["provider"]["jobs"][0]["state"] = "failed"
            elif fault == "mode": observed["receipt"]["provider"]["jobs"][0]["mode"] = "complete"
            else: observed["job"]["activeOwnedJobs"] = 2
            with self.subTest(fault=fault), self.assertRaises(ProductError):
                subject.held_job(observed, checkpoint(), HASHES, INSTANCE)


    @patch("tools.docker_d3_images.read_file", lambda p, _: p.read_bytes().replace(b"\r\n", b"\n"))
    def test_failed_hold_prevents_browser_and_still_closes_watcher(self):
        att = {"sourceSha": SHA, "project": PROJECT, "origin": "http://127.0.0.1:28123", **dict.fromkeys(
            ("isolatedData", "fakeProviderOnly", "networkEgressDenied", "externalEffectsDisabled"), True)}
        flow = runner.ProductFlow(att)
        flow.credentials = [(client, "owned@example.invalid", PRIVATE) for client in (flow.owner, flow.other)]
        watch = Mock(owner=OWNER)
        watch.start.side_effect = ProductError("D3_PHONE_CONTROL_REJECTED")
        watch.close.return_value = {"status": "FAIL", "cleanup": "PASS", "threadAlive": False}
        with tempfile.TemporaryDirectory() as tmp, patch.object(runner, "browser_run") as browser:
            result = runner.prove_chat_video(flow, att, Path(tmp) / "browser",
                provider_receipt=lambda: state()["receipt"], phone_watch=lambda directory, run_id: watch)
        browser.assert_not_called(); watch.start.assert_called_once(); watch.close.assert_called_once()
        self.assertEqual(result["errorCode"], "D3_PHONE_CONTROL_REJECTED")
        self.assertNotIn(PRIVATE, json.dumps(result))

    def test_held_mode_requires_joined_private_and_matching_actual_phone_result(self):
        watch = {"status": "PASS", "cleanup": "PASS", "threadAlive": False, "fullJobOwnerVerified": True,
            "wasHeld": True, "newGenerationRequests": 0, "releaseSeconds": 12, "jobId": JOB, "clientSha256": CLIENT,
            "sourceSha": SHA, "project": PROJECT, "runId": RUN,
            "holdAck": {"sequence": 1, "action": "hold", "status": "ACK"},
            "releaseAck": {"sequence": 2, "action": "release", "status": "ACK"}}
        phone = {"status": "PASS", "sourceSha": SHA, "project": PROJECT, "runId": RUN, "jobId": JOB,
            "uiCancellation": "NOT_SUPPORTED", "newGenerationRequests": 0, "imageId": "owned_image", "imageUrl": "/api/media/owned.png",
            "decoded": {"url": "/api/media/owned.png", "complete": True, "width": 64, "height": 64},
            "observations": deepcopy(subject.OBSERVATIONS), "statuses": {key: "running" for key in
                ("initialStatus", "reloadedStatus", "returnedStatus")}}
        browser = {"sourceSha": SHA, "project": PROJECT, "runId": RUN,
                   "image": {"jobId": JOB, "id": "owned_image", "url": "/api/media/owned.png"},
                   "checks": {"chatImage": {"phoneActive": phone}}}
        runner.accepted_phone_watch(watch, browser)
        for key, value in (("runId", "0" * 32), ("cleanup", "FAIL"), ("releaseSeconds", 55), ("threadAlive", True),
                           ("jobId", JOB[:10]), ("fullJobOwnerVerified", False), ("releaseAck", {"sequence": 3})):
            with self.subTest(key=key), self.assertRaises(ProductError):
                runner.accepted_phone_watch({**watch, key: value}, browser)
        with self.assertRaises(ProductError):
            runner.accepted_phone_watch(watch, {**browser, "checks": {"chatImage": {}}})
        for change in ({"imageId": "foreign"}, {"decoded": {}}, {"statuses": {}}, {"observations": {}}):
            with self.assertRaises(ProductError):
                runner.accepted_phone_watch(watch, {**browser, "checks": {"chatImage": {"phoneActive": {**phone, **change}}}})

    def test_caller_run_identity_rejects_old_checkpoint_before_partial_image_admission(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory, payload, report = Path(temporary), {"private": PRIVATE}, {"sourceSha": SHA, "project": PROJECT}
            (directory / "chat-video-image.json").write_text(json.dumps({"runId": "0" * 32}))
            with patch.object(runner.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)) as child:
                with self.assertRaisesRegex(ProductError, "D3_BROWSER_RUN_ID_CHANGED"):
                    runner.browser_run(payload, directory, report, run_id=RUN)
            self.assertEqual(payload, {}); self.assertNotIn("image", report)
            self.assertEqual(child.call_args.kwargs["timeout"], 150)
            self.assertNotIn(PRIVATE, json.dumps(report))


if __name__ == "__main__":
    unittest.main()
