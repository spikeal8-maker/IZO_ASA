from __future__ import annotations

from io import BytesIO
from pathlib import Path

from PIL import Image, UnidentifiedImageError
import pytest

from app.services.comfyui_results import (
    ComfyUIResult,
    extract_images_from_history,
    persist_downloaded_image,
    prompt_id_from_submission,
)


def test_result_dto_preserves_paths_prompt_and_history(tmp_path) -> None:
    image_path = tmp_path / "image.png"
    thumbnail_path = tmp_path / "thumb.webp"
    history = {"outputs": {}}

    result = ComfyUIResult("prompt-1", image_path, thumbnail_path, history)

    assert result.prompt_id == "prompt-1"
    assert result.image_path is image_path
    assert result.thumbnail_path is thumbnail_path
    assert result.history is history


def test_prompt_submission_returns_prompt_id() -> None:
    assert prompt_id_from_submission({"prompt_id": "prompt-1"}) == "prompt-1"


def test_prompt_submission_rejects_provider_error_before_other_fields() -> None:
    with pytest.raises(RuntimeError, match="^ComfyUI workflow error: invalid graph$"):
        prompt_id_from_submission(
            {
                "error": "invalid graph",
                "node_errors": {"FK:1": {"message": "ignored"}},
                "prompt_id": "ignored",
            }
        )


def test_prompt_submission_rejects_node_errors_with_readable_unicode() -> None:
    with pytest.raises(RuntimeError) as captured:
        prompt_id_from_submission({"node_errors": {"FK:1": {"message": "ошибка ноды"}}})

    assert str(captured.value) == 'ComfyUI node errors: {"FK:1": {"message": "ошибка ноды"}}'


@pytest.mark.parametrize("payload", [{}, {"prompt_id": ""}, {"prompt_id": None}])
def test_prompt_submission_requires_non_empty_prompt_id(payload: dict) -> None:
    with pytest.raises(RuntimeError, match=r"^ComfyUI не вернул prompt_id\.$"):
        prompt_id_from_submission(payload)


def test_history_images_preserve_output_order_and_defaults() -> None:
    history = {
        "outputs": {
            "save-1": {
                "images": [
                    {"filename": "first.png"},
                    {"subfolder": "ignored"},
                ]
            },
            "save-2": {
                "images": [
                    {"filename": "second.png", "subfolder": "nested", "type": "temp"},
                ]
            },
        }
    }

    assert extract_images_from_history(history) == [
        {"filename": "first.png", "subfolder": "", "type": "output"},
        {"filename": "second.png", "subfolder": "nested", "type": "temp"},
    ]
    assert extract_images_from_history({}) == []


def test_downloaded_image_adapter_uses_exact_prefix_and_callback_order(tmp_path) -> None:
    source = Image.new("RGB", (80, 40), "#2f6fed")
    buffer = BytesIO()
    source.save(buffer, "PNG")
    events: list[tuple[str, object]] = []

    def save_original(image: Image.Image, prefix: str) -> Path:
        events.append(("save", prefix))
        assert image.size == (80, 40) and image.format == "PNG"
        path = tmp_path / f"{prefix}.png"
        image.save(path, "PNG")
        return path

    def create_thumbnail(path: Path) -> Path:
        events.append(("thumbnail", path.name))
        thumbnail = path.with_name(f"{path.stem}_thumb.webp")
        Image.new("RGB", (20, 10), "#2f6fed").save(thumbnail, "WEBP")
        return thumbnail

    image_path, thumbnail_path = persist_downloaded_image(
        buffer.getvalue(),
        "job-1",
        save_original=save_original,
        create_thumbnail=create_thumbnail,
    )

    assert events == [("save", "job-1_comfyui"), ("thumbnail", "job-1_comfyui.png")]
    assert image_path.exists() and thumbnail_path.exists()


def test_downloaded_image_adapter_rejects_invalid_image_before_callbacks() -> None:
    called = False

    def save_original(_image: Image.Image, _prefix: str) -> Path:
        nonlocal called
        called = True
        return Path("unexpected.png")

    with pytest.raises(UnidentifiedImageError):
        persist_downloaded_image(
            b"not-an-image",
            "job-1",
            save_original=save_original,
            create_thumbnail=lambda path: path,
        )

    assert called is False
