"""Application-ready isolated fixture for an ACTIVE agent environment.

This module is deliberately import-safe: it reuses backend.app.database primitives,
never imports backend.main, never starts the application, and never probes providers.
"""
from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import shutil
import sys
from pathlib import Path
from typing import Mapping
from urllib.parse import urlsplit

from backend.app.database import (
    apply_account_verification_migration,
    apply_admin_notification_delivery_migration,
    apply_admin_notifications_migration,
    apply_generation_trial_migration,
    apply_phone_chat_history_migration,
    apply_phone_chat_request_lifecycle_migration,
    ensure_migration_ledger,
    finalize_legacy_schema_baseline,
    initialize_media_schema_group,
    open_sqlite,
    prepare_core_schema_group,
    prepare_identity_schema_group,
    seed_core_defaults,
    seed_default_challenge,
)
from backend.app.database.migrations import PHONE_CHAT_REQUEST_LIFECYCLE_MIGRATION

from .env import (
    CONTRACT_ID,
    EXTERNAL_PROVIDERS,
    EnvironmentContractError,
    ProductionPathContract,
    derive_environment_paths,
    discover_production_path_contract,
    inspect_provider_credentials,
    load_environment_identity,
    utc_now,
    validate_environment_paths,
)
from .env_lifecycle import environment_status
from .registry import atomic_write_text, resolve_repo_root


READY_CONTRACT_ID = "izo.agent-env.ready.v1"
CURRENT_REUSABLE_MIGRATION_VERSION = PHONE_CHAT_REQUEST_LIFECYCLE_MIGRATION.version
REQUIRED_TABLES = (
    "users",
    "jobs",
    "images",
    "schema_migrations",
    "auth_identities",
    "auth_sessions",
    "admin_notifications",
    "admin_notification_delivery_outbox",
    "account_verifications",
    "phone_chat_threads",
    "phone_chat_requests",
)
DEFAULT_LOCAL_PROVIDER_ENDPOINTS = {
    "comfyui": "http://127.0.0.1:8188",
    "ollama": "http://127.0.0.1:11434",
    "qwen": "http://127.0.0.1:8001",
}
FAKE_SECRET_NAMES = ("test_session_signing", "test_csrf_signing")


class ApplicationReadyError(RuntimeError):
    """Fail-closed application-ready preparation error."""


def _render(payload: Mapping[str, object]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def _load_active_owned_state(repo: Path):
    identity = load_environment_identity(repo)
    paths = derive_environment_paths(identity)
    if environment_status(repo).get("status") != "ACTIVE":
        raise ApplicationReadyError("ENVIRONMENT_NOT_ACTIVE")
    try:
        state = json.loads(paths.environment_state_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise ApplicationReadyError("ENVIRONMENT_STATE_INVALID") from None
    expected = {
        "contractId": CONTRACT_ID,
        "packageId": identity.package_id,
        "worktreePath": str(identity.worktree_path),
        "state": "active",
    }
    if not isinstance(state, dict) or any(state.get(k) != v for k, v in expected.items()):
        raise ApplicationReadyError("ENVIRONMENT_STATE_OWNERSHIP_INVALID")
    return identity, paths, state


def _validated_loopback_endpoint(name: str, value: str) -> str:
    raw = str(value or "").strip()
    try:
        parsed = urlsplit(raw)
        port = parsed.port
    except ValueError:
        raise ApplicationReadyError(f"PROVIDER_ENDPOINT_INVALID provider={name}") from None
    if (
        parsed.scheme.lower() != "http"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or port is None
        or not 1 <= port <= 65535
    ):
        raise ApplicationReadyError(f"PROVIDER_ENDPOINT_INVALID provider={name}")
    host = parsed.hostname.rstrip(".").lower()
    if host == "localhost":
        loopback = True
    else:
        try:
            loopback = ipaddress.ip_address(host).is_loopback
        except ValueError:
            loopback = False
    if not loopback:
        raise ApplicationReadyError(f"PROVIDER_ENDPOINT_NON_LOOPBACK provider={name}")
    return raw


def build_provider_configuration(
    local_provider_endpoints: Mapping[str, str] | None = None,
) -> dict[str, object]:
    supplied = dict(local_provider_endpoints or {})
    unknown = sorted(set(supplied) - set(DEFAULT_LOCAL_PROVIDER_ENDPOINTS))
    if unknown:
        raise ApplicationReadyError(
            "PROVIDER_NAME_UNSUPPORTED provider=" + ",".join(unknown)
        )
    local: dict[str, object] = {}
    for name, default in DEFAULT_LOCAL_PROVIDER_ENDPOINTS.items():
        endpoint = _validated_loopback_endpoint(name, supplied.get(name, default))
        local[name] = {
            "mode": "local-configurable",
            "endpoint": endpoint,
            "externalInternetAllowed": False,
        }
    external = {
        name: {
            "mode": "disabled/fake",
            "externalInternetAllowed": False,
            "credentials": "ABSENT",
        }
        for name in EXTERNAL_PROVIDERS
    }
    return {
        "externalInternetAllowed": False,
        "providerNetworkProbe": "NOT_RUN",
        "external": external,
        "local": local,
    }


def _assert_real_provider_credentials_absent(
    environment: Mapping[str, str] | None,
) -> None:
    present = [
        str(item["credentialName"])
        for item in inspect_provider_credentials(environment)
        if bool(item.get("present"))
    ]
    if present:
        raise ApplicationReadyError(
            "REAL_PROVIDER_CREDENTIAL_PRESENT credentialName="
            + ",".join(sorted(present))
        )


def _fake_secret_value(package_id: str, name: str) -> str:
    digest = hashlib.sha256(f"{READY_CONTRACT_ID}:{package_id}:{name}".encode()).hexdigest()
    return f"TEST_ONLY_NOT_A_CREDENTIAL::{digest[:24]}"


def _write_fake_secrets(paths, package_id: str) -> tuple[str, ...]:
    paths.secret_root.mkdir(parents=True, exist_ok=True)
    secrets = {
        name: _fake_secret_value(package_id, name) for name in FAKE_SECRET_NAMES
    }
    payload = {
        "mode": "fake-only",
        "productionCompatible": False,
        "secrets": secrets,
    }
    atomic_write_text(paths.secret_root / "test-secrets.json", _render(payload))
    return tuple(sorted(secrets))


def _initialize_database(database_path: Path, *, stamp: str) -> dict[str, object]:
    database_path.parent.mkdir(parents=True, exist_ok=True)
    conn = open_sqlite(database_path)
    try:
        prepare_core_schema_group(conn)
        seed_core_defaults(conn, now=stamp)
        prepare_identity_schema_group(conn, now=stamp)
        initialize_media_schema_group(conn)
        seed_default_challenge(conn, now=stamp)
        ensure_migration_ledger(
            conn, supported_version=CURRENT_REUSABLE_MIGRATION_VERSION
        )
        finalize_legacy_schema_baseline(conn, applied_at=stamp)
        apply_admin_notifications_migration(conn, applied_at=stamp)
        apply_admin_notification_delivery_migration(conn, applied_at=stamp)
        apply_account_verification_migration(conn, applied_at=stamp)
        apply_phone_chat_history_migration(conn, applied_at=stamp)
        apply_generation_trial_migration(conn, applied_at=stamp)
        apply_phone_chat_request_lifecycle_migration(conn, applied_at=stamp)
        conn.commit()

        integrity = str(conn.execute("PRAGMA integrity_check").fetchone()[0])
        tables = {
            str(row[0])
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        missing = sorted(set(REQUIRED_TABLES) - tables)
        ledger_version = int(
            conn.execute("SELECT COALESCE(MAX(version), 0) FROM schema_migrations").fetchone()[0]
        )
        user_version = int(conn.execute("PRAGMA user_version").fetchone()[0])
        if integrity.lower() != "ok":
            raise ApplicationReadyError("DATABASE_INTEGRITY_FAILED")
        if missing:
            raise ApplicationReadyError(
                "DATABASE_REQUIRED_TABLES_MISSING tables=" + ",".join(missing)
            )
        if (
            ledger_version != CURRENT_REUSABLE_MIGRATION_VERSION
            or user_version != CURRENT_REUSABLE_MIGRATION_VERSION
        ):
            raise ApplicationReadyError(
                "DATABASE_MIGRATION_VERSION_MISMATCH "
                f"ledger={ledger_version} userVersion={user_version}"
            )
        return {
            "databaseIntegrity": "PASS",
            "databaseMigrationVersion": ledger_version,
            "databaseRequiredTables": {
                "status": "PASS",
                "tables": list(REQUIRED_TABLES),
            },
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _remove_owned_payload(paths) -> None:
    root = paths.environment_root.resolve(strict=False)
    for target in (paths.environment_root / "db", paths.media_root, paths.secret_root):
        if not target.exists() and not target.is_symlink():
            continue
        if target.is_symlink():
            target.unlink(missing_ok=True)
            continue
        resolved = target.resolve(strict=False)
        try:
            resolved.relative_to(root)
        except ValueError:
            continue
        if target.is_file():
            target.unlink(missing_ok=True)
        else:
            shutil.rmtree(target)
    (paths.state_root / "provider-config.json").unlink(missing_ok=True)


def prepare_application_ready(
    repo_root: Path | str,
    *,
    environment: Mapping[str, str] | None = None,
    production_contract: ProductionPathContract | None = None,
    local_provider_endpoints: Mapping[str, str] | None = None,
    timestamp: str | None = None,
) -> dict[str, object]:
    repo = resolve_repo_root(repo_root)
    payload_touched = False
    was_ready = False
    try:
        identity, paths, state = _load_active_owned_state(repo)
        was_ready = state.get("applicationReady") == "PASS"
        validate_environment_paths(
            identity,
            paths,
            production_contract or discover_production_path_contract(repo),
        )
        _assert_real_provider_credentials_absent(environment)
        provider_runtime = build_provider_configuration(local_provider_endpoints)
        stamp = timestamp or utc_now()

        paths.media_root.mkdir(parents=True, exist_ok=True)
        payload_touched = True
        database_evidence = _initialize_database(paths.database_path, stamp=stamp)
        fake_secret_names = _write_fake_secrets(paths, identity.package_id)
        provider_path = paths.state_root / "provider-config.json"
        atomic_write_text(provider_path, _render(provider_runtime))

        ready_fields: dict[str, object] = {
            "applicationReadyContractId": READY_CONTRACT_ID,
            "databaseInitialization": "READY",
            "databaseFixture": "IMPORT_SAFE_APPLICATION_SCHEMA",
            **database_evidence,
            "identityStartupFinalization": "DEFERRED_TO_D1_NO_MAIN_IMPORT",
            "videoStorageTariffMigration": "DEFERRED_TO_APPLICATION_STARTUP",
            "demoFeedRestore": "NOT_RUN",
            "fakeSecrets": "READY",
            "fakeSecretStatus": "READY",
            "fakeSecretNames": list(fake_secret_names),
            "externalProviderCredentials": "ABSENT",
            "providerConfiguration": "READY",
            "providerNetworkProbe": "NOT_RUN",
            "providerRuntime": provider_runtime,
            "applicationReady": "PASS",
            "updatedAt": stamp,
        }
        state_document = {
            **state,
            **ready_fields,
            "documentType": "environment-state",
        }
        receipt_document = {
            **state,
            **ready_fields,
            "documentType": "environment-receipt",
        }
        atomic_write_text(paths.environment_state_path, _render(state_document))
        atomic_write_text(paths.receipt_path, _render(receipt_document))
        return {
            "status": "READY",
            "packageId": identity.package_id,
            "applicationReady": "PASS",
            "databaseInitialization": "READY",
            "databaseMigrationVersion": database_evidence["databaseMigrationVersion"],
            "databaseIntegrity": "PASS",
            "fakeSecrets": "READY",
            "externalProviderCredentials": "ABSENT",
            "providerConfiguration": "READY",
            "providerNetworkProbe": "NOT_RUN",
        }
    except (EnvironmentContractError, ApplicationReadyError):
        if "paths" in locals() and payload_touched and not was_ready:
            _remove_owned_payload(paths)
        raise
    except Exception as exc:
        if "paths" in locals() and payload_touched and not was_ready:
            _remove_owned_payload(paths)
        raise ApplicationReadyError(
            f"APPLICATION_READY_PREPARE_FAILED reason={type(exc).__name__}"
        ) from None


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agent-env-ready")
    parser.add_argument("--repo-root", default=".")
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("prepare")
    prepare.add_argument("--comfyui-endpoint")
    prepare.add_argument("--ollama-endpoint")
    prepare.add_argument("--qwen-endpoint")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command != "prepare":
        return 3
    endpoints = {
        key: value
        for key, value in {
            "comfyui": args.comfyui_endpoint,
            "ollama": args.ollama_endpoint,
            "qwen": args.qwen_endpoint,
        }.items()
        if value
    }
    try:
        result = prepare_application_ready(
            args.repo_root,
            local_provider_endpoints=endpoints,
        )
        print("AGENT_ENV_READY " + json.dumps(result, sort_keys=True))
        return 0
    except (EnvironmentContractError, ApplicationReadyError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
