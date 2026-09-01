from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "tools" / "backend-service-ownership.ps1"
PWSH = shutil.which("pwsh") or shutil.which("powershell")

pytestmark = pytest.mark.skipif(
    os.name != "nt" or not PWSH,
    reason="Windows PowerShell service ownership contract",
)


def _fixture(tmp_path: Path) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    sha = "a" * 40
    release_backend = tmp_path / "releases" / sha / "backend"
    launcher = release_backend / ".venv" / "Scripts" / "python.exe"
    launcher.parent.mkdir(parents=True)
    launcher.write_bytes(b"fixture")

    service_dir = tmp_path / "runtime" / "services" / "backend"
    service_dir.mkdir(parents=True)
    service_exe = service_dir / "IZOBackend.exe"
    service_exe.write_bytes(b"fixture")
    service_xml = service_exe.with_suffix(".xml")
    service_xml.write_text(
        "\n".join(
            [
                "<service>",
                "  <id>IZOBackend</id>",
                f"  <executable>{launcher}</executable>",
                "  <arguments>-m uvicorn main:app --host 127.0.0.1 --port 8000 --no-proxy-headers</arguments>",
                f"  <workingdirectory>{release_backend}</workingdirectory>",
                f'  <env name="GIT_COMMIT" value="{sha}" />',
                "</service>",
            ]
        ),
        encoding="utf-8",
    )

    listener = {
        "ProcessId": 300,
        "ParentProcessId": 200,
        "ExecutablePath": str(tmp_path / "runtime" / "python311" / "python.exe"),
    }
    Path(str(listener["ExecutablePath"])).parent.mkdir(parents=True)
    Path(str(listener["ExecutablePath"])).write_bytes(b"fixture")
    launcher_process = {
        "ProcessId": 200,
        "ParentProcessId": 100,
        "ExecutablePath": str(launcher),
        "CommandLine": f'"{launcher}" -m uvicorn main:app --host 127.0.0.1 --port 8000 --no-proxy-headers',
    }
    service = {
        "Name": "IZOBackend",
        "State": "Running",
        "ProcessId": 100,
        "PathName": f'"{service_exe}"',
    }
    return listener, launcher_process, service


def _run(
    tmp_path: Path,
    listener: dict[str, object],
    launcher: dict[str, object],
    service: dict[str, object],
) -> subprocess.CompletedProcess[str]:
    fixture_path = tmp_path / "ownership-fixture.json"
    fixture_path.write_text(
        json.dumps({"listener": listener, "launcher": launcher, "service": service}),
        encoding="utf-8",
    )
    environment = os.environ.copy()
    environment["IZO_OWNERSHIP_HELPER"] = str(HELPER)
    environment["IZO_OWNERSHIP_FIXTURE"] = str(fixture_path)
    environment["IZO_EXPECTED_RELEASE_ROOT"] = str(tmp_path / "releases")
    environment["IZO_EXPECTED_BASE_PYTHON"] = str(tmp_path / "runtime" / "python311" / "python.exe")
    environment["IZO_EXPECTED_SERVICE_EXECUTABLE"] = str(
        tmp_path / "runtime" / "services" / "backend" / "IZOBackend.exe"
    )
    command = (
        ". $env:IZO_OWNERSHIP_HELPER;"
        "$fixture=Get-Content -LiteralPath $env:IZO_OWNERSHIP_FIXTURE -Raw | ConvertFrom-Json;"
        "$result=Assert-IzoInstalledBackendServiceOwnership "
        "-ListenerProcess $fixture.listener -LauncherProcess $fixture.launcher -Service $fixture.service "
        "-ExpectedReleaseRoot $env:IZO_EXPECTED_RELEASE_ROOT -ExpectedBasePython $env:IZO_EXPECTED_BASE_PYTHON "
        "-ExpectedServiceExecutable $env:IZO_EXPECTED_SERVICE_EXECUTABLE;"
        "$result | ConvertTo-Json -Compress"
    )
    return subprocess.run(
        [PWSH, "-NoProfile", "-NonInteractive", "-Command", command],
        cwd=ROOT,
        env=environment,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )


def test_accepts_exact_running_service_process_and_release_contract(tmp_path: Path) -> None:
    listener, launcher, service = _fixture(tmp_path)
    result = _run(tmp_path, listener, launcher, service)

    assert result.returncode == 0, result.stdout + result.stderr
    evidence = json.loads(result.stdout)
    assert evidence["RuntimeOwnership"] == "installed-windows-service"
    assert evidence["ReleaseSha"] == "a" * 40
    assert evidence["RuntimeLauncherProcessId"] == 200


@pytest.mark.parametrize(
    ("mutation", "expected_error"),
    [
        ("service_pid", "not owned by the running IZOBackend service"),
        ("launcher_executable", "does not match the service XML executable"),
        ("launcher_arguments", "do not match the service XML contract"),
        ("release_sha", "release SHA does not match"),
        ("release_root", "outside the installed release root"),
        ("base_python", "does not match the configured service base Python"),
        ("service_executable", "outside the installed runtime location"),
    ],
)
def test_rejects_mismatched_installed_service_contract(
    tmp_path: Path, mutation: str, expected_error: str
) -> None:
    listener, launcher, service = _fixture(tmp_path)
    if mutation == "service_pid":
        service["ProcessId"] = 999
    elif mutation == "launcher_executable":
        launcher["ExecutablePath"] = str(tmp_path / "other" / "python.exe")
    elif mutation == "launcher_arguments":
        launcher["CommandLine"] = str(launcher["CommandLine"]).replace("--port 8000", "--port 9000")
    elif mutation == "release_sha":
        service_xml = Path(str(service["PathName"]).strip('"')).with_suffix(".xml")
        service_xml.write_text(
            service_xml.read_text(encoding="utf-8").replace('value="aaaaaaaa', 'value="baaaaaaa'),
            encoding="utf-8",
        )
    elif mutation == "base_python":
        listener["ExecutablePath"] = str(tmp_path / "unsupported" / "python.exe")
    elif mutation == "service_executable":
        service_exe = Path(str(service["PathName"]).strip('"'))
        alternate_dir = tmp_path / "alternate-service"
        alternate_dir.mkdir()
        alternate_exe = alternate_dir / service_exe.name
        alternate_xml = alternate_exe.with_suffix(".xml")
        service_exe.rename(alternate_exe)
        service_exe.with_suffix(".xml").rename(alternate_xml)
        service["PathName"] = f'"{alternate_exe}"'

    if mutation == "release_root":
        original_root = tmp_path / "releases"
        alternate_root = tmp_path / "other-releases"
        original_root.rename(alternate_root)
        launcher["ExecutablePath"] = str(launcher["ExecutablePath"]).replace(str(original_root), str(alternate_root))
        launcher["CommandLine"] = str(launcher["CommandLine"]).replace(str(original_root), str(alternate_root))
        service_exe = Path(str(service["PathName"]).strip('"'))
        service_xml = service_exe.with_suffix(".xml")
        service_xml.write_text(
            service_xml.read_text(encoding="utf-8").replace(str(original_root), str(alternate_root)),
            encoding="utf-8",
        )

    result = _run(tmp_path, listener, launcher, service)

    assert result.returncode != 0
    assert expected_error in result.stderr
