"""Reject false acceptance of incomplete image execution and duplicate accounting."""
from __future__ import annotations

import base64
import copy
import hashlib
import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from tools import docker_d3_image_modes as probe
from tools.docker_shadow_product import ProductError, ProductFlow


ATTESTATION = {"origin": "http://127.0.0.1:23981", "sourceSha": "a" * 40, "project": "izo-asa-shadow-d3-image",
    "isolatedData": True, "fakeProviderOnly": True, "networkEgressDenied": True, "externalEffectsDisabled": True}
OWNED_ID = "web_" + "a" * 32
SOURCE = {"id": "image-owned", "url": "/api/media/owned.png?userId=" + OWNED_ID}
DIGEST = "b" * 64


def receipt(jobs=()):
    return {"fixture": "controlled-chat-video-v1", "lifetimeSeconds": 300, "instanceId": "c" * 32,
        "provider": {"model_execution": False, "jobs": copy.deepcopy(list(jobs)), "counts": {"accepted": len(jobs)},
            "d3": {"profile": "controlled-chat-video-v1", "modelExecution": False, "acceleratorExecution": False,
                   "chat": [], "video": None}}}


def wire(job_id="job-owned-123", mode="edit", index=1):
    return {"prompt_id": "12345678-1234-1234-1234-" + f"{index:012x}", "state": "completed", "mode": "complete",
        "client_sha256": hashlib.sha256(("onenode-backend-" + job_id).encode()).hexdigest(),
        "body_sha256": hashlib.sha256(("distinct body " + job_id).encode()).hexdigest(),
        "graph": {"loadImageCount": 2 if mode == "faceswap" else 1, "allInputsOwned": True,
            "inputChainConnected": True, "loraCount": 1 if mode == "faceswap" else 0,
            "selectedFaceLora": probe.FACE_LORAS[0] if mode == "faceswap" else None, "allLorasAllowed": True}}


def phone(started, image):
    return {"ok": True, "job": {"id": started["id"], "operation": started["mode"], "modality": "image",
        "status": "completed", "phase": "terminal", "progress": 100, "terminal": True,
        "result": {"id": image["id"], "type": "image", "url": image["url"]},
        "billing": {"chargedTokens": started["tokenCost"], "refunded": False}}}


def owned_flow():
    flow = ProductFlow(ATTESTATION)
    for client in flow.clients:
        client.request = Mock(return_value={"httpStatus": 400})
    flow.media_hash = Mock(return_value=DIGEST)
    flow.account_snapshot = Mock()
    return flow


class ImageModeEvidenceTests(unittest.TestCase):
    def run_series(self, flow, callback, checkpoint=None):
        return probe.prove_image_modes(flow, SOURCE, attestation=ATTESTATION,
                                      provider_receipt=callback, checkpoint=checkpoint)

    def snapshots(self, main=1, daily=0):
        cost = main + daily
        before = {"identity": {"user": "owned", "session": "existing", "legacy_user_id": OWNED_ID},
                  "account": {"token_balance": 100, "daily_tokens_used": 0},
                  "ledger": {"summary": {"spentTokens": 0, "refundedTokens": 0,
                      "balanceSpentTokens": 0, "includedSpentTokens": 0, "balance": 100}, "items": []}}
        after = copy.deepcopy(before)
        after["account"] = {"token_balance": 100 - main, "daily_tokens_used": daily}
        after["ledger"] = {"summary": {"spentTokens": cost, "refundedTokens": 0,
            "balanceSpentTokens": main, "includedSpentTokens": daily, "balance": 100 - main},
            "items": [{"id": "charge-1", "spentTokens": cost, "delta": -main,
                "jobId": "job-owned-…", "mode": "edit", "provider": "comfyui",
                "reason": "generation" if main else "daily_generation"}]}
        started = {"id": "job-owned-123", "mode": "edit", "provider": "comfyui",
            "tokenCost": cost, "tokenBalance": 100 - main, "dailyTokensUsed": daily,
            "mainBalanceTokenPart": main, "dailyTokenPart": daily}
        return before, after, started

    def test_charge_for_another_job_mode_or_provider_is_rejected(self):
        for field, value in (("jobId", "unrelated…"), ("mode", "text_to_image"), ("provider", "external")):
            with self.subTest(field=field):
                before, after, started = self.snapshots()
                after["ledger"]["items"][0][field] = value
                with self.assertRaises(ProductError):
                    probe.settlement(before, after, started)

    def test_coherent_receipt_without_actual_debit_is_rejected(self):
        before, after, started = self.snapshots()
        after["account"]["token_balance"] = started["tokenBalance"] = 100
        after["ledger"]["summary"]["balance"] = 100
        with self.assertRaises(ProductError):
            probe.settlement(before, after, started)

    def test_completion_received_after_deadline_is_not_a_timely_success(self):
        for times, calls in (([11], 0), ([9, 11], 1)):
            owner = SimpleNamespace(request=Mock(return_value={"id": "job-a", "status": "completed", "progress": 100}))
            with patch.object(probe.time, "monotonic", side_effect=times):
                with self.assertRaisesRegex(ProductError, "JOB_TIMEOUT"):
                    probe.completed(SimpleNamespace(owner=owner), "job-a", deadline=10)
            self.assertEqual(owner.request.call_count, calls)

    def test_single_charge_is_accepted(self):
        for main, daily in ((1, 0), (0, 3), (1, 2)):
            with self.subTest(main=main, daily=daily):
                result = probe.settlement(*self.snapshots(main, daily))
                self.assertEqual(result["ledgerId"], "charge-1")
                self.assertEqual((result["mainBalanceDebit"], result["dailyBudgetDebit"]), (main, daily))
                self.assertEqual(result["publicJobId"], "job-owned-…")

    def test_double_charge_despite_coherent_summary(self):
        before, after, started = self.snapshots()
        after["ledger"]["items"].append({"id": "charge-2", "spentTokens": 1})
        with self.assertRaisesRegex(ProductError, "SINGLE_CHARGE"):
            probe.settlement(before, after, started)

    def test_missing_refunded_or_foreign_charge(self):
        for failure in ("missing", "refund", "identity", "cost", "summary"):
            with self.subTest(failure=failure):
                before, after, started = self.snapshots()
                changes = {"missing": (after["ledger"], "items", []),
                    "refund": (after["ledger"]["summary"], "refundedTokens", 1),
                    "identity": (after["identity"], "user", "foreign"), "cost": (started, "tokenCost", True),
                    "summary": (after["ledger"]["summary"], "spentTokens", 0)}
                target, field, value = changes[failure]
                target[field] = value
                with self.assertRaises(ProductError):
                    probe.settlement(before, after, started)

    def test_final_account_matches_admission(self):
        before, after, started = self.snapshots()
        after["account"]["token_balance"] = 98
        with self.assertRaisesRegex(ProductError, "ACCOUNT_MISMATCH"):
            probe.settlement(before, after, started)

    def test_failed_or_invalid_completion(self):
        for status, job_id, progress in (("failed", "job-a", 0), ("cancelled", "job-a", 0),
                                       ("surprise", "job-a", 0), ("completed", "job-b", 100),
                                       ("completed", "job-a", 99)):
            with self.subTest(status=status, id=job_id, progress=progress):
                owner = SimpleNamespace(request=lambda *args: {
                    "id": job_id, "status": status, "progress": progress})
                expected = "COMPLETION_INVALID" if status == "completed" else "JOB_FAILED"
                with patch.object(probe.time, "monotonic", return_value=0):
                    with self.assertRaisesRegex(ProductError, expected):
                        probe.completed(SimpleNamespace(owner=owner), "job-a", deadline=10)

    def test_canvas_and_private_input_paths(self):
        body = probe.payload("paint", "/api/media/owned.png")
        self.assertNotIn("inputImage1", body)
        self.assertTrue(body["canvas"].startswith("data:image/png;base64,iVBOR"))
        png = base64.b64decode(body["canvas"].split(",", 1)[1], validate=True)
        self.assertEqual(hashlib.sha256(png).hexdigest(), "6476365c2084d835546f23aa32927c463e3ed24e5bdd36eb3dce638ee442a536")
        for mode, url in (("arbitrary", "/api/media/owned.png"),
                          ("edit", "https://example.invalid/foreign.png"),
                          ("edit", "/api/media/../other"), ("edit", "/api/media/owned.png?token=private")):
            with self.assertRaises(ProductError):
                probe.payload(mode, url)

    def test_bootstrap_requires_owned_web_identity(self):
        for supplied, returned in (("demo_user", "demo_user"), (OWNED_ID, "demo_user")):
            with self.subTest(supplied=supplied):
                flow = owned_flow()
                flow.owner.request.side_effect = [SOURCE, {"user": {"id": returned}}]
                state = {"identity": {"legacy_user_id": supplied}}
                flow.account_snapshot.return_value = state
                with self.assertRaisesRegex(ProductError, "OWNED_WEB_ID|BOOTSTRAP_IDENTITY"):
                    self.run_series(flow, receipt)
                calls = flow.owner.request.call_args_list
                self.assertEqual(len(calls), 1 if supplied == "demo_user" else 2)
                if len(calls) == 2:
                    self.assertEqual(calls[1].args[2]["userId"], OWNED_ID)
                    self.assertEqual(calls[1].args[2]["platform"], "web")

    def test_ledger_history_is_preserved(self):
        for failure in ("remove", "change", "duplicate"):
            with self.subTest(failure=failure):
                before, after, started = self.snapshots()
                old = {"id": "prior", "spentTokens": 0, "delta": 100, "reason": "bonus_grant"}
                before["ledger"]["items"] = [old]
                if failure != "remove":
                    after["ledger"]["items"].append(dict(old))
                if failure == "change":
                    after["ledger"]["items"][-1]["delta"] = 99
                elif failure == "duplicate":
                    after["ledger"]["items"].append(dict(old))
                with self.assertRaisesRegex(ProductError, "LEDGER_BASELINE"):
                    probe.settlement(before, after, started)

    def test_debit_split_matches_all_records(self):
        for failure in ("daily_admission", "main_admission", "ledger_delta", "main_summary", "daily_summary", "boolean", "reason"):
            with self.subTest(failure=failure):
                before, after, started = self.snapshots(1, 2)
                if failure == "daily_admission":
                    started["dailyTokenPart"] = 3
                elif failure == "main_admission":
                    started["mainBalanceTokenPart"] = 0
                elif failure == "ledger_delta":
                    after["ledger"]["items"][0]["delta"] = -3
                elif failure == "main_summary":
                    after["ledger"]["summary"]["balanceSpentTokens"] = 3
                elif failure == "daily_summary":
                    after["ledger"]["summary"]["includedSpentTokens"] = 0
                elif failure == "boolean":
                    started["mainBalanceTokenPart"] = True
                else:
                    after["ledger"]["items"][0]["reason"] = "generation_refund"
                with self.assertRaisesRegex(ProductError, "DEBIT_MISMATCH"):
                    probe.settlement(before, after, started)

    def test_normal_completion_sequence(self):
        owner = SimpleNamespace(request=Mock(side_effect=[{"id": "job-a", "status": state, "progress": progress}
            for state, progress in (("queued", 0), ("running", 20), ("completed", 100))]))
        with patch.object(probe.time, "monotonic", return_value=1), patch.object(probe.time, "sleep"):
            job, states = probe.completed(SimpleNamespace(owner=owner), "job-a", deadline=10)
        self.assertEqual(job["id"], "job-a")
        self.assertEqual(states, ["completed", "queued", "running"])

    def test_phone_contract_and_privacy(self):
        _, _, started = self.snapshots()
        image = {"id": "result", "url": "/api/media/result.png"}
        valid = phone(started, image)
        probe.phone_result(valid, started, image)
        mutations = (("ok", False), ("job.modality", "video"), ("job.operation", "paint"),
            ("job.phase", "running"), ("job.progress", 99), ("job.progress", True), ("job.terminal", False),
            ("job.result.type", "video"), ("job.result.url", "/api/media/other.png"),
            ("job.billing.chargedTokens", True), ("job.billing.chargedTokens", 2),
            ("job.billing.refunded", True), ("job.result._workerClaim", {"secret": "private-canary"}))
        for field, replacement in mutations:
            with self.subTest(field=field):
                value = copy.deepcopy(valid)
                target = value
                for key in field.split(".")[:-1]:
                    target = target[key]
                target[field.split(".")[-1]] = replacement
                with self.assertRaisesRegex(ProductError, "PHONE_RESULT_MISMATCH"):
                    probe.phone_result(value, started, image)

    def test_graph_binds_modes_without_private_fields(self):
        for mode in probe.MODES:
            with self.subTest(mode=mode):
                job = wire(mode=mode)
                job["private"] = "private-canary"
                value = probe.provider_result(receipt(), receipt([job]), "job-owned-123", mode)
                self.assertEqual(value["graph"]["loadImageCount"], 2 if mode == "faceswap" else 1)
                self.assertEqual(set(value), {"promptId", "clientSha256", "bodySha256", "graph"})
                self.assertNotIn("private-canary", json.dumps(value))
        alternate = wire(mode="faceswap")
        alternate["graph"]["selectedFaceLora"] = probe.FACE_LORAS[1]
        self.assertIsNotNone(probe.provider_result(receipt(), receipt([alternate]), "job-owned-123", "faceswap"))

    def test_wrong_graph_never_passes(self):
        mutations = (("loadImageCount", 1), ("loadImageCount", True), ("allInputsOwned", False),
            ("inputChainConnected", False), ("loraCount", 0), ("allLorasAllowed", False),
            ("selectedFaceLora", "private-unknown.safetensors"), ("private", "private-canary"))
        for field, replacement in mutations:
            with self.subTest(field=field):
                job = wire(mode="faceswap")
                job["graph"][field] = replacement
                with self.assertRaisesRegex(ProductError, "GRAPH_MISMATCH"):
                    probe.provider_result(receipt(), receipt([job]), "job-owned-123", "faceswap")
        job = wire()
        job["graph"].pop("allInputsOwned")
        with self.assertRaisesRegex(ProductError, "GRAPH_MISMATCH"):
            probe.provider_result(receipt(), receipt([job]), "job-owned-123", "edit")

    def test_provider_replay_and_baseline_mismatch(self):
        old = wire("prior-source", index=99)
        for failure in ("instance", "client", "body", "duplicate", "multiple", "count", "prior_remove", "prior_change"):
            with self.subTest(failure=failure):
                before, after = receipt([old]), receipt([old, wire()])
                jobs = after["provider"]["jobs"]
                if failure == "instance":
                    after["instanceId"] = "d" * 32
                elif failure == "client":
                    jobs[-1]["client_sha256"] = "e" * 64
                elif failure == "body":
                    jobs[-1]["body_sha256"] = jobs[0]["body_sha256"]
                elif failure == "duplicate":
                    jobs[-1]["prompt_id"] = jobs[0]["prompt_id"]
                elif failure == "multiple":
                    jobs.append(wire("unexpected-extra", index=3))
                    after["provider"]["counts"]["accepted"] = 3
                elif failure == "count":
                    after["provider"]["counts"]["accepted"] = 3
                elif failure == "prior_remove":
                    jobs.pop(0)
                    after["provider"]["counts"]["accepted"] = 1
                else:
                    jobs[0]["state"] = "held"
                with self.assertRaises(ProductError):
                    probe.provider_result(before, after, "job-owned-123", "edit")

    def test_recorder_deadline_and_graph_refresh(self):
        callback = Mock(return_value=receipt())
        with patch.object(probe.time, "monotonic", side_effect=[0, 0, 0, 1, 1, 5]), patch.object(probe.time, "sleep"):
            with self.assertRaisesRegex(ProductError, "RECEIPT_TIMEOUT"):
                probe.wait_provider(receipt(), callback, "job-owned-123", "edit")
        self.assertEqual(callback.call_count, 2)
        partial = wire()
        partial.pop("graph")
        callback = Mock(side_effect=[receipt([partial]), receipt([wire()])])
        with patch.object(probe.time, "monotonic", return_value=1), patch.object(probe.time, "sleep"):
            result, _ = probe.wait_provider(receipt(), callback, "job-owned-123", "edit")
        self.assertTrue(result["graph"]["inputChainConnected"])
        self.assertEqual(callback.call_count, 2)

    def prepared_series(self):
        flow = owned_flow()
        before, _, _ = self.snapshots()
        outsider = copy.deepcopy(before)
        outsider["identity"]["legacy_user_id"] = "web_" + "d" * 32
        snapshots = [before, before, outsider, outsider]
        responses = [SOURCE, {"user": {"id": OWNED_ID}, "features": {"modes": list(probe.PUBLISHED)}}]
        jobs, receipts = [], [receipt()]
        for index, mode in enumerate(probe.MODES, 1):
            _, step, started = self.snapshots()
            after = copy.deepcopy(before)
            after["account"]["token_balance"] -= 1
            after["ledger"]["summary"].update(spentTokens=index, balanceSpentTokens=index, balance=100-index)
            started.update(id=f"job-owned-{index}", mode=mode, status="queued", tokenBalance=100-index)
            charge = step["ledger"]["items"][0]
            charge.update(id=f"charge-{index}", mode=mode)
            after["ledger"]["items"].append(charge)
            image = {"id": f"image-{index}", "url": f"/api/media/result-{index}.png?userId={OWNED_ID}", "mode": mode, "provider": "comfyui"}
            job = {**started, "status": "completed", "progress": 100,
                "resultImageId": image["id"], "resultUrl": image["url"]}
            responses.extend([started, job, image, phone(started, image), job])
            snapshots.extend([before, after, after])
            jobs.append(wire(started["id"], mode, index))
            receipts.append(receipt(jobs))
            before = after
        flow.owner.request.side_effect, flow.account_snapshot.side_effect = responses, snapshots
        return flow, responses, snapshots, Mock(side_effect=receipts)

    def test_admission_fails_before_io(self):
        for failure in ("origin", "source", "project", "client", "flag", "duplicate_clients"):
            with self.subTest(failure=failure):
                flow, attest, callback = owned_flow(), dict(ATTESTATION), Mock(return_value=receipt())
                if failure in {"origin", "source", "project"}:
                    attest[{"origin": "origin", "source": "sourceSha", "project": "project"}[failure]] = "invalid"
                elif failure == "client":
                    flow.other.origin = "https://example.invalid"
                elif failure == "flag":
                    attest["fakeProviderOnly"] = False
                else:
                    flow.other = flow.owner
                with self.assertRaises(ProductError):
                    probe.prove_image_modes(flow, SOURCE, attestation=attest, provider_receipt=callback)
                callback.assert_not_called()
                for client in flow.clients:
                    client.request.assert_not_called()

    def test_uncontrolled_profile_fails_before_http(self):
        flow, callback = owned_flow(), Mock(return_value={"fixture": "ordinary-service"})
        with self.assertRaisesRegex(ProductError, "PROVIDER_PROFILE_REQUIRED"):
            self.run_series(flow, callback)
        flow.owner.request.assert_not_called()

    def test_foreign_input_400_without_charge(self):
        for failure in ("403", "404", "charged"):
            with self.subTest(failure=failure):
                flow, _, snapshots, callback = self.prepared_series()
                if failure == "charged":
                    snapshots[3] = copy.deepcopy(snapshots[2])
                    snapshots[3]["account"]["token_balance"] -= 1
                else:
                    flow.other.request.return_value = {"httpStatus": int(failure)}
                with self.assertRaisesRegex(ProductError, "FOREIGN_INPUT"):
                    self.run_series(flow, callback)
                self.assertEqual(flow.other.request.call_args.kwargs["expected"], (400,))
                self.assertEqual(flow.owner.request.call_count, 2)

    def test_bootstrap_preserves_account_and_features(self):
        for failure in ("account", "mode", "duplicate", "query"):
            with self.subTest(failure=failure):
                flow, responses, snapshots, callback = self.prepared_series()
                if failure == "account":
                    snapshots[1] = copy.deepcopy(snapshots[0])
                    snapshots[1]["account"]["token_balance"] = 0
                elif failure == "mode":
                    responses[1]["features"]["modes"].remove("paint")
                elif failure == "duplicate":
                    responses[1]["features"]["modes"].append("paint")
                changed = {"url": SOURCE["url"].replace("a" * 32, "d" * 32)} if failure == "query" else {}
                with patch.dict(SOURCE, changed):
                    with self.assertRaisesRegex(ProductError, "BOOTSTRAP_IDENTITY|PUBLISHED_MODES|SOURCE_OWNER_QUERY"):
                        self.run_series(flow, callback)
                flow.other.request.assert_not_called()

    def test_three_modes_checkpoint_wire_proof(self):
        flow, _, _, callback = self.prepared_series()
        checkpoints = []
        result = self.run_series(flow, callback, checkpoints.append)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual([result["modes"][mode]["provider"]["graph"]["loadImageCount"] for mode in probe.MODES], [1, 1, 2])
        self.assertEqual(checkpoints[0]["modes"]["edit"]["status"], "RUNNING")
        self.assertEqual(checkpoints[1]["modes"]["edit"]["status"], "PASS")
        self.assertNotIn("paint", checkpoints[1]["modes"])
        self.assertIs(result["modelExecution"], False)

    def test_failure_preserves_prior_modes(self):
        flow, responses, _, callback = self.prepared_series()
        responses[10]["job"]["result"]["url"] = "/api/media/unrelated.png"
        checkpoints = []
        with self.assertRaisesRegex(ProductError, "PHONE_RESULT_MISMATCH"):
            self.run_series(flow, callback, checkpoints.append)
        final = checkpoints[-1]
        self.assertEqual(final["status"], "FAIL")
        self.assertEqual(final["modes"]["edit"]["status"], "PASS")
        self.assertEqual(final["modes"]["paint"]["status"], "FAIL")
        self.assertEqual(final["modes"]["paint"]["jobId"], "job-owned-2")
        self.assertNotIn("faceswap", final["modes"])

    def test_checkpoint_and_http_errors_are_redacted(self):
        for failure in ("request", "checkpoint"):
            flow, responses, _, callback = self.prepared_series()
            checkpoints = []
            if failure == "request":
                responses[1] = RuntimeError("private-canary /private/path token")
                checkpoint = checkpoints.append
            else:
                checkpoint = Mock(side_effect=OSError("private-canary /private/path token"))
            with self.assertRaises(ProductError) as caught:
                self.run_series(flow, callback, checkpoint)
            self.assertNotIn("private-canary", str(caught.exception) + json.dumps(checkpoints))
            self.assertIn("CHECKPOINT_FAILED" if failure == "checkpoint" else "OPERATION_FAILED", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
