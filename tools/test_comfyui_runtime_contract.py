from pathlib import Path

from tools import check_comfyui_runtime_contract as contract


def test_vendored_assets_match_manifest() -> None:
    assert contract.verify_assets(contract.load_manifest()) == []


def test_verify_file_reports_missing_file(tmp_path: Path) -> None:
    expected = {"bytes": 1, "sha256": "0" * 64}
    assert contract.verify_file(tmp_path / "missing.json", expected)[0].startswith("MISSING ")


def test_quality_face_lora_is_required_and_rank32_is_optional() -> None:
    models = {item["path"]: item for item in contract.load_manifest()["models"]}
    quality = models["models/loras/bfs_head_v1_flux-klein_9b_step3500_rank128.safetensors"]
    compatibility = models["models/loras/face_swap_flux_klein_9b_r32_800.safetensors"]

    assert quality["required"] is True
    assert quality["qualityProfile"] is True
    assert compatibility["required"] is False
    assert compatibility["compatibilityOnly"] is True


def test_pose_snapshot_is_not_expected_inside_live_custom_node() -> None:
    assets = {item["path"]: item for item in contract.load_manifest()["assets"]}
    pose = assets["one-node-flux-2-klein/workflows/pose_workflow.json"]

    assert pose["runtimeRequired"] is False
