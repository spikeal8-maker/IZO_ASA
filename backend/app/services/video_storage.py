"""Video gallery quota policy and repository helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


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
