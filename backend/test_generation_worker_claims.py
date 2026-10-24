"""Worker, recovery, accounting and storage SQL together, with held fake providers."""
from __future__ import annotations

import __future__
import ast
import asyncio
from contextlib import closing, redirect_stdout
from copy import deepcopy
from dataclasses import replace
from io import StringIO
import json
from pathlib import Path
from types import SimpleNamespace
import unittest

from app.services import generation_accounting as accounting, generation_queue as queue_service
from app.services import generation_bootstrap
from app.services import generation_recovery as recovery
from app.services import generation_worker
from app.services.generation_worker import process_generation_job
from app.services.generation_worker_persistence import WorkerPersistence, cancel_job
from app.storage.source_graph import SourcePersistenceRuntime, SourceTreeRuntime, persist_image_source_rows
from test_generation_claims import ClaimDatabase, NOW
from test_services_generation_worker_module import Harness, request


MAIN = ast.parse(Path(__file__).with_name("main.py").read_text(encoding="utf-8"))


class DatabaseHarness(Harness):
    def __init__(self, case):
        super().__init__()
        self.case, self.cache, self.optimize_calls = case, {}, []
        self.reject_completed = False
        self.optimize_error = None
        namespace = {"json": json, "db": case.connect,
            "SourceTreeRuntime": SourceTreeRuntime, "SourcePersistenceRuntime": SourcePersistenceRuntime,
            "safe_json_load": lambda value: json.loads(value or "{}"),
            "_source_role_label": lambda role, _slot, _mode=None: role or "base",
            "_save_source_thumb": self.source_thumb,
            "gallery_image_id_from_media_url": lambda *_args: None,
            "public_url": lambda path, owner: f"/api/media/{owner}/{path.name}",
            "media_filename_from_url": lambda _value: None, "_delete_media_rel": lambda _name: None,
            "gallery_quota_for_user": self.quota,
            "_generation_source_inputs": lambda _req: [{"value": "owned-input", "slot": 1, "role": "base"}],
            "storage_persist_image_source_rows": persist_image_source_rows}
        nodes = [node for node in MAIN.body if isinstance(node, ast.FunctionDef)
                 and node.name in {"persist_image", "persist_image_sources"}]
        if len(nodes) != 2:
            raise AssertionError("real main persistence functions missing")
        exec(compile(ast.Module(body=nodes, type_ignores=[]), "main.py", "exec",
                     flags=__future__.annotations.compiler_flag), namespace)
        self.storage = WorkerPersistence(
            connect=case.connect, refund=accounting.refund_generation_tokens,
            finalize_billing=lambda snapshot, _cost: {**snapshot, "actualTokens": 3},
            reconcile_charge=accounting.reconcile_openrouter_token_charge, quota=self.quota,
            evict=lambda *_args: 0, persist_image=namespace["persist_image"],
            persist_sources=namespace["persist_image_sources"], images=self.cache,
            optimize=self.optimize, read_job=case.read_job, now_iso=lambda: NOW,
        )

    def source_thumb(self, _source, image_id, slot):
        path = self.case.path.parent / f"{image_id}-{slot}.webp"
        path.write_bytes(b"owned source fixture")
        return path, 1, 1, path.stat().st_size

    def quota(self, conn, _user, user_id):
        count = conn.execute("SELECT count(*) FROM images WHERE user_id=?", (user_id,)).fetchone()[0]
        return {"gallery_full": False, "gallery_used": count, "gallery_slots": 20}

    def persist_job(self, job, payload):
        if self.reject_completed and job["status"] == "completed":
            raise RuntimeError("terminal row write failed")
        self.case.persist(job, payload)

    def optimize(self, user_id, *, limit):
        with closing(self.case.open()) as conn:
            self.optimize_calls.append((user_id, limit, conn.execute("SELECT status FROM jobs").fetchone()[0]))
        if self.optimize_error:
            raise self.optimize_error

    def runtime(self):
        return replace(super().runtime(), **self.storage.callbacks())


class WorkerClaimIntegrationTests(ClaimDatabase, unittest.TestCase):
    def financial(self, owner="user_1"):
        with closing(self.open()) as conn:
            user = dict(conn.execute("SELECT * FROM users WHERE id=?", (owner,)).fetchone())
            reasons = [row[0] for row in conn.execute("SELECT reason FROM token_ledger WHERE user_id=?", (owner,))]
            return user, reasons

    def execute(self, job, harness):
        asyncio.run(process_generation_job(job["id"], job, request(provider=job["provider"]),
                                          harness.runtime(), started_at=10.0))

    def test_two_consumers_of_same_durable_job_call_provider_and_save_once(self):
        job = self.seed(charge=7)
        harness = DatabaseHarness(self)
        async def scenario():
            accepted, release = asyncio.Event(), asyncio.Event()
            calls = []
            async def provider(_payload, value):
                calls.append(value["id"])
                accepted.set()
                await release.wait()
                return harness.comfy_result
            runtime = replace(harness.runtime(), send_to_comfyui=provider)
            first = asyncio.create_task(process_generation_job(job["id"], job, request(), runtime, started_at=10.0))
            await asyncio.wait_for(accepted.wait(), 1)
            second_job = deepcopy(job)
            await process_generation_job(job["id"], second_job, request(), runtime, started_at=10.0)
            release.set()
            await asyncio.wait_for(first, 1)
            self.assertEqual(calls, [job["id"]])
        asyncio.run(scenario())
        self.assertEqual(self.counts(), {"images": 1, "image_sources": 1, "token_ledger": 1})
        self.assertEqual(self.state()["status"], "completed")
        self.assertEqual(len(harness.cache), 1)

    def test_duplicate_consumer_sharing_dict_preserves_active_provider_metadata(self):
        job = self.seed(provider="openrouter", charge=7)
        harness = DatabaseHarness(self)
        metadata = {"model": "owned-model", "requestedSize": "704x960"}
        async def scenario():
            accepted, release = asyncio.Event(), asyncio.Event()
            calls = []
            async def held(payload, active):
                active["openrouterRequest"] = metadata.copy()
                self.persist(active, payload)
                calls.append(active["id"])
                accepted.set()
                await release.wait()
                return harness.openrouter_result
            runtime = replace(harness.runtime(), send_to_openrouter=held)
            first = asyncio.create_task(process_generation_job(job["id"], job,
                request(provider="openrouter"), runtime, started_at=10.0))
            await asyncio.wait_for(accepted.wait(), 1)
            try:
                await process_generation_job(job["id"], job, request(provider="openrouter"),
                                             runtime, started_at=10.0)
                self.assertEqual(job.get("openrouterRequest"), metadata)
            finally:
                release.set()
                await asyncio.wait_for(first, 1)
            self.assertEqual(calls, [job["id"]])
        asyncio.run(scenario())
        with closing(self.open()) as conn:
            saved = json.loads(conn.execute("SELECT settings_json FROM images").fetchone()[0])
            stored = json.loads(conn.execute("SELECT settings_json FROM jobs").fetchone()[0])
        self.assertEqual(saved["openrouterRequest"], metadata)
        self.assertEqual(stored["openrouterRequest"], metadata)
        self.assertEqual(self.counts()["images"], 1)

    def test_late_provider_return_cannot_save_or_adjust_after_durable_cancellation(self):
        for provider_name in ("comfyui", "openrouter"):
            with self.subTest(provider=provider_name):
                job = self.seed("job_"+provider_name, provider=provider_name, charge=7)
                harness = DatabaseHarness(self)
                async def scenario():
                    accepted, release = asyncio.Event(), asyncio.Event()
                    async def held(_payload, _job):
                        accepted.set()
                        await release.wait()
                        return harness.comfy_result if provider_name == "comfyui" else harness.openrouter_result
                    runtime = replace(harness.runtime(), **{"send_to_"+provider_name: held})
                    worker = asyncio.create_task(process_generation_job(
                        job["id"], job, request(provider=provider_name), runtime, started_at=10.0))
                    await asyncio.wait_for(accepted.wait(), 1)
                    async def interrupted():
                        pass  # Deliberately late provider ignores interrupt; durable fencing must suffice.
                    response = await cancel_job(job["id"], job["userId"], connect=self.connect,
                        jobs={job["id"]: deepcopy(job)}, persist_job=self.persist,
                        refund=accounting.refund_generation_tokens, read_job=self.read_job,
                        interrupt=interrupted, now_iso=NOW)
                    self.assertEqual(response["status"], "cancelled")
                    self.assertNotEqual(job["status"], "cancelled")  # No shared-dict shortcut.
                    release.set()
                    await asyncio.wait_for(worker, 1)
                asyncio.run(scenario())
                self.assertEqual(self.state(job["id"])["status"], "cancelled")
                self.assertEqual(job["status"], "cancelled")
                self.assertEqual(harness.cache, {})
                self.assertEqual(self.counts()["images"], 0)
                self.assertEqual(self.counts()["image_sources"], 0)
                user, reasons = self.financial()
                self.assertEqual(user["token_balance"], 100)
                self.assertNotIn("openrouter_generation_adjustment", reasons)
                with closing(self.open()) as conn:
                    owned = [row["reason"] for row in conn.execute("SELECT * FROM token_ledger")
                             if json.loads(row["meta_json"])["jobId"] == job["id"]]
                self.assertEqual(sorted(owned), ["generation", "generation_refund"])

    def test_terminal_write_failure_rolls_back_image_sources_adjustment_and_cache_before_refund(self):
        job = self.seed(provider="openrouter", charge=7)
        harness = DatabaseHarness(self)
        harness.reject_completed = True
        self.execute(job, harness)
        self.assertEqual(self.state()["status"], "failed")
        self.assertIsNone(self.state()["result_image_id"])
        self.assertIsNone(job.get("resultUrl"))
        self.assertEqual(self.counts(), {"images": 0, "image_sources": 0, "token_ledger": 2})
        self.assertEqual(harness.cache, {})
        user, reasons = self.financial()
        self.assertEqual((user["token_balance"], user["tokens_used"], user["generation_count"]), (100, 0, 0))
        self.assertEqual(sorted(reasons), ["generation", "generation_refund"])

    def test_process_context_loss_runs_actual_recovery_once_and_duplicate_queue_wakes_no_provider(self):
        job = self.seed(charge=7)
        with self.scope(job):
            job.update(status="sent_to_comfyui")
            self.persist(job)
        private_before = json.loads(self.state()["settings_json"])["_workerClaim"]
        for expected_refunds in (1, 0):
            with closing(self.open()) as conn, conn:
                report = recovery.reconcile_stale_generation_jobs(conn, completed_at=NOW,
                    refund_job=accounting.refund_generation_tokens)
            self.assertEqual(report.refunds_created, expected_refunds)
            self.assertEqual((report.checked, report.failed), (expected_refunds, expected_refunds))
        harness = DatabaseHarness(self)
        async def wakes():
            queue = asyncio.Queue()
            await queue.put(job["id"])
            await queue.put(job["id"])
            runtime = queue_service.GenerationQueueRuntime(queue=queue, jobs={job["id"]: job},
                parse_request=lambda value: SimpleNamespace(**value), perf_counter=lambda: 10.0,
                build_worker_runtime=harness.runtime, process_job=process_generation_job)
            consumer = asyncio.create_task(queue_service.consume_generation_queue(runtime))
            try:
                await asyncio.wait_for(queue.join(), 1)
            finally:
                consumer.cancel()
                await asyncio.gather(consumer, return_exceptions=True)
        asyncio.run(wakes())
        self.assertFalse(any(event[0] in {"comfyui", "openrouter"} for event in harness.events))
        self.assertEqual(self.state()["status"], "failed")
        self.assertEqual(json.loads(self.state()["settings_json"])["_workerClaim"], private_before)
        self.assertEqual(self.counts(), {"images": 0, "image_sources": 0, "token_ledger": 2})
        user, reasons = self.financial()
        self.assertEqual((user["token_balance"], user["generation_count"]), (100, 0))
        self.assertEqual(reasons.count("generation_refund"), 1)

    def test_queued_other_user_cancellation_repeats_without_interrupting_active_owner(self):
        active = self.seed(charge=7)
        queued = self.seed("job_2", "user_2", charge=7)
        async def scenario():
            interrupted = []
            async def interrupt():
                interrupted.append(True)
            for _attempt in range(2):
                response = await cancel_job(queued["id"], "user_2", connect=self.connect,
                    jobs={queued["id"]: queued}, persist_job=self.persist,
                    refund=accounting.refund_generation_tokens, read_job=self.read_job,
                    interrupt=interrupt, now_iso=NOW)
                self.assertEqual(response["status"], "cancelled")
            self.assertEqual(interrupted, [])
        with self.scope(active):
            # The API request has its own task context, independent of the worker claim.
            from contextvars import Context
            Context().run(lambda: asyncio.run(scenario()))
            self.assertEqual(self.state()["status"], "running")
        self.assertEqual(self.financial("user_1")[0]["token_balance"], 93)
        user, reasons = self.financial("user_2")
        self.assertEqual(user["token_balance"], 100)
        self.assertEqual(reasons.count("generation_refund"), 1)

    def test_optimization_failure_after_committed_result_cannot_fail_or_refund_job(self):
        job = self.seed(charge=7)
        harness = DatabaseHarness(self)
        harness.optimize_error = RuntimeError("private-storage-detail")
        with redirect_stdout(StringIO()) as output:
            self.execute(job, harness)
        self.assertEqual(harness.optimize_calls, [("user_1", 2, "completed")])
        self.assertEqual(self.state()["status"], "completed")
        self.assertEqual(self.counts(), {"images": 1, "image_sources": 1, "token_ledger": 1})
        self.assertEqual(self.financial()[0]["token_balance"], 93)
        self.assertIn("optimization deferred", output.getvalue())
        self.assertNotIn("private-storage-detail", output.getvalue())

    def test_real_comfyui_function_propagates_claim_loss_without_fallback_or_faceswap_wrap(self):
        node = next(node for node in MAIN.body if isinstance(node, ast.AsyncFunctionDef)
                    and node.name == "send_to_comfyui")
        for mode, failing_submit in (("inpaint", 1), ("inpaint", 2), ("inpaint", 3), ("faceswap", 1)):
            with self.subTest(mode=mode, failing_submit=failing_submit):
                events = []
                async def available():
                    return True
                async def models():
                    return {"loras": []}
                async def fetch(name):
                    events.append(("workflow", name))
                    return {}
                async def upload(_path):
                    return "owned-upload"
                async def submit(_workflow, _job):
                    events.append(("submit",))
                    if sum(event[0] == "submit" for event in events) == failing_submit:
                        raise generation_worker.GenerationClaimLost("GENERATION_CLAIM_LOST")
                    return "prompt", {}, []
                def forbidden(*_args, **_kwargs):
                    self.fail("claim loss reached mock/download output")
                def clone(*, update):
                    return SimpleNamespace(**{**vars(payload), **update})
                payload = request()
                payload.__dict__.update(mode=mode, inputImage1="first", inputImage2="second",
                    maskImage=None, outpaintMask=None, canvas=None, inputImages=[], model_copy=clone)
                namespace = {"generation_worker": generation_worker, "COMFYUI_MOCK_FALLBACK": True,
                    "COMFYUI_NATIVE4B_ONLY": False, "generation_bootstrap": generation_bootstrap,
                    "os": SimpleNamespace(environ={"IZO_PROCESS_ROLE": "combined"}),
                    "COMFYUI_REQUIRED": True, "COMFYUI_FACE_INPUT_MAX_SIDE": 512,
                    "_saved_setting": lambda _name: {}, "wait_for_comfyui_recovery_gate": available,
                    "comfyui_available": available, "effective_face_profile": str, "effective_edit_profile": str,
                    "get_comfyui_models": models, "choose_model": lambda *_args: ("klein9b", "clip", "vae"),
                    "choose_faceswap_lora": lambda *_args: SimpleNamespace(id="face"),
                    "fetch_workflow": fetch, "local_media_path_from_url": lambda value: Path(value) if value else None,
                    "save_data_url": lambda *_args: None, "save_canvas_json": lambda *_args: None,
                    "prepare_comfyui_input_image": lambda path, *_args, **_kwargs: path,
                    "upload_to_comfyui": upload, "patch_mode_nodes": lambda *_args, **_kwargs: None,
                    "submit_workflow": submit, "download_comfyui_image": forbidden, "mock_image": forbidden}
                exec(compile(ast.Module(body=[node], type_ignores=[]), "main.py", "exec",
                    flags=__future__.annotations.compiler_flag), namespace)
                with redirect_stdout(StringIO()), self.assertRaises(generation_worker.GenerationClaimLost):
                    asyncio.run(namespace["send_to_comfyui"](payload, {"id": "job_owned"}))
                self.assertEqual(sum(event[0] == "submit" for event in events), failing_submit)
                self.assertEqual(sum(event[0] == "workflow" for event in events), failing_submit)

    def test_lookup_parse_and_runtime_errors_acknowledge_each_real_queue_item(self):
        async def scenario(which):
            queue = asyncio.Queue()
            await queue.put("job")
            def broken(_value=None):
                raise ValueError("invalid queued request")
            runtime = queue_service.GenerationQueueRuntime(queue=queue,
                jobs={} if which == "lookup" else {"job": {"request": {}}},
                parse_request=broken if which == "parse" else lambda value: value,
                perf_counter=lambda: 0.0, build_worker_runtime=broken, process_job=process_generation_job)
            with self.assertRaises((KeyError, ValueError)):
                await queue_service.consume_generation_queue(runtime)
            await asyncio.wait_for(queue.join(), 1)
        for stage in ("lookup", "parse", "runtime"):
            asyncio.run(scenario(stage))


if __name__ == "__main__":
    unittest.main()
