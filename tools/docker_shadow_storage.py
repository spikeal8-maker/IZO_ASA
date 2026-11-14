"""Owned-fixture rehearsal using the application's existing backup primitives.

This tool does not operate Docker or attest executor isolation. An independently
verified executor supplies the fixture scope. Restored-application startup and
fresh Docker volumes require separate runtime evidence.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sqlite3
import sys
import tempfile
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.storage.backup import (
    BackupError, COMPLETE_MARKER, create_backup, restore_snapshot, sha256_file,
    verify_snapshot,
)
from backend.app.storage.paths import local_media_path_from_url

MAX_DATABASE_BYTES = 64 * 1024 * 1024
MAX_MEDIA_BYTES = 128 * 1024 * 1024
MAX_ROWS = 100000


class RehearsalError(RuntimeError):
    pass


def require(condition: bool, code: str) -> None:
    if not condition:
        raise RehearsalError(code)


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=True).encode()).hexdigest()


def scope_paths(scope_file: Path) -> tuple[dict, Path, Path, Path]:
    require(not scope_file.is_symlink() and scope_file.stat().st_size <= 4096,
            "FIXTURE_SCOPE_INVALID")
    scope = json.loads(scope_file.read_text(encoding="utf-8-sig"))
    require(isinstance(scope, dict), "FIXTURE_SCOPE_INVALID")
    require(bool(re.fullmatch(r"izo-asa-shadow-[a-z0-9][a-z0-9-]{2,39}",
                              str(scope.get("project", "")))), "FIXTURE_PROJECT_INVALID")
    require(bool(re.fullmatch(r"[0-9a-f]{40}", str(scope.get("sourceSha", "")))),
            "FIXTURE_SOURCE_INVALID")
    for key in ("isolatedData", "fakeProviderOnly", "externalEffectsDisabled", "networkEgressDenied"):
        require(scope.get(key) is True, "FIXTURE_ISOLATION_NOT_ATTESTED")
    root = scope_file.parent.resolve()
    paths = []
    for key in ("database", "media"):
        value = scope.get(key)
        require(isinstance(value, str) and bool(value) and not Path(value).is_absolute(),
                "FIXTURE_PATH_INVALID")
        candidate = root / value
        resolved = candidate.resolve()
        require(not candidate.is_symlink() and resolved.is_relative_to(root)
                and resolved != root, "FIXTURE_PATH_ESCAPE")
        paths.append(resolved)
    database, media = paths
    require(database.is_file() and database.stat().st_size <= MAX_DATABASE_BYTES
            and media.is_dir() and not database.is_relative_to(media), "FIXTURE_STORAGE_INVALID")
    return scope, root, database, media


def media_state(media: Path) -> dict:
    files = {}
    total = 0
    for path in media.rglob("*"):
        require(not path.is_symlink(), "FIXTURE_MEDIA_SYMLINK")
        if path.is_file():
            require(path.resolve().is_relative_to(media.resolve()), "FIXTURE_MEDIA_ESCAPE")
            total += path.stat().st_size
            require(len(files) < 2000 and total <= MAX_MEDIA_BYTES, "FIXTURE_MEDIA_LIMIT")
            files[path.relative_to(media).as_posix()] = sha256_file(path)
    require(bool(files), "FIXTURE_MEDIA_EMPTY")
    return {"files": len(files), "bytes": total, "digest": digest(files)}


def database_state(database: Path, media: Path) -> dict:
    tables = {}
    references = 0
    with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True,
                                timeout=5)) as connection:
        connection.execute("BEGIN")
        require(connection.execute("PRAGMA integrity_check").fetchall() == [("ok",)],
                "FIXTURE_DATABASE_INTEGRITY")
        require(not connection.execute("PRAGMA foreign_key_check").fetchall(),
                "FIXTURE_DATABASE_REFERENCES")
        names = [row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        require(len(names) <= 512 and {"users", "jobs", "images", "schema_migrations"} <= set(names),
                "FIXTURE_APPLICATION_SCHEMA_REQUIRED")
        total_rows = 0
        for name in names:
            quoted = '"' + name.replace('"', '""') + '"'
            rows = []
            for row in connection.execute("SELECT * FROM " + quoted):
                total_rows += 1
                require(total_rows <= MAX_ROWS, "FIXTURE_ROW_LIMIT")
                values = [value if not isinstance(value, bytes) else {"blobSha256":
                          hashlib.sha256(value).hexdigest()} for value in row]
                rows.append(digest(values))
            columns = list(connection.execute("PRAGMA table_info(" + quoted + ")"))
            tables[name] = {"rows": len(rows), "digest": digest(sorted(rows)),
                            "schemaDigest": digest(columns)}
        require(tables["schema_migrations"]["rows"] > 0, "FIXTURE_MIGRATION_LEDGER_EMPTY")
        # These are the application's canonical/legacy image and source URLs.
        # Other feature-specific media references need their own runtime tests.
        for table, columns in (("images", ("url", "thumbnail_url")),
                               ("image_sources", ("thumb_url",))):
            if table not in names:
                continue
            available = {row[1] for row in connection.execute("PRAGMA table_info(" + table + ")")}
            for column in columns:
                require(column in available, "FIXTURE_MEDIA_SCHEMA_INVALID")
                for (url,) in connection.execute("SELECT " + column + " FROM " + table):
                    if not url:
                        continue
                    require(isinstance(url, str) and url.startswith(("/api/media/", "/media/")),
                            "FIXTURE_IMAGE_REFERENCE_UNSUPPORTED")
                    path = local_media_path_from_url(media, url)
                    require(path is not None, "FIXTURE_IMAGE_REFERENCE_MISSING")
                    references += 1
    return {"tables": tables, "imageReferences": references,
            "migrationLedger": tables["schema_migrations"]}


def expect_rejection(backup: Path, destination: Path, snapshot: str) -> str:
    try:
        restore_snapshot(backup, destination, snapshot)
    except BackupError as error:
        require(not destination.exists(), "INVALID_RESTORE_WROTE_DESTINATION")
        code = str(error)
        return code if re.fullmatch(r"[a-z_]+", code) else "backup_rejected"
    raise RehearsalError("INVALID_BACKUP_ACCEPTED")


def rehearse(scope_file: Path, work_parent: Path) -> dict:
    scope, fixture_root, database, media = scope_paths(scope_file)
    work_parent = work_parent.resolve()
    require(work_parent.is_dir() and not work_parent.is_relative_to(fixture_root),
            "REHEARSAL_WORKSPACE_INVALID")
    before = {"database": database_state(database, media), "media": media_state(media)}
    result = {"project": scope["project"], "sourceSha": scope["sourceSha"], "status": "FAIL",
              "executorIsolation": "EXTERNAL_ATTESTATION_REQUIRED", "sourceState": before,
              "freshDockerVolumes": "NOT_VERIFIED", "restoredApplication": "NOT_VERIFIED",
              "referenceCoverage": "images.url, images.thumbnail_url, image_sources.thumb_url"}
    temporary_path = None
    with tempfile.TemporaryDirectory(prefix="izo-storage-", dir=work_parent) as temporary:
        temporary_path = Path(temporary)
        backup = temporary_path / "backup"
        # Same-volume exception is restricted to this disposable fixture rehearsal.
        saved = create_backup(database, media, backup, require_separate_volume=False)
        verify_snapshot(backup, saved.snapshot_id)
        restored = temporary_path / "restored"
        restore_snapshot(backup, restored, saved.snapshot_id)
        after = {"database": database_state(restored / "database.sqlite3", restored / "media"),
                 "media": media_state(restored / "media")}
        require(after == before, "RESTORED_FIXTURE_MISMATCH")
        result["restore"] = "PASS"
        result["negativeCases"] = {}
        for kind in ("database", "media", "incomplete"):
            damaged = temporary_path / ("damaged-" + kind)
            shutil.copytree(backup, damaged)
            snapshot = damaged / "snapshots" / saved.snapshot_id
            if kind == "database":
                with (snapshot / "database.sqlite3").open("r+b") as stream:
                    stream.write(b"invalid SQLite!!")
            elif kind == "media":
                obj = next(path for path in (damaged / "media-objects").rglob("*") if path.is_file())
                obj.write_bytes(b"corrupt fixture")
            else:
                (snapshot / COMPLETE_MARKER).unlink()
            result["negativeCases"][kind] = expect_rejection(
                damaged, temporary_path / ("refused-" + kind), saved.snapshot_id)
            verify_snapshot(backup, saved.snapshot_id)
        require({"database": database_state(database, media), "media": media_state(media)} == before,
                "SOURCE_FIXTURE_CHANGED")
    require(temporary_path is not None and not temporary_path.exists(), "REHEARSAL_CLEANUP_FAILED")
    result.update(status="STORAGE_REHEARSAL_PASS", cleanup="PASS", sourceUnchanged="PASS")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture-scope", required=True, type=Path)
    parser.add_argument("--work-parent", required=True, type=Path)
    parser.add_argument("--receipt", required=True, type=Path)
    args = parser.parse_args()
    work = receipt = None
    receipt_owned = False
    try:
        work = args.work_parent.resolve()
        receipt = args.receipt.resolve()
        fixture_root = args.fixture_scope.parent.resolve()
        require(work.is_dir() and receipt.is_relative_to(work) and receipt.parent.is_dir()
                and not receipt.exists() and not work.is_relative_to(fixture_root)
                and not receipt.is_relative_to(fixture_root),
                "RECEIPT_PATH_NOT_NEW_OWNED_WORKSPACE")
        receipt_owned = True
        result = rehearse(args.fixture_scope, args.work_parent)
    except Exception as error:
        # Never echo SQL values, filesystem paths or private media URLs.
        result = {"status": "FAIL", "exceptionType": type(error).__name__}
        if isinstance(error, RehearsalError):
            result["code"] = str(error)
    try:
        # Never replace a pre-existing file, including on a failed preflight.
        require(receipt_owned and work is not None and receipt is not None and work.is_dir()
                and receipt.is_relative_to(work) and receipt.parent.is_dir(),
                "RECEIPT_PATH_NOT_NEW_OWNED_WORKSPACE")
        with receipt.open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(result, indent=2) + "\n")
    except (OSError, RehearsalError):
        print("RECEIPT_WRITE_FAILED")
        return 1
    print(result["status"])
    return 0 if result["status"] == "STORAGE_REHEARSAL_PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
