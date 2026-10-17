"""Safety checks for opting a real backend into the bounded wire fixture."""
import asyncio
from dataclasses import dataclass
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from tools.docker_shadow_fixture import (DISABLED_ENDPOINTS, MARKER, SECRET_KEYS, FixtureControls,
                                         validate_environment, write_receipt)


def safe_environment():
    return {"IZO_SHADOW_FIXTURE": MARKER, "APP_ENV": "test", "ENV": "test",
            "MODE": "test", "BOT_MODE": "disabled", "MAX_UPDATES_MODE": "disabled",
            "COMFYUI_BASE_URL": "http://127.0.0.1:48991", "COMFYUI_MOCK_FALLBACK": "false",
            **{key: "http://127.0.0.1:1" for key in DISABLED_ENDPOINTS},
            **{key: "" for key in SECRET_KEYS}}


class FixtureEntrypointTests(unittest.TestCase):
    def test_requires_explicit_safe_profile(self):
        safe = safe_environment()
        validate_environment(safe)
        for key, value in (("IZO_SHADOW_FIXTURE", ""), ("APP_ENV", "production"),
                           ("COMFYUI_MOCK_FALLBACK", "true"), ("BOT_MODE", "polling")):
            with self.subTest(key=key), self.assertRaisesRegex(RuntimeError, "PROFILE_REQUIRED"):
                validate_environment({**safe, key: value})

    def test_real_endpoint_or_credentials_are_rejected(self):
        for key in DISABLED_ENDPOINTS:
            with self.subTest(key=key), self.assertRaisesRegex(RuntimeError, "ENDPOINT_FORBIDDEN"):
                validate_environment({**safe_environment(), key: "https://example.invalid"})
        for key in SECRET_KEYS:
            with self.subTest(key=key), self.assertRaisesRegex(RuntimeError, "CREDENTIAL_FORBIDDEN"):
                validate_environment({**safe_environment(), key: "unit-fixture-value"})

    def test_atomic_receipt_does_not_serialize_provider_object(self):
        class Provider:
            control_token = "private-control-capability"

            def receipt(self):
                return {"counts": {"accepted": 2}, "jobs": [], "model_execution": False}

        with tempfile.TemporaryDirectory(prefix="izo-fixture-test-") as folder:
            path = Path(folder) / "receipt.json"
            write_receipt(Provider(), path)
            first = path.read_text(encoding="utf-8")
            self.assertNotIn(Provider.control_token, first)
            self.assertEqual(json.loads(first)["provider"]["counts"]["accepted"], 2)
            write_receipt(Provider(), path)
            self.assertEqual(path.read_text(encoding="utf-8"), first)
            self.assertFalse(path.with_suffix(".tmp").exists())


def provider():
    return SimpleNamespace(control_token="private-control-capability", receipt=lambda: {
        "counts": {"accepted": 1}, "jobs": [{"prompt_id": "prompt-fixture", "state": "held"}],
        "model_execution": False})


class FixtureControlTests(unittest.TestCase):
    def test_signal_handler_only_queues_work_and_poll_records_ack(self):
        controls, handlers = FixtureControls(provider()), {}
        controls.exchange = Mock(return_value={"planned": "hold"})
        with patch("tools.docker_shadow_fixture.signal.getsignal", return_value=0), patch(
                "tools.docker_shadow_fixture.signal.signal", side_effect=lambda number, handler: handlers.update({number: handler})), patch.multiple(
                "tools.docker_shadow_fixture.signal", SIGUSR1=10, SIGUSR2=12, SIGWINCH=28, create=True):
            controls.install()
            handlers[10](10, None)
            controls.exchange.assert_not_called()
            controls.poll()
            controls.exchange.assert_called_once_with("/plan", {"mode": "hold", "hold_seconds": 60})
            self.assertEqual(controls.receipt()["control"], {"sequence": 1, "action": "hold", "status": "ACK"})
            controls.close()
            self.assertEqual(set(handlers.values()), {0})

    def test_release_requires_one_owned_held_prompt(self):
        controls = FixtureControls(provider())
        controls.exchange = Mock(return_value={"state": "completed"})
        controls.events["release"].set()
        controls.poll()
        controls.exchange.assert_called_once_with("/release", {"prompt_id": "prompt-fixture"})
        self.assertEqual(controls.receipt()["control"]["status"], "ACK")
        controls.provider.receipt = lambda: {"jobs": []}
        controls.events["release"].set()
        controls.poll()
        self.assertEqual(controls.receipt()["control"]["status"], "FAIL")
        self.assertEqual(controls.exchange.call_count, 1)

    def test_capability_only_used_for_loopback_request_and_never_receipt(self):
        controls = FixtureControls(provider())
        connection = Mock()
        connection.getresponse.return_value = SimpleNamespace(status=200, read=lambda _limit: b'{"planned":"hold"}')
        with patch("tools.docker_shadow_fixture.http.client.HTTPConnection", return_value=connection) as factory:
            controls.events["hold"].set()
            controls.poll()
        factory.assert_called_once_with("127.0.0.1", 48992, timeout=2)
        self.assertEqual(connection.request.call_args.kwargs["headers"]["Authorization"],
                         "Bearer " + controls.provider.control_token)
        connection.close.assert_called_once()
        with tempfile.TemporaryDirectory(prefix="izo-fixture-control-") as folder:
            target = Path(folder) / "receipt.json"
            write_receipt(controls.provider, target, controls=controls)
            raw = target.read_text()
            self.assertNotIn(controls.provider.control_token, raw)
            self.assertEqual(json.loads(raw)["instanceId"], controls.instance_id)

    def test_rejected_redirect_and_large_response_never_ack(self):
        for status, payload in ((302, b'{}'), (200, b'X' * 4097), (200, b'[]')):
            with self.subTest(status=status, size=len(payload)):
                controls, connection = FixtureControls(provider()), Mock()
                connection.getresponse.return_value = SimpleNamespace(status=status, read=lambda _limit: payload)
                with patch("tools.docker_shadow_fixture.http.client.HTTPConnection", return_value=connection):
                    controls.events["hold"].set()
                    controls.poll()
                self.assertEqual(controls.receipt()["control"]["status"], "FAIL")

    def test_control_bound_and_unbound_loop_fail_without_submission(self):
        controls = FixtureControls(provider())
        controls.exchange = Mock()
        controls.control["sequence"] = 12
        controls.events["hold"].set()
        controls.poll()
        self.assertEqual(controls.receipt()["control"]["status"], "FAIL")
        controls.exchange.assert_not_called()
        controls = FixtureControls(provider())
        controls.events["duplicate"].set()
        controls.poll()
        self.assertEqual(controls.receipt()["control"]["status"], "FAIL")


class FixtureConsumerTests(unittest.IsolatedAsyncioTestCase):
    async def test_duplicate_taps_existing_queue_and_keeps_worker_callback(self):
        @dataclass(frozen=True)
        class Runtime:
            queue: object
            process_job: object

        queue, seen = asyncio.Queue(), []
        executed = asyncio.Event()

        async def process(job_id):
            seen.append(job_id)
            executed.set()

        async def consume(runtime):
            self.assertIs(runtime.process_job, process)
            while True:
                job_id = await runtime.queue.get()
                await runtime.process_job(job_id)
                runtime.queue.task_done()

        app = SimpleNamespace(worker_started=True, queue=queue,
            jobs={"job-fixture": {"id": "job-fixture", "status": "sent_to_comfyui",
                  "provider": "comfyui", "mode": "text_to_image", "request": {}}},
            _generation_queue_runtime=lambda: Runtime(queue, process),
            generation_queue=SimpleNamespace(consume_generation_queue=consume))
        controls = FixtureControls(provider())
        await controls.bind(app)
        await controls.duplicate()
        await asyncio.wait_for(executed.wait(), 1)
        self.assertEqual(seen, ["job-fixture"])
        self.assertEqual(controls.receipt()["race"]["dequeuedJobId"], "job-fixture")
        self.assertEqual(controls.receipt()["race"]["completedDeliveries"], 1)
        with self.assertRaisesRegex(RuntimeError, "NOT_ADMITTED"):
            await controls.duplicate()
        controls.task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await controls.task
        await asyncio.sleep(0)
        self.assertEqual(controls.receipt()["race"]["status"], "STOPPED")
        self.assertFalse(controls.receipt()["race"]["active"])
        controls.close()

    async def test_duplicate_rejects_other_mode_or_more_than_one_active_job(self):
        controls = FixtureControls(provider())
        app = SimpleNamespace(worker_started=True, jobs={"job-a": {
            "id": "job-a", "status": "sent_to_comfyui", "provider": "comfyui", "mode": "paint", "request": {}}})
        await controls.bind(app)
        for jobs in (app.jobs, {**app.jobs, "job-b": {"status": "queued"}}):
            app.jobs = jobs
            with self.assertRaisesRegex(RuntimeError, "NOT_ADMITTED"):
                await controls.duplicate()
        self.assertIsNone(controls.task)

    async def test_foreign_queue_item_is_never_processed_or_lost(self):
        @dataclass(frozen=True)
        class Runtime:
            queue: object

        queue, processed = asyncio.Queue(), []

        async def consume(runtime):
            processed.append(await runtime.queue.get())

        app = SimpleNamespace(worker_started=True, queue=queue,
            jobs={"job-fixture": {"id": "job-fixture", "status": "sent_to_comfyui",
                "provider": "comfyui", "mode": "text_to_image", "request": {}}},
            _generation_queue_runtime=lambda: Runtime(queue),
            generation_queue=SimpleNamespace(consume_generation_queue=consume))
        controls = FixtureControls(provider())
        await controls.bind(app)
        queue.put_nowait("foreign-job")
        with self.assertRaisesRegex(RuntimeError, "NOT_ADMITTED"):
            await controls.duplicate()
        self.assertIsNone(controls.task)
        self.assertEqual(queue.get_nowait(), "foreign-job")
        queue.task_done()
        await controls.duplicate()
        self.assertEqual(queue.get_nowait(), "job-fixture")
        queue.task_done()
        queue.put_nowait("foreign-job")
        queue.put_nowait("job-fixture")
        with self.assertRaisesRegex(RuntimeError, "FOREIGN_QUEUE_DELIVERY"):
            await controls.task
        await asyncio.sleep(0)
        self.assertEqual(processed, [])
        self.assertEqual(controls.receipt()["race"]["status"], "FAILED")
        self.assertFalse(controls.receipt()["race"]["active"])
        self.assertEqual({queue.get_nowait(), queue.get_nowait()}, {"foreign-job", "job-fixture"})
        queue.task_done()
        queue.task_done()
        await asyncio.wait_for(queue.join(), 1)
        controls.close()


if __name__ == "__main__":
    unittest.main()
