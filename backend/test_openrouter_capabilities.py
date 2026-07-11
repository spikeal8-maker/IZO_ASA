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


def test_image_to_image_body_contains_reference_and_semantic_influence() -> None:
    req = main.GenerateRequest(
        mode="image_to_image",
        provider="openrouter",
        prompt="Make the jacket red",
        strength=0.75,
        seed=123,
        inputImage1="data:image/png;base64,AA==",
    )
    body = main.build_openrouter_image_body(
        req,
        "provider/editor",
        {"size": "1024x1024"},
        {"modes": ["image_to_image"], "parameters": ["input_references", "seed"]},
    )
    assert body["input_references"][0]["image_url"]["url"] == req.inputImage1
    assert "Image edit influence: 75%" in body["prompt"]
    assert body["seed"] == 123


def test_seed_is_omitted_when_model_does_not_support_it() -> None:
    req = main.GenerateRequest(mode="image_to_image", prompt="Edit", seed=123, inputImage1="data:image/png;base64,AA==")
    body = main.build_openrouter_image_body(req, "provider/editor", {"size": "auto"}, {"modes": ["image_to_image"], "parameters": ["input_references"]})
    assert "seed" not in body


def test_text_only_model_is_rejected_for_image_to_image() -> None:
    req = main.GenerateRequest(mode="image_to_image", prompt="Edit", inputImage1="data:image/png;base64,AA==")
    try:
        main.build_openrouter_image_body(req, "provider/text-only", {"size": "auto"}, {"modes": ["text_to_image"], "parameters": []})
    except RuntimeError as exc:
        assert "не поддерживает" in str(exc)
    else:
        raise AssertionError("text-only model must be rejected")


def test_google_plan_preserves_requested_aspect_ratio_instead_of_forcing_square() -> None:
    cases = [
        ((1024, 1024), "1:1"),
        ((1280, 720), "16:9"),
        ((720, 1280), "9:16"),
        ((1536, 1024), "3:2"),
    ]
    for (width, height), ratio in cases:
        plan = main.openrouter_image_request_plan("google/gemini-3-pro-image", width, height)
        assert plan["aspect_ratio"] == ratio
        assert plan["resolution"] == "1K"
        assert "size" not in plan


def test_google_body_uses_normalized_aspect_ratio_for_text_and_photo() -> None:
    capability = {
        "modes": ["text_to_image", "image_to_image"],
        "parameters": ["aspect_ratio", "resolution", "input_references"],
    }
    plan = main.openrouter_image_request_plan("google/gemini-3-pro-image", 1280, 720)
    text_body = main.build_openrouter_image_body(
        main.GenerateRequest(mode="text_to_image", provider="openrouter", prompt="Wide scene", width=1280, height=720),
        "google/gemini-3-pro-image",
        plan,
        capability,
    )
    photo_body = main.build_openrouter_image_body(
        main.GenerateRequest(
            mode="image_to_image",
            provider="openrouter",
            prompt="Edit wide scene",
            width=1280,
            height=720,
            inputImage1="data:image/png;base64,AA==",
        ),
        "google/gemini-3-pro-image",
        plan,
        capability,
    )
    for body in (text_body, photo_body):
        assert body["aspect_ratio"] == "16:9"
        assert body["resolution"] == "1K"
        assert "size" not in body


def test_assembly_body_preserves_four_reference_order() -> None:
    req = main.GenerateRequest(
        mode="edit",
        provider="openrouter",
        prompt="Combine references by their described roles",
        inputImages=[
            main.EditImage(index=3, role="background", image="data:image/png;base64,Aw=="),
            main.EditImage(index=1, role="base", image="data:image/png;base64,AQ=="),
            main.EditImage(index=4, role="style", image="data:image/png;base64,BA=="),
            main.EditImage(index=2, role="clothing", image="data:image/png;base64,Ag=="),
        ],
    )
    body = main.build_openrouter_image_body(
        req,
        "provider/four-reference-editor",
        {"size": "1024x1024"},
        {
            "modes": ["edit"],
            "parameters": ["input_references"],
            "maxInputReferences": 4,
        },
    )
    assert [item["image_url"]["url"] for item in body["input_references"]] == [
        "data:image/png;base64,AQ==",
        "data:image/png;base64,Ag==",
        "data:image/png;base64,Aw==",
        "data:image/png;base64,BA==",
    ]


def test_assembly_body_rejects_more_images_than_model_limit() -> None:
    req = main.GenerateRequest(
        mode="edit",
        provider="openrouter",
        prompt="Combine",
        inputImages=[
            main.EditImage(index=1, role="base", image="data:image/png;base64,AQ=="),
            main.EditImage(index=2, role="style", image="data:image/png;base64,Ag=="),
            main.EditImage(index=3, role="object", image="data:image/png;base64,Aw=="),
        ],
    )
    try:
        main.build_openrouter_image_body(
            req,
            "provider/two-reference-editor",
            {"size": "1024x1024"},
            {"modes": ["edit"], "parameters": ["input_references"], "maxInputReferences": 2},
        )
    except RuntimeError as exc:
        assert "не больше 2" in str(exc)
    else:
        raise AssertionError("assembly must enforce the selected model reference limit")


def test_public_model_option_exposes_reference_limit() -> None:
    option = main._public_model_option("provider/editor", {"maxInputReferences": 8})
    assert option["generation"]["maxInputReferences"] == 4
    assert main._public_model_option("server:local_flux_klein")["generation"]["maxInputReferences"] == 4


def test_public_assembly_models_are_filtered_by_live_capability(monkeypatch) -> None:
    compatible = "provider/multi"
    incompatible = "provider/single"
    monkeypatch.setattr(main, "get_openrouter_config", lambda: {
        "access": {"edit": {"pro": [compatible, incompatible]}},
        "qualityDefaults": {},
        "defaults": {},
    })
    tariffs = main.get_tariff_config()
    monkeypatch.setattr(main, "get_tariff_config", lambda: tariffs)
    catalog = [
        {"id": compatible, "modes": ["edit"], "maxInputReferences": 4},
        {"id": incompatible, "modes": ["image_to_image"], "maxInputReferences": 1},
    ]
    access = main.public_model_access_for_plan("pro", catalog)
    ids = [item["id"] for item in access["modes"]["edit"]["models"]]
    assert compatible in ids
    assert incompatible not in ids
