"""Explicit, bounded acceptance-only entrypoint using the existing Comfy fixture."""
from __future__ import annotations

import asyncio
from dataclasses import replace
from contextlib import nullcontext
import http.client
import json
import os
from pathlib import Path
import signal
import threading
import time
import uuid

try:
    from tools.docker_shadow_provider import ControlledProvider
except ModuleNotFoundError:
    from docker_shadow_provider import ControlledProvider

MARKER = "controlled-comfyui-v1"
D3_MARKER = "controlled-chat-video-v1"
AUDIO_MARKER = "controlled-audio-v1"
PROVIDER_PORT = 48991
CONTROL_PORT = 48992
LIFETIME_SECONDS = 300
RECEIPT = Path("/tmp/izo-shadow-provider-receipt.json")
DISABLED_ENDPOINTS = ("OLLAMA_BASE_URL", "QWEN_ASR_BASE_URL", "OPENROUTER_BASE_URL",
                      "MAX_API_BASE_URL", "LOCAL_LTX_COMFYUI_BASE_URL")
SECRET_KEYS = ("TELEGRAM_BOT_TOKEN", "MAX_BOT_TOKEN", "OPENROUTER_API_KEY",
               "PAYMENT_PROVIDER_TOKEN", "YOOKASSA_SECRET_KEY", "SMTP_PASSWORD",
               "SMTP_TOKEN", "UNISENDER_API_KEY", "VK_ACCESS_TOKEN")


def validate_environment(environment: dict) -> None:
    """Refuse accidental provider fallback or a non-test application profile."""
    marker = environment.get("IZO_SHADOW_FIXTURE")
    is_d3 = marker == D3_MARKER
    is_audio = marker == AUDIO_MARKER
    required = {"IZO_SHADOW_FIXTURE": D3_MARKER if is_d3 else AUDIO_MARKER if is_audio else MARKER, "APP_ENV": "test", "ENV": "test",
                "MODE": "test", "BOT_MODE": "disabled", "MAX_UPDATES_MODE": "disabled",
                "COMFYUI_BASE_URL": f"http://127.0.0.1:{PROVIDER_PORT}",
                "COMFYUI_MOCK_FALLBACK": "false"}
    if any(environment.get(key) != value for key, value in required.items()):
        raise RuntimeError("SHADOW_FIXTURE_PROFILE_REQUIRED")
    if is_d3:
        required.update(LOCAL_LTX_ENABLED="true",
                        LOCAL_LTX_WORKFLOW_API_PATH="/opt/izo/backend/workflows/ltx23_t2v_api.json")
        if any(environment.get(key) != value for key, value in required.items()):
            raise RuntimeError("SHADOW_FIXTURE_PROFILE_REQUIRED")
    enabled = {"OLLAMA_BASE_URL", "LOCAL_LTX_COMFYUI_BASE_URL"} if is_d3 else set()
    if any(environment.get(key) != (f"http://127.0.0.1:{PROVIDER_PORT}" if key in enabled else "http://127.0.0.1:1")
           for key in DISABLED_ENDPOINTS):
        raise RuntimeError("SHADOW_FIXTURE_EXTERNAL_ENDPOINT_FORBIDDEN")
    if is_audio and (environment.get("IZO_PROCESS_ROLE") != "server"
                     or any(environment.get(key, "") for key in ("IZO_PHONE_TTS_HTTP_URL", "IZO_PHONE_TTS_HTTP_TOKEN_FILE"))):
        raise RuntimeError("SHADOW_FIXTURE_AUDIO_STARTUP_REQUIRED")
    if any(environment.get(key, "") for key in SECRET_KEYS):
        raise RuntimeError("SHADOW_FIXTURE_EXTERNAL_CREDENTIAL_FORBIDDEN")


class FixtureControls:
    """Three fixed POSIX commands; the provider capability stays in this process."""

    def __init__(self, provider):
        self.provider = provider
        self.instance_id = uuid.uuid4().hex
        self.events = {name: threading.Event() for name in ("hold", "release", "duplicate")}
        self._lock = threading.Lock()
        self.control = {"sequence": 0, "action": None, "status": "IDLE"}
        self.race = {"status": "NOT_RUN", "active": False, "additionalConsumers": 0}
        self.loop = self.application = self.task = None
        self._handlers = {}

    def install(self):
        for name, number in (("hold", signal.SIGUSR1), ("release", signal.SIGUSR2),
                             ("duplicate", signal.SIGWINCH)):
            self._handlers[number] = signal.getsignal(number)
            signal.signal(number, lambda _number, _frame, event=self.events[name]: event.set())

    async def bind(self, application):
        self.application, self.loop = application, asyncio.get_running_loop()

    def exchange(self, path, body):
        connection = http.client.HTTPConnection("127.0.0.1", CONTROL_PORT, timeout=2)
        try:
            connection.request("POST", path, json.dumps(body), headers={
                "Content-Type": "application/json", "Authorization": "Bearer " + self.provider.control_token})
            response = connection.getresponse()
            raw = response.read(4097)
            if response.status != 200 or len(raw) > 4096:
                raise RuntimeError("SHADOW_FIXTURE_CONTROL_REJECTED")
            result = json.loads(raw)
            if not isinstance(result, dict):
                raise RuntimeError("SHADOW_FIXTURE_CONTROL_REJECTED")
            return result
        finally:
            connection.close()

    async def duplicate(self):
        app = self.application
        active = {"queued", "running", "uploading", "sent_to_comfyui", "sent_to_openrouter"}
        candidates = [job for job in app.jobs.values() if job.get("status") in active]
        if app.worker_started is not True or len(candidates) != 1 or self.task is not None:
            raise RuntimeError("SHADOW_FIXTURE_DUPLICATE_NOT_ADMITTED")
        job = candidates[0]
        if (job.get("status") != "sent_to_comfyui" or job.get("provider") != "comfyui"
                or job.get("mode") != "text_to_image" or not isinstance(job.get("request"), dict)):
            raise RuntimeError("SHADOW_FIXTURE_DUPLICATE_NOT_ADMITTED")
        if not app.queue.empty():
            raise RuntimeError("SHADOW_FIXTURE_DUPLICATE_NOT_ADMITTED")
        job_id, controls = job["id"], self

        class ObservedQueue:
            async def get(self):
                value = await app.queue.get()
                if value != job_id:
                    app.queue.task_done()
                    app.queue.put_nowait(value)
                    raise RuntimeError("SHADOW_FIXTURE_FOREIGN_QUEUE_DELIVERY")
                with controls._lock:
                    controls.race["dequeuedJobId"] = value
                return value

            def task_done(self):
                app.queue.task_done()
                with controls._lock:
                    controls.race["completedDeliveries"] = controls.race.get("completedDeliveries", 0) + 1

        # Deliberately duplicate delivery to the real queue/worker in one process.
        # No state, charge, result, provider response or application callback is faked.
        runtime = replace(app._generation_queue_runtime(), queue=ObservedQueue())
        self.task = asyncio.create_task(app.generation_queue.consume_generation_queue(runtime),
                                        name="shadow-extra-consumer")
        timer = self.loop.call_later(15, self.task.cancel)
        with self._lock:
            self.race = {"status": "RUNNING", "active": True, "additionalConsumers": 1,
                         "jobId": job_id, "sameProcess": True, "deadlineSeconds": 15}

        def finished(task):
            timer.cancel()
            failed = not task.cancelled() and task.exception() is not None
            with self._lock:
                self.race.update(status="FAILED" if failed else "STOPPED", active=False)

        self.task.add_done_callback(finished)
        await app.queue.put(job_id)

    def poll(self):
        for action, event in self.events.items():
            if not event.is_set():
                continue
            event.clear()
            status = "ACK"
            try:
                if self.control["sequence"] >= 12:
                    raise RuntimeError("SHADOW_FIXTURE_CONTROL_LIMIT")
                if action == "hold":
                    result = self.exchange("/plan", {"mode": "hold", "hold_seconds": 60})
                    if result.get("planned") != "hold":
                        raise RuntimeError("SHADOW_FIXTURE_CONTROL_REJECTED")
                elif action == "release":
                    held = [job for job in self.provider.receipt()["jobs"] if job["state"] == "held"]
                    if len(held) != 1:
                        raise RuntimeError("SHADOW_FIXTURE_RELEASE_NOT_ADMITTED")
                    result = self.exchange("/release", {"prompt_id": held[0]["prompt_id"]})
                    if result.get("state") != "completed":
                        raise RuntimeError("SHADOW_FIXTURE_CONTROL_REJECTED")
                else:
                    if self.loop is None or not self.loop.is_running():
                        raise RuntimeError("SHADOW_FIXTURE_LOOP_NOT_READY")
                    future = asyncio.run_coroutine_threadsafe(self.duplicate(), self.loop)
                    try:
                        future.result(timeout=2)
                    except BaseException:
                        future.cancel()
                        raise
            except (RuntimeError, OSError, ValueError, TypeError, KeyError, TimeoutError,
                    http.client.HTTPException):
                status = "FAIL"
            with self._lock:
                self.control = {"sequence": self.control["sequence"] + 1,
                                "action": action, "status": status}

    def receipt(self):
        with self._lock:
            value = {"instanceId": self.instance_id, "control": dict(self.control), "race": dict(self.race)}
        dispatcher = getattr(self.application, "generation_dispatcher", None)
        if dispatcher is not None:
            snapshot = dispatcher.snapshot()
            value["generationDispatcher"] = {key: snapshot[key] for key in (
                "role", "localConsumer", "ready", "connectedWorkers", "onlineWorkers", "lastWorkerSeenAt", "lastSuccessAt",
                "lastFailureAt", "claimedJobs", "completedJobs", "expiredLeases", "watchdog") if key in snapshot}
        return value

    def close(self):
        for number, previous in self._handlers.items():
            signal.signal(number, previous)
        if self.task is not None and not self.task.done():
            raise RuntimeError("SHADOW_FIXTURE_CONSUMER_NOT_STOPPED")


def write_receipt(provider: ControlledProvider, path: Path = RECEIPT, *, controls=None) -> None:
    """Only the existing provider's secret-free receipt crosses this boundary."""
    value = provider.receipt()
    marker = AUDIO_MARKER if value.get("audio", {}).get("profile") == AUDIO_MARKER else (
        D3_MARKER if value.get("d3", {}).get("profile") == D3_MARKER else MARKER)
    data = {"fixture": marker, "lifetimeSeconds": LIFETIME_SECONDS, "provider": value}
    if controls is not None:
        data.update(controls.receipt())
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, sort_keys=True) + "\n", encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(path)


def run() -> None:
    validate_environment(dict(os.environ))
    import uvicorn

    provider_type = ControlledProvider
    if os.environ.get("IZO_SHADOW_FIXTURE") == D3_MARKER:
        try:
            from tools.docker_d3_chat_video_provider import ChatVideoProvider
        except ModuleNotFoundError:
            from docker_d3_chat_video_provider import ChatVideoProvider
        provider_type = ChatVideoProvider
    elif os.environ.get("IZO_SHADOW_FIXTURE") == AUDIO_MARKER:
        try:
            from tools.docker_d3_audio_provider import AudioProvider
        except ModuleNotFoundError:
            from docker_d3_audio_provider import AudioProvider
        provider_type = AudioProvider

    server = uvicorn.Server(uvicorn.Config("main:app", host="0.0.0.0", port=8000,
                                         workers=1, log_level="warning"))
    stop = threading.Event()
    failures = []
    with provider_type(bind="127.0.0.1", port=PROVIDER_PORT,
                            control_port=CONTROL_PORT,
                            lifetime_seconds=LIFETIME_SECONDS) as provider:
        audio_context = nullcontext(None)
        if os.environ.get("IZO_SHADOW_FIXTURE") == AUDIO_MARKER:
            try:
                from tools.docker_d3_audio_fixture import audio_environment
            except ModuleNotFoundError:
                from docker_d3_audio_fixture import audio_environment
            audio_context = audio_environment(provider)
        with audio_context as audio_setup:
            import main as application

            controls = FixtureControls(provider)
            controls.install()

            async def bind_controls():
                await controls.bind(application)
                if audio_setup is not None:
                    audio_setup.seed(application)

            application.app.router.add_event_handler("startup", bind_controls)
            write_receipt(provider, controls=controls)
            deadline = time.monotonic() + LIFETIME_SECONDS

            def record() -> None:
                try:
                    while not stop.wait(.2):
                        controls.poll()
                        write_receipt(provider, controls=controls)
                        if time.monotonic() >= deadline:
                            server.should_exit = True
                            return
                except (OSError, ValueError, TypeError):
                    failures.append("SHADOW_FIXTURE_RECEIPT_FAILED")
                    server.should_exit = True

            recorder = threading.Thread(target=record, name="shadow-fixture-receipt", daemon=True)
            recorder.start()
            try:
                server.run()
            finally:
                stop.set()
                recorder.join(timeout=2)
                controls.close()
                write_receipt(provider, controls=controls)
            if recorder.is_alive() or failures:
                raise RuntimeError("SHADOW_FIXTURE_RECEIPT_FAILED")


if __name__ == "__main__":
    try:
        run()
    except (RuntimeError, OSError, ValueError, TypeError):
        print("SHADOW_FIXTURE_FAILED", flush=True)
        raise SystemExit(1) from None
