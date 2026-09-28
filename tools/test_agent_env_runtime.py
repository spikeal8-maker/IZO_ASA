from __future__ import annotations

import json
import os
import runpy
import sqlite3
from pathlib import Path

import pytest

from backend.app.config import load_local_env
from tools.agent_system import env_lifecycle as lifecycle
from tools.agent_system import env_ready as ready
from tools.agent_system.env import derive_environment_paths, load_environment_identity
from tools.test_agent_env_ready import (
    _agent_cli,
    _active,
    _available_package_id,
    _cleanup as _lifecycle_cleanup,
    _package,
    _prepare,
    _write_synthetic_production_contract,
)


def _runtime(paths) -> tuple[Path, dict[str, object]]:
    path = paths.state_root / "runtime-environment.json"
    return path, json.loads(path.read_text(encoding="utf-8"))

def _cleanup(worktree: Path, contract) -> None:
    _lifecycle_cleanup(worktree, contract)
    ready.cleanup_runtime_environment(worktree)

def _secret_store_api():
    path = Path(__file__).resolve().parents[1] / "backend/app/security/secret_store.py"
    return runpy.run_path(str(path))


def test_payment_notification_outbox_exists(tmp_path: Path) -> None:
    worktree, contract, paths = _active(tmp_path, "PKG-RUNTIME-BILLING")
    try:
        _prepare(worktree, contract)
        with sqlite3.connect(paths.database_path) as conn:
            row = conn.execute(
                "SELECT 1 FROM sqlite_master "
                "WHERE type='table' AND name='payment_notification_outbox'"
            ).fetchone()
        assert row == (1,)
    finally:
        _cleanup(worktree, contract)


def test_runtime_contract_routes_package_owned_state_and_disables_bots(
    tmp_path: Path,
) -> None:
    worktree, contract, paths = _active(tmp_path, "PKG-RUNTIME-CONTRACT")
    try:
        _prepare(worktree, contract)
        runtime_path, runtime = _runtime(paths)
        assert runtime_path.is_file()
        assert runtime["contractId"] == ready.RUNTIME_CONTRACT_ID
        assert runtime["inheritAmbient"] is False
        assert runtime["backendDotEnvAllowed"] is False
        assert runtime["backendDotEnvInheritance"] == "FORBIDDEN"
        assert runtime["hostSecretStoreInheritance"] == "FORBIDDEN"
        assert runtime["externalInternetAllowed"] is False
        child = runtime["environment"]
        external = Path(child["IZO_SECRET_DIR"])
        _secret_store_api()["assert_secret_store_outside_repository"](external, worktree)
        assert external.is_dir() and not any(external.iterdir())
        assert not external.resolve().is_relative_to(worktree.resolve())
        assert all(not external.resolve().is_relative_to(Path(root).resolve()) for root in contract.all_roots)
        assert child["DATABASE_URL"] == runtime["routing"]["DATABASE_URL"] == str(paths.database_path)
        assert child["MEDIA_DIR"] == runtime["routing"]["MEDIA_DIR"] == str(paths.media_root)
        assert child["IZO_SECRET_DIR"] == runtime["routing"]["IZO_SECRET_DIR"] == str(external)
        assert child["APP_ENV"] == child["ENV"] == child["MODE"] == "test"
        assert child["BOT_MODE"] == child["BOT_UPDATES_MODE"] == child["MAX_UPDATES_MODE"] == "disabled"
        assert child["TELEGRAM_POLLING_ENABLED"] == child["MAX_POLLING_ENABLED"] == "false"
        assert runtime["runtimeLabels"] == {
            "APP_ENV": "test",
            "ENV": "test",
            "MODE": "test",
        }
        assert runtime["botActivity"] == {
            "BOT_MODE": "disabled",
            "BOT_UPDATES_MODE": "disabled",
            "TELEGRAM_POLLING_ENABLED": False,
            "MAX_UPDATES_MODE": "disabled",
            "MAX_POLLING_ENABLED": False,
        }
        receipt = json.loads(paths.receipt_path.read_text(encoding="utf-8"))
        assert receipt["runtimeEnvironment"] == "READY"
        assert receipt["runtimeEnvironmentContract"] == str(runtime_path)
        assert receipt["inheritAmbient"] is False
        assert receipt["backendDotEnvInheritance"] == "FORBIDDEN"
        assert receipt["hostSecretStoreInheritance"] == "FORBIDDEN"
        assert receipt["databaseRouting"] == "PACKAGE_OWNED"
        assert receipt["mediaRouting"] == "PACKAGE_OWNED"
        assert receipt["externalProviderEffects"] == "DISABLED"
        assert receipt["applicationReady"] == "PASS"
    finally:
        _cleanup(worktree, contract)


def test_runtime_contract_local_providers_and_credentials_are_non_production(
    tmp_path: Path,
) -> None:
    worktree, contract, paths = _active(tmp_path, "PKG-RUNTIME-PROVIDERS")
    try:
        _prepare(worktree, contract)
        _, runtime = _runtime(paths)
        assert runtime["localProviders"] == {
            "COMFYUI_BASE_URL": "http://127.0.0.1:8188",
            "OLLAMA_BASE_URL": "http://127.0.0.1:11434",
            "QWEN_ASR_BASE_URL": "http://127.0.0.1:8001",
        }
        assert set(runtime["credentials"]) == set(ready.RUNTIME_CREDENTIAL_VARIABLES)
        assert all(
            item == {"inherit": False, "productionCredential": "ABSENT"}
            for item in runtime["credentials"].values()
        )
        child = runtime["environment"]
        assert {name: child[name] for name in runtime["localProviders"]} == runtime["localProviders"]
        assert all(child[name] == "" for name in ready.RUNTIME_CREDENTIAL_VARIABLES)
    finally:
        _cleanup(worktree, contract)


def test_runtime_contract_never_copies_ambient_values_and_unisender_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    worktree, contract, paths = _active(tmp_path, "PKG-RUNTIME-AMBIENT")
    try:
        marker = "ambient-value-must-not-serialize"
        ready.prepare_application_ready(
            worktree,
            environment={"UNRELATED_HOST_VALUE": marker},
            production_contract=contract,
            timestamp="2026-09-28T00:00:00Z",
        )
        runtime_path, runtime = _runtime(paths)
        assert marker not in runtime_path.read_text(encoding="utf-8")
        child = runtime["environment"]
        dotenv = tmp_path / "dotenv"
        dotenv.mkdir()
        (dotenv / ".env").write_text("OPENROUTER_API_KEY=from-dotenv\n", encoding="utf-8")
        monkeypatch.setenv("OPENROUTER_API_KEY", child["OPENROUTER_API_KEY"])
        load_local_env(dotenv)
        assert os.environ["OPENROUTER_API_KEY"] == ""
        monkeypatch.setenv("IZO_SECRET_DIR", child["IZO_SECRET_DIR"])
        assert _secret_store_api()["default_secret_store_dir"]() == Path(child["IZO_SECRET_DIR"]).resolve()
        with pytest.raises(
            ready.ApplicationReadyError, match="REAL_PROVIDER_CREDENTIAL_PRESENT"
        ):
            ready.prepare_application_ready(
                worktree,
                environment={"UNISENDER_API_KEY": "real-value-must-not-leak"},
                production_contract=contract,
            )
        assert "real-value-must-not-leak" not in runtime_path.read_text(encoding="utf-8")
        assert "real-value-must-not-leak" not in paths.receipt_path.read_text(
            encoding="utf-8"
        )
    finally:
        _cleanup(worktree, contract)


def test_runtime_materialization_failure_blocks_application_ready_and_cleans_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package_id = _available_package_id("PKG-RUNTIME-FAIL")
    worktree, contract, paths = _active(tmp_path, package_id)
    original_receipt = paths.receipt_path.read_text(encoding="utf-8")
    external = ready._runtime_secret_store_path(paths)

    def fail_runtime(*_args, **_kwargs):
        external.mkdir(parents=True, exist_ok=True)
        raise ready.ApplicationReadyError("RUNTIME_ENVIRONMENT_WRITE_FAILED")

    monkeypatch.setattr(ready, "_write_runtime_environment", fail_runtime)
    try:
        with pytest.raises(
            ready.ApplicationReadyError, match="RUNTIME_ENVIRONMENT_WRITE_FAILED"
        ):
            _prepare(worktree, contract)
        assert paths.receipt_path.read_text(encoding="utf-8") == original_receipt
        assert '"applicationReady": "PASS"' not in original_receipt
        assert not (paths.environment_root / "db").exists()
        assert not paths.media_root.exists()
        assert not paths.secret_root.exists()
        assert not (paths.state_root / "provider-config.json").exists()
        assert not (paths.state_root / "runtime-environment.json").exists()
        assert not external.exists()
    finally:
        _cleanup(worktree, contract)


@pytest.mark.skipif(os.name != "nt", reason="Public agent CLI is Windows PowerShell.")
def test_public_env_down_removes_runtime_contract(tmp_path: Path) -> None:
    package_id = _available_package_id("PKG-RUNTIME-DOWN")
    worktree, _contract_value = _package(tmp_path, package_id)
    _write_synthetic_production_contract(worktree)
    up = _agent_cli(worktree, "env-up")
    assert up.returncode == 0, up.stderr or up.stdout
    paths = derive_environment_paths(load_environment_identity(worktree))
    runtime_path = paths.state_root / "runtime-environment.json"
    assert runtime_path.is_file()
    external = Path(json.loads(runtime_path.read_text(encoding="utf-8"))["environment"]["IZO_SECRET_DIR"])
    assert external.is_dir()
    down = _agent_cli(worktree, "env-down")
    assert down.returncode == 0, down.stderr or down.stdout
    assert lifecycle.environment_status(worktree)["status"] == "STOPPED"
    assert not runtime_path.exists()
    assert not external.exists()
