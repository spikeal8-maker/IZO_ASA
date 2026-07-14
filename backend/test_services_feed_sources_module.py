from __future__ import annotations

import inspect
from typing import Any

import app.services.feed_sources as feed_sources_module
from app.services.feed_sources import feed_source_history_payload


class RecordingConnection:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    def execute(self, sql: str, parameters: tuple[object, ...]) -> "RecordingConnection":
        self.calls.append((" ".join(sql.split()), parameters))
        return self

    def fetchall(self) -> list[dict[str, Any]]:
        return self.rows


def test_feed_sources_module_is_import_safe() -> None:
    source = inspect.getsource(feed_sources_module).lower()

    for forbidden in ("import main", "fastapi", "pydantic", "sqlite3", "pathlib", "httpx", "os.environ"):
        assert forbidden not in source


def test_feed_source_history_preserves_query_and_mapping() -> None:
    events: list[tuple[object, ...]] = []
    connection = RecordingConnection(
        [
            {
                "source_kind": "image",
                "role": "subject",
                "slot_index": "3",
                "thumb_url": "thumb",
                "thumb_width": "80",
                "thumb_height": 40,
                "children_json": "raw",
            }
        ]
    )

    result = feed_source_history_payload(
        connection,
        "img",
        load_children=lambda raw: events.append(("json", raw)) or [{"id": "child"}],
        row_get=lambda row, key: events.append(("row_get", key)) or row.get(key),
        role_label=lambda role, index: events.append(("role_label", role, index)) or "Label",
    )

    assert connection.calls == [
        (
            "SELECT source_kind, role, slot_index, thumb_url, thumb_width, thumb_height, children_json "
            "FROM image_sources WHERE image_id = ? ORDER BY slot_index ASC, created_at ASC",
            ("img",),
        )
    ]
    assert result == [
        {
            "kind": "image",
            "role": "subject",
            "roleLabel": "Label",
            "slotIndex": 3,
            "thumbUrl": "thumb",
            "width": 80,
            "height": 40,
            "children": [{"id": "child"}],
        }
    ]
    assert [event[0] for event in events] == [
        "row_get",
        "json",
        "row_get",
        "row_get",
        "row_get",
        "row_get",
        "role_label",
        "row_get",
        "row_get",
        "row_get",
        "row_get",
    ]


def test_feed_source_history_short_circuits_empty_image_id() -> None:
    class FailingConnection:
        def execute(self, sql: str, parameters: tuple[object, ...]) -> None:
            raise AssertionError("database must not be queried")

    fail = lambda *args: (_ for _ in ()).throw(AssertionError(args))

    assert feed_source_history_payload(
        FailingConnection(),
        None,
        load_children=fail,
        row_get=fail,
        role_label=fail,
    ) == []
