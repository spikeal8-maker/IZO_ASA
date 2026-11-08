"""Fail-closed checks for the probe harness; the explicit CLI runs real BuildKit."""
from pathlib import Path
from unittest.mock import patch

import pytest

from tools import docker_canonical_context_probe as probe


def exported(tmp_path, role="web"):
    for name, content in probe.POSITIVE.items():
        if (name in {"ops/docker/dev/network_guard.py", "ops/docker/dev/comfyui_proxy.py",
                     "ops/docker/dev/openrouter_https_proxy.py"}) != (role == "guard"):
            continue
        target = tmp_path / "context" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    return tmp_path


@pytest.mark.parametrize("role,name", [("web", "frontend/package.json"),
    ("guard", "ops/docker/dev/network_guard.py"), ("guard", "ops/docker/dev/comfyui_proxy.py"),
    ("guard", "ops/docker/dev/openrouter_https_proxy.py")])
def test_missing_positive_input_fails(tmp_path, role, name):
    output = exported(tmp_path, role)
    target = output / "context" / name
    target.unlink()
    result = probe.inspect_export(output, role)
    assert result["status"] == "FAIL" and result["missing"] and not result["contentsVerified"]


@pytest.mark.parametrize("name", ["ops/docker/dev/network_guard.py", "ops/docker/dev/comfyui_proxy.py",
                                  "ops/docker/dev/openrouter_https_proxy.py"])
def test_guard_requires_exact_three_inputs_with_unchanged_bytes(tmp_path, name):
    output = exported(tmp_path, "guard")
    result = probe.inspect_export(output, "guard")
    assert result["status"] == "PASS" and result["files"] == [
        "ops/docker/dev/comfyui_proxy.py", "ops/docker/dev/network_guard.py", "ops/docker/dev/openrouter_https_proxy.py"]
    (output / "context" / name).write_bytes(b"changed synthetic source")
    result = probe.inspect_export(output, "guard")
    assert result["status"] == "FAIL" and not result["contentsVerified"]


@pytest.mark.parametrize("name", ["ops/docker/dev/nginx.shadow.conf", "ops/docker/dev/unrelated/private.txt", ".env"])
def test_guard_rejects_every_additional_input(tmp_path, name):
    output = exported(tmp_path, "guard")
    extra = output / "context" / name
    extra.parent.mkdir(parents=True, exist_ok=True)
    extra.write_bytes(b"synthetic forbidden input")
    result = probe.inspect_export(output, "guard")
    assert result["status"] == "FAIL" and result["unexpected"] == [name]


@pytest.mark.parametrize("suffix", ["-wal", "-shm", "-journal"])
def test_exported_sidecar_is_a_failure(tmp_path, suffix):
    output = exported(tmp_path)
    name = "frontend/probe.db" + suffix
    (output / "context" / name).write_bytes(b"synthetic sidecar")
    result = probe.inspect_export(output, "web")
    assert result["status"] == "FAIL" and result["unexpected"] == [name]


def test_changed_positive_content_is_a_failure(tmp_path):
    output = exported(tmp_path)
    (output / "context/frontend/package.json").write_bytes(b"different bytes")
    result = probe.inspect_export(output, "web")
    assert result["status"] == "FAIL" and not result["contentsVerified"]


def test_existing_receipt_cannot_be_overwritten(tmp_path):
    receipt = tmp_path / "receipt.json"; receipt.write_bytes(b"prior evidence")
    with patch.object(probe, "probe") as operation, pytest.raises(SystemExit):
        probe.main(["--source", str(tmp_path), "--context", "default", "--receipt", str(receipt)])
    operation.assert_not_called()
    assert receipt.read_bytes() == b"prior evidence"


def test_missing_policy_fails_before_docker(tmp_path):
    with patch.object(probe.subprocess, "run") as command, pytest.raises(probe.ProbeFailure):
        probe.probe(tmp_path, "default")
    command.assert_not_called()
