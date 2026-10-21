"""Compatibility composition and explicit generation process-role lifecycle."""
from __future__ import annotations

from contextlib import asynccontextmanager
from functools import partial
import asyncio
import os

from . import generation_admin_probe, generation_queue, generation_worker, generation_worker_persistence
from .generation_dispatch import DispatchRuntime, GenerationDispatcher, acquire_database_ownership
from .generation_leases import DurableWakeQueue
from ..integrations.generation_transport import executor_bound


def role(environment):
    value = environment.get("IZO_PROCESS_ROLE", "combined")
    if value not in {"combined", "server", "worker"}:
        raise RuntimeError("GENERATION_PROCESS_ROLE_INVALID")
    return value


def api_role(environment):
    selected = role(environment)
    if selected == "worker":
        raise RuntimeError("GENERATION_WORKER_MUST_USE_EXECUTOR_ENTRYPOINT")
    return selected


def configure_api(host):
    selected = api_role(host.os.environ)
    if selected == "server":
        if host.COMFYUI_MOCK_FALLBACK:
            raise RuntimeError("GENERATION_SERVER_MOCK_FALLBACK_FORBIDDEN")
        host.queue = DurableWakeQueue(host.db)
    elif isinstance(host.queue, DurableWakeQueue):
        host.queue = host.asyncio.Queue()


def require_executor(environment):
    if role(environment) == "server" and not executor_bound():
        raise RuntimeError("GENERATION_PROVIDER_EXECUTOR_REQUIRED")


def worker_ready(host):
    if role(host.os.environ) != "server":
        return True
    dispatcher = host.generation_dispatcher
    return dispatcher is not None and dispatcher.snapshot().get("ready") is True


def _dispatcher(host):
    if host.generation_dispatcher is None:
        host.generation_dispatcher = GenerationDispatcher(
            host.os.environ.get("IZO_WORKER_SOCKET", "/home/izo/worker/generation.sock"),
            DispatchRuntime(connect=host.db, parse_request=lambda data: host.GenerateRequest(**data),
                            make_runtime=host._generation_worker_runtime, jobs=host.jobs,
                            refund_job=host.refund_generation_tokens,
                            process_job=partial(generation_admin_probe.process_job, host),
                            drain_storage=lambda: _drain_storage(host)),
            database_path=host.DB_PATH,
        )
    return host.generation_dispatcher


@asynccontextmanager
async def prepared_api(host):
    configure_api(host)
    body_started = False
    try:
        if role(host.os.environ) == "server":
            await _dispatcher(host).prepare()
        elif os.name == "posix" and getattr(host, "generation_database_owner", None) is None:
            host.generation_database_owner = acquire_database_ownership(host.DB_PATH)
            host.generation_close_task = None
        body_started = True
        yield
    except BaseException:
        try:
            if body_started:
                await host.shutdown()
        finally:
            await stop(host)
        raise


def worker_runtime(host):
    persistence = generation_worker_persistence.WorkerPersistence(
        connect=host.db, refund=host.refund_generation_tokens,
        finalize_billing=host.finalize_openrouter_billing_snapshot,
        reconcile_charge=host.reconcile_openrouter_token_charge, quota=host.gallery_quota_for_user,
        evict=host.evict_gallery_images_for_new_save, persist_image=host.persist_image,
        persist_sources=host.persist_image_sources, images=host.images,
        optimize=host.optimize_gallery_storage_for_user, read_job=host.get_persisted_job_response,
        now_iso=lambda: host.datetime.now(host.timezone.utc).isoformat(),
    )
    return generation_worker.GenerationWorkerRuntime(
        comfyui_mock_fallback=host.COMFYUI_MOCK_FALLBACK, persist_job=host.persist_job,
        send_to_comfyui=host.send_to_comfyui, send_to_openrouter=host.send_to_openrouter,
        mock_image=host.mock_image, public_url=host.public_url,
        new_image_id=lambda: f"img_{host.uuid.uuid4().hex[:12]}",
        now_iso=lambda: host.datetime.now(host.timezone.utc).isoformat(),
        perf_counter=host.time.perf_counter, sleep=host.asyncio.sleep, **persistence.callbacks(),
    )


def queue_runtime(host):
    return generation_queue.GenerationQueueRuntime(
        queue=host.queue, jobs=host.jobs,
        parse_request=lambda payload: host.GenerateRequest(**payload),
        perf_counter=host.time.perf_counter,
        build_worker_runtime=host._generation_worker_runtime,
        process_job=generation_worker.process_generation_job,
        allow_consume=role(host.os.environ) == "combined",
    )


async def start(host):
    if role(host.os.environ) == "combined":
        return generation_queue.start_generation_consumer_once(
            already_started=host.worker_started,
            create_task=host.asyncio.create_task,
            consumer=host.worker,
            on_task=(lambda task: setattr(host, "generation_consumer_task", task)) if os.name == "posix" else None,
        )
    await _dispatcher(host).start()
    return False


def start_storage_maintenance(host):
    host.generation_storage_task = asyncio.create_task(asyncio.to_thread(host.optimize_existing_gallery_storage))


async def _drain_storage(host):
    task = getattr(host, "generation_storage_task", None)
    if task is not None:
        try:
            await generation_worker_persistence.drain_owned_task(task)
        except Exception as error:
            print(f"startup storage optimization deferred: {type(error).__name__}")
        finally:
            host.generation_storage_task = None


async def stop(host):
    if host.generation_dispatcher is not None:
        await host.generation_dispatcher.close()
        host.generation_dispatcher = None
    elif role(host.os.environ) == "combined" and os.name == "posix":
        if getattr(host, "generation_close_task", None) is None:
            host.generation_close_task = asyncio.create_task(_close_combined(host), name="generation-combined-close")
        await generation_worker_persistence.drain_owned_task(host.generation_close_task)
    else:
        await _drain_storage(host)


async def _close_combined(host):
    try:
        consumer = getattr(host, "generation_consumer_task", None)
        if consumer is not None:
            consumer.cancel()
            await asyncio.gather(consumer, return_exceptions=True)
            host.generation_consumer_task = None
            host.worker_started = False
        await _drain_storage(host)
    finally:
        owner = getattr(host, "generation_database_owner", None)
        if owner is not None:
            owner.close()
            host.generation_database_owner = None
