"""Persistent Linux AES-256-GCM secrets, isolated from Windows CurrentUser DPAPI."""

from __future__ import annotations

import base64
import hmac
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .secret_store import SECRET_NAME_PATTERN, SecretStoreError
from .secret_store_files import (
    LOCK_NAME, absolute_private_path, locked_directory, read_private, replace_private,
)


PROVIDER = "linux-aes-256-gcm"
MASTER_NAME = "master.key"
RESTORE_MARKER = ".restore-incomplete"
DOCUMENT_SUFFIX = ".aead.json"
MAX_SECRET_BYTES = 16384
_FIELDS = {"version", "provider", "name", "updatedAt", "nonce", "ciphertext"}


def document_name(name: str) -> str:
    if not isinstance(name, str) or not SECRET_NAME_PATTERN.fullmatch(name):
        raise SecretStoreError("Invalid secret name.")
    return name + DOCUMENT_SUFFIX


def _aad(name: str) -> bytes:
    return b"IZO_ASA/linux-aes-256-gcm/v1\x00" + name.encode("ascii")


def decrypt_document(name: str, raw: bytes, master: bytes) -> str:
    """The same authenticated envelope validation is used by restore."""
    document_name(name)
    try:
        document = json.loads(raw)
        if (not isinstance(document, dict) or set(document) != _FIELDS
                or type(document["version"]) is not int or document["version"] != 1
                or document["provider"] != PROVIDER or document["name"] != name
                or not isinstance(document["updatedAt"], str)):
            raise ValueError
        datetime.fromisoformat(document["updatedAt"])
        nonce = base64.b64decode(document["nonce"], validate=True)
        ciphertext = base64.b64decode(document["ciphertext"], validate=True)
        if len(master) != 32 or len(nonce) != 12 or not 16 < len(ciphertext) <= MAX_SECRET_BYTES + 16:
            raise ValueError
        value = AESGCM(master).decrypt(nonce, ciphertext, _aad(name)).decode("utf-8")
        if not value:
            raise ValueError
        return value
    except Exception:
        raise SecretStoreError("Encrypted secret document cannot be authenticated.") from None


def _master(directory: int, *, initialize: bool = False) -> bytes:
    value = read_private(directory, MASTER_NAME)
    if value is None:
        if not initialize or set(os.listdir(directory)) - {LOCK_NAME}:
            raise SecretStoreError("Existing secret storage has no master key; restore is required.")
        value = os.urandom(32)
        replace_private(directory, MASTER_NAME, value)
    if len(value) != 32:
        raise SecretStoreError("The secret-store master key is invalid; restore is required.")
    if initialize:
        for filename in os.listdir(directory):
            if filename.endswith(DOCUMENT_SUFFIX):
                name = filename[:-len(DOCUMENT_SUFFIX)]
                decrypt_document(name, read_private(directory, filename), value)
    return value


class LinuxSecretStore:
    source = "linux-aes-gcm"

    def __init__(self, root: Path) -> None:
        # Preserve the original path: resolve() would hide a symlink before no-follow checks.
        self.root = absolute_private_path(root)

    def path_for(self, name: str) -> Path:
        return self.root / document_name(name)

    def exists(self, name: str) -> bool:
        return bool(self.get(name))

    def _get(self, directory: int, name: str) -> str:
        if read_private(directory, RESTORE_MARKER) is not None:
            raise SecretStoreError("Secret storage has an unfinished restore.")
        raw = read_private(directory, document_name(name))
        if raw is None:
            if read_private(directory, name + ".dpapi.json") is not None:
                raise SecretStoreError("Windows secret material requires an explicit migration.")
            return ""
        return decrypt_document(name, raw, _master(directory))

    def get(self, name: str) -> str:
        document_name(name)
        with locked_directory(self.root) as directory:
            return "" if directory is None else self._get(directory, name)

    def _set(self, directory: int, name: str, value: str) -> None:
        filename = document_name(name)
        if not isinstance(value, str) or not value:
            raise SecretStoreError("Secret value must not be empty.")
        try:
            plaintext = value.encode("utf-8")
        except UnicodeError:
            raise SecretStoreError("Secret value must be valid Unicode.") from None
        if len(plaintext) > MAX_SECRET_BYTES:
            raise SecretStoreError("Secret value is too large.")
        self._get(directory, name)  # Never replace corrupted or foreign material.
        master = _master(directory, initialize=True)
        nonce = os.urandom(12)
        document = {
            "version": 1, "provider": PROVIDER, "name": name,
            "updatedAt": datetime.now(timezone.utc).isoformat(),
            "nonce": base64.b64encode(nonce).decode("ascii"),
            "ciphertext": base64.b64encode(AESGCM(master).encrypt(nonce, plaintext, _aad(name))).decode("ascii"),
        }
        replace_private(directory, filename, json.dumps(document, separators=(",", ":")).encode("ascii"))
        if not hmac.compare_digest(self._get(directory, name).encode("utf-8"), plaintext):
            raise SecretStoreError("Encrypted secret readback failed.")

    def set(self, name: str, value: str) -> None:
        document_name(name)
        with locked_directory(self.root, create=True) as directory:
            self._set(directory, name, value)

    def set_if_absent(self, name: str, value: str) -> None:
        document_name(name)
        with locked_directory(self.root, create=True) as directory:
            existing = self._get(directory, name)
            if existing:
                if not hmac.compare_digest(existing.encode("utf-8"), value.encode("utf-8")):
                    raise SecretStoreError("Legacy and protected secrets differ; explicit resolution is required.")
                return
            self._set(directory, name, value)

    def delete(self, name: str) -> bool:
        filename = document_name(name)
        with locked_directory(self.root) as directory:
            if directory is None or not self._get(directory, name):
                return False
            os.unlink(filename, dir_fd=directory)
            os.fsync(directory)
            return True
