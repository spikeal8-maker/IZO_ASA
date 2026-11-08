"""Encrypt a local snapshot as the secret owner inside the verified backend image."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--secret-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--recipient", required=True)
    parser.add_argument("--age-binary", default="age")
    parser.add_argument("--backend-root", type=Path, default=Path("/opt/izo/backend"))
    args = parser.parse_args()
    roots = (Path("/opt/izo/backend"), Path(__file__).resolve().parents[1] / "backend")
    backend = args.backend_root
    if backend not in roots or not (backend / "app/security/linux_secret_backup.py").is_file():
        print('{"status":"VERIFIED_BACKEND_RUNTIME_REQUIRED"}')
        return 2
    sys.path.insert(0, str(backend))
    from app.security.linux_secret_backup import encrypted_backup
    from app.security.secret_store import SecretStoreError
    try:
        result = encrypted_backup(args.secret_dir, args.output, args.recipient, age_binary=args.age_binary)
    except (SecretStoreError, OSError):
        print('{"status":"LOCAL_SECRET_BACKUP_UNCONFIRMED"}')
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
