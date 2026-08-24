from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Iterable


STAMP_NAME = ".izo-service-runtime.json"
PIN_RE = re.compile(r"^([A-Za-z0-9_.-]+)(?:\[[^]]+\])?==([^;\s]+)$")


class ServiceRuntimeError(RuntimeError):
    pass


def _resolved(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def _same_path(left: Path, right: Path) -> bool:
    return os.path.normcase(str(_resolved(left))) == os.path.normcase(str(_resolved(right)))


def _inside(path: Path, root: Path) -> bool:
    try:
        _resolved(path).relative_to(_resolved(root))
        return True
    except ValueError:
        return False


def _venv_python(venv: Path) -> Path:
    suffix = Path("Scripts/python.exe") if os.name == "nt" else Path("bin/python")
    return venv / suffix


def _read_cfg(venv: Path) -> dict[str, str]:
    cfg_path = venv / "pyvenv.cfg"
    if not cfg_path.is_file():
        return {}
    values: dict[str, str] = {}
    for raw_line in cfg_path.read_text(encoding="utf-8", errors="replace").splitlines():
        key, separator, value = raw_line.partition("=")
        if separator:
            values[key.strip().casefold()] = value.strip()
    return values


def _run_json(python: Path, code: str, *arguments: str) -> dict[str, object]:
    completed = subprocess.run(
        [str(python), "-c", code, *arguments],
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
        timeout=45,
    )
    if completed.returncode != 0:
        raise ServiceRuntimeError(
            f"Python runtime probe failed with exit code {completed.returncode}."
        )
    try:
        payload = json.loads(completed.stdout.strip())
    except json.JSONDecodeError as exc:
        raise ServiceRuntimeError("Python runtime probe returned invalid JSON.") from exc
    if not isinstance(payload, dict):
        raise ServiceRuntimeError("Python runtime probe returned an invalid payload.")
    return payload


def _probe_python(python: Path, required_modules: Iterable[str] = ()) -> dict[str, object]:
    code = (
        "import importlib,json,sys;"
        "mods=json.loads(sys.argv[1]);"
        "[importlib.import_module(name) for name in mods];"
        "print(json.dumps({'executable':sys.executable,'base_prefix':sys.base_prefix,"
        "'version':[sys.version_info.major,sys.version_info.minor,sys.version_info.micro]}))"
    )
    return _run_json(python, code, json.dumps(list(required_modules)))


def _requirements(requirements_path: Path) -> dict[str, str]:
    pinned: dict[str, str] = {}
    for raw_line in requirements_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        match = PIN_RE.fullmatch(line)
        if not match:
            raise ServiceRuntimeError(
                f"Production requirement is not exactly pinned: {line!r}."
            )
        name, version = match.groups()
        pinned[re.sub(r"[-_.]+", "-", name).casefold()] = version
    if not pinned:
        raise ServiceRuntimeError("Production requirements are empty.")
    return pinned


def _installed_versions(python: Path, names: Iterable[str]) -> dict[str, str | None]:
    code = (
        "import importlib.metadata,json,sys;"
        "names=json.loads(sys.argv[1]);out={};"
        "exec(\"for name in names:\\n"
        "  try: out[name]=importlib.metadata.version(name)\\n"
        "  except importlib.metadata.PackageNotFoundError: out[name]=None\");"
        "print(json.dumps(out))"
    )
    payload = _run_json(python, code, json.dumps(list(names)))
    return {str(key): None if value is None else str(value) for key, value in payload.items()}


def _requirements_sha256(requirements_path: Path) -> str:
    return "sha256:" + hashlib.sha256(requirements_path.read_bytes()).hexdigest()


def _runtime_state(
    *,
    release_root: Path,
    venv: Path,
    base_python: Path,
    requirements_path: Path,
    required_modules: Iterable[str],
) -> tuple[bool, list[str], dict[str, object]]:
    problems: list[str] = []
    expected_venv = release_root / "backend" / ".venv"
    if not _inside(venv, release_root) or not _same_path(venv, expected_venv):
        raise ServiceRuntimeError("Candidate venv is outside the exact release backend path.")
    if not _same_path(requirements_path, release_root / "backend" / "requirements.txt"):
        raise ServiceRuntimeError("Requirements path is outside the exact release backend path.")
    if not base_python.is_file():
        raise ServiceRuntimeError("Service base Python is missing.")
    if not requirements_path.is_file():
        raise ServiceRuntimeError("Candidate requirements file is missing.")

    base = _probe_python(base_python)
    expected_base = Path(str(base["base_prefix"]))
    expected_executable = Path(str(base["executable"]))
    if not _same_path(expected_executable, base_python):
        problems.append("BASE_PYTHON_EXECUTABLE_MISMATCH")

    cfg = _read_cfg(venv)
    if not cfg:
        problems.append("VENV_CONFIG_MISSING")
    else:
        cfg_home = Path(cfg.get("home", "."))
        cfg_executable = Path(cfg.get("executable", "."))
        if not _same_path(cfg_home, expected_base):
            problems.append("VENV_HOME_MISMATCH")
        if not _same_path(cfg_executable, expected_executable):
            problems.append("VENV_EXECUTABLE_MISMATCH")

    candidate_python = _venv_python(venv)
    if not candidate_python.is_file():
        problems.append("VENV_PYTHON_MISSING")
    else:
        try:
            candidate = _probe_python(candidate_python, required_modules)
            if not _same_path(Path(str(candidate["base_prefix"])), expected_base):
                problems.append("VENV_BASE_PREFIX_MISMATCH")
        except (OSError, subprocess.SubprocessError, ServiceRuntimeError):
            problems.append("VENV_PROBE_FAILED")

    pinned = _requirements(requirements_path)
    if candidate_python.is_file() and "VENV_PROBE_FAILED" not in problems:
        installed = _installed_versions(candidate_python, pinned)
        if any(installed.get(name) != expected for name, expected in pinned.items()):
            problems.append("DEPENDENCY_VERSION_MISMATCH")

    state = {
        "base_executable": str(_resolved(expected_executable)),
        "base_prefix": str(_resolved(expected_base)),
        "candidate_python": str(_resolved(candidate_python)),
        "requirements_sha256": _requirements_sha256(requirements_path),
        "python_version": base["version"],
        "required_modules": sorted(set(required_modules)),
    }
    return not problems, problems, state


def _run_quiet(command: list[str], *, timeout: int) -> None:
    completed = subprocess.run(
        command,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
        timeout=timeout,
    )
    if completed.returncode != 0:
        raise ServiceRuntimeError(
            f"Candidate Python preparation failed with exit code {completed.returncode}."
        )


def ensure_runtime(
    *,
    release_root: Path,
    base_python: Path,
    required_modules: list[str],
    repair: bool,
) -> dict[str, object]:
    release_root = _resolved(release_root)
    base_python = _resolved(base_python)
    venv = release_root / "backend" / ".venv"
    requirements_path = release_root / "backend" / "requirements.txt"

    ok, problems, state = _runtime_state(
        release_root=release_root,
        venv=venv,
        base_python=base_python,
        requirements_path=requirements_path,
        required_modules=required_modules,
    )
    if not ok and repair:
        venv.parent.mkdir(parents=True, exist_ok=True)
        command = [str(base_python), "-m", "venv"]
        if venv.exists():
            command.append("--upgrade")
        command.append(str(venv))
        _run_quiet(command, timeout=180)
        candidate_python = _venv_python(venv)
        pinned = _requirements(requirements_path)
        installed = _installed_versions(candidate_python, pinned)
        if any(installed.get(name) != version for name, version in pinned.items()):
            _run_quiet(
                [
                    str(candidate_python),
                    "-m",
                    "pip",
                    "install",
                    "--disable-pip-version-check",
                    "--no-input",
                    "--requirement",
                    str(requirements_path),
                ],
                timeout=900,
            )
        _run_quiet([str(candidate_python), "-m", "pip", "check"], timeout=120)
        ok, problems, state = _runtime_state(
            release_root=release_root,
            venv=venv,
            base_python=base_python,
            requirements_path=requirements_path,
            required_modules=required_modules,
        )

    if not ok:
        raise ServiceRuntimeError("Candidate Python is not service-safe: " + ",".join(problems))

    if repair:
        stamp_path = venv / STAMP_NAME
        temporary = stamp_path.with_suffix(f".tmp-{os.getpid()}")
        temporary.write_text(
            json.dumps(state, ensure_ascii=True, indent=2) + "\n", encoding="utf-8"
        )
        temporary.replace(stamp_path)
    return state


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate or repair a release venv against the service-safe Python runtime."
    )
    parser.add_argument("--release-root", type=Path, required=True)
    parser.add_argument("--base-python", type=Path, required=True)
    parser.add_argument("--required-module", action="append", default=[])
    parser.add_argument("--repair", action="store_true")
    args = parser.parse_args()
    try:
        state = ensure_runtime(
            release_root=args.release_root,
            base_python=args.base_python,
            required_modules=list(args.required_module),
            repair=bool(args.repair),
        )
    except (OSError, subprocess.SubprocessError, ServiceRuntimeError) as exc:
        print(f"SERVICE_PYTHON_RUNTIME_ERROR {exc}", file=sys.stderr)
        return 1
    print(
        "SERVICE_PYTHON_RUNTIME_OK "
        f"base={state['base_prefix']} requirements={state['requirements_sha256']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
