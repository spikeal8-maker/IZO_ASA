from pathlib import Path

from PIL import Image

from app.services import comfyui_inputs


def test_reference_fit_never_upscales_and_obeys_every_limit() -> None:
    assert comfyui_inputs.fit_reference_size(
        (304, 384),
        target_box=(704, 704),
        max_side=1536,
    ) == (304, 384)
    face = comfyui_inputs.fit_reference_size(
        (1120, 1408),
        target_box=(704, 704),
        max_side=1536,
        max_megapixels=0.35,
    )
    assert face == (512, 656)
    assert comfyui_inputs.image_megapixels(face) <= 0.35
    assert face[0] % 16 == 0 and face[1] % 16 == 0


def test_reference_fit_preserves_small_valid_source() -> None:
    assert comfyui_inputs.fit_reference_size(
        (256, 256),
        target_box=(1024, 1024),
        max_side=1536,
        max_megapixels=0.35,
    ) == (256, 256)


def test_prepare_reference_image_caps_face_and_does_not_enlarge_small_input(tmp_path: Path) -> None:
    large = tmp_path / "large.png"
    small = tmp_path / "small.png"
    Image.new("RGB", (1120, 1408), "white").save(large)
    Image.new("RGB", (304, 384), "white").save(small)

    prepared_large = comfyui_inputs.prepare_reference_image(
        large,
        output_directory=tmp_path,
        prefix="face",
        target_box=(704, 704),
        max_side=1536,
        minimum_side=256,
        max_megapixels=0.35,
    )
    prepared_small = comfyui_inputs.prepare_reference_image(
        small,
        output_directory=tmp_path,
        prefix="base",
        target_box=(704, 704),
        max_side=1536,
        minimum_side=256,
    )

    assert prepared_large is not None and prepared_large != large
    with Image.open(prepared_large) as image:
        assert image.size == (512, 656)
    assert prepared_small == small
