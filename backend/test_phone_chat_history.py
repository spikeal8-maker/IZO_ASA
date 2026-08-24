from __future__ import annotations

import sqlite3

from app.database.migrations import apply_phone_chat_history_migration
from app.services import phone_chat_history


def _database() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    apply_phone_chat_history_migration(conn, applied_at="2026-08-24T00:00:00+00:00")
    return conn


def test_chat_threads_are_owned_persisted_and_deleted_with_messages() -> None:
    conn = _database()
    thread = phone_chat_history.create_thread(conn, "user-1", title="Погода", context_chars=60000)
    phone_chat_history.add_exchange(
        conn, "user-1", thread["id"], user_content="Какая погода?",
        assistant_content="Сейчас +19 °C.", provider="local", model="local:izo-chat",
        tools=[{"name": "web_search", "sources": []}], charged_tokens=1, token_kind="daily",
    )

    assert phone_chat_history.get_thread(conn, "user-2", thread["id"]) is None
    assert [message["role"] for message in phone_chat_history.list_messages(conn, "user-1", thread["id"])] == ["user", "assistant"]
    assert phone_chat_history.delete_thread(conn, "user-1", thread["id"]) is True
    assert conn.execute("SELECT COUNT(*) FROM phone_chat_messages").fetchone()[0] == 0


def test_context_history_is_bounded_from_the_newest_messages() -> None:
    conn = _database()
    thread = phone_chat_history.create_thread(conn, "user-1", context_chars=4000)
    for number in range(3):
        phone_chat_history.add_exchange(
            conn, "user-1", thread["id"], user_content=f"Вопрос {number} " + "а" * 900,
            assistant_content=f"Ответ {number} " + "б" * 900, provider="local", model="local:izo-chat",
            tools=[], charged_tokens=1, token_kind="daily",
        )

    history = phone_chat_history.bounded_history(conn, "user-1", thread["id"], 4000)
    assert history[-1]["content"].startswith("Ответ 2")
    assert sum(len(item["content"]) for item in history) <= 4000
    assert not any(item["content"].startswith("Вопрос 0") for item in history)
