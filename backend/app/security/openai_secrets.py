"""External, encrypted OpenAI key storage. No plaintext key may enter SQLite."""
from __future__ import annotations

import os
import stat
import uuid
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from .secret_store import (
    DpapiSecretStore,
    SecretStoreError,
    assert_secret_store_outside_repository,
    default_secret_store_dir,
)

SECRET_NAME = "openai_api_key"
ENCRYPTED_FILENAME = "openai_api_key.fernet"


class OpenAISecretStoreError(RuntimeError):
    """A sanitized secret-store failure, without keys or filesystem paths."""


def _is_windows() -> bool:
    return os.name == "nt"


def _root() -> Path:
    if _is_windows():
        root = default_secret_store_dir()
    else:
        configured = os.getenv("IZO_SECRET_DIR", "").strip()
        if not configured:
            raise OpenAISecretStoreError("OPENAI_SECRET_VOLUME_REQUIRED")
        root = Path(configured).expanduser().resolve()
    try:
        assert_secret_store_outside_repository(root, Path(__file__).resolve().parents[3])
    except SecretStoreError as exc:
        raise OpenAISecretStoreError("OPENAI_SECRET_ROOT_UNSAFE") from exc
    return root


def _check_private(path: Path, *, directory: bool = False) -> None:
    if path.is_symlink():
        raise OpenAISecretStoreError("OPENAI_SECRET_SYMLINK_FORBIDDEN")
    if not path.exists():
        raise OpenAISecretStoreError("OPENAI_SECRET_PATH_MISSING")
    mode = path.stat().st_mode
    if directory and not stat.S_ISDIR(mode):
        raise OpenAISecretStoreError("OPENAI_SECRET_ROOT_NOT_DIRECTORY")
    if not directory and not stat.S_ISREG(mode):
        raise OpenAISecretStoreError("OPENAI_SECRET_NOT_REGULAR_FILE")
    if mode & 0o077:
        raise OpenAISecretStoreError("OPENAI_SECRET_PERMISSIONS_UNSAFE")


def _linux_cipher() -> Fernet:
    source = os.getenv("IZO_OPENAI_MASTER_KEY_FILE", "").strip()
    if not source:
        raise OpenAISecretStoreError("OPENAI_MASTER_KEY_MOUNT_REQUIRED")
    key_file = Path(source).expanduser()
    _check_private(key_file)
    try:
        return Fernet(key_file.read_bytes().strip())
    except (OSError, ValueError) as exc:
        raise OpenAISecretStoreError("OPENAI_MASTER_KEY_UNAVAILABLE") from exc


def openai_secret_store_status() -> dict[str, bool]:
    try:
        root = _root()
        if _is_windows():
            return {"ready": True}
        _linux_cipher()
        if root.exists():
            _check_private(root, directory=True)
        return {"ready": True}
    except (OpenAISecretStoreError, OSError, SecretStoreError):
        return {"ready": False}


def has_openai_key() -> bool:
    root = _root()
    if _is_windows():
        try:
            return DpapiSecretStore(root).exists(SECRET_NAME)
        except (OSError, SecretStoreError) as exc:
            raise OpenAISecretStoreError("OPENAI_SECRET_UNAVAILABLE") from exc
    if root.exists():
        _check_private(root, directory=True)
    filename = root / ENCRYPTED_FILENAME
    if filename.exists():
        _check_private(filename)
        _linux_cipher()
        return True
    return False


def get_openai_key() -> str:
    root = _root()
    if _is_windows():
        try:
            return DpapiSecretStore(root).get(SECRET_NAME)
        except (OSError, SecretStoreError) as exc:
            raise OpenAISecretStoreError("OPENAI_SECRET_UNAVAILABLE") from exc
    filename = root / ENCRYPTED_FILENAME
    if not filename.exists():
        return ""
    _check_private(root, directory=True)
    _check_private(filename)
    try:
        return _linux_cipher().decrypt(filename.read_bytes()).decode("utf-8")
    except (InvalidToken, UnicodeError, OSError) as exc:
        raise OpenAISecretStoreError("OPENAI_SECRET_DECRYPT_FAILED") from exc


def set_openai_key(key: str) -> None:
    value = key.strip()
    if not value.startswith("sk-") or len(value) < 12 or len(value) > 4096:
        raise ValueError("Ожидается проектный API-ключ OpenAI.")
    root = _root()
    if _is_windows():
        try:
            DpapiSecretStore(root).set(SECRET_NAME, value)
            return
        except (OSError, SecretStoreError) as exc:
            raise OpenAISecretStoreError("OPENAI_SECRET_SAVE_FAILED") from exc
    cipher = _linux_cipher()
    if not root.exists():
        root.mkdir(parents=True, mode=0o700)
    _check_private(root, directory=True)
    filename = root / ENCRYPTED_FILENAME
    if filename.exists():
        _check_private(filename)
    tmp = root / ("." + uuid.uuid4().hex + ".tmp")
    try:
        fd = os.open(tmp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "wb") as file:
            file.write(cipher.encrypt(value.encode("utf-8")))
            file.flush()
            os.fsync(file.fileno())
        os.replace(tmp, filename)
    except OSError as exc:
        raise OpenAISecretStoreError("OPENAI_SECRET_SAVE_FAILED") from exc
    finally:
        tmp.unlink(missing_ok=True)


def delete_openai_key() -> bool:
    root = _root()
    if _is_windows():
        try:
            return DpapiSecretStore(root).delete(SECRET_NAME)
        except (OSError, SecretStoreError) as exc:
            raise OpenAISecretStoreError("OPENAI_SECRET_DELETE_FAILED") from exc
    filename = root / ENCRYPTED_FILENAME
    if not filename.exists():
        return False
    _check_private(root, directory=True)
    _check_private(filename)
    try:
        filename.unlink()
    except OSError as exc:
        raise OpenAISecretStoreError("OPENAI_SECRET_DELETE_FAILED") from exc
    return True
