"""Fail-closed checks for the probe harness; the explicit CLI runs real BuildKit."""
from pathlib import Path
from unittest.mock import patch

import pytest

from tools import docker_canonical_context_probe as probe


def exported(tmp_path, role="web"):
    for name, content in probe.POSITIVE.items():
        if (name.endswith("network_guard.py")) != (role == "guard"):
            continue
        target = tmp_path / "context" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    return tmp_path


@pytest.mark.parametrize("role", ["web", "guard"])
def test_missing_positive_input_fails(tmp_path, role):
    output = exported(tmp_path, role)
    target = next((output / "context").rglob("*.py" if role == "guard" else "*.json"))
    target.unlink()
    result = probe.inspect_export(output, role)
    assert result["status"] == "FAIL" and result["missing"] and not result["contentsVerified"]


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
