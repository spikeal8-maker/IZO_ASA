from __future__ import annotations

import json
import os
import runpy
import sqlite3
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from backend.app.config import load_local_env
from tools.agent_system import env_lifecycle as lifecycle
from tools.agent_system import env_runtime as runtime_contract
from tools.agent_system import env_secret_store as secret_store
from tools.agent_system import env_ready as ready
from tools.agent_system.env import (
    CREDENTIAL_CLASSIFICATIONS,
    derive_environment_paths,
    load_environment_identity,
)
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
    worktree, contract, paths = _active(tmp_path, _available_package_id("PKG-RUNTIME-BILLING"))
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
    worktree, contract, paths = _active(tmp_path, _available_package_id("PKG-RUNTIME-CONTRACT"))
    try:
        _prepare(worktree, contract)
        runtime_path, runtime = _runtime(paths)
        assert runtime_path.is_file()
        assert runtime["contractId"] == runtime_contract.RUNTIME_CONTRACT_ID
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
    worktree, contract, paths = _active(tmp_path, _available_package_id("PKG-RUNTIME-PROVIDERS"))
    try:
        _prepare(worktree, contract)
        _, runtime = _runtime(paths)
        assert runtime["localProviders"] == {
            "COMFYUI_BASE_URL": "http://127.0.0.1:8188",
            "OLLAMA_BASE_URL": "http://127.0.0.1:11434",
            "QWEN_ASR_BASE_URL": "http://127.0.0.1:8001",
        }
        assert set(runtime["credentials"]) == set(runtime_contract.EMPTY_CREDENTIAL_KEYS)
        assert all(
            item == {"inherit": False, "productionCredential": "ABSENT"}
            for item in runtime["credentials"].values()
        )
        child = runtime["environment"]
        assert {name: child[name] for name in runtime["localProviders"]} == runtime["localProviders"]
        assert all(child[name] == "" for name in runtime_contract.EMPTY_CREDENTIAL_KEYS)
    finally:
        _cleanup(worktree, contract)


def test_runtime_contract_never_copies_ambient_values_and_unisender_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    worktree, contract, paths = _active(tmp_path, _available_package_id("PKG-RUNTIME-AMBIENT"))
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




def test_planner_credentials_converge_into_exact_empty_child_environment(
    tmp_path: Path,
) -> None:
    assert set(CREDENTIAL_CLASSIFICATIONS) <= set(runtime_contract.EMPTY_CREDENTIAL_KEYS)
    worktree, contract, paths = _active(tmp_path, _available_package_id("PKG-RUNTIME-CREDENTIAL-CONVERGENCE"))
    try:
        _prepare(worktree, contract)
        _, document = _runtime(paths)
        child = document["environment"]
        assert set(child) == runtime_contract.REVIEWED_CHILD_ENVIRONMENT_KEYS
        assert all(child[name] == "" for name in CREDENTIAL_CLASSIFICATIONS)
        assert child["YOOKASSA_SHOP_ID"] == ""
    finally:
        _cleanup(worktree, contract)


def test_backend_dotenv_cannot_reintroduce_protected_or_external_values(
    tmp_path: Path,
) -> None:
    worktree, contract, paths = _active(tmp_path, _available_package_id("PKG-RUNTIME-DOTENV-BLOCK"))
    try:
        _prepare(worktree, contract)
        _, document = _runtime(paths)
        child = dict(document["environment"])
        dotenv = tmp_path / "synthetic-backend"
        dotenv.mkdir()
        poisoned = {
            "SESSION_HMAC_SECRET": "production-marker",
            "ADMIN_ONE_TIME_CODE": "production-marker",
            "RUNTIME_SYNTHETIC_KEY": "production-marker",
            "YOOKASSA_SHOP_ID": "production-marker",
            "OPENROUTER_API_KEY": "production-marker",
            "UNISENDER_API_KEY": "production-marker",
            "RUNTIME_ALERT_WEBHOOK_URL": "https://example.invalid/hook",
            "LOCAL_LTX_COMFYUI_BASE_URL": "https://example.invalid/",
            "LOCAL_LTX_ENABLED": "true",
            "EMAIL_OTP_DEBUG_RETURN_CODE": "true",
            "OPENROUTER_BASE_URL": "https://example.invalid/openrouter",
            "MAX_API_BASE_URL": "https://example.invalid/max",
            "MAX_WEBHOOK_URL": "https://example.invalid/max-hook",
            "BACKEND_PUBLIC_URL": "https://example.invalid/backend",
            "CBR_DAILY_XML_URL": "https://example.invalid/cbr",
            "USD_RUB_FALLBACK_URL": "https://example.invalid/fx",
        }
        (dotenv / ".env").write_text(
            "".join(f"{key}={value}\n" for key, value in poisoned.items()),
            encoding="utf-8",
        )
        with patch.dict(os.environ, child, clear=True):
            load_local_env(dotenv)
            assert all(os.environ[name] == "" for name in CREDENTIAL_CLASSIFICATIONS)
            assert os.environ["SESSION_HMAC_SECRET"] == ""
            assert os.environ["ADMIN_ONE_TIME_CODE"] == ""
            assert os.environ["RUNTIME_SYNTHETIC_KEY"] == ""
            assert os.environ["YOOKASSA_SHOP_ID"] == ""
            assert os.environ["UNISENDER_API_KEY"] == ""
            assert os.environ["EMAIL_OTP_DEBUG_RETURN_CODE"] == "false"
            assert os.environ["LOCAL_LTX_ENABLED"] == "false"
            assert os.environ["LOCAL_LTX_COMFYUI_BASE_URL"] == child["COMFYUI_BASE_URL"]
            assert os.environ["RUNTIME_ALERT_WEBHOOK_URL"] == ""
            for key, expected in runtime_contract.NEUTRALIZED_EXTERNAL_ENVIRONMENT.items():
                assert os.environ[key] == expected
        assert document["externalInternetAllowed"] is False
        assert document["neutralizedExternalEnvironment"] == (
            runtime_contract.NEUTRALIZED_EXTERNAL_ENVIRONMENT
        )
    finally:
        _cleanup(worktree, contract)


def test_runtime_alert_is_disabled_before_http_and_external_urls_are_loopback(
    tmp_path: Path,
) -> None:
    worktree, contract, paths = _active(tmp_path, _available_package_id("PKG-RUNTIME-NETWORK-NEUTRAL"))
    try:
        _prepare(worktree, contract)
        _, document = _runtime(paths)
        child = document["environment"]
        assert child["RUNTIME_ALERT_WEBHOOK_URL"] == ""
        for key in (
            "OPENROUTER_BASE_URL",
            "MAX_API_BASE_URL",
            "CBR_DAILY_XML_URL",
            "USD_RUB_FALLBACK_URL",
        ):
            assert child[key] == runtime_contract.DISABLED_LOOPBACK_URL
        source = (Path(__file__).resolve().parents[1] / "backend/main.py").read_text(
            encoding="utf-8"
        )
        start = source.index("async def _send_runtime_alert")
        end = source.index("\ndef _check_runtime_error_rate", start)
        alert_source = source[start:end]
        assert 'os.getenv("RUNTIME_ALERT_WEBHOOK_URL", "").strip()' in alert_source
        assert "if not webhook:" in alert_source
        assert "await client.post" in alert_source
        assert document["externalInternetAllowed"] is False
    finally:
        _cleanup(worktree, contract)


def test_production_temp_root_rejected_before_secret_store_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package_id = _available_package_id("PKG-RUNTIME-PREWRITE-PROD")
    worktree, contract, paths = _active(tmp_path, package_id)
    production_root = Path(contract.secret_roots[-1])
    production_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(secret_store.tempfile, "gettempdir", lambda: str(production_root))
    managed_parent = production_root.resolve() / "izo-asa-agent-secrets"
    try:
        with pytest.raises(ready.ApplicationReadyError, match="RUNTIME_SECRET_STORE_PATH_REJECTED"):
            _prepare(worktree, contract)
        assert not managed_parent.exists()
    finally:
        _cleanup(worktree, contract)


def test_worktree_temp_root_rejected_before_secret_store_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package_id = _available_package_id("PKG-RUNTIME-PREWRITE-WORKTREE")
    worktree, contract, paths = _active(tmp_path, package_id)
    temp_base = worktree / "synthetic-system-temp"
    temp_base.mkdir()
    monkeypatch.setattr(secret_store.tempfile, "gettempdir", lambda: str(temp_base))
    managed_parent = temp_base.resolve() / "izo-asa-agent-secrets"
    try:
        with pytest.raises(ready.ApplicationReadyError, match="RUNTIME_SECRET_STORE_PATH_REJECTED"):
            _prepare(worktree, contract)
        assert temp_base.is_dir()
        assert not managed_parent.exists()
    finally:
        _cleanup(worktree, contract)


@pytest.mark.parametrize("boundary", ("temp", "parent", "leaf"))
def test_external_secret_store_rejects_each_known_production_boundary_prewrite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, boundary: str
) -> None:
    package_id = _available_package_id("PKG-RUNTIME-PREWRITE-BOUNDARY")
    worktree, contract, paths = _active(tmp_path, package_id)
    temp_base = tmp_path / "system-temp"
    temp_base.mkdir()
    monkeypatch.setattr(secret_store.tempfile, "gettempdir", lambda: str(temp_base))
    parent, leaf, marker = secret_store.canonical_external_secret_store(paths.environment_root)
    production_root = {"temp": temp_base.resolve(), "parent": parent, "leaf": leaf}[boundary]
    try:
        with pytest.raises(secret_store.ExternalSecretStoreError, match="RUNTIME_SECRET_STORE_PATH_REJECTED"):
            secret_store.prepare_external_secret_store(
                paths.environment_root, package_id, "synthetic-lease",
                allow_existing=False, production_roots=(str(production_root),),
            )
        assert not parent.exists()
        assert not leaf.exists()
        assert not marker.exists()
    finally:
        _cleanup(worktree, contract)


@pytest.mark.skipif(os.name != "nt", reason="Actual Windows junction challenge.")
def test_windows_external_secret_store_junction_challenges(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package_id = _available_package_id("PKG-RUNTIME-JUNCTION")
    worktree, contract, paths = _active(tmp_path, package_id)
    original_receipt = paths.receipt_path.read_text(encoding="utf-8")
    external = ready._runtime_secret_store_path(paths)
    def junction(link: Path, target: Path) -> None:
        target.mkdir(parents=True, exist_ok=True)
        link.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["cmd.exe", "/d", "/c", "mklink", "/J", str(link), str(target)], check=True)

    try:
        external.mkdir(parents=True)
        with pytest.raises(ready.ApplicationReadyError, match="OWNERSHIP_INVALID"):
            _prepare(worktree, contract)
        external.rmdir()

        target = Path(contract.secret_roots[-1])
        marker = target / "production.marker"
        target.mkdir(parents=True, exist_ok=True)
        marker.write_text("preserve", encoding="utf-8")
        junction(external, target)
        assert secret_store.is_reparse_point(external)
        ready.cleanup_runtime_environment(worktree)
        assert not external.exists() and target.is_dir() and marker.is_file()

        junction(external, target)
        with pytest.raises(ready.ApplicationReadyError, match="RUNTIME_SECRET_STORE_REPARSE_POINT"):
            _prepare(worktree, contract)
        assert not external.exists() and marker.read_text(encoding="utf-8") == "preserve"
        assert paths.receipt_path.read_text(encoding="utf-8") == original_receipt
        assert not any(path.exists() for path in (paths.environment_root / "db", paths.media_root, paths.secret_root))
        assert not any((paths.state_root / name).exists() for name in ("provider-config.json", "runtime-environment.json"))

        system_temp = tmp_path / "system-temp"
        system_temp.mkdir()
        monkeypatch.setattr(secret_store.tempfile, "gettempdir", lambda: str(system_temp))
        parent, _leaf, _owner = secret_store.canonical_external_secret_store(paths.environment_root)
        parent_target = tmp_path / "parent-target"
        parent_marker = parent_target / "production.marker"
        parent_target.mkdir()
        parent_marker.write_text("preserve", encoding="utf-8")
        junction(parent, parent_target)
        with pytest.raises(ready.ApplicationReadyError, match="RUNTIME_SECRET_STORE_REPARSE_POINT"):
            _prepare(worktree, contract)
        assert parent_marker.read_text(encoding="utf-8") == "preserve"
        assert list(parent_target.iterdir()) == [parent_marker]
        os.rmdir(parent)
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


@pytest.mark.skipif(os.name != "nt", reason="Public agent CLI is Windows PowerShell.")
def test_repeated_ready_failure_removes_ready_resources(tmp_path: Path) -> None:
    package_id = _available_package_id("PKG-RUNTIME-REPEATED-READY")
    worktree, contract = _package(tmp_path, package_id)
    _write_synthetic_production_contract(worktree)
    try:
        first = _agent_cli(worktree, "env-up")
        assert first.returncode == 0, first.stderr or first.stdout
        paths = derive_environment_paths(load_environment_identity(worktree))
        runtime_path, document = _runtime(paths)
        external = Path(document["environment"]["IZO_SECRET_DIR"])
        _parent, leaf, owner = secret_store.canonical_external_secret_store(
            paths.environment_root
        )
        assert external == leaf and external.is_dir() and owner.is_file()

        second = _agent_cli(
            worktree, "env-up", "-ComfyUIEndpoint", "http://example.com:8188"
        )
        assert second.returncode == 2
        assert lifecycle.environment_status(worktree)["status"] == "STOPPED"
        assert not runtime_path.exists()
        assert not external.exists()
        assert not owner.exists()
        assert not (paths.environment_root / "db").exists()
        assert not paths.media_root.exists()
        assert not paths.secret_root.exists()
        stopped = json.loads(paths.receipt_path.read_text(encoding="utf-8"))
        assert not lifecycle._port_open(int(stopped["ports"]["backend"]))
        assert not lifecycle._port_open(int(stopped["ports"]["frontend"]))
    finally:
        _cleanup(worktree, contract)
