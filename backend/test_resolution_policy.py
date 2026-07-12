import json
import sqlite3

from backend.main import get_tariff_config
from backend.resolution_policy import (
    CONFIG_UI_RESOLUTION_IDS,
    normalize_resolution_ids,
    resolution_id_for_size,
    supported_resolution_ids_from_capability,
)


def test_legacy_resolution_ids_are_migrated() -> None:
    assert normalize_resolution_ids(["sq-1024", "h-1280", "bad"]) == ["sq-hd", "h-hd"]


def test_exact_size_lookup_does_not_guess() -> None:
    assert resolution_id_for_size(1024, 1024) == "sq-hd"
    assert resolution_id_for_size(1280, 720) == "h-hd"
    assert resolution_id_for_size(1279, 720) is None


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


def test_config_ui_access_is_loaded_from_dedicated_database_setting() -> None:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute("CREATE TABLE admin_settings (key TEXT PRIMARY KEY, value_json TEXT NOT NULL)")
    connection.execute("INSERT INTO admin_settings VALUES ('tariffs', '{}')")
    connection.execute(
        "INSERT INTO admin_settings VALUES ('config_ui_resolution_access', ?)",
        (json.dumps({"plans": {"mini": ["sq-sd", "p-hd"], "pro": ["sq-fhd"]}}),),
    )
    config = get_tariff_config(connection)
    assert config["mini"]["allowed_resolutions"] == ["sq-sd", "p-hd"]
    assert config["pro"]["allowed_resolutions"] == ["sq-fhd"]


def test_flux_catalog_without_descriptors_keeps_all_supported_sizes() -> None:
    capability = {"id": "black-forest-labs/flux.2-pro", "parameterDescriptors": {}}
    assert len(supported_resolution_ids_from_capability(capability)) == 12


def test_openai_catalog_uses_adapter_safe_output_sizes() -> None:
    capability = {"id": "openai/gpt-image-2", "parameterDescriptors": {}}
    assert supported_resolution_ids_from_capability(capability) == ["sq-hd", "v-fhd", "p-fhd"]


def test_resolution_only_provider_keeps_all_four_formats() -> None:
    capability = {
        "id": "sourceful/riverflow-v2.5-fast",
        "parameterDescriptors": {"resolution": {"values": ["1K", "2K"]}},
    }
    assert supported_resolution_ids_from_capability(capability) == [
        "sq-hd", "sq-fhd", "v-hd", "v-fhd", "h-hd", "h-fhd", "p-hd", "p-fhd",
    ]


def test_config_ui_advertises_all_canonical_sizes() -> None:
    assert CONFIG_UI_RESOLUTION_IDS == (
        "sq-sd", "sq-hd", "sq-fhd",
        "v-sd", "v-hd", "v-fhd",
        "h-sd", "h-hd", "h-fhd",
        "p-sd", "p-hd", "p-fhd",
    )
