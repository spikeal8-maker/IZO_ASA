"""Video gallery quota policy and repository helpers."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from typing import Any, Protocol
import uuid


VIDEO_JOB_MODES = (
    "text_to_video",
    "image_to_video",
    "first_last_frame",
    "reference_to_video",
)
VIDEO_RESERVED_STATUSES = (
    "submitting",
    "queued",
    "pending",
    "in_progress",
    "finalizing",
)


def finalization_is_fresh(settings: dict[str, Any], *, stale_seconds: int) -> bool:
    value = str(settings.get("finalizingAt") or "")
    try:
        started = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - started).total_seconds() < stale_seconds


class VideoRefreshSuperseded(Exception):
    """A newer durable transition owns this job; return its current snapshot."""
    def __init__(self, row):
        super().__init__("VIDEO_REFRESH_SUPERSEDED")
        self.row = row


_download_claim = ContextVar("video_finalization_download", default=None)


def _current_video(conn, job_id, error_factory):
    row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    if row is None or row["mode"] not in VIDEO_JOB_MODES:
        raise error_factory(404, "Видео-задание не найдено.")
    return row


def _same_refresh(current, expected):
    return current["status"] in VIDEO_RESERVED_STATUSES and all(
        current[key] == expected[key]
        for key in ("id", "user_id", "mode", "provider", "status", "settings_json")
    )


def claim_finalization(connect, job_id, *, stale_seconds, error_factory, expected=None):
    """Claim only the active video snapshot observed before provider I/O."""
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        current = _current_video(conn, job_id, error_factory)
        if current["status"] not in VIDEO_RESERVED_STATUSES or (
            expected is not None and not _same_refresh(current, expected)
        ):
            return False, current
        settings = json.loads(current["settings_json"] or "{}")
        if current["status"] == "finalizing" and finalization_is_fresh(settings, stale_seconds=stale_seconds):
            return False, current
        settings.update(finalizingAt=datetime.now(timezone.utc).isoformat(), finalizingToken=uuid.uuid4().hex)
        settings.pop("finalizingError", None)
        conn.execute("UPDATE jobs SET status='finalizing',progress=90,settings_json=? WHERE id=?",
                     (json.dumps(settings, ensure_ascii=False), job_id))
        return True, _current_video(conn, job_id, error_factory)


@contextmanager
def refresh_transaction(connect, expected, *, error_factory):
    """Fence refund, gallery mutation and final state together; no await inside."""
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        current = _current_video(conn, expected["id"], error_factory)
        if not _same_refresh(current, expected):
            raise VideoRefreshSuperseded(current)
        yield conn


def release_finalization(connect, job_id, error, *, expected, error_factory, public_error=None):
    """Release this exact claim; an old error cannot reset a newer terminal job."""
    try:
        with refresh_transaction(connect, expected, error_factory=error_factory) as conn:
            if expected["id"] != job_id or expected["status"] != "finalizing":
                raise ValueError("VIDEO_FINALIZATION_CLAIM_INVALID")
            settings = json.loads(expected["settings_json"] or "{}")
            settings.pop("finalizingAt", None)
            settings.pop("finalizingToken", None)
            settings["finalizingError"] = str(error)[:500]
            conn.execute("UPDATE jobs SET status='pending',progress=85,error_message=?,settings_json=? WHERE id=?",
                         (str(error if public_error is None else public_error)[:500],
                          json.dumps(settings, ensure_ascii=False), job_id))
            return True, _current_video(conn, job_id, error_factory)
    except VideoRefreshSuperseded as loss:
        return False, loss.row


@contextmanager
def finalizing_download(row):
    """Give each claim its own file, including during stale-claim recovery."""
    token = json.loads(row["settings_json"] or "{}").get("finalizingToken")
    if row["status"] != "finalizing" or not isinstance(token, str) or uuid.UUID(hex=token).hex != token:
        raise ValueError("VIDEO_FINALIZATION_CLAIM_INVALID")
    marker = _download_claim.set((row["id"], token))
    try:
        yield
    finally:
        _download_claim.reset(marker)


def download_filename(job_id):
    claim = _download_claim.get()
    if claim is not None and claim[0] == job_id:
        return f"{job_id}_{claim[1]}.mp4"
    return f"{job_id}.mp4"


class VideoStorageConnection(Protocol):
    def execute(self, sql: str, parameters: tuple[Any, ...] = ()) -> Any: ...


@dataclass(frozen=True)
class VideoStorageState:
    limit: int
    active: int
    favorite: int
    reserved: int
    stored_bytes: int

    @property
    def free(self) -> int:
        return max(0, self.limit - self.active)

    @property
    def full(self) -> bool:
        return self.limit <= 0 or self.active >= self.limit

    @property
    def protected(self) -> int:
        return self.favorite + self.reserved

    @property
    def can_reserve(self) -> bool:
        return self.limit > 0 and self.protected < self.limit


def storage_state(
    conn: VideoStorageConnection,
    user_id: str,
    *,
    limit: int,
    exclude_job_id: str | None = None,
) -> VideoStorageState:
    video_row = conn.execute(
        "SELECT COUNT(*) AS active, "
        "COALESCE(SUM(CASE WHEN is_favorite = 1 THEN 1 ELSE 0 END), 0) AS favorite, "
        "COALESCE(SUM(stored_bytes), 0) AS stored_bytes "
        "FROM videos WHERE user_id = ? AND deleted_at IS NULL",
        (user_id,),
    ).fetchone()
    mode_slots = ",".join("?" for _ in VIDEO_JOB_MODES)
    status_slots = ",".join("?" for _ in VIDEO_RESERVED_STATUSES)
    params: list[Any] = [user_id, *VIDEO_JOB_MODES, *VIDEO_RESERVED_STATUSES]
    exclude_sql = ""
    if exclude_job_id:
        exclude_sql = " AND id <> ?"
        params.append(exclude_job_id)
    reserved_row = conn.execute(
        f"SELECT COUNT(*) AS c FROM jobs WHERE user_id = ? "
        f"AND mode IN ({mode_slots}) AND status IN ({status_slots}){exclude_sql}",
        tuple(params),
    ).fetchone()
    return VideoStorageState(
        limit=max(0, int(limit or 0)),
        active=int(video_row["active"] or 0),
        favorite=int(video_row["favorite"] or 0),
        reserved=int(reserved_row["c"] or 0),
        stored_bytes=int(video_row["stored_bytes"] or 0),
    )


def eviction_target(*, limit: int, active: int) -> int:
    """Shrink downgraded accounts gradually while making room for one result."""
    limit = max(0, int(limit or 0))
    active = max(0, int(active or 0))
    if limit <= 0 or active < limit:
        return 0
    return 2 if active > limit else 1


def select_eviction_candidates(
    conn: VideoStorageConnection,
    user_id: str,
    *,
    limit: int,
) -> list[Any]:
    state = storage_state(conn, user_id, limit=limit)
    target = eviction_target(limit=state.limit, active=state.active)
    if target <= 0:
        return []
    return list(
        conn.execute(
            "SELECT v.*, j.settings_json AS job_settings "
            "FROM videos v LEFT JOIN jobs j ON j.id = v.job_id "
            "WHERE v.user_id = ? AND v.deleted_at IS NULL AND v.is_favorite = 0 "
            "ORDER BY v.created_at ASC, v.id ASC LIMIT ?",
            (user_id, target),
        ).fetchall()
    )
