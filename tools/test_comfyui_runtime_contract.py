from pathlib import Path

from tools import check_comfyui_runtime_contract as contract


def test_vendored_assets_match_manifest() -> None:
    assert contract.verify_assets(contract.load_manifest()) == []


def test_verify_file_reports_missing_file(tmp_path: Path) -> None:
    expected = {"bytes": 1, "sha256": "0" * 64}
    assert contract.verify_file(tmp_path / "missing.json", expected)[0].startswith("MISSING ")
