from __future__ import annotations

import asyncio

import pytest

import main


def test_wait_for_history_reuses_one_client_until_prompt_completes(monkeypatch) -> None:
    state = {"entered": 0, "exited": 0, "fetches": 0, "sleeps": 0}
    responses = [{}, {"prompt-1": {"outputs": {"save": {"images": []}}}}]

    class FakeHistoryClient:
        def __init__(self, *, base_url: str, timeout_seconds: float) -> None:
            assert base_url == main.COMFYUI_BASE_URL
            assert timeout_seconds == main.COMFYUI_HISTORY_REQUEST_TIMEOUT_SECONDS

        async def __aenter__(self) -> "FakeHistoryClient":
            state["entered"] += 1
            return self

        async def __aexit__(self, *args) -> None:
            state["exited"] += 1

        async def fetch(self, prompt_id: str) -> dict:
            assert prompt_id == "prompt-1"
            state["fetches"] += 1
            return responses.pop(0)

    async def fake_sleep(seconds: float) -> None:
        assert seconds == 2
        state["sleeps"] += 1

    monkeypatch.setattr(main, "IntegrationComfyUIHistoryClient", FakeHistoryClient)
    monkeypatch.setattr(main.asyncio, "sleep", fake_sleep)
    job = {"status": "running", "progress": 24, "mode": "text_to_image"}

    result = asyncio.run(main.wait_for_history("prompt-1", job))

    assert result == {"outputs": {"save": {"images": []}}}
    assert state == {"entered": 1, "exited": 1, "fetches": 2, "sleeps": 1}
    assert job["progress"] == 26


def test_wait_for_history_checks_cancellation_before_network(monkeypatch) -> None:
    state = {"fetches": 0, "exited": 0}

    class FakeHistoryClient:
        def __init__(self, *, base_url: str, timeout_seconds: float) -> None:
            assert base_url == main.COMFYUI_BASE_URL
            assert timeout_seconds == main.COMFYUI_HISTORY_REQUEST_TIMEOUT_SECONDS

        async def __aenter__(self) -> "FakeHistoryClient":
            return self

        async def __aexit__(self, *args) -> None:
            state["exited"] += 1

        async def fetch(self, _prompt_id: str) -> dict:
            state["fetches"] += 1
            return {}

    monkeypatch.setattr(main, "IntegrationComfyUIHistoryClient", FakeHistoryClient)
    async def fake_recover(_prompt_id: str, _job: dict, reason: str) -> None:
        assert reason == "cancelled"

    monkeypatch.setattr(main, "recover_timed_out_comfyui_image", fake_recover)

    with pytest.raises(RuntimeError, match="Задача отменена"):
        asyncio.run(main.wait_for_history("prompt-1", {"status": "cancelled", "mode": "text_to_image"}))

    assert state == {"fetches": 0, "exited": 1}
