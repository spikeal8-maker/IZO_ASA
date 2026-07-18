"""Apply bounded retention to verified local or Yandex.Disk backup snapshots."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Hashable


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.storage.backup import BackupError, COMPLETE_MARKER, verify_snapshot  # noqa: E402
from backup_transport import verify_cloud_snapshot  # noqa: E402


@dataclass(frozen=True)
class SnapshotRecord:
    snapshot_id: str
    path: Path
    created_at: datetime
    database_bytes: int


@dataclass(frozen=True)
class RetentionPlan:
    scope: str
    root: Path
    snapshots_root: Path
    manifests_root: Path
    records: tuple[SnapshotRecord, ...]
    keep_ids: frozenset[str]
    delete_records: tuple[SnapshotRecord, ...]
    incomplete_delete_ids: tuple[str, ...]
    incomplete_ids: tuple[str, ...]
    policy: dict[str, int]

    @property
    def reclaim_bytes(self) -> int:
        return sum(record.database_bytes for record in self.delete_records)


def parse_snapshot_id(snapshot_id: str) -> datetime:
    try:
        parsed = datetime.strptime(snapshot_id, "%Y%m%dT%H%M%S.%fZ")
    except ValueError as exc:
        raise BackupError(f"invalid_snapshot_id:{snapshot_id}") from exc
    return parsed.replace(tzinfo=timezone.utc)


def _layout(scope: str, root: Path) -> tuple[Path, Path]:
    if scope == "local":
        return root / "snapshots", root / "manifests"
    if scope == "cloud":
        return root / "database" / "snapshots", root / "recovery" / "manifests"
    raise BackupError(f"unsupported_retention_scope:{scope}")


def discover_snapshots(
    scope: str, root: Path
) -> tuple[tuple[SnapshotRecord, ...], tuple[SnapshotRecord, ...], tuple[str, ...]]:
    snapshots_root, _manifests_root = _layout(scope, root)
    if not snapshots_root.is_dir():
        raise BackupError(f"snapshot_root_unavailable:{snapshots_root}")
    records: list[SnapshotRecord] = []
    incomplete: list[SnapshotRecord] = []
    unsafe_names: list[str] = []
    for path in sorted(snapshots_root.iterdir(), key=lambda item: item.name):
        if not path.is_dir() or path.is_symlink():
            continue
        try:
            created_at = parse_snapshot_id(path.name)
        except BackupError:
            unsafe_names.append(path.name)
            continue
        database = path / "database.sqlite3"
        marker = path / COMPLETE_MARKER
        record = SnapshotRecord(
            snapshot_id=path.name,
            path=path,
            created_at=created_at,
            database_bytes=database.stat().st_size if database.is_file() else 0,
        )
        if not database.is_file() or not marker.is_file():
            incomplete.append(record)
            continue
        records.append(record)
    return tuple(records), tuple(incomplete), tuple(unsafe_names)


def _latest_per_bucket(
    records: tuple[SnapshotRecord, ...],
    bucket: Callable[[datetime], Hashable],
    limit: int,
) -> set[str]:
    latest: dict[Hashable, SnapshotRecord] = {}
    for record in records:
        latest[bucket(record.created_at)] = record
    selected = sorted(latest.values(), key=lambda record: record.created_at, reverse=True)[:limit]
    return {record.snapshot_id for record in selected}


def select_local_snapshots(
    records: tuple[SnapshotRecord, ...], hourly: int = 24, daily: int = 14, weekly: int = 8
) -> frozenset[str]:
    if not records:
        raise BackupError("no_completed_snapshots")
    keep = {records[-1].snapshot_id}
    keep.update(_latest_per_bucket(records, lambda value: value.strftime("%Y-%m-%dT%H"), hourly))
    keep.update(_latest_per_bucket(records, lambda value: value.date(), daily))
    keep.update(
        _latest_per_bucket(
            records,
            lambda value: (value.isocalendar().year, value.isocalendar().week),
            weekly,
        )
    )
    return frozenset(keep)


def select_cloud_snapshots(
    records: tuple[SnapshotRecord, ...], daily: int = 30, monthly: int = 12
) -> frozenset[str]:
    if not records:
        raise BackupError("no_completed_cloud_snapshots")
    keep = {records[-1].snapshot_id}
    keep.update(_latest_per_bucket(records, lambda value: value.date(), daily))
    keep.update(_latest_per_bucket(records, lambda value: (value.year, value.month), monthly))
    return frozenset(keep)


def build_plan(
    scope: str,
    root: Path,
    *,
    local_hourly: int = 24,
    local_daily: int = 14,
    local_weekly: int = 8,
    cloud_daily: int = 30,
    cloud_monthly: int = 12,
    incomplete_grace_hours: int = 6,
) -> RetentionPlan:
    resolved = root.expanduser().resolve()
    snapshots_root, manifests_root = _layout(scope, resolved)
    records, incomplete, unsafe_names = discover_snapshots(scope, resolved)
    if scope == "local":
        policy = {"hourly": local_hourly, "daily": local_daily, "weekly": local_weekly}
        keep_ids = select_local_snapshots(records, local_hourly, local_daily, local_weekly)
    else:
        policy = {"daily": cloud_daily, "monthly": cloud_monthly}
        keep_ids = select_cloud_snapshots(records, cloud_daily, cloud_monthly)
    incomplete_cutoff = datetime.now(timezone.utc) - timedelta(hours=incomplete_grace_hours)
    expired_incomplete = tuple(record for record in incomplete if record.created_at <= incomplete_cutoff)
    recent_incomplete = tuple(record.snapshot_id for record in incomplete if record.created_at > incomplete_cutoff)
    delete_records = tuple(
        sorted(
            (record for record in records if record.snapshot_id not in keep_ids),
            key=lambda record: record.created_at,
        )
    ) + expired_incomplete
    policy["incomplete_grace_hours"] = incomplete_grace_hours
    return RetentionPlan(
        scope=scope,
        root=resolved,
        snapshots_root=snapshots_root,
        manifests_root=manifests_root,
        records=records,
        keep_ids=keep_ids,
        delete_records=delete_records,
        incomplete_delete_ids=tuple(record.snapshot_id for record in expired_incomplete),
        incomplete_ids=tuple((*recent_incomplete, *unsafe_names)),
        policy=policy,
    )


def _report_document(plan: RetentionPlan, status: str, deleted_ids: list[str] | None = None) -> dict[str, object]:
    return {
        "version": 1,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "scope": plan.scope,
        "root": str(plan.root),
        "policy": plan.policy,
        "total_completed": len(plan.records),
        "keep_count": len(plan.keep_ids),
        "delete_count": len(plan.delete_records),
        "reclaim_bytes": plan.reclaim_bytes,
        "keep_ids": sorted(plan.keep_ids),
        "delete_ids": [record.snapshot_id for record in plan.delete_records],
        "incomplete_delete_ids": list(plan.incomplete_delete_ids),
        "incomplete_ids_untouched": list(plan.incomplete_ids),
        "deleted_ids": deleted_ids or [],
        "media_objects_touched": False,
    }


def write_report(path: Path, document: dict[str, object]) -> None:
    destination = path.expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".tmp")
    temporary.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(destination)


def _assert_direct_snapshot_child(plan: RetentionPlan, record: SnapshotRecord) -> None:
    if record.path.parent.resolve() != plan.snapshots_root.resolve():
        raise BackupError(f"unsafe_snapshot_delete_path:{record.path}")
    if record.path.name != record.snapshot_id or parse_snapshot_id(record.snapshot_id) != record.created_at:
        raise BackupError(f"unsafe_snapshot_identity:{record.snapshot_id}")
    if record.snapshot_id in plan.keep_ids:
        raise BackupError(f"retained_snapshot_selected_for_delete:{record.snapshot_id}")


def verify_latest(plan: RetentionPlan) -> None:
    latest = plan.records[-1].snapshot_id
    if latest not in plan.keep_ids:
        raise BackupError("latest_snapshot_not_retained")
    if plan.scope == "local":
        verify_snapshot(plan.root, latest)
    else:
        verify_cloud_snapshot(plan.root, latest)


def apply_plan(plan: RetentionPlan) -> list[str]:
    verify_latest(plan)
    deleted: list[str] = []
    for record in plan.delete_records:
        _assert_direct_snapshot_child(plan, record)
        shutil.rmtree(record.path)
        (plan.manifests_root / f"{record.snapshot_id}.json").unlink(missing_ok=True)
        deleted.append(record.snapshot_id)
    verify_latest(plan)
    return deleted


def _read_backup_root(config_path: Path) -> Path:
    try:
        document = json.loads(config_path.expanduser().resolve().read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BackupError("backup_config_unreadable") from exc
    if document.get("version") != 1 or not str(document.get("backup_root", "")).strip():
        raise BackupError("backup_config_invalid")
    return Path(document["backup_root"])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope", choices=("local", "cloud"), required=True)
    parser.add_argument("--config", type=Path, default=Path(r"C:\IZO_ASA\config\backup.json"))
    parser.add_argument("--cloud-root", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--local-hourly", type=int, default=24)
    parser.add_argument("--local-daily", type=int, default=14)
    parser.add_argument("--local-weekly", type=int, default=8)
    parser.add_argument("--cloud-daily", type=int, default=30)
    parser.add_argument("--cloud-monthly", type=int, default=12)
    parser.add_argument("--incomplete-grace-hours", type=int, default=6)
    args = parser.parse_args()
    try:
        counts = (
            args.local_hourly,
            args.local_daily,
            args.local_weekly,
            args.cloud_daily,
            args.cloud_monthly,
        )
        if any(value < 1 for value in counts) or args.incomplete_grace_hours < 1:
            raise BackupError("retention_count_must_be_positive")
        if args.scope == "local":
            root = _read_backup_root(args.config)
        elif args.cloud_root is None:
            raise BackupError("cloud_root_required")
        else:
            root = args.cloud_root
        plan = build_plan(
            args.scope,
            root,
            local_hourly=args.local_hourly,
            local_daily=args.local_daily,
            local_weekly=args.local_weekly,
            cloud_daily=args.cloud_daily,
            cloud_monthly=args.cloud_monthly,
            incomplete_grace_hours=args.incomplete_grace_hours,
        )
        write_report(args.report, _report_document(plan, "planned"))
        print(
            f"BACKUP_RETENTION_PLAN_OK scope={plan.scope} total={len(plan.records)} "
            f"keep={len(plan.keep_ids)} delete={len(plan.delete_records)} "
            f"reclaimBytes={plan.reclaim_bytes} incompleteUntouched={len(plan.incomplete_ids)}"
        )
        if not args.apply:
            return 0
        deleted = apply_plan(plan)
        write_report(args.report, _report_document(plan, "completed", deleted))
        print(
            f"BACKUP_RETENTION_OK scope={plan.scope} kept={len(plan.keep_ids)} "
            f"deleted={len(deleted)} reclaimedBytes={plan.reclaim_bytes}"
        )
        return 0
    except (BackupError, OSError) as exc:
        print(f"BACKUP_RETENTION_ERROR reason={exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
