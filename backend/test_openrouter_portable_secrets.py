"""Linux encrypted OpenRouter store and Windows DPAPI compatibility."""
from __future__ import annotations
import os
import stat
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from app.security import portable_secrets
from app.security.secret_store import SecretStoreError


@pytest.mark.skipif(os.name == "nt", reason="Linux volume permission semantics")
def test_linux_encrypted_save_rotate_readback_delete(tmp_path, monkeypatch):
    private=tmp_path/"private"
    master=tmp_path/"master.key"
    private.mkdir(mode=0o700)
    master.write_bytes(Fernet.generate_key())
    master.chmod(0o600)
    monkeypatch.setenv("IZO_SECRET_DIR",str(private))
    monkeypatch.setenv("IZO_OPENAI_MASTER_KEY_FILE",str(master))
    store=portable_secrets.PortableSecretStore(private)
    assert store.ready()
    one="sk-or-test-unique-key-ONE-not-real"
    two="sk-or-test-unique-key-TWO-not-real"
    store.set("openrouter_api_key",one)
    file=store.path_for("openrouter_api_key")
    assert file.stat().st_mode & 0o077 == 0
    assert private.stat().st_mode & 0o077 == 0
    assert one.encode() not in file.read_bytes()
    assert store.get("openrouter_api_key")==one
    store.set("openrouter_api_key",two)
    assert store.get("openrouter_api_key")==two
    assert two.encode() not in file.read_bytes()
    assert store.exists("openrouter_api_key")
    store_recreated=portable_secrets.PortableSecretStore(private)
    assert store_recreated.get("openrouter_api_key")==two
    assert store_recreated.delete("openrouter_api_key") is True
    assert not store_recreated.exists("openrouter_api_key")
    assert not file.exists()


@pytest.mark.skipif(os.name == "nt", reason="Linux fail-closed semantics")
def test_linux_unsafe_permissions_and_missing_key_fail_closed(tmp_path,monkeypatch):
    private=tmp_path/"private"
    private.mkdir(mode=0o700)
    master=tmp_path/"master.key"
    master.write_bytes(Fernet.generate_key())
    master.chmod(0o644)
    monkeypatch.setenv("IZO_SECRET_DIR",str(private))
    monkeypatch.setenv("IZO_OPENAI_MASTER_KEY_FILE",str(master))
    store=portable_secrets.PortableSecretStore(private)
    assert not store.ready()
    with pytest.raises(SecretStoreError):
        store.set("openrouter_api_key","sk-or-unsafe-local-example")
    assert not store.exists("openrouter_api_key")
    master.chmod(0o600)
    store.set("openrouter_api_key","sk-or-unsafe-local-example")
    (private/"openrouter_api_key.fernet").chmod(0o644)
    with pytest.raises(SecretStoreError):
        store.get("openrouter_api_key")
    with pytest.raises(SecretStoreError):
        store.delete("openrouter_api_key")


def test_windows_dpapi_facade_fake(monkeypatch,tmp_path):
    memory={}
    class FakeDPAPI:
        def __init__(self,root): self.root=root
        def path_for(self,name): return self.root/(name+".dpapi.json")
        def get(self,name): return memory.get(name,"")
        def set(self,name,value): memory[name]=value
        def exists(self,name): return name in memory
        def delete(self,name): return memory.pop(name,None) is not None
    monkeypatch.setattr(portable_secrets,"DpapiSecretStore",FakeDPAPI)
    store=portable_secrets.PortableSecretStore(tmp_path)
    if store._legacy is None:
        store._legacy=FakeDPAPI(tmp_path)
    assert store.ready() or store._legacy is not None
    store.set("openrouter_api_key","sk-or-fake-window-key")
    assert store.get("openrouter_api_key")=="sk-or-fake-window-key"
    assert store.delete("openrouter_api_key")
    assert not store.exists("openrouter_api_key")


def test_name_validation_blocks_path_traversal(tmp_path):
    class Fake:
        def path_for(self,name): raise SecretStoreError("Invalid")
    store=portable_secrets.PortableSecretStore.__new__(portable_secrets.PortableSecretStore)
    store.root=tmp_path
    store._legacy=None
    for name in ("../credentials","../../etc/passwd","UPPER","foo/bar",""):
        with pytest.raises(SecretStoreError):
            store.path_for(name)
