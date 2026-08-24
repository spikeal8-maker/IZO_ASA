from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "ensure_service_python_runtime.py"


pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows service runtime contract")


def _run(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(TOOL), *arguments],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )


def _release(tmp_path: Path) -> Path:
    release = tmp_path / ("a" * 40)
    backend = release / "backend"
    backend.mkdir(parents=True)
    pip_version = subprocess.run(
        [sys.executable, "-c", "import ensurepip;print(ensurepip.version())"],
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=True,
    ).stdout.strip()
    (backend / "requirements.txt").write_text(f"pip=={pip_version}\n", encoding="utf-8")
    return release


def test_service_runtime_creates_and_validates_exact_base_venv(tmp_path: Path) -> None:
    release = _release(tmp_path)
    result = _run(
        "--release-root",
        str(release),
        "--base-python",
        sys.executable,
        "--required-module",
        "pip",
        "--repair",
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "SERVICE_PYTHON_RUNTIME_OK" in result.stdout
    stamp = json.loads(
        (release / "backend" / ".venv" / ".izo-service-runtime.json").read_text(
            encoding="utf-8"
        )
    )
    assert stamp["required_modules"] == ["pip"]
    assert stamp["requirements_sha256"].startswith("sha256:")

    validate = _run(
        "--release-root",
        str(release),
        "--base-python",
        sys.executable,
        "--required-module",
        "pip",
    )
    assert validate.returncode == 0, validate.stdout + validate.stderr


def test_service_runtime_rejects_interactive_profile_base_before_repair(tmp_path: Path) -> None:
    release = _release(tmp_path)
    venv = release / "backend" / ".venv"
    (venv / "Scripts").mkdir(parents=True)
    (venv / "Scripts" / "python.exe").write_bytes(b"not-a-python-launcher")
    (venv / "pyvenv.cfg").write_text(
        "home = C:\\Users\\interactive\\Python311\n"
        "executable = C:\\Users\\interactive\\Python311\\python.exe\n",
        encoding="utf-8",
    )

    result = _run(
        "--release-root",
        str(release),
        "--base-python",
        sys.executable,
        "--required-module",
        "pip",
    )

    assert result.returncode == 1
    assert "VENV_HOME_MISMATCH" in result.stderr
    assert "VENV_EXECUTABLE_MISMATCH" in result.stderr
    assert "VENV_PROBE_FAILED" in result.stderr


def test_runtime_state_refuses_venv_outside_release_backend(tmp_path: Path) -> None:
    release = _release(tmp_path)
    other = tmp_path / "other"
    other.mkdir()
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from pathlib import Path;"
                "from tools.ensure_service_python_runtime import _runtime_state;"
                f"_runtime_state(release_root=Path({str(release)!r}),"
                f"venv=Path({str(other)!r}),base_python=Path({sys.executable!r}),"
                f"requirements_path=Path({str(release / 'backend' / 'requirements.txt')!r}),"
                "required_modules=[]);"
            ),
        ],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    assert "outside the exact release backend path" in result.stderr
