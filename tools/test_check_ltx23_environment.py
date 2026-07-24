from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "check-ltx23-environment.ps1"
POWERSHELL = shutil.which("pwsh") or shutil.which("powershell")


def _run(tmp_path: Path, *, stale: bool = False) -> subprocess.CompletedProcess[str]:
    comfy = tmp_path / "portable" / "ComfyUI"
    model = comfy / "models" / "unet" / "tiny.gguf"
    model.parent.mkdir(parents=True)
    model.write_bytes(b"ltx-fixture")

    workflow = tmp_path / "workflow.json"
    workflow.write_text(
        json.dumps(
            {
                "1": {"class_type": "CLIPTextEncode", "inputs": {"text": "positive"}},
                "2": {"class_type": "CLIPTextEncode", "inputs": {"text": "negative"}},
                "3": {
                    "class_type": "EmptyLTXVLatentVideo",
                    "inputs": {"width": 832, "height": 480, "length": 49},
                },
                "4": {
                    "class_type": "VHS_VideoCombine",
                    "inputs": {
                        "filename_prefix": (
                            "ltx-av-step-1751000_vocoder_24K.safetensors"
                            if stale
                            else "ltx23-test"
                        )
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "runtime": {"python": "", "torch": "", "cuda_runtime": ""},
                "custom_nodes": [],
                "required_models": [
                    {
                        "path": "models/unet/tiny.gguf",
                        "bytes": model.stat().st_size,
                        "sha256": hashlib.sha256(model.read_bytes()).hexdigest(),
                    }
                ],
                "workflow": {
                    "required_class_types": [
                        "CLIPTextEncode",
                        "EmptyLTXVLatentVideo",
                        "VHS_VideoCombine",
                    ],
                    "required_text_nodes": 2,
                    "forbidden_references": [
                        "ltx-av-step-1751000_vocoder_24K.safetensors"
                    ],
                },
            }
        ),
        encoding="utf-8",
    )

    # The fixture intentionally omits the 35 GB runtime and Python. Its purpose
    # is to exercise manifest, checksum and workflow validation deterministically.
    command = [
        POWERSHELL,
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(SCRIPT),
        "-ComfyRoot",
        str(comfy),
        "-ManifestPath",
        str(manifest),
        "-WorkflowPath",
        str(workflow),
        "-SkipRuntime",
        "-SkipCommits",
    ]
    return subprocess.run(command, capture_output=True, text=True, check=False)


@pytest.mark.skipif(not POWERSHELL, reason="PowerShell is unavailable")
def test_preflight_accepts_models_and_api_workflow_before_runtime_check(tmp_path: Path) -> None:
    result = _run(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "model models/unet/tiny.gguf SHA256" in result.stdout
    assert "workflow has positive and negative text nodes" in result.stdout
    assert "workflow excludes stale reference" in result.stdout
    assert "LTX23_PREFLIGHT_OK" in result.stdout


@pytest.mark.skipif(not POWERSHELL, reason="PowerShell is unavailable")
def test_preflight_rejects_stale_vocoder_reference(tmp_path: Path) -> None:
    result = _run(tmp_path, stale=True)
    assert result.returncode == 1
    assert "ERR workflow excludes stale reference" in result.stdout
