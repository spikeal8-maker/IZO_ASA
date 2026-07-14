from __future__ import annotations

from typing import Any

import main


class RecordingConnection:
    def __init__(self, rows: list[dict[str, Any]], events: list[tuple[object, ...]]) -> None:
        self.rows = rows
        self.events = events

    def execute(self, sql: str, parameters: tuple[object, ...]) -> "RecordingConnection":
        self.events.append(("execute", " ".join(sql.split()), parameters))
        return self

    def fetchall(self) -> list[dict[str, Any]]:
        self.events.append(("fetchall",))
        return self.rows


def test_feed_source_history_preserves_query_payload_and_callback_order(monkeypatch) -> None:
    events: list[tuple[object, ...]] = []
    rows = [
        {
            "source_kind": "image",
            "role": "subject",
            "slot_index": "2",
            "thumb_url": "/thumb-a.webp",
            "thumb_width": "64",
            "thumb_height": 32,
            "children_json": "children-a",
        },
        {
            "source_kind": "mask",
            "role": None,
            "slot_index": None,
            "thumb_url": None,
            "thumb_width": None,
            "thumb_height": None,
            "children_json": "children-invalid",
        },
    ]
    connection = RecordingConnection(rows, events)
    monkeypatch.setattr(
        main,
        "_row_get",
        lambda row, key: events.append(("row_get", key)) or row.get(key),
    )
    monkeypatch.setattr(
        main,
        "safe_json_load",
        lambda raw: events.append(("json", raw))
        or ([{"id": "child"}] if raw == "children-a" else {"invalid": True}),
    )
    monkeypatch.setattr(
        main,
        "_source_role_label",
        lambda role, index: events.append(("role_label", role, index)) or f"label-{index}",
    )

    result = main._feed_source_history_payload(connection, "img-1")

    assert result == [
        {
            "kind": "image",
            "role": "subject",
            "roleLabel": "label-2",
            "slotIndex": 2,
            "thumbUrl": "/thumb-a.webp",
            "width": 64,
            "height": 32,
            "children": [{"id": "child"}],
        },
        {
            "kind": "mask",
            "role": None,
            "roleLabel": "label-0",
            "slotIndex": 0,
            "thumbUrl": None,
            "width": 0,
            "height": 0,
            "children": [],
        },
    ]
    assert events == [
        (
            "execute",
            "SELECT source_kind, role, slot_index, thumb_url, thumb_width, thumb_height, children_json "
            "FROM image_sources WHERE image_id = ? ORDER BY slot_index ASC, created_at ASC",
            ("img-1",),
        ),
        ("fetchall",),
        ("row_get", "children_json"),
        ("json", "children-a"),
        ("row_get", "source_kind"),
        ("row_get", "role"),
        ("row_get", "role"),
        ("row_get", "slot_index"),
        ("role_label", "subject", 2),
        ("row_get", "slot_index"),
        ("row_get", "thumb_url"),
        ("row_get", "thumb_width"),
        ("row_get", "thumb_height"),
        ("row_get", "children_json"),
        ("json", "children-invalid"),
        ("row_get", "source_kind"),
        ("row_get", "role"),
        ("row_get", "role"),
        ("row_get", "slot_index"),
        ("role_label", None, 0),
        ("row_get", "slot_index"),
        ("row_get", "thumb_url"),
        ("row_get", "thumb_width"),
        ("row_get", "thumb_height"),
    ]


def test_feed_source_history_empty_id_short_circuits_without_dependencies(monkeypatch) -> None:
    class FailingConnection:
        def execute(self, sql: str, parameters: tuple[object, ...]) -> None:
            raise AssertionError("database must not be queried")

    monkeypatch.setattr(main, "_row_get", lambda row, key: (_ for _ in ()).throw(AssertionError(key)))
    monkeypatch.setattr(main, "safe_json_load", lambda raw: (_ for _ in ()).throw(AssertionError(raw)))
    monkeypatch.setattr(
        main,
        "_source_role_label",
        lambda role, index: (_ for _ in ()).throw(AssertionError((role, index))),
    )

    assert main._feed_source_history_payload(FailingConnection(), None) == []
    assert main._feed_source_history_payload(FailingConnection(), "") == []
