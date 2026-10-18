"""Counterfactual installed-browser receipts must not manufacture D3 acceptance."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from tools import docker_d3_chat_video as subject
from tools.docker_shadow_product import ProductError

SHA, PROJECT, RUN = "a" * 40, "izo-asa-shadow-d3-owned", "b" * 32
IMAGE = {"id": "image_owned", "jobId": "job_owned", "url": "/api/media/owned.png", "tokenCost": 1}


def process_receipt():
    return {"status": "PASS", "timedOut": False, "nodeReturncode": 0,
            "scope": "PRIVATE_LINUX_SUBREAPER", "seconds": .2,
            "cleanup": {"status": "PASS", "childrenAtShutdown": 0, "remainingChildren": 0}}


def browser_receipt():
    return {"status": "PASS", "sourceSha": SHA, "project": PROJECT, "runId": RUN,
            "modelExecution": False, "acceleratorExecution": False, "image": dict(IMAGE),
            "sessionCleanup": "PASS", "browserCleanup": "PASS"}


def image_receipt():
    return {"status": "PARTIAL", "sourceSha": SHA, "project": PROJECT, "runId": RUN,
            "image": dict(IMAGE), "chatImage": {"status": "PASS", "jobId": IMAGE["jobId"],
                "requestId": "owned_chat_request", "imageSubmits": 1,
                "accounting": {"status": "PASS", "tokenCost": 1, "mainBalanceDebit": 1,
                    "dailyBudgetDebit": 0, "refundDelta": 0, "zeroTokenChatEntries": 1}}}


class BrowserReceiptTests(unittest.TestCase):
    def test_process_cleanliness_requires_actual_exact_zeroes_and_no_cleanup_work(self):
        subject.clean_process(process_receipt(), 0)
        mutations = [lambda v: v.update(status="FAIL"), lambda v: v.update(timedOut=True),
            lambda v: v.update(timedOut=0), lambda v: v.update(nodeReturncode=False),
            lambda v: v.update(nodeReturncode=-9), lambda v: v.update(scope="PROCESS_GROUP_ONLY"),
            lambda v: v.update(errorCode="D3_PROCESS_FAILED"), lambda v: v.pop("cleanup"),
            lambda v: v["cleanup"].update(status="FAIL"),
            lambda v: v["cleanup"].update(childrenAtShutdown=1),
            lambda v: v["cleanup"].update(childrenAtShutdown=False),
            lambda v: v["cleanup"].update(remainingChildren=1),
            lambda v: v["cleanup"].update(remainingChildren=None)]
        for index, mutate in enumerate(mutations):
            with self.subTest(index=index), self.assertRaises(ProductError):
                value = process_receipt()
                mutate(value)
                subject.clean_process(value, 0)
        for returncode in (1, False, 0.0):
            with self.subTest(returncode=repr(returncode)), self.assertRaises(ProductError):
                subject.clean_process(process_receipt(), returncode)

    def run_browser(self, *, browser=None, partial=None, supervisor=None, execution=None, returncode=0):
        browser = browser_receipt() if browser is None else browser
        partial = image_receipt() if partial is None else partial
        supervisor = process_receipt() if supervisor is None else supervisor
        with tempfile.TemporaryDirectory(prefix="izo-d3-receipts-") as temp:
            directory = Path(temp)
            report = {"status": "FAIL", "sourceSha": SHA, "project": PROJECT}
            payload = {"privateOwnedPassword": "stdin-only-canary"}

            def run(command, **options):
                self.assertEqual(command[1:3], [str(subject.ROOT / "tools/docker_d3_process.py"),
                                               str(subject.ROOT / "tools/docker_d3_chat_video.mjs")])
                self.assertEqual(options["timeout"], 150)
                self.assertEqual(options["stdout"], subprocess.DEVNULL)
                self.assertEqual(options["stderr"], subprocess.DEVNULL)
                self.assertNotIn("stdin-only-canary", json.dumps(command))
                self.assertIn(b"stdin-only-canary", options["input"])
                for name, value in (("chat-video-browser.json", browser),
                                    ("chat-video-image.json", partial), ("browser-process.json", supervisor)):
                    if value is not False:
                        (directory / name).write_text(json.dumps(value), encoding="utf-8")
                if execution:
                    raise execution
                return subprocess.CompletedProcess(command, returncode)

            with patch.object(subject.subprocess, "run", side_effect=run):
                try:
                    value = subject.browser_run(payload, directory, report)
                    error = None
                except ProductError as failure:
                    value, error = None, str(failure)
            self.assertEqual(payload, {})
            self.assertNotIn("stdin-only-canary", json.dumps(report))
            return value, report, error

    def test_isolated_supervisor_and_matching_image_checkpoint_are_required(self):
        browser, report, error = self.run_browser()
        self.assertIsNone(error)
        self.assertEqual(browser["status"], "PASS")
        self.assertEqual(report["image"], IMAGE)
        self.assertEqual(report["status"], "FAIL", "Only the outer provider correlation may finish acceptance")

    def test_late_video_or_supervisor_failure_preserves_only_owned_completed_image(self):
        cases = [dict(browser=False), dict(supervisor=False), dict(returncode=1),
            dict(execution=subprocess.TimeoutExpired(["owned-helper"], 150)),
            dict(execution=OSError("private-diagnostic-canary"))]
        failed = browser_receipt()
        failed.update(status="FAIL", errorCode="D3_VIDEO_GALLERY_DIMENSIONS_MISMATCH")
        cases.append(dict(browser=failed, returncode=1))
        for index, case in enumerate(cases):
            with self.subTest(index=index):
                browser, report, error = self.run_browser(**case)
                self.assertIsNone(browser)
                self.assertTrue(error.startswith("D3_"))
                self.assertEqual(report["status"], "FAIL")
                self.assertEqual(report["image"], IMAGE)
                self.assertNotIn("private-diagnostic-canary", json.dumps(report) + error)

    def test_foreign_or_changed_checkpoint_and_external_media_are_rejected(self):
        mutations = [lambda v: v.update(sourceSha="c" * 40), lambda v: v.update(project="izo-asa-shadow-other"),
            lambda v: v.update(runId="invalid"), lambda v: v.update(status="PASS"),
            lambda v: v["image"].update(url="https://example.invalid/private.png"),
            lambda v: v["image"].update(url="/api/media/../private"),
            lambda v: v["image"].update(tokenCost=True),
            lambda v: v["chatImage"].update(status="FAIL"),
            lambda v: v["chatImage"].update(jobId="different_completed_job"),
            lambda v: v["chatImage"].update(requestId=""),
            lambda v: v["chatImage"].update(imageSubmits=0),
            lambda v: v["chatImage"].update(imageSubmits=True),
            lambda v: v["chatImage"].update(errorCode="D3_LATE_IMAGE_FAILURE"),
            lambda v: v["chatImage"].pop("accounting"),
            lambda v: v["chatImage"]["accounting"].update(refundDelta=1),
            lambda v: v["chatImage"]["accounting"].update(mainBalanceDebit=0)]
        for index, mutate in enumerate(mutations):
            with self.subTest(index=index):
                value = image_receipt()
                mutate(value)
                _, report, error = self.run_browser(partial=value)
                self.assertTrue(error.startswith("D3_"))
                self.assertNotIn("image", report)
        changed = browser_receipt()
        changed["image"]["jobId"] = "other_job"
        _, report, error = self.run_browser(browser=changed)
        self.assertEqual(error, "D3_BROWSER_IMAGE_CHECKPOINT_CHANGED")
        self.assertEqual(report["image"], IMAGE)

    def test_oversized_or_nondictionary_receipt_is_never_accepted(self):
        with tempfile.TemporaryDirectory(prefix="izo-d3-receipt-limit-") as temp:
            directory = Path(temp)
            path = directory / "chat-video-browser.json"
            for body in (" " * 65537, "[]", "null"):
                with self.subTest(bytes=len(body)):
                    path.write_text(body, encoding="utf-8")
                    with self.assertRaises(ProductError):
                        subject.receipt(directory, path.name)


def provider_records():
    def job(number):
        return {"prompt_id": f"01234567-0123-4567-8901-{number:012d}", "state": "completed", "mode": "complete",
                "body_sha256": str(number) * 64, "client_sha256": str(number + 1) * 64}
    previous, new = job(1), job(2)
    new["client_sha256"] = hashlib.sha256(b"onenode-backend-job_owned").hexdigest()
    before = {"fixture": subject.MARKER, "lifetimeSeconds": 300, "instanceId": "c" * 32,
        "provider": {"model_execution": False, "counts": {"accepted": 1}, "jobs": [previous],
            "d3": {"profile": subject.MARKER, "modelExecution": False, "acceleratorExecution": False,
                   "chat": [], "video": None, "clipSha256": "d" * 64, "clipBytes": 1024}}}
    after = copy.deepcopy(before)
    after["provider"]["counts"]["accepted"] = 2
    after["provider"]["jobs"].append(new)
    after["provider"]["d3"]["chat"] = [{"stage": stage, "runId": RUN,
        "httpStatus": 502 if stage == "failed" else 200, "historyConfirmed": stage == "second",
        "toolRound": stage == "done"} for stage in ("first", "second", "failed", "image", "done")]
    after["provider"]["d3"]["video"] = {"jobId": "video_owned", "statusReads": 2, "downloads": 1,
                                        "width": 832, "height": 480, "frames": 25, "frameRate": 12}
    browser = {"runId": RUN, "image": dict(IMAGE),
               "checks": {"video": {"jobId": "video_owned", "sha256": "d" * 64, "bytes": 1024}}}
    return before, after, browser


class ProviderHistoryTests(unittest.TestCase):
    def accepted(self):
        before, after, browser = provider_records()
        browser.update(status="PASS", sessionCleanup="PASS", browserCleanup="PASS")
        for name in ("chat", "chatImage", "phone3d", "desktop3d", "video"):
            browser["checks"].setdefault(name, {})["status"] = "PASS"
        for name in ("chatImage", "video"):
            browser["checks"][name]["accounting"] = {"status": "PASS", "tokenCost": 1,
                "mainBalanceDebit": 1, "dailyBudgetDebit": 0, "refundDelta": 0,
                "zeroTokenChatEntries": 1 if name == "chatImage" else 0}
        browser["checks"]["video"]["tokenCost"] = 1
        self.assertEqual(subject.correlate(before, after, browser)["status"], "PASS")
        subject.accepted_browser(browser)
        return before, after, browser

    def test_matching_provider_and_top_level_pass_cannot_mask_a_missing_or_failed_scenario(self):
        before, after, original = self.accepted()
        # These receipts retain every provider/media correlation used by the previous caller.
        mutations = [lambda v: v["checks"].update(extra={"status": "PASS"}),
            lambda v: v.update(errorCode="D3_LATE_FAILURE")]
        for name in ("chat", "chatImage", "phone3d", "desktop3d", "video"):
            mutations.extend((lambda v, key=name: v["checks"][key].update(status="FAIL"),
                              lambda v, key=name: v["checks"][key].update(status="NOT_RUN")))
        for name in ("chat", "chatImage", "phone3d", "desktop3d"):
            mutations.append(lambda v, key=name: v["checks"].pop(key))
        for index, mutate in enumerate(mutations):
            with self.subTest(index=index):
                browser = copy.deepcopy(original)
                mutate(browser)
                self.assertEqual(subject.correlate(before, after, browser)["status"], "PASS")
                with self.assertRaises(ProductError):
                    subject.accepted_browser(browser)
        without_video = copy.deepcopy(original)
        without_video["checks"].pop("video")
        with self.assertRaises(ProductError):
            subject.accepted_browser(without_video)

    def test_accounting_flags_cannot_replace_a_complete_matching_debit(self):
        _, _, original = self.accepted()
        for name in ("chatImage", "video"):
            for patch_value in (None, {"status": "PASS"}, {"status": "FAIL"}, {"tokenCost": True},
                    {"mainBalanceDebit": 0}, {"dailyBudgetDebit": False}, {"refundDelta": 1},
                    {"zeroTokenChatEntries": 99}):
                with self.subTest(name=name, patch=patch_value), self.assertRaises(ProductError):
                    browser = copy.deepcopy(original)
                    if patch_value is None:
                        browser["checks"][name].pop("accounting")
                    elif patch_value == {"status": "PASS"}:
                        browser["checks"][name]["accounting"] = patch_value
                    else:
                        browser["checks"][name]["accounting"].update(patch_value)
                    subject.accepted_browser(browser)

    def test_matching_current_job_does_not_permit_prior_job_deletion_or_mutation(self):
        before, after, browser = provider_records()
        self.assertEqual(subject.correlate(before, after, browser)["status"], "PASS")
        mutations = [lambda v: v["provider"]["jobs"].pop(0),
            lambda v: v["provider"]["jobs"][0].update(state="expired"),
            lambda v: v["provider"]["jobs"][0].update(body_sha256="e" * 64),
            lambda v: v["provider"]["jobs"].insert(0, v["provider"]["jobs"][0]),
            lambda v: v["provider"]["counts"].update(accepted=99),
            lambda v: v["provider"]["jobs"][1].update(mode="disconnect")]
        for index, mutate in enumerate(mutations):
            with self.subTest(index=index), self.assertRaises(ProductError):
                value = copy.deepcopy(after)
                mutate(value)
                subject.correlate(before, value, browser)


class PublicationPersistenceTests(unittest.TestCase):
    """Synthetic HTTP/receipt counterexamples; these bytes are not a runtime decode proof."""
    def setUp(self):
        self.attestation = {"origin": "http://127.0.0.1:25432", "sourceSha": SHA, "project": PROJECT,
            "isolatedData": True, "fakeProviderOnly": True, "networkEgressDenied": True, "externalEffectsDisabled": True}
        self.flow = subject.ProductFlow(self.attestation)
        self.events, self.stage, self.mutate = [], 0, lambda: None
        self.api = {"containerId": "c" * 64, "imageId": "sha256:" + "e" * 64, "hostPid": 100,
                    "startedAt": "2026-10-18T01:00:00Z", "restartCount": 0}
        self.data, self.status = {}, {}
        self.flow.saved["accounts"] = {}
        for name, client in zip(("owner", "other", "guest"), self.flow.clients):
            identity = {"legacy_user_id": "web_" + ("1" if name == "owner" else "2") * 32,
                        "internal_user_id": name + "-internal"}
            self.flow.saved["accounts"][name] = {"identity": copy.deepcopy(identity)}
            self.data[name, "/api/me-v2"] = identity
            client.request = self.reader(name)
        self.status["guest", "/api/me-v2"] = 401
        self.private, self.public = "/api/video/media/video_owned", "/api/feed/video/pub_owned?variant=full"
        private, public = b"\0\0\0\x18ftyp" + b"a" * 1200, b"\0\0\0\x18ftyp" + b"b" * 1300
        observed = {"status": "PASS", "jobId": "video_owned", "galleryId": "gallery_owned", "publicationId": "pub_owned",
            "tokenCost": 1, "sha256": hashlib.sha256(private).hexdigest(), "bytes": len(private),
            "publicSha256": hashlib.sha256(public).hexdigest(), "publicBytes": len(public), "metadataMatches": True,
            "playback": {"width": 832, "height": 480, "duration": 25 / 12},
            "publicPlayback": {"width": 832, "height": 480, "duration": 25 / 12}, "publicMediaProof": "GUEST_FETCH_AND_DECODE"}
        browser = browser_receipt()
        browser["checks"] = {name: {"status": "PASS"} for name in ("chat", "chatImage", "phone3d", "desktop3d")}
        browser["checks"]["video"] = observed
        for name in ("chatImage", "video"):
            browser["checks"][name]["accounting"] = {"status": "PASS", "tokenCost": 1, "mainBalanceDebit": 1,
                "dailyBudgetDebit": 0, "refundDelta": 0, "zeroTokenChatEntries": 1 if name == "chatImage" else 0}
        self.report = {"status": "PASS", "sourceSha": SHA, "project": PROJECT, "runId": RUN,
                       "browser": browser, "process": process_receipt()}
        self.data["owner", "/api/video/jobs/video_owned"] = {"id": "video_owned", "status": "completed",
            "videoUrl": self.private, "galleryVideoId": "gallery_owned", "galleryDeleted": False, "prompt": "private-canary"}
        self.data["owner", "/api/phone/v1/jobs/video_owned"] = {"ok": True, "job": {"id": "video_owned",
            "status": "completed", "terminal": True, "result": {"id": "gallery_owned", "url": self.private}}}
        self.publication = {"id": "pub_owned", "video_id": "gallery_owned", "image_id": None, "media_type": "video",
            "status": "published", "media_status": "ready", "moderation_status": "approved",
            "user_id": "owner-internal", "video_url": self.public, "title": "private-title-canary"}
        self.data["owner", "/api/feed/publications/pub_owned/status"] = {"ok": True, "publication": self.publication}
        self.data["guest", "/api/feed?type=fresh&limit=60"] = {"items": [copy.deepcopy(self.publication)]}
        self.data["owner", "/api/gallery/items?limit=60&filter=video"] = {"items": [{"id": "gallery_owned",
            "mediaType": "video", "videoUrl": self.private, "publicationId": "pub_owned", "published": True,
            "width": 832, "height": 480}]}
        self.data["owner", self.private], self.data["guest", self.public] = private, public
        for name, status in (("other", 404), ("guest", 401)):
            for route in ("/api/video/jobs/video_owned", "/api/phone/v1/jobs/video_owned",
                          "/api/feed/publications/pub_owned/status", self.private):
                self.status[name, route] = status

    def reader(self, name):
        def request(method, route, payload=None, *, expected=(200,), binary=False):
            self.events.append((self.stage, name, method, route))
            self.assertEqual(method, "GET")
            self.assertIsNone(payload)
            status = self.status.get((name, route), 200)
            if status not in expected:
                raise ProductError(f"PRODUCT_HTTP_STATUS_UNEXPECTED_{status}")
            return copy.deepcopy(self.data[name, route]) if status == 200 else {"httpStatus": status}
        return request

    def restart(self):
        self.events.append("RECREATE")
        self.stage = 1
        self.api.update(containerId="d" * 64, hostPid=101, startedAt="2026-10-18T01:00:01Z")
        self.mutate()
        return {"status": "PASS", "retainedRuntime": {"owned": "unchanged"}}

    def prove(self, identity=None):
        return subject.prove_publication_restart(self.flow, self.attestation, self.report, self.restart,
            identity or (lambda: copy.deepcopy(self.api)), "sha256:" + "e" * 64)

    def test_same_publication_survives_one_recreate_with_exact_metadata_media_and_privacy(self):
        value = self.prove()
        proof = value["publicationPersistence"]
        self.assertEqual(proof["status"], "PASS")
        self.assertEqual(proof["jobId"], "video_owned")
        self.assertEqual(proof["publicationId"], "pub_owned")
        self.assertEqual(proof["privateAccess"], "PASS")
        self.assertEqual(proof["mediaProof"], "IDENTICAL_TO_PRE_RECREATE_BROWSER_DECODE")
        self.assertEqual(set(proof["metadataSha256"]), {"owner", "job", "phone", "gallery", "ownerPublication", "guestPublication"})
        self.assertEqual(self.events.count("RECREATE"), 1)
        self.assertEqual(len(self.events), 37)
        self.assertEqual({event[0] for event in self.events if isinstance(event, tuple)}, {0, 1})
        self.assertNotIn("private-canary", json.dumps(value))
        self.assertNotIn("private-title-canary", json.dumps(value))

    def test_changed_full_metadata_or_media_and_private_access_cannot_pass(self):
        mutations = [lambda: self.data["owner", "/api/video/jobs/video_owned"].update(prompt="changed"),
            lambda: self.publication.update(title="changed"),
            lambda: self.data["guest", "/api/feed?type=fresh&limit=60"]["items"][0].update(title="changed"),
            lambda: self.data.update({("guest", self.public): b"\0\0\0\x18ftyp" + b"c" * 1300}),
            lambda: self.data.update({("owner", self.private): b"\0\0\0\x18ftyp" + b"d" * 1200}),
            lambda: self.status.update({("guest", self.private): 200}),
            lambda: self.data["owner", "/api/me-v2"].update(internal_user_id="foreign-owner"),
            lambda: self.publication.update(video_id="gallery_owned_other"),
            lambda: self.data["owner", "/api/phone/v1/jobs/video_owned"]["job"]["result"].update(id="other-full-id"),
            lambda: self.data["owner", "/api/gallery/items?limit=60&filter=video"]["items"][0].update(width=853),
            lambda: self.data["guest", "/api/feed?type=fresh&limit=60"].update(items=[])]
        for index, mutation in enumerate(mutations):
            with self.subTest(index=index):
                self.setUp(); self.mutate = mutation
                with self.assertRaises(ProductError): self.prove()
                self.assertEqual(self.events.count("RECREATE"), 1)

    def test_changed_or_unrecreated_api_and_image_are_rejected(self):
        for change in ({"containerId": "c" * 64}, {"startedAt": "2026-10-18T01:00:00Z"},
                       {"imageId": "sha256:" + "f" * 64}):
            with self.subTest(change=change):
                self.setUp(); self.mutate = lambda: self.api.update(change)
                with self.assertRaises(ProductError): self.prove()
        self.setUp()
        identities = iter([dict(self.api), {**self.api, "hostPid": 999}])
        with self.assertRaises(ProductError): self.prove(lambda: next(identities))
        self.assertNotIn("RECREATE", self.events)
        self.setUp(); self.api["imageId"] = "sha256:" + "f" * 64
        with self.assertRaises(ProductError): self.prove()
        self.assertEqual(self.events, [])

    def test_invalid_decode_identity_or_unfinished_browser_stops_before_recreate(self):
        for key, value in (("publicMediaProof", "BYTES_ONLY"), ("publicBytes", True),
                           ("publicationId", "../foreign"), ("metadataMatches", False)):
            with self.subTest(key=key):
                self.setUp(); self.report["browser"]["checks"]["video"][key] = value
                with self.assertRaises(ProductError): self.prove()
                self.assertEqual(self.events, [])
        self.setUp(); self.report["process"]["cleanup"]["remainingChildren"] = 1
        with self.assertRaises(ProductError): self.prove()
        self.assertEqual(self.events, [])

    def test_oversized_metadata_and_failed_recreate_never_report_persistence(self):
        self.publication["title"] = "x" * 65537
        with self.assertRaises(ProductError): self.prove()
        self.assertNotIn("RECREATE", self.events)
        self.setUp()
        with patch.object(self, "restart", return_value={"status": "FAIL"}) as restart:
            with self.assertRaises(ProductError): self.prove()
            restart.assert_called_once_with()
        self.assertEqual(len(self.events), 18, "Only the pre-recreate snapshot may read the API")


if __name__ == "__main__":
    unittest.main()
