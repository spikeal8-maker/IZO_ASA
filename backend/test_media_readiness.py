from __future__ import annotations

import asyncio
import errno
import os
import threading
from contextlib import closing
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from fastapi import FastAPI

from app.api.routers.health import HealthDependencies, create_health_router
from app.services import media_readiness as readiness


def test_current_media_probe_preserves_existing_files_and_recovers(tmp_path):
    media = tmp_path / "media"
    media.mkdir()
    sentinel = media / ".izo-readiness-existing"
    sentinel.write_bytes(b"user-owned media must remain intact")
    original = (sentinel.read_bytes(), sentinel.stat().st_mode)
    assert readiness.probe_media_write(media) is None
    assert list(media.iterdir()) == [sentinel]
    hidden = tmp_path / "temporarily-unavailable"
    media.rename(hidden)
    try:
        assert readiness.probe_media_write(media) == "MEDIA_UNAVAILABLE"
        assert not media.exists()
    finally:
        hidden.rename(media)
    assert readiness.probe_media_write(media) is None
    assert (sentinel.read_bytes(), sentinel.stat().st_mode) == original
    assert list(media.iterdir()) == [sentinel]


@pytest.mark.parametrize(("code", "expected"), [
    (errno.EACCES, "MEDIA_NOT_WRITABLE"), (errno.EPERM, "MEDIA_NOT_WRITABLE"),
    (errno.EROFS, "MEDIA_NOT_WRITABLE"), (errno.ENOSPC, "MEDIA_CAPACITY_EXHAUSTED"),
    (getattr(errno, "EDQUOT", errno.ENOSPC), "MEDIA_CAPACITY_EXHAUSTED"), (errno.ENOENT, "MEDIA_UNAVAILABLE"),
    (errno.ENOTDIR, "MEDIA_UNAVAILABLE"), (errno.EIO, "MEDIA_IO_FAILED"),
])
def test_media_errors_have_stable_codes_without_operator_details(tmp_path, monkeypatch, code, expected):
    media = tmp_path / "probe-media"
    media.mkdir()
    def denied(*args, **kwargs):
        raise OSError(code, "private disk diagnostic", str(tmp_path / "private-media"))

    monkeypatch.setattr(readiness.tempfile, "TemporaryFile", denied)
    assert readiness.probe_media_write(media) == expected
    assert not list(media.iterdir())


def test_failed_sync_closes_and_removes_only_the_probe_file(tmp_path, monkeypatch):
    media = tmp_path / "probe-media"
    media.mkdir()
    sentinel = media / "image.png"
    sentinel.write_bytes(b"owned image")
    real_fsync = os.fsync
    observed = []

    def full(fd):
        observed.append(fd)
        assert os.fstat(fd).st_size == 1
        if os.name == "posix":
            assert list(media.iterdir()) == [sentinel]
        raise OSError(errno.ENOSPC, "private volume exhausted", str(tmp_path))

    monkeypatch.setattr(readiness.os, "fsync", full)
    assert readiness.probe_media_write(media) == "MEDIA_CAPACITY_EXHAUSTED"
    assert observed and list(media.iterdir()) == [sentinel]
    assert sentinel.read_bytes() == b"owned image"
    with pytest.raises(OSError):
        os.fstat(observed[0])
    monkeypatch.setattr(readiness.os, "fsync", real_fsync)
    assert readiness.probe_media_write(media) is None


def test_a_file_is_not_replaced_with_a_media_directory(tmp_path):
    file = tmp_path / "configured-as-a-directory"
    file.write_bytes(b"preserved")
    assert readiness.probe_media_write(file) == "MEDIA_UNAVAILABLE"
    assert file.read_bytes() == b"preserved"


async def _entered(event):
    async def wait():
        while not event.is_set():
            await asyncio.sleep(.001)
    await asyncio.wait_for(wait(), timeout=3)


def test_timeout_keeps_one_probe_in_flight_and_recovers_after_it_finishes(tmp_path, monkeypatch):
    media = tmp_path / "probe-media"
    media.mkdir()
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    calls = []
    real_probe = readiness.probe_media_write

    def stalled(path):
        calls.append(path)
        entered.set()
        try:
            assert release.wait(5)
            return real_probe(path)
        finally:
            finished.set()

    monkeypatch.setattr(readiness, "probe_media_write", stalled)
    probe = readiness.MediaReadiness(timeout_seconds=.05)

    async def exercise():
        first = asyncio.create_task(probe.check(media))
        await _entered(entered)
        results = await asyncio.gather(first, *(probe.check(media) for _ in range(12)))
        assert results == ["MEDIA_PROBE_TIMEOUT"] * 13
        assert calls == [media]
        assert await probe.check(tmp_path / "another-root") == "MEDIA_PROBE_BUSY"
        assert await probe.check(media) == "MEDIA_PROBE_TIMEOUT"
        assert calls == [media]

    try:
        asyncio.run(exercise())
    finally:
        release.set()
        assert finished.wait(5)
    monkeypatch.setattr(readiness, "probe_media_write", real_probe)
    assert asyncio.run(probe.check(media)) is None
    assert not list(media.iterdir())


def _health_app(monkeypatch, tmp_path):
    import main

    media = tmp_path / "route-media"
    media.mkdir()
    monkeypatch.setattr(main, "MEDIA", media)
    monkeypatch.setattr(main, "DB_GUARD_STATUS", {})
    monkeypatch.setattr(main, "collect_db_guard_status", lambda: {"ok": True, "reason": str(tmp_path)})
    monkeypatch.setattr(readiness, "MEDIA_READINESS", readiness.MediaReadiness())
    return main, media


def test_probe_started_before_a_fault_cannot_make_a_later_request_ready(tmp_path, monkeypatch):
    media, hidden = tmp_path / "probe-media", tmp_path / "unavailable-media"
    media.mkdir()
    entered, release = threading.Event(), threading.Event()
    original, calls = readiness.probe_media_write, []

    def first_slow_result(path):
        calls.append(path)
        result = original(path)
        if len(calls) == 1:
            entered.set()
            assert release.wait(5)
        return result

    monkeypatch.setattr(readiness, "probe_media_write", first_slow_result)
    probe = readiness.MediaReadiness(timeout_seconds=2)

    async def exercise():
        first = asyncio.create_task(probe.check(media))
        await _entered(entered)
        media.rename(hidden)
        later = asyncio.create_task(probe.check(media))
        await asyncio.sleep(.001)
        release.set()
        assert await first is None
        assert await later == "MEDIA_UNAVAILABLE"
        assert calls == [media, media]

    try:
        asyncio.run(exercise())
    finally:
        release.set()
        if hidden.exists():
            hidden.rename(media)


def test_health_changes_to_503_and_recovers_without_restart(tmp_path, monkeypatch):
    main, media = _health_app(monkeypatch, tmp_path)
    expected = {"ok": True, "app": "izo-asa", "release_id": main.RELEASE_IDENTITY.release_id, "ready": True}
    with closing(TestClient(main.app, raise_server_exceptions=True)) as client:
        assert client.get("/api/health").json() == expected
        hidden = tmp_path / "unavailable-route-media"
        media.rename(hidden)
        try:
            failed = client.get("/api/health")
            assert failed.status_code == 503
            assert failed.json() == {**expected, "ok": False, "ready": False, "reasonCode": "MEDIA_UNAVAILABLE"}
            assert failed.headers["cache-control"] == "no-store"
            alive = client.get("/api/live")
            assert alive.status_code == 200 and alive.json()["ok"] is True
            assert "ready" not in alive.json()
            assert str(tmp_path) not in failed.text + alive.text
        finally:
            hidden.rename(media)
        recovered = client.get("/api/health")
        assert recovered.status_code == 200 and recovered.json() == expected
        assert not list(media.iterdir())


def test_unready_database_and_liveness_do_not_touch_media(tmp_path, monkeypatch):
    main, _ = _health_app(monkeypatch, tmp_path)
    monkeypatch.setattr(main, "collect_db_guard_status", lambda: {"ok": False, "reason": str(tmp_path)})

    def unexpected_probe(_):
        raise AssertionError("unready DB or liveness must not write media")

    monkeypatch.setattr(readiness, "probe_media_write", unexpected_probe)
    with closing(TestClient(main.app, raise_server_exceptions=True)) as client:
        failed = client.get("/api/health")
        assert failed.status_code == 503
        assert failed.json()["reasonCode"] == "DATABASE_NOT_READY"
        assert str(tmp_path) not in failed.text
        monkeypatch.setattr(main, "collect_db_guard_status", unexpected_probe)
        assert client.get("/api/live").status_code == 200


def test_stalled_media_does_not_block_liveness_or_spawn_more_probes(tmp_path, monkeypatch):
    main, media = _health_app(monkeypatch, tmp_path)
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    calls = []

    def stalled(path):
        calls.append(path)
        entered.set()
        try:
            assert release.wait(5)
            return None
        finally:
            finished.set()

    monkeypatch.setattr(readiness, "probe_media_write", stalled)
    monkeypatch.setattr(readiness, "MEDIA_READINESS", readiness.MediaReadiness(timeout_seconds=1))

    async def exercise():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://testserver") as client:
            pending = asyncio.create_task(client.get("/api/health"))
            await _entered(entered)
            alive = await client.get("/api/live")
            assert alive.status_code == 200
            assert not pending.done()
            failed = await pending
            assert failed.status_code == 503
            assert failed.json()["reasonCode"] == "MEDIA_PROBE_TIMEOUT"
            again = await client.get("/api/health")
            assert again.status_code == 503 and calls == [media]

    try:
        asyncio.run(exercise())
    finally:
        release.set()
        assert finished.wait(5)


def test_worker_readiness_recovers_and_runs_only_after_database_and_media(tmp_path, monkeypatch):
    media = tmp_path / "worker-health-media"
    media.mkdir()
    state = {"database": True, "worker": False, "calls": 0, "error": False}
    def worker_ready():
        state["calls"] += 1
        if state["error"]:
            raise RuntimeError("private worker socket at " + str(tmp_path))
        return state["worker"]

    monkeypatch.setattr(readiness, "MEDIA_READINESS", readiness.MediaReadiness())
    app = FastAPI()
    app.include_router(create_health_router(HealthDependencies(
        media_dir=lambda: media, release_id=lambda: "test-release",
        collect_db_guard=lambda: {"ok": state["database"]}, update_db_guard=lambda guard: None,
        worker_ready=worker_ready,
    )))
    expected = {"ok": False, "app": "izo-asa", "release_id": "test-release", "ready": False,
                "reasonCode": "GENERATION_WORKER_UNAVAILABLE"}
    with closing(TestClient(app)) as client:
        failed = client.get("/api/health")
        assert failed.status_code == 503 and failed.json() == expected
        assert client.get("/api/live").status_code == 200 and state["calls"] == 1
        state["error"] = True
        failed = client.get("/api/health")
        assert failed.status_code == 503 and failed.json() == expected
        assert str(tmp_path) not in failed.text
        state.update(error=False, worker=True)
        recovered = client.get("/api/health")
        assert recovered.status_code == 200
        assert recovered.json() == {key: (True if key in {"ok", "ready"} else value)
                                    for key, value in expected.items() if key != "reasonCode"}
        state["database"] = False
        assert client.get("/api/health").json()["reasonCode"] == "DATABASE_NOT_READY"
        state["database"] = True
        media.rmdir()
        assert client.get("/api/health").json()["reasonCode"] == "MEDIA_UNAVAILABLE"
        assert state["calls"] == 3
