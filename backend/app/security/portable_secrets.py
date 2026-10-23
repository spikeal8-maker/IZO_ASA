"""Cross-platform encrypted secrets using the pre-existing OpenAI Linux Fernet boundary.

Windows keeps the existing CurrentUser DPAPI files; Linux uses the same external
private secret directory and read-only master-key volume used by OpenAI.
No plaintext secret may be written into SQLite, images or the Git checkout.
"""
from __future__ import annotations

import hmac
import json
import os
import re
import stat
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .openai_secrets import (
    OpenAISecretStoreError, _check_private, _linux_cipher, _root,
)
from .secret_store import DpapiSecretStore, SecretStoreError

_NAME = re.compile(r"^[a-z0-9_]{1,64}$")


class PortableSecretStore:
    """DPAPI for Windows, atomic Fernet ciphertext under Linux."""

    def __init__(self, root: Path):
        self.root = Path(root).expanduser().resolve()
        self._windows = os.name == "nt"
        self._legacy = DpapiSecretStore(self.root) if self._windows else None
        if not self._windows:
            try:
                self.root = _root()
            except (OpenAISecretStoreError, OSError) as exc:
                raise SecretStoreError("SECRET_STORAGE_ROOT_INVALID") from exc

    def path_for(self, name: str) -> Path:
        if not _NAME.fullmatch(str(name or "")):
            raise SecretStoreError("SECRET_NAME_INVALID")
        if self._legacy is not None:
            return self._legacy.path_for(name)
        return self.root / (name + ".fernet")

    def ready(self) -> bool:
        if self._legacy is not None:
            return True
        try:
            _check_private(self.root, directory=True)
            _linux_cipher()
            return True
        except (OpenAISecretStoreError, OSError):
            return False

    def exists(self, name: str) -> bool:
        file = self.path_for(name)
        if self._legacy is not None:
            return self._legacy.exists(name)
        try:
            if self.root.exists():
                _check_private(self.root, directory=True)
            if file.exists() or file.is_symlink():
                _check_private(file)
                return True
            return False
        except (OSError, OpenAISecretStoreError) as exc:
            raise SecretStoreError("SECRET_STORAGE_UNAVAILABLE") from exc

    def get(self, name: str) -> str:
        if self._legacy is not None:
            return self._legacy.get(name)
        file = self.path_for(name)
        if not self.exists(name):
            return ""
        try:
            result = _linux_cipher().decrypt(file.read_bytes()).decode("utf-8")
            return result
        except (OpenAISecretStoreError, OSError, ValueError, UnicodeError) as exc:
            raise SecretStoreError("SECRET_DECRYPT_FAILED") from exc
        except Exception as exc:
            # cryptography.InvalidToken never exposes the encrypted value.
            raise SecretStoreError("SECRET_DECRYPT_FAILED") from exc

    def set(self, name: str, value: str) -> None:
        text = str(value or "").strip()
        if not text or len(text) > 4096:
            raise SecretStoreError("SECRET_VALUE_INVALID")
        if self._legacy is not None:
            self._legacy.set(name, text)
            if not hmac.compare_digest(self._legacy.get(name), text):
                raise SecretStoreError("SECRET_READBACK_FAILED")
            return

        target = self.path_for(name)
        try:
            _check_private(self.root, directory=True)
            cipher = _linux_cipher()
            if target.exists() or target.is_symlink():
                _check_private(target)
            temp = self.root / ("." + uuid.uuid4().hex + ".tmp")
            try:
                descriptor = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(cipher.encrypt(text.encode("utf-8")))
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temp, target)
            finally:
                temp.unlink(missing_ok=True)
            if not hmac.compare_digest(self.get(name), text):
                raise SecretStoreError("SECRET_READBACK_FAILED")
        except SecretStoreError:
            raise
        except (OSError, OpenAISecretStoreError) as exc:
            raise SecretStoreError("SECRET_STORAGE_UNAVAILABLE") from exc

    def delete(self, name: str) -> bool:
        if self._legacy is not None:
            return self._legacy.delete(name)
        if not self.exists(name):
            return False
        file = self.path_for(name)
        try:
            file.unlink()
            return True
        except OSError as exc:
            raise SecretStoreError("SECRET_DELETE_FAILED") from exc
