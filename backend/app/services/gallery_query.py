"""Pure gallery cursor and full-text query helpers."""

from __future__ import annotations

import base64
import json
import re
from collections.abc import Mapping
from typing import Any


class GalleryCursorError(ValueError):
    """Raised when a gallery cursor cannot be decoded safely."""


def encode_gallery_cursor(created_at: Any, image_id: Any) -> str:
    payload = {"created_at": created_at or "", "id": image_id or ""}
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_gallery_cursor(cursor: str | None) -> tuple[str, str] | None:
    if not cursor:
        return None
    try:
        padded = cursor + ("=" * (-len(cursor) % 4))
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
        if not isinstance(payload, Mapping):
            raise GalleryCursorError("invalid gallery cursor")
        created_at = str(payload.get("created_at") or "")
        image_id = str(payload.get("id") or "")
        if not created_at or not image_id:
            raise GalleryCursorError("invalid gallery cursor")
        return created_at, image_id
    except GalleryCursorError:
        raise
    except Exception as exc:
        raise GalleryCursorError("invalid gallery cursor") from exc


def build_gallery_fts_query(value: Any) -> str:
    terms = [term for term in re.split(r"[^\w]+", str(value or "").lower(), flags=re.UNICODE) if term]
    return " AND ".join(f'"{term}"*' for term in terms[:12])
