from backend.resolution_policy import (
    normalize_resolution_ids,
    resolution_id_for_size,
    supported_resolution_ids_from_capability,
)


def test_legacy_resolution_ids_are_migrated() -> None:
    assert normalize_resolution_ids(["sq-1024", "h-1280", "bad"]) == ["sq-hd", "h-hd"]


def test_exact_size_lookup_does_not_guess() -> None:
    assert resolution_id_for_size(1024, 1024) == "sq-hd"
    assert resolution_id_for_size(1280, 720) is None


def test_openrouter_descriptors_define_formats_and_tiers() -> None:
    capability = {
        "parameterDescriptors": {
            "resolution": {"values": ["1K", "2K"]},
            "aspect_ratio": {"values": ["1:1", "16:9"]},
        }
    }
    assert supported_resolution_ids_from_capability(capability) == ["sq-hd", "sq-fhd", "h-hd", "h-fhd"]


def test_explicit_openai_sizes_are_not_mislabeled_as_wide() -> None:
    capability = {
        "parameterDescriptors": {
            "size": {"values": ["1024x1024", "1024x1536", "1536x1024"]},
        }
    }
    assert supported_resolution_ids_from_capability(capability) == ["sq-hd", "p-fhd"]
