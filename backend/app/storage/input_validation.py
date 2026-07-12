"""Generation media input validation independent from FastAPI."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from .media_references import (
    find_owned_active_image,
    owned_active_source_exists,
    owned_job_media_reference_exists,
)


@dataclass(frozen=True)
class MediaInputValidationRuntime:
    connect: Callable[[], sqlite3.Connection]
    filename_from_url: Callable[[str], str | None]
    resolve_local_media: Callable[[str], Path | None]
    active_image_where: str


class MediaInputValidationError(RuntimeError):
    def __init__(self, code: str, field: str):
        super().__init__(code)
        self.code = code
        self.field = field


def validate_owned_media_inputs(
    runtime: MediaInputValidationRuntime,
    candidates: Iterable[tuple[str, str]],
    user_id: str,
) -> None:
    with runtime.connect() as conn:
        for field, value in candidates:
            filename = runtime.filename_from_url(value)
            if not filename:
                continue
            if not runtime.resolve_local_media(value):
                raise MediaInputValidationError("input_media_missing", field)
            if find_owned_active_image(
                conn,
                filename,
                user_id,
                active_image_where=runtime.active_image_where,
            ):
                continue
            if owned_active_source_exists(
                conn,
                filename,
                user_id,
                active_image_where=runtime.active_image_where,
            ):
                continue
            if owned_job_media_reference_exists(conn, filename, user_id):
                continue
            raise MediaInputValidationError("input_media_unavailable", field)
