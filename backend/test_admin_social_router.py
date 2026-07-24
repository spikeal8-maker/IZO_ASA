from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routers.admin_operations import (
    AdminOperationsDependencies,
    create_admin_operations_router,
)


def test_social_status_and_master_enable_are_fail_closed(tmp_path) -> None:
    database_path = tmp_path / "admin-social.sqlite3"
    conn = sqlite3.connect(database_path)
    conn.executescript(
        """
        CREATE TABLE admin_settings (
            key TEXT PRIMARY KEY, value_json TEXT NOT NULL, updated_at TEXT
        );
        CREATE TABLE social_delivery_outbox (
            id TEXT PRIMARY KEY, network TEXT, status TEXT, sent_at TEXT
        );
        """
    )
    initial = {
        "masterEnabled": False,
        "autoPublish": True,
        "networks": {
            "telegram": {
                "enabled": True,
                "verified": True,
                "targetId": "@channel",
            }
        },
    }
    conn.execute(
        "INSERT INTO admin_settings (key, value_json) VALUES (?, ?)",
        ("social_syndication", json.dumps(initial)),
    )
    conn.commit()
    conn.close()
    secrets: dict[str, str] = {}

    @contextmanager
    def database():
        current = sqlite3.connect(database_path)
        current.row_factory = sqlite3.Row
        try:
            yield current
            current.commit()
        finally:
            current.close()

    def saved_setting(key: str):
        with database() as current:
            row = current.execute(
                "SELECT value_json FROM admin_settings WHERE key=?", (key,)
            ).fetchone()
        return json.loads(row["value_json"]) if row else {}

    def save_setting(key: str, value):
        with database() as current:
            current.execute(
                "INSERT INTO admin_settings (key, value_json) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
                (key, json.dumps(value)),
            )

    app = FastAPI()
    app.include_router(
        create_admin_operations_router(
            AdminOperationsDependencies(
                db=database,
                require_admin=lambda _request: {"internal_user_id": "admin"},
                saved_setting=saved_setting,
                save_setting=save_setting,
                record_audit=lambda *_args, **_kwargs: None,
                secret_exists=lambda name: bool(secrets.get(name)),
                secret_get=lambda name: secrets.get(name, ""),
                secret_set=lambda name, value: secrets.__setitem__(name, value),
                secret_delete=lambda name: secrets.pop(name, None) is not None,
                probe_social=lambda *_args, **_kwargs: None,
                social_worker_status=lambda: {
                    "running": True,
                    "lastSuccessAt": None,
                    "lastErrorAt": None,
                    "lastError": None,
                },
            )
        )
    )
    client = TestClient(app)

    status = client.get("/api/admin/social-v2")
    assert status.status_code == 200
    assert status.json()["operational"] is False
    assert status.json()["worker"]["running"] is True

    enable = {**initial, "masterEnabled": True}
    refused = client.put(
        "/api/admin/social-v2", json={"settings": enable}
    )
    assert refused.status_code == 400
    assert saved_setting("social_syndication")["masterEnabled"] is False

    secrets["social_telegram_access_token"] = "not-a-real-provider-token"
    accepted = client.put(
        "/api/admin/social-v2", json={"settings": enable}
    )
    assert accepted.status_code == 200
    assert accepted.json()["operational"] is True
    assert saved_setting("social_syndication")["masterEnabled"] is True

    changed_target = {
        **enable,
        "networks": {
            **enable["networks"],
            "telegram": {
                **enable["networks"]["telegram"],
                "targetId": "@different_channel",
            },
        },
    }
    refused_changed_target = client.put(
        "/api/admin/social-v2", json={"settings": changed_target}
    )
    assert refused_changed_target.status_code == 400
