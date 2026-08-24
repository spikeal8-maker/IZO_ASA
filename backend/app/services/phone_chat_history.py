"""Durable, bounded phone-chat threads owned by a legacy product user."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _thread(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "title": row["title"],
        "chatModelId": row["chat_model_id"],
        "imageModelId": row["image_model_id"],
        "videoModelId": row["video_model_id"],
        "contextChars": int(row["context_chars"] or 60000),
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


def _public_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for source in tools[:8]:
        if not isinstance(source, dict):
            continue
        name = str(source.get("name") or "")
        if name not in {"web_search", "generate_image"}:
            continue
        item: dict[str, Any] = {"name": name}
        if name == "generate_image":
            status = str(source.get("status") or "requested")
            item["status"] = status if status in {"requested", "running", "done", "error"} else "requested"
            item["prompt"] = str(source.get("prompt") or "")[:3000]
            item["aspectRatio"] = str(source.get("aspectRatio") or "1:1")[:10]
            item["jobId"] = str(source.get("jobId") or "")[:100]
            result_url = str(source.get("resultUrl") or "")[:2000]
            if result_url.startswith("/api/"):
                item["resultUrl"] = result_url
            if source.get("error"):
                item["error"] = str(source.get("error"))[:500]
        else:
            item["ok"] = bool(source.get("ok"))
            item["query"] = str(source.get("query") or "")[:500]
            sources = source.get("sources") if isinstance(source.get("sources"), list) else []
            item["sources"] = [
                {"title": str(value.get("title") or "")[:240], "url": str(value.get("url") or "")[:2000]}
                for value in sources[:8] if isinstance(value, dict) and str(value.get("url") or "").startswith(("https://", "http://"))
            ]
        output.append(item)
    return output


def _tools_from_json(value: Any) -> list[dict[str, Any]]:
    try:
        parsed = json.loads(str(value or "[]"))
    except (json.JSONDecodeError, TypeError):
        return []
    return _public_tools(parsed) if isinstance(parsed, list) else []


def list_threads(conn: sqlite3.Connection, user_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM phone_chat_threads WHERE user_id=? ORDER BY updated_at DESC LIMIT 50",
        (user_id,),
    ).fetchall()
    return [_thread(row) for row in rows]


def create_thread(
    conn: sqlite3.Connection,
    user_id: str,
    *,
    title: str = "Новый чат",
    chat_model_id: str = "local:izo-chat",
    image_model_id: str | None = None,
    video_model_id: str | None = None,
    context_chars: int = 60000,
) -> dict[str, Any]:
    now = _now()
    thread_id = uuid.uuid4().hex
    conn.execute(
        "INSERT INTO phone_chat_threads (id,user_id,title,chat_model_id,image_model_id,video_model_id,context_chars,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (
            thread_id, user_id, (title.strip() or "Новый чат")[:80], chat_model_id[:200],
            (image_model_id or None), (video_model_id or None), max(4000, min(240000, int(context_chars))), now, now,
        ),
    )
    row = conn.execute("SELECT * FROM phone_chat_threads WHERE id=?", (thread_id,)).fetchone()
    return _thread(row)


def get_thread(conn: sqlite3.Connection, user_id: str, thread_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM phone_chat_threads WHERE id=? AND user_id=?",
        (thread_id, user_id),
    ).fetchone()
    return _thread(row) if row else None


def update_thread(conn: sqlite3.Connection, user_id: str, thread_id: str, values: dict[str, Any]) -> dict[str, Any] | None:
    allowed = {
        "title": ("title", lambda value: (str(value).strip() or "Новый чат")[:80]),
        "chatModelId": ("chat_model_id", lambda value: str(value)[:200]),
        "imageModelId": ("image_model_id", lambda value: str(value)[:200] if value else None),
        "videoModelId": ("video_model_id", lambda value: str(value)[:200] if value else None),
        "contextChars": ("context_chars", lambda value: max(4000, min(240000, int(value)))),
    }
    assignments: list[str] = []
    params: list[Any] = []
    for key, value in values.items():
        if key in allowed:
            column, normalize = allowed[key]
            assignments.append(f"{column}=?")
            params.append(normalize(value))
    if assignments:
        assignments.append("updated_at=?")
        params.extend([_now(), thread_id, user_id])
        conn.execute(
            f"UPDATE phone_chat_threads SET {', '.join(assignments)} WHERE id=? AND user_id=?",
            params,
        )
    return get_thread(conn, user_id, thread_id)


def delete_thread(conn: sqlite3.Connection, user_id: str, thread_id: str) -> bool:
    cursor = conn.execute("DELETE FROM phone_chat_threads WHERE id=? AND user_id=?", (thread_id, user_id))
    return cursor.rowcount > 0


def list_messages(conn: sqlite3.Connection, user_id: str, thread_id: str, *, limit: int = 200) -> list[dict[str, Any]]:
    if get_thread(conn, user_id, thread_id) is None:
        return []
    rows = conn.execute(
        "SELECT * FROM phone_chat_messages WHERE thread_id=? ORDER BY created_at,rowid LIMIT ?",
        (thread_id, max(1, min(500, int(limit)))),
    ).fetchall()
    return [{
        "id": row["id"], "role": row["role"], "content": row["content"],
        "provider": row["provider"] or "", "model": row["model"] or "",
        "tools": _tools_from_json(row["tools_json"]),
        "chargedTokens": int(row["charged_tokens"] or 0), "tokenKind": row["token_kind"] or "",
        "createdAt": row["created_at"], "status": "done",
    } for row in rows]


def bounded_history(conn: sqlite3.Connection, user_id: str, thread_id: str, context_chars: int) -> list[dict[str, str]]:
    messages = list_messages(conn, user_id, thread_id, limit=500)
    remaining = max(4000, min(240000, int(context_chars)))
    selected: list[dict[str, str]] = []
    for item in reversed(messages):
        content = str(item["content"]).strip()
        if not content:
            continue
        if selected and len(content) > remaining:
            break
        selected.append({"role": item["role"], "content": content[-remaining:]})
        remaining -= min(remaining, len(content))
        if remaining <= 0:
            break
    return list(reversed(selected))


def add_exchange(
    conn: sqlite3.Connection,
    user_id: str,
    thread_id: str,
    *,
    user_content: str,
    assistant_content: str,
    provider: str,
    model: str,
    tools: list[dict[str, Any]],
    charged_tokens: int,
    token_kind: str,
) -> dict[str, str]:
    if get_thread(conn, user_id, thread_id) is None:
        raise KeyError("thread_not_found")
    now = _now()
    user_message_id = uuid.uuid4().hex
    assistant_message_id = uuid.uuid4().hex
    conn.execute(
        "INSERT INTO phone_chat_messages (id,thread_id,role,content,created_at) VALUES (?,?,?,?,?)",
        (user_message_id, thread_id, "user", user_content[:8000], now),
    )
    conn.execute(
        "INSERT INTO phone_chat_messages (id,thread_id,role,content,provider,model,tools_json,charged_tokens,token_kind,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (assistant_message_id, thread_id, "assistant", assistant_content[:12000], provider, model, json.dumps(_public_tools(tools), ensure_ascii=False), charged_tokens, token_kind, now),
    )
    conn.execute("UPDATE phone_chat_threads SET updated_at=? WHERE id=? AND user_id=?", (now, thread_id, user_id))
    return {"userMessageId": user_message_id, "assistantMessageId": assistant_message_id}


def update_message_tools(
    conn: sqlite3.Connection,
    user_id: str,
    thread_id: str,
    message_id: str,
    tools: list[dict[str, Any]],
) -> bool:
    cursor = conn.execute(
        "UPDATE phone_chat_messages SET tools_json=? WHERE id=? AND thread_id=? AND role='assistant' AND EXISTS (SELECT 1 FROM phone_chat_threads WHERE id=? AND user_id=?)",
        (json.dumps(_public_tools(tools), ensure_ascii=False), message_id, thread_id, thread_id, user_id),
    )
    return cursor.rowcount > 0
