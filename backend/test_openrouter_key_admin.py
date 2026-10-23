"""HTTP contract: admin-only OpenRouter credential storage and independent verification."""
from __future__ import annotations
from contextlib import contextmanager
from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest

import main


@contextmanager
def no_lifespan_client():
    client = TestClient(main.app)
    try:
        yield client
    finally:
        client.close()


class FakeStore:
    def __init__(self):
        self.value = ""
        self.allow = True
    def ready(self):
        return self.allow
    def get(self, name):
        return self.value
    def exists(self, name):
        return bool(self.value)
    def set(self, name, value):
        self.value=value
    def delete(self, name):
        existed = bool(self.value)
        self.value=""
        return existed


@pytest.fixture
def fake_admin(monkeypatch):
    events=[]
    store=FakeStore()
    allowed={"admin":False}
    def authenticate(_request):
        if not allowed["admin"]:
            raise HTTPException(status_code=401,detail="Not authorized")
        return {"internal_user_id":"trusted-qa-admin"}
    @contextmanager
    def conn():
        yield object()
    monkeypatch.setattr(main,"require_trusted_admin",authenticate)
    monkeypatch.setattr(main,"OPENROUTER_SECRET_STORE",store)
    monkeypatch.setattr(main,"db",conn)
    monkeypatch.setattr(main,"record_audit_log",lambda _conn, action, **kwargs:events.append((action,kwargs)))
    monkeypatch.setattr(main,"save_openrouter_api_key",lambda key: store.set(main.OPENROUTER_SECRET_NAME,key))
    monkeypatch.setattr(main,"delete_openrouter_api_key",lambda:store.delete(main.OPENROUTER_SECRET_NAME))
    monkeypatch.setattr(main,"openrouter_api_key",lambda:store.value)
    monkeypatch.setattr(main,"fetch_openrouter_key_status",
                        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("No provider access during key save")))
    return allowed,store,events


def test_unauthenticated_save_delete_probe_denied(fake_admin):
    _,store,events=fake_admin
    with no_lifespan_client() as client:
        assert client.put("/api/admin/openrouter/key",json={"key":"sk-or-test-unauthenticated-ABC"}).status_code==401
        assert client.delete("/api/admin/openrouter/key").status_code==401
        assert client.post("/api/admin/openrouter/key/check").status_code==401
    assert store.value==""
    assert events==[]


def test_save_confirms_readback_and_never_calls_provider(fake_admin):
    allowed,store,events=fake_admin
    allowed["admin"]=True
    with no_lifespan_client() as client:
        response=client.put("/api/admin/openrouter/key",json={"key":"sk-or-test-no-real-credential-ABC"})
        assert response.status_code==200
        assert response.json()["ok"] is True
        assert response.json()["keySaved"] is True
        assert response.json()["liveVerified"] is False
        assert "sk-or-test-no-real" not in response.text
        assert store.value=="sk-or-test-no-real-credential-ABC"
        assert client.put("/api/admin/openrouter/key",json={"key":"invalid-not-openrouter-api-key"}).status_code==400
        stored=client.delete("/api/admin/openrouter/key")
        assert stored.status_code==200
        assert stored.json()["keyConfigured"] is False
    assert store.value==""
    assert [e[0] for e in events]==["openrouter_key_saved","openrouter_key_deleted"]
    assert all("sk-or-" not in str(event) for event in events)


def test_storage_unavailable_returns_503_without_key_claim(fake_admin):
    allowed,store,events=fake_admin
    allowed["admin"]=True
    store.allow=False
    with no_lifespan_client() as client:
        response=client.put("/api/admin/openrouter/key",json={"key":"sk-or-test-credential-never-store"})
        assert response.status_code==503
        assert "sk-or-test-credential" not in response.text
    assert store.value==""
    assert events==[]
