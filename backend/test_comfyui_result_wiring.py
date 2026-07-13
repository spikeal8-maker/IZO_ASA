from __future__ import annotations

import asyncio

import pytest

import main


def run_submit(monkeypatch, response: dict):
    async def fake_submit(*, base_url: str, workflow: dict, job_id: str) -> dict:
        assert base_url == main.COMFYUI_BASE_URL
        assert workflow == {"node": {"inputs": {}}}
        assert job_id == "job-1"
        return response

    monkeypatch.setattr(main, "integration_submit_comfyui_workflow", fake_submit)
    return asyncio.run(main.submit_workflow({"node": {"inputs": {}}}, {"id": "job-1"}))


def test_submit_workflow_rejects_provider_error(monkeypatch) -> None:
    with pytest.raises(RuntimeError, match="^ComfyUI workflow error: invalid graph$"):
        run_submit(monkeypatch, {"error": "invalid graph"})


def test_submit_workflow_rejects_node_errors_with_unicode_json(monkeypatch) -> None:
    with pytest.raises(RuntimeError) as captured:
        run_submit(monkeypatch, {"node_errors": {"FK:1": {"message": "ошибка ноды"}}})

    assert str(captured.value) == 'ComfyUI node errors: {"FK:1": {"message": "ошибка ноды"}}'


def test_submit_workflow_requires_prompt_id(monkeypatch) -> None:
    with pytest.raises(RuntimeError, match=r"^ComfyUI не вернул prompt_id\.$"):
        run_submit(monkeypatch, {})


def test_submit_workflow_returns_history_and_normalized_images(monkeypatch) -> None:
    history = {
        "outputs": {
            "save": {
                "images": [
                    {"filename": "first.png"},
                    {"filename": "second.png", "subfolder": "nested", "type": "temp"},
                    {"subfolder": "ignored-without-filename"},
                ]
            }
        }
    }

    async def fake_wait(prompt_id: str, job: dict) -> dict:
        assert prompt_id == "prompt-1" and job["id"] == "job-1"
        return history

    monkeypatch.setattr(main, "wait_for_history", fake_wait)

    prompt_id, actual_history, images = run_submit(monkeypatch, {"prompt_id": "prompt-1"})

    assert prompt_id == "prompt-1"
    assert actual_history is history
    assert images == [
        {"filename": "first.png", "subfolder": "", "type": "output"},
        {"filename": "second.png", "subfolder": "nested", "type": "temp"},
    ]
