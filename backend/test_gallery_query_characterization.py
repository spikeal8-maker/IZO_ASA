from __future__ import annotations

import base64
import json

import pytest
from fastapi import HTTPException

import main


def encoded_json(value) -> str:
    raw = json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def test_gallery_cursor_roundtrip_preserves_unicode_and_omits_padding() -> None:
    row = {"created_at": "2026-07-14T03:30:00+00:00", "id": "изображение-1"}

    cursor = main.gallery_cursor_from_row(row)

    assert "=" not in cursor
    assert main.parse_gallery_cursor(cursor) == (row["created_at"], row["id"])


@pytest.mark.parametrize("cursor", [None, ""])
def test_empty_gallery_cursor_is_absent(cursor) -> None:
    assert main.parse_gallery_cursor(cursor) is None


@pytest.mark.parametrize("cursor", ["%%%", encoded_json({"created_at": "x"}), encoded_json({"id": "y"}), encoded_json({})])
def test_malformed_or_incomplete_cursor_maps_to_exact_http_400(cursor: str) -> None:
    with pytest.raises(HTTPException) as caught:
        main.parse_gallery_cursor(cursor)

    assert caught.value.status_code == 400
    assert caught.value.detail == "invalid gallery cursor"


@pytest.mark.parametrize("payload", [[], "text", 42, None])
def test_valid_json_non_object_cursor_maps_to_http_400(payload) -> None:
    with pytest.raises(HTTPException) as caught:
        main.parse_gallery_cursor(encoded_json(payload))

    assert caught.value.status_code == 400
    assert caught.value.detail == "invalid gallery cursor"


def test_gallery_fts_query_preserves_legacy_unicode_terms_and_duplicates() -> None:
    assert main.gallery_fts_query("  Маяк, blue-blue 42 BLUE!!! ") == (
        '"маяк"* AND "blue"* AND "blue"* AND "42"* AND "blue"*'
    )
    assert main.gallery_fts_query("") == ""


def test_gallery_fts_query_limits_output_to_first_twelve_terms() -> None:
    value = " ".join(f"term{index}" for index in range(15))

    query = main.gallery_fts_query(value)

    assert query.count(" AND ") == 11
    assert '"term11"*' in query
    assert "term12" not in query
