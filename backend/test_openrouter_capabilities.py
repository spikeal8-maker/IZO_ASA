import main


def capability(model_id: str, max_refs: int, **parameters: object) -> dict:
    return main.openrouter_model_capability({
        "id": model_id,
        "name": model_id,
        "architecture": {"input_modalities": ["text", "image"], "output_modalities": ["image"]},
        "supported_parameters": {
            "input_references": {"type": "range", "min": 0, "max": max_refs},
            **parameters,
        },
    })


def test_single_reference_model_is_not_offered_for_assembly() -> None:
    result = capability("recraft/recraft-v4.1", 1)
    assert "image_to_image" in result["modes"]
    assert "paint" in result["modes"]
    assert "edit" not in result["modes"]


def test_multi_reference_model_is_offered_for_assembly() -> None:
    result = capability("black-forest-labs/flux.2-klein-4b", 4, seed={"type": "boolean"})
    assert result["maxInputReferences"] == 4
    assert "edit" in result["modes"]
    assert result["features"]["seed"] is True


def test_background_is_not_mistaken_for_mask_or_outpaint() -> None:
    result = capability(
        "openai/gpt-image-1",
        16,
        background={"type": "enum", "values": ["auto", "transparent", "opaque"]},
    )
    assert "remove_background" in result["modes"]
    assert "inpaint" not in result["modes"]
    assert "outpaint" not in result["modes"]


def test_native_mask_and_outpaint_parameters_are_classified() -> None:
    result = capability("provider/editor", 1, mask={"type": "boolean"}, outpaint={"type": "boolean"})
    assert "inpaint" in result["modes"]
    assert "outpaint" in result["modes"]


def test_saved_config_drops_models_from_incompatible_modes() -> None:
    catalog = [capability("provider/single", 1), capability("provider/multi", 4)]
    config = {
        "enabled": {"image_to_image": ["provider/single", "provider/multi"], "edit": ["provider/single", "provider/multi"]},
        "defaults": {"edit": "provider/single"},
        "access": {"edit": {"pro": ["provider/single", "provider/multi"]}},
        "qualityDefaults": {"edit": {"fast": "provider/single", "max": "provider/multi"}},
    }
    filtered = main.filter_openrouter_config_by_capabilities(config, catalog)
    assert filtered["enabled"]["image_to_image"] == ["provider/multi", "provider/single"]
    assert filtered["enabled"]["edit"] == ["provider/multi"]
    assert "edit" not in filtered["defaults"]
    assert filtered["access"]["edit"]["pro"] == ["provider/multi"]
    assert filtered["qualityDefaults"]["edit"] == {"max": "provider/multi"}
