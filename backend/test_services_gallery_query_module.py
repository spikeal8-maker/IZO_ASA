from __future__ import annotations

import base64
import inspect
import json

import pytest

import app.services.gallery_query as gallery_query_module
from app.services.gallery_query import (
    GalleryCursorError,
    build_gallery_fts_query,
    decode_gallery_cursor,
    encode_gallery_cursor,
)


def encoded_json(value) -> str:
    raw = json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def test_gallery_query_module_is_import_safe_and_framework_database_free() -> None:
    source = inspect.getsource(gallery_query_module).lower()

    for forbidden in ("import main", "fastapi", "pydantic", "sqlite3", "pathlib", "httpx", "os.environ"):
        assert forbidden not in source


def test_cursor_encode_decode_roundtrip_preserves_exact_legacy_json_shape() -> None:
    created_at = "2026-07-14T03:30:00+00:00"
    image_id = "изображение-1"

    cursor = encode_gallery_cursor(created_at, image_id)
    padded = cursor + ("=" * (-len(cursor) % 4))
    payload = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))

    assert payload == {"created_at": created_at, "id": image_id}
    assert "=" not in cursor
    assert decode_gallery_cursor(cursor) == (created_at, image_id)


@pytest.mark.parametrize("cursor", [None, ""])
def test_empty_cursor_decodes_to_none(cursor) -> None:
    assert decode_gallery_cursor(cursor) is None


@pytest.mark.parametrize(
    "cursor",
    ["%%%", encoded_json({}), encoded_json({"created_at": "x"}), encoded_json({"id": "y"})],
)
def test_invalid_or_incomplete_cursor_raises_typed_error(cursor: str) -> None:
    with pytest.raises(GalleryCursorError, match="invalid gallery cursor"):
        decode_gallery_cursor(cursor)


@pytest.mark.parametrize("payload", [[], "text", 42, None])
def test_valid_json_non_object_cursor_raises_typed_error(payload) -> None:
    with pytest.raises(GalleryCursorError, match="invalid gallery cursor"):
        decode_gallery_cursor(encoded_json(payload))


def test_fts_builder_preserves_unicode_duplicates_and_legacy_value_coercion() -> None:
    assert build_gallery_fts_query("  Маяк, blue-blue 42 BLUE!!! ") == (
        '"маяк"* AND "blue"* AND "blue"* AND "42"* AND "blue"*'
    )
    assert build_gallery_fts_query(None) == ""
    assert build_gallery_fts_query(123) == '"123"*'


def test_fts_builder_limits_output_to_twelve_terms() -> None:
    query = build_gallery_fts_query(" ".join(f"term{index}" for index in range(15)))

    assert query.count(" AND ") == 11
    assert query.endswith('"term11"*')
