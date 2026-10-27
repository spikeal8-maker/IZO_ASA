from __future__ import annotations

import ast
import json
import os
import sqlite3
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from tools.agent_system import env_lifecycle as lifecycle
from tools.agent_system import env_ready as ready
from tools.agent_system.env import (
    derive_environment_paths,
    load_environment_identity,
)
from tools.test_agent_env import _add_package, _known_contract, _make_control_repo
from tools.agent_env_test_ports import available_package_id as _available_package_id


def _contract(tmp_path: Path):
    known = _known_contract(tmp_path)
    return replace(known, status="UNKNOWN", media_status="UNKNOWN", media_roots=())


def _package(tmp_path: Path, package_id: str):
    control, base = _make_control_repo(tmp_path)
    worktree = _add_package(control, base, package_id, tmp_path / "w")
    return worktree, _contract(tmp_path)


def _active(tmp_path: Path, package_id: str):
    worktree, contract = _package(tmp_path, package_id)
    lifecycle.env_up(worktree, environment={}, production_contract=contract)
    identity = load_environment_identity(worktree)
    return worktree, contract, derive_environment_paths(identity)


def _cleanup(worktree: Path, contract) -> None:
    try:
        status = lifecycle.environment_status(worktree)["status"]
        if status == "ACTIVE":
            lifecycle.env_down(worktree, production_contract=contract)
        elif status == "STALE":
            lifecycle.env_down(
                worktree, recover_stale=True, production_contract=contract
            )
    except Exception:
        pass


def _prepare(worktree: Path, contract, **kwargs):
    return ready.prepare_application_ready(
        worktree,
        environment={},
        production_contract=contract,
        timestamp="2026-09-27T20:00:00Z",
        **kwargs,
    )


def test_prepare_creates_initialized_sqlite_fixture(tmp_path: Path) -> None:
    worktree, contract, paths = _active(tmp_path, _available_package_id("PKG-READY-DB"))
    try:
        result = _prepare(worktree, contract)
        assert result["applicationReady"] == "PASS"
        assert result["databaseInitialization"] == "READY"
        assert paths.database_path.is_file()
        with sqlite3.connect(paths.database_path) as conn:
            assert conn.execute("SELECT 1").fetchone()[0] == 1
    finally:
        _cleanup(worktree, contract)


def test_database_integrity_and_required_tables(tmp_path: Path) -> None:
    worktree, contract, paths = _active(tmp_path, _available_package_id("PKG-READY-TABLES"))
    try:
        _prepare(worktree, contract)
        with sqlite3.connect(paths.database_path) as conn:
            assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
        assert set(ready.REQUIRED_TABLES) <= tables
    finally:
        _cleanup(worktree, contract)


def test_database_initialization_is_idempotent(tmp_path: Path) -> None:
    worktree, contract, paths = _active(tmp_path, _available_package_id("PKG-READY-IDEMPOTENT"))
    try:
        first = _prepare(worktree, contract)
        with sqlite3.connect(paths.database_path) as conn:
            before = conn.execute(
                "SELECT version, name, checksum FROM schema_migrations ORDER BY version"
            ).fetchall()
        second = _prepare(worktree, contract)
        with sqlite3.connect(paths.database_path) as conn:
            after = conn.execute(
                "SELECT version, name, checksum FROM schema_migrations ORDER BY version"
            ).fetchall()
        assert before == after
        assert first["databaseMigrationVersion"] == second["databaseMigrationVersion"]
        assert second["applicationReady"] == "PASS"
    finally:
        _cleanup(worktree, contract)


def test_fake_secret_material_is_test_only_and_values_absent_from_receipt(
    tmp_path: Path,
) -> None:
    worktree, contract, paths = _active(tmp_path, _available_package_id("PKG-READY-SECRETS"))
    try:
        _prepare(worktree, contract)
        payload = json.loads(
            (paths.secret_root / "test-secrets.json").read_text(encoding="utf-8")
        )
        assert payload["mode"] == "fake-only"
        assert payload["productionCompatible"] is False
        receipt_text = paths.receipt_path.read_text(encoding="utf-8")
        receipt = json.loads(receipt_text)
        assert receipt["fakeSecretStatus"] == "READY"
        assert receipt["fakeSecretNames"] == sorted(payload["secrets"])
        for value in payload["secrets"].values():
            assert str(value).startswith("TEST_ONLY_NOT_A_CREDENTIAL::")
            assert value not in receipt_text
    finally:
        _cleanup(worktree, contract)


def test_real_provider_credentials_remain_absent(tmp_path: Path) -> None:
    worktree, contract, paths = _active(tmp_path, _available_package_id("PKG-READY-CREDS"))
    try:
        result = _prepare(worktree, contract)
        receipt = json.loads(paths.receipt_path.read_text(encoding="utf-8"))
        assert result["externalProviderCredentials"] == "ABSENT"
        assert receipt["externalProviderCredentials"] == "ABSENT"
        provider_text = (paths.state_root / "provider-config.json").read_text(
            encoding="utf-8"
        )
        assert "OPENROUTER_API_KEY" not in provider_text
        with pytest.raises(
            ready.ApplicationReadyError, match="REAL_PROVIDER_CREDENTIAL_PRESENT"
        ):
            ready.prepare_application_ready(
                worktree,
                environment={"OPENROUTER_API_KEY": "present-but-never-reported"},
                production_contract=contract,
            )
        assert "present-but-never-reported" not in paths.receipt_path.read_text(
            encoding="utf-8"
        )
    finally:
        _cleanup(worktree, contract)


def test_default_local_provider_endpoints_are_loopback(tmp_path: Path) -> None:
    worktree, contract, paths = _active(tmp_path, _available_package_id("PKG-READY-PROVIDERS"))
    try:
        _prepare(worktree, contract)
        providers = json.loads(
            (paths.state_root / "provider-config.json").read_text(encoding="utf-8")
        )
        assert providers["externalInternetAllowed"] is False
        assert providers["providerNetworkProbe"] == "NOT_RUN"
        assert providers["local"]["comfyui"]["endpoint"] == "http://127.0.0.1:8188"
        assert providers["local"]["ollama"]["endpoint"] == "http://127.0.0.1:11434"
        assert providers["local"]["qwen"]["endpoint"] == "http://127.0.0.1:8001"
        assert all(
            item["externalInternetAllowed"] is False
            for item in providers["external"].values()
        )
    finally:
        _cleanup(worktree, contract)


@pytest.mark.parametrize(
    "endpoint",
    (
        "https://127.0.0.1:8188",
        "http://example.com:8188",
        "http://user:pass@127.0.0.1:8188",
        "http://127.0.0.1:99999",
        "http://localhost",
    ),
)
def test_non_loopback_provider_endpoint_fails_closed(
    tmp_path: Path, endpoint: str
) -> None:
    worktree, contract, paths = _active(tmp_path, _available_package_id("PKG-READY-BAD-ENDPOINT"))
    try:
        with pytest.raises(ready.ApplicationReadyError):
            _prepare(
                worktree,
                contract,
                local_provider_endpoints={"comfyui": endpoint},
            )
        assert not paths.database_path.exists()
        assert not (paths.secret_root / "test-secrets.json").exists()
        assert not (paths.state_root / "provider-config.json").exists()
    finally:
        _cleanup(worktree, contract)


def test_prepare_updates_environment_receipt_application_ready(tmp_path: Path) -> None:
    worktree, contract, paths = _active(tmp_path, _available_package_id("PKG-READY-RECEIPT"))
    try:
        _prepare(worktree, contract)
        state = json.loads(paths.environment_state_path.read_text(encoding="utf-8"))
        receipt = json.loads(paths.receipt_path.read_text(encoding="utf-8"))
        for document in (state, receipt):
            assert document["databaseInitialization"] == "READY"
            assert document["databaseFixture"] == "IMPORT_SAFE_APPLICATION_SCHEMA"
            assert document["databaseIntegrity"] == "PASS"
            assert (
                document["databaseMigrationVersion"]
                == ready.CURRENT_REUSABLE_MIGRATION_VERSION
            )
            assert document["databaseRequiredTables"]["status"] == "PASS"
            assert document["fakeSecrets"] == "READY"
            assert document["externalProviderCredentials"] == "ABSENT"
            assert document["providerConfiguration"] == "READY"
            assert document["providerNetworkProbe"] == "NOT_RUN"
            assert document["applicationReady"] == "PASS"
            assert document["identityStartupFinalization"] == (
                "DEFERRED_TO_D1_NO_MAIN_IMPORT"
            )
    finally:
        _cleanup(worktree, contract)


def test_prepare_requires_owned_active_environment(tmp_path: Path) -> None:
    worktree, contract = _package(tmp_path, "PKG-READY-NOT-ACTIVE")
    with pytest.raises(ready.ApplicationReadyError, match="ENVIRONMENT_NOT_ACTIVE"):
        _prepare(worktree, contract)


def test_prepare_failure_does_not_report_application_ready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    worktree, contract, paths = _active(tmp_path, _available_package_id("PKG-READY-FAIL"))
    original_receipt = paths.receipt_path.read_text(encoding="utf-8")

    def fail_database(database_path: Path, *, stamp: str):
        database_path.parent.mkdir(parents=True, exist_ok=True)
        database_path.write_bytes(b"partial")
        raise RuntimeError("synthetic database failure")

    monkeypatch.setattr(ready, "_initialize_database", fail_database)
    try:
        with pytest.raises(
            ready.ApplicationReadyError, match="APPLICATION_READY_PREPARE_FAILED"
        ):
            _prepare(worktree, contract)
        assert not (paths.environment_root / "db").exists()
        assert not paths.media_root.exists()
        assert not paths.secret_root.exists()
        assert not (paths.state_root / "provider-config.json").exists()
        receipt = paths.receipt_path.read_text(encoding="utf-8")
        assert receipt == original_receipt
        assert '"applicationReady": "PASS"' not in receipt
    finally:
        _cleanup(worktree, contract)


def test_env_down_removes_database_and_fake_secret_payload(tmp_path: Path) -> None:
    worktree, contract, paths = _active(tmp_path, _available_package_id("PKG-READY-DOWN"))
    _prepare(worktree, contract)
    assert paths.database_path.is_file()
    assert (paths.secret_root / "test-secrets.json").is_file()
    down = lifecycle.env_down(worktree, production_contract=contract)
    assert down["status"] == "STOPPED"
    assert not (paths.environment_root / "db").exists()
    assert not paths.media_root.exists()
    assert not paths.secret_root.exists()
    stopped = json.loads(paths.receipt_path.read_text(encoding="utf-8"))
    assert stopped["state"] == "stopped"
    assert stopped["cleanup"] == "PASS"


def test_env_ready_module_does_not_import_backend_main() -> None:
    source = Path(ready.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    assert "backend.main" not in imports


def _run_agent_with_fake_python(tmp_path: Path, *, ready_fails: bool, cleanup_fails: bool = False):
    import os
    import shutil
    import subprocess

    powershell = shutil.which("powershell.exe")
    if os.name != "nt" or not powershell:
        pytest.skip("PowerShell orchestration test requires Windows")
    repo = tmp_path / "repo"
    tools = repo / "tools"
    tools.mkdir(parents=True)
    source_script = Path(__file__).resolve().parents[1] / "tools" / "agent.ps1"
    (tools / "agent.ps1").write_text(source_script.read_text(encoding="utf-8"), encoding="utf-8")
    shim = tmp_path / "shim"
    shim.mkdir()
    log = tmp_path / "calls.log"
    fail_line = 'if "%*"=="-m tools.agent_system.env_ready --repo-root ' + str(repo) + ' prepare" exit /b 23' if ready_fails else ""
    down_fail_line = 'if "%*"=="-m tools.agent_system.env_lifecycle --repo-root ' + str(repo) + ' down" exit /b 41' if cleanup_fails else ""
    cleanup_fail_line = 'if "%*"=="-m tools.agent_system.env_ready --repo-root ' + str(repo) + ' cleanup" exit /b 42' if cleanup_fails else ""
    (shim / "python.cmd").write_text(
        "@echo off\r\n"
        f"echo %*>>\"{log}\"\r\n"
        f"{fail_line}\r\n"
        f"{down_fail_line}\r\n"
        f"{cleanup_fail_line}\r\n"
        "exit /b 0\r\n",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["PATH"] = str(shim) + os.pathsep + str(Path(powershell).parent)
    result = subprocess.run(
        [powershell, "-NoProfile", "-File", str(tools / "agent.ps1"), "env-up", "-RepoRoot", str(repo)],
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )
    return result, log.read_text(encoding="utf-8").splitlines()


def test_agent_env_up_orchestration_lifecycle_then_ready(tmp_path: Path) -> None:
    result, calls = _run_agent_with_fake_python(tmp_path, ready_fails=False)
    assert result.returncode == 0, result.stderr
    assert "tools.agent_system.env_lifecycle" in calls[0] and calls[0].endswith(" up")
    assert "tools.agent_system.env_ready" in calls[1] and calls[1].endswith(" prepare")
    assert len(calls) == 2


def test_agent_env_up_ready_failure_invokes_owned_cleanup(tmp_path: Path) -> None:
    result, calls = _run_agent_with_fake_python(tmp_path, ready_fails=True)
    assert result.returncode == 23
    assert "tools.agent_system.env_lifecycle" in calls[0] and calls[0].endswith(" up")
    assert "tools.agent_system.env_ready" in calls[1] and calls[1].endswith(" prepare")
    assert "tools.agent_system.env_lifecycle" in calls[2] and calls[2].endswith(" down")
    assert "tools.agent_system.env_ready" in calls[3] and calls[3].endswith(" cleanup")


def test_agent_env_up_cleanup_failures_preserve_ready_error(tmp_path: Path) -> None:
    result, calls = _run_agent_with_fake_python(
        tmp_path, ready_fails=True, cleanup_fails=True
    )
    assert result.returncode == 23
    assert "env_lifecycle" in calls[2] and calls[2].endswith(" down")
    assert "env_ready" in calls[3] and calls[3].endswith(" cleanup")


ROOT = Path(__file__).resolve().parents[1]


def _write_synthetic_production_contract(worktree: Path) -> None:
    promoter = worktree / "ops" / "release" / "promote-project-release.ps1"
    promoter.parent.mkdir(parents=True, exist_ok=True)
    promoter.write_text(
        "$database = 'C:\\IZO_ASA_TEST_PRODUCTION\\db\\app.sqlite3'\n"
        "if ($database.StartsWith('C:\\IZO_ASA_TEST_PRODUCTION\\db')) { }\n"
        "Set-ServiceEnvironmentValue -Document $xml -Name 'IZO_SECRET_DIR' "
        "-Value 'C:\\IZO_ASA_TEST_PRODUCTION\\secrets'\n",
        encoding="utf-8",
    )


def _cli_environment() -> dict[str, str]:
    blocked_prefixes = ("OPENROUTER", "TELEGRAM", "MAX", "SMTP", "VK", "YOOKASSA")
    blocked_paths = {"DATABASE_URL", "MEDIA_DIR", "IZO_SECRET_DIR"}
    environment = {
        key: value
        for key, value in os.environ.items()
        if key.upper() not in blocked_paths
        and not any(
            key.upper() == prefix or key.upper().startswith(prefix + "_")
            for prefix in blocked_prefixes
        )
    }
    environment["PYTHONPATH"] = str(ROOT)
    return environment


def _agent_cli(worktree: Path, *args: str) -> subprocess.CompletedProcess[str]:
    executable = "powershell.exe" if os.name == "nt" else "pwsh"
    return subprocess.run(
        [
            executable,
            "-NoProfile",
            "-File",
            str(ROOT / "tools" / "agent.ps1"),
            *args,
            "-RepoRoot",
            str(worktree),
        ],
        text=True,
        capture_output=True,
        env=_cli_environment(),
        check=False,
        timeout=30,
    )


@pytest.mark.skipif(os.name != "nt", reason="Public agent CLI is Windows PowerShell.")
def test_agent_env_up_orchestration_reaches_ready_and_env_down_cleans(
    tmp_path: Path,
) -> None:
    worktree, _contract_value = _package(tmp_path, _available_package_id("PKG-READY-CLI"))
    _write_synthetic_production_contract(worktree)
    up = _agent_cli(worktree, "env-up")
    assert up.returncode == 0, up.stderr or up.stdout
    paths = derive_environment_paths(load_environment_identity(worktree))
    receipt = json.loads(paths.receipt_path.read_text(encoding="utf-8"))
    assert receipt["state"] == "active"
    assert receipt["applicationReady"] == "PASS"
    assert paths.database_path.is_file()
    assert (paths.secret_root / "test-secrets.json").is_file()

    down = _agent_cli(worktree, "env-down")
    assert down.returncode == 0, down.stderr or down.stdout
    assert not (paths.environment_root / "db").exists()
    assert not paths.secret_root.exists()


@pytest.mark.skipif(os.name != "nt", reason="Public agent CLI is Windows PowerShell.")
def test_agent_env_up_ready_failure_runs_owned_cleanup(tmp_path: Path) -> None:
    worktree, _contract_value = _package(tmp_path, _available_package_id("PKG-READY-CLI-FAIL"))
    _write_synthetic_production_contract(worktree)
    result = _agent_cli(
        worktree,
        "env-up",
        "-ComfyUIEndpoint",
        "http://example.com:8188",
    )
    assert result.returncode == 2
    assert "PROVIDER_ENDPOINT_NON_LOOPBACK provider=comfyui" in result.stderr
    paths = derive_environment_paths(load_environment_identity(worktree))
    status = lifecycle.environment_status(worktree)
    assert status["status"] == "STOPPED"
    assert not (paths.environment_root / "db").exists()
    assert not paths.media_root.exists()
    assert not paths.secret_root.exists()
