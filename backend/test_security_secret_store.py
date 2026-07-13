from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

import main

from app.security.secret_store import (
    DpapiSecretStore,
    SecretStoreError,
    assert_secret_store_outside_repository,
    default_secret_store_dir,
    migrate_sqlite_secret_to_store,
    protect_bytes_dpapi,
    unprotect_bytes_dpapi,
)


def fake_protect(value: bytes) -> bytes:
    return b"protected:" + value[::-1]


def fake_unprotect(value: bytes) -> bytes:
    prefix = b"protected:"
    if not value.startswith(prefix):
        raise SecretStoreError("invalid protected payload")
    return value[len(prefix):][::-1]


@pytest.fixture
def store(tmp_path: Path):
    acl_calls: list[Path] = []
    instance = DpapiSecretStore(
        tmp_path / "external-secrets",
        protector=fake_protect,
        unprotector=fake_unprotect,
        acl_setter=lambda path: acl_calls.append(Path(path)),
    )
    return instance, acl_calls


def test_store_roundtrip_is_atomic_encrypted_and_acl_scoped(store):
    secret_store, acl_calls = store
    value = "sk-or-private-value"

    secret_store.set("openrouter_api_key", value)

    path = secret_store.path_for("openrouter_api_key")
    assert path.is_file()
    assert value not in path.read_text(encoding="utf-8")
    assert secret_store.get("openrouter_api_key") == value
    assert secret_store.exists("openrouter_api_key") is True
    assert list(path.parent.glob("*.tmp")) == []
    assert acl_calls == [path.parent, path]

    assert secret_store.delete("openrouter_api_key") is True
    assert secret_store.delete("openrouter_api_key") is False
    assert secret_store.get("openrouter_api_key") == ""


def test_store_rejects_invalid_names_and_corrupt_documents(store):
    secret_store, _acl_calls = store
    with pytest.raises(SecretStoreError, match="Invalid secret name"):
        secret_store.path_for("../escape")

    path = secret_store.path_for("openrouter_api_key")
    path.parent.mkdir(parents=True)
    path.write_text('{"version":1,"provider":"wrong","ciphertext":"AA=="}', encoding="utf-8")
    with pytest.raises(SecretStoreError, match="Unsupported secret document"):
        secret_store.get("openrouter_api_key")


def test_migration_verifies_dpapi_before_deleting_sqlite(store):
    secret_store, _acl_calls = store
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE admin_secrets (key TEXT PRIMARY KEY, value TEXT, updated_at TEXT)")
    conn.execute("INSERT INTO admin_secrets VALUES ('openrouter_api_key', 'sk-or-migrate-me', 'now')")

    result = migrate_sqlite_secret_to_store(conn, secret_store, "openrouter_api_key")

    assert result == "migrated"
    assert secret_store.get("openrouter_api_key") == "sk-or-migrate-me"
    assert conn.execute("SELECT COUNT(*) FROM admin_secrets").fetchone()[0] == 0


def test_failed_store_write_keeps_plaintext_row(tmp_path: Path):
    def failed_protect(_value: bytes) -> bytes:
        raise SecretStoreError("DPAPI unavailable")

    secret_store = DpapiSecretStore(
        tmp_path / "secrets",
        protector=failed_protect,
        unprotector=fake_unprotect,
        acl_setter=lambda _path: None,
    )
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE admin_secrets (key TEXT PRIMARY KEY, value TEXT, updated_at TEXT)")
    conn.execute("INSERT INTO admin_secrets VALUES ('openrouter_api_key', 'sk-or-keep-me', 'now')")

    with pytest.raises(SecretStoreError, match="DPAPI unavailable"):
        migrate_sqlite_secret_to_store(conn, secret_store, "openrouter_api_key")

    assert conn.execute("SELECT value FROM admin_secrets").fetchone()[0] == "sk-or-keep-me"


def test_migration_is_idempotent_when_sqlite_row_is_absent(store):
    secret_store, _acl_calls = store
    secret_store.set("openrouter_api_key", "sk-or-already-safe")
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE admin_secrets (key TEXT PRIMARY KEY, value TEXT, updated_at TEXT)")

    assert migrate_sqlite_secret_to_store(conn, secret_store, "openrouter_api_key") == "already_migrated"


def test_default_store_dir_uses_external_local_app_data(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))
    monkeypatch.delenv("IZO_SECRET_DIR", raising=False)

    assert default_secret_store_dir() == (tmp_path / "LocalAppData" / "IZO_ASA" / "secrets").resolve()


def test_store_directory_inside_repository_is_rejected(tmp_path: Path):
    repository = tmp_path / "repository"
    repository.mkdir()

    with pytest.raises(SecretStoreError, match="outside the repository"):
        assert_secret_store_outside_repository(repository / "secrets", repository)

    external = tmp_path / "external-secrets"
    assert_secret_store_outside_repository(external, repository)


def test_main_openrouter_key_prefers_env_then_dpapi(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    main.OPENROUTER_SECRET_STORE.set(main.OPENROUTER_SECRET_NAME, "sk-or-dpapi-value")

    assert main.openrouter_api_key_source() == "dpapi"
    assert main.openrouter_api_key() == "sk-or-dpapi-value"

    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-env-value")
    assert main.openrouter_api_key_source() == "env"
    assert main.openrouter_api_key() == "sk-or-env-value"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows DPAPI only")
def test_real_current_user_dpapi_roundtrip():
    protected = protect_bytes_dpapi(b"temporary-test-secret")

    assert b"temporary-test-secret" not in protected
    assert unprotect_bytes_dpapi(protected) == b"temporary-test-secret"
