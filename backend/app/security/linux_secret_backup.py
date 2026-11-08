"""Consistent local age-encrypted backup and empty-target Linux secret restore."""

from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import uuid
from pathlib import Path
from typing import BinaryIO

from .linux_secret_store import (
    DOCUMENT_SUFFIX, MASTER_NAME, RESTORE_MARKER, decrypt_document, document_name,
)
from .secret_store import SecretStoreError
from .secret_store_files import LOCK_NAME, MAX_FILE_BYTES, locked_directory, read_private, replace_private


FORMAT = "izo-linux-secrets-v1"
MAX_PAYLOAD = 6 * 1024 * 1024
MAX_DOCUMENTS = 64


def _validate(files: dict[str, bytes]) -> int:
    if not isinstance(files, dict) or MASTER_NAME not in files or len(files) > MAX_DOCUMENTS + 1:
        raise SecretStoreError("Invalid secret backup inventory.")
    master = files[MASTER_NAME]
    if not isinstance(master, bytes) or len(master) != 32:
        raise SecretStoreError("Invalid secret backup master key.")
    for filename, raw in files.items():
        if not isinstance(filename, str) or not isinstance(raw, bytes):
            raise SecretStoreError("Invalid secret backup entry.")
        if len(raw) > MAX_FILE_BYTES:
            raise SecretStoreError("Secret backup entry is too large.")
        if filename == MASTER_NAME:
            continue
        if not filename.endswith(DOCUMENT_SUFFIX):
            raise SecretStoreError("Unexpected secret backup entry.")
        name = filename[:-len(DOCUMENT_SUFFIX)]
        if document_name(name) != filename:
            raise SecretStoreError("Invalid secret backup entry.")
        decrypt_document(name, raw, master)
    return len(files) - 1


def _snapshot(root: Path) -> tuple[bytes, int]:
    # O_RDONLY + LOCK_SH on an existing lock also works with a read-only bind mount.
    with locked_directory(root, read_only=True) as directory:
        if directory is None:
            raise SecretStoreError("Configured secret storage is required for backup.")
        names = set(os.listdir(directory)) - {LOCK_NAME}
        if len(names) > MAX_DOCUMENTS + 1:
            raise SecretStoreError("Secret backup inventory is too large.")
        files = {name: read_private(directory, name) for name in sorted(names)}
        count = _validate(files)
        payload = json.dumps({"format": FORMAT, "files": {
            name: base64.b64encode(value).decode("ascii") for name, value in files.items()
        }}, separators=(",", ":"), sort_keys=True).encode("ascii")
        if len(payload) > MAX_PAYLOAD:
            raise SecretStoreError("Secret backup payload is too large.")
        return payload, count


def encrypted_backup(root: Path, output: Path, recipient: str, *, age_binary: str = "age") -> dict:
    """Stream private material only into age; publish only complete ciphertext."""
    if not re.fullmatch(r"age1[0-9a-z]{20,100}", recipient):
        raise SecretStoreError("An age public recipient is required.")
    output = Path(output).absolute()
    if output.name in {MASTER_NAME, LOCK_NAME, RESTORE_MARKER} or output.name.startswith("."):
        raise SecretStoreError("Invalid encrypted backup filename.")
    try:
        output.parent.relative_to(Path(root).absolute())
    except ValueError:
        pass
    else:
        raise SecretStoreError("Encrypted backup must be outside the live secret directory.")
    payload, count = _snapshot(root)
    temporary = ".backup-" + uuid.uuid4().hex + ".tmp"
    with locked_directory(output.parent) as directory:
        if directory is None:
            raise SecretStoreError("A private backup output directory is required.")
        if output.name in os.listdir(directory):
            raise SecretStoreError("The encrypted backup destination already exists.")
        descriptor = os.open(temporary, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                             0o600, dir_fd=directory)
        try:
            process = subprocess.Popen([age_binary, "-r", recipient], stdin=subprocess.PIPE,
                                       stdout=descriptor, stderr=subprocess.DEVNULL)
            try:
                process.communicate(payload, timeout=60)
            except BaseException as failure:
                process.kill()
                process.communicate()
                if isinstance(failure, subprocess.TimeoutExpired):
                    raise SecretStoreError("Age encryption did not finish before the deadline.") from None
                raise
            if process.returncode != 0:
                raise SecretStoreError("Age could not encrypt the secret backup.")
            os.fsync(descriptor)
            os.lseek(descriptor, 0, os.SEEK_SET)
            if os.read(descriptor, 22) != b"age-encryption.org/v1\n":
                raise SecretStoreError("Age did not produce an encrypted archive.")
            os.link(temporary, output.name, src_dir_fd=directory, dst_dir_fd=directory)
            os.fsync(directory)
        finally:
            os.close(descriptor)
            os.unlink(temporary, dir_fd=directory)
    return {"status": "LOCAL_SECRET_BACKUP_ENCRYPTED", "format": FORMAT, "documents": count}


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for name, value in pairs:
        if name in result:
            raise ValueError("Duplicate backup field.")
        result[name] = value
    return result


def restore_from_stream(root: Path, source: BinaryIO) -> dict:
    """Read host-age decrypted stdin; validate everything before touching an empty target."""
    raw = source.read(MAX_PAYLOAD + 1)
    if len(raw) > MAX_PAYLOAD:
        raise SecretStoreError("Secret restore input is too large.")
    try:
        document = json.loads(raw, object_pairs_hook=_unique_object)
        if not isinstance(document, dict) or set(document) != {"format", "files"} or document["format"] != FORMAT:
            raise ValueError
        encoded = document["files"]
        if not isinstance(encoded, dict):
            raise ValueError
        files = {name: base64.b64decode(value, validate=True) for name, value in encoded.items()}
        count = _validate(files)
    except SecretStoreError:
        raise
    except Exception:
        raise SecretStoreError("Secret restore input cannot be authenticated.") from None
    with locked_directory(root, create=True) as directory:
        if set(os.listdir(directory)) != {LOCK_NAME}:
            raise SecretStoreError("Secret restore requires an empty protected destination.")
        replace_private(directory, RESTORE_MARKER, b"restore-incomplete")
        for name, value in sorted(files.items(), key=lambda item: item[0] != MASTER_NAME):
            replace_private(directory, name, value)
        restored = {name: read_private(directory, name) for name in files}
        _validate(restored)
        if restored != files:
            raise SecretStoreError("Secret restore readback verification failed.")
        os.unlink(RESTORE_MARKER, dir_fd=directory)
        os.fsync(directory)
    return {"status": "LOCAL_SECRET_RESTORE_VERIFIED", "format": FORMAT, "documents": count}
