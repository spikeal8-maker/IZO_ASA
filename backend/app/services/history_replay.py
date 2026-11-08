"""Explicit, immutable replay boundaries for restored database clones.

Migrations own the two tables. Only an offline, explicit seal writes them;
normal application initialization validates the seal and performs no writes.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from types import MappingProxyType

RESOURCE_COLUMNS = MappingProxyType({
    "users": "id",
    "jobs": "id",
    "images": "id",
    "videos": "id",
    "token_ledger": "id",
    "invoices": "id",
    "payments": "id",
    "payment_provider_events": "id",
    "refunds": "id",
    "payment_notification_outbox": "id",
    "admin_notifications": "id",
    "admin_notification_delivery_outbox": "id",
    "social_delivery_outbox": "id",
    "feed_publications": "id",
    "video_file_deletions": "id",
    "tariff_token_grants": "id",
    "promo_redemptions": "id",
    "bonus_grants": "id",
    "referral_rewards": "id",
    "generation_trial_reservations": "job_id",
    "account_verifications": "internal_user_id",
})
_REQUIRED_RESOURCES = frozenset(("users", "jobs", "images", "videos", "token_ledger"))
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?")
_HEX_SHA256 = re.compile(r"[0-9a-f]{64}")


class HistoryReplayConfigurationError(RuntimeError):
    """Preservation was requested without a valid immutable boundary."""


class HistoricalReplayBlocked(RuntimeError):
    """An automatic execution or settlement targets restored history."""


def history_preservation_enabled(environment: Mapping[str, str]) -> bool:
    value = environment.get("IZO_PREPROD_PRESERVE_HISTORY", "").strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"", "0", "false", "no", "off"}:
        return False
    raise HistoryReplayConfigurationError("Invalid history preservation setting")


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _identity(value: object) -> str:
    if not isinstance(value, (str, int)) or isinstance(value, bool) or not str(value):
        raise HistoryReplayConfigurationError("Missing or invalid replay resource identity")
    return str(value)


def _resource(resource: str) -> str:
    if resource not in RESOURCE_COLUMNS:
        raise HistoryReplayConfigurationError("Unknown replay resource")
    return resource


def _column(column: str) -> str:
    if not isinstance(column, str) or not _IDENTIFIER.fullmatch(column):
        raise HistoryReplayConfigurationError("Invalid replay SQL identifier")
    return ".".join('"' + part + '"' for part in column.split("."))


def _digest(ids: Iterable[str], *, present: bool) -> dict[str, object]:
    ordered = sorted(ids)
    return {"count": len(ordered), "sha256": _sha256(_canonical(ordered)), "present": present}


@dataclass(frozen=True)
class HistoryReplayPolicy:
    enabled: bool
    snapshot_id: str | None
    _resources: Mapping[str, frozenset[str]]

    @property
    def automatic_history_mutation_allowed(self) -> bool:
        """Implicit tariff/recovery work must never run while history is preserved."""
        return not self.enabled

    def is_historical(self, resource: str, resource_id: str) -> bool:
        name, identity = _resource(resource), _identity(resource_id)
        return self.enabled and identity in self._resources[name]

    def require_allowed(
        self,
        resource: str,
        resource_id: str,
        *,
        parents: Iterable[tuple[str, str]] = (),
    ) -> None:
        """Check the work itself and every caller-declared replay-sensitive parent."""
        for name, identity in ((resource, resource_id), *parents):
            if self.is_historical(name, identity):
                raise HistoricalReplayBlocked(f"Historical {name} replay is blocked")

    def where_allowed(
        self,
        resource: str,
        id_column: str,
        *,
        parents: Iterable[tuple[str, str]] = (),
    ) -> tuple[str, tuple[str, ...]]:
        """Return SQL plus bindings, including optional parent ID column guards.

        Columns are identifiers, never SQL expressions. NULL identifiers fail
        closed in enabled mode; supply only mandatory parents for this operation.
        """
        clauses, parameters = [], []
        for name, column in ((resource, id_column), *parents):
            name, column = _resource(name), _column(column)
            if self.enabled:
                clauses.append(
                    f"{column} IS NOT NULL AND CAST({column} AS TEXT) NOT IN "
                    "(SELECT resource_id FROM history_replay_resources "
                    "WHERE snapshot_id = ? AND resource = ?)"
                )
                parameters.extend((self.snapshot_id, name))
        return " AND ".join(clauses) or "1 = 1", tuple(parameters)


def _schema_available(conn: sqlite3.Connection) -> None:
    try:
        conn.execute(
            "SELECT singleton, snapshot_id, sealed_at, manifest_json, manifest_sha256 "
            "FROM history_replay_boundary LIMIT 0"
        )
        conn.execute(
            "SELECT snapshot_id, resource, resource_id FROM history_replay_resources LIMIT 0"
        )
    except sqlite3.DatabaseError as exc:
        raise HistoryReplayConfigurationError("History replay migration is required") from exc


def _load_boundary(
    conn: sqlite3.Connection, expected_snapshot_id: str | None,
) -> tuple[str, dict[str, object], dict[str, frozenset[str]]]:
    _schema_available(conn)
    rows = conn.execute(
        "SELECT singleton, snapshot_id, sealed_at, manifest_json, manifest_sha256 "
        "FROM history_replay_boundary"
    ).fetchall()
    if len(rows) != 1 or rows[0][0] != 1:
        raise HistoryReplayConfigurationError("Exactly one history boundary is required")
    _, snapshot_id, sealed_at, raw_manifest, manifest_hash = tuple(rows[0])
    if not isinstance(snapshot_id, str) or not snapshot_id or not sealed_at:
        raise HistoryReplayConfigurationError("Invalid history boundary identity")
    if expected_snapshot_id is not None and snapshot_id != _identity(expected_snapshot_id):
        raise HistoryReplayConfigurationError("History snapshot does not match")
    try:
        manifest = json.loads(raw_manifest)
    except (TypeError, ValueError) as exc:
        raise HistoryReplayConfigurationError("Invalid history manifest") from exc
    if not isinstance(manifest, dict) or set(manifest) != {"version", "resources"}:
        raise HistoryReplayConfigurationError("Invalid history manifest shape")
    if manifest["version"] != 1 or _canonical(manifest) != raw_manifest:
        raise HistoryReplayConfigurationError("Unsupported or noncanonical history manifest")
    if _sha256(raw_manifest) != manifest_hash:
        raise HistoryReplayConfigurationError("History manifest checksum does not match")
    expected = manifest["resources"]
    if not isinstance(expected, dict) or set(expected) != set(RESOURCE_COLUMNS):
        raise HistoryReplayConfigurationError("Incomplete history resource manifest")
    collected: dict[str, set[str]] = {name: set() for name in RESOURCE_COLUMNS}
    for row in conn.execute(
        "SELECT snapshot_id, resource, resource_id FROM history_replay_resources"
    ):
        fence_snapshot, name, identity = tuple(row)
        if fence_snapshot != snapshot_id or name not in collected:
            raise HistoryReplayConfigurationError("Foreign history fence entry")
        identity = _identity(identity)
        if identity in collected[name]:
            raise HistoryReplayConfigurationError("Duplicate history fence entry")
        collected[name].add(identity)
    for name, ids in collected.items():
        entry = expected[name]
        if (
            not isinstance(entry, dict)
            or set(entry) != {"count", "sha256", "present"}
            or type(entry["count"]) is not int
            or type(entry["present"]) is not bool
            or not isinstance(entry["sha256"], str)
            or not _HEX_SHA256.fullmatch(entry["sha256"])
            or (not entry["present"] and ids)
            or (name in _REQUIRED_RESOURCES and not entry["present"])
            or entry != _digest(ids, present=entry["present"])
        ):
            raise HistoryReplayConfigurationError(f"Invalid history resource seal: {name}")
    return snapshot_id, manifest, {name: frozenset(ids) for name, ids in collected.items()}


def initialize_history_replay(
    conn: sqlite3.Connection,
    *,
    enabled: bool,
    expected_snapshot_id: str | None = None,
) -> HistoryReplayPolicy:
    """Read and validate once before recovery, workers or user side effects."""
    if not enabled:
        return HistoryReplayPolicy(False, None, MappingProxyType({}))
    snapshot_id, _, resources = _load_boundary(conn, expected_snapshot_id)
    return HistoryReplayPolicy(True, snapshot_id, MappingProxyType(resources))


def _check_counts(manifest: Mapping[str, object], expected_counts: Mapping[str, int] | None) -> None:
    resources = manifest["resources"]
    for name, count in (expected_counts or {}).items():
        _resource(name)
        if type(count) is not int or count < 0 or resources[name]["count"] != count:
            raise HistoryReplayConfigurationError(f"Source snapshot count does not match: {name}")


def seal_restored_history(
    conn: sqlite3.Connection,
    *,
    snapshot_id: str,
    expected_counts: Mapping[str, int] | None = None,
) -> HistoryReplayPolicy:
    """Explicit offline seal; caller owns the outer transaction and commit.

    Acquire a write reservation before reading. A second seal validates the
    original sets, never snapshots live tables again. No source rows or DDL are
    changed. A failed insertion rolls back this function's savepoint only.
    """
    snapshot_id = _identity(snapshot_id)
    _schema_available(conn)
    if conn.in_transaction:
        conn.execute("UPDATE history_replay_boundary SET singleton = singleton WHERE 0")
    else:
        conn.execute("BEGIN IMMEDIATE")
    existing = conn.execute("SELECT 1 FROM history_replay_boundary").fetchone()
    if existing:
        _, manifest, resources = _load_boundary(conn, snapshot_id)
        _check_counts(manifest, expected_counts)
        return HistoryReplayPolicy(True, snapshot_id, MappingProxyType(resources))
    if conn.execute("SELECT 1 FROM history_replay_resources LIMIT 1").fetchone():
        raise HistoryReplayConfigurationError("Unsealed history fence entries already exist")
    tables = {
        row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    if not _REQUIRED_RESOURCES.issubset(tables):
        raise HistoryReplayConfigurationError("Required source snapshot tables are missing")
    captured: dict[str, frozenset[str]] = {}
    entries = {}
    for name, column in RESOURCE_COLUMNS.items():
        if name in tables:
            columns = {row[1] for row in conn.execute(f'PRAGMA table_info("{name}")')}
            if column not in columns:
                raise HistoryReplayConfigurationError(f"Source identity column is missing: {name}")
        ids = [
            _identity(row[0])
            for row in conn.execute(f'SELECT "{name}"."{column}" FROM "{name}"')
        ] if name in tables else []
        if len(ids) != len(set(ids)):
            raise HistoryReplayConfigurationError(f"Duplicate source identity: {name}")
        captured[name] = frozenset(ids)
        entries[name] = _digest(ids, present=name in tables)
    manifest = {"version": 1, "resources": entries}
    _check_counts(manifest, expected_counts)
    raw_manifest = _canonical(manifest)
    conn.execute("SAVEPOINT history_replay_seal")
    try:
        conn.executemany(
            "INSERT INTO history_replay_resources (snapshot_id, resource, resource_id) "
            "VALUES (?, ?, ?)",
            (
                (snapshot_id, name, identity)
                for name, ids in captured.items() for identity in sorted(ids)
            ),
        )
        conn.execute(
            "INSERT INTO history_replay_boundary "
            "(singleton, snapshot_id, sealed_at, manifest_json, manifest_sha256) "
            "VALUES (1, ?, ?, ?, ?)",
            (
                snapshot_id, datetime.now(timezone.utc).isoformat(),
                raw_manifest, _sha256(raw_manifest),
            ),
        )
        conn.execute("RELEASE SAVEPOINT history_replay_seal")
    except BaseException:
        conn.execute("ROLLBACK TO SAVEPOINT history_replay_seal")
        conn.execute("RELEASE SAVEPOINT history_replay_seal")
        raise
    return HistoryReplayPolicy(True, snapshot_id, MappingProxyType(captured))


def history_policy_for_connection(
    conn: sqlite3.Connection,
    *,
    environment: Mapping[str, str] | None = None,
) -> HistoryReplayPolicy:
    """Resolve the actual connection; never cache a policy across databases."""
    environment = os.environ if environment is None else environment
    return initialize_history_replay(
        conn, enabled=history_preservation_enabled(environment),
        expected_snapshot_id=environment.get("IZO_HISTORY_SNAPSHOT_ID") or None,
    )
