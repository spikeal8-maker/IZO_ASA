"""OpenAI secret storage contract. Uses fake DPAPI on Windows, never real credentials."""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from app.security import openai_secrets as store


@pytest.mark.skipif(os.name == "nt", reason="POSIX owner/mode assertions run on Linux CI")
def test_linux_encrypted_key_roundtrip_no_plaintext(tmp_path, monkeypatch):
    root = tmp_path / "secrets"
    master = tmp_path / "master.key"
    master.write_bytes(Fernet.generate_key())
    master.chmod(0o600)
    monkeypatch.setenv("IZO_SECRET_DIR", str(root))
    monkeypatch.setenv("IZO_OPENAI_MASTER_KEY_FILE", str(master))
    assert store.openai_secret_store_status()["ready"] is True
    sample = "sk-proj-LOCAL-TEST-ONLY-NOT-A-REAL-KEY"
    store.set_openai_key(sample)
    file = root / store.ENCRYPTED_FILENAME
    assert file.exists()
    assert sample.encode() not in file.read_bytes()
    assert file.stat().st_mode & 0o077 == 0
    assert root.stat().st_mode & 0o077 == 0
    assert store.get_openai_key() == sample
    assert store.delete_openai_key() is True
    assert store.has_openai_key() is False


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlink/mode assertions run on Linux CI")
def test_linux_missing_or_unprotected_master_is_rejected(tmp_path, monkeypatch):
    root = tmp_path / "secrets"
    master = tmp_path / "master.key"
    master.write_bytes(Fernet.generate_key())
    master.chmod(0o644)
    monkeypatch.setenv("IZO_SECRET_DIR", str(root))
    monkeypatch.setenv("IZO_OPENAI_MASTER_KEY_FILE", str(master))
    assert store.openai_secret_store_status()["ready"] is False
    with pytest.raises(store.OpenAISecretStoreError):
        store.set_openai_key("sk-proj-local-bad-mode")
    assert not root.exists()
    master.chmod(0o600)
    root.mkdir(mode=0o700)
    (root / store.ENCRYPTED_FILENAME).symlink_to(master)
    with pytest.raises(store.OpenAISecretStoreError):
        store.get_openai_key()


def test_windows_dpapi_contract_with_isolated_fake(monkeypatch, tmp_path):
    memory = {}
    class FakeDPAPI:
        def __init__(self, root):
            assert root == tmp_path
        def set(self, name, value):
            memory[name] = value
        def get(self, name):
            return memory.get(name, "")
        def exists(self, name):
            return name in memory
        def delete(self, name):
            return memory.pop(name, None) is not None
    monkeypatch.setattr(store, "_is_windows", lambda: True)
    monkeypatch.setattr(store, "_root", lambda: tmp_path)
    monkeypatch.setattr(store, "DpapiSecretStore", FakeDPAPI)
    store.set_openai_key("sk-proj-fake-windows")
    assert store.has_openai_key()
    assert store.get_openai_key() == "sk-proj-fake-windows"
    assert store.delete_openai_key()
    assert not store.has_openai_key()
    assert not (tmp_path / store.ENCRYPTED_FILENAME).exists()


def test_no_key_is_rejected_before_storage(monkeypatch, tmp_path):
    monkeypatch.setattr(store, "_root", lambda: tmp_path)
    with pytest.raises(ValueError):
        store.set_openai_key("sk-admin")
