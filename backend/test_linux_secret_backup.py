"""Pure snapshot/restore semantics; native verification adds a real age roundtrip."""

from __future__ import annotations

import base64
import io
import json
import os
import stat
import sys

import pytest

from app.security import linux_secret_backup as backup
from app.security.linux_secret_store import LinuxSecretStore, MASTER_NAME, RESTORE_MARKER
from app.security.secret_store import SecretStoreError


pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux POSIX secret backup contract")


def _configured(tmp_path):
    store = LinuxSecretStore(tmp_path / "source")
    store.set("openrouter_api_key", "fixture-provider-value")
    store.set("smtp_password", "fixture-second-value")
    return store


def _state(root):
    return {p.name: (p.read_bytes(), p.stat().st_mode, p.stat().st_ino) for p in root.iterdir()}


def test_readonly_snapshot_and_verified_empty_restore_preserve_all_private_bytes(tmp_path):
    source = _configured(tmp_path)
    before = _state(source.root)
    payload, count = backup._snapshot(source.root)
    target = tmp_path / "restored"
    receipt = backup.restore_from_stream(target, io.BytesIO(payload))
    assert receipt == {"status": "LOCAL_SECRET_RESTORE_VERIFIED", "format": backup.FORMAT, "documents": 2}
    assert count == 2 and _state(source.root) == before
    restored = LinuxSecretStore(target)
    assert restored.get("openrouter_api_key") == "fixture-provider-value"
    assert restored.get("smtp_password") == "fixture-second-value"
    for name, (raw, _mode, _inode) in before.items():
        assert (target / name).read_bytes() == raw
    assert stat.S_IMODE(target.stat().st_mode) == 0o700
    assert all(stat.S_IMODE(p.stat().st_mode) == 0o600 for p in target.iterdir())
    assert not (target / RESTORE_MARKER).exists()


@pytest.mark.parametrize("damage", ["master", "ciphertext", "traversal", "extra", "version", "oversize", "entry-oversize"])
def test_restore_rejects_untrusted_payload_before_creating_target(tmp_path, damage):
    source = _configured(tmp_path)
    payload, _ = backup._snapshot(source.root)
    document = json.loads(payload)
    if damage == "master":
        document["files"][MASTER_NAME] = base64.b64encode(os.urandom(32)).decode()
    elif damage == "ciphertext":
        document["files"]["openrouter_api_key.aead.json"] = base64.b64encode(b"invalid").decode()
    elif damage == "traversal":
        document["files"]["../outside"] = base64.b64encode(b"invalid").decode()
    elif damage == "extra":
        document["files"]["unexpected"] = ""
    elif damage == "version":
        document["format"] = "unknown"
    elif damage == "entry-oversize":
        name = "openrouter_api_key.aead.json"
        valid = base64.b64decode(document["files"][name])
        document["files"][name] = base64.b64encode(valid + b" " * backup.MAX_FILE_BYTES).decode()
    payload = b"x" * (backup.MAX_PAYLOAD + 1) if damage == "oversize" else json.dumps(document).encode()
    target = tmp_path / "restored"
    with pytest.raises(SecretStoreError):
        backup.restore_from_stream(target, io.BytesIO(payload))
    assert not target.exists()


def test_restore_refuses_existing_target_and_never_overwrites_a_newer_value(tmp_path):
    source = _configured(tmp_path)
    payload, _ = backup._snapshot(source.root)
    target = LinuxSecretStore(tmp_path / "restored")
    target.set("openrouter_api_key", "fixture-newer")
    before = _state(target.root)
    with pytest.raises(SecretStoreError, match="empty"):
        backup.restore_from_stream(target.root, io.BytesIO(payload))
    assert _state(target.root) == before


def test_interrupted_restore_stays_marked_and_unusable(tmp_path, monkeypatch):
    source = _configured(tmp_path)
    payload, _ = backup._snapshot(source.root)
    target = tmp_path / "restored"
    original = backup.replace_private

    def fail(directory, name, value):
        if name.endswith(".aead.json"):
            raise OSError("injected restore write failure")
        return original(directory, name, value)

    monkeypatch.setattr(backup, "replace_private", fail)
    with pytest.raises(SecretStoreError):
        backup.restore_from_stream(target, io.BytesIO(payload))
    assert (target / RESTORE_MARKER).exists()
    with pytest.raises(SecretStoreError, match="unfinished restore"):
        LinuxSecretStore(target).get("openrouter_api_key")
    with pytest.raises(SecretStoreError, match="unfinished restore"):
        LinuxSecretStore(target).set("another", "fixture-value")


def test_snapshot_does_not_initialize_or_follow_foreign_entries(tmp_path):
    root = tmp_path / "missing"
    with pytest.raises(SecretStoreError):
        backup._snapshot(root)
    assert not root.exists()
    source = _configured(tmp_path)
    outside = tmp_path / "outside"
    outside.write_text("not-a-secret-fixture")
    (source.root / "extra.aead.json").symlink_to(outside)
    with pytest.raises(SecretStoreError):
        backup._snapshot(source.root)
    assert outside.read_text() == "not-a-secret-fixture"


def test_age_boundary_never_writes_plaintext_snapshot_to_a_file(tmp_path, monkeypatch):
    source = _configured(tmp_path)
    output_dir = tmp_path / "backups"
    output_dir.mkdir(mode=0o700)
    output = output_dir / "snapshot.age"
    seen = {}

    class EncryptorFixture:
        returncode = 0

        def __init__(self, command, *, stdin, stdout, stderr):
            seen.update(command=command, stdin=stdin, stderr=stderr)
            self.output = stdout

        def communicate(self, payload, timeout):
            seen["payload"] = payload
            assert timeout == 60
            os.write(self.output, b"age-encryption.org/v1\nfixture-opaque-ciphertext")

    monkeypatch.setattr(backup.subprocess, "Popen", EncryptorFixture)
    receipt = backup.encrypted_backup(source.root, output, "age1" + "a" * 58, age_binary="/verified/age")
    assert receipt["status"] == "LOCAL_SECRET_BACKUP_ENCRYPTED"
    assert seen["command"] == ["/verified/age", "-r", "age1" + "a" * 58]
    assert seen["stdin"] == backup.subprocess.PIPE and seen["stderr"] == backup.subprocess.DEVNULL
    assert "fixture-provider-value" not in output.read_text()
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert not any(p.name.endswith(".tmp") for p in output_dir.iterdir())
    assert set(p.name for p in output_dir.iterdir()) == {".store.lock", "snapshot.age"}


def test_bad_age_output_is_not_published(tmp_path, monkeypatch):
    source = _configured(tmp_path)
    output_dir = tmp_path / "backups"
    output_dir.mkdir(mode=0o700)

    class FailedAge:
        returncode = 1

        def __init__(self, *_args, **_kwargs):
            pass

        def communicate(self, _payload, timeout):
            pass

    monkeypatch.setattr(backup.subprocess, "Popen", FailedAge)
    with pytest.raises(SecretStoreError, match="encrypt"):
        backup.encrypted_backup(source.root, output_dir / "bad.age", "age1" + "a" * 58)
    assert list(p for p in output_dir.iterdir() if p.name != ".store.lock") == []


def test_restore_rejects_duplicate_inventory_fields_before_target_creation(tmp_path):
    target = tmp_path / "restored"
    payload = b'{"format":"izo-linux-secrets-v1","files":{},"files":{}}'
    with pytest.raises(SecretStoreError):
        backup.restore_from_stream(target, io.BytesIO(payload))
    assert not target.exists()


def test_age_deadline_kills_child_and_does_not_publish(tmp_path, monkeypatch):
    source = _configured(tmp_path)
    output_dir = tmp_path / "backups"
    output_dir.mkdir(mode=0o700)
    events = []

    class HungAge:
        def __init__(self, *_args, **_kwargs):
            pass

        def communicate(self, *args, **_kwargs):
            if args:
                raise backup.subprocess.TimeoutExpired("fixture-age", 60)
            events.append("reaped")

        def kill(self):
            events.append("killed")

    monkeypatch.setattr(backup.subprocess, "Popen", HungAge)
    with pytest.raises(SecretStoreError, match="deadline"):
        backup.encrypted_backup(source.root, output_dir / "bad.age", "age1" + "a" * 58)
    assert events == ["killed", "reaped"]
    assert list(p for p in output_dir.iterdir() if p.name != ".store.lock") == []
