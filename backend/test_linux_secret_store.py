"""Actual POSIX/AEAD storage tests; all data is generated in disposable roots."""

from __future__ import annotations

import concurrent.futures
import json
import multiprocessing
import os
import secrets
import sqlite3
import stat
import sys
import threading
from pathlib import Path

import pytest

from app.security.linux_secret_store import LinuxSecretStore, MASTER_NAME
from app.security.secret_store import SecretStoreError, create_secret_store, migrate_sqlite_secret_to_store
from app.security.secret_store_files import locked_directory


pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux POSIX secret-store contract")


def _value() -> str:
    return "fixture-" + secrets.token_hex(32)


def _parallel_write(root: str, index: int) -> int:
    store = LinuxSecretStore(Path(root))
    name = f"parallel_{index}"
    value = "fixture-" + str(index)
    store.set(name, value)
    store.set("shared", value)
    store.delete("discarded")
    if store.get(name) != value:
        raise RuntimeError("isolated roundtrip failed")
    return index


def test_platform_factory_and_constructor_have_no_storage_side_effects(tmp_path):
    root = tmp_path / "secrets"
    store = create_secret_store(root)
    assert isinstance(store, LinuxSecretStore)
    assert store.source == "linux-aes-gcm"
    assert not root.exists()
    assert store.get("openrouter_api_key") == ""
    assert not store.exists("openrouter_api_key")
    assert not root.exists()
    assert create_secret_store(root, platform="win32").source == "dpapi"
    with pytest.raises(SecretStoreError, match="No protected"):
        create_secret_store(root, platform="unsupported")


def test_real_aead_roundtrip_restart_nonce_and_private_modes(tmp_path):
    root = tmp_path / "secrets"
    value = _value()
    store = LinuxSecretStore(root)
    store.set("openrouter_api_key", value)
    first = store.path_for("openrouter_api_key").read_bytes()
    master = (root / MASTER_NAME).read_bytes()
    assert value.encode() not in first
    assert len(master) == 32
    assert LinuxSecretStore(root).get("openrouter_api_key") == value
    store.set("openrouter_api_key", value)
    assert store.path_for("openrouter_api_key").read_bytes() != first
    assert (root / MASTER_NAME).read_bytes() == master
    assert stat.S_IMODE(root.stat().st_mode) == 0o700
    assert all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in root.iterdir())
    assert store.delete("openrouter_api_key")
    assert not store.delete("openrouter_api_key")
    assert store.get("openrouter_api_key") == ""
    assert (root / MASTER_NAME).read_bytes() == master


@pytest.mark.parametrize("field", ["provider", "name", "nonce", "ciphertext", "version"])
def test_tampered_envelope_cannot_be_read_replaced_or_deleted(tmp_path, field):
    store = LinuxSecretStore(tmp_path / "secrets")
    store.set("first", _value())
    path = store.path_for("first")
    document = json.loads(path.read_bytes())
    document[field] = 2 if field == "version" else "invalid"
    path.write_text(json.dumps(document))
    before = path.read_bytes()
    for operation in (lambda: store.get("first"), lambda: store.set("first", _value()), lambda: store.delete("first")):
        with pytest.raises(SecretStoreError, match="authenticated"):
            operation()
        assert path.read_bytes() == before


@pytest.mark.parametrize("damage", ["missing", "short", "different"])
def test_missing_or_corrupt_master_never_regenerates_or_changes_documents(tmp_path, damage):
    store = LinuxSecretStore(tmp_path / "secrets")
    store.set("first", _value())
    master = store.root / MASTER_NAME
    if damage == "missing":
        master.unlink()
    else:
        master.write_bytes(b"bad" if damage == "short" else os.urandom(32))
    before = {p.name: p.read_bytes() for p in store.root.iterdir()}
    for operation in (lambda: store.get("first"), lambda: store.set("first", _value()), lambda: store.delete("first")):
        with pytest.raises(SecretStoreError):
            operation()
        assert {p.name: p.read_bytes() for p in store.root.iterdir()} == before
    with pytest.raises(SecretStoreError):
        store.set("second", _value())
    assert {p.name: p.read_bytes() for p in store.root.iterdir()} == before
    if damage == "missing":
        assert not master.exists()


@pytest.mark.parametrize("target", ["root", "document", "master", "lock"])
def test_unsafe_permissions_fail_closed_without_repairing_them(tmp_path, target):
    store = LinuxSecretStore(tmp_path / "secrets")
    store.set("first", _value())
    path = {"root": store.root, "document": store.path_for("first"),
            "master": store.root / MASTER_NAME, "lock": store.root / ".store.lock"}[target]
    mode = 0o755 if target == "root" else 0o644
    path.chmod(mode)
    with pytest.raises(SecretStoreError):
        store.get("first")
    assert stat.S_IMODE(path.stat().st_mode) == mode


@pytest.mark.parametrize("where", ["root", "ancestor", "document", "master", "lock"])
def test_symlink_paths_never_follow_or_change_the_destination(tmp_path, where):
    root = tmp_path / "private" / "secrets"
    store = LinuxSecretStore(root)
    store.set("first", _value())
    if where in {"root", "ancestor"}:
        source = root if where == "root" else root.parent
        moved = source.with_name("moved")
        source.rename(moved)
        source.symlink_to(moved, target_is_directory=True)
    else:
        path = {"document": store.path_for("first"), "master": root / MASTER_NAME,
                "lock": root / ".store.lock"}[where]
        moved = path.with_name("saved")
        path.rename(moved)
        path.symlink_to(moved)
    before = moved.read_bytes() if moved.is_file() else None
    with pytest.raises(SecretStoreError):
        store.get("first")
    if before is not None:
        assert moved.read_bytes() == before


def test_hardlink_and_fifo_rejected_before_read(tmp_path):
    store = LinuxSecretStore(tmp_path / "secrets")
    store.set("first", _value())
    path = store.path_for("first")
    other = tmp_path / "outside"
    os.link(path, other)
    with pytest.raises(SecretStoreError):
        store.set("first", _value())
    assert other.read_bytes() == path.read_bytes()
    other.unlink()
    path.unlink()
    os.mkfifo(path, 0o600)
    with pytest.raises(SecretStoreError):
        store.get("first")


def test_failed_atomic_replace_keeps_previous_secret_and_cleans_temporary(tmp_path, monkeypatch):
    store = LinuxSecretStore(tmp_path / "secrets")
    first = _value()
    store.set("first", first)
    before = {p.name: p.read_bytes() for p in store.root.iterdir()}
    original = os.replace

    def fail(source, destination, **kwargs):
        if destination == "first.aead.json":
            raise OSError("injected write failure")
        return original(source, destination, **kwargs)

    monkeypatch.setattr(os, "replace", fail)
    with pytest.raises(SecretStoreError, match="unavailable"):
        store.set("first", _value())
    assert store.get("first") == first
    assert {p.name: p.read_bytes() for p in store.root.iterdir()} == before


@pytest.mark.parametrize("count", [2, 5, 10])
def test_process_concurrency_initialization_update_and_delete(tmp_path, count):
    root = tmp_path / "secrets"
    with concurrent.futures.ProcessPoolExecutor(max_workers=count, mp_context=multiprocessing.get_context("spawn")) as pool:
        results = list(pool.map(_parallel_write, [str(root)] * count, range(count)))
    assert sorted(results) == list(range(count))
    store = LinuxSecretStore(root)
    assert {store.get(f"parallel_{index}") for index in range(count)} == {f"fixture-{index}" for index in range(count)}
    assert store.get("shared") in {f"fixture-{index}" for index in range(count)}
    assert not store.exists("discarded")
    assert not list(root.glob("*.tmp"))


def test_busy_lock_is_bounded_and_does_not_delete_another_owner_lock(tmp_path):
    root = tmp_path / "secrets"
    with locked_directory(root, create=True):
        inode = (root / ".store.lock").stat().st_ino
        with pytest.raises(SecretStoreError, match="lock is busy"):
            with locked_directory(root, timeout=0.02):
                pytest.fail("second lock must not be acquired")
        assert (root / ".store.lock").stat().st_ino == inode


def test_windows_document_requires_explicit_migration_and_no_new_master(tmp_path):
    root = tmp_path / "secrets"
    root.mkdir(mode=0o700)
    path = root / "openrouter_api_key.dpapi.json"
    path.write_bytes(b"synthetic Windows document")
    path.chmod(0o600)
    store = LinuxSecretStore(root)
    with pytest.raises(SecretStoreError, match="explicit migration"):
        store.set("openrouter_api_key", _value())
    assert not (root / MASTER_NAME).exists()
    assert path.read_bytes() == b"synthetic Windows document"


def test_envelope_cannot_be_moved_between_secret_names(tmp_path):
    store = LinuxSecretStore(tmp_path / "secrets")
    store.set("first", _value())
    raw = json.loads(store.path_for("first").read_bytes())
    raw["name"] = "second"
    path = store.path_for("second")
    path.write_text(json.dumps(raw))
    path.chmod(0o600)
    with pytest.raises(SecretStoreError, match="authenticated"):
        store.get("second")


def test_migration_cannot_overwrite_concurrent_admin_save(tmp_path, monkeypatch):
    root = tmp_path / "secrets"
    store = LinuxSecretStore(root)
    entered, release = threading.Event(), threading.Event()
    original = store._set

    def pause(directory, name, value):
        entered.set()
        assert release.wait(5)
        return original(directory, name, value)

    monkeypatch.setattr(store, "_set", pause)

    def migrate():
        conn = sqlite3.connect(":memory:")
        try:
            conn.execute("CREATE TABLE admin_secrets (key TEXT PRIMARY KEY, value TEXT)")
            conn.execute("INSERT INTO admin_secrets VALUES ('shared', 'fixture-legacy')")
            try:
                return migrate_sqlite_secret_to_store(conn, store, "shared")
            except SecretStoreError:
                assert conn.execute("SELECT COUNT(*) FROM admin_secrets").fetchone()[0] == 1
                return "newer_admin_value_detected"
        finally:
            conn.close()

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        migration = pool.submit(migrate)
        assert entered.wait(5)
        admin = pool.submit(LinuxSecretStore(root).set, "shared", "fixture-newer")
        release.set()
        assert migration.result(timeout=5) in {"migrated", "newer_admin_value_detected"}
        admin.result(timeout=5)
    assert store.get("shared") == "fixture-newer"


def test_post_replace_fsync_failure_reports_uncertain_durability_without_rollback(tmp_path, monkeypatch):
    store = LinuxSecretStore(tmp_path / "secrets")
    store.set("first", "fixture-before")
    original = os.fsync

    def fail_directory(descriptor):
        if stat.S_ISDIR(os.fstat(descriptor).st_mode):
            raise OSError("injected post-replace fsync failure")
        return original(descriptor)

    monkeypatch.setattr(os, "fsync", fail_directory)
    with pytest.raises(SecretStoreError, match="unavailable"):
        store.set("first", "fixture-after")
    assert store.get("first") == "fixture-after"
    assert not list(store.root.glob("*.tmp"))


def test_readonly_snapshot_lock_uses_existing_inode_and_allows_shared_readers(tmp_path, monkeypatch):
    store = LinuxSecretStore(tmp_path / "secrets")
    store.set("first", "fixture-value")
    inode = (store.root / ".store.lock").stat().st_ino
    original = os.open
    lock_flags = []

    def record(path, flags, *args, **kwargs):
        if path == ".store.lock":
            lock_flags.append(flags)
        return original(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", record)
    with locked_directory(store.root, read_only=True):
        with locked_directory(store.root, read_only=True):
            pass
        with pytest.raises(SecretStoreError, match="busy"):
            with locked_directory(store.root, timeout=0.02):
                pytest.fail("writer cannot cross shared snapshot lock")
    assert all(not flags & (os.O_RDWR | os.O_WRONLY | os.O_CREAT) for flags in lock_flags[:2])
    assert (store.root / ".store.lock").stat().st_ino == inode


def test_readonly_snapshot_does_not_create_a_missing_lock(tmp_path):
    root = tmp_path / "secrets"
    root.mkdir(mode=0o700)
    with pytest.raises(SecretStoreError, match="unavailable"):
        with locked_directory(root, read_only=True):
            pytest.fail("configured snapshot requires an existing lock")
    assert list(root.iterdir()) == []
