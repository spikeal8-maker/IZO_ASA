"""External Windows CurrentUser DPAPI secret storage and SQLite migration."""

from __future__ import annotations

import base64
import ctypes
import hashlib
import hmac
import json
import os
import re
import sqlite3
import subprocess
import uuid
from ctypes import wintypes
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable


DOCUMENT_VERSION = 1
DOCUMENT_PROVIDER = "windows-dpapi-current-user"
SECRET_NAME_PATTERN = re.compile(r"^[a-z0-9_]{1,64}$")
DPAPI_ENTROPY = hashlib.sha256(b"IZO_ASA/windows-dpapi-secret-store/v1").digest()
CRYPTPROTECT_UI_FORBIDDEN = 0x01


class SecretStoreError(RuntimeError):
    pass


class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
    ]


def _data_blob(value: bytes) -> tuple[_DataBlob, ctypes.Array]:
    buffer = ctypes.create_string_buffer(value, len(value))
    pointer = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))
    return _DataBlob(len(value), pointer), buffer


def _require_windows_dpapi():
    if os.name != "nt":
        raise SecretStoreError("Windows DPAPI is unavailable on this platform.")
    return ctypes.windll.crypt32, ctypes.windll.kernel32


def protect_bytes_dpapi(value: bytes) -> bytes:
    crypt32, kernel32 = _require_windows_dpapi()
    source, source_buffer = _data_blob(value)
    entropy, entropy_buffer = _data_blob(DPAPI_ENTROPY)
    protected = _DataBlob()
    _ = (source_buffer, entropy_buffer)
    if not crypt32.CryptProtectData(
        ctypes.byref(source),
        "IZO_ASA secret",
        ctypes.byref(entropy),
        None,
        None,
        CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(protected),
    ):
        raise SecretStoreError(f"Windows DPAPI protect failed with code {ctypes.get_last_error()}.")
    try:
        return ctypes.string_at(protected.pbData, protected.cbData)
    finally:
        kernel32.LocalFree(protected.pbData)


def unprotect_bytes_dpapi(value: bytes) -> bytes:
    crypt32, kernel32 = _require_windows_dpapi()
    protected, protected_buffer = _data_blob(value)
    entropy, entropy_buffer = _data_blob(DPAPI_ENTROPY)
    plaintext = _DataBlob()
    _ = (protected_buffer, entropy_buffer)
    if not crypt32.CryptUnprotectData(
        ctypes.byref(protected),
        None,
        ctypes.byref(entropy),
        None,
        None,
        CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(plaintext),
    ):
        raise SecretStoreError(f"Windows DPAPI unprotect failed with code {ctypes.get_last_error()}.")
    try:
        return ctypes.string_at(plaintext.pbData, plaintext.cbData)
    finally:
        kernel32.LocalFree(plaintext.pbData)


def default_secret_store_dir() -> Path:
    configured = os.getenv("IZO_SECRET_DIR", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    local_app_data = os.getenv("LOCALAPPDATA", "").strip()
    base = Path(local_app_data).expanduser() if local_app_data else Path.home() / "AppData" / "Local"
    return (base / "IZO_ASA" / "secrets").resolve()


def assert_secret_store_outside_repository(secret_dir: Path, repository_root: Path) -> None:
    candidate = Path(secret_dir).expanduser().resolve()
    repository = Path(repository_root).expanduser().resolve()
    try:
        candidate.relative_to(repository)
    except ValueError:
        return
    raise SecretStoreError("IZO_SECRET_DIR must be outside the repository.")


def apply_windows_current_user_acl(path: Path) -> None:
    if os.name != "nt":
        raise SecretStoreError("Windows ACL configuration is unavailable on this platform.")
    try:
        identity = subprocess.check_output(
            ["whoami"],
            text=True,
            encoding="utf-8",
            errors="replace",
        ).strip()
        subprocess.run(
            ["icacls", str(path), "/inheritance:r", "/grant:r", f"{identity}:(F)"],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise SecretStoreError("Failed to restrict the Windows secret-store ACL.") from exc


class DpapiSecretStore:
    def __init__(
        self,
        root: Path,
        *,
        protector: Callable[[bytes], bytes] = protect_bytes_dpapi,
        unprotector: Callable[[bytes], bytes] = unprotect_bytes_dpapi,
        acl_setter: Callable[[Path], None] = apply_windows_current_user_acl,
    ) -> None:
        self.root = Path(root).expanduser().resolve()
        self._protect = protector
        self._unprotect = unprotector
        self._set_acl = acl_setter

    def path_for(self, name: str) -> Path:
        if not SECRET_NAME_PATTERN.fullmatch(str(name or "")):
            raise SecretStoreError("Invalid secret name.")
        return self.root / f"{name}.dpapi.json"

    def exists(self, name: str) -> bool:
        return self.path_for(name).is_file()

    def get(self, name: str) -> str:
        path = self.path_for(name)
        if not path.is_file():
            return ""
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
            if (
                not isinstance(document, dict)
                or document.get("version") != DOCUMENT_VERSION
                or document.get("provider") != DOCUMENT_PROVIDER
                or not isinstance(document.get("ciphertext"), str)
            ):
                raise SecretStoreError("Unsupported secret document.")
            encrypted = base64.b64decode(document["ciphertext"], validate=True)
            return self._unprotect(encrypted).decode("utf-8")
        except SecretStoreError:
            raise
        except Exception as exc:
            raise SecretStoreError("Failed to read the encrypted secret document.") from exc

    def set(self, name: str, value: str) -> None:
        if not isinstance(value, str) or not value:
            raise SecretStoreError("Secret value must not be empty.")
        path = self.path_for(name)
        self.root.mkdir(parents=True, exist_ok=True)
        self._set_acl(self.root)
        encrypted = self._protect(value.encode("utf-8"))
        document = {
            "version": DOCUMENT_VERSION,
            "provider": DOCUMENT_PROVIDER,
            "scope": "CurrentUser",
            "updatedAt": datetime.now(timezone.utc).isoformat(),
            "ciphertext": base64.b64encode(encrypted).decode("ascii"),
        }
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            temporary.write_text(
                json.dumps(document, ensure_ascii=True, separators=(",", ":")),
                encoding="utf-8",
            )
            os.replace(temporary, path)
            self._set_acl(path)
        finally:
            temporary.unlink(missing_ok=True)

    def delete(self, name: str) -> bool:
        path = self.path_for(name)
        if not path.exists():
            return False
        path.unlink()
        return True


def migrate_sqlite_secret_to_store(
    conn: sqlite3.Connection,
    store: DpapiSecretStore,
    name: str,
) -> str:
    row = conn.execute("SELECT value FROM admin_secrets WHERE key = ?", (name,)).fetchone()
    if row is None:
        return "already_migrated" if store.exists(name) else "not_configured"
    plaintext = str(row[0] or "").strip()
    if not plaintext:
        conn.execute("DELETE FROM admin_secrets WHERE key = ?", (name,))
        return "empty_row_deleted"
    store.set(name, plaintext)
    verified = store.get(name)
    if not hmac.compare_digest(verified.encode("utf-8"), plaintext.encode("utf-8")):
        raise SecretStoreError("Encrypted secret readback verification failed.")
    conn.execute("DELETE FROM admin_secrets WHERE key = ?", (name,))
    return "migrated"
